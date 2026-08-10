# -*- coding: utf-8 -*-
"""region_recommend.py — 흙토람 토양적성 데이터로 "전북 8개 시군 중 상추 재배에 어디가
좋은가" 지역추천 리포트를 만든다.

원래 프로젝트 목표("작물을 추천 및 경고")의 추천 절반을 담당한다. 가격예측(backtest.py/
predict_2026.py)과는 별개 산출물 — 토양적성은 연도가 지나도 거의 안 변하는 정적 데이터라
월별 가격모델에 피처로 넣기보다 이렇게 별도 리포트로 두는 게 맞다(RESOLVE_GUIDE 참고).

점수화: 등급별 면적(최적지/적지/가능지/저위생산지)에 가중치를 줘서 하나의 점수로 합친다.
가중치는 "등급이 좋을수록 배로 중요"하게 2배씩 차등(8:4:2:1)을 뒀다 — 특별한 통계적
근거는 없고 직관적인 등급 가중치라 참고용으로만 쓸 것.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

import sources as S

CROP = "lettuce"
OUT_DIR = Path(__file__).resolve().parent.parent / "outputs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

GRADE_WEIGHTS = {"high_suit_area": 8, "suit_area": 4, "poss_area": 2, "low_suit_area": 1}


def build_report(crop_id: str = CROP) -> pd.DataFrame:
    regions = list(S.region_xwalk().index)
    rows = []
    for r in regions:
        d = S.load_suit(r, crop_id)
        if d is None or d.empty:
            rows.append({"region_id": r, "status": "데이터없음"})
            continue
        row = d.iloc[0].to_dict()
        row["status"] = "OK"
        rows.append(row)
    df = pd.DataFrame(rows)

    area_cols = [c for c in GRADE_WEIGHTS if c in df.columns]
    if area_cols:
        df["total_area"] = df[area_cols].sum(axis=1, skipna=True)
        df["suit_score"] = sum(df[c].fillna(0) * w for c, w in GRADE_WEIGHTS.items() if c in df.columns)
        # 총면적 대비 비율로도 — 절대면적이 큰 지역(시)이 절대점수에서 유리해지는 걸 보정
        df["high_suit_pct"] = (df.get("high_suit_area", 0) / df["total_area"].replace(0, pd.NA) * 100)
        df["suit_or_better_pct"] = (
            (df.get("high_suit_area", 0) + df.get("suit_area", 0)) / df["total_area"].replace(0, pd.NA) * 100
        )
        df = df.sort_values("suit_score", ascending=False)
    return df.reset_index(drop=True)


def main():
    df = build_report()
    out_csv = OUT_DIR / f"region_recommend_{CROP}.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"저장: {out_csv}")
    print()
    cols = ["region_id", "bjd_nm", "high_suit_area", "suit_area", "poss_area", "low_suit_area",
            "total_area", "high_suit_pct", "suit_or_better_pct", "suit_score"]
    cols = [c for c in cols if c in df.columns]
    print(df[cols].to_string(index=False))


if __name__ == "__main__":
    main()
