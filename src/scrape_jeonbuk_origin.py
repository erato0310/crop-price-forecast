# -*- coding: utf-8 -*-
"""scrape_jeonbuk_origin.py — 전북 각 시군에서 "생산돼 어느 공판장으로든 팔린" 상추 가격을
산지(시군) 기준으로 재구축한다.

기존 scrape_jeonbuk_market.py는 "전북에 있는 시장"(전주·익산·정읍) 3곳만 봤는데, 실측해보니
전북산 상추의 **94%는 그 3개 시장이 아니라 전국 다른 시장**(광주·서울가락·부산·대구·대전·
순천·창원 등)으로 팔린다(2026-08 5일 표본 확인). 그래서 "시장 위치" 기준이 아니라
`plor_nm`(산지) 필드 기준으로 다시 잡아야 진짜 "그 지역 상추가 얼마에 팔렸는가"가 나온다.

katRealTime2/trades2(시장코드 없이 날짜 하나로 전국 조회 가능)는 최근 데이터만 지원해서
(2025년 이전 날짜는 totalCount=0 확인됨) 과거 이력 수집엔 못 쓴다. 그래서 katSale/trades로
시장별 조회를 하되, "전북산이 실제로 팔리는 시장 상위 17곳"(katRealTime2로 5일 표본 조사해
누적거래량 97.9% 커버 확인)만 골라서 돈다 — 전국 수십 개 시장을 다 도는 것보다 훨씬
현실적인 시간 안에 끝난다.

MARKETS_TOP17: 시장명 -> 시장코드. 2026-08 katRealTime2/trades2 5일(07-16,07-23,07-30,
08-01,08-04) 표본으로 확정. 계절에 따라 주력 시장이 바뀔 가능성은 있으나(예: 수박은
여름 산지가 다르듯) 상추는 연중 출하라 큰 변화 없을 것으로 가정 — 결과 보고 이상하면
재검증할 것.
"""
from __future__ import annotations

import datetime as dt
import os
import re
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

MARKETS_TOP17 = {
    "광주서부": "240004", "서울가락": "110001", "광주각화": "240001",
    "부산반여": "210009", "부산엄궁": "210001", "대구북부": "220001",
    "대전오정": "250001", "창원내서": "380303", "전주": "350101",
    "익산": "350301", "대전노은": "250003", "순천": "360301",
    "인천남촌": "230001", "서울강서": "110008", "인천삼산": "230003",
    "창원팔용": "380101", "진주": "380401",
}

OUT_DIR = _PROJECT_ROOT / "data" / "raw"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SAMPLE_DAYS = (5, 15, 25)
REQUEST_DELAY_SEC = 0.2
START = "2018-01-01"

_COUNTY_RE = re.compile(r"전(?:북특별자치도|라북도|북)\s*([가-힣]+(?:시|군))")


def parse_county(plor_nm: Optional[str]) -> Optional[str]:
    """'전북특별자치도 남원시 운봉읍' -> '남원시'. 매칭 안 되면 None."""
    if not plor_nm:
        return None
    m = _COUNTY_RE.match(plor_nm.strip())
    return m.group(1) if m else None


def fetch_day_market_lettuce(market_cd: str, date: dt.date) -> list[dict]:
    """해당 날짜·시장의 상추 레코드 전부(산지 필드 포함). totalCount>numOfRows면 페이징."""
    if requests is None or not KEY:
        return []
    rows: list[dict] = []
    page = 1
    while True:
        params = {
            "serviceKey": KEY, "returnType": "JSON",
            "cond[whsl_mrkt_cd::EQ]": market_cd,
            "cond[trd_clcln_ymd::EQ]": date.isoformat(),
            "cond[gds_mclsf_nm::EQ]": "상추",
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
            try:
                price = float(it.get("avgprc") or 0)
                qty = float(it.get("unit_tot_qty") or 0)
            except (TypeError, ValueError):
                continue
            if price <= 0 or qty <= 0:
                continue
            county = parse_county(it.get("plor_nm"))
            if county is None:
                continue
            rows.append({
                "date": date, "market_cd": market_cd, "county": county,
                "plor_nm": it.get("plor_nm"), "price": price, "qty": qty,
            })
        total = body.get("totalCount", 0)
        if page * 1000 >= total or not items:
            break
        page += 1
    return rows


def _wavg(d: pd.DataFrame) -> float:
    total_qty = d["qty"].sum()
    return (d["price"] * d["qty"]).sum() / total_qty if total_qty else float("nan")


def scrape_monthly(start: str = START, end: Optional[str] = None, verbose: bool = True):
    end_date = dt.date.fromisoformat(end) if end else dt.date.today()
    months = pd.period_range(start=start, end=end_date.isoformat(), freq="M")
    today = dt.date.today()
    by_county_rows, raw_all = [], []
    for i, ym in enumerate(months):
        month_records: list[dict] = []
        for day in SAMPLE_DAYS:
            try:
                target = dt.date(ym.year, ym.month, day)
            except ValueError:
                continue
            if target > today:
                continue
            for mkt_cd in MARKETS_TOP17.values():
                recs = fetch_day_market_lettuce(mkt_cd, target)
                month_records.extend(recs)
                time.sleep(REQUEST_DELAY_SEC)
        if month_records:
            raw_all.extend(month_records)
            df_m = pd.DataFrame(month_records)
            for county, grp in df_m.groupby("county"):
                by_county_rows.append({
                    "ym": ym, "county": county,
                    "price_avg": _wavg(grp), "qty_total": grp["qty"].sum(), "n_obs": len(grp),
                    "n_markets": grp["market_cd"].nunique(),
                })
        if verbose:
            n_county = len(set(r["county"] for r in month_records))
            got = f"OK({len(month_records)}건, {n_county}개 시군)" if month_records else "없음"
            print(f"[{i+1}/{len(months)}] {ym} -> {got}", flush=True)
    return pd.DataFrame(by_county_rows), pd.DataFrame(raw_all)


def main():
    by_county, raw = scrape_monthly()

    out_county = OUT_DIR / "jeonbuk_origin_lettuce_by_county.csv"
    by_county.to_csv(out_county, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료(시군별 산지가격): {out_county} ({len(by_county)}행)")

    out_raw = OUT_DIR / "jeonbuk_origin_lettuce_raw.csv"
    raw.to_csv(out_raw, index=False, encoding="utf-8-sig")
    print(f"저장 완료(원시 레코드): {out_raw} ({len(raw)}행)")

    if not by_county.empty:
        summary = by_county.groupby("county").agg(
            n_months=("ym", "nunique"), avg_price=("price_avg", "mean"), total_qty=("qty_total", "sum")
        ).sort_values("n_months", ascending=False)
        print("\n시군별 요약:")
        print(summary.to_string())


if __name__ == "__main__":
    main()
