# -*- coding: utf-8 -*-
"""scrape_jeonbuk_all_crops.py — scrape_jeonbuk_origin.py를 상추 하나에서 "전북산 거래량
상위 10개 작물"로 일반화. 시장×날짜 조합은 완전히 동일하게 도니(호출 횟수 그대로) 품목
필터만 빼서 한 번에 여러 작물을 같이 받는다 — 작물마다 따로 몇 시간씩 다시 긁을 필요가 없다.

TOP10_CROPS: 2026-08-06 katRealTime2/trades2 3일 표본(전북산 전체 8,937건)에서 거래량
상위 10개로 확정 — 상추·수박·포도·오이·토마토·복숭아·고구마·방울토마토·멜론·대파.
전체 79개 작물 중 이 10개가 79.1%를 차지한다. 나머지 69개는 표본이 너무 적어(대부분
100건 미만) 통계적으로 의미 있는 월별 모델을 만들기 어렵다고 판단해 제외했다.

MARKETS_TOP17은 scrape_jeonbuk_origin.py와 동일 — **상추 기준으로 뽑은 목록을 그대로
재사용**한다. 다른 작물(특히 수박·포도처럼 산지·유통망이 상추와 다를 수 있는 작물)은
이 17개 시장이 상추만큼 정확히(97.9%) 커버 안 할 수 있다는 한계가 있음 — 결과 보고
이상하면 작물별로 재조사할 것.
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Optional

import pandas as pd

from scrape_jeonbuk_origin import (
    KEY, URL, MARKETS_TOP17, OUT_DIR, SAMPLE_DAYS, REQUEST_DELAY_SEC, START,
    parse_county, requests,
)

TOP10_CROPS = ["상추", "수박", "포도", "오이", "토마토", "복숭아", "고구마",
               "방울토마토", "멜론", "대파"]

CROP_NAME_TO_ID = {
    "상추": "lettuce", "수박": "watermelon", "포도": "grape", "오이": "cucumber",
    "토마토": "tomato", "복숭아": "peach", "고구마": "sweetpotato",
    "방울토마토": "cherrytomato", "멜론": "melon", "대파": "greenonion",
}

# 실제 순회할 시장 목록. 기본은 상추 기준 TOP17 + scan_crop_markets.py 재조사(2026-08-07,
# 최근 8일 표본 66,304건)에서 확인된 부족분 6개 시장. TOP17만으로는 수박 77%·고구마 90%·
# 멜론 90%·복숭아 93%밖에 못 잡았는데, 6개를 더하면 수박 96.8%·나머지 전부 96%+ 커버.
# (상추·토마토·포도·오이는 TOP17로 이미 99~100%였음 — outputs/crop_market_coverage.csv)
MARKETS: dict[str, str] = dict(MARKETS_TOP17) | {
    "구리": "311201",   # 고구마 6%·멜론 5%·복숭아 4%·수박 4.3%
    "청주": "330101",   # 수박 6.9%
    "천안": "340101",   # 수박 2.9%·대파
    "정읍": "350402",   # 전북 소재 시장인데 TOP17에서 빠져 있었음 — 오이·대파·복숭아
    "안양": "310401",   # 수박 2.6%·멜론
    "수원": "310101",   # 수박 2.2%·고구마·상추
}


FETCH_FAILURES: list[dict] = []  # 재시도 후에도 실패한 (시장, 날짜) — 조용한 데이터 구멍 방지


def fetch_day_market_all(market_cd: str, date: dt.date) -> list[dict]:
    """해당 날짜·시장의 모든 품목 레코드(품목 필터 없음). totalCount>numOfRows면 페이징.

    이전 환경(느린 네트워크)에서 `except: break`가 타임아웃을 조용히 삼켜 2026-05 등
    월 단위 데이터 구멍을 냈던 이력이 있어, 3회 재시도 + 실패 기록으로 바꿨다.
    """
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
        js = None
        for attempt in range(5):
            try:
                r = requests.get(URL, params=params, timeout=30)
                r.raise_for_status()
                js = r.json()
                break
            except Exception as e:
                if attempt == 4:
                    detail = getattr(getattr(e, "response", None), "status_code", "") \
                        or type(e).__name__
                    FETCH_FAILURES.append({"market_cd": market_cd, "date": date,
                                           "page": page, "err": str(detail)})
                    print(f"    ! 실패(5회): {market_cd} {date} p{page} {detail}",
                          flush=True)
                else:
                    # 빠른 네트워크에선 서버측 순간 제한(HTTP 429 실측)이 걸림 —
                    # 429는 특히 길게 물러났다 재시도
                    status = getattr(getattr(e, "response", None), "status_code", None)
                    time.sleep((10.0 if status == 429 else 2.0) * (attempt + 1))
        if js is None:
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
                "crop": it.get("gds_mclsf_nm"), "plor_nm": it.get("plor_nm"),
                "price": price, "qty": qty,
            })
        total = body.get("totalCount", 0)
        if page * 1000 >= total or not items:
            break
        page += 1
    return rows


def _wavg(d: pd.DataFrame) -> float:
    total_qty = d["qty"].sum()
    return (d["price"] * d["qty"]).sum() / total_qty if total_qty else float("nan")


PARTIAL_PATH = OUT_DIR / "allcrops_rescrape_partial.csv"


def scrape_monthly(start: str = START, end: Optional[str] = None, verbose: bool = True):
    """월 단위 순회 수집. 중간에 죽어도 PARTIAL_PATH에서 이어받는다(완료 월 스킵).
    기존 출력 파일들은 전체 완주 후 main()에서만 덮어쓴다."""
    end_date = dt.date.fromisoformat(end) if end else dt.date.today()
    months = pd.period_range(start=start, end=end_date.isoformat(), freq="M")
    today = dt.date.today()
    by_crop_county_rows, raw_all = [], []
    done_months: set = set()
    if PARTIAL_PATH.exists():
        prev = pd.read_csv(PARTIAL_PATH, parse_dates=["date"])
        # 마지막 월은 도중에 끊겼을 수 있으니 버리고 다시 받는다
        prev_ym = prev["date"].dt.to_period("M")
        last = prev_ym.max()
        prev = prev[prev_ym < last]
        raw_all = prev.to_dict("records")
        done_months = set(prev["date"].dt.to_period("M").astype(str))
        print(f"[재개] 체크포인트 {len(raw_all)}건, 완료월 {len(done_months)}개 스킵", flush=True)
    for i, ym in enumerate(months):
        if str(ym) in done_months:
            continue
        month_records: list[dict] = []
        for day in SAMPLE_DAYS:
            try:
                target = dt.date(ym.year, ym.month, day)
            except ValueError:
                continue
            # 도매시장 대부분 일요일 휴장 → 표본일이 일요일이면 다음날(월)로 이동.
            # (기존엔 그냥 빈 날로 날려서 해당 월 표본이 2일로 줄었음)
            if target.weekday() == 6:
                target += dt.timedelta(days=1)
            if target > today:
                continue
            for mkt_cd in MARKETS.values():
                recs = fetch_day_market_all(mkt_cd, target)
                month_records.extend(recs)
                time.sleep(0.35)  # 빠른 네트워크에서 0.2s는 서버 제한에 걸림(2018-01 실측)
        if month_records:
            raw_all.extend(month_records)  # 79개 작물 전부 원시로 남겨둠(나중에 확장 대비)
            # 체크포인트: 월마다 저장 — 프로세스가 죽어도 여기서 이어받음
            pd.DataFrame(raw_all).to_csv(PARTIAL_PATH, index=False, encoding="utf-8-sig")
        if verbose:
            n_crop = len(set(r["crop"] for r in month_records))
            got = f"OK({len(month_records)}건, {n_crop}개 작물)" if month_records else "없음"
            print(f"[{i+1}/{len(months)}] {ym} -> {got}", flush=True)

    # 집계는 재개 로직과 어긋나지 않게 마지막에 원시 전체에서 일괄 계산
    raw_df = pd.DataFrame(raw_all)
    if not raw_df.empty:
        raw_df["date"] = pd.to_datetime(raw_df["date"])
        raw_df["_ym"] = raw_df["date"].dt.to_period("M")
        top10 = raw_df[raw_df["crop"].isin(TOP10_CROPS)]
        for (ym2, crop, county), grp in top10.groupby(["_ym", "crop", "county"]):
            by_crop_county_rows.append({
                "ym": ym2, "crop": crop, "crop_id": CROP_NAME_TO_ID.get(crop, crop),
                "county": county,
                "price_avg": _wavg(grp), "qty_total": grp["qty"].sum(), "n_obs": len(grp),
                "n_markets": grp["market_cd"].nunique(),
            })
        raw_df = raw_df.drop(columns=["_ym"])
    return pd.DataFrame(by_crop_county_rows), raw_df


def main():
    by_crop_county, raw = scrape_monthly()

    out_agg = OUT_DIR / "jeonbuk_origin_top10crops_by_county.csv"
    by_crop_county.to_csv(out_agg, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료(작물x시군별 산지가격): {out_agg} ({len(by_crop_county)}행)")

    out_raw = OUT_DIR / "jeonbuk_origin_allcrops_raw.csv"
    raw.to_csv(out_raw, index=False, encoding="utf-8-sig")
    print(f"저장 완료(전체 79개 작물 원시 레코드, 확장용): {out_raw} ({len(raw)}행)")

    # 상추 전용 파일(build_dataset.build_jeonbuk_origin_history가 읽음)도 같은 원시
    # 데이터에서 재생성 — scrape_jeonbuk_origin.py를 따로 다시 돌릴 필요 없음.
    lettuce = by_crop_county[by_crop_county["crop"] == "상추"]
    if not lettuce.empty:
        out_lettuce = OUT_DIR / "jeonbuk_origin_lettuce_by_county.csv"
        lettuce.drop(columns=["crop", "crop_id"]).to_csv(
            out_lettuce, index=False, encoding="utf-8-sig")
        print(f"저장 완료(상추 시군별, build_dataset용): {out_lettuce} ({len(lettuce)}행)")

    if PARTIAL_PATH.exists():
        PARTIAL_PATH.unlink()  # 완주했으니 체크포인트 제거

    if FETCH_FAILURES:
        fail_df = pd.DataFrame(FETCH_FAILURES)
        fail_path = OUT_DIR / "scrape_failures.csv"
        fail_df.to_csv(fail_path, index=False, encoding="utf-8-sig")
        # cp949 콘솔에서 못 찍는 문자(em-dash 등)를 쓰면 저장 다 끝난 뒤에도
        # UnicodeEncodeError로 죽으니 최종 안내 print는 ASCII 구두점만 사용
        print(f"\n[경고] 재시도 후에도 실패한 요청 {len(fail_df)}건 - {fail_path} 확인, "
              f"해당 (시장,날짜)는 데이터에 구멍이 있을 수 있음")
    else:
        print("\n네트워크 실패 0건 - 전 요청 정상 수신")

    if not by_crop_county.empty:
        summary = by_crop_county.groupby("crop").agg(
            n_rows=("ym", "size"), n_counties=("county", "nunique"),
            avg_price=("price_avg", "mean"), total_qty=("qty_total", "sum"),
        ).sort_values("n_rows", ascending=False)
        print("\n작물별 요약:")
        print(summary.to_string())


if __name__ == "__main__":
    main()
