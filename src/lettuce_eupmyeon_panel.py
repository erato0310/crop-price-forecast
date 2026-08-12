# -*- coding: utf-8 -*-
"""lettuce_eupmyeon_panel.py — 산지를 읍면까지 쪼갠 패널.

────────────────────────────────────────────────────────────────
왜 읍면인가
────────────────────────────────────────────────────────────────
시군은 이질적인 것을 섞는다. 남원시 하나에

    금지면  해발 40~60m  섬진강변 저지대   출하 51.5%
    아영면  해발 450m    운봉고원          출하  4.4%
    운봉읍  해발 500m                      출하  0.3%

가 같이 들어간다. 이 둘의 8월 고온일수는 5~6일 차이인데, 시군 평균을 내면
사라진다. **집계 단위가 신호를 지우고 있었다.**

읍면으로 내리면 두 가지를 얻는다.
  1. 횡단면 단위 12개 -> 43개, 패널 1,210행 -> 3,955행 (3.3배)
  2. **읍면별로 고도에 맞는 기상 지점을 붙일 수 있다** — 이게 핵심이다.
     지금은 아영면·운봉읍이 남원 시내(133m) 기상을 쓰고 있다.

────────────────────────────────────────────────────────────────
한계 (반드시 감안)
────────────────────────────────────────────────────────────────
- 산지 표기의 70%만 읍면까지 특정된다. 나머지는 '(미상)' 단위로 남긴다.
  익산은 특정률이 낮아 '익산시·(미상)'이 최대 단위(41,795t)다.
- `plor_nm`은 **출하자 주소**지 경작지가 아니다. 공동출하는 사무소 주소로 잡힌다.
- 읍면당 월 레코드가 54건(시군 148건)으로 얇아져 월평균 잡음이 커진다.
- 기상 관측소는 시군 단위가 상한이다. 읍면에 '맞는' 지점을 고를 뿐,
  읍면 기상을 실제로 관측하는 것은 아니다.

[실행]
  python lettuce_eupmyeon_panel.py build     # 패널 구성·점검
  python lettuce_eupmyeon_panel.py compare   # 시군 패널 대비 성능
  python lettuce_eupmyeon_panel.py weather   # 고도 맞춤 기상의 효과
"""
from __future__ import annotations

import argparse
import re
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")

from scrape_lettuce_daily import MAIN_VARIETIES

_ROOT = Path(__file__).resolve().parent.parent
RAW = _ROOT / "data" / "raw"
OUT = _ROOT / "outputs"

SRC = RAW / "lettuce_daily_raw.csv"
ASOS = RAW / "daily_weather_lettuce.csv"
AWS = RAW / "daily_weather_aws.csv"

MIN_MONTHS = 60
TEST_YEARS = [2020, 2021, 2022, 2023, 2024, 2025]
HOLDOUT_YEAR = 2026
MIN_TRAIN = 200
ALPHAS = [0.1, 1.0, 3.0, 10.0, 30.0]

_EUP = re.compile(r"(?:시|군)\s+([가-힣]+(?:읍|면|동))(?:\s|$)")

# 읍면 -> 기상지점. 고도·위치를 맞춰 배정한다.
# 미배정 읍면은 그 시군의 기본 지점을 쓴다(COUNTY_DEFAULT).
# 근거: weather.go.kr 전북 AWS 45지점 고도 실측(fetch_aws_stations 주석 참고)
#   장수 248 = 407m, 진안 703 = 354m, 임실 244 = 247m, 무주 701 = 212m
#   전주 146 = 60m, 익산 702 = 11m, 완주 734 = 64m, 남원 247 = 133m
EUP_STATION: dict[str, str] = {
    # 남원 동부 산간 (운봉고원·지리산 자락) -> 장수(407m)가 고도상 가장 가깝다
    "남원시·운봉읍": "248", "남원시·인월면": "248", "남원시·아영면": "248",
    "남원시·산내면": "248", "남원시·산동면": "248",
    # 남원 서남부 저지대 (섬진강변)
    "남원시·금지면": "247", "남원시·수지면": "247", "남원시·송동면": "247",
    "남원시·주생면": "247", "남원시·대강면": "247",
    # 진안·무주 산간
    "진안군·동향면": "703", "진안군·정천면": "703", "진안군·부귀면": "703",
    # 장수
    "장수군·번암면": "248", "장수군·계남면": "248", "장수군·장수읍": "248",
}
COUNTY_DEFAULT: dict[str, str] = {
    "익산시": "702", "남원시": "247", "완주군": "734", "장수군": "248",
    "전주시": "146", "김제시": "737", "순창군": "254", "진안군": "703",
    "고창군": "172", "정읍시": "245", "부안군": "243", "무주군": "701",
    "임실군": "244", "군산시": "140",
}
# 대조군: 읍면 무시하고 시군 기본 지점만 (기존 방식)
BASELINE_STATION = dict(COUNTY_DEFAULT)


