# -*- coding: utf-8 -*-
"""analyze_dtr_within.py — 일교차 가설을 시군 **안에서** 검정한다.

────────────────────────────────────────────────────────────────
왜 설계를 바꾸는가
────────────────────────────────────────────────────────────────
`analyze_dtr_premium.py` 는 시군 14개를 놓고 "일교차가 큰 시군이 비싼가"를
물었다. 결과는 판정불가였고, 유일하게 나왔던 양의 관계(여름일교차 vs
여름−겨울 격차, r=+0.527)도 무주 한 점을 빼면 무너졌다.

당연한 일이다. 시군의 값 수준은 일교차 말고도 많은 것이 정한다 —
품종 구성, 재배 기술, 작목반 조직, 시장까지의 거리, 평판. 14개 점으로
그걸 다 가르려는 것은 무리다.

그래서 **같은 시군 안에서 주마다** 묻는다.

    그 시군이 **예년 그 주보다** 일교차가 컸던 해에,
    값도 **예년 그 주보다** 더 받았는가?

이렇게 하면
  - 표본이 14개에서 수천 개(시군 × 주)로 늘고
  - 시군의 고정된 성질(고도·평판·품종구성·거리)은 **전부 상쇄된다.**
    같은 시군끼리 견주기 때문이다.
  - 계절도 상쇄된다. '그 주차의 그 시군 평년'을 기준으로 삼기 때문이다.

────────────────────────────────────────────────────────────────
변수
────────────────────────────────────────────────────────────────
    가격 편차   log(그 주 상대값) − 그 시군·그 주차의 평년 log(상대값)
    일교차 편차 그 주 일교차 − 그 시군·그 주차의 평년 일교차
    열대야 편차 그 주 열대야 일수 − 그 시군·그 주차의 평년

상대값은 `analyze_dtr_premium` 과 같다(같은 주·같은 품종·같은 시장 안에서의 비).
즉 **전국 시세 변동은 이미 빠져 있고**, 남는 것은 그 주에 그 시군이 남들보다
얼마나 더 받았느냐다.

────────────────────────────────────────────────────────────────
검정 규칙
────────────────────────────────────────────────────────────────
- 시차를 준다. 오늘 일교차가 오늘 값을 바꾸지는 않는다. 잎이 두꺼워지려면
  자라는 동안 누적돼야 하므로 **출하 전 2·4주 누적**을 본다.
- 부트스트랩은 **시군 단위로 재표집**한다. 같은 시군의 주들은 서로 얽혀 있어
  주 단위로 뽑으면 구간이 실제보다 좁아진다.
- 구간이 0을 포함하면 판정불가.

[실행] python analyze_dtr_within.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from analyze_dtr_premium import COUNTY_STN, load_weather, T_TROPICAL

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "outputs"

MIN_WEEKS = 60        # 이보다 짧은 시군은 평년을 못 잡는다


def weekly_weather() -> pd.DataFrame:
    """시군 × 주 일교차·열대야."""
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
        g = g[g["nday"] >= 5].reset_index()      # 결측 많은 주는 뺀다
        g["county"] = cty
        rows.append(g)
    return pd.concat(rows, ignore_index=True)


def weekly_relative() -> pd.DataFrame:
    """시군 × 주 상대값 — 같은 주·같은 품종·같은 시장 안에서의 비."""
    d = pd.read_csv(RAW / "lettuce_daily_raw.csv", low_memory=False,
                    usecols=["date", "market_cd", "county", "variety",
                             "price_kg", "qty_kg"],
                    dtype={"market_cd": str})
    d = d[d["county"].notna()].dropna(subset=["price_kg", "qty_kg"])
    d = d[(d["qty_kg"] > 0) & (d["price_kg"] > 0)]
    d["date"] = pd.to_datetime(d["date"], format="mixed")
    d["wk"] = d["date"] - pd.to_timedelta(d["date"].dt.weekday, unit="D")
    key = ["wk", "variety", "market_cd"]
    cell = (d.groupby(key + ["county"])
              .apply(lambda g: np.average(g["price_kg"], weights=g["qty_kg"]),
                     include_groups=False)
              .rename("p").reset_index())
    cell = cell[cell.groupby(key)["county"].transform("nunique") >= 2]
    cell["rel"] = cell["p"] / cell.groupby(key)["p"].transform("mean")
    cell["w"] = 1.0
    g = (cell.groupby(["county", "wk"])
             .agg(rel=("rel", "mean"), ncell=("rel", "size")).reset_index())
    return g[g["ncell"] >= 2]


def demean(df: pd.DataFrame, col: str, by=("county", "woy")) -> pd.Series:
    """그 시군·그 주차의 평년을 뺀 편차."""
    return df[col] - df.groupby(list(by))[col].transform("mean")


def boot_by_county(df: pd.DataFrame, xcol: str, ycol: str,
                   n=4000, seed=20260814):
    """시군 단위 블록 부트스트랩. 주 단위로 뽑으면 구간이 좁아진다."""
    rng = np.random.default_rng(seed)
    ctys = df["county"].unique()
    r0 = float(np.corrcoef(df[xcol], df[ycol])[0, 1])
    bs = []
    for _ in range(n):
        pick = rng.choice(ctys, len(ctys), replace=True)
        sub = pd.concat([df[df["county"] == c] for c in pick], ignore_index=True)
        if len(sub) < 30:
            continue
        with np.errstate(invalid="ignore"):
            c = np.corrcoef(sub[xcol], sub[ycol])[0, 1]
        if np.isfinite(c):
            bs.append(c)
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return r0, float(lo), float(hi)


def main() -> None:
    wxw = weekly_weather()
    rel = weekly_relative()
    m = rel.merge(wxw, on=["county", "wk"], how="inner")
    m["woy"] = m["wk"].dt.isocalendar().week.astype(int)
    m = m.sort_values(["county", "wk"]).reset_index(drop=True)

    # 출하 전 누적 — 오늘 일교차가 오늘 값을 바꾸지는 않는다
    for k in (2, 4):
        m[f"dtr{k}"] = (m.groupby("county")["dtr"]
                          .transform(lambda s: s.rolling(k, min_periods=k).mean()))
        m[f"trop{k}"] = (m.groupby("county")["trop"]
                           .transform(lambda s: s.rolling(k, min_periods=k).sum()))
    m["lrel"] = np.log(m["rel"])

    keep = m.groupby("county")["wk"].transform("size") >= MIN_WEEKS
    m = m[keep].dropna(subset=["dtr2", "dtr4", "trop2", "trop4"]).copy()

    # 그 시군·그 주차의 평년을 뺀다
    m["y"] = demean(m, "lrel")
    for c in ("dtr", "dtr2", "dtr4", "trop", "trop2", "trop4"):
        m["d_" + c] = demean(m, c)

    print("=" * 78)
    print("시군 안에서 — 그 주차 평년 대비 편차끼리의 관계")
    print("=" * 78)
    print(f"  표본 {len(m):,}주 · 시군 {m['county'].nunique()}개 "
          f"({m['wk'].min().date()} ~ {m['wk'].max().date()})")
    print()
    print("  가설: 일교차가 평년보다 크면(+) 값도 평년보다 높다(+) -> 양의 관계")
    print("        열대야가 평년보다 많으면(+) 값은 낮다(−)      -> 음의 관계")
    print()
    print(f"  {'변수':<22}{'r':>8}{'95% 구간':>22}   판정")
    for col, lab, want in (("d_dtr", "일교차 (그 주)", +1),
                           ("d_dtr2", "일교차 (2주 누적)", +1),
                           ("d_dtr4", "일교차 (4주 누적)", +1),
                           ("d_trop", "열대야 (그 주)", -1),
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

    # 여름만 따로 — 기작이 여름에 작동한다는 주장이라면 여름에 더 뚜렷해야 한다
    sm = m[m["wk"].dt.month.isin([6, 7, 8, 9])]
    if len(sm) > 200:
        print()
        print(f"  여름(6~9월)만 · {len(sm):,}주")
        for col, lab in (("d_dtr4", "일교차 (4주 누적)"), ("d_trop4", "열대야 (4주 누적)")):
            r, lo, hi = boot_by_county(sm, col, "y")
            v = "양의 관계" if lo > 0 else ("음의 관계" if hi < 0 else "판정불가")
            print(f"  {lab:<22}{r:+8.3f}   [{lo:+.3f}, {hi:+.3f}]   {v}")

    OUT.mkdir(exist_ok=True)
    m.to_csv(OUT / "dtr_within.csv", index=False, encoding="utf-8-sig")
    print(f"\n저장: {OUT/'dtr_within.csv'}")


if __name__ == "__main__":
    main()
