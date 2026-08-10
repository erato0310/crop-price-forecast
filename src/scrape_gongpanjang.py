# -*- coding: utf-8 -*-
"""scrape_gongpanjang.py — 산지공판장 정산가격(농식품부 포털 TI_MD_JIMKT_CLCLN_PRC)에서
전북산 거래를 수집. 도매시장(katSale) 데이터의 보완 소스.

왜: katSale 기반 산지가격은 공영도매시장 경유 물량만 잡는데, 전북엔 공판장 4곳
(군산원예농협·전주농협·김제원예농협·남원원협)이 이 API에 참여 중이고, 특히
**군산·임실·정읍·부안**처럼 도매시장 표본이 얇아 모델링을 제외했던 시군의 물량이
공판장으로 흐른다(2026-08-07 3일 표본: 군산 690건, 임실 90건 등). 데이터는
2020-01-02부터.

API 특성 (2026-08-07 실측):
- 요청: http://211.237.50.150:7080/openapi/{KEY}/json/{GRID}/{start}/{end}?SALEDATE=YYYYMMDD
- 필터는 SALEDATE만 지원(다른 컬럼 파라미터는 무시됨) → 하루 전체(1~2만행)를
  페이징으로 받아 클라이언트에서 전북산만 남긴다. 전북만 따로 등록돼 있지 않음.
- 페이지당 최대 1000행. 일일 트래픽 1000건 → 하루에 약 50개 날짜(날짜당 ~10-20회
  호출)까지. 중간에 트래픽 초과로 끊기면 저장된 진행분에서 이어서 재실행하면 됨
  (이미 받은 날짜는 건너뜀).
- 가격: COST(단가)는 DANQ(단위중량)당 가격 → price_per_kg = COST/DANQ 로 정규화.
  물량은 kg 환산 = QTY*DANQ. (katSale의 avgprc/unit_tot_qty와 단위 체계가 달라
  그대로 합치면 안 되고, 별도 컬럼(price_avg_gpj_*)으로 패널에 들어간다.)
"""
from __future__ import annotations

import datetime as dt
import os
import re
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

KEY = os.getenv("MAFRA_KEY", "")
GRID = "Grid_20240625000000000660_1"
BASE = "http://211.237.50.150:7080/openapi"

OUT_DIR = _PROJECT_ROOT / "data" / "raw"
RAW_PATH = OUT_DIR / "gongpanjang_jeonbuk_raw.csv"
AGG_PATH = OUT_DIR / "gongpanjang_top10crops_by_county.csv"

START = "2020-01"  # 데이터 최초 등록일 2020-01-02
SAMPLE_DAYS = (5, 15, 25)

_COUNTY_RE = re.compile(r"^(?:전북특별자치도|전라북도|전북)\s*([가-힣]+(?:시|군))")

# scrape_jeonbuk_all_crops.TOP10_CROPS와 동일 (import하면 무거운 의존 없음, 복붙 아님)
from scrape_jeonbuk_all_crops import TOP10_CROPS, CROP_NAME_TO_ID


def parse_county(sanname: str | None) -> str | None:
    if not sanname:
        return None
    m = _COUNTY_RE.match(sanname.strip())
    return m.group(1) if m else None


def fetch_day(date: dt.date) -> tuple[list[dict], bool]:
    """하루치 전체를 페이징 수집 → 전북산만 반환. (rows, ok) — ok=False면 트래픽/네트워크 실패."""
    day = date.strftime("%Y%m%d")
    rows: list[dict] = []
    start = 1
    while True:
        url = f"{BASE}/{KEY}/json/{GRID}/{start}/{start + 999}?SALEDATE={day}"
        js = None
        for attempt in range(3):
            try:
                r = requests.get(url, timeout=30)
                r.raise_for_status()
                js = r.json()
                break
            except Exception:
                time.sleep(1.5 * (attempt + 1))
        if js is None:
            return rows, False
        g = js.get(GRID)
        if g is None:  # 트래픽 초과 등 — {'result': {'code': 'ERROR-...'}}
            code = js.get("result", {}).get("code", "?")
            print(f"    ! {day} start={start}: {code}", flush=True)
            return rows, False
        for x in g.get("row", []):
            county = parse_county(x.get("SANNAME"))
            if county is None:
                continue
            try:
                cost = float(x.get("COST") or 0)
                danq = float(x.get("DANQ") or 0)
                qty = float(x.get("QTY") or 0)
            except (TypeError, ValueError):
                continue
            if cost <= 0 or danq <= 0 or qty <= 0:
                continue
            rows.append({
                "date": date, "cmp_cd": x.get("CMPCD"), "cmp_nm": x.get("CMPNAME"),
                "county": county, "crop": x.get("PUMNAME"), "good": x.get("GOODNAME"),
                "san_nm": x.get("SANNAME"), "cost": cost, "danq": danq, "qty": qty,
                "price_per_kg": cost / danq, "qty_kg": qty * danq,
            })
        total = int(g.get("totalCnt", 0) or 0)
        if start + 999 >= total or not g.get("row"):
            break
        start += 1000
        time.sleep(0.15)
    return rows, True


