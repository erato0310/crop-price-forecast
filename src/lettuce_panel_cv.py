# -*- coding: utf-8 -*-
"""lettuce_panel_cv.py — 시군 x 월 패널로 표본을 늘려 기상 효과를 다시 검정한다.

────────────────────────────────────────────────────────────────
왜 패널인가 — 표본 개수가 아니라 '식별'의 문제다
────────────────────────────────────────────────────────────────
lettuce_cv는 전북을 하나로 합쳐 월 103개를 쓴다. 그 구조에서는 기상이
**한 달에 값 하나**라 month_sin/cos와 거의 같은 정보가 되고, 실제로 어떤
기상 변수도 개선을 못 만들었다(1·4단계). 그런데 그게 "기상이 무관해서"인지
"식별이 안 돼서"인지는 그 자료로 가릴 수 없다. 여름이 8번뿐이었다.

패널은 이 문제를 푼다.

    같은 2023년 8월에도  장수 vhot 4일 / 전주 vhot 13일
    같은 시군 안에서도    2018년 8월 vs 2023년 8월이 다르다

즉 **(시군 x 연월) 두 방향 변이**가 생긴다. 월 고정효과를 넣어 "그 달 전국
공통 충격"을 통째로 빼내고도, 시군 간 기상 차이로 가격 차이를 설명할 수
있는지 볼 수 있다. 이건 집계 시계열로는 원리적으로 불가능한 검정이다.

katSale은 2018-01이 시작점이라(2017년 이전 전 작물·전 시장 0건 실측) 시간
축으로는 더 못 늘린다. 그래서 이 방향이 남은 유일한 확장이다.

────────────────────────────────────────────────────────────────
설계
────────────────────────────────────────────────────────────────
타깃    시군 x 월 주력 상추 log(원/kg)
피처    시군 자체 가격시차 + 계절 + (시군 고정효과) + 그 시군 기상
검증    연도별 walk-forward. 학습구간은 항상 검증연도 이전.
        하이퍼파라미터는 학습구간 내부에서만 재탐색(lettuce_cv.tune과 동일 규약)

**월 고정효과 판정**이 핵심이다. 월 더미를 넣으면 "그 달 전국 공통"이
흡수되므로, 그 뒤에도 기상이 기여하면 그건 진짜 지역 기상 효과다.

[실행]
  python lettuce_panel_cv.py build     # 패널 규모 확인
  python lettuce_panel_cv.py compare   # 기상 유무 비교 (본론)
  python lettuce_panel_cv.py within    # 월 고정효과 넣고 재검정
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import lettuce_cv as CV

_ROOT = Path(__file__).resolve().parent.parent
RAW = _ROOT / "data" / "raw"
OUT = _ROOT / "outputs"

PRICE = RAW / "lettuce_daily_by_county.csv"
ASOS = RAW / "daily_weather_lettuce.csv"
AWS = RAW / "daily_weather_aws.csv"

MIN_MONTHS = 60          # 이보다 얇은 시군은 제외(가격시차가 성립 안 함)
MIN_OBS_MONTH = 5        # 그 달 거래 레코드 최소치
TEST_YEARS = [2020, 2021, 2022, 2023, 2024, 2025]
HOLDOUT = 2026

# 시군 -> (기온 지점, 광·습도 ASOS). 기온은 AWS 자체관측소 우선
# (test_aws_station_swap 결과 집계 수준에선 차이가 없었지만, 패널에선
#  시군 간 변이가 핵심이므로 정확한 쪽을 쓴다).
STN = {
    "익산시": ("702", "140"), "남원시": ("247", "247"), "완주군": ("734", "146"),
    "장수군": ("248", "248"), "전주시": ("146", "146"), "김제시": ("737", "146"),
    "순창군": ("254", "254"), "진안군": ("703", "244"), "고창군": ("172", "172"),
    "정읍시": ("245", "245"), "부안군": ("243", "243"), "무주군": ("701", "248"),
    "임실군": ("244", "244"), "군산시": ("140", "140"),
}


def _wavg(g, p, q):
    x = g[[p, q]].dropna()
    t = x[q].sum()
    return (x[p] * x[q]).sum() / t if t else np.nan


def weather_monthly() -> pd.DataFrame:
    """(시군, 월) 기상. 기온계열은 AWS/ASOS 중 매핑된 지점, 광은 항상 ASOS."""
    a = pd.read_csv(ASOS, dtype={"stn": str})
    a["date"] = pd.to_datetime(a["date"])
    w = pd.read_csv(AWS, dtype={"stn": str})
    w["date"] = pd.to_datetime(w["date"])

    def temp_feats(stn):
        src, tc = w[w["stn"] == stn], "tavg_approx"
        if src.empty:
            src, tc = a[a["stn"] == stn], "tavg"
        if src.empty:
            return None
        d = src.copy()
        d["ym"] = d["date"].dt.to_period("M")
        g = d.groupby("ym")
        return pd.DataFrame({
            "hot_days": g.apply(lambda x: (x["tmax"] >= 30).sum(), include_groups=False),
            "vhot_days": g.apply(lambda x: (x["tmax"] >= 33).sum(), include_groups=False),
            "trop_nights": g.apply(lambda x: (x["tmin"] >= 20).sum(), include_groups=False),
            "germ_block": g.apply(lambda x: (x[tc] >= 25).sum(), include_groups=False),
            "cold_days": g.apply(lambda x: (x["tmin"] <= 0).sum(), include_groups=False),
            "tavg": g[tc].mean(),
            "rain_sum": g["rain"].sum(),
        }).reset_index()

    def light_feats(stn):
        d = a[a["stn"] == stn].copy()
        if d.empty:
            return None
        d["ym"] = d["date"].dt.to_period("M")
        g = d.groupby("ym")
        o = pd.DataFrame({
            "sun_hours": g["sun_hr"].sum(),
            "sun_poss": g["sun_possible"].sum(),
            "dark_days": g.apply(lambda x: (x["sun_hr"] <= 3).sum(), include_groups=False),
        }).reset_index()
        o["sun_ratio"] = o["sun_hours"] / o["sun_poss"].replace(0, np.nan)
        return o.drop(columns=["sun_poss"])

    tcache, lcache, rows = {}, {}, []
    for county, (ts, ls) in STN.items():
        if ts not in tcache:
            tcache[ts] = temp_feats(ts)
        if ls not in lcache:
            lcache[ls] = light_feats(ls)
        t, l = tcache[ts], lcache[ls]
        if t is None:
            continue
        m = t if l is None else t.merge(l, on="ym", how="left")
        m = m.copy()
        m["county"] = county
        rows.append(m)
    return pd.concat(rows, ignore_index=True)


WX = ["hot_days", "vhot_days", "trop_nights", "germ_block", "cold_days",
      "tavg", "rain_sum", "sun_hours", "sun_ratio", "dark_days"]


def build_panel() -> pd.DataFrame:
    d = pd.read_csv(PRICE)
    d["date"] = pd.to_datetime(d["date"])
    d["ym"] = d["date"].dt.to_period("M")
    rows = []
    for (ym, c), g in d.groupby(["ym", "county"]):
        n = int(g["n_obs"].sum())
        if n < MIN_OBS_MONTH:
            continue
        rows.append({"ym": ym, "county": c, "price": _wavg(g, "price_kg", "qty_kg"),
                     "qty": g["qty_kg"].sum(min_count=1), "n_obs": n,
                     "n_days": g["date"].nunique()})
    p = pd.DataFrame(rows).dropna(subset=["price"])
    keep = p.groupby("county")["price"].count()
    p = p[p["county"].isin(keep[keep >= MIN_MONTHS].index)].copy()
    cur = pd.Timestamp.today().to_period("M")
    p = p[p["ym"] != cur]

    p = p.merge(weather_monthly(), on=["ym", "county"], how="left")
    p = p.sort_values(["county", "ym"]).reset_index(drop=True)
    p["month"] = p["ym"].dt.month
    p["year"] = p["ym"].dt.year
    p["month_sin"] = np.sin(2 * np.pi * p["month"] / 12)
    p["month_cos"] = np.cos(2 * np.pi * p["month"] / 12)

    h = CV.HORIZON
    g = p.groupby("county")
    p["lag_h"] = g["price"].shift(h)
    p["lag12"] = g["price"].shift(12)
    p["roll3"] = g["price"].shift(h).rolling(3).mean().reset_index(level=0, drop=True)
    # 기상은 생리 시차 — 추대/광은 l1, 발아저해는 l2
    for c in WX:
        p[c + "_l1"] = g[c].shift(1)
    p["germ_block_l2"] = g["germ_block"].shift(2)
    return p


CORE = ["month_sin", "month_cos", "lag_h", "lag12", "roll3"]
WX_L1 = [c + "_l1" for c in ["vhot_days", "trop_nights", "dark_days", "sun_ratio",
                             "cold_days", "rain_sum"]] + ["germ_block_l2"]

SETS = {
    "가격시차": CORE,
    "+고온": CORE + ["vhot_days_l1", "germ_block_l2"],
    "+광": CORE + ["dark_days_l1", "sun_ratio_l1"],
    "+기상전부": CORE + WX_L1,
}


def _dummies(p: pd.DataFrame, county_fe: bool, month_fe: bool) -> pd.DataFrame:
    parts = []
    if county_fe:
        parts.append(pd.get_dummies(p["county"], prefix="c", dtype=float))
    if month_fe:
        parts.append(pd.get_dummies(p["month"], prefix="m", dtype=float))
    return pd.concat(parts, axis=1) if parts else pd.DataFrame(index=p.index)


def run(p: pd.DataFrame, cols: list[str], county_fe=True, month_fe=False,
        years=None) -> pd.DataFrame:
    years = years or TEST_YEARS
    D = _dummies(p, county_fe, month_fe)
    X = pd.concat([p[cols], D], axis=1)
    feat = list(X.columns)
    X = X.assign(price=p["price"].values, year=p["year"].values,
                 county=p["county"].values, ym=p["ym"].values,
                 month=p["month"].values)
    rows = []
    for y in years:
        tr = X[X["year"] < y].dropna(subset=["price"])
        te = X[X["year"] == y].dropna(subset=["price"])
        if len(tr) < 200 or te.empty:
            continue
        med = tr[feat].median(numeric_only=True)
        best, bs = 1.0, np.inf
        inner = [yy for yy in sorted(tr["year"].unique())[2:]]
        for al in [0.1, 1.0, 10.0, 50.0]:
            e = []
            for yy in inner:
                it, iv = tr[tr["year"] < yy], tr[tr["year"] == yy]
                if len(it) < 200 or iv.empty:
                    continue
                mo = make_pipeline(StandardScaler(), Ridge(alpha=al)).fit(
                    it[feat].fillna(med), np.log(it["price"]))
                e.append(CV.mape(iv["price"].values,
                                 np.exp(mo.predict(iv[feat].fillna(med)))))
            if e and np.mean(e) < bs:
                bs, best = float(np.mean(e)), al
        mo = make_pipeline(StandardScaler(), Ridge(alpha=best)).fit(
            tr[feat].fillna(med), np.log(tr["price"]))
        pred = np.exp(mo.predict(te[feat].fillna(med)))
        pred = np.clip(pred, tr["price"].min() / 3, tr["price"].max() * 3)
        # 베이스라인: 시군별 달력월 평균
        key = tr.groupby(["county", "month"])["price"].mean()
        gl = tr.groupby("month")["price"].mean()
        base = np.array([key.get((c, m), gl.get(m, tr["price"].mean()))
                         for c, m in zip(te["county"], te["month"])])
        rows.append({"year": y, "n_train": len(tr), "n_test": len(te), "alpha": best,
                     "baseline": CV.mape(te["price"].values, base),
                     "model": CV.mape(te["price"].values, pred)})
    return pd.DataFrame(rows)


def cmd_build(p):
    print("=" * 76)
    print("패널 규모")
    print("=" * 76)
    print(f"  관측 {len(p):,}개  (시군 {p['county'].nunique()}개 x 월 "
          f"{p['ym'].nunique()}개)")
    print(f"  구간 {p['ym'].min()} ~ {p['ym'].max()}")
    print(f"  집계 시계열 대비 {len(p)/p['ym'].nunique():.1f}배\n")
    print(f"  {'시군':<8}{'월수':>5}{'평균원/kg':>11}{'8월 vhot 평균':>14}")
    for c, g in p.groupby("county"):
        v = g[g["month"] == 8]["vhot_days"].mean()
        print(f"  {c:<8}{len(g):>5}{g['price'].mean():>11,.0f}{v:>13.1f}일")
    a8 = p[p["month"] == 8].groupby("year")["vhot_days"]
    print(f"\n  같은 8월 안에서도 시군 간 vhot 편차: 연평균 "
          f"{a8.std().mean():.1f}일 (최대 {a8.max().max():.0f} / 최소 {a8.min().min():.0f})")
    print("  -> 이 횡단면 변이가 집계 시계열에는 없던 식별 정보다")


def cmd_compare(p):
    for mfe, lbl in [(False, "월 고정효과 없음 (계절은 sin/cos)"),
                     (True, "월 고정효과 포함 — 그 달 공통충격 제거")]:
        print("=" * 76)
        print(f"{lbl}")
        print("=" * 76)
        print(f"  {'피처집합':<12}{'모델':>9}{'베이스':>9}{'개선':>9}{'승':>6}"
              f"{'표본':>8}  fold별")
        for name, cols in SETS.items():
            r = run(p, cols, county_fe=True, month_fe=mfe)
            if r.empty:
                continue
            w = int((r["model"] < r["baseline"]).sum())
            print(f"  {name:<12}{r['model'].mean():>8.2f}%{r['baseline'].mean():>8.2f}%"
                  f"{r['baseline'].mean()-r['model'].mean():>+8.2f}%{w:>4}/{len(r)}"
                  f"{r['n_train'].iloc[-1]:>8,}  "
                  + " ".join(f"{x:.0f}" for x in r["model"]))
        print()


def cmd_within(p):
    """홀드아웃까지 포함한 최종 확인."""
    print("=" * 76)
    print(f"독립 홀드아웃 {HOLDOUT} — 패널")
    print("=" * 76)
    for mfe in (False, True):
        print(f"  [월 고정효과 {'있음' if mfe else '없음'}]")
        for name, cols in SETS.items():
            r = run(p, cols, county_fe=True, month_fe=mfe, years=[HOLDOUT])
            if r.empty:
                continue
            x = r.iloc[0]
            print(f"    {name:<12}{x['model']:>8.2f}%  (기준 {x['baseline']:.2f}%, "
                  f"n_test={int(x['n_test'])})")
        print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "compare", "within"])
    a = ap.parse_args()
    p = build_panel()
    {"build": cmd_build, "compare": cmd_compare, "within": cmd_within}[a.cmd](p)


if __name__ == "__main__":
    main()
