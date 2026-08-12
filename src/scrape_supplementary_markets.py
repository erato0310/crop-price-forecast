# -*- coding: utf-8 -*-
"""scrape_supplementary_markets.py — 누락된 전국 공영도매시장 7곳 보강 수집.

────────────────────────────────────────────────────────────────
왜 필요한가
────────────────────────────────────────────────────────────────
기존 23개 시장은 '상추 기준 TOP17 + 보강 6'으로 뽑은 목록이고, "커버리지 100%"는
**그 23개 안에서 계산한 값**이라 순환논법이었다. 실제로 전국 도매시장 코드를
전수 탐색(2026-08-12, 870요청)하니 30곳이 나왔고 7곳이 빠져 있었다.

  320101 춘천   320201 원주   320301 강릉   330201 충주
  370101 포항   370401 안동   380201 울산

전북산 상추 기준으로는 영향이 없다(2025년 25건). 그러나 **강원 3곳은 고랭지
물량의 산지 가격을 직접 담고 있다.** 지금은 강원 공급을 전국 축에서 간접
추정하는데, 이 시장들을 넣으면 여름 대체공급을 직접 관측할 수 있다.

  시장    2025 상추 전체   그중 전북산
  춘천        1,595건          0건
  원주        2,360건          0건
  강릉        1,848건         14건
  충주        2,325건         11건
  포항        2,273건          0건
  안동           77건          0건
  울산        4,011건          0건

────────────────────────────────────────────────────────────────
체크포인트 설계 — 쿼터가 끊겨도 손실 0
────────────────────────────────────────────────────────────────
본 스크래퍼(scrape_lettuce_daily.py)는 상태를 **월 단위**로 기록한다. 그래서
시장을 추가하면 "그 달은 이미 받았다"고 판단해 새 시장을 영영 건너뛴다.
여기서는 **(시장, 월) 쌍 단위**로 기록해 그 문제를 피한다.

  - 매 (시장, 월)을 받는 즉시 append 저장. 프로세스가 죽어도 그 직전까지 남는다
  - 상태는 supp_state.json 에 (시장, 월) 쌍 목록으로 누적
  - 쿼터 소진(429 + LIMITED_NUMBER)이면 재시도하지 않고 즉시 정상 종료
  - 다음 실행 시 남은 쌍만 이어받는다

[실행]
  python scrape_supplementary_markets.py fetch     # 수집(이어받기 자동)
  python scrape_supplementary_markets.py status    # 진행 상황만 확인
  python scrape_supplementary_markets.py merge     # 본 파일에 합치기
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")

from scrape_lettuce_daily import (  # noqa: E402
    URL, MAX_UNIT_QTY_KG, _kg_fields, parse_county, parse_sido,
    PAGE_ROWS, REQUEST_DELAY_SEC, _QUOTA_MARKERS, QuotaExhausted,
)

KEY = urllib.parse.unquote(os.getenv("DATA_GO_KR_KEY", ""))
RAW = _ROOT / "data" / "raw"
SUPP_PATH = RAW / "lettuce_daily_supp.csv"
STATE_PATH = RAW / "lettuce_daily_supp_state.json"
MAIN_PATH = RAW / "lettuce_daily_raw.csv"

START = "2018-01"

# 전수 탐색(2026-08-12)에서 확인된 누락 시장.
#
# [2차 확인] 코드 접두 스캔만으로는 2곳을 놓쳤다. at 도매시장 통합홈페이지가
# "전국 32개 공영도매시장"이라 명시해 재확인한 결과, katRealTime2/trades2로
# **시장코드 없이 전국을 조회**하면 실제 목록이 나온다는 것을 알았다.
# 접두 추측이 아니라 이 방법이 권위 있는 목록이다.
#   추가 발견: 310901 안산(2025 전북산 432건), 371501 구미(0건)
SUPP_MARKETS: dict[str, str] = {
    "춘천": "320101", "원주": "320201", "강릉": "320301",
    "충주": "330201", "포항": "370101", "안동": "370401", "울산": "380201",
    "안산": "310901", "구미": "371501",
}

MAX_RETRY = 4


def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            s = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            s["done"] = set(tuple(x) for x in s.get("done", []))
            return s
        except Exception:
            print("[경고] state 파일이 깨져 처음부터 받는다")
    return {"done": set(), "failed": []}


def _save_state(s: dict) -> None:
    STATE_PATH.write_text(json.dumps(
        {"done": sorted(list(x) for x in s["done"]), "failed": s.get("failed", []),
         "updated": dt.datetime.now().isoformat(timespec="seconds")},
        ensure_ascii=False, indent=1), encoding="utf-8")


def _get(params: dict) -> dict | None:
    for attempt in range(MAX_RETRY):
        try:
            r = requests.get(URL, params=params, timeout=90)
            if r.status_code in (429, 200) and any(m in r.text for m in _QUOTA_MARKERS):
                raise QuotaExhausted("일일 요청 한도 초과")
            r.raise_for_status()
            return r.json().get("response", {}).get("body", {})
        except QuotaExhausted:
            raise
        except Exception as e:
            if attempt == MAX_RETRY - 1:
                return None
            st = getattr(getattr(e, "response", None), "status_code", None)
            time.sleep((10.0 if st in (429, 504) else 2.0) * (attempt + 1))
    return None


def fetch_market_month(cd: str, ym: pd.Period) -> tuple[list[dict], bool]:
    s = ym.start_time.date()
    e = min(ym.end_time.date(), dt.date.today())
    cond = {
        "serviceKey": KEY, "returnType": "JSON",
        "cond[whsl_mrkt_cd::EQ]": cd,
        "cond[trd_clcln_ymd::GTE]": s.isoformat(),
        "cond[trd_clcln_ymd::LTE]": e.isoformat(),
        "cond[gds_mclsf_nm::EQ]": "상추",
        "numOfRows": PAGE_ROWS,
    }
    rows: list[dict] = []
    page, total = 1, None
    while True:
        b = _get({**cond, "pageNo": page})
        if b is None:
            return rows, False
        if total is None:
            total = int(b.get("totalCount") or 0)
        items = b.get("items", {}).get("item", [])
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
            plor = it.get("plor_nm")
            try:
                uq = float(it.get("unit_qty") or 0)
            except (TypeError, ValueError):
                uq = 0.0
            pkg, qkg = _kg_fields(price, qty, it.get("unit_nm"), uq)
            rows.append({
                "date": it.get("trd_clcln_ymd"), "market_cd": cd,
                "county": parse_county(plor), "sido": parse_sido(plor),
                "plor_cd": it.get("plor_cd"), "plor_nm": plor,
                "variety": it.get("gds_sclsf_nm"), "grade": it.get("grd_nm"),
                "trd_se": it.get("trd_se"), "price": price, "qty": qty,
                "unit_nm": it.get("unit_nm"), "unit_qty": uq,
                "price_kg": pkg, "qty_kg": qkg,
            })
        if not items or page * PAGE_ROWS >= (total or 0):
            break
        page += 1
        time.sleep(REQUEST_DELAY_SEC)
    return rows, True


def _append(rows: list[dict]) -> None:
    """받는 즉시 덧붙인다. 프로세스가 죽어도 여기까지는 남는다."""
    if not rows:
        return
    df = pd.DataFrame(rows)
    header = not SUPP_PATH.exists()
    df.to_csv(SUPP_PATH, mode="a", header=header, index=False,
              encoding="utf-8-sig")


def cmd_fetch() -> None:
    if not KEY:
        sys.exit("DATA_GO_KR_KEY 없음")
    end = dt.date.today()
    months = list(pd.period_range(start=START, end=end.isoformat(), freq="M"))
    st = _load_state()
    todo = [(nm, cd, ym) for nm, cd in SUPP_MARKETS.items() for ym in months
            if (cd, str(ym)) not in st["done"]]
    total_pairs = len(SUPP_MARKETS) * len(months)
    print(f"보강 시장 {len(SUPP_MARKETS)}곳 x {len(months)}개월 = {total_pairs} 쌍")
    print(f"  완료 {len(st['done'])} / 남은 {len(todo)}")
    if not todo:
        print("전부 완료됨")
        return

    t0 = time.time()
    got = 0
    quota = False
    for i, (nm, cd, ym) in enumerate(todo, 1):
        try:
            rows, ok = fetch_market_month(cd, ym)
        except QuotaExhausted:
            quota = True
            break
        if not ok:
            st["failed"] = sorted(set(st.get("failed", [])) | {f"{cd}|{ym}"})
            _save_state(st)
            print(f"  ! 실패 {nm} {ym} — 다음 실행에서 재시도", flush=True)
            continue
        _append(rows)                      # 즉시 저장
        st["done"].add((cd, str(ym)))
        _save_state(st)                    # 즉시 상태 갱신
        got += len(rows)
        if i % 20 == 0 or i == len(todo):
            el = (time.time() - t0) / 60
            print(f"  [{i}/{len(todo)}] {nm} {ym}  누적 {got:,}건  "
                  f"{el:.1f}분  남은 {len(todo)-i}", flush=True)
        time.sleep(REQUEST_DELAY_SEC)

    print()
    if quota:
        left = total_pairs - len(st["done"])
        print(f"[중단] 일일 요청 한도 초과. 여기까지 안전하게 저장됨.")
        print(f"  완료 {len(st['done'])}/{total_pairs} 쌍, 남은 {left} 쌍")
        print(f"  자정(KST) 이후 같은 명령을 다시 실행하면 정확히 이어받는다.")
    else:
        print(f"완료: {len(st['done'])}/{total_pairs} 쌍, 이번에 {got:,}건 추가")
    if SUPP_PATH.exists():
        print(f"  {SUPP_PATH.name}: {sum(1 for _ in open(SUPP_PATH, encoding='utf-8-sig'))-1:,}행")


def cmd_status() -> None:
    st = _load_state()
    months = list(pd.period_range(start=START, end=dt.date.today().isoformat(),
                                  freq="M"))
    total = len(SUPP_MARKETS) * len(months)
    print(f"진행 {len(st['done'])}/{total} 쌍 ({len(st['done'])/total*100:.1f}%)")
    for nm, cd in SUPP_MARKETS.items():
        n = sum(1 for c, _ in st["done"] if c == cd)
        print(f"  {nm:<6}{cd}  {n:>4}/{len(months)}개월")
    if st.get("failed"):
        print(f"  실패 대기 {len(st['failed'])}건: {st['failed'][:5]}")
    if SUPP_PATH.exists():
        d = pd.read_csv(SUPP_PATH, dtype={"market_cd": str}, low_memory=False)
        print(f"\n수집물 {len(d):,}행")
        print(f"  전북산 {d['county'].notna().sum():,}건")
        print(f"  시도별 상위: {d['sido'].value_counts().head(5).to_dict()}")


# 산지가 아니라 **경유지**로 찍힌 레코드. 가락시장에서 경매된 물량이 지방
# 시장으로 재출하되면 plor_nm이 '서울 송파구 가락1동 가락농수산물시장'이 된다.
# 그대로 두면 같은 상추가 두 번 계상된다.
#   기존 23개 시장: 건수 4.53%, 물량 0.58% (전북산 중에는 0건 — 영향 없었음)
#   보강 춘천 시장: 산지의 60%가 가락 재출하 (강원 시장인데 서울산 1위로 잡힘)
# 전북산 타깃에는 영향이 없지만 전국 물량·산지 점유율 지표는 오염되므로 거른다.
_RELAY = re.compile(r"가락|도매시장|농수산물시장|공판장|청과")


def cmd_merge() -> None:
    """본 파일에 합친다. market_cd가 서로 겹치지 않으므로 중복 위험이 없다."""
    if not SUPP_PATH.exists():
        sys.exit("보강 수집물 없음")
    supp = pd.read_csv(SUPP_PATH, dtype={"market_cd": str, "plor_cd": str},
                       low_memory=False)
    relay = supp["plor_nm"].fillna("").str.contains(_RELAY)
    if relay.any():
        print(f"재출하(경유지) 제외 {int(relay.sum()):,}행 "
              f"({relay.sum()/len(supp)*100:.1f}%) — 산지가 아니라 가락 등 경유 표기")
        supp = supp[~relay]
    main = pd.read_csv(MAIN_PATH, dtype={"market_cd": str, "plor_cd": str},
                       low_memory=False)
    overlap = set(supp["market_cd"]) & set(main["market_cd"])
    if overlap:
        sys.exit(f"시장코드가 겹친다 — 병합 중단: {overlap}")
    out = pd.concat([main, supp], ignore_index=True)
    bak = MAIN_PATH.with_suffix(".before_supp.csv")
    if not bak.exists():
        main.to_csv(bak, index=False, encoding="utf-8-sig")
        print(f"백업: {bak.name}")
    out.to_csv(MAIN_PATH, index=False, encoding="utf-8-sig")
    print(f"병합 완료: {len(main):,} + {len(supp):,} = {len(out):,}행, "
          f"시장 {out['market_cd'].nunique()}곳")
    print("  이후 scrape_lettuce_daily.py --reaggregate 로 집계 갱신할 것")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "status", "merge"])
    a = ap.parse_args()
    {"fetch": cmd_fetch, "status": cmd_status, "merge": cmd_merge}[a.cmd]()


if __name__ == "__main__":
    main()
