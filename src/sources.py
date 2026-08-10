# -*- coding: utf-8 -*-
"""
sources.py — OpenAPI 실 페처 레이어 (v2: 엔드포인트 확정)

기존 farm_engine/sources.py의 `_*_real()` 슬롯 실 구현 + 예측용 신규 소스.
v1의 TODO 자리표시자를 각 포털 명세에서 확인한 실제 요청주소로 교체했다.

응답 형식 주의
--------------
- JSON: KMA ASOS(1360000), ECOS, KOSIS, odcloud(소득)
- XML : 농진청 1390802 계열(흙토람 토양적성·생장도일), 관세청 1220000
  → `_get_xml()`로 처리.

상태(확정도)
------------
  [CONFIRMED] 요청주소 확인. 키만 있으면 동작 기대(파라미터명 일부는 명세 최종대조 권장).
  [VERIFY]    아직 확정 못한 값이 남음(주로 코드/식별자).

미해결로 남은 값
----------------
  1) 소득조사(3060748): odcloud **uddi** 1개 — 승인된 활용신청 페이지의 데이터명세에서 복사.
  2) KOSIS tblId/itmId: 작목군별로 상이 → crop_crosswalk.kosis_item 에 표ID 기입.
  3) 생장도일: 농진청 **관측지점코드**(KMA ASOS 번호와 다름) → region_crosswalk 에 rda_spot 열 추가.
  4) 흙토람·생장도일·관세 일부 파라미터명은 명세 최종 대조.

환경변수
--------
  KAMIS_CERT_KEY, KAMIS_CERT_ID / DATA_GO_KR_KEY / KOSIS_KEY / BOK_ECOS_KEY
"""

from __future__ import annotations

import os
import time
import datetime as dt
import urllib.parse
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

try:
    import requests
except ImportError:
    requests = None

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass


# ─────────────────────────────────────────────────────────────
# 0. 설정
# ─────────────────────────────────────────────────────────────

def _decoded_key(raw: str) -> str:
    """data.go.kr은 Encoding/Decoding 두 버전 키를 다 준다. requests의 params=는
    자체적으로 퍼센트 인코딩을 하므로, 이미 인코딩된 키를 넣으면 이중 인코딩되어
    SERVICE_KEY_IS_NOT_REGISTERED_ERROR가 난다. 항상 디코딩된 형태로 보관해 방지한다."""
    return urllib.parse.unquote(raw) if raw else raw


KEYS = {
    "kamis_key": os.getenv("KAMIS_CERT_KEY", ""),
    "kamis_id":  os.getenv("KAMIS_CERT_ID", ""),
    "data_go":   _decoded_key(os.getenv("DATA_GO_KR_KEY", "")),
    "kosis":     os.getenv("KOSIS_KEY", ""),
    "ecos":      os.getenv("BOK_ECOS_KEY", ""),
}

BASE = {
    # ── JSON ──
    "kamis":  "https://www.kamis.or.kr/service/price/xml.do",
    "asos":   "https://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList",
    "ecos":   "https://ecos.bok.or.kr/api/StatisticSearch",
    "kosis":  "https://kosis.kr/openapi/Param/statisticsParameterData.do",
    "income": "https://api.odcloud.kr/api",   # 소득조사 3060748 (뒤에 /v1/uddi:{UUID})
    # ── XML ──
    "soil":   "https://apis.data.go.kr/1390802/SoilEnviron/SoilFitStat/V2/getSoilCropFitInfo",
    "gdd":    "https://apis.data.go.kr/1390802/AgriWeather/WeatherObsrInfo/GrwDay/getWeatherDegreeDaySpotList",
    "customs":"https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList",
}

# [VERIFY] 소득조사 odcloud uddi — 승인 페이지 데이터명세에서 복사 후 기입.
INCOME_UDDI = os.getenv("INCOME_UDDI", "")   # 예: "uddi:xxxxxxxx-xxxx-..."

_XWALK_DIR = Path(os.getenv(
    "XWALK_DIR", Path(__file__).resolve().parent.parent / "data" / "crosswalk"
))


# ─────────────────────────────────────────────────────────────
# 1. 크로스워크 로더 (1번 산출물 연동)
# ─────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def crop_xwalk() -> pd.DataFrame:
    df = pd.read_csv(_XWALK_DIR / "crop_crosswalk.csv", dtype=str, encoding="utf-8-sig").fillna("")
    return df.set_index("crop_id")


