# -*- coding: utf-8 -*-
"""test_aws_station_swap.py — 기상 지점을 정확한 것으로 바꾸면 예측이 좋아지는가.

────────────────────────────────────────────────────────────────
왜 이 검정이 필요한가
────────────────────────────────────────────────────────────────
lettuce_cv 결과 기상 피처가 하나도 가격시차를 못 이겼다(1번 단계). 그런데
그 기상은 **인접 ASOS로 대체된 값**이었다. 특히 출하 1위 익산(37%)이
해안 도시 군산(140)의 기온을 쓰고 있었고, 실측 격차가 컸다.

    8월 평균   hot(30C+)  vhot(33C+)
    군산 140      20.1       7.2     <- 익산이 쓰던 값
    익산 AWS 702  22.5      12.9     <- 실제 익산

vhot에서 5.7일 차이다. 그렇다면 "기상이 무용하다"가 아니라 **"틀린 기상을
넣어서 무용해 보였다"**일 가능성이 남는다. 이 파일이 그걸 가른다.

지점을 바꿔도 개선이 없으면, 기상 무용 결론은 자료 품질 탓이 아니라
구조적인 것(계절항이 이미 흡수)으로 확정된다.

[비교 대상]
  ASOS  기존 매핑 (익산=군산140, 완주/김제=전주146, 진안=임실244, 무주=장수248)
  AWS   자체 관측소 (익산702, 완주734, 김제737, 진안703, 무주701)
  둘 다 광·습도는 ASOS를 쓴다 — AWS는 일조·습도를 관측하지 않는다.

[실행] python test_aws_station_swap.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import lettuce_cv as CV
import lettuce_agro_features as AF

_ROOT = Path(__file__).resolve().parent.parent
RAW = _ROOT / "data" / "raw"
OUT = _ROOT / "outputs"

ASOS_PATH = RAW / "daily_weather_lettuce.csv"
AWS_PATH = RAW / "daily_weather_aws.csv"
WEIGHTS = _ROOT / "data" / "processed" / "county_shipment_weights.csv"

# 시군 -> (ASOS 기존, AWS 신규). AWS가 없는 시군은 양쪽 동일.
SWAP = {
    "iksan": ("140", "702"), "wanju": ("146", "734"), "gimje": ("146", "737"),
    "jinan": ("244", "703"), "muju": ("248", "701"),
    "namwon": ("247", "247"), "jangsu": ("248", "248"), "jeonju": ("146", "146"),
    "sunchang": ("254", "254"), "gochang": ("172", "172"),
    "jeongeup": ("245", "245"), "buan": ("243", "243"),
    "imsil": ("244", "244"), "gunsan": ("140", "140"),
}


def load_daily() -> tuple[pd.DataFrame, pd.DataFrame]:
    a = pd.read_csv(ASOS_PATH, dtype={"stn": str})
    a["date"] = pd.to_datetime(a["date"])
    w = pd.read_csv(AWS_PATH, dtype={"stn": str})
    w["date"] = pd.to_datetime(w["date"])
    return a, w


def monthly_for(stn: str, asos: pd.DataFrame, aws: pd.DataFrame) -> pd.DataFrame:
    """지점 하나의 월별 기온·강수 피처. AWS에 있으면 AWS, 없으면 ASOS."""
    src, tcol = aws[aws["stn"] == stn], "tavg_approx"
    if src.empty:
        src, tcol = asos[asos["stn"] == stn], "tavg"
    if src.empty:
        return pd.DataFrame()
    d = src.copy()
    d["ym"] = d["date"].dt.to_period("M")
    d["_hot"] = d["tmax"] >= 30
    d["_vhot"] = d["tmax"] >= 33
    d["_trop"] = d["tmin"] >= 20
    d["_germ"] = d[tcol] >= 25
    g = d.groupby("ym")
    return pd.DataFrame({
        "hot_days": g["_hot"].sum(), "vhot_days": g["_vhot"].sum(),
        "trop_nights": g["_trop"].sum(), "germ_block_days": g["_germ"].sum(),
        "tavg": g[tcol].mean(),
    }).reset_index()


def build_weather(which: str, asos: pd.DataFrame, aws: pd.DataFrame) -> pd.DataFrame:
    """출하량 가중 월별 기온 피처. which in {'asos','aws'}."""
    w = pd.read_csv(WEIGHTS)
    idx = 0 if which == "asos" else 1
    w["stn"] = w["county_id"].map({k: v[idx] for k, v in SWAP.items()})
    w = w.dropna(subset=["stn"])

    cache = {s: monthly_for(s, asos, aws) for s in w["stn"].unique()}
    frames = []
    for stn, m in cache.items():
        if m.empty:
            continue
        m = m.copy()
        m["stn"] = stn
        frames.append(m)
    sm = pd.concat(frames, ignore_index=True)
    sm["month"] = sm["ym"].dt.month
    j = sm.merge(w, on=["stn", "month"], how="inner")

    cols = ["hot_days", "vhot_days", "trop_nights", "germ_block_days", "tavg"]
    out = {}
    for c in cols:
        num = (j[c] * j["w"]).groupby(j["ym"]).sum(min_count=1)
        den = j.loc[j[c].notna()].groupby("ym")["w"].sum()
        out[c] = num / den.replace(0, np.nan)
    r = pd.DataFrame(out).reset_index().sort_values("ym").reset_index(drop=True)
    # 생리 시차 — 추대는 생육기(l1), 발아저해는 파종기(l2)
    r["vhot_days_l1"] = r["vhot_days"].shift(1)
    r["hot_days_l1"] = r["hot_days"].shift(1)
    r["trop_nights_l1"] = r["trop_nights"].shift(1)
    r["germ_block_days_l2"] = r["germ_block_days"].shift(2)
    return r


def main() -> None:
    asos, aws = load_daily()

    print("=" * 78)
    print("0. 지점 교체가 기상 수치를 얼마나 바꾸나 (출하량 가중, 8월 평균)")
    print("=" * 78)
    wa_ = {k: build_weather(k, asos, aws) for k in ("asos", "aws")}
    for k, r in wa_.items():
        r8 = r[r["ym"].dt.month == 8]
        print(f"  {k.upper():<6} hot {r8['hot_days'].mean():5.1f}  "
              f"vhot {r8['vhot_days'].mean():5.1f}  "
              f"열대야 {r8['trop_nights'].mean():5.1f}  "
              f"발아저해 {r8['germ_block_days'].mean():5.1f}")
    d8a = wa_["asos"][wa_["asos"]["ym"].dt.month == 8]
    d8w = wa_["aws"][wa_["aws"]["ym"].dt.month == 8]
    print(f"  차이   hot {d8w['hot_days'].mean()-d8a['hot_days'].mean():+5.1f}  "
          f"vhot {d8w['vhot_days'].mean()-d8a['vhot_days'].mean():+5.1f}  "
          f"열대야 {d8w['trop_nights'].mean()-d8a['trop_nights'].mean():+5.1f}  "
          f"발아저해 {d8w['germ_block_days'].mean()-d8a['germ_block_days'].mean():+5.1f}")

    # ── CV 비교 ─────────────────────────────────────────────
    base = CV.build_panel()
    keep = ["ym", "price", "qty", "n_days", "month", "month_sin", "month_cos",
            "lag_h", "lag12", "roll3"]
    base = base[keep]

    print()
    print("=" * 78)
    print("1. 같은 피처집합, 기상 출처만 교체 — walk-forward")
    print("=" * 78)
    sets = {
        "기상없음(가격시차)": [],
        "+고온": ["vhot_days_l1", "germ_block_days_l2"],
        "+고온+열대야": ["vhot_days_l1", "germ_block_days_l2", "trop_nights_l1"],
        "+전부": ["hot_days_l1", "vhot_days_l1", "trop_nights_l1",
                 "germ_block_days_l2"],
    }
    core = ["month_sin", "month_cos", "lag_h", "lag12", "roll3"]
    rows = []
    print(f"  {'피처집합':<18}{'ASOS':>9}{'AWS':>9}{'차이':>9}{'승(ASOS/AWS)':>14}")
    for name, extra in sets.items():
        line = {}
        for src in ("asos", "aws"):
            p = base.merge(wa_[src], on="ym", how="left")
            cols = core + extra
            miss = [c for c in cols if c not in p.columns]
            if miss:
                line[src] = np.nan
                continue
            r = CV.walk_forward(p, cols)
            line[src] = r["model"].mean()
            line[src + "_win"] = int((r["model"] < r["baseline"]).sum())
            line["nf"] = len(r)
        if not extra:
            print(f"  {name:<18}{line['asos']:>8.2f}%{'':>9}{'':>9}"
                  f"{line.get('asos_win',0)}/{line.get('nf',0)}")
        else:
            print(f"  {name:<18}{line['asos']:>8.2f}%{line['aws']:>8.2f}%"
                  f"{line['aws']-line['asos']:>+8.2f}%"
                  f"{line.get('asos_win',0)}/{line.get('nf',0)}"
                  f" vs {line.get('aws_win',0)}/{line.get('nf',0)}".rjust(14))
        rows.append({"featureset": name, **line})
    pd.DataFrame(rows).to_csv(OUT / "aws_swap_cv.csv", index=False,
                              encoding="utf-8-sig")

    # ── 홀드아웃 ────────────────────────────────────────────
    print()
    print("=" * 78)
    print(f"2. 독립 홀드아웃 {CV.HOLDOUT_YEAR}")
    print("=" * 78)
    print(f"  {'피처집합':<18}{'ASOS':>9}{'AWS':>9}{'차이':>9}")
    for name, extra in sets.items():
        if not extra:
            continue
        vals = {}
        for src in ("asos", "aws"):
            p = base.merge(wa_[src], on="ym", how="left")
            cols = core + extra
            tr = p[p["ym"].dt.year < CV.HOLDOUT_YEAR].dropna(subset=["price"])
            te = p[p["ym"].dt.year == CV.HOLDOUT_YEAR].dropna(subset=["price"])
            a, b = CV.tune(tr, cols)
            vals[src] = CV.mape(te["price"].values,
                                CV.fit_predict(tr, te, cols, a, b))
        print(f"  {name:<18}{vals['asos']:>8.2f}%{vals['aws']:>8.2f}%"
              f"{vals['aws']-vals['asos']:>+8.2f}%")

    print()
    print("  판정 기준: AWS로 바꿔도 '기상없음'을 못 이기면, 기상 무용 결론은")
    print("            자료 품질 탓이 아니라 구조적인 것이다.")


if __name__ == "__main__":
    main()
