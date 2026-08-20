# -*- coding: utf-8 -*-
"""analyze_namwon_shift.py — 남원 '산간 전환'의 정체를 가린다.

────────────────────────────────────────────────────────────────
왜
────────────────────────────────────────────────────────────────
HANDOFF 10.5에 이렇게 적혀 있다.

    남원 산지가 구조 변화 중. 산간 비중이 5%(2018) -> 28%(2026).
    운봉읍이 2023년 0톤에서 2026년 1,193톤으로 급증했고,
    물량의 86.3%가 부산엄궁행이다.

새 산지가 생긴 것이면 큰 이야기다. 지리산 고원으로 재배가 올라가는 중이라면
여름 고온기 공급처가 바뀌는 것이고, 지역추천과 급등기 해석이 전부 달라진다.

그런데 katSale의 산지는 **출하자 주소지이지 경작지 주소가 아니다**(HANDOFF 10.6).
공동출하·법인 출하는 사무소 주소로 잡힌다. 그래서 '새 산지'와 '같은 출하자의
주소 변경'이 자료에서 똑같이 생겼다. 갈라야 한다.

────────────────────────────────────────────────────────────────
결론 — 라벨 이동이다. 새 산지가 아니다
────────────────────────────────────────────────────────────────
부산엄궁 한 시장만 떼어 보면 대체가 그대로 드러난다(톤).

    연도     2018 2019 2020 2021 2022 2023  2024 2025 2026
    금지면    419  546  511  544  559  585   128    0    0
    운봉읍      0    0    0    0    0    0   394  876  997

6년간 그 시장에 500톤대를 보내던 금지면이 2025년부터 **정확히 0**이 되고,
운봉읍이 같은 시장에서 같은 규모로 나타난다. 창원내서에서도 한 해 늦게 같은 일이
일어난다. 그리고 넷이 더 맞는다.

1. **끊김이 없다.** 2024-04까지 금지면, 2024-05 한 달 공백, 2024-06부터 운봉읍.
   물량 수준도 이어진다.
2. **지문이 같다.** 전환 전(금지면 2021~23) / 후(운봉 2025~26)
   상자 2kg 100% / 100%, 경매 100% / 100%, 상등급 98% / 100%.
   2kg 100%는 흔한 조합이 아니다 — 전북 평균은 4kg이 주력이다(HANDOFF 1-F).
3. **라벨에 리(里)가 없다.** 운봉 2,624톤 중 2,624톤이 `남원시 운봉읍`까지만이고
   `동천리`가 붙은 것은 3.3톤뿐이다. 개별 농가가 아니라 한 곳에서 나온 표기다.
4. **연중 출하다.** 2025년 1월 26t · 4월 69t · 7월 114t · 12월 76t.
   해발 500m 운봉고원의 노지 고랭지 작기라면 여름에 몰려야 한다. 연중이면 시설인데,
   시설을 새로 지어 1년 만에 900톤을 내는 것보다 주소가 바뀐 쪽이 훨씬 간단하다.

**단, 밭이 실제로 옮겨갔을 가능성을 이 자료로 완전히 배제하지는 못한다.**
말할 수 있는 것은 '출하 경로가 끊김 없이 이어졌고 포장·등급·거래 방식이 그대로'라는
것까지다. 그러므로 **새 산지로 세지 않는다.**

────────────────────────────────────────────────────────────────
그래서 산간 비중은
────────────────────────────────────────────────────────────────
운봉의 경남 채널(부산엄궁+창원내서)을 원래 라벨로 되돌리면:

    2018 산간 5.4%  ->  2025 산간 23.9% (겉보기)
                    ->  2025 산간  9.8% (보정)

(2026은 자료 끝까지라 연간이 아니어서 마지막 완전 연도인 2025로 적는다.)

보정하면 **8년간 5.4% -> 9.8%**다. 늘긴 늘었고 그건 진짜다 — 아영면이
135t에서 288t으로 커졌고 광주서부로 간다. 하지만 '구조 변화'라 부를 크기가 아니다.
겉보기 28%의 4분의 3은 라벨 하나가 만든 것이다.

> 산간 읍면 목록(운봉읍·인월면·아영면·산내면)은 **사람 판단이다.** 자료에 고도가
> 없어 열거로 정할 수 없었다. `audit_hardcoded_lists.py`의 '사람 판단' 절에 넣었다.

[실행] python analyze_namwon_shift.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_origin_eupmyeon import _EUP          # 읍면 파싱은 한 곳에서만 정의한다
from scrape_lettuce_daily import MARKETS

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "lettuce_daily_raw.csv"
OUT = ROOT / "outputs"

COUNTY = "남원"
# 지리산 동북부 운봉고원 일대. 자료에 고도가 없어 지명으로 골랐다 — 사람 판단이다.
MOUNTAIN_EUP = ("운봉읍", "인월면", "아영면", "산내면")
SWITCH_MARKETS = ("부산엄궁", "창원내서")     # 운봉 물량의 99%가 가는 곳


def load() -> pd.DataFrame:
    m = {v: k for k, v in MARKETS.items()}
    cols = ["date", "county", "plor_nm", "variety", "grade", "trd_se",
            "qty_kg", "price_kg", "unit_qty", "market_cd"]
    it = pd.read_csv(RAW, usecols=cols, chunksize=400_000)
    d = pd.concat([c[c["county"].astype(str).str.contains(COUNTY, na=False)] for c in it])
    d["date"] = pd.to_datetime(d["date"])
    d["year"] = d["date"].dt.year
    d["mkt"] = d["market_cd"].astype(str).map(m).fillna(d["market_cd"].astype(str))
    d["eup"] = d["plor_nm"].map(
        lambda s: (_EUP.search(str(s)).group(1) if _EUP.search(str(s)) else "(읍면 미기재)"))
    return d


def h(t: str) -> None:
    print("\n" + "=" * 74 + f"\n{t}\n" + "=" * 74)


def main() -> None:
    d = load()
    OUT.mkdir(exist_ok=True)
    print(f"남원 {len(d):,}행 / {d.date.min().date()} ~ {d.date.max().date()}")
    print("※ 2026년은 자료 마지막 날까지라 연간 합계가 아니다")

    # ── 1. 읍면별 연도별 물량 ─────────────────────────────────
    h("1. 읍면별 연도별 물량 (톤)")
    t = (d.pivot_table(index="eup", columns="year", values="qty_kg", aggfunc="sum")
         .div(1000).fillna(0))
    t["합계"] = t.sum(axis=1)
    t = t.sort_values("합계", ascending=False)
    print(t.head(10).round(0).to_string())
    t.round(1).to_csv(OUT / "namwon_eup_yearly.csv", encoding="utf-8-sig")

    # ── 2. 전환의 증거 — 시장별 대조 ──────────────────────────
    h("2. 운봉 등장의 정체 — 경남 두 시장에서 금지면이 그대로 대체된다 (톤)")
    rows = []
    for mk in SWITCH_MARKETS:
        g = d[d["mkt"] == mk]
        p = (g.pivot_table(index="eup", columns="year", values="qty_kg", aggfunc="sum")
             .div(1000).fillna(0))
        keep = [e for e in ("금지면", "운봉읍") if e in p.index]
        print(f"\n[{mk}]")
        print(p.loc[keep].round(0).to_string())
        for e in keep:
            for y, v in p.loc[e].items():
                rows.append({"market": mk, "eup": e, "year": int(y), "ton": round(v, 1)})
    pd.DataFrame(rows).to_csv(OUT / "namwon_channel_switch.csv",
                              index=False, encoding="utf-8-sig")

    # ── 3. 끊김 없음 ─────────────────────────────────────────
    h("3. 끊김이 없다 — 부산엄궁 남원 월물량 (톤)")
    w = d[(d["mkt"] == "부산엄궁") & (d["date"] >= "2024-01-01") & (d["date"] < "2025-04-01")]
    p = (w.pivot_table(index="eup", columns=w["date"].dt.to_period("M").astype(str),
                       values="qty_kg", aggfunc="sum").div(1000).fillna(0))
    p.loc["합계"] = p.sum()
    print(p.round(1).to_string())
    print("\n  2024-05가 통째로 비어 있고(그 달 남원->부산엄궁 출하 자체가 없다),")
    print("  그 앞은 전부 금지면, 그 뒤는 전부 운봉읍이다.")

    # ── 4. 지문 대조 ─────────────────────────────────────────
    h("4. 지문 대조 — 같은 출하자인가")
    e = d[d["mkt"] == "부산엄궁"]
    pre = e[(e["eup"] == "금지면") & (e["year"].between(2021, 2023))]
    post = e[(e["eup"] == "운봉읍") & (e["year"] >= 2025)]
    for g, name in ((pre, "금지면 2021~2023 (전환 전)"), (post, "운봉읍 2025~2026 (전환 후)")):
        q = g["qty_kg"].sum()
        def top(col, n=3, unit=""):
            s = g.groupby(col)["qty_kg"].sum().div(q).mul(100).sort_values(ascending=False)
            return " · ".join(f"{k}{unit} {v:.0f}%" for k, v in s.head(n).items())
        print(f"\n  {name}  {q/1000:,.0f}t / {len(g):,}행")
        print(f"    품종  {top('variety')}")
        print(f"    등급  {top('grade')}")
        print(f"    상자  {top('unit_qty', 2, 'kg')}")
        print(f"    거래  {top('trd_se', 2)}")

    # ── 5. 산간 비중 — 겉보기와 보정 ─────────────────────────
    h("5. 산간 비중 — 겉보기 vs 라벨 보정")
    tot = d.groupby("year")["qty_kg"].sum()
    mt = d[d["eup"].isin(MOUNTAIN_EUP)].groupby("year")["qty_kg"].sum()
    # 되돌릴 몫: 운봉이 경남 두 시장에 낸 물량 = 원래 금지면 라벨이던 채널
    back = (d[(d["eup"] == "운봉읍") & (d["mkt"].isin(SWITCH_MARKETS))]
            .groupby("year")["qty_kg"].sum().reindex(tot.index).fillna(0))
    r = pd.DataFrame({
        "남원_총물량t": tot / 1000,
        "산간_겉보기t": mt.reindex(tot.index).fillna(0) / 1000,
        "라벨이동분t": back / 1000,
    })
    r["산간_보정t"] = r["산간_겉보기t"] - r["라벨이동분t"]
    r["겉보기_%"] = r["산간_겉보기t"] / r["남원_총물량t"] * 100
    r["보정_%"] = r["산간_보정t"] / r["남원_총물량t"] * 100
    print(r.round(1).to_string())
    r.round(2).to_csv(OUT / "namwon_mountain_share.csv", encoding="utf-8-sig")

    # 마지막 해는 자료 끝까지라 연간이 아니다 — 결론은 마지막 '완전' 연도로 낸다.
    first, last_full = r.index.min(), r.index.max() - 1
    a, b = r.loc[first], r.loc[last_full]
    print(f"\n  {first} {a['겉보기_%']:.1f}%  ->  {last_full} "
          f"겉보기 {b['겉보기_%']:.1f}% / 보정 {b['보정_%']:.1f}%   (마지막 완전 연도)")
    print("  HANDOFF 10.5의 '5% -> 28%'는 라벨 이동을 산지 이동으로 읽은 것이다.")
    print(f"  다만 보정해도 {a['보정_%']:.1f}% -> {b['보정_%']:.1f}%로 늘긴 했다. 이건 진짜다")
    print("  (아영면 135->288t, 광주서부행). '구조 변화'라 부를 크기는 아니다.")

    print(f"\n저장: namwon_eup_yearly.csv · namwon_channel_switch.csv · "
          f"namwon_mountain_share.csv ({OUT})")


if __name__ == "__main__":
    main()