@lru_cache(maxsize=1)
def region_xwalk() -> pd.DataFrame:
    df = pd.read_csv(_XWALK_DIR / "region_crosswalk.csv", dtype=str, encoding="utf-8-sig").fillna("")
    return df.set_index("region_id")


def _code(df: pd.DataFrame, key: str, col: str) -> str:
    """크로스워크 코드 조회. 없는 열/행/TODO → '' (→ 폴백)."""
    if key not in df.index or col not in df.columns:
        return ""
    v = str(df.loc[key, col]).strip()
    return "" if v in ("", "TODO", "nan") else v


def _missing(*codes: str) -> bool:
    return any(c == "" for c in codes)


# ─────────────────────────────────────────────────────────────
# 2. HTTP 헬퍼 (JSON / XML)
# ─────────────────────────────────────────────────────────────

def _request(url: str, params: dict, timeout: int = 60, retries: int = 1):
    if requests is None:
        return None
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception:
            if attempt < retries:
                time.sleep(0.6 * (attempt + 1))
            else:
                return None


def _get_json(url: str, params: dict) -> Optional[dict]:
    r = _request(url, params)
    if r is None:
        return None
    try:
        return r.json()
    except Exception:
        return None


def _get_xml_items(url: str, params: dict) -> Optional[list]:
    """apis.data.go.kr XML 응답 → item 레코드 list[dict]. (envelope: .../body/items/item)"""
    r = _request(url, params)
    if r is None:
        return None
    try:
        root = ET.fromstring(r.content)
    except Exception:
        return None
    items = [{c.tag: (c.text or "").strip() for c in it} for it in root.iter("item")]
    return items or None


def _to_num(x) -> float:
    try:
        return float(str(x).replace(",", "").strip())
    except (ValueError, TypeError):
        return np.nan


def _has(*ks: str) -> bool:
    return all(KEYS.get(k) for k in ks)


# ─────────────────────────────────────────────────────────────
# 3. KAMIS 도매/공판장 가격 → 시장성·위험·예측 타깃          [CONFIRMED]
# ─────────────────────────────────────────────────────────────

def _kamis_real(crop_id: str, start: str, end: str) -> Optional[pd.DataFrame]:
    """반환: [date, crop_id, price] (일별 도매). start/end='YYYY-MM-DD'."""
    cx = crop_xwalk()
    item = _code(cx, crop_id, "kamis_item")
    kind = _code(cx, crop_id, "kamis_kind")
    if _missing(item) or not _has("kamis_key", "kamis_id"):
        return None
    params = {
        "action": "periodProductList",
        "p_productclscode": "01",
        "p_itemcategorycode": item[0] + "00",
        "p_itemcode": item, "p_kindcode": kind or "",
        "p_productrankcode": "",
        "p_startday": start, "p_endday": end,
        "p_convert_kg_yn": "Y",
        "p_cert_key": KEYS["kamis_key"], "p_cert_id": KEYS["kamis_id"],
        "p_returntype": "json",
    }
    js = _get_json(BASE["kamis"], params)
    data = (js or {}).get("data", {})
    items = data.get("item") if isinstance(data, dict) else None
    if not items:
        return None
    if isinstance(items, dict):
        items = [items]
    rows = []
    for it in items:
        yyyy, regday = str(it.get("yyyy", "")), str(it.get("regday", ""))
        price = _to_num(it.get("price"))
        if not yyyy or "/" not in regday or np.isnan(price):
            continue
        mm, dd = regday.split("/")
        try:
            d = dt.date(int(yyyy), int(mm), int(dd))
        except ValueError:
            continue
        rows.append({"date": d, "crop_id": crop_id, "price": price})
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True) if rows else None


# ─────────────────────────────────────────────────────────────
# 4. 소득조사(농축산물소득정보 3060748) → 수익성·초기투자
#    odcloud uddi 발급이 막혀 있고 API 데이터도 2014년까지만 있어 API 경로는 폐기.
#    농사로/KOSIS에서 받은 정적 CSV(data/raw/income.csv)를 우선 사용한다.        [CSV 우선]
# ─────────────────────────────────────────────────────────────

_INCOME_CSV_PATH = Path(os.getenv("INCOME_CSV_PATH", _XWALK_DIR.parent / "raw" / "income.csv"))


