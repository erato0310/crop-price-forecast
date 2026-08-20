# -*- coding: utf-8 -*-
"""fetch_retail_kamis.py — KAMIS 소매·도매 상추 가격 수집 (품종별).

────────────────────────────────────────────────────────────────
왜
────────────────────────────────────────────────────────────────
우리 자료는 **도매시장 경락가**다. 농가가 받는 값이다. 그런데 "상추값이
올랐다"는 뉴스는 대개 **소매가**를 말한다. 둘의 격차가 유통마진이고,
농가로서는 그 격차가 얼마나 되는지가 관심사다.

KAMIS(농산물유통정보)는 같은 품목의 소매가와 도매가를 함께 준다.
품종 코드가 우리 자료와 맞아떨어진다.

    kind 01 = 적상추 (1kg)
    kind 02 = 청상추 (1kg)

**도매가는 검증에도 쓴다.** 우리 자료도 도매시장 경락가이므로 KAMIS 도매와
크게 어긋나면 우리 집계 어딘가가 잘못된 것이다.

────────────────────────────────────────────────────────────────
주의
────────────────────────────────────────────────────────────────
- KAMIS는 **전국 평균**이다. 전북산만 뽑을 수 없다. 지역 비교에는 못 쓰고
  '전북 산지 vs 전국 소매' 수준의 대조로만 쓴다.
- **일별 자료는 최근 1년만 준다.** 실측: 2025-09는 정상, 2025-06 이전을 요청하면
  요청을 무시하고 최근 1년을 돌려준다(243일이 그대로 반복돼 나온다).
  과거는 `yearlySalesList`가 연평균만 준다(2021~).
- KAMIS 도매는 **중도매인 판매가격**이다. 우리 자료의 경락가보다 한 단계 위다.
  경락가 -> 중도매인 판매가 -> 소매가 순으로 붙는 것이라 그대로 견주면 안 된다.
- `p_convert_kg_yn=Y` 로 kg 환산을 요청한다. 원자료는 1kg 단위 표기다.
- 소매는 조사처(대형마트·전통시장 등)가 섞인 평균이다.

[실행] python fetch_retail_kamis.py            # 2018~현재
       python fetch_retail_kamis.py --start 2024
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = RAW / "kamis_lettuce_retail.csv"

URL = "https://www.kamis.or.kr/service/price/xml.do"
ITEM = "214"                      # 상추
CATEGORY = "200"                  # 엽채류
KINDS = {"01": "적상추", "02": "청상추"}
CLS = {"01": "소매", "02": "도매"}
DELAY = 0.4


def fetch(cls: str, kind: str, start: str, end: str, key: str, cid: str) -> list[dict]:
    p = {
        "action": "periodProductList",
        "p_productclscode": cls,
        "p_itemcategorycode": CATEGORY,
        "p_itemcode": ITEM,
        "p_kindcode": kind,
        "p_productrankcode": "",
        "p_startday": start, "p_endday": end,
        "p_convert_kg_yn": "Y",
        "p_cert_key": key, "p_cert_id": cid,
        "p_returntype": "json",
    }
    r = requests.get(URL, params=p, timeout=60)
    r.raise_for_status()
    js = r.json()
    data = js.get("data", {})
    items = data.get("item") if isinstance(data, dict) else None
    if not items:
        return []
    if isinstance(items, dict):
        items = [items]
    rows = []
    for it in items:
        # 지역별 행이 섞여 오므로 '평균'만 쓴다
        if str(it.get("countyname", "")) != "평균":
            continue
        yyyy, regday = str(it.get("yyyy", "")), str(it.get("regday", ""))
        price = str(it.get("price", "")).replace(",", "")
        if "/" not in regday or not price.replace(".", "").isdigit():
            continue
        mm, dd = regday.split("/")
        try:
            d = dt.date(int(yyyy), int(mm), int(dd))
        except ValueError:
            continue
        rows.append({"date": d, "cls": CLS[cls], "variety": KINDS[kind],
                     "price": float(price)})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    # 어차피 최근 1년만 온다. 과거 연도를 넣어도 같은 자료가 반복될 뿐이다.
    ap.add_argument("--start", type=int, default=dt.date.today().year - 1)
    a = ap.parse_args()

    load_dotenv(ROOT / ".env")
    key, cid = os.getenv("KAMIS_CERT_KEY", ""), os.getenv("KAMIS_CERT_ID", "")
    if not key or not cid:
        raise SystemExit("KAMIS_CERT_KEY / KAMIS_CERT_ID 가 .env 에 없습니다")

    today = dt.date.today()
    rows: list[dict] = []
    for year in range(a.start, today.year + 1):
        s = f"{year}-01-01"
        e = f"{year}-12-31" if year < today.year else today.isoformat()
        for cls in CLS:
            for kind in KINDS:
                try:
                    got = fetch(cls, kind, s, e, key, cid)
                except Exception as ex:
                    print(f"  ! {year} {CLS[cls]} {KINDS[kind]} 실패: {ex}")
                    got = []
                rows += got
                print(f"  {year} {CLS[cls]:<3} {KINDS[kind]:<4} {len(got):>4}일")
                time.sleep(DELAY)

    if not rows:
        raise SystemExit("받은 자료가 없습니다")
    d = pd.DataFrame(rows).drop_duplicates(["date", "cls", "variety"])
    d = d.sort_values(["variety", "cls", "date"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(OUT, index=False, encoding="utf-8-sig")
    print()
    print(f"저장: {OUT} ({len(d):,}행)")
    print(d.groupby(["variety", "cls"]).agg(
        일수=("price", "size"), 시작=("date", "min"), 끝=("date", "max"),
        평균=("price", "mean")).round(0).to_string())


if __name__ == "__main__":
    main()
