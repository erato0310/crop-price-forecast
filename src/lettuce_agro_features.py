# -*- coding: utf-8 -*-
"""lettuce_agro_features.py — 상추 생리·생태 기반 기상 피처 생성.

기존 thermal_features.py(전북 8개 시군, tmax/tmin/rain만)를 세 방향으로 확장한다.

────────────────────────────────────────────────────────────────
1. 시군 확대 — 출하량의 12.7%가 기상 없이 모델링되고 있었다
────────────────────────────────────────────────────────────────
region_crosswalk.csv는 8개 시군만 담는데, 실제 전북산 상추 출하 시군은 14개다.
2018-01~2021-02 물량 실측 기준 누락분:

    장수군  6.85% (출하 4위) <- **준고랭지(해발 406m). 여름 대체산지의 핵심**
    전주시  4.42% (5위)
    순창군  1.46%
    ------ 합계 12.73%

특히 장수군 누락이 뼈아프다. HANDOFF_rev2 7.1은 "해발 400m 이상 고랭지 관측지점이
없다"며 여름철 정확도 한계를 미해결로 남겼는데, **장수 ASOS(248)는 존재한다.**
크로스워크에 없었을 뿐이다. 실측(2025-08-01~10 일최고 평균):

    장수 29.7C < 임실 30.6C < 부안 31.1C < 남원 31.6C < 순창 31.8C < 정읍 32.4C

rev2가 "전북 내 고온일수 격차 3.6일뿐"이라 한 것은 진안을 임실(244)로 대체해
계산했기 때문이다. 장수를 넣으면 격차가 벌어진다.

────────────────────────────────────────────────────────────────
2. 필드 확대 — sun_sum은 날씨가 아니라 달력이었다
────────────────────────────────────────────────────────────────
sources.py:378이 ASOS의 `ssDur`을 뽑아 "sun"으로 저장하고 build_dataset이 이를
`sun_sum`으로 집계한다. 그런데 **`ssDur`은 가조시간**(일출~일몰 이론값)이다.
날짜·위도만의 함수라 month_sin/cos와 사실상 같은 정보이고 기상 정보가 없다.
실측(전주 146, 2025-08):

    날짜     ssDur  sumSsHr  sumGsr  강수
    08-01     14.0     12.6   27.50     -      <- 맑음
    08-03     13.9      0.0    5.68  42.3mm    <- 폭우, 실제 일조 0
    08-06     13.8      0.8   11.29   2.8mm

실제 일조시간은 `sumSsHr`, 일사량은 `sumGsr`이다. 겨울 시설 상추의 1차 제한요인이
광량이므로 이 둘이 있어야 겨울 구간을 설명할 수 있다. 습도(`avgRhm`)도 같이 받는다
— 무름병·균핵병은 고온다습에서 나온다.

일조율 = sumSsHr / ssDur 을 파생한다. 계절 길이 효과가 나눠서 제거되므로
"그 달이 평소보다 흐렸는가"만 남는다.

────────────────────────────────────────────────────────────────
3. 출하량 가중 — 주산지 이동을 새 자료 없이 반영
────────────────────────────────────────────────────────────────
전북 내부에서 여름에 주산지가 이동한다(2023+2025 실측, kg 기준):

    월    익산    완주    남원    장수    진안  | 준고랭지(무진장)
     1   50.5%  22.4%  17.3%   1.1%   0.2% |   1.3%
     8   37.7%  17.6%  22.2%   7.2%   5.3% |  12.7%   <- 10배

평지 시설(익산)이 고온으로 멈추고 준고랭지가 그 자리를 메운다. 시군 단순평균
기상을 쓰면 이 이동이 통째로 사라진다. 각 시군 기상을 **그 달의 출하 비중으로
가중**하면 반영된다. rev2 7.1이 "다지역 기상 입력이 필요하다"며 남긴 과제가
새 자료 없이 풀린다.

*** 누출 주의 *** 예측 대상월의 실제 출하 비중은 그 시점에 알 수 없다. 그래서
가중치는 **학습구간에서 계산한 달력월별 평년 비중**을 쓴다(calendar-month
climatology). 8월이면 "8월엔 보통 장수 비중이 높다"는 사전 지식만 쓰는 셈이라
누출이 없다. 실제 비중을 쓰는 변형은 `--weights actual`로 만들 수 있으나 이는
**설명용이며 예측에 쓰면 안 된다**(rev2 3.1이 지적한 당월변수 누출과 같은 종류).

────────────────────────────────────────────────────────────────
실행
────────────────────────────────────────────────────────────────
  python lettuce_agro_features.py fetch     # ASOS 일자료 수집(9지점 x 2015~), ~5분
  python lettuce_agro_features.py build     # 생리 피처 생성
  python lettuce_agro_features.py report    # 피처 계절 프로파일 진단
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
import urllib.parse
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")

KEY = urllib.parse.unquote(os.getenv("DATA_GO_KR_KEY", ""))
ASOS_URL = "https://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"

RAW = _ROOT / "data" / "raw"
PROC = _ROOT / "data" / "processed"
PROC.mkdir(parents=True, exist_ok=True)

DAILY_PATH = RAW / "daily_weather_lettuce.csv"
MONTHLY_PATH = PROC / "agro_features_monthly.csv"
WEIGHTS_PATH = PROC / "county_shipment_weights.csv"
PRICE_DAILY = RAW / "lettuce_daily_by_county.csv"

START_YEAR = 2015          # 2018 타깃의 lag12/roll을 채우려면 앞이 더 필요하다
REQUEST_DELAY_SEC = 0.25

# 시군 -> ASOS 지점. 2026-08-11 전 지점 실측 확인(stnNm 대조 + 8/1~10 기온).
# station_type: 자체=그 시군에 지점이 있음, 인접=가장 가까운 지점으로 대체.
COUNTY_STATION: dict[str, tuple[str, str, str]] = {
    # county_ko:      (stn, county_id,    station_type/비고)
    "익산시":  ("140", "iksan",    "인접(군산)"),
    "남원시":  ("247", "namwon",   "자체"),
    "완주군":  ("146", "wanju",    "인접(전주)"),
    "장수군":  ("248", "jangsu",   "자체 — 해발 406m 준고랭지"),
    "전주시":  ("146", "jeonju",   "자체"),
    "김제시":  ("146", "gimje",    "인접(전주)"),
    "순창군":  ("254", "sunchang", "자체"),
    "진안군":  ("244", "jinan",    "인접(임실) — 진안 자체 ASOS 없음"),
    "고창군":  ("172", "gochang",  "자체"),
    "정읍시":  ("245", "jeongeup", "자체"),
    "부안군":  ("243", "buan",     "자체"),
    "무주군":  ("248", "muju",     "인접(장수) — 같은 무진장 산간"),
    "임실군":  ("244", "imsil",    "자체"),
    "군산시":  ("140", "gunsan",   "자체"),
}

# ── 생리 임계값 ────────────────────────────────────────────────
# 상추(Lactuca sativa)는 저온성 작물. 생육적온 15~20C.
T_BOLT = 30.0      # 일최고. 추대(bolting)·잎끝마름 유발 문턱
T_BOLT_SEVERE = 33.0
T_TROPNIGHT = 20.0  # 일최저. 야간 고온 -> 호흡 소모 증가, 동화산물 축적 저하
T_GERM_BLOCK = 25.0  # 일평균. 종자 열휴면(thermo-dormancy) 발아율 급락 구간
T_FROST = 0.0
T_SEVERE_COLD = -5.0
DARK_HOURS = 3.0     # 일조 3시간 이하 = 사실상 흐린 날
HUMID_RH = 80.0      # 무름병·잿빛곰팡이 발병 습도


def _to_num(x) -> float:
    try:
        v = float(x)
        return np.nan if v <= -99 else v
    except (TypeError, ValueError):
        return np.nan


# ═══════════════════════════════════════════════════════════════
# 1. 수집
# ═══════════════════════════════════════════════════════════════

def _fetch_chunk(stn: str, start: str, end: str) -> list[dict]:
    params = {
        "serviceKey": KEY, "dataType": "JSON", "dataCd": "ASOS", "dateCd": "DAY",
        "startDt": start, "endDt": end, "stnIds": stn, "numOfRows": 999, "pageNo": 1,
    }
    for attempt in range(4):
        try:
            r = requests.get(ASOS_URL, params=params, timeout=60)
            if "LIMITED_NUMBER" in r.text:
                raise RuntimeError("ASOS 일일 요청 한도 초과 — 자정 이후 재실행")
            r.raise_for_status()
            items = r.json()["response"]["body"]["items"]["item"]
            if isinstance(items, dict):
                items = [items]
            return items
        except RuntimeError:
            raise
        except Exception:
            if attempt == 3:
                print(f"    ! 실패: 지점{stn} {start}~{end}", flush=True)
                return []
            time.sleep(2 * (attempt + 1))
    return []


def fetch() -> pd.DataFrame:
    if not KEY:
        sys.exit("DATA_GO_KR_KEY 없음")
    # ASOS는 '어제까지'만 제공한다. 오늘을 endDt에 넣으면 구간 전체가 거부된다.
    end_d = dt.date.today() - dt.timedelta(days=1)
    stations = sorted({s for s, _, _ in COUNTY_STATION.values()})
    print(f"ASOS 일자료 수집 | 지점 {len(stations)}곳 | {START_YEAR}-01-01 ~ {end_d}")

    rows: list[dict] = []
    for stn in stations:
        got = 0
        for yr in range(START_YEAR, end_d.year + 1):
            s = dt.date(yr, 1, 1)
            e = min(dt.date(yr, 12, 31), end_d)
            if s > e:
                continue
            for it in _fetch_chunk(stn, s.strftime("%Y%m%d"), e.strftime("%Y%m%d")):
                rows.append({
                    "stn": stn, "stn_nm": it.get("stnNm"),
                    "date": it.get("tm"),
                    "tavg": _to_num(it.get("avgTa")),
                    "tmax": _to_num(it.get("maxTa")),
                    "tmin": _to_num(it.get("minTa")),
                    "rain": _to_num(it.get("sumRn")),
                    # sumSsHr = 실제 일조시간. ssDur(가조시간)과 혼동 금지 — 상단 주석 참고
                    "sun_hr": _to_num(it.get("sumSsHr")),
                    "sun_possible": _to_num(it.get("ssDur")),
                    "rad_mj": _to_num(it.get("sumGsr")),
                    "rh": _to_num(it.get("avgRhm")),
                    "rh_min": _to_num(it.get("minRhm")),
                    "wind": _to_num(it.get("avgWs")),
                })
                got += 1
            time.sleep(REQUEST_DELAY_SEC)
        print(f"  지점 {stn}: {got:,}일", flush=True)

    d = pd.DataFrame(rows)
    d["rain"] = d["rain"].fillna(0.0)     # ASOS는 무강수일을 빈 값으로 준다
    d = d.dropna(subset=["date"]).drop_duplicates(["stn", "date"])
    d.to_csv(DAILY_PATH, index=False, encoding="utf-8-sig")
    print(f"\n저장: {DAILY_PATH.name} ({len(d):,}행)")
    _report_coverage(d)
    return d


def _report_coverage(d: pd.DataFrame) -> None:
    print("\n[수집 점검]")
    dd = d.copy()
    dd["date"] = pd.to_datetime(dd["date"])
    for stn, g in dd.groupby("stn"):
        cal = (g["date"].max() - g["date"].min()).days + 1
        miss = cal - len(g)
        nm = g["stn_nm"].iloc[0]
        na = {c: f"{g[c].isna().mean()*100:.0f}%"
              for c in ("tmax", "tmin", "sun_hr", "rad_mj", "rh") if g[c].isna().any()}
        print(f"  {stn} {nm:6s} {len(g):,}일 (달력 {cal:,}, 결일 {miss})"
              + (f"  결측필드 {na}" if na else "  결측 없음"))


# ═══════════════════════════════════════════════════════════════
# 2. 일별 -> 생리 피처
# ═══════════════════════════════════════════════════════════════

def _streak_days(flags: pd.Series, min_run: int = 3) -> float:
    """min_run일 이상 연속으로 참인 구간에 속한 날의 수.

    고온 장해는 문턱 반응이면서 지속성 반응이다 — 30C가 흩어진 3일과
    연속 3일은 피해가 다르다. rev2는 단순 카운트만 시도했다.
    """
    v = flags.fillna(False).astype(bool).values
    total, run = 0, 0
    for x in list(v) + [False]:
        if x:
            run += 1
        else:
            if run >= min_run:
                total += run
            run = 0
    return float(total)


def _max_streak(flags: pd.Series) -> float:
    v = flags.fillna(False).astype(bool).values
    best = run = 0
    for x in v:
        run = run + 1 if x else 0
        best = max(best, run)
    return float(best)


def build_daily_flags(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["date"] = pd.to_datetime(d["date"])
    d["hot"] = d["tmax"] >= T_BOLT
    d["vhot"] = d["tmax"] >= T_BOLT_SEVERE
    d["heat_deg"] = (d["tmax"] - T_BOLT).clip(lower=0)
    d["trop"] = d["tmin"] >= T_TROPNIGHT
    d["night_heat_deg"] = (d["tmin"] - T_TROPNIGHT).clip(lower=0)
    d["germ_block"] = d["tavg"] >= T_GERM_BLOCK
    d["cold"] = d["tmin"] <= T_FROST
    d["vcold"] = d["tmin"] <= T_SEVERE_COLD
    d["frost_deg"] = (T_FROST - d["tmin"]).clip(lower=0)
    d["dtr"] = d["tmax"] - d["tmin"]
    d["dark"] = d["sun_hr"] <= DARK_HOURS
    d["wet"] = d["rain"] >= 1.0
    d["humid_hot"] = (d["tmax"] >= 25.0) & (d["rh"] >= HUMID_RH)
    return d


def build_monthly_by_station(d: pd.DataFrame) -> pd.DataFrame:
    d = build_daily_flags(d)
    d["ym"] = d["date"].dt.to_period("M")
    g = d.groupby(["stn", "ym"])
    out = g.agg(
        tavg=("tavg", "mean"), dtr=("dtr", "mean"),
        # 고온 / 추대
        hot_days=("hot", "sum"), vhot_days=("vhot", "sum"),
        heat_deg=("heat_deg", "sum"),
        # 야간 고온
        trop_nights=("trop", "sum"), night_heat_deg=("night_heat_deg", "sum"),
        # 발아 저해(열휴면) — 파종기에 작용
        germ_block_days=("germ_block", "sum"),
        # 저온
        cold_days=("cold", "sum"), vcold_days=("vcold", "sum"),
        frost_deg=("frost_deg", "sum"),
        # 광 — 겨울 시설 제한요인
        sun_hours=("sun_hr", "sum"), sun_possible=("sun_possible", "sum"),
        dark_days=("dark", "sum"), rad_mj=("rad_mj", "sum"),
        # 병해 / 습해
        rain_sum=("rain", "sum"), wet_days=("wet", "sum"),
        humid_hot_days=("humid_hot", "sum"), rh=("rh", "mean"),
        n_days=("date", "nunique"),
    ).reset_index()

    streaks = g.apply(lambda x: pd.Series({
        "hot_streak3": _streak_days(x["hot"], 3),
        "hot_streak_max": _max_streak(x["hot"]),
        "wet_streak_max": _max_streak(x["wet"]),
    }), include_groups=False).reset_index()
    out = out.merge(streaks, on=["stn", "ym"])

    # 일조율: 계절 길이(가조시간)로 나눠 "평소보다 흐렸는가"만 남긴다
    out["sun_ratio"] = out["sun_hours"] / out["sun_possible"].replace(0, np.nan)
    return out.drop(columns=["sun_possible"])


FEATURE_COLS = [
    "tavg", "dtr", "hot_days", "vhot_days", "heat_deg", "hot_streak3", "hot_streak_max",
    "trop_nights", "night_heat_deg", "germ_block_days", "cold_days", "vcold_days",
    "frost_deg", "sun_hours", "sun_ratio", "dark_days", "rad_mj",
    "rain_sum", "wet_days", "wet_streak_max", "humid_hot_days", "rh",
]


# ═══════════════════════════════════════════════════════════════
# 3. 출하량 가중치 (누출 없는 평년 비중)
# ═══════════════════════════════════════════════════════════════

def build_weights(train_end: str | None = None) -> pd.DataFrame:
    """달력월별 시군 출하 비중(평년). train_end 이전 자료만 쓴다.

    반환: [month(1~12), county_id, w]  (월별 합 = 1)

    누출 방지: 예측 대상월의 실제 비중이 아니라 '그 달엔 보통 이랬다'는 계절
    패턴만 쓴다. CV에서는 fold마다 train_end를 옮겨 재계산해야 한다.
    """
    if not PRICE_DAILY.exists():
        sys.exit(f"{PRICE_DAILY.name} 없음 — scrape_lettuce_daily.py 먼저 실행")
    p = pd.read_csv(PRICE_DAILY)
    p["date"] = pd.to_datetime(p["date"])
    if train_end:
        p = p[p["date"] <= pd.Timestamp(train_end)]
    p["month"] = p["date"].dt.month
    p["county_id"] = p["county"].map({k: v for k, (_, v, _) in COUNTY_STATION.items()})
    unmapped = p[p["county_id"].isna()]["county"].unique()
    if len(unmapped):
        print(f"[경고] COUNTY_STATION에 없는 시군: {list(unmapped)} — 가중치에서 제외됨")
    p = p.dropna(subset=["county_id"])

    w = p.groupby(["month", "county_id"])["qty_kg"].sum().reset_index()
    w["w"] = w.groupby("month")["qty_kg"].transform(lambda x: x / x.sum())
    return w[["month", "county_id", "w"]]


def weighted_monthly(station_monthly: pd.DataFrame, weights: pd.DataFrame) -> pd.DataFrame:
    """시군 가중평균 기상. 시군 -> 지점 매핑을 거쳐 붙인다."""
    c2s = {cid: stn for _, (stn, cid, _) in COUNTY_STATION.items()}
    w = weights.copy()
    w["stn"] = w["county_id"].map(c2s)
    sm = station_monthly.copy()
    sm["month"] = sm["ym"].dt.month

    m = sm.merge(w, on=["stn", "month"], how="inner")
    # 같은 지점을 여러 시군이 공유하면(예: 146 = 전주·완주·김제) 가중치가 합산된다 —
    # 그게 맞다. 그 지점 기상이 그만큼의 출하를 대표하기 때문이다.
    out = {}
    for c in FEATURE_COLS:
        num = (m[c] * m["w"]).groupby(m["ym"]).sum(min_count=1)
        den = m.loc[m[c].notna()].groupby("ym")["w"].sum()
        out[c] = num / den.replace(0, np.nan)
    res = pd.DataFrame(out).reset_index()
    return res.rename(columns={c: f"{c}_w" for c in FEATURE_COLS})


def simple_monthly(station_monthly: pd.DataFrame) -> pd.DataFrame:
    """지점 단순평균. rev2(8개 시군 평균)와 비교하기 위한 대조군."""
    return (station_monthly.groupby("ym")[FEATURE_COLS].mean().reset_index()
            .rename(columns={c: f"{c}_m" for c in FEATURE_COLS}))


# 평지 / 준고랭지 구분. 8월 평균 실측(2015~2026)으로 확인한 서열:
#   장수 hot 16.3 vhot 4.2  <<  임실 19.1/8.2  <  나머지 평지 20.1~22.2 / 7.2~13.2
# 장수(해발 406m)만 확연히 다르고 임실(246m)이 중간이다.
UPLAND_STN = {"248"}                     # 장수 (무주도 이 지점을 대리로 씀)
MIDLAND_STN = {"244"}                    # 임실 (진안 대리)
LOWLAND_STN = {"140", "146", "172", "243", "245", "247", "254"}

SPREAD_COLS = ["hot_days", "vhot_days", "heat_deg", "trop_nights", "germ_block_days"]


def spread_monthly(station_monthly: pd.DataFrame) -> pd.DataFrame:
    """평지-준고랭지 고온 격차를 **변수로** 만든다.

    [왜 가중평균만으로는 부족한가]
    출하량 가중을 걸어도 8월 가중치가 익산 34% + 남원 31% = 평지 65%, 장수 11%다.
    그래서 가중평균은 단순평균 대비 hot_days가 0.21일밖에 안 움직인다(실측).
    장수의 vhot_days가 평지의 1/3(4.2 vs 13.2)이라는 정보가 평균에 녹아 사라진다.

    수급 관점에서 의미 있는 것은 평균 기온이 아니라 **격차**다. 평지가 고랭지보다
    훨씬 더운 해일수록 평지 시설이 먼저 멈추고 대체 압력이 커진다. 그래서
    lowland - upland 차이를 그대로 변수로 둔다.
    """
    s = station_monthly
    out = {}
    for c in SPREAD_COLS:
        low = s[s["stn"].isin(LOWLAND_STN)].groupby("ym")[c].mean()
        up = s[s["stn"].isin(UPLAND_STN)].groupby("ym")[c].mean()
        out[f"{c}_lowland"] = low
        out[f"{c}_upland"] = up
        out[f"{c}_spread"] = low - up
    return pd.DataFrame(out).reset_index()


# ═══════════════════════════════════════════════════════════════
# 4. 생리적 시차
# ═══════════════════════════════════════════════════════════════
# 상추는 파종~수확 4~6주(시설, 계절에 따라 30~60일). 그래서 당월 출하량을 좌우하는
# 기상은 당월이 아니라 직전 1~2개월이다. 다만 **경로마다 시차가 다르다.**
#
#   발아 저해(열휴면)  파종 시점  -> lag 2   종자가 아예 안 나거나 발아 지연
#   추대·고온장해      생육 중후기 -> lag 1   상품성 상실, 조기 수확/폐기
#   저온 피해          피해 후 재정식 -> lag 1  4~6주 뒤 출하 공백
#   광 부족            생육 전 기간 -> lag 0,1  생육 속도 저하(누적)
#   병해               발병~확산   -> lag 1
#
# rev2는 hot_days에만 lag1·lag2를 같이 넣어 두 경로를 한 덩어리로 취급했다.
# 여기서는 경로별로 나눠 붙인다. 어느 쪽이 실제로 기여하는지는 CV가 판정한다.
PHYSIO_LAGS: dict[str, tuple[int, ...]] = {
    "germ_block_days": (2,),
    "hot_days": (1, 2), "vhot_days": (1,), "heat_deg": (1,),
    "hot_streak3": (1,), "hot_streak_max": (1,),
    "trop_nights": (1,), "night_heat_deg": (1,),
    "cold_days": (1,), "vcold_days": (1,), "frost_deg": (1,),
    "sun_hours": (0, 1), "sun_ratio": (0, 1), "dark_days": (1,), "rad_mj": (1,),
    "rain_sum": (1,), "wet_days": (1,), "wet_streak_max": (1,),
    "humid_hot_days": (1,), "rh": (1,), "tavg": (0, 1), "dtr": (1,),
}


def add_physio_lags(df: pd.DataFrame, suffix: str) -> pd.DataFrame:
    """FEATURE_COLS의 {c}{suffix} 컬럼에 생리 근거 시차를 붙인다."""
    d = df.sort_values("ym").reset_index(drop=True)
    new = {}
    for base, lags in PHYSIO_LAGS.items():
        col = f"{base}{suffix}"
        if col not in d.columns:
            continue
        for L in lags:
            new[f"{col}_l{L}"] = d[col].shift(L) if L else d[col]
    # 한 번에 붙인다 — 하나씩 insert하면 프레임이 조각나 경고가 뜬다
    return pd.concat([d, pd.DataFrame(new, index=d.index)], axis=1)


# ═══════════════════════════════════════════════════════════════

def build(weights_mode: str = "climatology", train_end: str | None = None) -> pd.DataFrame:
    if not DAILY_PATH.exists():
        sys.exit(f"{DAILY_PATH.name} 없음 — 먼저 'fetch'를 실행")
    daily = pd.read_csv(DAILY_PATH, dtype={"stn": str})
    sm = build_monthly_by_station(daily)
    sm.to_csv(PROC / "agro_features_by_station.csv", index=False, encoding="utf-8-sig")

    out = simple_monthly(sm).merge(spread_monthly(sm), on="ym", how="left")
    if PRICE_DAILY.exists():
        w = build_weights(train_end)
        w.to_csv(WEIGHTS_PATH, index=False, encoding="utf-8-sig")
        out = out.merge(weighted_monthly(sm, w), on="ym", how="left")
        print(f"출하량 가중치: {WEIGHTS_PATH.name} "
              f"(mode={weights_mode}, train_end={train_end or '전체'})")
    else:
        print(f"[주의] {PRICE_DAILY.name} 없음 — 단순평균 피처만 만든다. "
              f"수집 완료 후 다시 실행할 것.")

    out = add_physio_lags(out, "_m")
    if any(c.endswith("_w") for c in out.columns):
        out = add_physio_lags(out, "_w")
    # 격차 변수의 시차. 추대·야간고온은 생육기(lag1), 발아저해는 파종기(lag2).
    lagged = {}
    for c in SPREAD_COLS:
        lags = (2,) if c == "germ_block_days" else (1,)
        for kind in ("lowland", "upland", "spread"):
            col = f"{c}_{kind}"
            if col in out.columns:
                for L in lags:
                    lagged[f"{col}_l{L}"] = out[col].shift(L)
    out = pd.concat([out, pd.DataFrame(lagged, index=out.index)], axis=1)
    out.to_csv(MONTHLY_PATH, index=False, encoding="utf-8-sig")
    print(f"저장: {MONTHLY_PATH.name} ({len(out)}행 x {len(out.columns)}열)")
    print(f"      지점별: agro_features_by_station.csv ({len(sm)}행)")
    return out


def report() -> None:
    if not MONTHLY_PATH.exists():
        sys.exit("먼저 build 실행")
    d = pd.read_csv(MONTHLY_PATH)
    d["ym"] = pd.PeriodIndex(d["ym"], freq="M")
    d["month"] = d["ym"].dt.month

    print("=" * 78)
    print("생리 피처 월별 프로파일 (단순평균 기준, 2015~)")
    print("=" * 78)
    show = ["hot_days", "vhot_days", "hot_streak3", "trop_nights", "germ_block_days",
            "cold_days", "vcold_days", "sun_hours", "sun_ratio", "dark_days",
            "humid_hot_days", "wet_days"]
    print(f"  {'피처':<16}" + "".join(f"{m:>6d}" for m in range(1, 13)))
    for c in show:
        col = f"{c}_m"
        if col not in d.columns:
            continue
        mm = d.groupby("month")[col].mean()
        fmt = "{:>6.2f}" if c == "sun_ratio" else "{:>6.1f}"
        print(f"  {c:<16}" + "".join(fmt.format(mm.get(m, np.nan)) for m in range(1, 13)))

    wcols = [c for c in d.columns if c.endswith("_w") and not c[:-2].endswith("_l")]
    if wcols:
        print()
        print("=" * 78)
        print("출하량 가중 vs 단순평균 — 차이가 클수록 주산지 이동이 큰 달")
        print("=" * 78)
        print(f"  {'피처':<16}" + "".join(f"{m:>6d}" for m in range(1, 13)))
        for c in ["hot_days", "vhot_days", "trop_nights", "cold_days"]:
            if f"{c}_w" not in d.columns:
                continue
            diff = d.groupby("month").apply(
                lambda x: x[f"{c}_w"].mean() - x[f"{c}_m"].mean(), include_groups=False)
            print(f"  {c:<16}" + "".join(f"{diff.get(m, np.nan):>+6.2f}"
                                         for m in range(1, 13)))
        print("  (음수 = 가중이 더 서늘 → 여름엔 서늘한 준고랭지로 출하가 옮겨간다는 뜻)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "build", "report"])
    ap.add_argument("--train-end", default=None,
                    help="가중치 계산에 쓸 학습구간 끝(YYYY-MM-DD). CV에서 fold마다 지정")
    a = ap.parse_args()
    if a.cmd == "fetch":
        fetch()
    elif a.cmd == "build":
        build(train_end=a.train_end)
    else:
        report()


if __name__ == "__main__":
    main()