def _wavg(g, p="price_kg", q="qty_kg"):
    x = g[[p, q]].dropna()
    t = x[q].sum()
    return (x[p] * x[q]).sum() / t if t else np.nan


def load_units() -> pd.DataFrame:
    d = pd.read_csv(SRC, dtype={"market_cd": str}, low_memory=False)
    d = d[d["variety"].isin(MAIN_VARIETIES)]
    d["date"] = pd.to_datetime(d["date"], format="mixed")
    d["ym"] = d["date"].dt.to_period("M")
    j = d[d["county"].notna()].copy()
    j["eup"] = j["plor_nm"].str.extract(_EUP)
    j["unit"] = j["county"] + "·" + j["eup"].fillna("(미상)")
    rows = []
    for (ym, u), g in j.groupby(["ym", "unit"]):
        w = g[["price_kg", "qty_kg"]].dropna()
        t = w["qty_kg"].sum()
        if t <= 0:
            continue
        rows.append({"ym": ym, "unit": u, "county": g["county"].iloc[0],
                     "price": (w["price_kg"] * w["qty_kg"]).sum() / t,
                     "qty": t, "n_obs": len(g), "n_days": g["date"].nunique(),
                     "n_markets": g["market_cd"].nunique()})
    p = pd.DataFrame(rows)
    cnt = p.groupby("unit").size()
    keep = cnt[cnt >= MIN_MONTHS].index
    return p[p["unit"].isin(keep)].sort_values(["unit", "ym"]).reset_index(drop=True)


def weather_monthly() -> pd.DataFrame:
    """지점별 월 기상. ASOS(광·습도 포함) + AWS(기온 정밀)를 지점코드로 합친다."""
    a = pd.read_csv(ASOS, dtype={"stn": str})
    a["date"] = pd.to_datetime(a["date"])
    a["src"] = "asos"
    w = pd.read_csv(AWS, dtype={"stn": str})
    w["date"] = pd.to_datetime(w["date"])
    w = w.rename(columns={"tavg_approx": "tavg"})
    w["sun_hr"] = np.nan
    w["src"] = "aws"
    cols = ["stn", "date", "tmax", "tmin", "tavg", "rain", "sun_hr", "src"]
    d = pd.concat([a.reindex(columns=cols), w.reindex(columns=cols)],
                  ignore_index=True)
    # 같은 지점번호가 양쪽에 있으면 AWS(기온) 우선, 광은 ASOS만 있으므로 자동 보완
    d = d.sort_values("src").drop_duplicates(["stn", "date"], keep="last")
    d["ym"] = d["date"].dt.to_period("M")
    d["_vhot"] = d["tmax"] >= 33
    d["_hot"] = d["tmax"] >= 30
    d["_germ"] = d["tavg"] >= 25
    d["_dark"] = d["sun_hr"] <= 3.0
    g = d.groupby(["stn", "ym"]).agg(
        vhot=("_vhot", "sum"), hot=("_hot", "sum"), germ=("_germ", "sum"),
        dark=("_dark", "sum"), sun=("sun_hr", "sum"), tavg=("tavg", "mean"),
        rain=("rain", "sum"),
    ).reset_index()
    return g


