# -*- coding: utf-8 -*-
"""analyze_market_choice.py — "어느 도매시장에 내는 게 유리한가"를 검정한다.

────────────────────────────────────────────────────────────────
왜 시장별 평균가를 그대로 비교하면 안 되는가
────────────────────────────────────────────────────────────────
웹앱의 출하처 카드는 시장별 평균값을 보여 준다. 그런데 그 값으로
"광주가 부산보다 쳐준다"고 읽으면 틀린다. 섞여 있는 것이 셋이다.

  1) 품종  — 부산엄궁행은 포기찹 74%, 광주서부행은 청상추 85%다.
             품종이 다르면 값도 다르다.
  2) 시기  — 비싼 철에 많이 보낸 시장은 평균이 저절로 올라간다.
  3) 등급  — 같은 품종이라도 상품/중품이 섞인다(자료에 등급이 있으나
             시장마다 표기가 달라 그대로 비교하기 어렵다).

그래서 **같은 산지·같은 주·같은 품종** 안에서만 시장끼리 비교한다.
같은 밭에서 같은 주에 딴 같은 품종이 서로 다른 시장으로 갈 때
어디가 더 받았는지를 보는 것이다(matched comparison).

────────────────────────────────────────────────────────────────
검정 규칙
────────────────────────────────────────────────────────────────
- 셀(산지·주·품종) 안에 시장이 2곳 이상일 때만 쓴다. 1곳뿐이면 비교가 안 된다.
- 각 시장의 값을 그 셀 평균으로 나눠 **상대값**으로 바꾼 뒤 평균한다.
- 연도 walk-forward로 **과거에서 고른 1등이 다음 해에도 1등인지** 본다.
  이게 핵심이다. 과거 자료로 순위를 매기는 건 누구나 한다.
  그 순위가 다음 해에 쓸모가 있어야 추천이 성립한다.
- 대조군: 그 해 그 산지에서 **물량이 가장 많은 시장**(=관행대로 보내던 곳).
  추천이 관행을 못 이기면 의미가 없다.

[실행]
  python analyze_market_choice.py            # 전부
  python analyze_market_choice.py season     # 시기별 표만
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "outputs"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scrape_lettuce_daily import MARKETS                      # noqa: E402
from scrape_supplementary_markets import SUPP_MARKETS         # noqa: E402

CODE_TO_MARKET = {v: k for k, v in {**MARKETS, **SUPP_MARKETS}.items()}
MIN_CELL_MARKETS = 2      # 셀 안에 시장이 이보다 적으면 비교 불가
MIN_OBS = 30              # 이보다 적은 (산지,시장) 조합은 순위에서 뺀다


def load() -> pd.DataFrame:
    d = pd.read_csv(RAW / "lettuce_daily_raw.csv",
                    dtype={"market_cd": str}, low_memory=False,
                    usecols=["date", "market_cd", "county", "variety",
                             "price_kg", "qty_kg"])
    d = d[d["county"].notna()].dropna(subset=["price_kg", "qty_kg"])
    d = d[(d["qty_kg"] > 0) & (d["price_kg"] > 0)]
    d["date"] = pd.to_datetime(d["date"], format="mixed")
    d["market"] = d["market_cd"].map(CODE_TO_MARKET)
    d = d[d["market"].notna()]
    d["wk"] = d["date"] - pd.to_timedelta(d["date"].dt.weekday, unit="D")
    d["year"] = d["date"].dt.year
    d["month"] = d["date"].dt.month
    return d


def matched(d: pd.DataFrame) -> pd.DataFrame:
    """같은 (산지, 주, 품종) 안에서 시장별 상대값을 만든다."""
    # 먼저 셀×시장 단위로 물량가중 평균가를 낸다
    g = (d.groupby(["county", "wk", "variety", "market", "year", "month"])
           .apply(lambda x: pd.Series({
               "price": np.average(x["price_kg"], weights=x["qty_kg"]),
               "qty": x["qty_kg"].sum()}))
           .reset_index())
    # 셀 안에 시장이 2곳 이상인 것만
    n = g.groupby(["county", "wk", "variety"])["market"].transform("nunique")
    g = g[n >= MIN_CELL_MARKETS].copy()
    # 셀 평균(물량가중) 대비 상대값
    cell = (g.groupby(["county", "wk", "variety"])
              .apply(lambda x: np.average(x["price"], weights=x["qty"]))
              .rename("cell_price").reset_index())
    g = g.merge(cell, on=["county", "wk", "variety"])
    g["rel"] = g["price"] / g["cell_price"]
    return g


def rank_table(g: pd.DataFrame, by_month: bool = False) -> pd.DataFrame:
    keys = ["county", "market"] + (["month"] if by_month else [])
    r = (g.groupby(keys)
           .agg(rel=("rel", "mean"), n=("rel", "size"), qty=("qty", "sum"))
           .reset_index())
    return r[r["n"] >= (10 if by_month else MIN_OBS)]


def describe(g: pd.DataFrame) -> None:
    print("=" * 78)
    print("같은 산지·같은 주·같은 품종 안에서 본 시장별 상대값")
    print("=" * 78)
    print(f"  비교 가능한 셀 {g.groupby(['county','wk','variety']).ngroups:,}개 "
          f"/ 레코드 {len(g):,}건")
    r = rank_table(g)
    for c, sub in r.groupby("county"):
        sub = sub.sort_values("rel", ascending=False)
        if len(sub) < 3:
            continue
        top, bot = sub.iloc[0], sub.iloc[-1]
        print(f"\n  {c}  (시장 {len(sub)}곳)")
        for _, x in sub.iterrows():
            bar = "+" if x["rel"] >= 1 else "-"
            print(f"     {x['market']:<8} {(x['rel']-1)*100:+6.1f}%  "
                  f"n={int(x['n']):>5}  {bar*max(1,int(abs(x['rel']-1)*100))}")
        print(f"     -> 최고 {top['market']} vs 최저 {bot['market']} "
              f"차이 {(top['rel']/bot['rel']-1)*100:.1f}%")
    r.to_csv(OUT / "market_choice_rel.csv", index=False, encoding="utf-8-sig")


def stability(g: pd.DataFrame) -> None:
    """과거로 고른 1등이 다음 해에도 1등인가 — 이게 되어야 추천이 성립한다."""
    print()
    print("=" * 78)
    print("과거로 고른 '가장 잘 받는 시장'이 다음 해에도 통하는가")
    print("=" * 78)
    years = sorted(g["year"].unique())
    rows = []
    for ty in [y for y in years if y >= 2020]:
        tr, te = g[g["year"] < ty], g[g["year"] == ty]
        if tr.empty or te.empty:
            continue
        rtr, rte = rank_table(tr), rank_table(te)
        for c in sorted(set(rtr["county"]) & set(rte["county"])):
            a = rtr[rtr["county"] == c].sort_values("rel", ascending=False)
            b = rte[rte["county"] == c].set_index("market")["rel"]
            if len(a) < 3:
                continue
            pick = a.iloc[0]["market"]                       # 과거 1등
            # 관행 대조군: 그 해 그 산지에서 물량이 가장 많던 시장
            hab = (te[te["county"] == c].groupby("market")["qty"].sum()
                   .sort_values(ascending=False).index[0])
            if pick not in b.index or hab not in b.index:
                continue
            rows.append({"year": ty, "county": c, "pick": pick, "habit": hab,
                         "pick_rel": b[pick], "habit_rel": b[hab],
                         "best_rel": b.max(), "best": b.idxmax(),
                         "hit": int(pick == b.idxmax())})
    R = pd.DataFrame(rows)
    if R.empty:
        print("  검정할 표본이 없다")
        return
    print(f"  표본 {len(R)}건 (연도 x 시군)")
    print(f"  과거 1등이 그 해에도 1등이었던 비율  {R['hit'].mean()*100:.1f}%")
    print(f"  과거 1등을 골랐을 때 얻은 상대값     {R['pick_rel'].mean():.4f}")
    print(f"  관행(물량 최다)을 그대로 썼을 때     {R['habit_rel'].mean():.4f}")
    print(f"  그 해 실제 1등(사후에만 앎)          {R['best_rel'].mean():.4f}")
    diff = (R["pick_rel"] - R["habit_rel"]).to_numpy()
    rng = np.random.default_rng(20260813)
    # 연도 단위 블록 부트스트랩 — 같은 해 시군들은 같은 시황을 공유한다
    yrs = R["year"].unique()
    bs = []
    for _ in range(4000):
        pick_y = rng.choice(yrs, len(yrs), replace=True)
        v = np.concatenate([(R[R["year"] == y]["pick_rel"]
                             - R[R["year"] == y]["habit_rel"]).to_numpy() for y in pick_y])
        bs.append(v.mean())
    lo, hi = np.percentile(bs, [2.5, 97.5])
    verdict = "개선" if lo > 0 else ("악화" if hi < 0 else "판정불가")
    print(f"  추천 - 관행 = {diff.mean()*100:+.2f}%  95% [{lo*100:+.2f}, {hi*100:+.2f}] "
          f"-> {verdict}")
    R.to_csv(OUT / "market_choice_stability.csv", index=False, encoding="utf-8-sig")


def season(g: pd.DataFrame) -> None:
    """시기(월)마다 유리한 시장이 바뀌는가."""
    print()
    print("=" * 78)
    print("달마다 유리한 시장이 바뀌는가 (물량 상위 4개 시군)")
    print("=" * 78)
    r = rank_table(g, by_month=True)
    top_counties = (g.groupby("county")["qty"].sum().sort_values(ascending=False)
                    .index[:4])
    for c in top_counties:
        sub = r[r["county"] == c]
        if sub.empty:
            continue
        piv = sub.pivot(index="month", columns="market", values="rel")
        keep = piv.columns[piv.notna().sum() >= 6]
        piv = piv[keep]
        if piv.empty:
            continue
        print(f"\n  {c}")
        print("    월 " + " ".join(f"{m:>8}" for m in piv.columns))
        for mth, row in piv.iterrows():
            cells = " ".join("      —" if pd.isna(v) else f"{(v-1)*100:+7.1f}%"
                             for v in row)
            best = row.idxmax() if row.notna().any() else "—"
            print(f"    {mth:>2}월 {cells}   <- {best}")
        # 달마다 1등이 실제로 바뀌는가
        winners = piv.idxmax(axis=1).dropna()
        print(f"    달별 1등 종류: {winners.nunique()}가지 "
              f"({', '.join(sorted(set(winners)))})")
    r.to_csv(OUT / "market_choice_by_month.csv", index=False, encoding="utf-8-sig")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", nargs="?", default="all",
                    choices=["all", "describe", "stability", "season"])
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    d = load()
    print(f"전북산 {len(d):,}건 · 시장 {d['market'].nunique()}곳")
    g = matched(d)
    if a.mode in ("all", "describe"):
        describe(g)
    if a.mode in ("all", "stability"):
        stability(g)
    if a.mode in ("all", "season"):
        season(g)


if __name__ == "__main__":
    main()