def _income_csv(crop_id: str, year: Optional[int] = None) -> Optional[pd.DataFrame]:
    """반환: [crop_id, year, gross, cost, net]. data/raw/income.csv가 있을 때만 동작.

    기대하는 CSV 컬럼: crop_id, year, gross, cost, net (10a당, 만원).
    없으면 None → 폴백. 이 함수는 가격 예측 파이프라인에는 연결돼 있지 않은
    선택적 수익성 참고 데이터라, 없어도 build_dataset.py/backtest.py는 그대로 동작한다.
    """
    if not _INCOME_CSV_PATH.exists():
        return None
    df = pd.read_csv(_INCOME_CSV_PATH, dtype=str, encoding="utf-8-sig")
    df.columns = [c.strip() for c in df.columns]
    if "crop_id" not in df.columns:
        return None
    df = df[df["crop_id"] == crop_id].copy()
    if df.empty:
        return None
    for col in ("year", "gross", "cost", "net"):
        if col in df.columns:
            df[col] = df[col].apply(_to_num)
    if year is not None and "year" in df.columns:
        df = df[df["year"] == year]
    return df.reset_index(drop=True) if not df.empty else None


def _income_real(crop_id: str, year: Optional[int] = None) -> Optional[pd.DataFrame]:
    """
    반환: [crop_id, year, gross, cost, net] (10a당, 만원). odcloud JSON.
    남은 것: INCOME_UDDI (승인 활용신청 페이지 데이터명세에서 복사).
    """
    cx = crop_xwalk()
    icode = _code(cx, crop_id, "income_code")
    if _missing(icode) or not INCOME_UDDI or not _has("data_go"):
        return None
    url = f"{BASE['income']}/3060748/v1/{INCOME_UDDI}"
    params = {"serviceKey": KEYS["data_go"], "page": 1, "perPage": 200, "returnType": "JSON"}
    # 파라미터명은 명세 최종대조: cond[작목코드::EQ]=icode, cond[조사연도::EQ]=year
    js = _get_json(url, params)
    recs = (js or {}).get("data") or []
    rows = []
    for r in recs:
        if str(r.get("작목코드", r.get("작목명", ""))).strip() not in (icode,):
            # 서버 필터 미적용 시 클라이언트 필터. 필드명 명세 대조.
            pass
        rows.append({
            "crop_id": crop_id,
            "year": _to_num(r.get("조사연도") or r.get("year")),
            "gross": _to_num(r.get("총수입")),
            "cost":  _to_num(r.get("경영비")),
            "net":   _to_num(r.get("소득")),
        })
    return pd.DataFrame(rows) if rows else None


# ─────────────────────────────────────────────────────────────
# 5. 흙토람 작물별 토양적성(V2) → 토양 적합                   [CONFIRMED, 실측 데이터 확인]
#    요청주소 SoilFitStat/V2/getSoilCropFitInfo · 법정동코드(10) + 작물코드 · XML
#    data.go.kr 15144182(V2). 이전 URL엔 "/V2/" 세그먼트가 빠져 있었고(NO_OPENAPI_SERVICE_ERROR),
#    파라미터명도 추측(BJD_Code/Crop_Code)이 전부 틀렸었다 — 실제로는 대소문자가 특이한
#    STDG_CD / soil_Crop_CD (첨부 hwp 기술명세서에서 실측 확인). 응답은 등급별 롱포맷이
#    아니라 한 행에 5개 등급 면적이 다 들어있는 와이드포맷이라 컬럼 구조를 다시 짬.
# ─────────────────────────────────────────────────────────────

def _suit_real(region_id: str, crop_id: str) -> Optional[pd.DataFrame]:
    """반환: [region_id, crop_id, bjd_nm, high_suit_area, suit_area, poss_area,
    low_suit_area, etc_area] (전부 ha). 점수화는 호출부에서."""
    rx, cx = region_xwalk(), crop_xwalk()
    ldong = _code(rx, region_id, "ldong_code")
    scode = _code(cx, crop_id, "soil_code")
    if _missing(ldong, scode) or not _has("data_go"):
        return None
    params = {
        "serviceKey": KEYS["data_go"],
        "STDG_CD": ldong, "soil_Crop_CD": scode,
    }
    items = _get_xml_items(BASE["soil"], params)
    if not items:
        return None
    rows = [{
        "region_id": region_id, "crop_id": crop_id,
        "bjd_nm": it.get("bjd_Nm"),
        "high_suit_area": _to_num(it.get("high_Suit_Area")),
        "suit_area":       _to_num(it.get("suit_Area")),
        "poss_area":       _to_num(it.get("poss_Area")),
        "low_suit_area":   _to_num(it.get("low_Suit_Area")),
        "etc_area":        _to_num(it.get("etc_Area")),
    } for it in items]
    return pd.DataFrame(rows) if rows else None


