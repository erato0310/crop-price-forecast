# -*- coding: utf-8 -*-
"""fetch_competitor_weather.py — 경쟁 산지(노지 비중 높은 지역) 기상 수집.

────────────────────────────────────────────────────────────────
왜 전북 기상이 안 먹혔는지에 대한 재해석
────────────────────────────────────────────────────────────────
생리 가설 9종을 전부 기각했는데, 그 기상은 **전부 전북 관측소**였다.
그런데 전북 상추는 시설 93.5%다 — **보호받는 쪽**이다.

  시도       노지ha   시설ha   시설%     여름 점유율 변화(1월->7월)
  전라북도       95   1,376   93.5%    24.1% -> 32.7%  (오히려 증가)
  충청남도       86     954   91.8%    16.7% -> 19.8%
  경기도        253     498   66.3%    24.9% -> 10.9%  (붕괴)
  강원도        158      15    8.7%     0.0% -> 12.2%  (여름에만)
  경상북도      119     126   51.4%

상추는 저온성 작물이라 노지에서는 고온기에 **녹거나 추대**해 상품성을 잃는다.
시설은 환기·차광·포그로 버틴다. 따라서 고온이 가격을 올리는 경로는

    전북 시설이 더워져서(X)  ->  전북 공급 감소
    경기·경북 **노지**가 무너져서(O)  ->  전국 공급 감소  ->  전북도 가격 상승

전북은 오히려 **수혜자**다(여름에 점유율이 24.1%->32.7%로 오른다).
그러므로 설명변수는 전북 기상이 아니라 **노지 산지의 기상**이어야 한다.

────────────────────────────────────────────────────────────────
핵심 구성물: 노지가중 고온 노출
────────────────────────────────────────────────────────────────
    노지가중_고온 = sum_시도 ( 시도 노지면적 비중 x 시도 고온일수 )

'전국의 무방비 상추 중 얼마나 많은 부분이 고온 스트레스를 받았나'를 직접 잰다.
시설 면적은 가중치에서 뺀다 — 보호받으므로.

강원은 반대 방향으로도 본다. 고랭지 노지가 여름 공급의 버퍼인데, **강원이
서늘해야** 그 버퍼가 작동한다. 강원이 더우면 마지막 피난처마저 막힌다.

[실행] python fetch_competitor_weather.py fetch
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
import urllib.parse
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")
KEY = urllib.parse.unquote(os.getenv("DATA_GO_KR_KEY", ""))
URL = "https://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"
OUT_PATH = _ROOT / "data" / "raw" / "daily_weather_competitors.csv"

START_YEAR = 2015
DELAY = 0.25

# 시도 -> ASOS 지점들. 상추 재배가 실제로 이뤄지는 평야·산지 위주로 골랐다.
SIDO_STATIONS: dict[str, list[str]] = {
    "경기도":   ["119", "203", "202", "99", "98"],      # 수원 이천 양평 파주 동두천
    "강원도":   ["100", "216", "212", "114", "101"],    # 대관령 태백 홍천 원주 춘천
    "충청남도": ["129", "232", "236", "235"],           # 서산 천안 부여 보령
    "충청북도": ["131", "221", "127"],                  # 청주 제천 충주
    "경상북도": ["136", "137", "279"],                  # 안동 상주 구미
    "전라남도": ["165", "170", "168"],                  # 목포 완도 여수
    "경상남도": ["155", "192", "162"],                  # 창원 산청 통영
}

# KOSIS DT_1ET0028 (2024) 실측. 노지/시설 ha
AREA_2024 = {
    "전라북도": (95, 1376), "충청남도": (86, 954), "경기도": (253, 498),
    "강원도": (158, 15), "경상북도": (119, 126), "충청북도": (6, 208),
    "전라남도": (60, 127), "경상남도": (38, 91),
}


def _to_num(x) -> float:
    try:
        v = float(x)
        return np.nan if v <= -99 else v
    except (TypeError, ValueError):
        return np.nan


def _chunk(stn: str, s: str, e: str) -> list[dict]:
    for attempt in range(4):
        try:
            r = requests.get(URL, params={
                "serviceKey": KEY, "dataType": "JSON", "dataCd": "ASOS",
                "dateCd": "DAY", "startDt": s, "endDt": e, "stnIds": stn,
                "numOfRows": 999, "pageNo": 1}, timeout=60)
            if "LIMITED_NUMBER" in r.text:
                sys.exit("ASOS 일일 한도 초과 — 자정 이후 재실행")
            r.raise_for_status()
            it = r.json()["response"]["body"]["items"]["item"]
            return [it] if isinstance(it, dict) else it
        except SystemExit:
            raise
        except Exception:
            if attempt == 3:
                return []
            time.sleep(2 * (attempt + 1))
    return []


def fetch() -> pd.DataFrame:
    if not KEY:
        sys.exit("DATA_GO_KR_KEY 없음")
    end_d = dt.date.today() - dt.timedelta(days=1)
    pairs = [(sido, s) for sido, ss in SIDO_STATIONS.items() for s in ss]
    print(f"경쟁 산지 기상 | 지점 {len(pairs)}곳 | {START_YEAR}-01-01 ~ {end_d}")
    rows = []
    for sido, stn in pairs:
        got = 0
        for yr in range(START_YEAR, end_d.year + 1):
            s = dt.date(yr, 1, 1)
            e = min(dt.date(yr, 12, 31), end_d)
            if s > e:
                continue
            for it in _chunk(stn, s.strftime("%Y%m%d"), e.strftime("%Y%m%d")):
                rows.append({
                    "sido": sido, "stn": stn, "stn_nm": it.get("stnNm"),
                    "date": it.get("tm"),
                    "tavg": _to_num(it.get("avgTa")), "tmax": _to_num(it.get("maxTa")),
                    "tmin": _to_num(it.get("minTa")), "rain": _to_num(it.get("sumRn")),
                    "sun_hr": _to_num(it.get("sumSsHr")), "rh": _to_num(it.get("avgRhm")),
                })
                got += 1
            time.sleep(DELAY)
        nm = next((r["stn_nm"] for r in rows[::-1] if r["stn"] == stn), "?")
        print(f"  {sido:<8} {stn} {str(nm):<8} {got:,}일", flush=True)

    d = pd.DataFrame(rows).dropna(subset=["date"]).drop_duplicates(["stn", "date"])
    d["rain"] = d["rain"].fillna(0.0)
    d.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\n저장: {OUT_PATH.name} ({len(d):,}행, 지점 {d['stn'].nunique()}곳)")
    return d


def build_monthly() -> pd.DataFrame:
    """시도별 월 피처 + 노지가중 전국 지표."""
    if not OUT_PATH.exists():
        sys.exit("먼저 fetch 실행")
    d = pd.read_csv(OUT_PATH, dtype={"stn": str})
    d["date"] = pd.to_datetime(d["date"])
    d["ym"] = d["date"].dt.to_period("M")
    d["_hot"] = d["tmax"] >= 30
    d["_vhot"] = d["tmax"] >= 33
    d["_ehot"] = d["tmax"] >= 35        # 노지 상추가 '녹는' 수준
    d["_trop"] = d["tmin"] >= 20
    d["_germ"] = d["tavg"] >= 25

    per = d.groupby(["sido", "stn", "ym"]).agg(
        hot=("_hot", "sum"), vhot=("_vhot", "sum"), ehot=("_ehot", "sum"),
        trop=("_trop", "sum"), germ=("_germ", "sum"),
        tmax=("tmax", "mean"), tavg=("tavg", "mean"),
    ).reset_index()
    sido_m = per.groupby(["sido", "ym"]).mean(numeric_only=True).reset_index()

    # 노지가중 / 시설가중 전국 지표
    nogi = {k: v[0] for k, v in AREA_2024.items()}
    sisl = {k: v[1] for k, v in AREA_2024.items()}
    sido_m["w_nogi"] = sido_m["sido"].map(nogi).fillna(0)
    sido_m["w_sisl"] = sido_m["sido"].map(sisl).fillna(0)

    out = {}
    for c in ("hot", "vhot", "ehot", "trop", "germ", "tmax"):
        for tag, wcol in (("nogi", "w_nogi"), ("sisl", "w_sisl")):
            num = (sido_m[c] * sido_m[wcol]).groupby(sido_m["ym"]).sum()
            den = sido_m.groupby("ym")[wcol].sum()
            out[f"{c}_{tag}"] = num / den.replace(0, np.nan)
    nat = pd.DataFrame(out).reset_index()

    # 시도 개별 (경기·강원은 따로 봐야 한다)
    for sd, tag in [("경기도", "gg"), ("강원도", "gw"), ("경상북도", "gb"),
                    ("충청남도", "cn")]:
        g = sido_m[sido_m["sido"] == sd].set_index("ym")
        for c in ("hot", "vhot", "ehot", "tmax"):
            nat[f"{c}_{tag}"] = nat["ym"].map(g[c])
    return nat, sido_m


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "build"])
    a = ap.parse_args()
    if a.cmd == "fetch":
        fetch()
    else:
        nat, sido_m = build_monthly()
        p = _ROOT / "data" / "processed"
        nat.to_csv(p / "competitor_weather_monthly.csv", index=False,
                   encoding="utf-8-sig")
        sido_m.to_csv(p / "competitor_weather_by_sido.csv", index=False,
                      encoding="utf-8-sig")
        print(f"저장: competitor_weather_monthly.csv ({len(nat)}행 x {len(nat.columns)}열)")
        m = nat.copy()
        m["month"] = m["ym"].dt.month
        print()
        print("  월별 — 노지가중 vs 시설가중 고온 노출")
        print("    " + " ".join(f"{x:>6d}" for x in range(1, 13)))
        for c in ("hot_nogi", "hot_sisl", "ehot_nogi", "hot_gg", "hot_gw"):
            g = m.groupby("month")[c].mean()
            print(f"  {c:<10}" + " ".join(f"{g.get(x, np.nan):6.1f}" for x in range(1, 13)))


if __name__ == "__main__":
    main()
