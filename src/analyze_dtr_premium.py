# -*- coding: utf-8 -*-
"""analyze_dtr_premium.py — 일교차·열대야로 지역 가격차를 설명할 수 있는가.

────────────────────────────────────────────────────────────────
가설
────────────────────────────────────────────────────────────────
엽채류 생리에서 **일교차가 크면 잎이 두꺼워진다.** 낮에 광합성으로 만든
동화산물을 밤에 호흡으로 덜 태우기 때문이다(야간 기온이 높을수록 소모가 크다).
잎이 두꺼우면 조직이 치밀하고 저장성이 좋아 상품성이 올라간다.

그렇다면 **일교차가 큰 지역의 상추가 더 비싸게 팔려야 한다.**

여름이 관건이다. 저지대는 여름에 일교차가 줄고 열대야(일최저 25℃ 이상)가
오지만, 고랭지는 여름에도 일교차가 유지되고 열대야가 거의 없다.
그래서 이 가설이 맞다면 **지역 간 가격차가 여름에 벌어지고 겨울에 좁아져야 한다.**

이건 반증 가능한 예측이다 — 겨울에도 격차가 같다면 일교차가 아니라 다른 것이
원인이라는 뜻이다. 그래서 계절을 통제해 없애지 않고 **계절별로 나눠서** 본다.

────────────────────────────────────────────────────────────────
어떻게 재는가
────────────────────────────────────────────────────────────────
지역 가격차를 그냥 평균으로 비교하면 안 된다. 시군마다 파는 품종도, 내는
시장도 다르기 때문이다. 그래서 **같은 주 · 같은 품종 · 같은 시장** 안에서만
견준다(analyze_market_choice 와 같은 대응짝 설계).

    상대값 = 그 셀(주×품종×시장)의 평균 대비 그 시군이 받은 값의 비

1.05면 같은 조건에서 5% 더 받았다는 뜻이다.

────────────────────────────────────────────────────────────────
검정 규칙
────────────────────────────────────────────────────────────────
- 상관 하나로 인과를 주장하지 않는다. 시군이 14개뿐이라 표본이 작다.
- 부트스트랩 95% 구간이 0을 포함하면 **판정불가**로 적는다.
- 고도와 일교차는 강하게 얽혀 있다. 어느 쪽이 설명하는지 못 가리면
  못 가린다고 적는다.

[실행] python analyze_dtr_premium.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "outputs"

# 시군 -> 기상 지점. **자체 지점을 우선한다** — 일교차는 계곡·산지에 따라
# 국지적으로 갈려서 옆 시군 값으로 대신하면 가설 자체가 흐려진다.
# (lettuce_agro_features.COUNTY_STATION 은 ASOS 9지점만 써서 익산·진안·무주·
#  완주·김제를 옆 시군으로 대체하고 있다. 여기서는 AWS 자체 지점을 쓴다.)
# **사람 판단이 들어간 목록이다.** 근거를 옆에 적어 둔다.
COUNTY_STN: dict[str, tuple[list[str], str]] = {
    "진안군": (["703", "758"], "AWS 자체 2지점(진안 354m·동향 321m) 평균"),
    "무주군": (["701"], "AWS 자체(무주 212m)"),
    "익산시": (["702"], "AWS 자체(익산 11m)"),
    "완주군": (["734"], "AWS 자체(완주 64m)"),
    "김제시": (["737"], "AWS 자체(김제 55m)"),
    "장수군": (["248", "379"], "ASOS 자체(장수 406m) + AWS 번암(292m) 평균"),
    "남원시": (["247"], "ASOS 자체. 뱀사골(479m)은 산내면만 대표해 제외"),
    "전주시": (["146"], "ASOS 자체"),
    "정읍시": (["245"], "ASOS 자체"),
    "부안군": (["243"], "ASOS 자체"),
    "고창군": (["172"], "ASOS 자체"),
    "순창군": (["254"], "ASOS 자체"),
    "임실군": (["244"], "ASOS 자체"),
    "군산시": (["140"], "ASOS 자체"),
}

SUMMER = [6, 7, 8, 9]
WINTER = [12, 1, 2, 3]
T_TROPICAL = 25.0     # 일최저 25℃ 이상 = 열대야


def load_weather() -> pd.DataFrame:
    frames = []
    a = pd.read_csv(RAW / "daily_weather_lettuce.csv", encoding="utf-8-sig",
                    dtype={"stn": str})
    frames.append(a[["stn", "date", "tmax", "tmin"]])
    w = pd.read_csv(RAW / "daily_weather_aws.csv", encoding="utf-8-sig",
                    dtype={"stn": str})
    frames.append(w[["stn", "date", "tmax", "tmin"]])
    d = pd.concat(frames, ignore_index=True)
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    for c in ("tmax", "tmin"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["date", "tmax", "tmin"])
    d["dtr"] = d["tmax"] - d["tmin"]
    d["trop"] = (d["tmin"] >= T_TROPICAL).astype(float)
    d["month"] = d["date"].dt.month
    return d


def county_climate(wx: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for cty, (stns, note) in COUNTY_STN.items():
        s = wx[wx["stn"].isin(stns)]
        if s.empty:
            continue
        # 지점이 둘이면 날짜별로 먼저 평균 — 관측일수가 다른 지점이 섞이면
        # 단순평균이 관측 많은 지점 쪽으로 기운다
        day = s.groupby("date").agg(dtr=("dtr", "mean"), trop=("trop", "max"),
                                    month=("month", "first"))
        nyear = max(1, day.index.year.nunique())
        sm = day[day["month"].isin(SUMMER)]
        wt = day[day["month"].isin(WINTER)]
        rows.append({
            "county": cty,
            "dtr_all": day["dtr"].mean(),
            "dtr_sum": sm["dtr"].mean(),
            "dtr_win": wt["dtr"].mean(),
            "trop_days": sm["trop"].sum() / nyear,   # 연 몇 일
            "note": note,
        })
    return pd.DataFrame(rows)


def premium(d: pd.DataFrame, season: list[int] | None) -> pd.DataFrame:
    """같은 주·같은 품종·같은 시장 안에서 시군이 받은 값의 상대비."""
    x = d if not season else d[d["date"].dt.month.isin(season)]
    key = ["wk", "variety", "market_cd"]
    cell = (x.groupby(key + ["county"])
              .apply(lambda g: np.average(g["price_kg"], weights=g["qty_kg"]),
                     include_groups=False)
              .rename("p").reset_index())
    # 셀 안에 시군이 둘 이상 있어야 비교가 성립한다
    cell = cell[cell.groupby(key)["county"].transform("nunique") >= 2]
    cell["rel"] = cell["p"] / cell.groupby(key)["p"].transform("mean")
    return (cell.groupby("county")
                .agg(rel=("rel", "mean"), n=("rel", "size")).reset_index())


def boot_corr(x, y, n=4000, seed=20260814):
    rng = np.random.default_rng(seed)
    x, y = np.asarray(x, float), np.asarray(y, float)
    r0 = float(np.corrcoef(x, y)[0, 1])
    bs = []
    for _ in range(n):
        i = rng.integers(0, len(x), len(x))
        if len(set(i.tolist())) < 3:
            continue
        with np.errstate(invalid="ignore"):
            c = np.corrcoef(x[i], y[i])[0, 1]
        if np.isfinite(c):
            bs.append(c)
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return r0, float(lo), float(hi)


def verdict(lo: float, hi: float, want_positive: bool) -> str:
    if lo > 0:
        return "양의 관계" if want_positive else "역관계(가설과 반대)"
    if hi < 0:
        return "역관계(가설과 반대)" if want_positive else "음의 관계"
    return "판정불가"


def main() -> None:
    wx = load_weather()
    clim = county_climate(wx)

    print("=" * 78)
    print("1. 시군 기상 — 자체 지점 우선 (일교차 = 일최고 − 일최저)")
    print("=" * 78)
    print(f"{'시군':<7}{'연평균':>7}{'여름':>7}{'겨울':>7}{'열대야':>8}  근거")
    for _, r in clim.sort_values("dtr_sum", ascending=False).iterrows():
        print(f"{r['county']:<7}{r['dtr_all']:7.1f}{r['dtr_sum']:7.1f}"
              f"{r['dtr_win']:7.1f}{r['trop_days']:6.0f}일  {r['note']}")

    d = pd.read_csv(RAW / "lettuce_daily_raw.csv", low_memory=False,
                    usecols=["date", "market_cd", "county", "variety",
                             "price_kg", "qty_kg"],
                    dtype={"market_cd": str})
    d = d[d["county"].notna()].dropna(subset=["price_kg", "qty_kg"])
    d = d[(d["qty_kg"] > 0) & (d["price_kg"] > 0)]
    d["date"] = pd.to_datetime(d["date"], format="mixed")
    d["wk"] = d["date"] - pd.to_timedelta(d["date"].dt.weekday, unit="D")

    keep = {}
    for label, season, col in (("연중", None, "dtr_all"),
                               ("여름(6~9월)", SUMMER, "dtr_sum"),
                               ("겨울(12~3월)", WINTER, "dtr_win")):
        m = premium(d, season).merge(clim, on="county")
        keep[label] = m
        print()
        print("=" * 78)
        print(f"2. {label} — 같은 주·같은 품종·같은 시장 안에서 받은 값의 상대비")
        print("=" * 78)
        print(f"{'시군':<7}{'상대값':>8}{'비교셀':>8}{'일교차':>8}{'열대야':>7}")
        for _, r in m.sort_values("rel", ascending=False).iterrows():
            print(f"{r['county']:<7}{r['rel']:8.3f}{int(r['n']):8d}"
                  f"{r[col]:8.1f}{r['trop_days']:6.0f}일")
        if len(m) >= 5:
            r0, lo, hi = boot_corr(m[col], m["rel"])
            print(f"  일교차 vs 상대값   r = {r0:+.3f}  95% [{lo:+.3f}, {hi:+.3f}]"
                  f"  -> {verdict(lo, hi, True)}")
            r1, lo1, hi1 = boot_corr(m["trop_days"], m["rel"])
            print(f"  열대야 vs 상대값   r = {r1:+.3f}  95% [{lo1:+.3f}, {hi1:+.3f}]"
                  f"  -> {verdict(lo1, hi1, False)}")

    # 가설의 핵심 예측: 격차가 여름에 벌어지고 겨울에 좁아지는가
    s = keep["여름(6~9월)"][["county", "rel"]].rename(columns={"rel": "summer"})
    w = keep["겨울(12~3월)"][["county", "rel"]].rename(columns={"rel": "winter"})
    g = s.merge(w, on="county").merge(clim[["county", "dtr_sum", "trop_days"]], on="county")
    g["gap"] = g["summer"] - g["winter"]
    print()
    print("=" * 78)
    print("3. 핵심 예측 — 일교차가 큰 곳일수록 여름에 더 벌어지는가")
    print("=" * 78)
    print(f"{'시군':<7}{'여름':>8}{'겨울':>8}{'여름-겨울':>10}{'여름일교차':>10}")
    for _, r in g.sort_values("gap", ascending=False).iterrows():
        print(f"{r['county']:<7}{r['summer']:8.3f}{r['winter']:8.3f}"
              f"{r['gap']:+10.3f}{r['dtr_sum']:10.1f}")
    if len(g) >= 5:
        r0, lo, hi = boot_corr(g["dtr_sum"], g["gap"])
        print(f"  여름일교차 vs (여름−겨울)  r = {r0:+.3f}  95% [{lo:+.3f}, {hi:+.3f}]"
              f"  -> {verdict(lo, hi, True)}")
        print()
        print("  가설이 맞다면 이 값이 **양수**여야 한다 — 일교차가 큰 곳일수록")
        print("  여름에 상대적으로 더 받아야 하기 때문이다.")

    OUT.mkdir(exist_ok=True)
    out = keep["연중"].merge(s, on="county").merge(w, on="county")
    out.to_csv(OUT / "dtr_premium.csv", index=False, encoding="utf-8-sig")
    print(f"\n저장: {OUT/'dtr_premium.csv'}")


if __name__ == "__main__":
    main()
