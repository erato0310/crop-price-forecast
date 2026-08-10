# -*- coding: utf-8 -*-
"""scrape_jeonbuk_market.py — 전북 실제 공판장(전주·익산·정읍) 상추 거래 데이터 수집.

data.go.kr 오픈API "한국농수산식품유통공사_전국 공영도매시장 정산정보"
(katSale/trades, https://apis.data.go.kr/B552845/katSale/trades)를 사용한다.

이 API는 예전 KAMIS/가락시장과 달리 진짜 "전북 지역" 도매시장 데이터다 — KAMIS API는
전국평균만 주고, 가락시장 스크래핑은 서울 단일 시장이었다. 전북에 실제로 있는 공영도매시장은
전주·익산·정읍 3곳뿐이라(2026-08 실측 확인, at.agromarket.kr/whsal/search.do), 이 3곳을
물량가중평균으로 합쳐 "전북 지역 상추 공판장 가격"을 만든다.

시장코드(whsl_mrkt_cd)는 문서화가 안 돼 있어 실측으로 찾았다(katRealTime2/trades2를
날짜만으로 스캔해 whsl_mrkt_nm으로 매칭 후, katSale/trades에 whsl_mrkt_cd 후보를 던져
totalCount>0으로 검증):
    전주=350101, 익산=350301, 정읍=350402
(패턴상 앞 2자리=시도(35=전라북도, KOSIS 코드와 일치), 다음 2자리=시군, 마지막 2자리=시장
순번으로 추정되나 확정은 아님 — 다른 지역 확장 시 재검증 필요.)

날짜 커버리지 실측: 2018-01-15는 데이터 있음(totalCount>0), 2016-01-15는 없음(totalCount=0)
— 최소 2018년부터 현재까지 커버.
"""
from __future__ import annotations

import datetime as dt
import os
import time
import urllib.parse
from pathlib import Path
from typing import Optional

import pandas as pd

try:
    import requests
except ImportError:
    requests = None

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

KEY = urllib.parse.unquote(os.getenv("DATA_GO_KR_KEY", ""))
URL = "https://apis.data.go.kr/B552845/katSale/trades"

MARKETS = {"jeonju": "350101", "iksan": "350301", "jeongeup": "350402"}

OUT_DIR = _PROJECT_ROOT / "data" / "raw"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SAMPLE_DAYS = (5, 15, 25)
REQUEST_DELAY_SEC = 0.25
START = "2018-01-01"


def fetch_day_market(market_cd: str, date: dt.date) -> list[dict]:
    """해당 날짜·시장의 상추(gds_mclsf_nm=='상추') 전 레코드. totalCount>numOfRows면 페이징."""
    if requests is None or not KEY:
        return []
    rows: list[dict] = []
    page = 1
    while True:
        params = {
            "serviceKey": KEY, "returnType": "JSON",
            "cond[whsl_mrkt_cd::EQ]": market_cd,
            "cond[trd_clcln_ymd::EQ]": date.isoformat(),
            "numOfRows": 1000, "pageNo": page,
        }
        try:
            r = requests.get(URL, params=params, timeout=20)
            r.raise_for_status()
            js = r.json()
        except Exception:
            break
        body = js.get("response", {}).get("body", {})
        items = body.get("items", {}).get("item", [])
        if isinstance(items, dict):
            items = [items]
        for it in items:
            if (it.get("gds_mclsf_nm") or "") != "상추":
                continue
            try:
                price = float(it.get("avgprc") or 0)
                qty = float(it.get("unit_tot_qty") or 0)
            except (TypeError, ValueError):
                continue
            if price <= 0 or qty <= 0:
                continue
            rows.append({
                "date": date, "market_cd": market_cd,
                "variety": it.get("gds_sclsf_nm"), "grade": it.get("grd_nm"),
                "price": price, "qty": qty,
            })
        total = body.get("totalCount", 0)
        if page * 1000 >= total or not items:
            break
        page += 1
    return rows


_CD_TO_REGION = {v: k for k, v in MARKETS.items()}


def _wavg(d: pd.DataFrame) -> float:
    total_qty = d["qty"].sum()
    return (d["price"] * d["qty"]).sum() / total_qty if total_qty else float("nan")


def scrape_monthly(start: str = START, end: Optional[str] = None, verbose: bool = True):
    """반환: (combined_df, by_region_df, raw_df).
    combined = 3개 시장 합친 물량가중평균(price_avg_jeonbuk, 기존과 동일 스키마).
    by_region = 시장별로 따로 낸 월별 물량가중평균(long format: region_id 컬럼).
    raw = 표본일마다 받은 개별 레코드 전부(재분석용, 재수집 없이 다른 방식으로 다시 집계 가능)."""
    end_date = dt.date.fromisoformat(end) if end else dt.date.today()
    months = pd.period_range(start=start, end=end_date.isoformat(), freq="M")
    today = dt.date.today()
    combined_rows, region_rows, raw_all = [], [], []
    for i, ym in enumerate(months):
        month_records: list[dict] = []
        for day in SAMPLE_DAYS:
            try:
                target = dt.date(ym.year, ym.month, day)
            except ValueError:
                continue
            if target > today:
                continue
            for mkt_cd in MARKETS.values():
                recs = fetch_day_market(mkt_cd, target)
                month_records.extend(recs)
                time.sleep(REQUEST_DELAY_SEC)
        if month_records:
            df_m = pd.DataFrame(month_records)
            raw_all.extend(month_records)
            combined_rows.append({
                "ym": ym,
                "price_avg_jeonbuk": _wavg(df_m),
                "qty_total_jeonbuk": df_m["qty"].sum(),
                "n_obs_jeonbuk": len(df_m),
                "n_markets_jeonbuk": df_m["market_cd"].nunique(),
            })
            for mkt_cd, grp in df_m.groupby("market_cd"):
                region_rows.append({
                    "ym": ym, "region_id": _CD_TO_REGION.get(mkt_cd, mkt_cd),
                    "price_avg": _wavg(grp), "qty_total": grp["qty"].sum(), "n_obs": len(grp),
                })
        if verbose:
            got = f"OK({len(month_records)}건)" if month_records else "없음"
            print(f"[{i+1}/{len(months)}] {ym} -> {got}", flush=True)
    return pd.DataFrame(combined_rows), pd.DataFrame(region_rows), pd.DataFrame(raw_all)


def main():
    combined, by_region, raw = scrape_monthly()

    out_combined = OUT_DIR / "jeonbuk_market_lettuce_history.csv"
    combined.to_csv(out_combined, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료(합산): {out_combined} ({len(combined)}행)")

    out_region = OUT_DIR / "jeonbuk_market_lettuce_by_region.csv"
    by_region.to_csv(out_region, index=False, encoding="utf-8-sig")
    print(f"저장 완료(시장별): {out_region} ({len(by_region)}행)")
    print(by_region.to_string(index=False))

    out_raw = OUT_DIR / "jeonbuk_market_lettuce_raw.csv"
    raw.to_csv(out_raw, index=False, encoding="utf-8-sig")
    print(f"저장 완료(원시 레코드, 재분석용): {out_raw} ({len(raw)}행)")


if __name__ == "__main__":
    main()
