# -*- coding: utf-8 -*-
"""scrape_lettuce_daily.py — 상추 **전 일자** 경락 데이터 수집.

[왜 새로 만들었나]
기존 scrape_jeonbuk_all_crops.py는 매월 5·15·25일 **3일만** 표본으로 받는다
(scrape_jeonbuk_origin.SAMPLE_DAYS). 한 달에 23~27 거래일이 있으니 실측치의
약 88%를 버리는 셈이고, 그 3일 중 휴장이 겹치면 월 표본이 1~2일로 주저앉는다.
`build_dataset.MIN_OBS_PER_MONTH=2` 필터에 걸려 통째로 사라진 월도 있었다.

[핵심: 일별 수집이 표본 수집보다 오히려 싸다]
API 파라미터를 다시 조사해서(2026-08-11 실측) 두 가지를 확인했다.

  1. `cond[gds_mclsf_nm::EQ]=상추`  — 품목 서버측 필터. all_crops 스크래퍼는 10개
     작물을 한 번에 받으려고 이 필터를 **뺐고**, 그래서 응답이 작물 전체로 부풀었다.
     상추만 걸면 market-day당 평균 58건(1페이지)으로 줄어든다.
  2. `cond[trd_clcln_ymd::GTE/::LTE]` — **날짜 범위 조회가 된다.** 하루씩 부를 필요가
     없다. 시장 1곳의 여러 달치를 한 번에 받는다.

  범위조회의 무결성은 실측 확인했다 — 가락 2025-08에서 totalCount(3,316) == 수집행수,
  완전동일 행 0건, 개별 일자 호출과 일별 건수 완전 일치(3개 시장 x 3개월, 18일 대조
  불일치 0건). `--verify` 참고.

[호출 예산 — 이게 이 스크립트 설계를 지배한다]
katSale은 **일일 요청 한도**가 있다. 2026-08-11 실측: 약 1,900회에서
`LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR`(HTTP 429, reasonCode 22).
HANDOFF에 적힌 "~1만"보다 훨씬 낮으니 그 수치를 믿지 말 것.

  104개월 x 23시장 국내 전량 기준 실측/추정 소요:
     1개월 단위 조회  2,131회  <- 하루 예산 초과, 이틀 필요
     3개월 단위 조회  1,593회  <- 기본값. 하루에 완주
     3개월 + 전북산만   620회  <- --scope jeonbuk

  chunk를 넓힐수록 기본요청이 줄지만 응답이 무거워진다. 실측(가락 상추):
     1개월  3,316건 0.7s / 3개월  9,964건 1.4s / 6개월 18,662건 29s / 1년 504 timeout
  그래서 3개월이 상한이다. CHUNK_MONTHS를 6 이상으로 올리지 말 것.

[산지 필터]
`cond[plor_nm::LIKE]=전북`도 서버측에서 동작하며 **무손실**임을 확인했다(가락
2019-08·2025-08에서 클라이언트 필터 결과와 고유키 집합까지 완전 일치). 또한 API가
산지명을 현행 명칭으로 소급 정규화해 두어서, 2018년 데이터도 '전라북도'가 아니라
'전북'으로 매칭된다(LIKE '전라북도' = 0건). 그래도 파싱은 구 지명까지 받아둔다.

[자료원 — 도매시장만]
katSale(공영도매시장 경락) 하나만 쓴다. 산지공판장(MAFRA gpj)은 **의도적으로 뺐다** —
공판장 물량은 결국 도매시장으로 넘어가 다시 경매되므로 합치면 같은 상추를 두 번 센다.
같은 이유로 산지명이 시장·공판장으로 찍힌 재출하 레코드도 거른다
(scrape_supplementary_markets._RELAY 참고).

[scope]
  national (기본) 산지 무관 전량. 전북산은 이 안에 포함된다. 비용이 2.5배지만
                  (a) 여름철 고랭지(강원) 대체 물량, (b) 전국-전북 가격 스프레드를
                  같이 얻는다 — HANDOFF_rev2 7.1·7.4가 지목한 두 한계에 직접 대응.
  jeonbuk         전북산만. 620회로 싸다. 산지 이동 분석은 포기.

[재개]
완료 월 목록을 `lettuce_daily_state.json`에 **명시적으로** 기록한다. 데이터에서
역추론하지 않는다 — 일부 시장만 성공한 월이 "수집됨"으로 보여 영구히 스킵되는
사고를 막기 위해서다(all_crops 스크래퍼가 실제로 이 구조였다). 쿼터 소진·네트워크
실패로 끊긴 월은 state에 들어가지 않으므로 다음 실행에서 자동으로 다시 받는다.

[출력]
  data/raw/lettuce_daily_raw.csv             일별 레코드 원본(scope에 따름)
  data/raw/lettuce_daily_by_county.csv       전북 시군 x 일자 물량가중 집계
  data/raw/lettuce_daily_by_origin_sido.csv  시도 x 일자 집계(산지 이동 분석용)
  data/raw/lettuce_daily_partial.csv         체크포인트(완주 시 삭제)
  data/raw/lettuce_daily_state.json          완료 월 · 실패 기록

[실행]
  python scrape_lettuce_daily.py                 # 전량, 2018-01~오늘 (이어받기 자동)
  python scrape_lettuce_daily.py --scope jeonbuk
  python scrape_lettuce_daily.py --chunk 1       # 응답이 무거우면 좁힌다
  python scrape_lettuce_daily.py --verify        # 범위조회 == 일별조회 재확인만
  python scrape_lettuce_daily.py --reaggregate   # 재수집 없이 집계만 다시
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

KEY = urllib.parse.unquote(os.getenv("DATA_GO_KR_KEY", ""))
URL = "https://apis.data.go.kr/B552845/katSale/trades"
OUT_DIR = _ROOT / "data" / "raw"
OUT_DIR.mkdir(parents=True, exist_ok=True)

RAW_PATH = OUT_DIR / "lettuce_daily_raw.csv"
COUNTY_PATH = OUT_DIR / "lettuce_daily_by_county.csv"
SIDO_PATH = OUT_DIR / "lettuce_daily_by_origin_sido.csv"
PARTIAL_PATH = OUT_DIR / "lettuce_daily_partial.csv"
STATE_PATH = OUT_DIR / "lettuce_daily_state.json"
MANIFEST_PATH = OUT_DIR / "lettuce_daily_manifest.csv"

START = "2018-01"
PAGE_ROWS = 1000
CHUNK_MONTHS = 1          # 1개월 = 사용자 지정. 상단 주석의 응답시간 실측 참고.
                          # 넓힐수록 요청은 줄지만 6개월부터 504로 끊긴다.
REQUEST_DELAY_SEC = 0.15
MAX_RETRY = 5

# scrape_jeonbuk_all_crops.MARKETS와 동일(상추 기준 TOP17 + 커버리지 보강 6곳).
# 상추 물량 기준 이 23곳이 전북산 누적 100%를 담는다(상위 12곳에서 이미 95.6%).
MARKETS: dict[str, str] = {
    "광주서부": "240004", "서울가락": "110001", "광주각화": "240001",
    "부산반여": "210009", "부산엄궁": "210001", "대구북부": "220001",
    "대전오정": "250001", "창원내서": "380303", "전주": "350101",
    "익산": "350301", "대전노은": "250003", "순천": "360301",
    "인천남촌": "230001", "서울강서": "110008", "인천삼산": "230003",
    "창원팔용": "380101", "진주": "380401", "구리": "311201",
    "청주": "330101", "천안": "340101", "정읍": "350402",
    "안양": "310401", "수원": "310101",
}

# price_kg = avgprc / unit_qty 를 계산할 때만 쓰는 상한. unit_qty가 포장중량이
# 아닌 값(3001 등)을 담은 극소수 레코드에서 단가가 수백분의 1로 찌그러진다.
MAX_UNIT_QTY_KG = 50.0

# ─────────────────────────────────────────────────────────────
# [2026-08-11 정정] qty_kg 계산 버그 — unit_tot_qty는 **이미 kg 총량**이다
# ─────────────────────────────────────────────────────────────
# scrape_jeonbuk_all_crops._kg_fields 가 `qty_kg = unit_tot_qty * unit_qty` 로
# 계산하는데, 이건 틀렸다. 원본 응답으로 검산하면 드러난다:
#
#     avgprc 13,800 / unit_qty 4.0 / unit_tot_qty 240.0 / totprc 828,000
#         totprc / avgprc      = 60      -> 60상자 거래
#         60상자 x 4kg          = 240kg  = unit_tot_qty  (일치)
#         totprc / unit_tot_qty = 3,450원/kg = avgprc / unit_qty  (일치)
#
# 즉 unit_tot_qty가 곧 kg 총량이고, unit_qty를 또 곱하면 상자무게배(상추는
# 주로 4배)로 부풀어난다. 규모로도 확인된다:
#
#     현행 계산: 전북산 상추 도매출하 50,078 톤/년
#     수정 계산:                    13,559 톤/년
#     KOSIS 전북 상추 생산량(2018~20): 26,190 톤/년
#
# 출하량이 생산량의 1.91배일 수는 없다. 수정하면 52%로 도매시장 출하율에 맞는다.
#
# 영향: 가격(price_kg)은 원래 맞았다(0~5% 차이). 틀린 것은 물량이고, 그래서
# (a) 물량가중평균의 가중치, (b) 출하 비중, (c) qty를 피처로 쓰는 모델이 영향받는다.
# 비중은 unit_qty 구성이 지역마다 비슷해 대부분 상쇄된다(시군 비중 1~5pp 이동).
#
# 같은 버그가 scrape_jeonbuk_all_crops.py 에 남아 있다 — 10작물 파이프라인·웹앱
# 물량 표시가 전부 부풀려져 있으니 별도로 고쳐야 한다.


def _kg_fields(price: float, qty: float, unit_nm, unit_qty: float) -> tuple[float, float]:
    """(price_kg, qty_kg). qty 인자는 응답의 unit_tot_qty = **이미 kg 총량**.

    price_kg만 unit_qty가 필요하다. unit_qty가 신뢰 불가여도 qty_kg는 살린다 —
    그 레코드는 가격 평균에서만 빠지고 물량 집계에는 정상적으로 들어간다.
    """
    nan = float("nan")
    if unit_nm != "kg":
        return nan, nan
    price_kg = price / unit_qty if (0 < unit_qty <= MAX_UNIT_QTY_KG) else nan
    return price_kg, qty

# ─────────────────────────────────────────────────────────────
# 품종 분리 — '상추'는 단일 품목이 아니다
# ─────────────────────────────────────────────────────────────
# gds_sclsf_nm이 13종으로 나뉘고 가격대가 3.8배 차이난다(꽃적상추 4,103 ~
# 상추솎음 1,087 원/kg). 전부 섞어 물량가중하면 '가격 변동'과 '상품 구성 변화'가
# 뒤섞인다. 실측: 9월 주력만 7,068원 vs 전품종 6,412원 -> 10.2% 차이.
#
# 특히 **쫑상추는 품종이 아니라 작기 단계다.** 한 작기가 끝날 무렵 순을 꺾어
# 내는 것이라, 출하 자체가 "그 작기가 마무리됐다"는 뜻이다. 그리고 주력 상추가
# 귀할 때 대체 수요가 붙어 쫑상추 가격이 오른다(현장 지식).
# 그래서 평균에 섞지 않고 **독립 계열로 따로 뽑는다** — 타깃 오염을 막으면서
# 수급 신호는 보존한다.
# [2026-08-12 정정] 목록을 **열거하지 말고 배제로 정의한다.**
#
# 처음엔 관찰된 품종을 손으로 적어 MAIN_VARIETIES를 만들었는데, 그 방식이면
# 새 품종이 등장하거나 내가 못 본 품종이 있을 때 **조용히 타깃에서 빠진다.**
# 실제로 그랬다 — 감사(audit_hardcoded_lists.py)에서 5종이 어느 분류에도
# 없는 것으로 드러났고, 그중 '기타'가 3,042t(2.17%)였다.
#
# '기타'는 정상 상추다. 104개월 전 구간·14개 시군 전체에 나오고 가격 3,998원
# (주력 4,174원), 여름/겨울 배율 2.02배(주력 1.93배)로 주력과 같이 움직인다.
# 세부 품종만 미기재된 것이다.
#
# 그래서 규칙을 뒤집었다. **작기 단계 지표로 따로 뺄 것만 명시하고, 나머지는
# 전부 주력으로 본다.** 이러면 새 품종이 들어와도 자동으로 포함된다.
JJONG_VARIETIES = ["쫑상추", "상추순"]      # 작기 종료 신호. 순을 꺾어 내는 것
THIN_VARIETIES = ["상추솎음"]               # 작기 초반 신호. 솎아낸 것
EXCLUDE_FROM_MAIN = set(JJONG_VARIETIES) | set(THIN_VARIETIES)


def is_main_variety(v) -> bool:
    """주력(정상 수확물)인가. 배제 목록에 없으면 전부 주력이다."""
    return v is not None and v == v and str(v) not in EXCLUDE_FROM_MAIN


# 하위호환: 기존 코드가 MAIN_VARIETIES를 import한다. 실제 자료에서 열거해 채운다.
def _discover_main() -> list[str]:
    p = OUT_DIR / "lettuce_daily_raw.csv"
    if not p.exists():
        return []
    try:
        vs = pd.read_csv(p, usecols=["variety"], low_memory=False)["variety"]
        return sorted({str(v) for v in vs.dropna().unique()
                       if str(v) not in EXCLUDE_FROM_MAIN})
    except Exception:
        return []


MAIN_VARIETIES = _discover_main()

_COUNTY_RE = re.compile(r"전(?:북특별자치도|라북도|북)\s*([가-힣]+(?:시|군))")
_SIDO_RE = re.compile(r"^([가-힣]+?(?:특별자치도|특별자치시|특별시|광역시|남도|북도|도))")

_QUOTA_MARKERS = ("LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR",
                  "SERVICE_KEY_IS_NOT_REGISTERED_ERROR")

COUNT_MISMATCH: list[dict] = []

# 수집 원장. (시장, 구간)마다 서버가 알려준 totalCount와 실제 저장 행수·페이지수·거래일수를
# 남긴다. 나중에 audit_lettuce_daily.py가 이걸로 "빠진 날/겹친 날"을 산술 대조한다.
# 원본 응답의 건수는 그 순간에만 알 수 있으므로 수집 시점에 반드시 적어 둬야 한다.
MANIFEST: list[dict] = []


class QuotaExhausted(RuntimeError):
    """일일 요청 한도 초과. 재시도해도 소용없으니 즉시 중단한다."""


def parse_county(plor_nm: str | None) -> str | None:
    """'전북특별자치도 남원시 운봉읍' -> '남원시'. 전북이 아니면 None."""
    if not plor_nm:
        return None
    m = _COUNTY_RE.search(plor_nm)
    return m.group(1) if m else None


def parse_sido(plor_nm: str | None) -> str | None:
    """'충청남도 논산시' -> '충청남도'. '전북특별자치도 익산시' -> '전북특별자치도'."""
    if not plor_nm:
        return None
    m = _SIDO_RE.match(plor_nm.strip())
    return m.group(1) if m else plor_nm.strip().split()[0]


def _get(params: dict, timeout: int = 120) -> dict | None:
    """재시도 포함 단일 호출. 쿼터 소진이면 QuotaExhausted, 그 외 실패면 None."""
    for attempt in range(MAX_RETRY):
        try:
            r = requests.get(URL, params=params, timeout=timeout)
            # 쿼터 초과는 429 + OpenAPI_ServiceResponse 봉투로 온다. raise_for_status가
            # 본문을 안 보고 던져버리면 무한 재시도에 빠지므로 먼저 본문을 확인한다.
            if r.status_code in (429, 200) and any(m in r.text for m in _QUOTA_MARKERS):
                raise QuotaExhausted(next(m for m in _QUOTA_MARKERS if m in r.text))
            r.raise_for_status()
            return r.json().get("response", {}).get("body", {})
        except QuotaExhausted:
            raise
        except Exception as e:
            if attempt == MAX_RETRY - 1:
                return None
            status = getattr(getattr(e, "response", None), "status_code", None)
            time.sleep((10.0 if status in (429, 504) else 2.0) * (attempt + 1))
    return None


def fetch_market_range(market_cd: str, start: dt.date, end: dt.date,
                       scope: str) -> tuple[list[dict], bool]:
    """시장 1곳 x [start, end] 상추 레코드 전부. (rows, ok) 반환."""
    cond = {
        "serviceKey": KEY, "returnType": "JSON",
        "cond[whsl_mrkt_cd::EQ]": market_cd,
        "cond[trd_clcln_ymd::GTE]": start.isoformat(),
        "cond[trd_clcln_ymd::LTE]": end.isoformat(),
        "cond[gds_mclsf_nm::EQ]": "상추",
        "numOfRows": PAGE_ROWS,
    }
    if scope == "jeonbuk":
        cond["cond[plor_nm::LIKE]"] = "전북"

    rows: list[dict] = []
    seen: dict[tuple, int] = {}   # 레코드 서명 -> 처음 나온 페이지 번호
    dup_pages = 0
    page, total = 1, None
    while True:
        body = _get({**cond, "pageNo": page})
        if body is None:
            print(f"    ! 실패({MAX_RETRY}회): {market_cd} {start}~{end} p{page}", flush=True)
            return rows, False
        if total is None:
            total = int(body.get("totalCount") or 0)
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
            plor = it.get("plor_nm")
            try:
                unit_qty = float(it.get("unit_qty") or 0)
            except (TypeError, ValueError):
                unit_qty = 0.0
            unit_nm = it.get("unit_nm")
            price_kg, qty_kg = _kg_fields(price, qty, unit_nm, unit_qty)
            # 페이지 경계 중복 탐지. 같은 날 동일 조건 거래가 여러 건인 것은 **정상**이고
            # 실제로 존재한다(HANDOFF의 gpj 중복버그 절에 실측 근거 있음). 그래서 같은
            # 페이지 안의 동일 레코드는 세지 않고, **다른 페이지에 같은 레코드가 또
            # 나오는 경우만** 센다 — 그건 서버 정렬이 불안정해 페이지가 겹쳤다는 뜻이다.
            sg = tuple(sorted((str(k), str(v)) for k, v in it.items()))
            prev_page = seen.get(sg) if isinstance(seen, dict) else None
            if prev_page is not None and prev_page != page:
                dup_pages += 1
            else:
                seen[sg] = page
            rows.append({
                "date": it.get("trd_clcln_ymd"),
                "market_cd": market_cd,
                "county": parse_county(plor),
                "sido": parse_sido(plor),
                "plor_cd": it.get("plor_cd"),
                "plor_nm": plor,
                "variety": it.get("gds_sclsf_nm"),
                "grade": it.get("grd_nm"),
                "trd_se": it.get("trd_se"),
                "price": price, "qty": qty,
                "unit_nm": unit_nm, "unit_qty": unit_qty,
                "price_kg": price_kg, "qty_kg": qty_kg,
            })
        if not items or page * PAGE_ROWS >= (total or 0):
            break
        page += 1
        time.sleep(REQUEST_DELAY_SEC)

    # 가격/물량<=0으로 걸러진 분은 정상 감소이므로 '초과'만 이상으로 본다.
    if total is not None and len(rows) > total:
        COUNT_MISMATCH.append({"market_cd": market_cd, "range": f"{start}~{end}",
                               "totalCount": total, "collected": len(rows)})
    MANIFEST.append({
        "market_cd": market_cd, "start": start.isoformat(), "end": end.isoformat(),
        "ym": start.strftime("%Y-%m"),
        "total_count": total,            # 서버가 신고한 건수
        "collected": len(rows),          # 필터 통과 후 저장한 건수
        "pages": page,
        "n_days": len({r["date"] for r in rows}),
        "cross_page_dupes": dup_pages,   # >0이면 페이징이 겹쳤다는 뜻
        "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
    })
    return rows, True


def _save_manifest() -> None:
    """원장을 누적 저장. 재개 시에도 이어 붙는다(과거 기록을 지우지 않는다)."""
    if not MANIFEST:
        return
    new = pd.DataFrame(MANIFEST)
    if MANIFEST_PATH.exists():
        old = pd.read_csv(MANIFEST_PATH, dtype={"market_cd": str})
        new = pd.concat([old, new], ignore_index=True)
    new.to_csv(MANIFEST_PATH, index=False, encoding="utf-8-sig")
    MANIFEST.clear()


# ── 상태 관리 ──────────────────────────────────────────────────

def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            print("[경고] state 파일이 깨져 있어 처음부터 받는다")
    return {"done_months": [], "failed_months": [], "scope": None}


def _save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                          encoding="utf-8")


def _chunks(months: list[pd.Period], size: int) -> list[list[pd.Period]]:
    """연속한 월만 한 덩어리로 묶는다. 중간이 비면(이미 받은 월) 끊는다."""
    out: list[list[pd.Period]] = []
    cur: list[pd.Period] = []
    for m in months:
        if cur and (m - cur[-1]).n != 1 or len(cur) >= size:
            out.append(cur)
            cur = []
        cur.append(m)
    if cur:
        out.append(cur)
    return out


def scrape(start: str, end: str | None, scope: str, chunk: int) -> pd.DataFrame:
    end_date = dt.date.fromisoformat(end) if end else dt.date.today()
    all_months = list(pd.period_range(start=start, end=end_date.isoformat(), freq="M"))

    state = _load_state()
    if state.get("scope") and state["scope"] != scope:
        sys.exit(f"체크포인트가 scope={state['scope']}로 모은 것이다. "
                 f"--scope {state['scope']}로 이어받거나 체크포인트를 지울 것.")
    done = set(state.get("done_months", []))

    # 재개 소스. PARTIAL이 원칙이지만, 완주 판정이 한 번 났으면(예: --end로 범위를
    # 좁혀 실행) PARTIAL이 지워지고 RAW만 남는다. 그때 RAW로 폴백하지 않으면 다음
    # 실행이 빈 상태에서 시작해 **이미 받은 달을 통째로 잃는다.**
    src = PARTIAL_PATH if PARTIAL_PATH.exists() else (
        RAW_PATH if (RAW_PATH.exists() and done) else None)
    acc: list[dict] = []
    if src is not None and done:
        prev = pd.read_csv(src, dtype={"market_cd": str, "plor_cd": str},
                           low_memory=False)
        prev["date"] = pd.to_datetime(prev["date"], format="mixed").dt.strftime("%Y-%m-%d")
        # state에 없는 월의 행은 신뢰할 수 없다(중간에 끊긴 월) — 버리고 다시 받는다
        keep = prev["date"].str.slice(0, 7).isin(done)
        dropped = int((~keep).sum())
        acc = prev[keep].to_dict("records")
        print(f"[재개] {src.name}에서 완료월 {len(done)}개 / {len(acc):,}건"
              + (f" (미완료월 {dropped:,}건 폐기)" if dropped else ""), flush=True)

    todo = [m for m in all_months if str(m) not in done]
    if not todo:
        # 예약 실행으로 매일 도는 경우가 있다. 이미 완주했으면 조용히 끝낸다
        # (PARTIAL은 완주 시 지워지므로 acc가 비어 있는 게 정상이다).
        print(f"받을 월이 없다 — {len(done)}개월 전부 완료됨")
        return pd.DataFrame(acc)

    groups = _chunks(todo, chunk)
    est = len(groups) * len(MARKETS)
    print(f"남은 {len(todo)}개월 -> {len(groups)}개 구간 x {len(MARKETS)}시장 "
          f"= 기본요청 {est:,}회 (+페이징)", flush=True)

    today = dt.date.today()
    t0 = time.time()
    quota_hit = False
    for gi, grp in enumerate(groups, 1):
        s = grp[0].start_time.date()
        e = min(grp[-1].end_time.date(), today)
        grp_rows: list[dict] = []
        ok_all = True
        try:
            for mkt_cd in MARKETS.values():
                rows, ok = fetch_market_range(mkt_cd, s, e, scope)
                grp_rows.extend(rows)
                ok_all &= ok
                time.sleep(REQUEST_DELAY_SEC)
        except QuotaExhausted as ex:
            print(f"\n[중단] 일일 요청 한도 초과 ({ex}).", flush=True)
            quota_hit = True
            ok_all = False

        if ok_all:
            acc.extend(grp_rows)
            done.update(str(m) for m in grp)
            state["done_months"] = sorted(done)
            state["scope"] = scope
            pd.DataFrame(acc).to_csv(PARTIAL_PATH, index=False, encoding="utf-8-sig")
            _save_state(state)
            _save_manifest()
            nd = len({r["date"] for r in grp_rows})
            print(f"[{gi}/{len(groups)}] {s}~{e} -> {len(grp_rows):,}건 / 거래일 {nd}일  "
                  f"(누적 {len(acc):,}, {(time.time()-t0)/60:.1f}분)", flush=True)
        else:
            # 부분 성공분은 버린다. 섞어 두면 "받은 것처럼" 보여서 영구 누락이 된다.
            # 원장도 같이 버려야 한다 — 안 그러면 저장 안 된 행을 수집한 것으로 기록한다.
            MANIFEST.clear()
            state["failed_months"] = sorted(set(state.get("failed_months", []))
                                            | {str(m) for m in grp})
            _save_state(state)
            print(f"[{gi}/{len(groups)}] {s}~{e} 실패 — 해당 구간 폐기, "
                  f"다음 실행에서 재수집", flush=True)
        if quota_hit:
            remain = sum(1 for m in todo if str(m) not in done)
            print(f"       남은 {remain}개월은 쿼터 회복 후(보통 자정 KST) "
                  f"같은 명령을 다시 실행하면 이어받는다.", flush=True)
            break

    return pd.DataFrame(acc)


def _wavg(d: pd.DataFrame, p: str, q: str) -> float:
    d = d[[p, q]].dropna()
    tq = d[q].sum()
    return (d[p] * d[q]).sum() / tq if tq else float("nan")


def aggregate(raw: pd.DataFrame) -> None:
    raw = raw.copy()
    raw["date"] = pd.to_datetime(raw["date"], format="mixed")

    jb = raw[raw["county"].notna()]
    county_rows = []
    for (d, c), g in jb.groupby(["date", "county"]):
        main = g[g["variety"].isin(MAIN_VARIETIES)]
        jj = g[g["variety"].isin(JJONG_VARIETIES)]
        th = g[g["variety"].isin(THIN_VARIETIES)]
        tot_q = g["qty_kg"].sum(min_count=1)
        county_rows.append({
            "date": d.date(), "county": c,
            # ── 모델 타깃: 주력 품종만 ──
            "price_kg": _wavg(main, "price_kg", "qty_kg"),
            "qty_kg": main["qty_kg"].sum(min_count=1),
            "n_obs": len(main), "n_markets": main["market_cd"].nunique(),
            # ── 쫑상추 독립 계열 (작기 종료 · 대체수요 지표) ──
            "price_kg_jjong": _wavg(jj, "price_kg", "qty_kg"),
            "qty_kg_jjong": jj["qty_kg"].sum(min_count=1),
            "n_obs_jjong": len(jj),
            # ── 솎음 (작기 초반 지표) ──
            "qty_kg_thin": th["qty_kg"].sum(min_count=1),
            # ── 전 품종 혼합 (구 정의. 하위호환·대조용, 타깃으로 쓰지 말 것) ──
            "price_kg_all": _wavg(g, "price_kg", "qty_kg"),
            "qty_kg_all": tot_q,
        })
    cdf = pd.DataFrame(county_rows).sort_values(["date", "county"])
    cdf["jjong_share"] = cdf["qty_kg_jjong"].fillna(0) / cdf["qty_kg_all"] * 100
    # 상대가격: 주력 대비 쫑상추. 주력이 귀할수록 대체수요로 올라간다는 가설의 지표
    cdf["jjong_rel_price"] = cdf["price_kg_jjong"] / cdf["price_kg"]
    cdf.to_csv(COUNTY_PATH, index=False, encoding="utf-8-sig")
    print(f"저장: {COUNTY_PATH.name} ({len(cdf):,}행) "
          f"— 타깃=주력 {len(MAIN_VARIETIES)}종, 쫑상추 별도 계열")

    sido_rows = []
    for (d, s), g in raw[raw["sido"].notna()].groupby(["date", "sido"]):
        sido_rows.append({
            "date": d.date(), "sido": s,
            "price_kg": _wavg(g, "price_kg", "qty_kg"),
            "qty_kg": g["qty_kg"].sum(min_count=1), "n_obs": len(g),
        })
    pd.DataFrame(sido_rows).sort_values(["date", "sido"]).to_csv(
        SIDO_PATH, index=False, encoding="utf-8-sig")
    print(f"저장: {SIDO_PATH.name} ({len(sido_rows):,}행)")

    _report_integrity(raw)


def _report_integrity(raw: pd.DataFrame) -> None:
    """수집 자체의 건전성 점검. 여기서 이상이 나오면 집계를 믿으면 안 된다."""
    print("\n[무결성]")
    d = raw.copy()
    d["_ym"] = pd.to_datetime(d["date"], format="mixed").dt.to_period("M")

    days = d.groupby("_ym")["date"].nunique()
    thin = days[days < 15]
    print(f"  월별 거래일수: 중앙값 {days.median():.0f}일, 최소 {days.min()}일")
    if len(thin):
        print(f"  [경고] 거래일 15일 미만인 월 {len(thin)}개: "
              f"{list(thin.index.astype(str))[:8]}")

    mkts = d.groupby("_ym")["market_cd"].nunique()
    short = mkts[mkts < len(MARKETS)]
    if len(short):
        print(f"  [경고] 시장 {len(MARKETS)}곳이 다 안 찬 월 {len(short)}개: "
              f"{dict(list(short.astype(int).items())[:6])}")
    else:
        print(f"  전 월 시장 {len(MARKETS)}곳 완비")

    # 완전 동일 행. 같은 날 같은 조건 거래는 실재하므로 무조건 제거하면 안 된다.
    exact = int(d.drop(columns=["_ym"]).duplicated().sum())
    print(f"  완전 동일 행 {exact:,}건 ({exact/len(d)*100:.2f}%) — 제거 금지")

    if COUNT_MISMATCH:
        print(f"  [경고] totalCount 초과 수집 {len(COUNT_MISMATCH)}건: {COUNT_MISMATCH[:5]}")
    else:
        print("  totalCount 대비 초과 수집 없음")

    kgna = d["price_kg"].isna().mean() * 100
    print(f"  kg 환산 불가 비율 {kgna:.2f}% (unit_nm!='kg' 또는 unit_qty>{MAX_UNIT_QTY_KG:.0f})")


def verify() -> None:
    """범위조회가 일별조회와 같은 결과를 주는지 재확인(표본). 깊은 페이징도 같이 본다."""
    print("범위조회 vs 일별조회 대조")
    for mkt, s, e in [("110001", "2025-06-01", "2025-08-31"),
                      ("350101", "2022-01-01", "2022-03-31"),
                      ("240001", "2019-10-01", "2019-12-31")]:
        sd, ed = dt.date.fromisoformat(s), dt.date.fromisoformat(e)
        rows, ok = fetch_market_range(mkt, sd, ed, "national")
        got = pd.Series([r["date"] for r in rows]).value_counts()
        npage = -(-len(rows) // PAGE_ROWS)
        bad = 0
        # 첫 페이지·마지막 페이지에 걸리는 날짜를 섞어 뽑아 깊은 페이징까지 확인
        days = sorted(got.index)
        for day in days[:3] + days[-3:]:
            b = _get({"serviceKey": KEY, "returnType": "JSON",
                      "cond[whsl_mrkt_cd::EQ]": mkt, "cond[trd_clcln_ymd::EQ]": day,
                      "cond[gds_mclsf_nm::EQ]": "상추", "numOfRows": 1, "pageNo": 1})
            n = int((b or {}).get("totalCount") or 0)
            # 일별 totalCount는 price/qty<=0 필터 전 값이라 범위조회 수집분 이상이어야 한다
            if n < got[day]:
                bad += 1
                print(f"    불일치 {mkt} {day}: 일별 {n} < 범위 {got[day]}")
        print(f"  {mkt} {s[:7]}~{e[:7]}: {len(rows):,}건 / {npage}페이지 / "
              f"거래일 {len(got)}일 / 대조 6일 중 불일치 {bad}건")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", choices=["national", "jeonbuk"], default="national")
    ap.add_argument("--start", default=START)
    ap.add_argument("--end", default=None)
    ap.add_argument("--chunk", type=int, default=CHUNK_MONTHS,
                    help="한 번에 조회할 개월 수 (1~3 권장, 6 이상 금지)")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--reaggregate", action="store_true")
    ap.add_argument("--check-complete", action="store_true",
                    help="수집 없이 완주 여부만 판정. 완주=exit 0, 미완료=exit 1 "
                         "(예약 배치가 감사 실행 여부를 정할 때 쓴다)")
    a = ap.parse_args()

    if a.check_complete:
        st = _load_state()
        exp = list(pd.period_range(start=a.start,
                                   end=(a.end or dt.date.today().isoformat()), freq="M"))
        missing = [str(m) for m in exp if str(m) not in set(st.get("done_months", []))]
        if missing:
            print(f"미완료 {len(missing)}/{len(exp)}개월: "
                  f"{missing[:6]}{' ...' if len(missing) > 6 else ''}")
            sys.exit(1)
        print(f"완주 ({len(exp)}개월)")
        return

    if not KEY:
        sys.exit("DATA_GO_KR_KEY 없음 — .env 확인")
    if a.chunk > 5:
        sys.exit("--chunk 6 이상은 서버가 504로 끊는다(실측). 3 이하로 쓸 것.")

    if a.verify:
        verify()
        return

    if a.reaggregate:
        src = RAW_PATH if RAW_PATH.exists() else PARTIAL_PATH
        print(f"재집계: {src.name}")
        aggregate(pd.read_csv(src, dtype={"market_cd": str, "plor_cd": str},
                              low_memory=False))
        return

    print(f"상추 일별 수집 | scope={a.scope} | {a.start}~{a.end or '오늘'} | "
          f"시장 {len(MARKETS)}곳 | chunk={a.chunk}개월")
    raw = scrape(a.start, a.end, a.scope, a.chunk)

    state = _load_state()
    if raw.empty:
        # 완주 후 재실행(예약 작업)이면 done_months가 꽉 차 있고 PARTIAL은 없다.
        # 이건 오류가 아니므로 0으로 끝내야 예약 체인이 실패로 잡히지 않는다.
        expected_n = len(pd.period_range(
            start=a.start, end=(a.end or dt.date.today().isoformat()), freq="M"))
        if len(state.get("done_months", [])) >= expected_n:
            print("이미 완주 상태 — 할 일 없음")
            return
        sys.exit("수집 결과 없음")

    expected = pd.period_range(start=a.start,
                               end=(a.end or dt.date.today().isoformat()), freq="M")
    missing = [str(m) for m in expected if str(m) not in set(state.get("done_months", []))]
    if missing:
        print(f"\n미완료 {len(missing)}개월 남음 — 같은 명령 재실행 시 이어받는다: "
              f"{missing[:6]}{' ...' if len(missing) > 6 else ''}")
        aggregate(raw)
        print("\n(중간 집계다. 전 구간 완료 후 다시 볼 것.)")
        return

    raw.to_csv(RAW_PATH, index=False, encoding="utf-8-sig")
    print(f"\n저장: {RAW_PATH.name} ({len(raw):,}행)")
    aggregate(raw)
    # --end로 구간을 좁혀 돌린 경우엔 그 범위만 '완주'일 뿐이므로 체크포인트를 남긴다.
    # (RAW 폴백이 있어 지워도 데이터는 안 잃지만, 진행 상태를 오해하기 쉽다.)
    if a.end:
        print("(--end 지정 실행이라 체크포인트를 남긴다)")
    else:
        PARTIAL_PATH.unlink(missing_ok=True)
        print("체크포인트 삭제(완주)")


if __name__ == "__main__":
    main()
