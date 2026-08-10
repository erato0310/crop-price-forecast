# -*- coding: utf-8 -*-
"""cross_crop_cv.py — 교차작물 피처 실험 (walk-forward CV로 검증).

가설: 연관 작물(대체재/같은 유통군)의 가격이 서로의 예측에 도움될 수 있다
(예: 토마토↔방울토마토, 수박↔멜론). 각 작물×시군 조합에 대해 "연관 작물의
전북 전체 가격(물량가중) lag1"을 피처로 추가했을 때 CV MAPE가 좋아지는지 잰다.

방법론 주의: crop_county_cv.py와 동일한 walk-forward CV(2020~2025 fold)로
비교한다 — 단일 홀드아웃 비교 금지(models.py 과적합 사례 참고). 기존 튜닝된
alpha/blend(crop_county_cv_summary.csv)를 그대로 쓰고 피처만 추가해, 피처
효과만 분리 측정한다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest import load_panel
from features import build_features
from crop_county_cv import _add_features, cv_eval, MIN_MONTHS

# 연관 작물 그룹(농산물 유통 관행 기준). 그룹 내 서로가 서로의 후보 피처.
CROP_GROUPS = {
    "과채_토마토군": ["tomato", "cherrytomato"],
    "과채_박과": ["watermelon", "melon", "cucumber"],
    "엽채조미": ["lettuce", "greenonion"],
    "과일": ["grape", "peach"],
}

ALL_CROPS_LONG = "../data/raw/jeonbuk_origin_top10crops_by_county.csv"


def build_crop_level_prices() -> pd.DataFrame:
    """작물별 전북 전체(시군 통합, 물량가중) 월별 가격 — 교차작물 피처의 원천."""
    long = pd.read_csv(ALL_CROPS_LONG, encoding="utf-8-sig")
    long["ym"] = pd.PeriodIndex(long["ym"], freq="M")

    def _wavg(g):
        tq = g["qty_total"].sum()
        return (g["price_avg"] * g["qty_total"]).sum() / tq if tq else np.nan

    agg = (long.groupby(["crop_id", "ym"])
           .apply(_wavg, include_groups=False).rename("price").reset_index())
    wide = agg.pivot(index="ym", columns="crop_id", values="price")
    wide.columns = [f"crossprice_{c}" for c in wide.columns]
    return wide.reset_index()


def main():
    df = build_features(load_panel())
    crop_prices = build_crop_level_prices()
    df = df.merge(crop_prices, on="ym", how="left")

    tuned = pd.read_csv("../outputs/crop_county_cv_summary.csv")
    tuned = tuned[~tuned["skipped"]]

    results = []
    for _, t in tuned.iterrows():
        crop, county = t["crop_id"], t["county_id"]
        partners = []
        for grp in CROP_GROUPS.values():
            if crop in grp:
                partners = [c for c in grp if c != crop]
        if not partners:
            continue  # sweetpotato 등 그룹 없는 작물
        df2, target, feats, _extra = _add_features(df, crop, county)
        if not feats or df2[target].notna().sum() < MIN_MONTHS:
            continue
        alpha, blend = t["best_alpha"], t["best_blend_w"]

        base_avg, _ = cv_eval(df2, target, feats, alpha=alpha, blend_w=blend)
        for p in partners:
            col = f"crossprice_{p}"
            if col not in df2.columns or df2[col].notna().sum() < MIN_MONTHS:
                continue
            df3 = df2.copy()
            df3[f"{col}_lag1"] = df3[col].shift(1)
            aug_avg, _ = cv_eval(df3, target, feats + [f"{col}_lag1"],
                                 alpha=alpha, blend_w=blend)
            if base_avg is None or aug_avg is None:
                continue
            results.append({
                "crop_id": crop, "county_id": county, "partner": p,
                "mape_base": round(base_avg, 2), "mape_with_cross": round(aug_avg, 2),
                "delta": round(aug_avg - base_avg, 2),
            })
            print(f"{crop:13s}x{county:9s} +{p:13s} {base_avg:6.1f}% -> {aug_avg:6.1f}% "
                  f"({aug_avg-base_avg:+.1f}pp)", flush=True)

    res = pd.DataFrame(results)
    res.to_csv("../outputs/cross_crop_cv_results.csv", index=False, encoding="utf-8-sig")
    if not res.empty:
        print("\n" + "=" * 70)
        improved = res[res["delta"] < -0.5]
        print(f"개선(-0.5pp 이상) {len(improved)}/{len(res)}개 조합")
        print(f"평균 delta: {res['delta'].mean():+.2f}pp (음수=개선)")
        print("\n파트너별 평균 효과:")
        print(res.groupby(["crop_id", "partner"])["delta"].agg(["mean", "count"])
              .round(2).sort_values("mean").to_string())
    print("\n저장: ../outputs/cross_crop_cv_results.csv")


if __name__ == "__main__":
    main()
