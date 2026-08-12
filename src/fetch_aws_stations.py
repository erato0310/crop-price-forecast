# -*- coding: utf-8 -*-
"""fetch_aws_stations.py — 방재기상관측(AWS) 일자료 수집. ASOS 기온계열 보강용.

────────────────────────────────────────────────────────────────
왜 필요한가 — 출하 1위 익산이 '해안 도시 군산'의 기상을 쓰고 있었다
────────────────────────────────────────────────────────────────
region_crosswalk.csv는 시군마다 가장 가까운 **ASOS** 지점을 붙여 놨는데, 전북엔
ASOS가 9곳뿐이라 상당수 시군이 성격이 다른 지점으로 대체돼 있었다. 그런데
**AWS까지 세면 전북에 45개 지점이 있고, 정작 그 시군에 자체 관측소가 있다.**

  시군      출하비중   현재 사용                 실제 자체 지점
  익산시     39.8%    군산 ASOS 140 (28m,해안)  익산 AWS 702 (11m, 신흥동)
  남원시     28.9%    남원 ASOS 247 (133m)      뱀사골 AWS 759 (479m, 산내면)
  완주군     15.9%    전주 ASOS 146             완주 AWS 734 (64m, 고산면)
  진안군      0.5%    임실 ASOS 244 (247m)      진안 AWS 703 (354m)
  김제시      1.6%    전주 ASOS 146             김제 AWS 737 (55m)
  무주군      0.04%   장수 ASOS 248             무주 AWS 701 (212m)

대체가 얼마나 어긋나는지는 이미 받아 둔 ASOS로 잴 수 있다. 8월 평균(2015~2026):

      군산 140:  hot 20.1일  vhot  7.2일  일조율 0.54   <- 지금 익산이 쓰는 값
      전주 146:  hot 22.2일  vhot 13.2일  일조율 0.49

**vhot(33C 이상) 7.2 vs 13.2 — 6일 차이다.** 익산은 전주 북쪽 내륙이라 군산보다
전주에 가까울 텐데, 지금은 극한 고온일수를 절반 가까이 과소평가하고 있을 수 있다.
출하량의 40%가 여기 걸려 있다.

남원은 반대 방향 문제다. ASOS 247은 남원 시내 도통동(133m)인데 남원 상추 산지는
동부 산간(운봉고원 450~500m)일 가능성이 크다. 운봉읍에는 관측소가 없고, 남원시
안에서 고도가 맞는 곳은 뱀사골 AWS 759(479m)뿐이다.

────────────────────────────────────────────────────────────────
주의 — AWS는 ASOS를 대체하지 않는다
────────────────────────────────────────────────────────────────
AWS 관측 항목은 기온·강수·풍향·풍속·습도·기압뿐이고 **일조시간이 없다.**
그래서 광 변수(sun_hours, sun_ratio, dark_days)는 계속 ASOS를 써야 한다.
이 모듈은 **기온 계열만 보강**하는 용도다.

또 AWS는 ASOS보다 관측 이력이 짧거나 결측이 많을 수 있다. 반드시 `--inspect`로
실제 커버리지를 확인한 뒤 채택할 것. 뱀사골(759)은 산지 계곡 지점이라 개활지인
운봉고원 농경지와 성격이 다를 수 있다는 점도 감안해야 한다.

────────────────────────────────────────────────────────────────
받는 방법 두 가지
────────────────────────────────────────────────────────────────
A) 기상청 API 허브 (권장 — 자동화됨)
   1. https://apihub.kma.go.kr 회원가입 (무료, 즉시 발급)
   2. 마이페이지에서 인증키 확인
   3. .env 에 추가:   KMA_APIHUB_KEY=발급받은키
   4. python fetch_aws_stations.py fetch

   * data.go.kr 키와 **다른 키**다. AWS 일자료는 data.go.kr에 API가 없다
     (1360000 아래 AWS 경로 4종 전부 NO_OPENAPI_SERVICE_ERROR, 실측 확인).

B) 기상자료개방포털 CSV 수동 다운로드
   https://data.kma.go.kr → 데이터 → 기상관측 → 지상 → 방재기상관측(AWS) → 자료
   지점·기간 선택 후 CSV 저장 → data/raw/aws_manual/ 에 넣고
   python fetch_aws_stations.py load-csv

[실행]
  python fetch_aws_stations.py inspect   # 응답 형식·컬럼 확인 (소량 호출)
  python fetch_aws_stations.py fetch     # 전 지점 수집
  python fetch_aws_stations.py load-csv  # 수동 CSV 취합
  python fetch_aws_stations.py compare   # ASOS 대체지점과 얼마나 다른지 비교
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")

APIHUB_KEY = os.getenv("KMA_APIHUB_KEY", "").strip()
APIHUB_URL = "https://apihub.kma.go.kr/api/typ01/url/sfc_aws_day.php"

RAW = _ROOT / "data" / "raw"
CSV_DIR = RAW / "aws_manual"
OUT_PATH = RAW / "daily_weather_aws.csv"
ASOS_PATH = RAW / "daily_weather_lettuce.csv"

START_YEAR = 2015
DELAY = 0.3

# 대상 AWS 지점. weather.go.kr 실시간 표(2026-08-11)에서 전북 45개 지점을 파싱해
# 고도·주소까지 확인한 목록 중, 출하 시군과 매칭되는 것만 골랐다.
AWS_STATIONS: dict[str, tuple[str, int, str]] = {
    # stn:   (이름,      고도m, 대체할 현행 ASOS)
    "702": ("익산",     11,  "140 군산"),
    "759": ("뱀사골",  479,  "247 남원"),
    "734": ("완주",     64,  "146 전주"),
    "703": ("진안",    354,  "244 임실"),
    "737": ("김제",     55,  "146 전주"),
    "701": ("무주",    212,  "248 장수"),
    # 참고용 대조군 — ASOS와 같은 자리에 있는 AWS가 있으면 두 관측망의 계통차를 잴 수 있다
    "379": ("번암(장수)", 292, "248 장수"),
    "758": ("동향(진안)", 321, "244 임실"),
}

# 시군 -> AWS 지점. lettuce_agro_features.COUNTY_STATION을 덮어쓸 후보 매핑.
# 채택 여부는 CV로 판정한다 — 여기서는 만들어만 둔다.
COUNTY_AWS_CANDIDATE = {
    "익산시": "702", "완주군": "734", "진안군": "703",
    "김제시": "737", "무주군": "701",
    # 남원은 시내(ASOS 247)와 산간(AWS 759)을 둘 다 두고 CV로 고르게 한다
    "남원시_산간": "759",
}


def _need_key() -> None:
    if not APIHUB_KEY:
        sys.exit(
            "KMA_APIHUB_KEY 없음.\n"
            "  1) https://apihub.kma.go.kr 가입(무료·즉시)\n"
            "  2) 마이페이지에서 인증키 복사\n"
            "  3) .env 에  KMA_APIHUB_KEY=키  추가\n"
            "  (data.go.kr 키와 다른 키다. AWS 일자료는 data.go.kr에 API가 없다.)"
        )


# sfc_aws_day.php는 **요소 1개씩** 준다. 2026-08-11 실측으로 유효한 코드는 셋뿐이다:
#   ta_max / ta_min / rn_day   (성공)
#   ta_avg, hm_avg, hm_min, ws_avg, si_sum, ss_day 는 전부 0행 (미제공)
# 즉 AWS로는 기온·강수만 보강할 수 있고 습도·일조는 계속 ASOS를 써야 한다.
ELEMENTS = {"ta_max": "tmax", "ta_min": "tmin", "rn_day": "rain"}


def _call(stn: str, tm1: str, tm2: str, obs: str, help_: int = 0) -> str:
    """(지점, 기간, 요소) 하나를 조회. tm1~tm2 범위 조회가 되는 것을 실측 확인했다."""
    params = {"tm1": tm1, "tm2": tm2, "obs": obs, "stn": stn, "disp": "0",
              "help": str(help_), "authKey": APIHUB_KEY}
    for attempt in range(4):
        try:
            r = requests.get(APIHUB_URL, params=params, timeout=90)
            if r.status_code == 401:
                sys.exit("인증키 거부(401). .env의 KMA_APIHUB_KEY 확인.")
            if r.status_code == 403:
                sys.exit("권한 없음(403). apihub에서 '지상 및 AWS 일통계 자료 조회' "
                         "활용신청이 됐는지, 마이페이지에 휴대전화가 등록됐는지 확인.")
            r.raise_for_status()
            r.encoding = "euc-kr"
            return r.text
        except SystemExit:
            raise
        except Exception:
            if attempt == 3:
                return ""
            time.sleep(2 * (attempt + 1))
    return ""


def _parse(text: str, value_name: str) -> pd.DataFrame:
    """응답 -> [date, stn, lon, lat, alt_m, <value_name>, stn_nm].

    형식(disp=0, 공백 구분):
        20250801   759 127.57826000  35.37162000  478.65     32.3 뱀사골
        TM         STN  LON           LAT          HT        VAL  지점명
    지점명에 공백·괄호가 들어가는 경우가 있어(예: '관악(레) *') maxsplit으로 자른다.
    """
    rows = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        f = ln.split(maxsplit=6)
        if len(f) < 6:
            continue
        rows.append({
            "date": f[0], "stn": f[1], "lon": f[2], "lat": f[3],
            "alt_m": f[4], value_name: f[5],
            "stn_nm": f[6].strip() if len(f) > 6 else "",
        })
    if not rows:
        return pd.DataFrame()
    d = pd.DataFrame(rows)
    d["date"] = pd.to_datetime(d["date"], format="%Y%m%d", errors="coerce")
    for c in ("lon", "lat", "alt_m", value_name):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    # apihub 결측 관행: -99, -999 등. 기온에 -50 미만은 없으므로 결측으로 본다.
    d.loc[d[value_name] <= -50, value_name] = pd.NA
    return d.dropna(subset=["date"])


def inspect() -> None:
    _need_key()
    print("요소 코드 가용성 — 뱀사골(759) 2025-08-01~03")
    for obs in ("ta_max", "ta_min", "rn_day", "ta_avg", "hm_avg", "ws_avg", "ss_day"):
        d = _parse(_call("759", "20250801", "20250803", obs), "v")
        mark = "OK " if len(d) else "-- "
        vals = list(d["v"]) if len(d) else []
        print(f"  {mark}{obs:8s} {len(d)}행  {vals}")
    print("\n원문 샘플 (ta_max):")
    print(_call("759", "20250801", "20250803", "ta_max")[:600])


def fetch() -> pd.DataFrame:
    _need_key()
    end_d = dt.date.today() - dt.timedelta(days=1)
    n_req = len(AWS_STATIONS) * len(ELEMENTS) * (end_d.year - START_YEAR + 1)
    print(f"AWS 일자료 | 지점 {len(AWS_STATIONS)}곳 x 요소 {len(ELEMENTS)}종 "
          f"| {START_YEAR}-01-01 ~ {end_d} | 예상 요청 {n_req}회")

    per_station: list[pd.DataFrame] = []
    for stn, (nm, alt, repl) in AWS_STATIONS.items():
        cols: list[pd.DataFrame] = []
        for obs, colname in ELEMENTS.items():
            parts = []
            for yr in range(START_YEAR, end_d.year + 1):
                s = dt.date(yr, 1, 1)
                e = min(dt.date(yr, 12, 31), end_d)
                if s > e:
                    continue
                d = _parse(_call(stn, s.strftime("%Y%m%d"), e.strftime("%Y%m%d"), obs),
                           colname)
                if not d.empty:
                    parts.append(d[["date", colname]])
                time.sleep(DELAY)
            if parts:
                cols.append(pd.concat(parts, ignore_index=True)
                            .drop_duplicates("date").set_index("date"))
        if not cols:
            print(f"  {stn} {nm:8s}: 자료 없음", flush=True)
            continue
        g = pd.concat(cols, axis=1).reset_index()
        g["stn"], g["stn_nm"], g["alt_m"] = stn, nm, alt
        # 평균기온은 API가 안 준다. (tmax+tmin)/2로 근사한다 — germ_block_days(일평균
        # 25C 이상 일수)를 만들려면 필요하고, 문턱 카운트에는 이 근사로 충분하다.
        # 다만 ASOS의 실측 tavg와는 다른 값이므로 컬럼명을 구분해 둔다.
        if "tmax" in g and "tmin" in g:
            g["tavg_approx"] = (g["tmax"] + g["tmin"]) / 2
        per_station.append(g)
        print(f"  {stn} {nm:8s} ({alt:>3}m, 대체대상 {repl}): {len(g):,}일", flush=True)

    if not per_station:
        sys.exit("한 건도 못 받았다 — inspect로 응답을 확인할 것")
    out = pd.concat(per_station, ignore_index=True).sort_values(["stn", "date"])
    out.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\n저장: {OUT_PATH.name} ({len(out):,}행)")
    _coverage(out)
    return out


def load_csv() -> pd.DataFrame:
    """기상자료개방포털에서 손으로 받은 CSV들을 취합한다(API 경로를 못 쓸 때)."""
    if not CSV_DIR.exists() or not list(CSV_DIR.glob("*.csv")):
        sys.exit(f"{CSV_DIR} 에 CSV가 없다.\n"
                 "  https://data.kma.go.kr → 데이터 → 기상관측 → 지상 →\n"
                 "  방재기상관측(AWS) → 자료 에서 지점·기간 선택 후 내려받아 넣을 것.")
    frames = []
    for p in sorted(CSV_DIR.glob("*.csv")):
        for enc in ("utf-8-sig", "cp949", "euc-kr"):
            try:
                d = pd.read_csv(p, encoding=enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            print(f"  [건너뜀] {p.name}: 인코딩 판별 실패")
            continue
        # 포털 CSV는 한글 헤더다 — 흔한 이름을 표준명으로 옮긴다
        ko = {"지점": "stn", "지점명": "stn_nm", "일시": "date",
              "평균기온(°C)": "tavg", "최고기온(°C)": "tmax", "최저기온(°C)": "tmin",
              "일강수량(mm)": "rain", "평균습도(%rh)": "rh", "평균 상대습도(%)": "rh"}
        d = d.rename(columns={k: v for k, v in ko.items() if k in d.columns})
        frames.append(d)
        print(f"  {p.name}: {len(d):,}행")
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out = out.dropna(subset=["date"]).drop_duplicates(["stn", "date"])
    out["stn"] = out["stn"].astype(str)
    out.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\n저장: {OUT_PATH.name} ({len(out):,}행)")
    _coverage(out)
    return out


def _coverage(d: pd.DataFrame) -> None:
    print("\n[커버리지] — 이력이 짧거나 결측이 많으면 채택하지 말 것")
    d = d.copy()
    d["date"] = pd.to_datetime(d["date"])
    for stn, g in d.groupby("stn"):
        cal = (g["date"].max() - g["date"].min()).days + 1
        miss = cal - len(g)
        na = {c: f"{g[c].isna().mean()*100:.0f}%"
              for c in ("tmax", "tmin", "rain") if c in g and g[c].isna().any()}
        print(f"  {stn} {str(g.get('stn_nm', pd.Series(['?'])).iloc[0]):8s} "
              f"{g['date'].min().date()}~{g['date'].max().date()}  "
              f"{len(g):,}일 (결일 {miss}, {miss/cal*100:.1f}%)"
              + (f"  결측 {na}" if na else ""))


def compare() -> None:
    """AWS 신규 지점 vs 현행 ASOS 대체지점 — 얼마나 어긋나 있었는지."""
    if not OUT_PATH.exists():
        sys.exit("먼저 fetch 또는 load-csv 실행")
    aws = pd.read_csv(OUT_PATH, dtype={"stn": str})
    asos = pd.read_csv(ASOS_PATH, dtype={"stn": str})
    for d in (aws, asos):
        d["date"] = pd.to_datetime(d["date"])

    def prof(d, stn):
        g = d[(d["stn"] == stn) & (d["date"].dt.month == 8)]
        if g.empty:
            return None
        return {
            "hot": (g["tmax"] >= 30).groupby(g["date"].dt.year).sum().mean(),
            "vhot": (g["tmax"] >= 33).groupby(g["date"].dt.year).sum().mean(),
            "trop": (g["tmin"] >= 20).groupby(g["date"].dt.year).sum().mean(),
        }

    print("8월 평균 — AWS 신규지점 vs 현행 ASOS 대체지점")
    print(f"  {'시군/지점':<22}{'hot':>7}{'vhot':>7}{'열대야':>8}")
    for stn, (nm, alt, repl) in AWS_STATIONS.items():
        a = prof(aws, stn)
        old_stn = repl.split()[0]
        b = prof(asos, old_stn)
        if not a:
            print(f"  {nm}({stn}) 자료 없음")
            continue
        print(f"  {nm+'('+stn+', '+str(alt)+'m)':<22}"
              f"{a['hot']:>7.1f}{a['vhot']:>7.1f}{a['trop']:>8.1f}")
        if b:
            print(f"  {'  ← 현행 '+repl:<22}{b['hot']:>7.1f}{b['vhot']:>7.1f}{b['trop']:>8.1f}"
                  f"   차이 {a['hot']-b['hot']:+.1f}/{a['vhot']-b['vhot']:+.1f}/"
                  f"{a['trop']-b['trop']:+.1f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["inspect", "fetch", "load-csv", "compare"])
    a = ap.parse_args()
    {"inspect": inspect, "fetch": fetch,
     "load-csv": load_csv, "compare": compare}[a.cmd]()


if __name__ == "__main__":
    main()
