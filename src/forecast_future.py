# -*- coding: utf-8 -*-
"""forecast_future.py — 실적이 아직 없는 미래(마지막 실측 이후 ~ 2027-12)를 진짜로 예측한다.

지금까지의 backtest.py/predict_2026.py는 전부 "이미 실적이 나온 과거"를 예측해서 정답과
비교하는 검증이었다(그래서 그 달 실측 강수량·거래물량을 그대로 썼다 — README의 반복된
caveat 참고). 여기는 그 caveat이 실제로 적용되는 첫 케이스다:

1. 미래 달의 강수량(rain_sum)·거래물량(qty_log)은 알 수 없으니 **평년값(그 달의 과거
   평균)**으로 대체한다.
2. 미래 달의 가격지연(lag1/lag12/roll3/roll6)은 마지막 실측 이후로는 **직전 달 예측값을
   다음 달 입력으로 재귀적으로** 먹인다. 이 때문에 lag12(12개월 전)가 실측이 아니라
   예측값이 되는 시점(마지막 실측으로부터 13개월째부터)부터 불확실성이 누적된다 —
   출력의 `lag1_actual`/`lag12_actual` 컬럼(True/False)으로 어디부터 그런지 표시한다.
3. 폭등확률(spike_prob)도 같은 방식으로 매달 계산한다.
4. **오차율 추정**: 두 가지를 같이 준다.
   - `reference_mape`: county_cv.py/cross_validate.py로 CV 검증된 "이 지역 모델이 과거
     6년간 보통 이 정도는 틀렸다"는 고정 참고치(1개월 앞만 보는 정상적 조건 기준).
   - `pred_lower_90`/`pred_upper_90`: 로그공간 잔차가 정규분포라는 폭등모델과 같은
     가정으로 만든 근사 90% 구간. **재귀 단계(`months_beyond_actual`)가 늘수록
     `sqrt(months_beyond_actual)`만큼 폭을 넓힌다** — 재귀 예측이 쌓일수록 불확실성이
     커진다는 걸 반영한 대략적 근사치이지, 엄밀하게 오차전파를 계산한 건 아니다
     (선형모델 계수까지 반영한 정확한 전파는 안 함 — 그 정도로 정밀할 필요는 없다고 판단).

**이건 검증이 안 되는 순수 forward forecast다** — 실적이 실제로 나오면
(scrape_jeonbuk_origin.py 재실행 → build_dataset.py 재실행) 그때 대조해봐야 한다.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from backtest import load_panel
from features import build_features
from county_predict import COUNTY_PARAMS
import models as M

OUT_DIR = Path(__file__).resolve().parent.parent / "outputs" / "future_forecast"
OUT_DIR.mkdir(parents=True, exist_ok=True)

HORIZON_END = "2027-12"
BASE_FEATS = ["month_sin", "month_cos"]
Z_90 = 1.645  # 정규분포 90% 양측 구간 z값

# cross_validate.py(전북_전체)/county_cv.py(시군별) 실행 결과(2026-08) 그대로 — CV 평균
# MAPE(walk-forward, 1개월 앞만 보는 정상적 조건 기준). COUNTY_PARAMS와 마찬가지로 CV를
# 다시 돌리면 값이 바뀔 수 있으니 주기적으로 재확인할 것.
ENTITY_CV_MAPE = {
    "전북_전체": 26.64,
    "iksan": 25.57, "jangsu": 26.55, "wanju": 27.99, "namwon": 28.58,
    "sunchang": 29.87, "jeonju": 30.82, "gimje": 36.14, "jinan": 41.90,
    "gochang": 42.59, "muju": 69.85,
}


def _month_sin_cos(month: int) -> tuple[float, float]:
    return np.sin(2 * np.pi * month / 12), np.cos(2 * np.pi * month / 12)


def _climatology(train: pd.DataFrame, col: str) -> pd.Series:
    """월별 평년값(과거 학습기간 그 달들의 평균). 없는 컬럼이면 전부 NaN 시리즈."""
    if col not in train.columns or train[col].notna().sum() == 0:
        return pd.Series(dtype=float)
    return train.groupby(train["ym"].dt.month)[col].mean()


def forecast_entity(df: pd.DataFrame, price_col: str, qty_col: str, alpha: float, blend_w: float,
                     horizon_end: str = HORIZON_END, label: str = "",
                     reference_mape: float | None = None) -> pd.DataFrame | None:
    """price_col을 타깃으로 학습 -> 마지막 실측 다음달부터 horizon_end까지 재귀 예측."""
    d = df.copy()
    d[f"{price_col}_lag1"] = d[price_col].shift(1)
    d[f"{price_col}_lag12"] = d[price_col].shift(12)
    d[f"{price_col}_roll3"] = d[price_col].shift(1).rolling(3).mean()
    d[f"{price_col}_roll6"] = d[price_col].shift(1).rolling(6).mean()
    d[f"{qty_col}_log"] = np.log1p(d[qty_col]) if qty_col in d.columns else np.nan

    feats = BASE_FEATS + [f"{price_col}_lag1", f"{price_col}_lag12",
                          f"{price_col}_roll3", f"{price_col}_roll6",
                          "rain_sum", f"{qty_col}_log"]

    train = d.dropna(subset=[price_col])
    if train.empty:
        return None
    last_actual_ym = train["ym"].max()

    cols = [c for c in feats if c in train.columns and train[c].notna().any()]
    Xtr = train[cols].fillna(train[cols].median(numeric_only=True))
    model = Ridge(alpha=alpha)
    model.fit(Xtr, np.log(train[price_col].values))
    train_medians = train[cols].median(numeric_only=True)

    monthly_avg = train.groupby(train["ym"].dt.month)[price_col].mean()
    fallback_avg = train[price_col].mean()

    rain_clim = _climatology(train, "rain_sum")
    qty_clim = _climatology(train, qty_col)  # 원본 스케일 평년값(로그는 예측 시점에 씀)

    # 재귀용 작업 시리즈: {ym: price}. 처음엔 실측 전체로 채움.
    series: dict[pd.Period, float] = dict(zip(train["ym"], train[price_col]))

    # in-sample 잔차(블렌딩 예측 기준)로 폭등모델 학습 — models.py와 동일 절차.
    Xtr_pred = np.exp(model.predict(Xtr))
    baseline_tr = np.array([monthly_avg.get(m.month, fallback_avg) for m in train["ym"]])
    blend_tr = blend_w * baseline_tr + (1 - blend_w) * Xtr_pred
    spike_params = M.fit_spike_model(train[price_col].values, blend_tr)

    horizon_months = pd.period_range(start=last_actual_ym + 1, end=horizon_end, freq="M")
    rows = []
    for ym in horizon_months:
        m_sin, m_cos = _month_sin_cos(ym.month)
        lag1_ym, lag12_ym = ym - 1, ym - 12
        lag1 = series.get(lag1_ym)
        lag12 = series.get(lag12_ym)
        roll_window = [series.get(ym - k) for k in range(1, 4)]
        roll3 = np.nanmean([v for v in roll_window if v is not None]) if any(v is not None for v in roll_window) else np.nan
        roll_window6 = [series.get(ym - k) for k in range(1, 7)]
        roll6 = np.nanmean([v for v in roll_window6 if v is not None]) if any(v is not None for v in roll_window6) else np.nan

        rain_val = rain_clim.get(ym.month, np.nan) if len(rain_clim) else np.nan
        qty_val = qty_clim.get(ym.month, np.nan) if len(qty_clim) else np.nan
        qty_log_val = np.log1p(qty_val) if pd.notna(qty_val) else np.nan

        row_vals = {
            "month_sin": m_sin, "month_cos": m_cos,
            f"{price_col}_lag1": lag1, f"{price_col}_lag12": lag12,
            f"{price_col}_roll3": roll3, f"{price_col}_roll6": roll6,
            "rain_sum": rain_val, f"{qty_col}_log": qty_log_val,
        }
        x_row = pd.DataFrame([row_vals])[cols].fillna(train_medians)
        reg_pred = float(np.exp(model.predict(x_row))[0])
        baseline_pred = monthly_avg.get(ym.month, fallback_avg)
        pred = blend_w * baseline_pred + (1 - blend_w) * reg_pred

        spike_prob = float(M.predict_spike_prob(np.array([pred]), spike_params)[0])

        months_out = (ym - last_actual_ym).n
        # 재귀 단계가 늘수록 잔차폭을 sqrt(h)로 넓힌다(1단계=순수 1개월 앞 예측이라 배율 1,
        # 그 이후로는 예측이 예측을 낳으니 불확실성이 누적된다는 걸 반영한 근사치).
        widened_std = spike_params["resid_std"] * np.sqrt(months_out)
        pred_lower = pred * float(np.exp(-Z_90 * widened_std))
        pred_upper = pred * float(np.exp(Z_90 * widened_std))

        rows.append({
            "entity": label, "ym": str(ym), "forecast_price": pred,
            "pred_lower_90": pred_lower, "pred_upper_90": pred_upper,
            "reference_mape_pct": reference_mape,
            "spike_prob": spike_prob, "spike_threshold": spike_params["threshold"],
            "lag1_actual": lag1_ym <= last_actual_ym,
            "lag12_actual": lag12_ym <= last_actual_ym,
            "months_beyond_actual": months_out,
        })
        series[ym] = pred  # 다음 달 lag 계산에 이번 예측을 재귀적으로 사용

    return pd.DataFrame(rows)


def main():
    df = build_features(load_panel())

    entities = [("전북_전체", M.TARGET, "qty_total_jeonbuk", M.RIDGE_ALPHA, M.BLEND_WEIGHT)]
    for county_id, params in COUNTY_PARAMS.items():
        entities.append((
            county_id, f"price_avg_origin_{county_id}", f"qty_total_origin_{county_id}",
            params["alpha"], params["blend_w"],
        ))

    all_forecasts = []
    for label, price_col, qty_col, alpha, blend_w in entities:
        result = forecast_entity(df, price_col, qty_col, alpha, blend_w, label=label,
                                  reference_mape=ENTITY_CV_MAPE.get(label))
        if result is None:
            print(f"{label}: 실측 데이터 없어 스킵")
            continue
        all_forecasts.append(result)
        n_recursive = int((~result["lag12_actual"]).sum())
        print(f"{label:12s}: {len(result)}개월 예측 "
              f"(마지막 실측 이후 {result['months_beyond_actual'].max()}개월치, "
              f"lag12까지 예측값으로 재귀된 달 {n_recursive}개월)")

    combined = pd.concat(all_forecasts, ignore_index=True)
    out_path = OUT_DIR / "future_forecast_2026H2_2027.csv"
    combined.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료: {out_path} ({len(combined)}행)")

    print("\n=== 전북_전체 미리보기 ===")
    preview = combined[combined["entity"] == "전북_전체"]
    print(preview.to_string(index=False))


if __name__ == "__main__":
    main()
