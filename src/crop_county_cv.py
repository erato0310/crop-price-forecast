# -*- coding: utf-8 -*-
"""crop_county_cv.py — 상위 10개 작물 x 전북 14개 시군(140개 조합)을 전부 CV 튜닝.

county_cv.py(상추 전용)를 작물 축으로 일반화한 것. 방법론은 동일(로그+Ridge+계절평균
블렌딩, walk-forward CV). 데이터가 너무 얇은 조합(관측 MIN_MONTHS 미만)은 건너뛴다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from backtest import load_panel, mape
from features import build_features
from build_dataset import COUNTY_NAME_TO_ID
from scrape_jeonbuk_all_crops import CROP_NAME_TO_ID

MIN_MONTHS = 40
TEST_YEARS = [2020, 2021, 2022, 2023, 2024, 2025]
BASE_FEATS = ["month_sin", "month_cos"]

CROPS = sorted(set(CROP_NAME_TO_ID.values()))
COUNTIES = sorted(set(COUNTY_NAME_TO_ID.values()))

# 작물 유형 분류 (문헌 근거: KREI 최병옥·최익창 2007 "품목별 최적 모형이 다르다",
# arXiv 2310.18646 리뷰의 저장성(storable) vs 부패성(perishable) 구분).
# 유형별 피처 가설 — CV가 기각하면 조합별로 채택 안 됨:
#  - storable(고구마): 저장 출하로 가격 동학이 느림 → 짧은 roll3 대신 긴 roll12
#  - leafy(상추·대파): 부패성이라 기상 충격이 즉시 가격에 반영 → 당월 평균기온 추가
#  - fruitveg/fruit: 기본 피처 유지(변형 없음)
CROP_TYPE = {
    "sweetpotato": "storable",
    "lettuce": "leafy", "greenonion": "leafy",
    "cucumber": "fruitveg", "tomato": "fruitveg", "cherrytomato": "fruitveg",
    "watermelon": "fruitveg", "melon": "fruitveg",
    "grape": "fruit", "peach": "fruit",
}


def _add_features(df: pd.DataFrame, crop_id: str, county_id: str,
                  target_source: str = "origin"):
    """target_source: 'origin'=도매시장 산지가격(기본), 'gpj'=산지공판장 정산가격.
    gpj는 도매시장 표본이 없는 시군(군산 등)의 대체 타깃으로 쓴다(2020-01~).
    origin 타깃일 때 같은 조합의 gpj 가격이 있으면 lag1을 보조 피처로 추가한다."""
    prefix = "origin" if target_source == "origin" else "gpj"
    price_col = f"price_avg_{prefix}_{crop_id}_{county_id}"
    qty_col = f"qty_total_{prefix}_{crop_id}_{county_id}"
    df = df.copy()
    if price_col not in df.columns:
        return df, price_col, [], []
    df[f"{price_col}_lag1"] = df[price_col].shift(1)
    df[f"{price_col}_lag12"] = df[price_col].shift(12)
    df[f"{price_col}_roll3"] = df[price_col].shift(1).rolling(3).mean()
    df[f"{price_col}_roll6"] = df[price_col].shift(1).rolling(6).mean()
    df[f"{qty_col}_log"] = np.log1p(df[qty_col]) if qty_col in df.columns else np.nan
    feats = BASE_FEATS + [f"{price_col}_lag1", f"{price_col}_lag12",
                          f"{price_col}_roll3", f"{price_col}_roll6",
                          "rain_sum", f"{qty_col}_log"]
    extra: list[str] = []
    if target_source == "origin":
        gpj_col = f"price_avg_gpj_{crop_id}_{county_id}"
        if gpj_col in df.columns and df[gpj_col].notna().sum() >= 24:
            df[f"{gpj_col}_lag1"] = df[gpj_col].shift(1)
            extra = [f"{gpj_col}_lag1"]  # 후보일 뿐 — tune()이 CV로 채택 여부 결정
    return df, price_col, feats, extra


def _variant_feats(df: pd.DataFrame, crop_id: str, price_col: str,
                   feats: list[str]) -> tuple[pd.DataFrame, list[str], str]:
    """작물 유형별 피처 변형 후보. (df, 변형 피처목록, 변형이름) — 변형 없으면 feats 그대로."""
    ctype = CROP_TYPE.get(crop_id, "")
    if ctype == "storable":
        df = df.copy()
        df[f"{price_col}_roll12"] = df[price_col].shift(1).rolling(12).mean()
        v = [f if not f.endswith("_roll3") else f"{price_col}_roll12" for f in feats]
        return df, v, "storable_long"
    if ctype == "leafy" and "tavg" in df.columns:
        return df, feats + ["tavg"], "leafy_weather"
    return df, feats, ""


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
        # 표본이 얇은 조합에서 로그공간 외삽이 지수 역변환으로 폭발하는 것 방지:
        # 학습 기간에서 본 가격 범위를 크게 벗어나는 예측은 물리적으로 신뢰 불가
        reg_pred = np.clip(reg_pred, train[target].min() / 3.0, train[target].max() * 3.0)
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


def tune(df: pd.DataFrame, crop_id: str, county_id: str, target_source: str = "origin"):
    df2, target, feats, extra = _add_features(df, crop_id, county_id, target_source)
    if not feats or target not in df2.columns:
        return {"crop_id": crop_id, "county_id": county_id, "n_obs": 0, "skipped": True,
                "target_source": target_source}
    n_obs = df2[target].notna().sum()
    if n_obs < MIN_MONTHS:
        return {"crop_id": crop_id, "county_id": county_id, "n_obs": int(n_obs),
                "skipped": True, "target_source": target_source}

    avg_base, _ = cv_eval(df2, target, feats, alpha=1.0, blend_w=1.0)

    best_a = None
    # alpha 하한 2: 0.5~1은 얇은 표본(40~90개월)에서 계수가 불안정해져
    # 5개 조합(cucumber×gochang 등)의 MAPE가 수백~수만%로 폭발한 이력 있음
    for a in [2, 3, 5, 10, 20, 30, 50, 100]:
        avg, fm = cv_eval(df2, target, feats, alpha=a, blend_w=0.0)
        if avg is not None and (best_a is None or avg < best_a[1]):
            best_a = (a, avg, fm)

    best_w = None
    if best_a:
        for w in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6]:
            avg, fm = cv_eval(df2, target, feats, alpha=best_a[0], blend_w=w)
            if avg is not None and (best_w is None or avg < best_w[1]):
                best_w = (w, avg, fm)

    # 산지공판장 가격 lag1 후보 피처: CV가 좋아질 때만 채택
    use_gpj = False
    if best_w and extra:
        avg_g, fm_g = cv_eval(df2, target, feats + extra,
                              alpha=best_a[0], blend_w=best_w[0])
        if avg_g is not None and avg_g < best_w[1]:
            best_w = (best_w[0], avg_g, fm_g)
            use_gpj = True

    # 작물 유형별 피처 변형(저장성=긴 lag, 엽채=기온): CV가 좋아질 때만 채택
    variant_used = ""
    if best_w:
        cur_feats = feats + (extra if use_gpj else [])
        df3, vfeats, vname = _variant_feats(df2, crop_id, target, cur_feats)
        if vname:
            avg_v, fm_v = cv_eval(df3, target, vfeats,
                                  alpha=best_a[0], blend_w=best_w[0])
            if avg_v is not None and avg_v < best_w[1]:
                best_w = (best_w[0], avg_v, fm_v)
                variant_used = vname

    return {
        "crop_id": crop_id, "county_id": county_id, "n_obs": int(n_obs), "skipped": False,
        "target_source": target_source,
        "baseline_mape": avg_base,
        "best_alpha": best_a[0] if best_a else None,
        "best_blend_w": best_w[0] if best_w else None,
        "use_gpj_feature": use_gpj,
        "feature_variant": variant_used,
        "model_mape": best_w[1] if best_w else None,
        "n_folds": len(best_w[2]) if best_w else 0,
    }


def _eval_with_params(df, crop_id, county_id, target_source, alpha, blend_w,
                      use_gpj, variant):
    """튜닝 없이 주어진 파라미터·피처 구성으로 CV 한 번만 평가 (컨센서스 비교용)."""
    df2, target, feats, extra = _add_features(df, crop_id, county_id, target_source)
    if not feats:
        return None
    cur = feats + (extra if (use_gpj and extra) else [])
    if variant:
        df2, cur, _ = _variant_feats(df2, crop_id, target, cur)
    avg, _ = cv_eval(df2, target, cur, alpha=alpha, blend_w=blend_w)
    return avg


def apply_consensus(df, results, thin_below=60, thick_min=70, tolerance_pp=2.0):
    """얇은 표본 조합(n_obs<thin_below)은 개별 튜닝이 과적합되기 쉬움(이상치 5개 사건의
    근본 원인). 같은 작물의 두터운 조합(n_obs>=thick_min)들이 합의한 alpha/blend를
    빌려와 평가하고, 개별 튜닝이 컨센서스를 tolerance_pp 이상 확실히 이기지 못하면
    컨센서스 파라미터를 최종 채택한다(정규화 논리 — 얇은 CV의 승리는 우연일 확률이 큼)."""
    res_df = pd.DataFrame(results)
    valid = res_df[~res_df["skipped"]]
    consensus = {}
    for crop, grp in valid[valid["n_obs"] >= thick_min].groupby("crop_id"):
        if len(grp) < 3:
            continue  # 두터운 조합이 3개 미만이면 합의라 부르기 어려움
        alpha = float(grp["best_alpha"].median())
        alpha = min([2, 3, 5, 10, 20, 30, 50, 100], key=lambda a: abs(a - alpha))
        blend = round(float(grp["best_blend_w"].median()), 1)
        consensus[crop] = (alpha, blend)

    for r in results:
        if r.get("skipped") or r["n_obs"] >= thin_below:
            r["params_source"] = "own" if not r.get("skipped") else None
            continue
        c = consensus.get(r["crop_id"])
        if c is None:
            r["params_source"] = "own"
            continue
        cons_mape = _eval_with_params(df, r["crop_id"], r["county_id"],
                                      r["target_source"], c[0], c[1],
                                      r.get("use_gpj_feature", False),
                                      r.get("feature_variant", ""))
        r["consensus_alpha"], r["consensus_blend_w"] = c
        r["consensus_mape"] = cons_mape
        if cons_mape is not None and cons_mape - r["model_mape"] < tolerance_pp:
            r["params_source"] = "crop_consensus"
            r["model_mape_own"] = r["model_mape"]
            r["model_mape"] = cons_mape
            r["best_alpha"], r["best_blend_w"] = c
        else:
            r["params_source"] = "own"
    return results


def main():
    df = build_features(load_panel())
    results = []
    total = len(CROPS) * len(COUNTIES)
    i = 0
    for crop in CROPS:
        for county in COUNTIES:
            i += 1
            r = tune(df, crop, county)
            if r["skipped"]:
                # 도매시장 표본 부족 → 산지공판장 정산가격을 대체 타깃으로 시도
                r_gpj = tune(df, crop, county, target_source="gpj")
                if not r_gpj["skipped"]:
                    r = r_gpj
            results.append(r)
            if not r["skipped"]:
                gp = " [gpj타깃]" if r["target_source"] == "gpj" else (
                    " [+gpj피처]" if r.get("use_gpj_feature") else "")
                print(f"[{i}/{total}] {crop:14s} x {county:10s} 관측{r['n_obs']:3d}개월  "
                      f"베이스라인={r['baseline_mape']:5.1f}%  모델={r['model_mape']:5.1f}%  "
                      f"(alpha={r['best_alpha']}, blend={r['best_blend_w']}){gp}", flush=True)

    results = apply_consensus(df, results)
    n_cons = sum(1 for r in results if r.get("params_source") == "crop_consensus")
    print(f"\n얇은 표본 조합 중 작물 컨센서스 파라미터 채택: {n_cons}개")

    summary = pd.DataFrame(results)
    out_path = "../outputs/crop_county_cv_summary.csv"
    summary.to_csv(out_path, index=False, encoding="utf-8-sig")

    valid = summary[~summary["skipped"]].sort_values("model_mape")
    print("\n" + "=" * 90)
    print(f"유효 조합 {len(valid)}개 / 전체 {total}개 (나머지는 {MIN_MONTHS}개월 미만이라 스킵)")
    print("=" * 90)
    print(valid.to_string(index=False))
    print(f"\n저장 완료: {out_path}")
    return results


if __name__ == "__main__":
    main()
