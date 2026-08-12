# -*- coding: utf-8 -*-
"""analyze_agro_price_link.py — 시군별 기상 x 공판장 가격 1:1 매칭 상관분석.

────────────────────────────────────────────────────────────────
반드시 먼저 읽을 것 — 원계열 상관은 거의 전부 가짜다
────────────────────────────────────────────────────────────────
상추 가격도 여름에 오르고 고온일수도 여름에 오른다. 그래서 두 원계열을 그냥
상관내면 r=0.6~0.8이 쉽게 나오는데, 이는 "고온이 가격을 올린다"가 아니라
**둘 다 달력을 따라간다**는 사실을 재확인한 것에 불과하다. month_sin/cos만
넣어도 같은 정보가 들어온다.

그래서 이 스크립트는 두 가지를 나란히 낸다.

  raw   원계열 상관            — 참고용. 계절성이 대부분이다
  adj   계절조정 후 상관        — **이게 본론**
        각 시군의 달력월 평균을 빼서 "그 해 그 달이 평년보다 얼마나
        더웠나 / 비쌌나"만 남긴 뒤 상관을 낸다.

adj에서 유의한 관계만 "기상이 가격에 정보를 준다"고 말할 수 있다.

────────────────────────────────────────────────────────────────
표본 한계 (결과 해석 전에 반드시 감안)
────────────────────────────────────────────────────────────────
현재 가격자료는 2018-01~2021-02 **38개월**뿐이다(나머지 66개월 수집 중).
계절조정을 하면 시군당 유효표본이 30개 안팎으로 떨어지고, **여름이 세 번밖에
없다.** 고온 변수는 여름에만 값이 있으므로 사실상 n=3~6의 관계를 보는 셈이다.
따라서 이 결과는 **탐색적**이며, 개별 계수를 근거로 변수를 확정해서는 안 된다.
확정은 66개월이 채워진 뒤 walk-forward CV로 한다.

다중검정도 문제다. 변수 20종 x 시군 12개 x 시차 3개면 720번 검정이라
p<0.05가 우연히 36개 나온다. 그래서 개별 시군보다 **패널 통합 결과**를
먼저 보고, 시군별은 부호 일관성 확인용으로만 쓴다.

[실행] python analyze_agro_price_link.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
RAW = _ROOT / "data" / "raw"
PROC = _ROOT / "data" / "processed"
OUT = _ROOT / "outputs"
OUT.mkdir(exist_ok=True)

PRICE = RAW / "lettuce_daily_by_county.csv"
ASOS = RAW / "daily_weather_lettuce.csv"
AWS = RAW / "daily_weather_aws.csv"

# 시군 -> (기온용 지점, 광·습도용 ASOS 지점). 기온은 AWS가 있으면 그쪽이 정확하다
# (fetch_aws_stations.compare 실측: 익산은 군산 대체로 vhot를 5.7일 과소평가했다).
# 일조·습도는 AWS가 관측하지 않으므로 항상 ASOS를 쓴다.
COUNTY_MAP: dict[str, tuple[str, str, str]] = {
    # 시군:      (기온지점, 광습도ASOS, 비고)
    "익산시":   ("702", "140", "AWS 익산(11m) / 종전 군산140"),
    "남원시":   ("247", "247", "ASOS 남원 시내(133m)"),
    "남원시*산간": ("759", "247", "AWS 뱀사골(479m) — 남원 대체안"),
    "완주군":   ("734", "146", "AWS 완주(64m)"),
    "장수군":   ("248", "248", "ASOS 장수(407m)"),
    "전주시":   ("146", "146", "ASOS 전주"),
    "김제시":   ("737", "146", "AWS 김제(55m)"),
    "순창군":   ("254", "254", "ASOS 순창"),
    "진안군":   ("703", "244", "AWS 진안(354m) / 종전 임실244"),
    "고창군":   ("172", "172", "ASOS 고창"),
    "정읍시":   ("245", "245", "ASOS 정읍"),
    "부안군":   ("243", "243", "ASOS 부안"),
    "무주군":   ("701", "248", "AWS 무주(212m)"),
    "임실군":   ("244", "244", "ASOS 임실"),
    "군산시":   ("140", "140", "ASOS 군산"),
}

# 생리 경로별 변수와 기대 부호. 부호가 기대와 반대로 나오면 그 자체가 정보다.
#   +  : 값이 클수록 공급 감소 -> 가격 상승 기대
#   -  : 값이 클수록 생육 양호 -> 가격 하락 기대
EXPECTED = {
    "hot_days": "+", "vhot_days": "+", "heat_deg": "+", "hot_streak3": "+",
    "trop_nights": "+", "night_heat_deg": "+", "germ_block_days": "+",
    "cold_days": "+", "vcold_days": "+", "frost_deg": "+",
    "sun_hours": "-", "sun_ratio": "-", "dark_days": "+",
    "rain_sum": "+", "wet_days": "+", "wet_streak_max": "+", "humid_hot_days": "+",
    "tavg": "?", "dtr": "?",
}
TEMP_FEATS = ["hot_days", "vhot_days", "heat_deg", "hot_streak3", "trop_nights",
              "night_heat_deg", "germ_block_days", "cold_days", "vcold_days",
              "frost_deg", "tavg", "dtr", "rain_sum", "wet_days", "wet_streak_max"]
LIGHT_FEATS = ["sun_hours", "sun_ratio", "dark_days", "humid_hot_days"]

T_BOLT, T_SEVERE, T_TROP, T_GERM = 30.0, 33.0, 20.0, 25.0


def _streak3(v: pd.Series) -> float:
    b = v.fillna(False).astype(bool).tolist()
    tot = run = 0
    for x in b + [False]:
        if x:
            run += 1
        else:
            if run >= 3:
                tot += run
            run = 0
    return float(tot)


def monthly_from_daily(d: pd.DataFrame, tavg_col: str) -> pd.DataFrame:
    """일별 기상 -> 월별 생리 피처(지점 하나)."""
    d = d.copy()
    d["ym"] = d["date"].dt.to_period("M")
    d["_hot"] = d["tmax"] >= T_BOLT
    d["_vhot"] = d["tmax"] >= T_SEVERE
    d["_trop"] = d["tmin"] >= T_TROP
    d["_germ"] = d[tavg_col] >= T_GERM
    d["_cold"] = d["tmin"] <= 0
    d["_vcold"] = d["tmin"] <= -5
    d["_wet"] = d["rain"].fillna(0) >= 1.0
    g = d.groupby("ym")
    out = pd.DataFrame({
        "hot_days": g["_hot"].sum(), "vhot_days": g["_vhot"].sum(),
        "heat_deg": g.apply(lambda x: (x["tmax"] - T_BOLT).clip(lower=0).sum(),
                            include_groups=False),
        "trop_nights": g["_trop"].sum(),
        "night_heat_deg": g.apply(lambda x: (x["tmin"] - T_TROP).clip(lower=0).sum(),
                                  include_groups=False),
        "germ_block_days": g["_germ"].sum(),
        "cold_days": g["_cold"].sum(), "vcold_days": g["_vcold"].sum(),
        "frost_deg": g.apply(lambda x: (0 - x["tmin"]).clip(lower=0).sum(),
                             include_groups=False),
        "tavg": g[tavg_col].mean(),
        "dtr": g.apply(lambda x: (x["tmax"] - x["tmin"]).mean(), include_groups=False),
        "rain_sum": g["rain"].sum(), "wet_days": g["_wet"].sum(),
        "wet_streak_max": g.apply(lambda x: _streak3(x["_wet"]), include_groups=False),
        "n_days": g["date"].nunique(),
    })
    out["hot_streak3"] = g.apply(lambda x: _streak3(x["_hot"]), include_groups=False)
    return out.reset_index()


def light_monthly(a: pd.DataFrame) -> pd.DataFrame:
    """ASOS 전용 — 일조·습도. AWS는 이 항목을 관측하지 않는다."""
    a = a.copy()
    a["ym"] = a["date"].dt.to_period("M")
    a["_dark"] = a["sun_hr"] <= 3.0
    a["_hh"] = (a["tmax"] >= 25.0) & (a["rh"] >= 80.0)
    g = a.groupby("ym")
    o = pd.DataFrame({
        "sun_hours": g["sun_hr"].sum(),
        "sun_possible": g["sun_possible"].sum(),
        "dark_days": g["_dark"].sum(),
        "humid_hot_days": g["_hh"].sum(),
    })
    o["sun_ratio"] = o["sun_hours"] / o["sun_possible"].replace(0, np.nan)
    return o.drop(columns=["sun_possible"]).reset_index()


def deseasonalize(s: pd.Series, months: pd.Series) -> pd.Series:
    """달력월 평균을 빼서 '평년 대비 편차'만 남긴다."""
    return s - months.map(s.groupby(months).transform("mean").groupby(months).first())


def corr_with_n(x: pd.Series, y: pd.Series) -> tuple[float, int]:
    m = x.notna() & y.notna()
    n = int(m.sum())
    if n < 8 or x[m].std() == 0 or y[m].std() == 0:
        return np.nan, n
    return float(np.corrcoef(x[m], y[m])[0, 1]), n


def main() -> None:
    price = pd.read_csv(PRICE)
    price["date"] = pd.to_datetime(price["date"])
    price["ym"] = price["date"].dt.to_period("M")

    asos = pd.read_csv(ASOS, dtype={"stn": str})
    asos["date"] = pd.to_datetime(asos["date"])
    aws = pd.read_csv(AWS, dtype={"stn": str})
    aws["date"] = pd.to_datetime(aws["date"])

    # 월별 시군 가격(물량가중 원/kg) + 물량
    pm = []
    for (ym, c), g in price.groupby(["ym", "county"]):
        w = g[["price_kg", "qty_kg"]].dropna()
        tq = w["qty_kg"].sum()
        pm.append({"ym": ym, "county": c,
                   "price_kg": (w["price_kg"] * w["qty_kg"]).sum() / tq if tq else np.nan,
                   "qty_kg": g["qty_kg"].sum(min_count=1),
                   "n_days": g["date"].nunique()})
    pm = pd.DataFrame(pm)

    print("=" * 78)
    print("0. 자료 현황")
    print("=" * 78)
    print(f"  가격 구간 {pm['ym'].min()} ~ {pm['ym'].max()}  ({pm['ym'].nunique()}개월)")
    print(f"  {'시군':<8}{'월수':>5}{'거래일/월':>10}{'평균원/kg':>11}{'물량비중':>9}   기상지점")
    tot_q = pm["qty_kg"].sum()
    order = pm.groupby("county")["qty_kg"].sum().sort_values(ascending=False)
    for c in order.index:
        g = pm[pm["county"] == c]
        mp = COUNTY_MAP.get(c)
        note = mp[2] if mp else "매핑 없음"
        print(f"  {c:<8}{len(g):>5}{g['n_days'].median():>10.0f}"
              f"{g['price_kg'].mean():>11,.0f}{order[c]/tot_q*100:>8.2f}%   {note}")

    # 지점별 월 피처 캐시
    cache: dict[str, pd.DataFrame] = {}

    def feats_for(county: str) -> pd.DataFrame | None:
        mp = COUNTY_MAP.get(county)
        if mp is None:
            return None
        tstn, lstn, _ = mp
        key = f"{tstn}|{lstn}"
        if key in cache:
            return cache[key]
        src = aws[aws["stn"] == tstn]
        tcol = "tavg_approx"
        if src.empty:
            src = asos[asos["stn"] == tstn]
            tcol = "tavg"
        if src.empty:
            return None
        t = monthly_from_daily(src, tcol)
        lt = light_monthly(asos[asos["stn"] == lstn])
        out = t.merge(lt, on="ym", how="left")
        cache[key] = out
        return out

    # 시군 x 월 패널 구성 (시차 0/1/2)
    rows = []
    for c in order.index:
        f = feats_for(c)
        if f is None:
            continue
        g = pm[pm["county"] == c].merge(f, on="ym", how="left", suffixes=("", "_w"))
        g = g.sort_values("ym").reset_index(drop=True)
        allf = TEMP_FEATS + LIGHT_FEATS
        for L in (0, 1, 2):
            for col in allf:
                if col in g.columns:
                    g[f"{col}__l{L}"] = g[col].shift(L)
        g["county"] = c
        rows.append(g)
    panel = pd.concat(rows, ignore_index=True)
    panel["month"] = panel["ym"].dt.month
    panel["logp"] = np.log(panel["price_kg"])

    # 시군별 계절조정
    panel["logp_adj"] = panel.groupby(["county", "month"])["logp"].transform(
        lambda x: x - x.mean())
    feat_cols = [c for c in panel.columns if "__l" in c]
    # 한 번에 붙인다 — 하나씩 대입하면 프레임이 조각나 경고가 쏟아진다
    grp = panel.groupby(["county", "month"])
    adj = {c + "_adj": panel[c] - grp[c].transform("mean") for c in feat_cols}
    panel = pd.concat([panel, pd.DataFrame(adj, index=panel.index)], axis=1)

    panel.to_csv(OUT / "agro_price_panel.csv", index=False, encoding="utf-8-sig")

    # ── 1. 패널 통합 ────────────────────────────────────────
    print()
    print("=" * 78)
    print("1. 패널 통합 상관 — 전 시군 묶어서 (본론)")
    print("=" * 78)
    print("   raw = 원계열(계절성 포함, 참고용) / adj = 계절조정 후(해석 대상)")
    print(f"   {'변수':<17}{'기대':>4}{'lag':>4}{'raw':>8}{'adj':>8}{'n':>6}  판정")
    res = []
    for base in TEMP_FEATS + LIGHT_FEATS:
        for L in (0, 1, 2):
            col = f"{base}__l{L}"
            if col not in panel.columns:
                continue
            r_raw, _ = corr_with_n(panel[col], panel["logp"])
            r_adj, n = corr_with_n(panel[col + "_adj"], panel["logp_adj"])
            res.append({"feature": base, "lag": L, "raw": r_raw, "adj": r_adj, "n": n,
                        "expected": EXPECTED.get(base, "?")})
    res = pd.DataFrame(res)
    res["absadj"] = res["adj"].abs()
    for _, r in res.sort_values("absadj", ascending=False).head(18).iterrows():
        exp = r["expected"]
        sign_ok = ("?" if exp == "?" else
                   ("부호일치" if (r["adj"] > 0) == (exp == "+") else "부호반대"))
        # n>=30에서 |r|>0.15면 대략 p<0.05. 엄밀한 검정은 CV로 대체한다
        strength = "***" if abs(r["adj"]) > 0.30 else ("**" if abs(r["adj"]) > 0.20 else
                                                       ("*" if abs(r["adj"]) > 0.15 else ""))
        print(f"   {r['feature']:<17}{exp:>4}{r['lag']:>4}{r['raw']:>8.2f}"
              f"{r['adj']:>8.2f}{r['n']:>6}  {sign_ok} {strength}")
    res.drop(columns=["absadj"]).to_csv(OUT / "agro_price_corr_pooled.csv",
                                        index=False, encoding="utf-8-sig")

    # ── 2. 시군별 ───────────────────────────────────────────
    print()
    print("=" * 78)
    print("2. 시군별 계절조정 상관 — 부호 일관성 확인용")
    print("=" * 78)
    show = ["vhot_days__l1", "hot_days__l1", "trop_nights__l1",
            "germ_block_days__l2", "sun_ratio__l0", "vcold_days__l1"]
    hdr = "".join(f"{s.replace('__l','.l')[:13]:>14}" for s in show)
    print(f"   {'시군':<8}{'n':>4}{hdr}")
    per_county = []
    for c in order.index:
        g = panel[panel["county"] == c]
        if g["logp_adj"].notna().sum() < 12:
            continue
        line, rec = "", {"county": c}
        for s in show:
            if s + "_adj" not in g.columns:
                line += f"{'-':>14}"
                continue
            r, n = corr_with_n(g[s + "_adj"], g["logp_adj"])
            rec[s] = r
            line += f"{'-' if np.isnan(r) else f'{r:+.2f}':>14}"
        print(f"   {c:<8}{int(g['logp_adj'].notna().sum()):>4}{line}")
        per_county.append(rec)
    pd.DataFrame(per_county).to_csv(OUT / "agro_price_corr_by_county.csv",
                                    index=False, encoding="utf-8-sig")

    # ── 3. 남원 시내 vs 산간 ────────────────────────────────
    print()
    print("=" * 78)
    print("3. 남원 — 시내(ASOS 247, 133m) vs 산간(AWS 759, 479m) 어느 쪽이 맞나")
    print("=" * 78)
    nam = pm[pm["county"] == "남원시"]
    for label, key in [("시내 247", "남원시"), ("산간 759", "남원시*산간")]:
        f = feats_for(key)
        if f is None:
            continue
        g = nam.merge(f, on="ym", how="left").sort_values("ym").reset_index(drop=True)
        g["month"] = g["ym"].dt.month
        g["logp"] = np.log(g["price_kg"])
        g["logp_adj"] = g.groupby("month")["logp"].transform(lambda x: x - x.mean())
        out = []
        for base in ("vhot_days", "hot_days", "trop_nights", "germ_block_days"):
            g["_x"] = g[base].shift(1)
            g["_xadj"] = g.groupby("month")["_x"].transform(lambda x: x - x.mean())
            r, n = corr_with_n(g["_xadj"], g["logp_adj"])
            out.append(f"{base[:9]}.l1 {r:+.2f}" if not np.isnan(r) else f"{base[:9]} -")
        print(f"   {label}: " + "  ".join(out))
    print("   (부호가 크고 일관된 쪽이 남원 상추 실제 산지에 가깝다는 뜻)")

    print()
    print("=" * 78)
    print("해석 주의")
    print("=" * 78)
    print("  - 가격자료가 38개월(여름 3회)뿐이다. 고온 변수는 사실상 n=3~6이다.")
    print("  - 변수 x 시차 x 시군으로 수백 번 상관을 냈다. 우연한 유의가 섞인다.")
    print("  - 여기 결과로 변수를 확정하지 말 것. 66개월 완료 후 walk-forward CV로 판정.")
    print(f"  - 저장: outputs/agro_price_panel.csv, agro_price_corr_pooled.csv,")
    print(f"          agro_price_corr_by_county.csv")


if __name__ == "__main__":
    main()
