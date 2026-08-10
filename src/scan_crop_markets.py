# -*- coding: utf-8 -*-
"""scan_crop_markets.py — 작물별 "전북산이 실제로 팔리는 시장" 분포 재조사.

배경: MARKETS_TOP17은 2026-08 상추 기준 표본으로 확정한 목록인데, 이걸 10개 작물
전체에 재사용 중이다(scrape_jeonbuk_all_crops.py). 수박·포도처럼 유통망이 다른
작물은 이 17개가 커버를 못 할 수 있어, katRealTime2/trades2(시장코드 없이 날짜
전국 조회, 최근 데이터만 지원)로 여러 날짜 표본을 떠서 작물×시장 분포를 다시 잰다.

한계: katRealTime2는 최근 날짜만 되므로 표본이 "지금 계절"(8월)에 치우친다.
겨울 유통망이 다른 작물(대파 등)은 완전히 못 잡을 수 있음 — 결과 해석 시 유의.
"""
from __future__ import annotations

import datetime as dt
import time

import pandas as pd

from scrape_jeonbuk_origin import KEY, MARKETS_TOP17, parse_county, requests
from scrape_jeonbuk_all_crops import TOP10_CROPS

URL2 = "https://apis.data.go.kr/B552845/katRealTime2/trades2"


def fetch_day_all(date: dt.date, max_pages: int = 200) -> list[dict]:
    """해당 날짜 전국 거래 전체를 페이징으로 수집, 산지=전북만 남김."""
    rows: list[dict] = []
    page = 1
    while page <= max_pages:
        params = {
            "serviceKey": KEY, "returnType": "JSON",
            "cond[trd_clcln_ymd::EQ]": date.isoformat(),
            "numOfRows": 1000, "pageNo": page,
        }
        for attempt in range(3):  # 이전 환경 네트워크 문제 재발 방지: 재시도
            try:
                r = requests.get(URL2, params=params, timeout=30)
                r.raise_for_status()
                js = r.json()
                break
            except Exception as e:
                if attempt == 2:
                    print(f"    ! {date} page={page} 3회 실패: {type(e).__name__}", flush=True)
                    return rows
                time.sleep(1.5 * (attempt + 1))
        body = js.get("response", {}).get("body", {})
        items = body.get("items", {}).get("item", [])
        if isinstance(items, dict):
            items = [items]
        if not items:
            break
        for it in items:
            county = parse_county(it.get("plor_nm"))
            if county is None:
                continue
            try:
                qty = float(it.get("unit_tot_qty") or 0)
            except (TypeError, ValueError):
                qty = 0.0
            rows.append({
                "date": date, "market_nm": it.get("whsl_mrkt_nm"),
                "market_cd": it.get("whsl_mrkt_cd"), "crop": it.get("gds_mclsf_nm"),
                "county": county, "qty": qty,
            })
        total = int(body.get("totalCount", 0) or 0)
        if page * 1000 >= total:
            break
        page += 1
        time.sleep(0.2)
    return rows


def main():
    # 최근 3주 평일 표본(일요일 휴장 회피)
    today = dt.date.today()
    dates = []
    d = today - dt.timedelta(days=1)
    while len(dates) < 8 and d > today - dt.timedelta(days=25):
        if d.weekday() < 6 and d.weekday() != 6:  # 일요일 제외
            if d.weekday() != 5 or len([x for x in dates if x.weekday() == 5]) < 2:
                dates.append(d)
        d -= dt.timedelta(days=2)

    all_rows: list[dict] = []
    for i, date in enumerate(dates):
        rows = fetch_day_all(date)
        all_rows.extend(rows)
        print(f"[{i+1}/{len(dates)}] {date} ({date.strftime('%a')}) 전북산 {len(rows)}건", flush=True)

    df = pd.DataFrame(all_rows)
    if df.empty:
        print("데이터 없음 — API 응답 확인 필요")
        return

    df.to_csv("../outputs/crop_market_scan_raw.csv", index=False, encoding="utf-8-sig")
    known_cds = set(MARKETS_TOP17.values())

    print("\n" + "=" * 80)
    print("작물별 시장 커버리지 (거래량 기준, TOP17 시장이 커버하는 비율)")
    print("=" * 80)
    report_rows = []
    for crop in TOP10_CROPS:
        sub = df[df["crop"] == crop]
        if sub.empty:
            print(f"\n### {crop}: 표본 없음(계절 이슈일 수 있음)")
            report_rows.append({"crop": crop, "n_rec": 0, "coverage_pct": None})
            continue
        total_qty = sub["qty"].sum()
        in17 = sub[sub["market_cd"].isin(known_cds)]["qty"].sum()
        cov = in17 / total_qty * 100 if total_qty else float("nan")
        mkts = (sub.groupby(["market_nm", "market_cd"])["qty"].sum()
                .sort_values(ascending=False))
        missing = mkts[~mkts.index.get_level_values("market_cd").isin(known_cds)]
        print(f"\n### {crop}: {len(sub)}건, TOP17 커버 {cov:.1f}%")
        print("  상위 시장:", ", ".join(
            f"{n}({q/total_qty*100:.0f}%)" for (n, c), q in mkts.head(6).items()))
        if not missing.empty:
            print("  ** TOP17에 없는 시장:", ", ".join(
                f"{n}[{c}]({q/total_qty*100:.1f}%)" for (n, c), q in missing.head(5).items()))
        report_rows.append({"crop": crop, "n_rec": len(sub), "coverage_pct": round(cov, 1)})

    # 전체 작물(top10 외 포함) 기준 놓친 시장 집계
    print("\n" + "=" * 80)
    print("전북산 전체 거래에서 TOP17 밖 시장 (추가 후보)")
    print("=" * 80)
    out = df[~df["market_cd"].isin(known_cds)]
    if out.empty:
        print("없음 — TOP17로 충분")
    else:
        cand = (out.groupby(["market_nm", "market_cd"])["qty"].sum()
                .sort_values(ascending=False))
        tot = df["qty"].sum()
        for (n, c), q in cand.head(15).items():
            crops_here = out[out["market_cd"] == c].groupby("crop")["qty"].sum().nlargest(3)
            print(f"  {n}[{c}]: 전체의 {q/tot*100:.2f}%  주요작물: "
                  + ", ".join(f"{k}" for k in crops_here.index))

    pd.DataFrame(report_rows).to_csv("../outputs/crop_market_coverage.csv",
                                     index=False, encoding="utf-8-sig")
    print("\n저장: ../outputs/crop_market_scan_raw.csv, ../outputs/crop_market_coverage.csv")


if __name__ == "__main__":
    main()
