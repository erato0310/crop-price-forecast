# -*- coding: utf-8 -*-
"""diagnose_october.py — 10월 오차가 왜 압도적으로 큰가.

────────────────────────────────────────────────────────────────
문제
────────────────────────────────────────────────────────────────
out-of-fold 월별 오차(2020~2025)에서 10월이 독보적이다.

    월      1     7     9    10
  계절평균 27.0  33.3  33.3  63.1
  가격시차 30.8  29.8  25.6  40.7

rev2는 8~9월 고온에 집중했는데 실제 최대 난제는 10월이다. 아무도 안 본 구간이다.

[가설]
  H1 수준 변동성  10월 가격의 연도 간 편차 자체가 크다 (평균으로 못 맞힘)
  H2 전환점       9월 정점에서 11월 저점으로 급락하는 구간이라 시차가 안 먹는다
  H3 추석 이동    추석이 9월/10월을 오가며 수요·휴장이 옮겨다닌다
  H4 산지 전환    고랭지 -> 평지 가을작기 전환기라 공급 주체가 바뀐다
  H5 표본         10월 거래일·물량이 특별히 적다

[실행] python diagnose_october.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import lettuce_cv as CV
from scrape_lettuce_daily import MAIN_VARIETIES

_ROOT = Path(__file__).resolve().parent.parent
SRC = _ROOT / "data" / "raw" / "lettuce_daily_raw.csv"
OUT = _ROOT / "outputs"

# 추석 당일 (음력 8/15). 2018~2026 실제 날짜.
CHUSEOK = {2018: "09-24", 2019: "09-13", 2020: "10-01", 2021: "09-21",
           2022: "09-10", 2023: "09-29", 2024: "09-17", 2025: "10-06",
           2026: "09-25"}


def _wavg(g, p="price_kg", q="qty_kg"):
    x = g[[p, q]].dropna()
    t = x[q].sum()
    return (x[p] * x[q]).sum() / t if t else np.nan


def main() -> None:
    d = pd.read_csv(SRC, dtype={"market_cd": str}, low_memory=False)
    d = d[d["variety"].isin(MAIN_VARIETIES)]
    d["date"] = pd.to_datetime(d["date"], format="mixed")
    d["ym"] = d["date"].dt.to_period("M")
    jb = d[d["county"].notna()].copy()

    m = []
    for ym, g in jb.groupby("ym"):
        m.append({"ym": ym, "year": ym.year, "month": ym.month,
                  "price": _wavg(g), "qty": g["qty_kg"].sum(),
                  "n_days": g["date"].nunique(), "n_obs": len(g)})
    mm = pd.DataFrame(m)
    mm = mm[mm["ym"] != pd.Timestamp.today().to_period("M")]

    # ── H1 변동성 ───────────────────────────────────────────
    print("=" * 78)
    print("H1. 10월 가격의 연도 간 변동성이 큰가")
    print("=" * 78)
    s = mm.groupby("month")["price"].agg(["mean", "std", "min", "max"])
    s["cv%"] = s["std"] / s["mean"] * 100
    print(f"  {'월':>3}{'평균':>9}{'표준편차':>9}{'변동계수':>9}{'최소':>9}{'최대':>9}{'최대/최소':>9}")
    for x in range(1, 13):
        r = s.loc[x]
        print(f"  {x:>3}{r['mean']:>9,.0f}{r['std']:>9,.0f}{r['cv%']:>8.1f}%"
              f"{r['min']:>9,.0f}{r['max']:>9,.0f}{r['max']/r['min']:>8.1f}x")
    print()
    print("  10월 연도별 실제 가격")
    o = mm[mm["month"] == 10].sort_values("year")
    print("    " + "  ".join(f"{int(r.year)}:{r.price:,.0f}" for _, r in o.iterrows()))

    # ── H2 전환점 ───────────────────────────────────────────
    print()
    print("=" * 78)
    print("H2. 전환점 구간인가 — 전월 대비 변화율")
    print("=" * 78)
    mm = mm.sort_values("ym").reset_index(drop=True)
    mm["chg"] = mm["price"] / mm["price"].shift(1) - 1
    c = mm.groupby("month")["chg"].agg(["mean", "std"])
    print(f"  {'월':>3}{'평균변화':>10}{'변화의 편차':>12}   해석")
    for x in range(1, 13):
        r = c.loc[x]
        tag = ""
        if abs(r["mean"]) > 0.25:
            tag = "급등" if r["mean"] > 0 else "급락"
        if r["std"] > 0.25:
            tag += " 편차큼"
        print(f"  {x:>3}{r['mean']*100:>+9.1f}%{r['std']*100:>11.1f}%   {tag}")
    print()
    print("  -> 평균 변화가 크면서 편차도 크면, 방향은 알아도 폭을 못 맞힌다")

    # ── H3 추석 ─────────────────────────────────────────────
    print()
    print("=" * 78)
    print("H3. 추석 이동 — 추석이 낀 달이 어긋나는가")
    print("=" * 78)
    ch = {y: pd.Timestamp(f"{y}-{md}") for y, md in CHUSEOK.items()}
    mm["chuseok_m"] = mm["year"].map(lambda y: ch[y].month if y in ch else np.nan)
    mm["is_chuseok"] = (mm["month"] == mm["chuseok_m"]).astype(int)
    print(f"  연도별 추석: " + "  ".join(f"{y}:{v.strftime('%m-%d')}"
                                       for y, v in sorted(ch.items())))
    print()
    for x in (9, 10):
        g = mm[mm["month"] == x]
        a = g[g["is_chuseok"] == 1]["price"]
        b = g[g["is_chuseok"] == 0]["price"]
        print(f"  {x}월: 추석 낀 해 {a.mean():,.0f}원 (n={len(a)})  vs "
              f"안 낀 해 {b.mean():,.0f}원 (n={len(b)})  "
              f"차이 {(a.mean()/b.mean()-1)*100:+.1f}%")
    print("  -> 추석이 9월/10월을 오가므로, 달력월 평균은 두 상태를 섞어버린다")

    # ── H4 산지 전환 ────────────────────────────────────────
    print()
    print("=" * 78)
    print("H4. 산지 구성 전환 — 10월에 공급 주체가 바뀌는가")
    print("=" * 78)
    d["sido_g"] = d["sido"].fillna("미상").str.replace(
        "특별자치도|특별자치시|특별시|광역시", "", regex=True)
    piv = d.pivot_table(index=d["date"].dt.month, columns="sido_g",
                        values="qty_kg", aggfunc="sum")
    sh = piv.div(piv.sum(axis=1), axis=0) * 100
    keep = sh.mean().sort_values(ascending=False).head(5).index
    print("  전국 산지 점유율(%)  " + " ".join(f"{c[:4]:>7s}" for c in keep)
          + "   전월대비 최대변화")
    prev = None
    for x in range(1, 13):
        row = sh.loc[x, keep]
        chg = "" if prev is None else f"{(row - prev).abs().max():>+6.1f}%p"
        print(f"    {x:2d}월              " + " ".join(f"{row[c]:6.1f}%" for c in keep)
              + f"   {chg}")
        prev = row

    # ── H5 표본 ─────────────────────────────────────────────
    print()
    print("=" * 78)
    print("H5. 10월 표본이 얇은가")
    print("=" * 78)
    q = mm.groupby("month")[["n_days", "n_obs", "qty"]].mean()
    print(f"  {'월':>3}{'거래일':>8}{'레코드':>9}{'물량t':>10}")
    for x in range(1, 13):
        r = q.loc[x]
        print(f"  {x:>3}{r['n_days']:>8.1f}{r['n_obs']:>9,.0f}{r['qty']/1000:>10,.0f}")

    # ── 종합: 베이스라인 오차 분해 ──────────────────────────
    print()
    print("=" * 78)
    print("종합 — 계절평균이 10월에 왜 63% 틀리나")
    print("=" * 78)
    print("  계절평균은 '그 달 과거 평균'이다. 그 달의 연도 간 편차가 크면 원리적으로 못 맞힌다.")
    for x in (1, 7, 9, 10, 11):
        g = mm[mm["month"] == x].sort_values("year")
        vals = g["price"].values
        loo = [np.mean(np.delete(vals, i)) for i in range(len(vals))]
        err = np.mean(np.abs((np.array(loo) - vals) / vals)) * 100
        print(f"  {x:2d}월  연도별 {' '.join(f'{v:,.0f}' for v in vals)}")
        print(f"        leave-one-out 계절평균 오차 {err:.1f}%")


if __name__ == "__main__":
    main()
