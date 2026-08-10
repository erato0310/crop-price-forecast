# -*- coding: utf-8 -*-
"""crop_county_predict.py — 10개 작물 x 전북 14개 시군 실제 예측 산출물 생성.

county_predict.py(상추 전용)를 작물 축으로 일반화한 것. 파라미터를 하드코딩하지 않고
crop_county_cv.py가 저장한 outputs/crop_county_cv_summary.csv에서 조합별 최적
(alpha, blend_w, target_source, use_gpj_feature, feature_variant)을 읽어 쓴다 —
CV를 재실행하면 이 스크립트도 자동으로 새 파라미터를 따라간다.

피처 구성은 crop_county_cv._add_features / _variant_feats를 그대로 임포트해서
CV 때와 예측 때의 입력이 어긋날 여지를 없앴다.

조합별로 backtest.py(2025 검증) / predict_2026.py(2026 실적대조)와 동일한 산출물
+ 폭등확률(models.fit_spike_model)을 만든다.

제외 규칙:
  - CV에서 skipped=True(표본 부족)인 조합
  - CV model_mape >= EXCLUDE_MAPE(기본 100%)인 조합 — 현재 2개가 여기 걸리는데
    둘 다 모델이 아니라 데이터 문제로 진단됨(HANDOFF.md 참고):
    watermelon x buan(통/kg 단위 혼입 의심), greenonion x gimje(실제 가격 파동).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from backtest import load_panel, mape
from features import build_features
from crop_county_cv import _add_features, _variant_feats
import models as M

OUT_DIR = Path(__file__).resolve().parent.parent / "outputs" / "crop_county_predictions"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CV_SUMMARY_PATH = Path(__file__).resolve().parent.parent / "outputs" / "crop_county_cv_summary.csv"
EXCLUDE_MAPE = 100.0  # CV MAPE가 이 이상인 조합은 신뢰 불가로 예측 제외


def load_params() -> pd.DataFrame:
    cv = pd.read_csv(CV_SUMMARY_PATH)
    usable = cv[(~cv["skipped"]) & (cv["model_mape"] < EXCLUDE_MAPE)].copy()
    excluded = cv[(~cv["skipped"]) & (cv["model_mape"] >= EXCLUDE_MAPE)]
    for _, r in excluded.iterrows():
        print(f"[제외] {r['crop_id']} x {r['county_id']}: CV MAPE {r['model_mape']:.0f}% "
              f"(데이터 문제 — HANDOFF.md 참고)")
    return usable


def _seasonal_naive(train: pd.DataFrame, target: str, target_months) -> np.ndarray:
    monthly_avg = train.groupby(train["ym"].dt.month)[target].mean()
    fallback = train[target].mean()
    return np.array([monthly_avg.get(m.month, fallback) for m in target_months])


def run_combo(df: pd.DataFrame, row: pd.Series,
              train_end_year: int, test_year: int, label: str):
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

    train = df2[df2["ym"].dt.year <= train_end_year].dropna(subset=[target])
    test = df2[df2["ym"].dt.year == test_year].dropna(subset=[target])
    if len(train) < 12 or test.empty:
        return None

    cols = [c for c in cur_feats if c in train.columns and train[c].notna().any()]
    Xtr = train[cols].fillna(train[cols].median(numeric_only=True))
    Xte = test[cols].fillna(train[cols].median(numeric_only=True))

    model = Ridge(alpha=alpha)
    model.fit(Xtr, np.log(train[target].values))

    # cv_eval()과 동일한 clip — 학습 범위를 크게 벗어나는 로그공간 외삽 차단
    lo, hi = train[target].min() / 3.0, train[target].max() * 3.0
    reg_pred_test = np.clip(np.exp(model.predict(Xte)), lo, hi)
    reg_pred_train = np.clip(np.exp(model.predict(Xtr)), lo, hi)
    baseline_test = _seasonal_naive(train, target, test["ym"])
    baseline_train = _seasonal_naive(train, target, train["ym"])

    pred_test = blend_w * baseline_test + (1 - blend_w) * reg_pred_test
    pred_train = blend_w * baseline_train + (1 - blend_w) * reg_pred_train

    spike_params = M.fit_spike_model(train[target].values, pred_train)
    spike_prob = M.predict_spike_prob(pred_test, spike_params)
    actual_spike = (test[target].values > spike_params["threshold"]).astype(int)

    result = pd.DataFrame({
        "crop_id": crop_id, "county_id": county_id,
        "target_source": target_source, "ym": test["ym"].astype(str),
        "actual": test[target].values,
        "baseline_pred": baseline_test, "model_pred": pred_test,
        "spike_prob": spike_prob, "actual_spike": actual_spike,
    })
    result["baseline_err_pct"] = (result["baseline_pred"] - result["actual"]) / result["actual"] * 100
    result["model_err_pct"] = (result["model_pred"] - result["actual"]) / result["actual"] * 100

    metrics = {
        "crop_id": crop_id, "county_id": county_id, "label": label,
        "target_source": target_source,
        "n_train": len(train), "n_test": len(test),
        "baseline_MAPE": mape(result["actual"], result["baseline_pred"]),
        "model_MAPE": mape(result["actual"], result["model_pred"]),
        "cv_mape_ref": float(row["model_mape"]),
        "spike_threshold": spike_params["threshold"],
    }
    return result, metrics


def main():
    params = load_params()
    print(f"예측 대상 조합: {len(params)}개")
    df = build_features(load_panel())

    all_2025, all_2026 = [], []
    metrics_2025, metrics_2026 = [], []
    for _, row in params.iterrows():
        r2025 = run_combo(df, row, train_end_year=2024, test_year=2025, label="2025검증")
        r2026 = run_combo(df, row, train_end_year=2025, test_year=2026, label="2026실적대조")
        if r2025:
            all_2025.append(r2025[0]); metrics_2025.append(r2025[1])
        if r2026:
            all_2026.append(r2026[0]); metrics_2026.append(r2026[1])

    pd.concat(all_2025, ignore_index=True).to_csv(
        OUT_DIR / "crop_county_backtest_2025.csv", index=False, encoding="utf-8-sig")
    pd.concat(all_2026, ignore_index=True).to_csv(
        OUT_DIR / "crop_county_predict_2026.csv", index=False, encoding="utf-8-sig")

    m2025 = pd.DataFrame(metrics_2025).sort_values(["crop_id", "model_MAPE"])
    m2026 = pd.DataFrame(metrics_2026).sort_values(["crop_id", "model_MAPE"])
    m2025.to_csv(OUT_DIR / "crop_county_metrics_2025.csv", index=False, encoding="utf-8-sig")
    m2026.to_csv(OUT_DIR / "crop_county_metrics_2026.csv", index=False, encoding="utf-8-sig")

    for label, m in [("2025년 검증 (학습: ~2024-12)", m2025),
                     ("2026년 실적대조 (학습: ~2025-12)", m2026)]:
        print("\n" + "=" * 88)
        print(label)
        print("=" * 88)
        print(m.to_string(index=False))
        print("\n[작물별 요약]")
        g = m.groupby("crop_id").agg(
            n_combos=("county_id", "size"),
            baseline_MAPE=("baseline_MAPE", "mean"),
            model_MAPE=("model_MAPE", "mean"),
        ).sort_values("model_MAPE").round(1)
        print(g.to_string())

    print(f"\n저장 완료: {OUT_DIR}")


if __name__ == "__main__":
    main()
