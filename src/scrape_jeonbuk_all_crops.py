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

# [2026-08-11] unit_qty 상한. unit_qty는 '거래 단위 1개의 kg 중량'이어야 하는데
# 극소수 레코드가 포장 중량이 아닌 값을 담고 있다(오이 3001, 포도 805, 수박 813 등).
# 이게 치명적인 이유는 두 방향으로 동시에 틀리기 때문:
#   price_kg = price / unit_qty  -> 단가가 수백 분의 1로 찌그러지고
#   qty_kg   = qty  * unit_qty   -> 가중치가 수백 배로 부풀어서
# 물량가중평균에서 그 한 행이 그 달 전체를 납치한다. 실측: 오이x임실 2022-11이
# 정상 1,000~2,000원/kg 36건 + 불량 3건 때문에 월평균 4.85원/kg으로 붕괴했고,
# CV MAPE가 21.5% -> 158%로 터졌다(포도x전주 2021-01은 52원/kg).
# 분포상 kg 레코드의 99.9%가 30 이하이고, TOP10 작물에서 50 초과는 272,434건 중 18건뿐인데
# 그 18건이 kg 물량 총합의 35.9%를 차지했다. 50kg 넘는 '포장 단위'는 이 작물들에 없다.
# 초과분은 지어내지 않고 NaN으로 두어 집계에서 빠지게 한다(unit_nm != 'kg'과 같은 처리).
# 하한은 두지 않는다 — 0.2~0.5kg 소포장은 실제로 존재하고, 그 경우 높은 원/kg이 맞다.
MAX_UNIT_QTY_KG = 50.0


def _kg_fields(price: float, qty: float, unit_nm, unit_qty: float) -> tuple[float, float]:
    """(price_kg, qty_kg). 환산 불가·신뢰 불가면 (NaN, NaN) — 억지로 kg인 척하지 않는다."""
    nan = float("nan")
    if unit_nm != "kg" or not (unit_qty > 0) or unit_qty > MAX_UNIT_QTY_KG:
        return nan, nan
    return price / unit_qty, qty * unit_qty


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
            # 단위 정규화용 필드. avgprc는 '거래 단위(상자)당' 단가라, 같은 작물이라도
            # 3kg/12kg 상자가 섞이면 단가가 몇 배씩 널뛴다(수박·대파에서 실측 확인).
            # unit_nm은 표본 조사에서 100% 'kg'이었고 unit_qty가 상자 무게다.
            try:
                unit_qty = float(it.get("unit_qty") or 0)
            except (TypeError, ValueError):
                unit_qty = 0.0
            unit_nm = it.get("unit_nm")
            price_kg, qty_kg = _kg_fields(price, qty, unit_nm, unit_qty)
            rows.append({
                "date": date, "market_cd": market_cd, "county": county,
                "crop": it.get("gds_mclsf_nm"), "plor_nm": it.get("plor_nm"),
                "price": price, "qty": qty,
                "unit_nm": unit_nm, "unit_qty": unit_qty,
                "price_kg": price_kg, "qty_kg": qty_kg,
            })
        total = body.get("totalCount", 0)
        if page * 1000 >= total or not items:
            break
        page += 1
    return rows


def _wavg(d: pd.DataFrame, price_col: str = "price", qty_col: str = "qty") -> float:
    """물량가중 평균. kg 환산 컬럼에는 NaN이 섞일 수 있으므로 유효한 행만 쓴다."""
    d = d[[price_col, qty_col]].dropna()
    total_qty = d[qty_col].sum()
    return (d[price_col] * d[qty_col]).sum() / total_qty if total_qty else float("nan")


PARTIAL_PATH = OUT_DIR / "allcrops_rescrape_partial.csv"