def build_panel(station_map: str = "eup") -> pd.DataFrame:
    u = load_units()
    wm = weather_monthly()
    if station_map == "eup":
        u["stn"] = u["unit"].map(EUP_STATION).fillna(u["county"].map(COUNTY_DEFAULT))
    else:
        u["stn"] = u["county"].map(BASELINE_STATION)
    p = u.merge(wm, on=["stn", "ym"], how="left")

    p["year"] = p["ym"].dt.year
    p["month"] = p["ym"].dt.month
    p["month_sin"] = np.sin(2 * np.pi * p["month"] / 12)
    p["month_cos"] = np.cos(2 * np.pi * p["month"] / 12)
    g = p.sort_values(["unit", "ym"]).groupby("unit")
    p = p.sort_values(["unit", "ym"]).reset_index(drop=True)
    g = p.groupby("unit")
    p["lag1"] = g["price"].shift(1)
    p["lag12"] = g["price"].shift(12)
    p["roll3"] = g["price"].shift(1).rolling(3).mean().reset_index(level=0, drop=True)
    p["qty_l"] = np.log(g["qty"].shift(1).replace(0, np.nan))
    for c in ("vhot", "hot", "germ", "dark", "sun"):
        p[f"{c}_l1"] = g[c].shift(1)
        p[f"{c}_l2"] = g[c].shift(2)
    return p


CORE = ["month_sin", "month_cos", "lag1", "lag12", "roll3"]
WEATHER = ["vhot_l1", "germ_l2", "dark_l1", "sun_l1"]


def mape(a, f):
    a, f = np.asarray(a, float), np.asarray(f, float)
    m = np.isfinite(a) & np.isfinite(f) & (a != 0)
    return float(np.mean(np.abs((a[m] - f[m]) / a[m])) * 100) if m.any() else np.nan


def run_panel(p, cols, unit_fe=True, month_fe=False, years=None) -> pd.DataFrame:
    years = years or TEST_YEARS
    rows = []
    for y in years:
        tr = p[p["year"] < y].dropna(subset=["price"])
        te = p[p["year"] == y].dropna(subset=["price"])
        if len(tr) < MIN_TRAIN or te.empty:
            continue
        X_cols = list(cols)
        tr, te = tr.copy(), te.copy()
        if unit_fe:
            d = pd.get_dummies(pd.concat([tr["unit"], te["unit"]]), prefix="u")
            tr = pd.concat([tr, d.iloc[: len(tr)].set_index(tr.index)], axis=1)
            te = pd.concat([te, d.iloc[len(tr):].set_index(te.index)], axis=1)
            X_cols += list(d.columns)
        if month_fe:
            d = pd.get_dummies(pd.concat([tr["month"], te["month"]]), prefix="m")
            tr = pd.concat([tr, d.iloc[: len(tr)].set_index(tr.index)], axis=1)
            te = pd.concat([te, d.iloc[len(tr):].set_index(te.index)], axis=1)
            X_cols += list(d.columns)
        med = tr[X_cols].median(numeric_only=True)
        Xtr = tr[X_cols].fillna(med).astype(float)
        ytr = np.log(tr["price"])
        best, best_e = None, np.inf
        for al in ALPHAS:
            m = make_pipeline(StandardScaler(), Ridge(alpha=al)).fit(Xtr, ytr)
            e = float(np.mean((m.predict(Xtr) - ytr) ** 2))
            if e < best_e:
                best_e, best = e, (al, m)
        al, mod = best
        pr = np.exp(mod.predict(te[X_cols].fillna(med).astype(float)))
        pr = pr * float(np.mean(np.exp(ytr - mod.predict(Xtr))))     # 스미어링
        # 단위별 계절평균 베이스라인
        bavg = tr.groupby(["unit", "month"])["price"].mean()
        gavg = tr.groupby("month")["price"].mean()
        base = np.array([bavg.get((u_, m_), gavg.get(m_, tr["price"].mean()))
                         for u_, m_ in zip(te["unit"], te["month"])])
        rows.append({"year": y, "n_train": len(tr), "n_test": len(te),
                     "alpha": al, "baseline": mape(te["price"].values, base),
                     "model": mape(te["price"].values, pr)})
    return pd.DataFrame(rows)