# ─────────────────────────────────────────────────────────────
# 6. KOSIS 농작물생산조사 재배면적 → 경합                     [CONFIRMED, 실측 데이터 확인]
#    orgId=101 · tblId 작목군별(crosswalk.kosis_item) · itmId 작목별(crosswalk.kosis_itm_id)
#    · objL1=지역(crosswalk.kosis_region_code) · JSON
#    예시 표ID: 시설 DT_1ET0017 / 과수 재배면적 DT_1AG20411 / 엽채류 DT_1ET0028(상추 itmId=T66)
#    상추(DT_1ET0028)는 시군 단위가 아니라 시도 단위(objL1=35=전라북도)로만 제공됨 —
#    region_crosswalk.csv의 8개 시군이 전부 같은 도 단위 값을 공유하므로 build_dataset.py의
#    build_area_yearly()는 지역별 sum이 아닌 mean으로 집계해야 8중복(x8)을 피할 수 있다.
# ─────────────────────────────────────────────────────────────

def _area_real(region_id: str, crop_id: str,
               start_year: str = "2015", end_year: str = "2024") -> Optional[pd.DataFrame]:
    """반환: [region_id, crop_id, year, area(ha)]. tblId/itmId는 crosswalk.kosis_item/kosis_itm_id."""
    rx, cx = region_xwalk(), crop_xwalk()
    tbl = _code(cx, crop_id, "kosis_item")               # 표ID(작목군별)
    itm = _code(cx, crop_id, "kosis_itm_id")             # 항목ID(작목별, 예: 상추:면적=T66)
    obj = _code(rx, region_id, "kosis_region_code")      # 지역 분류값
    if _missing(tbl, itm, obj) or not _has("kosis"):
        return None
    params = {
        "method": "getList", "apiKey": KEYS["kosis"], "format": "json", "jsonVD": "Y",
        "orgId": "101", "tblId": tbl,
        "itmId": itm, "objL1": obj,
        "prdSe": "Y", "startPrdDe": start_year, "endPrdDe": end_year,
    }
    js = _get_json(BASE["kosis"], params)
    if not isinstance(js, list):
        return None
    rows = [{
        "region_id": region_id, "crop_id": crop_id,
        "year": _to_num(r.get("PRD_DE")), "area": _to_num(r.get("DT")),
    } for r in js if isinstance(r, dict)]
    return pd.DataFrame(rows) if rows else None


# ─────────────────────────────────────────────────────────────
# 7. 기상 KMA ASOS 일자료 → 기후 적합·작황 피처              [CONFIRMED]
# ─────────────────────────────────────────────────────────────

def _weather_one_chunk(stn: str, region_id: str, start: str, end: str) -> list:
    """start/end='YYYYMMDD', 최대 1년 이내 구간 하나를 조회 (numOfRows=999 한도 안쪽)."""
    params = {
        "serviceKey": KEYS["data_go"], "dataType": "JSON",
        "dataCd": "ASOS", "dateCd": "DAY",
        "startDt": start, "endDt": end, "stnIds": stn,
        "numOfRows": 999, "pageNo": 1,
    }
    js = _get_json(BASE["asos"], params)
    try:
        items = js["response"]["body"]["items"]["item"]
    except (TypeError, KeyError):
        return []
    if isinstance(items, dict):
        items = [items]
    return [{
        "region_id": region_id,
        "date": pd.to_datetime(it.get("tm"), errors="coerce"),
        "tavg": _to_num(it.get("avgTa")), "rain": _to_num(it.get("sumRn")),
        "sun":  _to_num(it.get("ssDur")),
    } for it in items]


def _weather_real(region_id: str, start: str, end: str) -> Optional[pd.DataFrame]:
    """반환: [region_id, date, tavg, rain, sun]. start/end='YYYYMMDD'.

    ASOS 일자료는 numOfRows 한도(1페이지 999행)가 있어 여러 해를 한 번에 요청하면
    앞부분만 잘려 온다. 연도별로 쪼개 호출한 뒤 이어붙인다.
    """
    rx = region_xwalk()
    stn = _code(rx, region_id, "asos_station")
    if _missing(stn) or not _has("data_go"):
        return None

    start_d = dt.datetime.strptime(start, "%Y%m%d").date()
    end_d = dt.datetime.strptime(end, "%Y%m%d").date()
    yesterday = dt.date.today() - dt.timedelta(days=1)
    end_d = min(end_d, yesterday)  # ASOS는 "전날 자료까지"만 제공(resultCode 99로 거부됨)
    if start_d > end_d:
        return None

    rows = []
    cur = start_d
    while cur <= end_d:
        chunk_end = min(dt.date(cur.year, 12, 31), end_d)
        rows.extend(_weather_one_chunk(
            stn, region_id, cur.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d")
        ))
        cur = dt.date(cur.year + 1, 1, 1)

    df = pd.DataFrame(rows).dropna(subset=["date"]) if rows else pd.DataFrame()
    return df if not df.empty else None


