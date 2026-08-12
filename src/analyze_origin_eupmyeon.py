# -*- coding: utf-8 -*-
"""analyze_origin_eupmyeon.py — 산지를 읍면 단위로 쪼개 실제 재배 분포를 파악한다.

────────────────────────────────────────────────────────────────
왜 이걸 봐야 하나
────────────────────────────────────────────────────────────────
시군 단위로만 보면 그 시군 안 **어디서** 나는지 모른다. 그래서 기상 지점을
붙일 때 "남원은 고랭지(운봉)일 것"처럼 짐작하게 되는데, 실측하면 틀린다.

  남원시 상추 출하 비중 (2018-01~2021-02, kg 기준)
      금지면 51.5%  수지면 22.0%   <- 섬진강변 저지대(해발 40~60m)
      운봉읍  0.3%  산내면  0.02%  <- 고랭지. 사실상 없다

즉 남원 상추는 산간이 아니라 서남부 저지대 작목이다. 뱀사골 AWS(479m)를
남원 대표로 쓰려던 계획은 폐기해야 한다.

katSale 응답의 `plor_nm`은 '전북특별자치도 남원시 금지면 귀석리'처럼 **읍면·리까지**
담고 있다. 재배면적 통계가 시도 단위밖에 없다는 제약(HANDOFF_rev2 6.5)을
출하 기준으로 우회할 수 있는 유일한 경로다.

────────────────────────────────────────────────────────────────
주의
────────────────────────────────────────────────────────────────
- `plor_nm`은 **출하자 주소**지 경작지 주소가 아니다. 공동출하·법인 출하는
  사무소 주소로 잡힌다(예: '남원우체국사서함' 5.6%, '전주지방법원남원지원').
  그래서 읍면 미상·기관명 항목을 따로 집계해 규모를 밝힌다.
- 출하량 기준이므로 자가소비·직거래는 안 잡힌다. 도매시장 출하분만이다.

[실행] python analyze_origin_eupmyeon.py
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
RAW = _ROOT / "data" / "raw"
OUT = _ROOT / "outputs"
OUT.mkdir(exist_ok=True)

SRC = RAW / "lettuce_daily_raw.csv"

_SIGUN = re.compile(r"전(?:북특별자치도|라북도|북)\s+([가-힣]+(?:시|군))")
# 읍면동은 시군 바로 뒤 토큰. '리'는 더 뒤라 여기서 안 잡는다.
_EUP = re.compile(r"(?:시|군)\s+([가-힣]+(?:읍|면|동))(?:\s|$)")
# 주소가 아니라 기관·사서함으로 찍힌 것들
_INST = re.compile(r"(사서함|우체국|법원|지원|농협|조합|공사|센터|주식회사|영농)")


def split_origin(s: str) -> tuple[str | None, str | None, str]:
    """plor_nm -> (시군, 읍면동, 분류)."""
    if not isinstance(s, str):
        return None, None, "결측"
    m = _SIGUN.search(s)
    sigun = m.group(1) if m else None
    e = _EUP.search(s)
    eup = e.group(1) if e else None
    if _INST.search(s):
        kind = "기관·공동출하"
    elif eup:
        kind = "읍면동"
    elif sigun:
        kind = "시군만"
    else:
        kind = "미상"
    return sigun, eup, kind


def main() -> None:
    d = pd.read_csv(SRC, dtype={"market_cd": str}, low_memory=False)
    d = d[d["county"].notna()].copy()
    d["date"] = pd.to_datetime(d["date"])
    d["month"] = d["date"].dt.month
    parsed = d["plor_nm"].map(split_origin)
    d["sigun"] = [p[0] for p in parsed]
    d["eup"] = [p[1] for p in parsed]
    d["kind"] = [p[2] for p in parsed]

    tot = d["qty_kg"].sum()
    print("=" * 78)
    print("0. 산지 표기 해상도")
    print("=" * 78)
    k = d.groupby("kind")["qty_kg"].sum().sort_values(ascending=False)
    for nm, v in k.items():
        print(f"  {nm:<14}{v:>14,.0f}kg  {v/tot*100:5.1f}%")
    print(f"  -> 읍면까지 특정되는 물량이 전체의 "
          f"{k.get('읍면동', 0)/tot*100:.1f}%")

    # ── 읍면별 경락가 ───────────────────────────────────────
    print()
    print("=" * 78)
    print("1-A. 읍면별 공판장 경락가 (원/kg, 물량가중) — 물량 상위 20")
    print("=" * 78)
    e = d[d["eup"].notna()].copy()
    rows_p = []
    for (c, ep), g in e.groupby(["county", "eup"]):
        w = g[["price_kg", "qty_kg"]].dropna()
        if w["qty_kg"].sum() <= 0:
            continue
        summer = g[g["month"].isin([7, 8, 9])]
        winter = g[g["month"].isin([12, 1, 2])]

        def wa(x):
            x = x[["price_kg", "qty_kg"]].dropna()
            t = x["qty_kg"].sum()
            return (x["price_kg"] * x["qty_kg"]).sum() / t if t else float("nan")

        rows_p.append({
            "county": c, "eup": ep,
            "price_kg": wa(g), "qty_kg": g["qty_kg"].sum(),
            "n_rec": len(g), "n_months": g["date"].dt.to_period("M").nunique(),
            "price_summer": wa(summer), "price_winter": wa(winter),
            "n_markets": g["market_cd"].nunique(),
        })
    pe = pd.DataFrame(rows_p).sort_values("qty_kg", ascending=False)
    pe["share"] = pe["qty_kg"] / pe["qty_kg"].sum() * 100
    pe["summer_ratio"] = pe["price_summer"] / pe["price_winter"]
    print(f"  {'시군':<7}{'읍면':<7}{'원/kg':>7}{'물량t':>8}{'비중':>7}"
          f"{'월수':>5}{'시장':>5}{'여름':>7}{'겨울':>7}{'여름/겨울':>9}")
    for _, r in pe.head(20).iterrows():
        print(f"  {r['county']:<7}{r['eup']:<7}{r['price_kg']:>7,.0f}"
              f"{r['qty_kg']/1000:>8,.0f}{r['share']:>6.1f}%{r['n_months']:>5.0f}"
              f"{r['n_markets']:>5.0f}{r['price_summer']:>7,.0f}"
              f"{r['price_winter']:>7,.0f}{r['summer_ratio']:>8.2f}배")
    pe.to_csv(OUT / "price_by_eupmyeon.csv", index=False, encoding="utf-8-sig")

    # ── 시군별 읍면 구성 ────────────────────────────────────
    print()
    print("=" * 78)
    print("1. 시군별 주요 읍면 (물량 상위, 괄호는 시군내 비중)")
    print("=" * 78)
    order = d.groupby("county")["qty_kg"].sum().sort_values(ascending=False)
    rows = []
    for c in order.index:
        g = d[d["county"] == c]
        if g["qty_kg"].sum() < tot * 0.001:
            continue
        e = g[g["eup"].notna()].groupby("eup")["qty_kg"].sum().sort_values(ascending=False)
        share = g["qty_kg"].sum() / tot * 100
        named = e.sum() / g["qty_kg"].sum() * 100 if g["qty_kg"].sum() else 0
        top = "  ".join(f"{nm}({v/e.sum()*100:.0f}%)" for nm, v in e.head(4).items()) \
            if len(e) else "(읍면 미상)"
        print(f"  {c:<7} 전북내 {share:5.2f}%  읍면특정 {named:4.0f}%  | {top}")
        for nm, v in e.items():
            rows.append({"county": c, "eup": nm, "qty_kg": v,
                         "share_in_county": v / e.sum() * 100})
    pd.DataFrame(rows).to_csv(OUT / "origin_by_eupmyeon.csv", index=False,
                              encoding="utf-8-sig")

    # ── 계절 이동 ───────────────────────────────────────────
    print()
    print("=" * 78)
    print("2. 읍면 단위 계절 이동 — 여름에 산지가 옮겨가는가")
    print("=" * 78)
    print("   전북 전체 상위 읍면의 월별 물량 비중(%)")
    e_all = d[d["eup"].notna()].copy()
    e_all["key"] = e_all["county"].str[:2] + "·" + e_all["eup"]
    top_keys = e_all.groupby("key")["qty_kg"].sum().sort_values(ascending=False).head(10)
    piv = e_all.pivot_table(index="month", columns="key", values="qty_kg", aggfunc="sum")
    piv = piv.reindex(columns=top_keys.index).fillna(0)
    sh = piv.div(piv.sum(axis=1), axis=0) * 100
    print("   월 | " + " ".join(f"{k[:7]:>8s}" for k in top_keys.index))
    for m in range(1, 13):
        if m not in sh.index:
            continue
        print(f"   {m:2d} | " + " ".join(f"{sh.loc[m, k]:7.1f}%" for k in top_keys.index))

    # 여름(7~8월) vs 겨울(12~2월) 비중 변화가 큰 읍면
    print()
    print("   여름(7~8월) - 겨울(12~2월) 비중 변화 상위/하위")
    summer = sh.loc[[m for m in (7, 8) if m in sh.index]].mean()
    winter = sh.loc[[m for m in (12, 1, 2) if m in sh.index]].mean()
    diff = (summer - winter).sort_values()
    for k, v in list(diff.items())[:3] + list(diff.items())[-3:]:
        arrow = "여름에 감소" if v < 0 else "여름에 증가"
        print(f"     {k:<14}{v:+6.1f}%p  {arrow}  "
              f"(겨울 {winter[k]:.1f}% -> 여름 {summer[k]:.1f}%)")

    # ── 남원 정밀 ───────────────────────────────────────────
    print()
    print("=" * 78)
    print("3. 남원 — 저지대 vs 고랭지 (기상지점 선택 근거)")
    print("=" * 78)
    LOW = {"금지면", "수지면", "송동면", "주생면", "대강면", "동충동", "금동",
           "왕정동", "신정동", "하정동", "갈치동", "사매면", "보절면", "이백면"}
    HIGH = {"운봉읍", "인월면", "아영면", "산내면", "산동면", "주천면", "덕과면"}
    n = d[d["county"] == "남원시"]
    ne = n[n["eup"].notna()]
    lo = ne[ne["eup"].isin(LOW)]["qty_kg"].sum()
    hi = ne[ne["eup"].isin(HIGH)]["qty_kg"].sum()
    un = n["qty_kg"].sum() - lo - hi
    t = n["qty_kg"].sum()
    print(f"   저지대(금지·수지 등)  {lo:>12,.0f}kg  {lo/t*100:5.1f}%")
    print(f"   고랭지(운봉·인월·아영) {hi:>12,.0f}kg  {hi/t*100:5.1f}%")
    print(f"   미상·기관            {un:>12,.0f}kg  {un/t*100:5.1f}%")
    print()
    print("   월별 고랭지 비중(%) — 여름에 올라가는지 확인")
    mm = ne.groupby("month").apply(
        lambda x: x[x["eup"].isin(HIGH)]["qty_kg"].sum() / x["qty_kg"].sum() * 100,
        include_groups=False)
    print("     " + " ".join(f"{m:>6d}" for m in range(1, 13)))
    print("     " + " ".join(f"{mm.get(m, float('nan')):5.1f}%" for m in range(1, 13)))
    print()
    print(f"   -> 고랭지 비중이 연중 {hi/t*100:.1f}%에 불과하다. 남원 기상지점은")
    print(f"      ASOS 247(시내 133m)이 타당하고, 뱀사골 AWS 759(479m)는 부적합하다.")

    print()
    print(f"저장: outputs/origin_by_eupmyeon.csv")


if __name__ == "__main__":
    main()