def cmd_build() -> None:
    p = build_panel("eup")
    print("=" * 78)
    print("읍면 패널 점검")
    print("=" * 78)
    print(f"  단위 {p['unit'].nunique()}개, 관측 {len(p):,}행, "
          f"{p['ym'].min()} ~ {p['ym'].max()}")
    print(f"  단위당 월 레코드 중앙 {p['n_obs'].median():.0f}건, "
          f"거래일 중앙 {p['n_days'].median():.0f}일")
    print()
    print("  고도 맞춤 기상지점이 배정된 읍면")
    m = p[p["unit"].isin(EUP_STATION)].groupby("unit").agg(
        지점=("stn", "first"), 월수=("price", "size"),
        평균가=("price", "mean"), 물량t=("qty", lambda x: x.sum() / 1000))
    for u_, r in m.sort_values("물량t", ascending=False).iterrows():
        base_stn = COUNTY_DEFAULT.get(u_.split("·")[0], "?")
        tag = "" if r["지점"] == base_stn else f"  (기존 {base_stn} -> {r['지점']})"
        print(f"    {u_:<14}{int(r['월수']):>4}개월{r['평균가']:>8,.0f}원"
              f"{r['물량t']:>9,.0f}t{tag}")
    print()
    print("  물량 상위 12 단위")
    g = p.groupby("unit").agg(월수=("price", "size"), 평균가=("price", "mean"),
                              물량t=("qty", lambda x: x.sum() / 1000)).sort_values(
        "물량t", ascending=False)
    print(g.head(12).round(0).to_string())


def cmd_compare() -> None:
    print("=" * 78)
    print("집계 단위 비교 — 시군 vs 읍면")
    print("=" * 78)
    import lettuce_panel_cv as PN
    try:
        sg = PN.build_panel()
        r_sg = PN.run(sg, PN.CORE, county_fe=True)
        print(f"  시군 패널   단위 {sg['county'].nunique()}개 / {len(sg):,}행")
        print(f"    가격시차   모델 {r_sg['model'].mean():.2f}%  "
              f"베이스 {r_sg['baseline'].mean():.2f}%  "
              f"개선 {r_sg['baseline'].mean()-r_sg['model'].mean():+.2f}%p")
    except Exception as e:
        print(f"  시군 패널 실행 실패: {str(e)[:60]}")
    print()
    p = build_panel("eup")
    print(f"  읍면 패널   단위 {p['unit'].nunique()}개 / {len(p):,}행")
    print(f"  {'구성':<22}{'모델':>9}{'베이스':>9}{'개선':>9}{'승':>6}")
    for lbl, cols, mfe in [("가격시차", CORE, False),
                           ("+기상(고도맞춤)", CORE + WEATHER, False),
                           ("[상한] 월고정효과", CORE, True)]:
        r = run_panel(p, cols, unit_fe=True, month_fe=mfe)
        if r.empty:
            continue
        w = int((r["model"] < r["baseline"]).sum())
        print(f"  {lbl:<22}{r['model'].mean():>8.2f}%{r['baseline'].mean():>8.2f}%"
              f"{r['baseline'].mean()-r['model'].mean():>+8.2f}%{w:>4}/{len(r)}")


def cmd_weather() -> None:
    print("=" * 78)
    print("고도 맞춤 기상의 효과 — 같은 읍면 패널, 지점 배정만 교체")
    print("=" * 78)
    print("  기존: 읍면 무시, 시군 대표지점 하나")
    print("  맞춤: 남원 산간(운봉·인월·아영·산내) -> 장수(407m) 등 고도 대응")
    print()
    print(f"  {'지점배정':<14}{'가격시차':>10}{'+기상':>10}{'기상 기여':>11}")
    for tag, key in [("기존(시군)", "county"), ("고도맞춤(읍면)", "eup")]:
        p = build_panel(key)
        r0 = run_panel(p, CORE, unit_fe=True)
        r1 = run_panel(p, CORE + WEATHER, unit_fe=True)
        print(f"  {tag:<14}{r0['model'].mean():>9.2f}%{r1['model'].mean():>9.2f}%"
              f"{r1['model'].mean()-r0['model'].mean():>+10.2f}%p")
    print()
    print("  기상 기여가 음수로 커지면 '지점을 제대로 붙이니 기상이 산다'는 뜻이다.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "compare", "weather"])
    a = ap.parse_args()
    {"build": cmd_build, "compare": cmd_compare, "weather": cmd_weather}[a.cmd]()


if __name__ == "__main__":
    main()
