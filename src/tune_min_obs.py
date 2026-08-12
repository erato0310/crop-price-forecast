# -*- coding: utf-8 -*-
"""tune_min_obs.py — build_dataset.MIN_OBS_PER_MONTH(월별 최소 거래건수)를 CV로 고른다.

거래 1~2건으로 만든 월평균은 시장가격이 아니라 잡음이라 lag 피처를 오염시킨다.
그렇다고 세게 걸러내면 월이 사라져 얇은 조합이 MIN_MONTHS(40)에 못 미쳐 통째로 빠진다.
어디서 균형이 맞는지는 이 프로젝트의 원칙대로 단일 홀드아웃이 아니라 CV로 판정한다.

기후·거시 컬럼은 임계값과 무관하므로 기존 패널을 재사용하고 origin 가격 컬럼만
임계값별로 다시 만든다 — build_dataset.py를 임계값마다 다시 돌리면 기후 API 때문에
10분씩 더 걸린다.

사용: ..\\.venv\\Scripts\\python.exe tune_min_obs.py
"""
from __future__ import annotations

import pandas as pd

import build_dataset as BD
import crop_county_cv as CV
from features import build_features

THRESHOLDS = [1, 2, 3, 5]


def panel_for(threshold: int, base: pd.DataFrame) -> pd.DataFrame:
    """origin 가격/물량 컬럼만 임계값에 맞춰 다시 만든 패널."""
    BD.MIN_OBS_PER_MONTH = threshold
    origin = BD.build_all_crops_origin_history()
    lettuce = BD.build_jeonbuk_origin_history()
    drop = [c for c in base.columns
            if c.startswith(("price_avg_origin_", "qty_total_origin_", "n_obs_origin_"))]
    out = base.drop(columns=drop).merge(origin, on="ym", how="left")
    return out.merge(lettuce, on="ym", how="left")


def main() -> None:
    base = pd.read_csv(BD.OUT_DIR / "monthly_panel.csv")
    base["ym"] = pd.PeriodIndex(base["ym"], freq="M")

    rows = []
    per_combo: dict[int, pd.DataFrame] = {}
    for t in THRESHOLDS:
        panel = panel_for(t, base)
        df = build_features(panel)
        results = []
        for crop in CV.CROPS:
            for county in CV.COUNTIES:
                r = CV.tune(df, crop, county)
                if r["skipped"]:
                    r_gpj = CV.tune(df, crop, county, target_source="gpj")
                    if not r_gpj["skipped"]:
                        r = r_gpj
                results.append(r)
        results = CV.apply_consensus(df, results)
        s = pd.DataFrame(results)
        v = s[~s["skipped"]]
        per_combo[t] = v.set_index(["crop_id", "county_id"])["model_mape"]
        rows.append({
            "min_obs": t, "n_valid": len(v),
            "median_mape": v["model_mape"].median(),
            "mean_mape": v["model_mape"].mean(),
            "n_over_100": int((v["model_mape"] >= 100).sum()),
            "n_beat_baseline": int((v["model_mape"] < v["baseline_mape"]).sum()),
        })
        print(f"[min_obs={t}] 유효 {rows[-1]['n_valid']}개, 중앙 MAPE "
              f"{rows[-1]['median_mape']:.2f}%, 평균 {rows[-1]['mean_mape']:.2f}%, "
              f"100%초과 {rows[-1]['n_over_100']}개, 모델승 {rows[-1]['n_beat_baseline']}",
              flush=True)

    out = pd.DataFrame(rows)
    print("\n" + "=" * 70)
    print("전체 유효 조합 기준 (임계값이 오르면 어려운 조합이 빠져 나가므로 그대로 비교하면 안 됨)")
    print(out.to_string(index=False))

    # 임계값을 올리면 '어려운 조합'이 유효 목록에서 빠져 중앙 MAPE가 자동으로 좋아진다.
    # 그건 모델이 좋아진 게 아니라 표본이 바뀐 것이다 — 모든 임계값에서 살아남은
    # 공통 조합만으로 다시 비교해야 순수한 효과가 보인다.
    common = set.intersection(*(set(s.index) for s in per_combo.values()))
    print(f"\n모든 임계값에서 살아남은 공통 조합 {len(common)}개로 재비교:")
    comp = pd.DataFrame({t: per_combo[t].loc[sorted(common)] for t in THRESHOLDS})
    summary = pd.DataFrame({
        "min_obs": THRESHOLDS,
        "median_mape_common": [comp[t].median() for t in THRESHOLDS],
        "mean_mape_common": [comp[t].mean() for t in THRESHOLDS],
        "n_worse_than_1": [int((comp[t] > comp[THRESHOLDS[0]] + 0.5).sum()) for t in THRESHOLDS],
        "n_better_than_1": [int((comp[t] < comp[THRESHOLDS[0]] - 0.5).sum()) for t in THRESHOLDS],
    })
    print(summary.to_string(index=False))
    best = summary.loc[summary["median_mape_common"].idxmin(), "min_obs"]
    print(f"\n공통 조합 중앙 MAPE 최소: min_obs={best}")
    print(f"(단, 유효 조합 수도 같이 보라: {dict(zip(out['min_obs'], out['n_valid']))} "
          "- 웹앱에 노출할 작물x시군이 그만큼 줄어든다)")
    out.merge(summary, on="min_obs").to_csv(
        "../outputs/min_obs_threshold_cv.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