def _wavg(d: pd.DataFrame) -> float:
    tq = d["qty_kg"].sum()
    return (d["price_per_kg"] * d["qty_kg"]).sum() / tq if tq else float("nan")


def main():
    if not KEY:
        raise SystemExit("MAFRA_KEY가 .env에 없습니다")

    done_dates: set[str] = set()
    old = None
    if RAW_PATH.exists():
        old = pd.read_csv(RAW_PATH, parse_dates=["date"])
        done_dates = set(old["date"].dt.date.astype(str))
        print(f"기존 진행분 {len(old)}행, {len(done_dates)}개 날짜 — 이어서 진행", flush=True)

    today = dt.date.today()
    months = pd.period_range(start=START, end=today.isoformat(), freq="M")
    all_new: list[dict] = []
    aborted = False
    for i, ym in enumerate(months):
        for day in SAMPLE_DAYS:
            try:
                target = dt.date(ym.year, ym.month, day)
            except ValueError:
                continue
            if target.weekday() == 6:  # 일요일 휴장 → 월요일
                target += dt.timedelta(days=1)
            if target > today or str(target) in done_dates:
                continue
            rows, ok = fetch_day(target)
            all_new.extend(rows)
            if not ok:
                print(f"[중단] {target}에서 실패(트래픽 초과 가능) — 진행분 저장 후 종료. "
                      f"내일 재실행하면 이어서 받음", flush=True)
                aborted = True
                break
            time.sleep(0.15)
        if aborted:
            break
        print(f"[{i+1}/{len(months)}] {ym} 누적 {len(all_new)}건", flush=True)
        # 체크포인트: 6개월마다 중간 저장 — 프로세스가 죽어도 진행분·트래픽 낭비 없음
        if all_new and (i + 1) % 2 == 0:
            ckpt = pd.concat([old, pd.DataFrame(all_new)], ignore_index=True) \
                if old is not None else pd.DataFrame(all_new)
            ckpt.to_csv(RAW_PATH, index=False, encoding="utf-8-sig")

    new_df = pd.DataFrame(all_new)
    raw = pd.concat([old, new_df], ignore_index=True) if old is not None else new_df
    if raw.empty:
        print("수집된 데이터 없음")
        return
    raw.to_csv(RAW_PATH, index=False, encoding="utf-8-sig")
    print(f"저장: {RAW_PATH} ({len(raw)}행, 신규 {len(new_df)})")

    # 상위 10작물 × 시군 월별 집계 (패널 병합용)
    raw["date"] = pd.to_datetime(raw["date"])
    raw["ym"] = raw["date"].dt.to_period("M")
    top = raw[raw["crop"].isin(TOP10_CROPS)]
    agg_rows = []
    for (ym, crop, county), grp in top.groupby(["ym", "crop", "county"]):
        agg_rows.append({
            "ym": ym, "crop": crop, "crop_id": CROP_NAME_TO_ID.get(crop, crop),
            "county": county, "price_avg_kg": _wavg(grp),
            "qty_total_kg": grp["qty_kg"].sum(), "n_obs": len(grp),
        })
    agg = pd.DataFrame(agg_rows)
    agg.to_csv(AGG_PATH, index=False, encoding="utf-8-sig")
    print(f"저장: {AGG_PATH} ({len(agg)}행)")
    if not agg.empty:
        print("\n시군별 관측월수(작물 합산):")
        print(agg.groupby("county")["ym"].nunique().sort_values(ascending=False).to_string())


if __name__ == "__main__":
    main()
