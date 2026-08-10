# -*- coding: utf-8 -*-
"""county_cv.py — 전북 시군별(산지 기준) 상추 가격을 각각 타깃으로 walk-forward CV.

build_dataset.build_jeonbuk_origin_history()가 만든 price_avg_origin_{county} 컬럼들을
county_cv.py의 region_cv.py와 같은 방법론(로그타깃+Ridge, 계절평균 블렌딩)으로 검증한다.
데이터가 너무 얇은 시군(관측월 MIN_MONTHS 미만)은 CV 자체가 노이즈라 건너뛴다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from backtest import load_panel, mape
from features import build_features
from build_dataset import COUNTY_NAME_TO_ID

MIN_MONTHS = 40  # 이보다 적으면 CV fold가 너무 얇아져서(예: 2022년 4개월 사례) 건너뜀
TEST_YEARS = [2020, 2021, 2022, 2023, 2024, 2025]
BASE_FEATS = ["month_sin", "month_cos"]


def _add_county_features(df: pd.DataFrame, county_id: str):
    price_col = f"price_avg_origin_{county_id}"
    qty_col = f"qty_total_origin_{county_id}"
    df = df.copy()
    df[f"{price_col}_lag1"] = df[price_col].shift(1)
    df[f"{price_col}_lag12"] = df[price_col].shift(12)
    df[f"{price_col}_roll3"] = df[price_col].shift(1).rolling(3).mean()
    df[f"{price_col}_roll6"] = df[price_col].shift(1).rolling(6).mean()
    if qty_col in df.columns:
        df[f"{qty_col}_log"] = np.log1p(df[qty_col])
    else:
        df[f"{qty_col}_log"] = np.nan
    feats = BASE_FEATS + [f"{price_col}_lag1", f"{price_col}_lag12",
                          f"{price_col}_roll3", f"{price_col}_roll6",
                          "rain_sum", f"{qty_col}_log"]
    return df, price_col, feats


def cv_eval(df, target, feats, alpha, blend_w, test_years=TEST_YEARS):
    fold_mape = {}
    for ty in test_years:
        train = df[df["ym"].dt.year < ty].dropna(subset=[target])
        test = df[df["ym"].dt.year == ty].dropna(subset=[target])
        if len(train) < 6 or test.empty:
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
    if not fold_mape:
        return None, {}
    return float(np.mean(list(fold_mape.values()))), fold_mape


def tune_county(df: pd.DataFrame, county_id: str, verbose: bool = True):
    df2, target, feats = _add_county_features(df, county_id)
    n_obs = df2[target].notna().sum() if target in df2.columns else 0
    if n_obs < MIN_MONTHS:
        if verbose:
            print(f"{county_id:10s} 관측 {n_obs:3d}개월 — {MIN_MONTHS}개월 미만이라 건너뜀")
        return {"county_id": county_id, "n_obs": int(n_obs), "skipped": True}

    avg_base, fm_base = cv_eval(df2, target, feats, alpha=1.0, blend_w=1.0)

    best_a = None
    for a in [0.5, 1, 2, 3, 5, 10, 20, 30, 50, 100]:
        avg, fm = cv_eval(df2, target, feats, alpha=a, blend_w=0.0)
        if avg is not None and (best_a is None or avg < best_a[1]):
            best_a = (a, avg, fm)

    best_w = None
    if best_a:
        for w in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6]:
            avg, fm = cv_eval(df2, target, feats, alpha=best_a[0], blend_w=w)
            if avg is not None and (best_w is None or avg < best_w[1]):
                best_w = (w, avg, fm)

    result = {
        "county_id": county_id, "n_obs": int(n_obs), "skipped": False,
        "baseline_mape": avg_base,
        "best_alpha": best_a[0] if best_a else None,
        "best_blend_w": best_w[0] if best_w else None,
        "model_mape": best_w[1] if best_w else None,
        "n_folds": len(best_w[2]) if best_w else 0,
    }
    if verbose:
        print(f"{county_id:10s} 관측{n_obs:3d}개월  베이스라인={avg_base:5.1f}%  "
              f"모델={result['model_mape']:5.1f}%  (alpha={result['best_alpha']}, "
              f"blend={result['best_blend_w']}, fold={result['n_folds']}개)")
    return result


def main():
    df = build_features(load_panel())
    county_ids = sorted(set(COUNTY_NAME_TO_ID.values()))
    results = [tune_county(df, c) for c in county_ids]
    print("\n" + "=" * 70)
    print("요약")
    print("=" * 70)
    summary = pd.DataFrame(results)
    print(summary.to_string(index=False))
    return results


if __name__ == "__main__":
    main()
