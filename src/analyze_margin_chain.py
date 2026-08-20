# -*- coding: utf-8 -*-
"""analyze_margin_chain.py — 산지 경락가 vs 중도매인 판매가 vs 소매가.

────────────────────────────────────────────────────────────────
무엇을 보는가
────────────────────────────────────────────────────────────────
"상추값 올랐다"는 뉴스는 소매가를 말하고, 농가가 받는 것은 경락가다.
둘 사이에 두 단계가 있다.

    우리 자료   전북산 도매시장 **경락가**      농가 수취의 기준
    KAMIS 도매  **중도매인 판매가격**          경매로 산 물건을 소매상에 넘기는 값
    KAMIS 소매  소비자가                      대형마트·전통시장 평균

같은 품종(적상추·청상추)으로 1:1 대응이 된다. 겹치는 기간은
**최근 1년**이다 — KAMIS 일별 자료가 그만큼만 제공된다.

────────────────────────────────────────────────────────────────
주의 — 그대로 빼면 안 되는 것들
────────────────────────────────────────────────────────────────
- KAMIS는 **전국 평균**이고 우리 자료는 **전북산**이다. 지역이 다르다.
- 우리 값은 그 주에 실제로 팔린 물량으로 가중한 값이고, KAMIS는 조사 평균이다.
- 소매가에는 포장·운송·보관·감모·판매 마진이 다 들어 있다. 격차를 그대로
  "누가 가져갔다"로 읽으면 안 된다. 여기서는 **격차의 크기와 움직임**만 본다.
- 등급이 다르다. KAMIS 도·소매는 '상품(上品)' 기준이고 우리 자료는 전 등급이다.

[실행] python analyze_margin_chain.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "outputs"

VARIETIES = ["적상추", "청상추"]


def ours() -> pd.DataFrame:
    """전북산 경락가 — 품종별 주간 물량가중."""
    d = pd.read_csv(RAW / "lettuce_daily_raw.csv", low_memory=False,
                    usecols=["date", "county", "variety", "price_kg", "qty_kg"])
    d = d[d["county"].notna() & d["variety"].isin(VARIETIES)]
    d = d.dropna(subset=["price_kg", "qty_kg"])
    d = d[(d["qty_kg"] > 0) & (d["price_kg"] > 0)]
    d["date"] = pd.to_datetime(d["date"], format="mixed")
    d["wk"] = d["date"] - pd.to_timedelta(d["date"].dt.weekday, unit="D")
    g = (d.groupby(["variety", "wk"])
           .apply(lambda x: pd.Series({
               "산지": np.average(x["price_kg"], weights=x["qty_kg"]),
               "물량t": x["qty_kg"].sum() / 1000}), include_groups=False)
           .reset_index())
    return g


def kamis() -> pd.DataFrame:
    k = pd.read_csv(RAW / "kamis_lettuce_retail.csv", encoding="utf-8-sig")
    k["date"] = pd.to_datetime(k["date"])
    k["wk"] = k["date"] - pd.to_timedelta(k["date"].dt.weekday, unit="D")
    g = (k.groupby(["variety", "cls", "wk"])["price"].mean()
           .unstack("cls").reset_index())
    return g.rename(columns={"도매": "중도매", "소매": "소매"})


def main() -> None:
    o, k = ours(), kamis()
    m = o.merge(k, on=["variety", "wk"], how="inner").dropna(
        subset=["산지", "중도매", "소매"])
    m = m.sort_values(["variety", "wk"])
    print(f"겹치는 기간: {m['wk'].min().date()} ~ {m['wk'].max().date()} "
          f"· 주 {m['wk'].nunique()}개 · 품종 {m['variety'].nunique()}종")

    m["도매배율"] = m["중도매"] / m["산지"]
    m["소매배율"] = m["소매"] / m["산지"]
    m["소매_중도매"] = m["소매"] / m["중도매"]
    m["농가몫%"] = m["산지"] / m["소매"] * 100

    print()
    print("=" * 84)
    print("1. 품종별 평균 (원/kg)")
    print("=" * 84)
    s = m.groupby("variety").agg(
        주=("wk", "size"), 산지=("산지", "mean"), 중도매=("중도매", "mean"),
        소매=("소매", "mean"), 농가몫=("농가몫%", "mean"),
        소매배율=("소매배율", "median"))
    print(s.round(1).to_string())
    print()
    print("  '농가몫'은 소매가 100원 중 산지 경락가가 차지하는 비율이다.")

    print()
    print("=" * 84)
    print("2. 월별 흐름")
    print("=" * 84)
    m["ym"] = m["wk"].dt.strftime("%Y-%m")
    for v in VARIETIES:
        x = m[m["variety"] == v]
        if x.empty:
            continue
        print(f"\n  [{v}]")
        print(f"  {'월':<9}{'산지':>8}{'중도매':>9}{'소매':>9}{'소매배율':>9}{'농가몫%':>9}{'물량t':>9}")
        for ym, g in x.groupby("ym"):
            print(f"  {ym:<9}{g['산지'].mean():8.0f}{g['중도매'].mean():9.0f}"
                  f"{g['소매'].mean():9.0f}{g['소매배율'].median():9.2f}"
                  f"{g['농가몫%'].mean():9.1f}{g['물량t'].sum():9.0f}")

    print()
    print("=" * 84)
    print("3. 산지값이 오를 때 소매값도 같이 오르는가")
    print("=" * 84)
    for v in VARIETIES:
        x = m[m["variety"] == v].sort_values("wk")
        if len(x) < 20:
            continue
        lv = np.corrcoef(x["산지"], x["소매"])[0, 1]
        d1 = x[["산지", "소매"]].diff().dropna()
        ch = np.corrcoef(d1["산지"], d1["소매"])[0, 1]
        # 산지가 크게 오른 주에 배율이 어떻게 되는가
        hi = x[x["산지"] >= x["산지"].quantile(0.8)]
        lo = x[x["산지"] <= x["산지"].quantile(0.2)]
        print(f"  [{v}] 수준 상관 {lv:+.3f} · 주간 변화 상관 {ch:+.3f}")
        print(f"       산지 비쌀 때(상위20%) 소매배율 {hi['소매배율'].median():.2f} "
              f"· 농가몫 {hi['농가몫%'].mean():.1f}%")
        print(f"       산지 쌀 때(하위20%)  소매배율 {lo['소매배율'].median():.2f} "
              f"· 농가몫 {lo['농가몫%'].mean():.1f}%")

    OUT.mkdir(exist_ok=True)
    m.to_csv(OUT / "margin_chain.csv", index=False, encoding="utf-8-sig")
    print(f"\n저장: {OUT/'margin_chain.csv'}")
    print()
    print("  주의 — KAMIS는 전국 평균·상품(上品) 기준이고 우리 자료는 전북산·전 등급이다.")
    print("  격차를 '누가 가져갔다'로 읽으면 안 된다. 크기와 움직임만 본다.")


if __name__ == "__main__":
    main()
