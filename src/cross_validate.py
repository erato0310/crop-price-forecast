# -*- coding: utf-8 -*-
"""cross_validate.py — 연도별 walk-forward 교차검증.

backtest.py는 학습 -> 2025 예측 딱 한 번만 본다. 그 한 해에만 맞는 피처를 "최적"으로
잘못 고를 위험이 있어(실제로 한 번 그랬다 — models.py 모듈 docstring 참고), 여러 연도를
각각 테스트로 돌려가며 평균 성능을 보는 스크립트를 별도로 둔다. 새 피처를 추가할지 말지는
backtest.py(2025 단일 홀드아웃)가 아니라 여기 결과로 판단할 것.

타깃이 price_avg_jeonbuk(전북 실제 공판장, 2018-01~)로 바뀌면서 2020~2025 6개 fold를
쓴다(예전 price_avg_garak_seoul은 2021-09~라 2022~2025 4개 fold, 그중 2022는 학습
4개월뿐이라 사실상 노이즈였음 — 지금은 그런 문제 없음).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest import load_panel, mape
from features import build_features
import models as M

TEST_YEARS = [2020, 2021, 2022, 2023, 2024, 2025]


def run_cv(feature_cols: list[str] | None = None, skip_years: tuple[int, ...] = ()):
    """skip_years: 필요하면 학습 데이터가 너무 적은 초반 fold를 평균에서 뺄 때 사용
    (fold별 결과 자체는 출력에 다 나오니 필요하면 직접 봐도 됨)."""
    df = build_features(load_panel())
    rows = []
    for ty in TEST_YEARS:
        train = df[df["ym"].dt.year < ty].dropna(subset=[M.TARGET])
        test = df[df["ym"].dt.year == ty].dropna(subset=[M.TARGET])
        if train.empty or test.empty:
            continue
        baseline_pred = M.seasonal_naive_predict(train, test["ym"])
        model, cols = M.fit_model(train, feature_cols=feature_cols)
        train_medians = train[cols].median(numeric_only=True)
        model_pred = M.predict_blended(train, model, cols, test, train_medians=train_medians)
        rows.append({
            "test_year": ty, "n_train": len(train), "n_test": len(test),
            "baseline_MAE": float(np.mean(np.abs(baseline_pred.values - test[M.TARGET].values))),
            "baseline_MAPE": mape(test[M.TARGET].values, baseline_pred.values),
            "model_MAE": float(np.mean(np.abs(model_pred - test[M.TARGET].values))),
            "model_MAPE": mape(test[M.TARGET].values, model_pred),
        })
    result = pd.DataFrame(rows)
    kept = result[~result["test_year"].isin(skip_years)]
    return result, kept


def main():
    result, kept = run_cv()
    print("=== fold별 결과 ===")
    print(result.to_string(index=False))
    print(f"\n=== 평균({len(kept)}개 fold 기준) ===")
    print(f"  baseline_MAPE 평균: {kept['baseline_MAPE'].mean():.2f}")
    print(f"  model_MAPE 평균:    {kept['model_MAPE'].mean():.2f}")
    print(f"  model_MAPE 범위:    {kept['model_MAPE'].min():.2f} ~ {kept['model_MAPE'].max():.2f}")


if __name__ == "__main__":
    main()
