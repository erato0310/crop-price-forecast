# -*- coding: utf-8 -*-
"""crop_county_forecast.py — 10개 작물 x 14개 시군의 진짜 미래(마지막 실측 ~ 2027-12) 예측.

forecast_future.py(전북 전체 + 상추 시군별)를 작물 축으로 일반화한 것. 방법론 동일:
  1. 미래 달의 외생 피처(강수량/기온/거래물량/공판장가격)는 평년값(그 달의 과거 평균) 대체.
  2. 가격 lag(lag1/lag12/roll3/roll6/roll12)은 직전 예측값을 재귀적으로 먹임 —
     lag12까지 예측값이 되는 13개월째부터 불확실성 누적(lag12_actual=False로 표시).
  3. 폭등확률 + 근사 90% 구간(재귀 단계 sqrt(h)만큼 폭 확대) 동봉.

crop_county_predict.py와 마찬가지로 파라미터는 outputs/crop_county_cv_summary.csv에서
읽는다(alpha/blend/target_source/use_gpj_feature/feature_variant, CV 재실행 시 자동 추종).
reference_mape_pct도 하드코딩 딕셔너리 대신 CV summary의 model_mape를 그대로 쓴다.

학습은 crop_county_cv._add_features/_variant_feats로 CV와 동일하게 구성하고, 미래 행만
같은 컬럼 이름으로 수동 조립한다. 예측값은 cv_eval()과 같은 clip(학습범위 /3~x3) 적용.

**검증 불가능한 순수 forward forecast** — 실적이 나오면 그때 대조할 것.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from backtest import load_panel
from features import build_features
from crop_county_cv import _add_features, _variant_feats
import models as M

OUT_DIR = Path(__file__).resolve().parent.parent / "outputs" / "future_forecast"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CV_SUMMARY_PATH = Path(__file__).resolve().parent.parent / "outputs" / "crop_county_cv_summary.csv"
EXCLUDE_MAPE = 100.0  # crop_county_predict.py와 동일한 제외 기준
HORIZON_END = "2027-12"
Z_90 = 1.645


def load_params() -> pd.DataFrame:
    cv = pd.read_csv(CV_SUMMARY_PATH)
    return cv[(~cv["skipped"]) & (cv["model_mape"] < EXCLUDE_MAPE)].copy()


def _climatology(frame: pd.DataFrame, col: str) -> pd.Series:
    if col not in frame.columns or frame[col].notna().sum() == 0:
        return pd.Series(dtype=float)
    return frame.groupby(frame["ym"].dt.month)[col].mean()


def forecast_combo(df: pd.DataFrame, row: pd.Series,
                   horizon_end: str = HORIZON_END) -> pd.DataFrame | None:
    crop_id, county_id = row["crop_id"], row["county_id"]
    target_source = row["target_source"]
    alpha, blend_w = float(row["best_alpha"]), float(row["best_blend_w"])
    use_gpj = bool(row["use_gpj_feature"]) if pd.notna(row["use_gpj_feature"]) else False
    variant = row["feature_variant"] if isinstance(row["feature_variant"], str) else ""

    df2, target, feats, extra = _add_features(df, crop_id, county_id, target_source)
    if not feats or target not in df2.columns:
        return None
    cur_feats = feats + (extra if (use_gpj and extra) else [])
    if variant:
        df2, cur_feats, _ = _variant_feats(df2, crop_id, target, cur_feats)

    train = df2.dropna(subset=[target])
    if len(train) < 12:
        return None
    last_actual_ym = train["ym"].max()

    cols = [c for c in cur_feats if c in train.columns and train[c].notna().any()]
    Xtr = train[cols].fillna(train[cols].median(numeric_only=True))
    model = Ridge(alpha=alpha)
    model.fit(Xtr, np.log(train[target].values))
    train_medians = train[cols].median(numeric_only=True)
    clip_lo, clip_hi = train[target].min() / 3.0, train[target].max() * 3.0

    monthly_avg = train.groupby(train["ym"].dt.month)[target].mean()
    fallback_avg = train[target].mean()

    prefix = "origin" if target_source == "origin" else "gpj"
    qty_col = f"qty_total_{prefix}_{crop_id}_{county_id}"
    gpj_price_col = f"price_avg_gpj_{crop_id}_{county_id}"
    rain_clim = _climatology(train, "rain_sum")
    tavg_clim = _climatology(train, "tavg")
    qty_clim = _climatology(train, qty_col)
    gpj_clim = _climatology(df2, gpj_price_col)  # 보조피처는 전 기간 평년값이면 충분

    series: dict[pd.Period, float] = dict(zip(train["ym"], train[target]))

    # in-sample 블렌딩 예측 잔차로 폭등모델 학습 (forecast_future.py와 동일 절차)
    reg_tr = np.clip(np.exp(model.predict(Xtr)), clip_lo, clip_hi)
    baseline_tr = np.array([monthly_avg.get(m.month, fallback_avg) for m in train["ym"]])
    blend_tr = blend_w * baseline_tr + (1 - blend_w) * reg_tr
    spike_params = M.fit_spike_model(train[target].values, blend_tr)

    def _roll(ym: pd.Period, k: int) -> float:
        vals = [series.get(ym - i) for i in range(1, k + 1)]
        vals = [v for v in vals if v is not None]
        return float(np.mean(vals)) if vals else np.nan

    rows = []
    for ym in pd.period_range(start=last_actual_ym + 1, end=horizon_end, freq="M"):
        row_vals = {
            "month_sin": np.sin(2 * np.pi * ym.month / 12),
            "month_cos": np.cos(2 * np.pi * ym.month / 12),
            f"{target}_lag1": series.get(ym - 1),
            f"{target}_lag12": series.get(ym - 12),
            f"{target}_roll3": _roll(ym, 3),
            f"{target}_roll6": _roll(ym, 6),
            f"{target}_roll12": _roll(ym, 12),  # storable 변형 조합만 cols에 있음
            "rain_sum": rain_clim.get(ym.month, np.nan) if len(rain_clim) else np.nan,
            "tavg": tavg_clim.get(ym.month, np.nan) if len(tavg_clim) else np.nan,
        }
        qty_val = qty_clim.get(ym.month, np.nan) if len(qty_clim) else np.nan
        row_vals[f"{qty_col}_log"] = np.log1p(qty_val) if pd.notna(qty_val) else np.nan
        row_vals[f"{gpj_price_col}_lag1"] = (
            gpj_clim.get((ym - 1).month, np.nan) if len(gpj_clim) else np.nan)

        x_row = pd.DataFrame([row_vals]).reindex(columns=cols).fillna(train_medians)
        reg_pred = float(np.clip(np.exp(model.predict(x_row))[0], clip_lo, clip_hi))
        baseline_pred = monthly_avg.get(ym.month, fallback_avg)
        pred = blend_w * baseline_pred + (1 - blend_w) * reg_pred

        spike_prob = float(M.predict_spike_prob(np.array([pred]), spike_params)[0])
        months_out = (ym - last_actual_ym).n
        widened_std = spike_params["resid_std"] * np.sqrt(months_out)
        rows.append({
            "crop_id": crop_id, "county_id": county_id, "target_source": target_source,
            "ym": str(ym), "forecast_price": pred,
            "pred_lower_90": pred * float(np.exp(-Z_90 * widened_std)),
            "pred_upper_90": pred * float(np.exp(Z_90 * widened_std)),
            "reference_mape_pct": float(row["model_mape"]),
            "spike_prob": spike_prob, "spike_threshold": spike_params["threshold"],
            "lag1_actual": (ym - 1) <= last_actual_ym,
            "lag12_actual": (ym - 12) <= last_actual_ym,
            "months_beyond_actual": months_out,
        })
        series[ym] = pred

    return pd.DataFrame(rows)


def main():
    params = load_params()
    print(f"미래 예측 대상 조합: {len(params)}개 (~{HORIZON_END})")
    df = build_features(load_panel())

    all_fc = []
    for _, row in params.iterrows():
        fc = forecast_combo(df, row)
        if fc is None or fc.empty:
            print(f"{row['crop_id']} x {row['county_id']}: 실측 부족으로 스킵")
            continue
        all_fc.append(fc)

    combined = pd.concat(all_fc, ignore_index=True)
    out_path = OUT_DIR / "crop_county_future_forecast.csv"
    combined.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"저장 완료: {out_path} ({len(combined)}행, {len(all_fc)}개 조합)")

    # 요약: 조합별 첫 6개월 평균 예측가와 최대 폭등확률
    head6 = combined[combined["months_beyond_actual"] <= 6]
    g = head6.groupby(["crop_id", "county_id"]).agg(
        avg_price_6m=("forecast_price", "mean"),
        max_spike_prob_6m=("spike_prob", "max"),
        ref_mape=("reference_mape_pct", "first"),
    ).round(1).sort_values(["crop_id", "avg_price_6m"])
    print("\n=== 조합별 향후 6개월 요약 ===")
    print(g.to_string())


if __name__ == "__main__":
    main()
