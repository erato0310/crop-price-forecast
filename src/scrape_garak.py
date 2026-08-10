# -*- coding: utf-8 -*-
"""scrape_garak.py — 가락시장 경락가격(공판장 낙찰가) 웹페이지 스크래퍼.

KAMIS periodProductList API와 odcloud 15134477은 각각 최근 1년/2024년 일부만 준다
(docs/RESOLVE_GUIDE.md 참고). 반면 KAMIS 홈페이지의 "가락시장 경락가격 > 기간별" 페이지
(/customer/price/market/period.do)는 로그인·키 없이 약 5년 전(2021-09 무렵)부터 오늘까지
실데이터를 서버 렌더링으로 내려준다 — 실측으로 이분탐색해 확인함(2021-08-04는 없고
2021-09-15는 있음).

이 페이지는 특정 하루(`regday`)씩만 조회 가능해 대량 스크래핑이 필요하다. 월별로 며칠만
표본 추출해 평균가를 근사한다(원 KAMIS periodProductList가 주는 "전국평균"과 달리
가락시장=서울 단일 시장 값이라 레벨이 다를 수 있음 — README/RESOLVE_GUIDE에 명시).
"""
from __future__ import annotations

import datetime as dt
import io
import time
from pathlib import Path
from typing import Optional

import pandas as pd

try:
    import requests
except ImportError:
    requests = None

URL = "https://www.kamis.or.kr/customer/price/market/period.do"
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SAMPLE_DAYS = (5, 15, 25)          # 월별 표본일
FALLBACK_OFFSETS = (1, -1, 2, -2)  # 표본일에 데이터 없을 때(장 휴무 등) 시도할 보정
REQUEST_DELAY_SEC = 0.4


def fetch_day(item_code: str, date: dt.date) -> Optional[pd.DataFrame]:
    """해당 날짜의 [등급, 평균가] 실데이터. 없으면 None."""
    if requests is None:
        return None
    params = {
        "regday": date.strftime("%Y.%m.%d"),
        "marketcode": "1",
        "itemcode": item_code,
        "productrankcode": "",
    }
    try:
        r = requests.get(URL, params=params, timeout=20)
        r.raise_for_status()
    except Exception:
        return None

    if "검색조건에 해당하는 데이터가 없습니다" in r.text:
        return None

    try:
        tables = pd.read_html(io.StringIO(r.text))
    except ValueError:
        return None

    for t in tables:
        cols = [str(c) for c in t.columns]
        if "일자" in cols and "평균가" in cols and "등급" in cols:
            t = t.copy()
            t["평균가"] = (
                t["평균가"].astype(str).str.replace(",", "", regex=False).str.strip()
            )
            t = t[t["평균가"].str.match(r"^\d+$", na=False)]
            if t.empty:
                return None
            t["평균가"] = t["평균가"].astype(float)
            t["date"] = date
            return t[["date", "등급", "평균가"]].rename(
                columns={"등급": "grade", "평균가": "price"}
            )
    return None


def fetch_day_with_fallback(item_code: str, date: dt.date) -> Optional[pd.DataFrame]:
    d = fetch_day(item_code, date)
    if d is not None:
        return d
    for off in FALLBACK_OFFSETS:
        time.sleep(REQUEST_DELAY_SEC)
        alt = date + dt.timedelta(days=off)
        if alt > dt.date.today():
            continue
        d = fetch_day(item_code, alt)
        if d is not None:
            return d
    return None


def scrape_monthly(item_code: str, start: str, end: str, verbose: bool = True) -> pd.DataFrame:
    """월별로 SAMPLE_DAYS를 표본조회해 [ym, price_avg_garak, n_obs_garak] 근사."""
    months = pd.period_range(start=start, end=end, freq="M")
    today = dt.date.today()
    rows = []
    for i, ym in enumerate(months):
        month_frames = []
        for day in SAMPLE_DAYS:
            target = dt.date(ym.year, ym.month, day)
            if target > today:
                continue
            d = fetch_day_with_fallback(item_code, target)
            time.sleep(REQUEST_DELAY_SEC)
            if d is not None:
                month_frames.append(d)
        if month_frames:
            allm = pd.concat(month_frames, ignore_index=True)
            rows.append({
                "ym": ym,
                "price_avg_garak": allm["price"].mean(),
                "n_obs_garak": len(allm),
            })
        if verbose:
            got = "OK" if month_frames else "없음"
            print(f"[{i+1}/{len(months)}] {ym} -> {got}", flush=True)
    return pd.DataFrame(rows)


def main():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import sources as S

    cx = S.crop_xwalk()
    item_code = str(cx.loc["lettuce", "garak_item"])
    start = "2021-09-01"
    end = dt.date.today().isoformat()

    df = scrape_monthly(item_code, start, end)
    out_path = OUT_DIR / "garak_lettuce_history.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료: {out_path} ({len(df)}행)")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