def scrape_monthly(start: str = START, end: Optional[str] = None, verbose: bool = True):
    """월 단위 순회 수집. 중간에 죽어도 PARTIAL_PATH에서 이어받는다(완료 월 스킵).
    기존 출력 파일들은 전체 완주 후 main()에서만 덮어쓴다."""
    end_date = dt.date.fromisoformat(end) if end else dt.date.today()
    months = pd.period_range(start=start, end=end_date.isoformat(), freq="M")
    today = dt.date.today()
    raw_all: list[dict] = []
    done_months: set = set()
    if PARTIAL_PATH.exists():
        # [2026-08-11] date 포맷을 반드시 정규화할 것. 체크포인트를 read_csv로 읽으면
        # date가 Timestamp가 되는데 새로 받는 행은 datetime.date라, 그대로 섞어
        # to_csv하면 한 파일에 "2018-01-05 00:00:00"과 "2018-01-05"이 공존한다.
        # 그러면 *다음* 재개 때 read_csv(parse_dates=...)가 파싱을 포기하고 str로
        # 돌려줘 `.dt`에서 AttributeError로 죽는다(pandas 3.0.5에서 실측).
        # 죽는 것 자체는 데이터를 망치진 않지만, 여기서 체크포인트를 지우고
        # 처음부터 다시 돌리면 몇 시간을 버리게 된다.
        prev = pd.read_csv(PARTIAL_PATH)
        prev["date"] = pd.to_datetime(prev["date"], format="mixed")
        # 마지막 월은 도중에 끊겼을 수 있으니 버리고 다시 받는다
        prev_ym = prev["date"].dt.to_period("M")
        last = prev_ym.max()
        prev = prev[prev_ym < last].copy()
        prev["date"] = prev["date"].dt.date  # 새로 받는 행과 같은 타입으로 맞춘다
        raw_all = prev.to_dict("records")
        done_months = set(prev_ym[prev_ym < last].astype(str))
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
    return aggregate_raw(raw_df), raw_df


def recompute_kg_fields(raw_df: pd.DataFrame) -> pd.DataFrame:
    """원시 레코드의 price_kg/qty_kg를 현재 규칙(_kg_fields)으로 다시 계산한다.

    규칙이 바뀌어도 6시간짜리 재스크래핑 없이 반영하려고 둔 것 — 원시 파일에
    price/qty/unit_nm/unit_qty가 그대로 남아 있어서 언제든 재계산할 수 있다."""
    d = raw_df.copy()
    ok = (d["unit_nm"] == "kg") & (d["unit_qty"] > 0) & (d["unit_qty"] <= MAX_UNIT_QTY_KG)
    d["price_kg"] = (d["price"] / d["unit_qty"]).where(ok)
    d["qty_kg"] = (d["qty"] * d["unit_qty"]).where(ok)
    return d


def aggregate_raw(raw_df: pd.DataFrame) -> pd.DataFrame:
    """원시 레코드 -> 작물x시군x월 집계. backfill_failed_days.py도 이 함수를 쓴다
    (집계 규칙이 두 군데로 갈라지면 조용히 어긋난다).
    kg 필드는 저장된 값을 믿지 않고 항상 현재 규칙으로 다시 계산한다."""
    if raw_df.empty:
        return pd.DataFrame()
    rows: list[dict] = []
    raw_df = recompute_kg_fields(raw_df)
    raw_df["date"] = pd.to_datetime(raw_df["date"], format="mixed")
    raw_df["_ym"] = raw_df["date"].dt.to_period("M")
    top10 = raw_df[raw_df["crop"].isin(TOP10_CROPS)]
    for (ym2, crop, county), grp in top10.groupby(["_ym", "crop", "county"]):
        rows.append({
            "ym": ym2, "crop": crop, "crop_id": CROP_NAME_TO_ID.get(crop, crop),
            "county": county,
            # price_avg_kg가 앞으로의 기준. price_avg(상자당)는 과거 비교용으로만 남긴다.
            "price_avg_kg": _wavg(grp, "price_kg", "qty_kg"),
            "qty_total_kg": grp["qty_kg"].sum(),
            # [2026-08-11] 실거래 최고/최저가. 물량가중평균만 내보내면 "그 달에 얼마까지
            # 받았나"가 사라진다 — 복숭아x부안 2026-06은 평균 15,726원/kg인데 실제로는
            # 53,500원/kg(2kg 상자 107,000원) 거래가 있었다. 그 거래가 32kg으로 그 달
            # 물량의 0.35%뿐이라 평균으로는 절대 안 드러난다. 모델 타깃은 평균 그대로 두고
            # 표시용으로만 쓴다(최고가는 소량 특품이라 예측 대상이 아니다).
            "price_max_kg": grp["price_kg"].max(),
            "price_min_kg": grp["price_kg"].min(),
            # 최고가 거래의 원본 단가·포장중량. 공판장에서 본 금액과 대조하려면 필요하다
            # ("10만원 넘게 나왔다"는 기억은 상자 단가지 kg 단가가 아니다).
            "price_max_unit": (grp.loc[grp["price_kg"].idxmax(), "price"]
                               if grp["price_kg"].notna().any() else float("nan")),
            "price_max_unit_qty": (grp.loc[grp["price_kg"].idxmax(), "unit_qty"]
                                   if grp["price_kg"].notna().any() else float("nan")),
            "price_avg": _wavg(grp), "qty_total": grp["qty"].sum(),
            "n_obs": len(grp),
            # kg 단가가 실제로 몇 건에서 나왔는지. n_obs는 unit_qty가 불량이라
            # kg 환산에서 빠진 행까지 세므로, 표본 두께 판정에는 이쪽을 써야 한다.
            "n_obs_kg": int(grp["price_kg"].notna().sum()),
            "n_markets": grp["market_cd"].nunique(),
        })
    return pd.DataFrame(rows)


