# -*- coding: utf-8 -*-
"""region_cv.py — 전주·익산·정읍 개별 시장 가격을 각각 타깃으로 삼아 walk-forward CV.

"3개 시장을 합친 price_avg_jeonbuk 하나"가 아니라, 지역마다 실제로 가격이 다를 수 있으니
시장별로 따로 모델을 검증한다. 방법론(로그타깃+Ridge, 계절평균 블렌딩, walk-forward CV)은
models.py/cross_validate.py와 동일하게 맞춰서 결과를 공정하게 비교한다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from backtest import load_panel, mape
from features import build_features

REGIONS = ["jeonju", "iksan", "jeongeup"]
TEST_YEARS = [2020, 2021, 2022, 2023, 2024, 2025]
BASE_FEATS = ["month_sin", "month_cos"]


def _add_region_features(df: pd.DataFrame, region: str) -> tuple[pd.DataFrame, str, list[str]]:
    price_col = f"price_avg_{region}"
    qty_col = f"qty_total_{region}"
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


def cv_eval(df: pd.DataFrame, target: str, feats: list[str], alpha: float, blend_w: float,
            test_years: list[int] = TEST_YEARS, verbose: bool = False):
    fold_mape = {}
    for ty in test_years:
        train = df[df["ym"].dt.year < ty].dropna(subset=[target])
        test = df[df["ym"].dt.year == ty].dropna(subset=[target])
        if train.empty or test.empty:
            continue
        cols = [c for c in feats if c in train.columns and train[c].notna().any()]
        Xtr = train[cols].fillna(train[cols].median(numeric_only=True))
        Xte = test[cols].fillna(train[cols].median(numeric_only=True))
        model = Ridge(alpha=alpha)
        model.fit(Xtr, np.log(train[target].values))
        reg_pred = np.exp(model.predict(Xte))
        if blend_w > 0:
            monthly_avg = train.groupby(train["ym"].dt.month)[target].mean()
            fallback = train[target].mean()
            baseline = np.array([monthly_avg.get(m.month, fallback) for m in test["ym"]])
            pred = blend_w * baseline + (1 - blend_w) * reg_pred
        else:
            pred = reg_pred
        fold_mape[ty] = mape(test[target].values, pred)
        if verbose:
            n_tr = len(train)
            print(f"    [{ty}] train={n_tr:3d}개월  MAPE={fold_mape[ty]:6.2f}")
    if not fold_mape:
        return None, {}
    return float(np.mean(list(fold_mape.values()))), fold_mape


def tune_region(df: pd.DataFrame, region: str, verbose: bool = True):
    df2, target, feats = _add_region_features(df, region)
    if verbose:
        n_obs = df2[target].notna().sum()
        print(f"\n{'='*70}\n{region} ({target}) — 유효 관측 {n_obs}개월\n{'='*70}")

    # 1) 베이스라인
    _, fm_base = cv_eval(df2, target, feats, alpha=1.0, blend_w=1.0)
    avg_base = float(np.mean(list(fm_base.values()))) if fm_base else float("nan")
    if verbose:
        print(f"  베이스라인(계절평균): 평균MAPE={avg_base:.2f}  fold={ {k: round(v,1) for k,v in fm_base.items()} }")

    # 2) alpha 재탐색 (rain+qty_log 포함, blend 없음)
    best_a = None
    for a in [0.5, 1, 2, 3, 5, 10, 20, 30, 50, 100]:
        avg, fm = cv_eval(df2, target, feats, alpha=a, blend_w=0.0)
        if avg is not None and (best_a is None or avg < best_a[1]):
            best_a = (a, avg, fm)
    if verbose and best_a:
        print(f"  최적 alpha={best_a[0]}: 평균MAPE={best_a[1]:.2f}  fold={ {k: round(v,1) for k,v in best_a[2].items()} }")

    # 3) 블렌딩 비율 재탐색
    best_w = None
    if best_a:
        for w in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6]:
            avg, fm = cv_eval(df2, target, feats, alpha=best_a[0], blend_w=w)
            if avg is not None and (best_w is None or avg < best_w[1]):
                best_w = (w, avg, fm)
        if verbose:
            print(f"  최적 blend_w={best_w[0]}: 평균MAPE={best_w[1]:.2f}  fold={ {k: round(v,1) for k,v in best_w[2].items()} }")

    return {
        "region": region, "target": target, "n_obs": int(df2[target].notna().sum()),
        "baseline_mape": avg_base,
        "best_alpha": best_a[0] if best_a else None,
        "best_blend_w": best_w[0] if best_w else None,
        "model_mape": best_w[1] if best_w else None,
        "fold_detail": best_w[2] if best_w else {},
    }


def main():
    df = build_features(load_panel())
    results = [tune_region(df, r) for r in REGIONS]
    print("\n" + "=" * 70)
    print("요약 — 시장별 최적 구성 비교")
    print("=" * 70)
    summary = pd.DataFrame(results)[["region", "n_obs", "baseline_mape", "model_mape", "best_alpha", "best_blend_w"]]
    print(summary.to_string(index=False))
    return results


if __name__ == "__main__":
    main()
