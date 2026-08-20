# -*- coding: utf-8 -*-
"""analyze_dtr_grade.py — 일교차가 **등급**에 나타나는가.

────────────────────────────────────────────────────────────────
왜 값이 아니라 등급인가
────────────────────────────────────────────────────────────────
`analyze_dtr_within.py` 에서 일교차와 경매가의 관계는 4,321주 표본에서
전부 판정불가였다(r = +0.014 ~ +0.026). 표본이 부족해서가 아니라 신호가
없어서다.

그런데 생각해 보면 당연할 수 있다. **경매는 등급을 먼저 매기고 값은 그
등급 안에서 정해진다.** 잎이 두꺼워 상품성이 올라가면 그것은
"같은 특등급인데 비싸게" 팔리는 게 아니라 **"상 → 특으로 올라가는"** 형태로
나타난다. 그러면 값에는 안 보이고 등급 구성에 보인다.

그래서 같은 설계를 등급에 다시 건다.

    그 시군이 **예년 그 주보다** 일교차가 컸던 해에,
    **특 비율**도 예년 그 주보다 높았는가?

────────────────────────────────────────────────────────────────
등급 자료
────────────────────────────────────────────────────────────────
전북산 실측: 특 105,181t / 상 21,358t / 미기재 12,586t / 중 787t / 나머지 미미.
**미기재('.')는 분모에서 뺀다** — 등급을 안 적은 것이지 낮은 등급이 아니다.
미기재 비율 자체가 시장·시기마다 다르므로 그것도 같이 본다.

────────────────────────────────────────────────────────────────
검정 규칙
────────────────────────────────────────────────────────────────
- 시군·주차 평년 대비 편차끼리 견준다(시군 고정 성질·계절 상쇄).
- 부트스트랩은 시군 단위. 구간이 0을 포함하면 판정불가.
- 등급은 **사람이 매긴다.** 검사원·시장 관행이 지역마다 다르면 그것이
  그대로 섞인다. 이 설계로는 가릴 수 없다 — 결과에 적는다.

[실행] python analyze_dtr_grade.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from analyze_dtr_premium import COUNTY_STN, load_weather
from analyze_dtr_within import boot_by_county, demean, MIN_WEEKS

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "outputs"

TOP_GRADE = {"특"}
GRADED = {"특", "상", "중", "하", "등외"}      # 등급이 적힌 것


def weekly_weather() -> pd.DataFrame:
    wx = load_weather()
    wx["wk"] = wx["date"] - pd.to_timedelta(wx["date"].dt.weekday, unit="D")
    rows = []
    for cty, (stns, _) in COUNTY_STN.items():
        s = wx[wx["stn"].isin(stns)]
        if s.empty:
            continue
        day = s.groupby("date").agg(dtr=("dtr", "mean"), trop=("trop", "max"),
                                    wk=("wk", "first"))
        g = day.groupby("wk").agg(dtr=("dtr", "mean"), trop=("trop", "sum"),
                                  nday=("dtr", "size"))
        g = g[g["nday"] >= 5].reset_index()
        g["county"] = cty
        rows.append(g)
    return pd.concat(rows, ignore_index=True)


def weekly_grade() -> pd.DataFrame:
    d = pd.read_csv(RAW / "lettuce_daily_raw.csv", low_memory=False,
                    usecols=["date", "county", "variety", "grade", "qty_kg"])
    d = d[d["county"].notna()].dropna(subset=["qty_kg"])
    d = d[d["qty_kg"] > 0]
    d["date"] = pd.to_datetime(d["date"], format="mixed")
    d["wk"] = d["date"] - pd.to_timedelta(d["date"].dt.weekday, unit="D")
    d["graded"] = d["grade"].isin(GRADED)
    d["top"] = d["grade"].isin(TOP_GRADE)
    g = d.groupby(["county", "wk"]).apply(lambda x: pd.Series({
        "q_all": x["qty_kg"].sum(),
        "q_graded": x.loc[x["graded"], "qty_kg"].sum(),
        "q_top": x.loc[x["top"], "qty_kg"].sum(),
    }), include_groups=False).reset_index()
    g = g[g["q_graded"] > 0].copy()
    g["top_share"] = g["q_top"] / g["q_graded"]
    g["unrec"] = 1 - g["q_graded"] / g["q_all"]
    return g


def main() -> None:
    gr = weekly_grade()
    wxw = weekly_weather()
    m = gr.merge(wxw, on=["county", "wk"], how="inner")
    m["woy"] = m["wk"].dt.isocalendar().week.astype(int)
    m = m.sort_values(["county", "wk"]).reset_index(drop=True)

    for k in (2, 4):
        m[f"dtr{k}"] = (m.groupby("county")["dtr"]
                          .transform(lambda s: s.rolling(k, min_periods=k).mean()))
        m[f"trop{k}"] = (m.groupby("county")["trop"]
                           .transform(lambda s: s.rolling(k, min_periods=k).sum()))
    m = m[m.groupby("county")["wk"].transform("size") >= MIN_WEEKS]
    m = m.dropna(subset=["dtr2", "dtr4"]).copy()

    m["y"] = demean(m, "top_share")
    for c in ("dtr", "dtr2", "dtr4", "trop", "trop2", "trop4"):
        m["d_" + c] = demean(m, c)

    print("=" * 78)
    print("일교차 -> 등급? 시군·주차 평년 대비 편차끼리")
    print("=" * 78)
    print(f"  표본 {len(m):,}주 · 시군 {m['county'].nunique()}개")
    print(f"  특 비율 평균 {m['top_share'].mean()*100:.1f}% "
          f"(등급 미기재 물량 {m['unrec'].mean()*100:.1f}%는 분모에서 뺌)")
    print()
    print("  가설: 일교차가 평년보다 크면 특 비율도 높다 -> 양의 관계")
    print()
    print(f"  {'변수':<22}{'r':>8}{'95% 구간':>22}   판정")
    for col, lab, want in (("d_dtr", "일교차 (그 주)", +1),
                           ("d_dtr2", "일교차 (2주 누적)", +1),
                           ("d_dtr4", "일교차 (4주 누적)", +1),
                           ("d_trop2", "열대야 (2주 누적)", -1),
                           ("d_trop4", "열대야 (4주 누적)", -1)):
        r, lo, hi = boot_by_county(m, col, "y")
        if lo > 0:
            v = "양의 관계" + ("" if want > 0 else "  (가설과 반대)")
        elif hi < 0:
            v = "음의 관계" + ("" if want < 0 else "  (가설과 반대)")
        else:
            v = "판정불가"
        print(f"  {lab:<22}{r:+8.3f}   [{lo:+.3f}, {hi:+.3f}]   {v}")

    sm = m[m["wk"].dt.month.isin([6, 7, 8, 9])]
    if len(sm) > 200:
        print()
        print(f"  여름(6~9월)만 · {len(sm):,}주")
        for col, lab in (("d_dtr4", "일교차 (4주 누적)"), ("d_trop4", "열대야 (4주 누적)")):
            r, lo, hi = boot_by_county(sm, col, "y")
            v = "양의 관계" if lo > 0 else ("음의 관계" if hi < 0 else "판정불가")
            print(f"  {lab:<22}{r:+8.3f}   [{lo:+.3f}, {hi:+.3f}]   {v}")

    print()
    print("  주의 — 등급은 사람이 매긴다. 검사원·시장 관행이 지역이나 시기마다")
    print("  다르면 그대로 섞인다. 이 설계로는 그것을 가려내지 못한다.")

    OUT.mkdir(exist_ok=True)
    m.to_csv(OUT / "dtr_grade.csv", index=False, encoding="utf-8-sig")
    print(f"\n저장: {OUT/'dtr_grade.csv'}")


if __name__ == "__main__":
    main()
