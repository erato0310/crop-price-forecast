# -*- coding: utf-8 -*-
"""export_destinations.py — 어느 도매시장으로 나가고 무슨 품종으로 나가는가.

────────────────────────────────────────────────────────────────
왜 필요한가
────────────────────────────────────────────────────────────────
값이 얼마인지는 보여 주면서 **어디로 보내는지**를 안 보여 주고 있었다.
농가에는 이게 값만큼 중요하다. 같은 상추라도 광주로 가느냐 가락으로 가느냐에
따라 운임도 받는 값도 달라진다.

품종도 마찬가지다. 웹앱에 품종 카드가 있긴 했는데 **기간 버튼을 무시하고
전 기간 고정**이라 위쪽 표와 다른 기간을 말하고 있었다. 여기서 같이 고친다.

────────────────────────────────────────────────────────────────
기간
────────────────────────────────────────────────────────────────
웹앱 기간 버튼과 **같은 창**으로 미리 계산해 둔다(8주/6개월/1년/3년/전체).
주 단위 원자료를 그대로 실으면 파일이 커지고, 기간마다 다시 세는 것은
브라우저에서 할 일이 아니다. 직접 지정한 구간은 '전체'로 보여 주고
화면에 그렇게 적는다 — 슬쩍 다른 기간을 보여 주면 안 된다.

────────────────────────────────────────────────────────────────
주의
────────────────────────────────────────────────────────────────
시장별 평균가는 **그 시장이 더 쳐준다는 뜻이 아니다.** 품종·등급·출하 시기가
시장마다 다르고, 여름에 몰아 보낸 시장은 그만큼 높게 잡힌다. 화면에도 적었다.

[실행] python export_destinations.py
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "webapp" / "data" / "lettuce_destinations.json"

# 시장 코드 -> 이름. 두 수집기에 흩어져 있던 것을 합친다.
# **자료에 있는 코드가 여기 없으면 실행을 멈춘다** — 이름을 지어내지 않는다.
from scrape_lettuce_daily import MARKETS                      # noqa: E402
from scrape_supplementary_markets import SUPP_MARKETS         # noqa: E402
from export_lettuce_webapp import extract_eup                 # noqa: E402

CODE_TO_MARKET = {v: k for k, v in {**MARKETS, **SUPP_MARKETS}.items()}

# 웹앱 기간 버튼과 같은 창. 값은 주 수, 0은 전체.
HORIZONS = {"8": 8, "26": 26, "53": 53, "157": 157, "0": 0}
TOP_N = 6          # 이보다 많으면 '그 밖'으로 묶는다


def load() -> pd.DataFrame:
    d = pd.read_csv(RAW / "lettuce_daily_raw.csv",
                    dtype={"market_cd": str, "plor_cd": str}, low_memory=False,
                    usecols=["date", "market_cd", "county", "plor_nm", "variety",
                             "price_kg", "qty_kg"])
    d = d[d["county"].notna()].copy()
    d["date"] = pd.to_datetime(d["date"], format="mixed")
    d = d.dropna(subset=["qty_kg"])
    d = d[d["qty_kg"] > 0]
    unknown = sorted(set(d["market_cd"].dropna()) - set(CODE_TO_MARKET))
    if unknown:
        raise SystemExit(
            f"이름을 모르는 시장 코드가 있습니다: {unknown}\n"
            "scrape_lettuce_daily.MARKETS 또는 scrape_supplementary_markets."
            "SUPP_MARKETS 에 추가한 뒤 다시 실행하세요. 임의로 이름을 붙이지 않습니다.")
    d["market"] = d["market_cd"].map(CODE_TO_MARKET)
    d["eup"] = [extract_eup(p, c) for p, c in zip(d["plor_nm"], d["county"])]
    d["wk"] = d["date"] - pd.to_timedelta(d["date"].dt.weekday, unit="D")
    return d


def variety_of(g: pd.DataFrame, n: int = 3) -> list:
    """그 시장으로 간 물량의 품종 구성 상위 n종. [이름, 비중%, 원/kg] 배열로 담는다.

    키 있는 객체로 담으면 같은 내용이 파일에서 세 배가 된다. 시장마다 붙는
    자료라 개수가 많다 — 여기서는 배열이 맞다.
    """
    tot = g["qty_kg"].sum()
    if not tot:
        return []
    rows = []
    for name, sub in g.groupby("variety"):
        q = sub["qty_kg"].sum()
        x = sub[["price_kg", "qty_kg"]].dropna()
        p = (x["price_kg"] * x["qty_kg"]).sum() / x["qty_kg"].sum() if x["qty_kg"].sum() else np.nan
        rows.append((str(name), q, p))
    rows.sort(key=lambda r: -r[1])
    # 3% 미만은 뺀다. 0.5%짜리까지 붙이면 줄만 길어지고 읽는 사람에게 쓸모가 없다.
    return [[nm, round(q / tot * 100, 1), None if pd.isna(p) else round(float(p))]
            for nm, q, p in rows[:n] if q / tot >= 0.03]


def top_mix(g: pd.DataFrame, key: str, n: int = TOP_N) -> list:
    """(이름, 물량t, 비중%, 평균원/kg) 상위 n개 + 그 밖."""
    tot = g["qty_kg"].sum()
    if not tot:
        return []
    rows = []
    for name, sub in g.groupby(key):
        q = sub["qty_kg"].sum()
        x = sub[["price_kg", "qty_kg"]].dropna()
        p = (x["price_kg"] * x["qty_kg"]).sum() / x["qty_kg"].sum() if x["qty_kg"].sum() else np.nan
        rows.append((str(name), q, p))
    rows.sort(key=lambda r: -r[1])
    out, rest = [], rows[n:]
    for name, q, p in rows[:n]:
        e = {"name": name, "t": round(q / 1000, 1),
             "share": round(q / tot * 100, 1),
             "price": None if pd.isna(p) else round(float(p))}
        # 시장 줄에는 그 시장으로 간 물량의 품종 구성을 붙인다.
        # 꼬리(1% 미만)까지 붙이면 파일만 커지고 읽히지도 않는다.
        if key == "market" and q / tot >= 0.01:
            e["v"] = variety_of(g[g[key] == name])
        out.append(e)
    if rest:
        q = sum(r[1] for r in rest)
        pw = [(r[2], r[1]) for r in rest if not pd.isna(r[2])]
        p = sum(a * b for a, b in pw) / sum(b for _, b in pw) if pw else None
        out.append({"name": f"그 밖 {len(rest)}곳", "t": round(q / 1000, 1),
                    "share": round(q / tot * 100, 1),
                    "price": None if p is None else round(float(p)),
                    "rest": [r[0] for r in rest]})
    return out


def pack_unit(g: pd.DataFrame, last_wk) -> dict:
    """한 단위(시군 또는 읍면)를 기간별로 담는다."""
    out = {}
    for key, wks in HORIZONS.items():
        sub = g if not wks else g[g["wk"] > last_wk - pd.Timedelta(weeks=wks)]
        if sub.empty:
            continue
        out[key] = {
            "markets": top_mix(sub, "market"),
            "varieties": top_mix(sub, "variety", 7),
            "t": round(sub["qty_kg"].sum() / 1000, 1),
        }
    return out


def main() -> None:
    d = load()
    last_wk = d["wk"].max()
    print(f"자료 {len(d):,}행 · 마지막 주 {last_wk.date()}")

    counties = {}
    for cname, cg in d.groupby("county"):
        eups = {}
        for ename, eg in cg.groupby("eup"):
            p = pack_unit(eg, last_wk)
            if p:
                eups[str(ename)] = p
        counties[str(cname)] = {"self": pack_unit(cg, last_wk), "eups": eups}
        n = len(counties[str(cname)]["self"].get("0", {}).get("markets", []))
        print(f"  {cname:<7} 읍면 {len(eups):>2}개 · 전 기간 시장 {n}곳")

    payload = {
        "meta": {
            "built": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "last_week": str(last_wk.date()),
            "horizons": list(HORIZONS),
            "markets_named": len(CODE_TO_MARKET),
            "caveat_ko": ("시장별 평균값은 그 시장이 더 쳐준다는 뜻이 아닙니다. "
                          "품종·등급·보내는 철이 시장마다 달라서, 비싼 철에 많이 보낸 "
                          "시장이 그만큼 높게 나옵니다."),
        },
        "counties": counties,
        "jeonbuk": pack_unit(d, last_wk),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    print(f"\n저장: {OUT} ({OUT.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