# ─────────────────────────────────────────────────────────────
# 8. 농진청 생장도일 → 생리 피처(적산온도)                    [CONFIRMED endpoint]
#    getWeatherDegreeDaySpotList · XML · 농진청 관측지점코드 사용
#    → region_crosswalk 에 rda_spot 열 추가 필요(KMA ASOS 번호와 다름).
# ─────────────────────────────────────────────────────────────

def _gdd_real(region_id: str, year: Optional[int] = None) -> Optional[pd.DataFrame]:
    """반환: [region_id, year, gdd]. 관측지점코드는 crosswalk.rda_spot."""
    rx = region_xwalk()
    spot = _code(rx, region_id, "rda_spot")   # ← region_crosswalk 에 열 추가
    if _missing(spot) or not _has("data_go"):
        return None
    params = {
        "serviceKey": KEYS["data_go"], "Page_No": 1, "Page_Size": 100,
        # 파라미터명 명세 대조: 관측지점코드/관측기관
        "obsr_Spot_Code": spot,
    }
    items = _get_xml_items(BASE["gdd"], params)
    if not items:
        return None
    rows = [{
        "region_id": region_id,
        "year": _to_num(it.get("year") or it.get("Year")),
        "gdd":  _to_num(it.get("grw_Degree_Day") or it.get("생장도일") or it.get("gdd")),
    } for it in items]
    return pd.DataFrame(rows) if rows else None


# ─────────────────────────────────────────────────────────────
# 9. 한국은행 ECOS → 거시(환율·유가·소비심리)               [CONFIRMED]
# ─────────────────────────────────────────────────────────────

ECOS_SERIES = {
    "fx_usd": {"stat": "731Y001", "item": "0000001", "cycle": "D"},   # 원/달러(명세 대조)
    "csi":    {"stat": "511Y002", "item": "FME",     "cycle": "M"},   # 소비자심리(명세 대조)
    # "oil_dubai": {...},  # 두바이유가 계열 추가
}

_ECOS_PAGE = 1000


def _macro_real(series: str, start: str, end: str) -> Optional[pd.DataFrame]:
    """반환: [date, series, value]. start/end: cycle에 맞춰 YYYYMMDD/YYYYMM/YYYY.

    ECOS는 한 요청당 최대 1000행(start_no~end_no)만 주므로, 일별(D) 시계열처럼
    11년치가 1000행을 넘는 경우 list_total_count를 보고 페이지를 이어서 요청한다.
    """
    spec = ECOS_SERIES.get(series)
    if not spec or not _has("ecos"):
        return None

    recs = []
    page_start = 1
    total = None
    while total is None or page_start <= total:
        page_end = page_start + _ECOS_PAGE - 1
        url = "/".join([BASE["ecos"], KEYS["ecos"], "json", "kr", str(page_start), str(page_end),
                        spec["stat"], spec["cycle"], start, end, spec["item"]])
        js = _get_json(url, params={})
        try:
            block = js["StatisticSearch"]
            page_recs = block["row"]
            total = int(block.get("list_total_count", len(page_recs)))
        except (TypeError, KeyError):
            break
        recs.extend(page_recs)
        if len(page_recs) < _ECOS_PAGE:
            break
        page_start += _ECOS_PAGE

    rows = [{"date": r.get("TIME"), "series": series, "value": _to_num(r.get("DATA_VALUE"))}
            for r in recs]
    return pd.DataFrame(rows) if rows else None


# ─────────────────────────────────────────────────────────────
# 10. 관세청 품목별 수출입 → 수입량/수입액(수요 side)         [CONFIRMED]
#     nitemtrade/getNitemtradeList · hsSgn/strtYymm/endYymm · XML
# ─────────────────────────────────────────────────────────────