def _report_integrity(raw: pd.DataFrame) -> None:
    """재개·재시도가 같은 (시장,날짜)를 두 번 담지 않았는지 확인만 하고 보고한다.

    같은 날 같은 시장에서 동일 조건 거래가 여러 건인 것은 katSale에서 정상이라
    행 단위 drop_duplicates는 진짜 거래를 지운다(공판장 중복 버그 대응 때 확인된
    교훈 — HANDOFF "공판장 API 중복 버그" 참고). 그래서 **(시장,날짜) 묶음이
    두 번 수집됐는지**만 본다: 재개 로직이 깨지면 여기서 배수로 튄다.
    """
    if raw.empty:
        return
    d = raw.copy()
    d["_ym"] = pd.to_datetime(d["date"], format="mixed").dt.to_period("M")
    dup_months = d.groupby(["_ym", "market_cd", "date"]).size()
    exact = int(d.duplicated().sum())
    print(f"\n[무결성] 수집 (시장,날짜) 조합 {len(dup_months)}개, "
          f"완전 동일 행 {exact}건(정상 범위: 같은 날 같은 조건 거래는 실제로 있음)")
    # 월 x 시장 x 날짜가 두 번 이상 '수집'됐는지는 행 수로는 못 보므로,
    # 대신 같은 월이 표본일 수(SAMPLE_DAYS)보다 많은 날짜를 갖는지로 본다.
    per_month_days = d.groupby("_ym")["date"].nunique()
    odd = per_month_days[per_month_days > len(SAMPLE_DAYS)]
    if len(odd):
        print(f"[무결성][경고] 표본일보다 많은 날짜가 담긴 월 {len(odd)}개 - "
              f"재개 로직 점검 필요: {list(odd.index.astype(str))[:6]}")
    else:
        print("[무결성] 월별 수집 날짜 수 정상 - 재개로 인한 중복 없음")


RAW_PATH = OUT_DIR / "jeonbuk_origin_allcrops_raw.csv"


def _write_aggregates(by_crop_county: pd.DataFrame) -> None:
    out_agg = OUT_DIR / "jeonbuk_origin_top10crops_by_county.csv"
    by_crop_county.to_csv(out_agg, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료(작물x시군별 산지가격): {out_agg} ({len(by_crop_county)}행)")

    # 상추 전용 파일(build_dataset.build_jeonbuk_origin_history가 읽음)도 같은 원시
    # 데이터에서 재생성 — scrape_jeonbuk_origin.py를 따로 다시 돌릴 필요 없음.
    lettuce = by_crop_county[by_crop_county["crop"] == "상추"]
    if not lettuce.empty:
        out_lettuce = OUT_DIR / "jeonbuk_origin_lettuce_by_county.csv"
        lettuce.drop(columns=["crop", "crop_id"]).to_csv(
            out_lettuce, index=False, encoding="utf-8-sig")
        print(f"저장 완료(상추 시군별, build_dataset용): {out_lettuce} ({len(lettuce)}행)")


def reaggregate_only() -> None:
    """이미 받아둔 원시 파일에서 kg 필드·집계만 다시 만든다(`--reaggregate`).
    _kg_fields 규칙이 바뀌었을 때 6시간짜리 재스크래핑을 다시 돌리지 않으려고 둔 경로."""
    raw = pd.read_csv(RAW_PATH)
    print(f"원시 {len(raw)}행 재집계 - unit_qty 상한 {MAX_UNIT_QTY_KG:g}kg 적용")
    fixed = recompute_kg_fields(raw)
    dropped = int(fixed["price_kg"].isna().sum() - raw["price_kg"].isna().sum())
    print(f"이번 규칙으로 새로 제외된 레코드: {dropped}건")
    fixed.to_csv(RAW_PATH, index=False, encoding="utf-8-sig")
    _write_aggregates(aggregate_raw(fixed))


def main():
    by_crop_county, raw = scrape_monthly()
    _report_integrity(raw)
    _write_aggregates(by_crop_county)

    raw.to_csv(RAW_PATH, index=False, encoding="utf-8-sig")
    print(f"저장 완료(전체 79개 작물 원시 레코드, 확장용): {RAW_PATH} ({len(raw)}행)")

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
    import sys
    if "--reaggregate" in sys.argv:
        reaggregate_only()
    else:
        main()
