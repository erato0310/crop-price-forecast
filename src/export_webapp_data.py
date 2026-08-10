# -*- coding: utf-8 -*-
"""export_webapp_data.py — 웹앱(webapp/)이 읽을 단일 JSON을 만든다.

예측이 전부 사전 계산돼 있으므로(crop_county_predict.py / crop_county_forecast.py)
웹앱은 서버 없이 이 JSON 하나만 읽으면 된다 — 정적 호스팅(GitHub Pages 등)으로
바로 공개 URL을 받을 수 있고 운영비가 0이다.

입력:
  data/processed/monthly_panel.csv                        (실측 가격 이력)
  outputs/crop_county_cv_summary.csv                      (조합별 검증 성적)
  outputs/crop_county_predictions/crop_county_metrics_*.csv (연도별 검증 성적)
  outputs/future_forecast/crop_county_future_forecast.csv (미래 예측 + 구간)
  outputs/region_recommend_lettuce.csv                    (지역 추천)
출력:
  webapp/data/app_data.json

용량을 위해 가격은 정수로, 확률은 소수 3자리로 반올림한다.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from build_dataset import COUNTY_NAME_TO_ID
from crop_county_predict import EXCLUDE_MAPE
from scrape_jeonbuk_all_crops import CROP_NAME_TO_ID

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "webapp" / "data" / "app_data.json"

CROP_ID_TO_NAME = {v: k for k, v in CROP_NAME_TO_ID.items()}
COUNTY_ID_TO_NAME = {v: k for k, v in COUNTY_NAME_TO_ID.items()}

# 작물 표시 순서: 검증 성적이 좋은 순으로 보여주면 첫인상이 정직하면서도 강점이 먼저 보임
CROP_ORDER = ["sweetpotato", "tomato", "peach", "cherrytomato", "lettuce",
              "cucumber", "melon", "grape", "greenonion", "watermelon"]


def _hist_series(panel: pd.DataFrame, crop_id: str, county_id: str,
                 target_source: str) -> list:
    prefix = "origin" if target_source == "origin" else "gpj"
    col = f"price_avg_{prefix}_{crop_id}_{county_id}"
    if col not in panel.columns:
        return []
    s = panel[["ym", col]].dropna()
    return [[ym, int(round(v))] for ym, v in zip(s["ym"], s[col])]


def main() -> None:
    panel = pd.read_csv(ROOT / "data/processed/monthly_panel.csv")
    cv = pd.read_csv(ROOT / "outputs/crop_county_cv_summary.csv")
    fc = pd.read_csv(ROOT / "outputs/future_forecast/crop_county_future_forecast.csv")
    m2025 = pd.read_csv(ROOT / "outputs/crop_county_predictions/crop_county_metrics_2025.csv")
    m2026 = pd.read_csv(ROOT / "outputs/crop_county_predictions/crop_county_metrics_2026.csv")

    usable = cv[(~cv["skipped"]) & (cv["model_mape"] < EXCLUDE_MAPE)]
    m25 = m2025.set_index(["crop_id", "county_id"])
    m26 = m2026.set_index(["crop_id", "county_id"])

    combos: dict[str, dict] = {}
    for _, r in usable.iterrows():
        crop_id, county_id = r["crop_id"], r["county_id"]
        key = f"{crop_id}|{county_id}"
        sub = fc[(fc["crop_id"] == crop_id) & (fc["county_id"] == county_id)]
        if sub.empty:
            continue

        hist = _hist_series(panel, crop_id, county_id, r["target_source"])
        if not hist:
            continue

        entry = {
            "src": r["target_source"],            # origin=도매시장 산지가, gpj=산지공판장 정산가
            "n_obs": int(r["n_obs"]),
            "cv_mape": round(float(r["model_mape"]), 1),
            "cv_base_mape": round(float(r["baseline_mape"]), 1),
            "hist": hist,
            # [ym, 예측가, 하한, 상한, 폭등확률]
            "fc": [[row.ym, int(round(row.forecast_price)), int(round(row.pred_lower_90)),
                    int(round(row.pred_upper_90)), round(float(row.spike_prob), 3)]
                   for row in sub.itertuples()],
            "spike_threshold": int(round(float(sub["spike_threshold"].iloc[0]))),
        }
        for label, table in (("v2025", m25), ("v2026", m26)):
            if (crop_id, county_id) in table.index:
                row = table.loc[(crop_id, county_id)]
                entry[label] = [round(float(row["model_MAPE"]), 1),
                                round(float(row["baseline_MAPE"]), 1)]
        combos[key] = entry

    # 작물/시군 목록은 실제로 예측 가능한 조합이 있는 것만 노출
    crops_present = {k.split("|")[0] for k in combos}
    counties_present = {k.split("|")[1] for k in combos}

    region = pd.read_csv(ROOT / "outputs/region_recommend_lettuce.csv")
    region_rows = [{
        "county_id": r["region_id"],
        "county": COUNTY_ID_TO_NAME.get(r["region_id"], r["region_id"]),
        "crop_id": r["crop_id"],
        "suit_pct": round(float(r["suit_or_better_pct"]), 1),
        "high_pct": round(float(r["high_suit_pct"]), 1),
        "total_ha": int(round(float(r["total_area"]))),
    } for _, r in region.sort_values("suit_or_better_pct", ascending=False).iterrows()]

    last_actual = max(h[-1][0] for h in (c["hist"] for c in combos.values()) if h)
    payload = {
        "meta": {
            "generated": date.today().isoformat(),
            "last_actual_ym": last_actual,
            "n_combos": len(combos),
            "excluded_note": "검증 오차 100% 이상인 조합(수박×부안, 대파×김제)은 "
                             "데이터 품질 문제로 예측에서 제외했습니다.",
        },
        "crops": [{"id": c, "name": CROP_ID_TO_NAME[c]}
                  for c in CROP_ORDER if c in crops_present],
        "counties": [{"id": cid, "name": nm} for nm, cid in COUNTY_NAME_TO_ID.items()
                     if cid in counties_present],
        "combos": combos,
        "region_recommend": region_rows,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"저장 완료: {OUT_PATH} ({size_kb:.0f} KB, 조합 {len(combos)}개, "
          f"작물 {len(payload['crops'])}종, 시군 {len(payload['counties'])}곳)")
    print(f"마지막 실측: {last_actual}")


if __name__ == "__main__":
    main()
