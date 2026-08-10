# -*- coding: utf-8 -*-
"""garch_spike_cv.py — 변동성 큰 품목(대파·수박)의 폭등확률에 GARCH 조건부 변동성 적용 실험.

배경: 현재 폭등확률(models.fit_spike_model)은 로그잔차 σ를 상수로 두는 등분산 가정.
KREI 최병옥·최익창(2007)은 ARCH 효과가 있는 품목(변동성 군집)에서 GARCH가 우세함을
보였다. 우리 CV에서 대파(MAPE 39%)·수박이 가장 불안정한 품목 → 이들에서 σ를
GARCH(1,1) 조건부 변동성으로 바꾸면 폭등확률 보정(Brier score)이 좋아지는지 검증.

설계:
- 시계열: 작물별 전북 전체(시군 물량가중 집계, jeonbuk_origin_top10crops_by_county.csv)
- 점예측: 로그+Ridge(alpha=10)+계절평균 30% 블렌딩 — 등분산/GARCH 둘 다 동일한
  점예측을 공유하므로 차이는 순수하게 σ 모델링에서만 나옴
- walk-forward: 2022~2025 각 연도를 테스트로, 그 이전 전체로 학습
- 폭등 정의: 학습기간 가격 상위 20% 문턱(threshold) 초과 (기존과 동일)
- GARCH: 학습 잔차로 GARCH(1,1) 적합 → 테스트 구간은 실현 잔차로 1-step 재귀 갱신
- 평가: Brier score (낮을수록 좋음), 대조군: 고정σ(현행), 컨트롤 작물: 고구마(안정)
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.linear_model import Ridge

warnings.filterwarnings("ignore")

TOP10_PATH = "../data/raw/jeonbuk_origin_top10crops_by_county.csv"
CROPS = ["greenonion", "watermelon", "sweetpotato"]  # 불안정 2 + 안정 대조 1
TEST_YEARS = [2022, 2023, 2024, 2025]
SPIKE_Q = 0.80


def build_crop_series(crop_id: str) -> pd.DataFrame:
    long = pd.read_csv(TOP10_PATH, encoding="utf-8-sig")
    long = long[long["crop_id"] == crop_id].copy()
    long["ym"] = pd.PeriodIndex(long["ym"], freq="M")

    def _w(g):
        tq = g["qty_total"].sum()
        return (g["price_avg"] * g["qty_total"]).sum() / tq if tq else np.nan

    s = long.groupby("ym").apply(_w, include_groups=False).rename("price")
    q = long.groupby("ym")["qty_total"].sum().rename("qty")
    df = pd.concat([s, q], axis=1).reset_index()
    df = df.set_index("ym").resample("M").asfreq().reset_index()  # 결측월 명시화
    m = df["ym"].dt.month
    df["month_sin"] = np.sin(2 * np.pi * m / 12)
    df["month_cos"] = np.cos(2 * np.pi * m / 12)
    df["lag1"] = df["price"].shift(1)
    df["lag12"] = df["price"].shift(12)
    df["roll3"] = df["price"].shift(1).rolling(3).mean()
    df["qty_log"] = np.log1p(df["qty"])
    return df


FEATS = ["month_sin", "month_cos", "lag1", "lag12", "roll3", "qty_log"]


def point_predict(train: pd.DataFrame, test: pd.DataFrame):
    cols = [c for c in FEATS if train[c].notna().any()]
    med = train[cols].median(numeric_only=True)
    Xtr, Xte = train[cols].fillna(med), test[cols].fillna(med)
    model = Ridge(alpha=10.0)
    model.fit(Xtr, np.log(train["price"].values))
    monthly = train.groupby(train["ym"].dt.month)["price"].mean()
    fb = train["price"].mean()

    def blended(X, yms):
        reg = np.exp(model.predict(X))
        base = np.array([monthly.get(t.month, fb) for t in yms])
        return 0.3 * base + 0.7 * reg

    return blended(Xtr, train["ym"]), blended(Xte, test["ym"])


def garch_sigma_path(resid_train: np.ndarray, resid_test: np.ndarray):
    """학습 잔차로 GARCH(1,1) 적합, 테스트는 실현 잔차로 1-step 재귀 σ_t 산출."""
    from arch import arch_model
    am = arch_model(resid_train * 100, mean="Zero", vol="GARCH", p=1, q=1,
                    dist="normal", rescale=False)
    res = am.fit(disp="off")
    om, al, be = (res.params.get("omega", 0.0), res.params.get("alpha[1]", 0.0),
                  res.params.get("beta[1]", 0.0))
    # 학습 마지막 시점의 조건부 분산에서 출발해 실현 잔차로 갱신
    var = float(res.conditional_volatility[-1] ** 2)
    eps_prev = float(resid_train[-1] * 100)
    sigmas = []
    for eps in resid_test:
        var = om + al * eps_prev**2 + be * var  # 1-step ahead 분산
        sigmas.append(np.sqrt(var) / 100)
        eps_prev = eps * 100  # 이번 달 실현 잔차 반영(다음 달 예측에 사용)
    return np.array(sigmas)


def brier(y, p):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def main():
    rows = []
    for crop in CROPS:
        df = build_crop_series(crop)
        y_all, p_fix_all, p_gar_all = [], [], []
        for ty in TEST_YEARS:
            train = df[(df["ym"].dt.year < ty)].dropna(subset=["price"])
            test = df[df["ym"].dt.year == ty].dropna(subset=["price"])
            if len(train) < 30 or test.empty:
                continue
            tr_pred, te_pred = point_predict(train, test)
            thr = np.quantile(train["price"], SPIKE_Q)
            resid_tr = np.log(train["price"].values) - np.log(tr_pred)
            resid_te = np.log(test["price"].values) - np.log(te_pred)
            y = (test["price"].values > thr).astype(int)
            # 현행: 고정 σ
            sd = np.std(resid_tr, ddof=1)
            z = (np.log(thr) - np.log(te_pred)) / sd
            p_fix = 1 - norm.cdf(z)
            # GARCH(1,1) 시변 σ_t
            try:
                sig = garch_sigma_path(resid_tr, resid_te)
                sig = np.clip(sig, sd * 0.3, sd * 3.0)  # 수렴 실패 방어
                zg = (np.log(thr) - np.log(te_pred)) / sig
                p_gar = 1 - norm.cdf(zg)
            except Exception as e:
                print(f"  {crop} {ty}: GARCH 실패 {type(e).__name__} — 고정σ로 대체")
                p_gar = p_fix
            y_all.extend(y); p_fix_all.extend(p_fix); p_gar_all.extend(p_gar)
        n_spike = int(np.sum(y_all))
        b_fix, b_gar = brier(y_all, p_fix_all), brier(y_all, p_gar_all)
        rows.append({"crop": crop, "n_months": len(y_all), "n_spikes": n_spike,
                     "brier_fixed": round(b_fix, 4), "brier_garch": round(b_gar, 4),
                     "garch_better": b_gar < b_fix})
        print(f"{crop:12s} 테스트 {len(y_all)}개월(폭등 {n_spike}회)  "
              f"고정σ Brier={b_fix:.4f}  GARCH Brier={b_gar:.4f}  "
              f"{'GARCH 승' if b_gar < b_fix else '고정σ 승'}", flush=True)

    out = pd.DataFrame(rows)
    out.to_csv("../outputs/garch_spike_cv_results.csv", index=False, encoding="utf-8-sig")
    print("\n저장: ../outputs/garch_spike_cv_results.csv")


if __name__ == "__main__":
    main()