def _import_real(crop_id: str, start: str, end: str) -> Optional[pd.DataFrame]:
    """반환: [crop_id, ym, import_qty, import_val]. start/end='YYYYMM'. hs=crosswalk.hs_code."""
    cx = crop_xwalk()
    hs = _code(cx, crop_id, "hs_code")
    if _missing(hs) or not _has("data_go"):
        return None
    params = {"serviceKey": KEYS["data_go"], "strtYymm": start, "endYymm": end, "hsSgn": hs}
    items = _get_xml_items(BASE["customs"], params)
    if not items:
        return None
    rows = [{
        "crop_id": crop_id, "ym": it.get("year") or it.get("ym"),
        "import_qty": _to_num(it.get("impWgt")), "import_val": _to_num(it.get("impDlr")),
    } for it in items]
    return pd.DataFrame(rows) if rows else None


# ─────────────────────────────────────────────────────────────
# 11. 합성 폴백 (오프라인/미확정 시)
# ─────────────────────────────────────────────────────────────

def _synth_price(crop_id: str, start: str, end: str) -> pd.DataFrame:
    rng = np.random.default_rng(hash((crop_id, "p")) % (2**32))
    days = pd.date_range(start, end, freq="D")
    base = 1000 + rng.integers(0, 3000)
    seasonal = 200 * np.sin(2 * np.pi * days.dayofyear / 365.25)
    noise = rng.normal(0, 60, len(days)).cumsum() * 0.1
    price = np.clip(base + seasonal + noise, 100, None)
    return pd.DataFrame({"date": days.date, "crop_id": crop_id, "price": price.round(0)})


# ─────────────────────────────────────────────────────────────
# 12. 공개 로더
# ─────────────────────────────────────────────────────────────

def load_prices(crop_id: str, start: str, end: str) -> pd.DataFrame:
    df = _kamis_real(crop_id, start, end)
    if df is not None and not df.empty:
        df.attrs["source"] = "kamis"; return df
    df = _synth_price(crop_id, start, end)
    df.attrs["source"] = "synthetic"; return df


def load_income(crop_id, **k):
    df = _income_csv(crop_id, **k)
    if df is not None and not df.empty:
        df.attrs["source"] = "csv"; return df
    return _income_real(crop_id, **k)  # uddi 있으면 폴백 시도, 없으면 None
def load_suit(region_id, crop_id):      return _suit_real(region_id, crop_id)
def load_area(region_id, crop_id, **k): return _area_real(region_id, crop_id, **k)
def load_weather(region_id, s, e):      return _weather_real(region_id, s, e)
def load_gdd(region_id, **k):           return _gdd_real(region_id, **k)
def load_macro(series, s, e):           return _macro_real(series, s, e)
def load_import(crop_id, s, e):         return _import_real(crop_id, s, e)


# ─────────────────────────────────────────────────────────────
# 13. 소스 레지스트리 (점검/문서용)
# ─────────────────────────────────────────────────────────────

REGISTRY = [
    # name,     fn,             keys,                      fmt,    status
    ("kamis",   "_kamis_real",  ("kamis_key", "kamis_id"), "json", "CONFIRMED"),
    ("income",  "_income_csv",  (),                        "csv",  "CSV(data/raw/income.csv)"),
    ("soil",    "_suit_real",   ("data_go",),              "xml",  "CONFIRMED"),
    ("area",    "_area_real",   ("kosis",),                "json", "CONFIRMED(tblId)"),
    ("weather", "_weather_real",("data_go",),              "json", "CONFIRMED"),
    ("gdd",     "_gdd_real",    ("data_go",),              "xml",  "CONFIRMED(rda_spot)"),
    ("macro",   "_macro_real",  ("ecos",),                 "json", "CONFIRMED"),
    ("import",  "_import_real", ("data_go",),              "xml",  "CONFIRMED"),
]


def status_report() -> pd.DataFrame:
    rows = [{
        "source": n, "fn": fn, "fmt": fmt, "status": st,
        "keys_ready": all(KEYS.get(k) for k in ks), "needs": ",".join(ks),
    } for n, fn, ks, fmt, st in REGISTRY]
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────
# 14. 오프라인 스모크 테스트
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("== 소스 상태 ==")
    print(status_report().to_string(index=False))
    print("\n== 크로스워크 ==")
    print("crops:", list(crop_xwalk().index))
    print("regions:", list(region_xwalk().index))
    print("\n== 가격 로더(합성 폴백) ==")
    d = load_prices("apple", "2024-01-01", "2024-03-31")
    print("source =", d.attrs.get("source"), "| rows =", len(d))
    print(d.head(3).to_string(index=False))
