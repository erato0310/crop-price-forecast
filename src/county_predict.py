# -*- coding: utf-8 -*-
"""county_predict.py — 전북 시군별(산지 기준) 상추 가격 실제 예측 + 폭등확률.

county_cv.py로 시군별 최적 (alpha, blend_w)를 찾아둔 걸 그대로 써서(COUNTY_PARAMS),
각 시군마다 backtest.py(2025 검증)/predict_2026.py(2026 실적대조)와 동일한 걸 만든다.
데이터가 너무 얇은 4개 시군(부안·임실·정읍·군산, county_cv.py에서 40개월 미만으로 스킵)은
여기서도 제외한다 — 억지로 예측해봐야 신뢰 못할 숫자만 나온다.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from backtest import load_panel, mape
from features import build_features
from build_dataset import COUNTY_NAME_TO_ID
import models as M

OUT_DIR = Path(__file__).resolve().parent.parent / "outputs" / "county_predictions"
OUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_FEATS = ["month_sin", "month_cos"]

# county_cv.py 실행 결과(2026-08) 그대로 — 40개월 미만(부안·임실·정읍·군산)은 제외.
COUNTY_PARAMS = {
    "iksan":    {"alpha": 10.0,  "blend_w": 0.5},
    "jangsu":   {"alpha": 100.0, "blend_w": 0.3},
    "wanju":    {"alpha": 100.0, "blend_w": 0.2},
    "namwon":   {"alpha": 100.0, "blend_w": 0.5},
    "sunchang": {"alpha": 50.0,  "blend_w": 0.3},
    "jeonju":   {"alpha": 50.0,  "blend_w": 0.4},
    "gimje":    {"alpha": 50.0,  "blend_w": 0.2},
    "jinan":    {"alpha": 0.5,   "blend_w": 0.6},
    "gochang":  {"alpha": 100.0, "blend_w": 0.6},
    "muju":     {"alpha": 100.0, "blend_w": 0.0},
}


def _prep(df: pd.DataFrame, county_id: str):
    price_col = f"price_avg_origin_{county_id}"
    qty_col = f"qty_total_origin_{county_id}"
    df = df.copy()
    df[f"{price_col}_lag1"] = df[price_col].shift(1)
    df[f"{price_col}_lag12"] = df[price_col].shift(12)
    df[f"{price_col}_roll3"] = df[price_col].shift(1).rolling(3).mean()
    df[f"{price_col}_roll6"] = df[price_col].shift(1).rolling(6).mean()
    df[f"{qty_col}_log"] = np.log1p(df[qty_col]) if qty_col in df.columns else np.nan
    feats = BASE_FEATS + [f"{price_col}_lag1", f"{price_col}_lag12",
                          f"{price_col}_roll3", f"{price_col}_roll6",
                          "rain_sum", f"{qty_col}_log"]
    return df, price_col, feats


def _seasonal_naive(train, target, target_months):
    monthly_avg = train.groupby(train["ym"].dt.month)[target].mean()
    fallback = train[target].mean()
    return np.array([monthly_avg.get(m.month, fallback) for m in target_months])


def run_county(df: pd.DataFrame, county_id: str, train_end_year: int, test_year: int, label: str):
    df2, target, feats = _prep(df, county_id)
    alpha = COUNTY_PARAMS[county_id]["alpha"]
    blend_w = COUNTY_PARAMS[county_id]["blend_w"]

    train = df2[df2["ym"].dt.year <= train_end_year].dropna(subset=[target])
    test = df2[df2["ym"].dt.year == test_year].dropna(subset=[target])
    if train.empty or test.empty:
        return None

    cols = [c for c in feats if c in train.columns and train[c].notna().any()]
    Xtr = train[cols].fillna(train[cols].median(numeric_only=True))
    Xte = test[cols].fillna(train[cols].median(numeric_only=True))

    model = Ridge(alpha=alpha)
    model.fit(Xtr, np.log(train[target].values))

    reg_pred_test = np.exp(model.predict(Xte))
    reg_pred_train = np.exp(model.predict(Xtr))
    baseline_test = _seasonal_naive(train, target, test["ym"])
    baseline_train = _seasonal_naive(train, target, train["ym"])

    pred_test = blend_w * baseline_test + (1 - blend_w) * reg_pred_test
    pred_train = blend_w * baseline_train + (1 - blend_w) * reg_pred_train

    spike_params = M.fit_spike_model(train[target].values, pred_train)
    spike_prob = M.predict_spike_prob(pred_test, spike_params)
    actual_spike = (test[target].values > spike_params["threshold"]).astype(int)

    result = pd.DataFrame({
        "county_id": county_id, "ym": test["ym"].astype(str),
        "actual": test[target].values,
        "baseline_pred": baseline_test, "model_pred": pred_test,
        "spike_prob": spike_prob, "actual_spike": actual_spike,
    })
    result["baseline_err_pct"] = (result["baseline_pred"] - result["actual"]) / result["actual"] * 100
    result["model_err_pct"] = (result["model_pred"] - result["actual"]) / result["actual"] * 100

    metrics = {
        "county_id": county_id, "label": label, "n_train": len(train), "n_test": len(test),
        "baseline_MAPE": mape(result["actual"], result["baseline_pred"]),
        "model_MAPE": mape(result["actual"], result["model_pred"]),
        "spike_threshold": spike_params["threshold"],
    }
    return result, metrics


def main():
    df = build_features(load_panel())
    all_2025, all_2026 = [], []
    metrics_2025, metrics_2026 = [], []

    for county_id in COUNTY_PARAMS:
        r2025 = run_county(df, county_id, train_end_year=2024, test_year=2025, label="2025검증")
        r2026 = run_county(df, county_id, train_end_year=2025, test_year=2026, label="2026실적대조")
        if r2025:
            all_2025.append(r2025[0]); metrics_2025.append(r2025[1])
        if r2026:
            all_2026.append(r2026[0]); metrics_2026.append(r2026[1])

    combined_2025 = pd.concat(all_2025, ignore_index=True)
    combined_2026 = pd.concat(all_2026, ignore_index=True)
    combined_2025.to_csv(OUT_DIR / "county_backtest_2025.csv", index=False, encoding="utf-8-sig")
    combined_2026.to_csv(OUT_DIR / "county_predict_2026.csv", index=False, encoding="utf-8-sig")

    m2025 = pd.DataFrame(metrics_2025).sort_values("model_MAPE")
    m2026 = pd.DataFrame(metrics_2026).sort_values("model_MAPE")
    m2025.to_csv(OUT_DIR / "county_metrics_2025.csv", index=False, encoding="utf-8-sig")
    m2026.to_csv(OUT_DIR / "county_metrics_2026.csv", index=False, encoding="utf-8-sig")

    print("=" * 78)
    print("2025년 검증 (학습: ~2024-12)")
    print("=" * 78)
    print(m2025.to_string(index=False))

    print("\n" + "=" * 78)
    print("2026년 실적대조 (학습: ~2025-12)")
    print("=" * 78)
    print(m2026.to_string(index=False))

    print(f"\n저장 완료: {OUT_DIR}")


if __name__ == "__main__":
    main()
