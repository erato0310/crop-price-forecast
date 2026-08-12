# -*- coding: utf-8 -*-
"""build_dataset.py — 상추(lettuce) x 전북 8시군 월별 패널 데이터 구축.

가격은 KAMIS 도매/공판장 기준 단일(전국 또는 대표시장) 시계열이고,
기후·재배면적은 전북 8개 시군의 평균/합계로 지역 대표값을 만든다.
KAMIS 가격이 시군 단위로 쪼개지지 않는다는 제약은 README·docs/RESOLVE_GUIDE.md 참고.

키가 없으면 sources.py의 합성(synthetic) 폴백이 자동 동작해 파이프라인 배선만 검증된다.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

import sources as S

CROP = "lettuce"
START = "2015-01-01"
END = dt.date.today().isoformat()

# KAMIS periodProductList는 실측 결과 "오늘 기준 정확히 365일"보다 오래된 날짜를 요청하면
# 에러 없이 조용히 최근 1년 데이터로 치환하면서 응답에 20~35초가 걸린다(400일 전 요청도 28초).
# 365일 안쪽(350일)으로 요청하면 실제 요청한 날짜 그대로 몇 초 안에 응답한다(docs/RESOLVE_GUIDE.md "-1)" 참고).
# 그 이상 과거는 이 API로 못 받으므로, 2015~2024 히스토리는 별도 소스
# (RESOLVE_GUIDE.md의 data.go.kr 15134477 등)로 채워야 한다.
KAMIS_PRICE_START = (dt.date.today() - dt.timedelta(days=350)).isoformat()

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# scrape_garak.py가 만든 가락시장(서울) 경락가격 월별 근사치. KAMIS periodProductList의
# "전국평균"과는 시장 범위가 다른 별도 계열이라 price_avg와 절대 합치지 않고 별도 컬럼으로
# 붙인다 — docs/RESOLVE_GUIDE.md "가락시장 vs 전국평균 레벨 차이" 참고.
GARAK_HISTORY_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "garak_lettuce_history.csv"

# scrape_jeonbuk_market.py가 만든 진짜 전북 지역 공판장(전주·익산·정읍) 상추 거래 월별
# 물량가중평균 — 2018-01~현재. 이게 지금까지 중 유일하게 "전북 지역" 실데이터다(price_avg는
# 전국평균, price_avg_garak_seoul은 서울 가락시장). models.TARGET을 이걸로 전환함
# (docs/RESOLVE_GUIDE.md·models.py docstring 참고).
JEONBUK_HISTORY_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "jeonbuk_market_lettuce_history.csv"

# scrape_jeonbuk_market.py가 시장별로 안 합치고 따로 저장한 버전(long format: region_id
# ∈ {jeonju, iksan, jeongeup}). "지역마다 공판장이 다르고 가격도 다를 것"이라는 지적에
# 따라 3개 시장을 합친 price_avg_jeonbuk 말고 시장별 개별 시계열도 패널에 얹는다.
JEONBUK_REGION_HISTORY_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "jeonbuk_market_lettuce_by_region.csv"

# scrape_jeonbuk_origin.py가 만든, **산지(생산지) 기준** 전북 시군별 상추 가격 — 위
# jeonbuk_market_lettuce_by_region.csv(시장 "위치" 기준)와는 다른 개념이다. 실측해보니
# 전북산 상추의 94%가 전북 안의 시장(전주·익산·정읍)이 아니라 전국 각지(광주·서울가락·
# 부산·대구·대전·순천·창원 등)로 팔린다 — "시장이 어디 있는가"가 아니라 katSale/trades의
# `plor_nm`(산지) 필드로 "어느 시군에서 난 상추인가"를 추적해야 진짜 지역별 가격이 나온다.
# 전북산 상추가 실제로 팔리는 상위 17개 시장(누적거래량 97.9% 커버, katRealTime2/trades2
# 5일 표본으로 확정)을 돌아 만들었다. 전북 14개 시군 거의 전부가 산지로 잡힌다.
JEONBUK_ORIGIN_HISTORY_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "jeonbuk_origin_lettuce_by_county.csv"

# scrape_jeonbuk_all_crops.py가 만든, 상추 외 "전북산 거래량 상위 10개 작물"
# (상추·수박·포도·오이·토마토·복숭아·고구마·방울토마토·멜론·대파) × 14개 시군 산지가격.
# 위 상추 전용 파일과 원리는 같고(katSale/trades의 plor_nm 산지 필드 기준, 같은 상위 17개
# 시장), 품목 필터를 빼서 한 번의 스크래핑으로 여러 작물을 동시에 받았다. 컬럼명은
# price_avg_origin_{crop_id}_{county_id} 형태(예: price_avg_origin_watermelon_namwon).
ALL_CROPS_ORIGIN_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "jeonbuk_origin_top10crops_by_county.csv"

# [2026-08-11] 한 달의 "그 시군 가격"으로 인정할 최소 거래 건수.
# 거래 1건으로 만든 월평균은 시장가격이 아니라 잡음이다 — 진안 토마토의 2020-02·03월이
# 각각 1건짜리라 11,333·16,000원/kg(두터운 달 중앙값 2,374원/kg의 5~7배)로 잡혔고,
# 이게 lag 피처를 오염시켜 CV MAPE를 26% -> 135%로 터뜨렸다. 익산 복숭아도 1건짜리 달이
# 500원 ~ 22,500원으로 널뛴다. 버리는 비용은 작다: n_obs_kg<2인 달은 집계 행의 7.7%지만
# **거래물량으로는 0.16%**뿐이다.
#
# 값은 CV로 정했다(tune_min_obs.py, 로그 outputs/min_obs_threshold_cv.log).
# 주의: 임계값을 올리면 어려운 조합이 유효 목록에서 빠져 중앙 MAPE가 자동으로 좋아진다 —
# 그래서 모든 임계값에서 살아남은 공통 70개 조합으로 비교해야 한다:
#     임계값   유효조합   공통70개 중앙MAPE   MAPE>=100%
#       1        93          26.36%             3개
#       2        88          25.44%             1개
#       3        76          24.45%             0개
#       5        70          24.45%             0개
# 3~5는 정확도가 같은 수준에서 포화되는데 조합을 12~18개 더 잃는다. 1건짜리 달만
# 걷어내는 2가 "월평균이라 부를 수 있는 최소 조건"이라는 근거도 가장 분명해서 2를 채택.
# 정확도를 더 원하면 3으로 올리면 되지만 웹앱에 노출할 작물x시군이 88 -> 76으로 준다.
MIN_OBS_PER_MONTH = 2


def _drop_thin_months(long: pd.DataFrame, label: str) -> pd.DataFrame:
    """거래 건수가 MIN_OBS_PER_MONTH 미만인 (작물x시군x월) 행 제거.
    n_obs_kg(=kg 단가가 실제로 나온 건수)가 있으면 그걸 쓴다 — n_obs는 unit_qty 불량으로
    kg 환산에서 빠진 행까지 세기 때문에 표본 두께를 과대평가한다."""
    if MIN_OBS_PER_MONTH <= 1 or long.empty:
        return long
    col = "n_obs_kg" if "n_obs_kg" in long.columns else "n_obs"
    before = len(long)
    long = long[long[col] >= MIN_OBS_PER_MONTH]
    print(f"  [{label}] 표본 얇은 달 제거: {before} -> {len(long)}행 ({col} >= {MIN_OBS_PER_MONTH})")
    return long


def _month_range(start: str, end: str) -> pd.PeriodIndex:
    return pd.period_range(start=start, end=end, freq="M")


def _fmt_for_cycle(cycle: str, date_str: str) -> str:
    d = dt.date.fromisoformat(date_str)
    if cycle == "M":
        return d.strftime("%Y%m")
    if cycle == "Y":
        return d.strftime("%Y")
    return d.strftime("%Y%m%d")


def build_price_monthly() -> pd.DataFrame:
    df = S.load_prices(CROP, KAMIS_PRICE_START, END)
    df["date"] = pd.to_datetime(df["date"])
    df["ym"] = df["date"].dt.to_period("M")
    agg = (
        df.groupby("ym")["price"]
        .agg(price_avg="mean", price_median="median", price_std="std",
             price_min="min", price_max="max", n_price_obs="count")
        .reset_index()
    )
    agg.attrs["source"] = df.attrs.get("source", "unknown")
    return agg


def build_weather_monthly(regions: list[str]) -> pd.DataFrame:
    start_ymd = START.replace("-", "")
    end_ymd = END.replace("-", "")
    frames = []
    for r in regions:
        d = S.load_weather(r, start_ymd, end_ymd)
        if d is None or d.empty:
            continue
        d["ym"] = pd.to_datetime(d["date"]).dt.to_period("M")
        frames.append(d)
    if not frames:
        return pd.DataFrame(columns=["ym", "tavg", "rain_sum", "sun_sum"])
    allw = pd.concat(frames, ignore_index=True)
    n_regions = allw["region_id"].nunique() or 1
    agg = allw.groupby("ym").agg(
        tavg=("tavg", "mean"),
        rain_sum=("rain", "sum"),
        sun_sum=("sun", "sum"),
    ).reset_index()
    # 시군별 합산치를 시군 수로 나눠 "전북 평균" 스케일로 맞춘다.
    agg["rain_sum"] = agg["rain_sum"] / n_regions
    agg["sun_sum"] = agg["sun_sum"] / n_regions
    return agg


def build_area_yearly(regions: list[str]) -> pd.DataFrame:
    frames = []
    for r in regions:
        d = S.load_area(r, CROP, start_year=START[:4], end_year=END[:4])
        if d is None or d.empty:
            continue
        frames.append(d)
    if not frames:
        return pd.DataFrame(columns=["year", "area_ha"])
    alla = pd.concat(frames, ignore_index=True)
    # 상추(KOSIS DT_1ET0028)는 시군이 아니라 시도(전북) 단위로만 제공돼 8개 시군이 전부
    # 같은 도 단위 값을 공유한다. sum()을 쓰면 8중복(x8)이 되므로 mean()으로 집계한다
    # (지역별 실제 면적이 갈리는 표라면 여기를 다시 sum()으로 되돌려야 함).
    return alla.groupby("year")["area"].mean().reset_index().rename(columns={"area": "area_ha"})


def build_garak_history() -> pd.DataFrame:
    if not GARAK_HISTORY_PATH.exists():
        return pd.DataFrame(columns=["ym", "price_avg_garak_seoul", "n_obs_garak_seoul"])
    df = pd.read_csv(GARAK_HISTORY_PATH, encoding="utf-8-sig")
    df["ym"] = pd.PeriodIndex(df["ym"], freq="M")
    return df.rename(columns={
        "price_avg_garak": "price_avg_garak_seoul",
        "n_obs_garak": "n_obs_garak_seoul",
    })


def build_jeonbuk_history() -> pd.DataFrame:
    if not JEONBUK_HISTORY_PATH.exists():
        return pd.DataFrame(columns=["ym", "price_avg_jeonbuk", "qty_total_jeonbuk", "n_obs_jeonbuk"])
    df = pd.read_csv(JEONBUK_HISTORY_PATH, encoding="utf-8-sig")
    df["ym"] = pd.PeriodIndex(df["ym"], freq="M")
    return df


def build_jeonbuk_region_history() -> pd.DataFrame:
    """long(ym,region_id,price_avg,qty_total,n_obs) -> wide(ym, price_avg_{region},
    qty_total_{region}, n_obs_{region}) — 시장(전주/익산/정읍)별로 컬럼을 나눈다."""
    if not JEONBUK_REGION_HISTORY_PATH.exists():
        return pd.DataFrame(columns=["ym"])
    long = pd.read_csv(JEONBUK_REGION_HISTORY_PATH, encoding="utf-8-sig")
    long["ym"] = pd.PeriodIndex(long["ym"], freq="M")
    wide = long.pivot(index="ym", columns="region_id", values=["price_avg", "qty_total", "n_obs"])
    wide.columns = [f"{metric}_{region}" for metric, region in wide.columns]
    return wide.reset_index()


# 전북 14개 시군 한글명 -> 컬럼용 로마자 id. 기존 region_crosswalk.csv의 8개(jinan~buan)와
# 이름 규칙을 맞추고, 거기 없던 6개(전주·군산·무주·장수·임실·순창)를 추가했다.
COUNTY_NAME_TO_ID = {
    "전주시": "jeonju", "군산시": "gunsan", "익산시": "iksan", "정읍시": "jeongeup",
    "남원시": "namwon", "김제시": "gimje", "완주군": "wanju", "진안군": "jinan",
    "무주군": "muju", "장수군": "jangsu", "임실군": "imsil", "순창군": "sunchang",
    "고창군": "gochang", "부안군": "buan",
}


def build_jeonbuk_origin_history() -> pd.DataFrame:
    """long(ym,county,price_avg_kg,qty_total_kg,n_obs) -> wide(ym, price_avg_origin_{county_id}, ...)
    — 산지(생산지) 기준 전북 시군별 상추 가격. 시장 기준(build_jeonbuk_region_history)과
    헷갈리지 않게 컬럼명에 origin_을 넣는다.

    [2026-08 단위 통일] build_all_crops_origin_history()와 같은 이유로 **원/kg** 기준으로
    바꿨다(상세 근거는 그쪽 docstring). 이 파일은 scrape_jeonbuk_all_crops.py가 상추만
    떼어 재생성하므로 컬럼 구성도 top10 집계 파일과 동일하다."""
    if not JEONBUK_ORIGIN_HISTORY_PATH.exists():
        return pd.DataFrame(columns=["ym"])
    long = pd.read_csv(JEONBUK_ORIGIN_HISTORY_PATH, encoding="utf-8-sig")
    if "price_avg_kg" not in long.columns:
        raise SystemExit(
            f"{JEONBUK_ORIGIN_HISTORY_PATH.name}에 price_avg_kg가 없습니다 — "
            "scrape_jeonbuk_all_crops.py를 kg 필드 추가 버전으로 다시 돌려야 합니다.")
    long = _drop_thin_months(long, "상추 산지")
    long["ym"] = pd.PeriodIndex(long["ym"], freq="M")
    long["county_id"] = long["county"].map(COUNTY_NAME_TO_ID).fillna(long["county"])
    wide = long.pivot(index="ym", columns="county_id",
                      values=["price_avg_kg", "qty_total_kg", "n_obs"])
    # 하류(county_cv/county_predict/forecast_future)는 price_avg_origin_* 이름을 그대로
    # 쓰므로 이름은 유지하고 내용만 kg 기준으로 바꾼다.
    rename = {"price_avg_kg": "price_avg", "qty_total_kg": "qty_total", "n_obs": "n_obs"}
    wide.columns = [f"{rename[metric]}_origin_{county}" for metric, county in wide.columns]
    return wide.reset_index()


def build_all_crops_origin_history() -> pd.DataFrame:
    """long(ym,crop_id,county,price_avg_kg,qty_total_kg,...) -> wide(ym,
    price_avg_origin_{crop_id}_{county_id}, ...) — 상추 외 상위 10개 작물.

    [2026-08 단위 통일] 가격을 **원/kg**으로 바꿨다. katSale의 avgprc는 '거래 단위(상자)당'
    단가라 같은 작물이라도 3kg/12kg 상자가 섞이면 단가가 몇 배씩 널뛴다(수박 상자단가
    변동폭 35배 → kg 환산 11배, 대파 18배 → 6배로 실측 확인). 산지공판장(gpj)도 원래
    원/kg이라 이제 두 소스의 단위가 같아졌다 — 웹앱에서 나란히 비교해도 된다.
    price_avg(상자당)는 과거 결과와 대조하려고 스크래퍼가 계속 남기지만 여기선 안 쓴다."""
    if not ALL_CROPS_ORIGIN_PATH.exists():
        return pd.DataFrame(columns=["ym"])
    long = pd.read_csv(ALL_CROPS_ORIGIN_PATH, encoding="utf-8-sig")
    if "price_avg_kg" not in long.columns:
        raise SystemExit(
            f"{ALL_CROPS_ORIGIN_PATH.name}에 price_avg_kg가 없습니다 — "
            "scrape_jeonbuk_all_crops.py를 kg 필드 추가 버전으로 다시 돌려야 합니다.")
    long = _drop_thin_months(long, "전작물 산지")
    long["ym"] = pd.PeriodIndex(long["ym"], freq="M")
    long["county_id"] = long["county"].map(COUNTY_NAME_TO_ID).fillna(long["county"])
    long["key"] = long["crop_id"] + "_" + long["county_id"]
    wide = long.pivot(index="ym", columns="key",
                      values=["price_avg_kg", "qty_total_kg", "n_obs"])
    # 하류(피처·CV·웹앱)는 price_avg_origin_* 이름을 그대로 쓰므로 이름은 유지하고
    # 내용만 kg 기준으로 바꾼다.
    rename = {"price_avg_kg": "price_avg", "qty_total_kg": "qty_total", "n_obs": "n_obs"}
    wide.columns = [f"{rename[metric]}_origin_{key}" for metric, key in wide.columns]
    return wide.reset_index()


GONGPANJANG_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "gongpanjang_top10crops_by_county.csv"


def build_gongpanjang_history() -> pd.DataFrame:
    """산지공판장 정산가격(농식품부 포털, scrape_gongpanjang.py) -> wide(ym,
    price_avg_gpj_{crop_id}_{county_id}, ...). katSale 도매시장 데이터와 단위 체계가
    달라(원/kg 정규화) 별도 컬럼으로 둔다. 2020-01부터. 군산·임실·정읍·부안처럼
    도매시장 표본이 얇은 시군의 보완 소스."""
    if not GONGPANJANG_PATH.exists():
        return pd.DataFrame(columns=["ym"])
    long = pd.read_csv(GONGPANJANG_PATH, encoding="utf-8-sig")
    long["ym"] = pd.PeriodIndex(long["ym"], freq="M")
    long["county_id"] = long["county"].map(COUNTY_NAME_TO_ID).fillna(long["county"])
    long["key"] = long["crop_id"] + "_" + long["county_id"]
    wide = long.pivot(index="ym", columns="key",
                      values=["price_avg_kg", "qty_total_kg", "n_obs"])
    metric_names = {"price_avg_kg": "price_avg", "qty_total_kg": "qty_total", "n_obs": "n_obs"}
    wide.columns = [f"{metric_names[m]}_gpj_{key}" for m, key in wide.columns]
    return wide.reset_index()


_CYCLE_DATE_FMT = {"D": "%Y%m%d", "M": "%Y%m", "Y": "%Y"}


def build_macro_monthly() -> pd.DataFrame:
    frames = []
    for series, spec in S.ECOS_SERIES.items():
        s_start = _fmt_for_cycle(spec["cycle"], START)
        s_end = _fmt_for_cycle(spec["cycle"], END)
        d = S.load_macro(series, s_start, s_end)
        if d is None or d.empty:
            continue
        # cycle="M"이면 date가 "YYYYMM"(6자리)라 포맷 없이 to_datetime하면 전부 NaT로
        # 조용히 사라진다(cycle="D"의 8자리 "YYYYMMDD"는 우연히 자동인식돼서 안 걸렸음) —
        # csi가 비어있던 원인이 이거였다. cycle별 포맷을 명시해서 고침.
        fmt = _CYCLE_DATE_FMT.get(spec["cycle"])
        d["date"] = pd.to_datetime(d["date"], format=fmt, errors="coerce")
        d = d.dropna(subset=["date"])
        d["ym"] = d["date"].dt.to_period("M")
        m = d.groupby("ym")["value"].mean().reset_index().rename(columns={"value": series})
        frames.append(m)
    if not frames:
        return pd.DataFrame(columns=["ym", "fx_usd", "csi"])
    out = frames[0]
    for f in frames[1:]:
        out = out.merge(f, on="ym", how="outer")
    return out


def build_panel() -> pd.DataFrame:
    regions = list(S.region_xwalk().index)

    price = build_price_monthly()
    weather = build_weather_monthly(regions)
    area = build_area_yearly(regions)
    macro = build_macro_monthly()
    garak = build_garak_history()
    jeonbuk = build_jeonbuk_history()
    jeonbuk_region = build_jeonbuk_region_history()
    jeonbuk_origin = build_jeonbuk_origin_history()
    all_crops_origin = build_all_crops_origin_history()
    gongpanjang = build_gongpanjang_history()

    months = pd.DataFrame({"ym": _month_range(START, END)})
    panel = (
        months.merge(price, on="ym", how="left")
        .merge(weather, on="ym", how="left")
        .merge(macro, on="ym", how="left")
        .merge(garak, on="ym", how="left")
        .merge(jeonbuk, on="ym", how="left")
        .merge(jeonbuk_region, on="ym", how="left")
        .merge(jeonbuk_origin, on="ym", how="left")
        .merge(all_crops_origin, on="ym", how="left")
        .merge(gongpanjang, on="ym", how="left")
    )

    panel["year"] = panel["ym"].dt.year
    if not area.empty:
        area["year"] = area["year"].astype(int)
        panel = panel.merge(area, on="year", how="left")
        panel["area_ha"] = panel.groupby("year")["area_ha"].transform(lambda s: s.ffill().bfill())
    else:
        panel["area_ha"] = np.nan

    panel["price_source"] = price.attrs.get("source", "unknown")
    return panel.sort_values("ym").reset_index(drop=True)


def main():
    panel = build_panel()
    out_path = OUT_DIR / "monthly_panel.csv"
    panel.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"저장 완료: {out_path} ({len(panel)}행)")
    if len(panel):
        print(f"가격 소스: {panel['price_source'].iloc[0]}")
    print(panel.head(15).to_string(index=False))


if __name__ == "__main__":
    main()
