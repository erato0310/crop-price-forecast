# -*- coding: utf-8 -*-
"""test_openfield_heat.py — '노지 산지가 고온에 무너져 가격이 오른다' 가설 검정.

────────────────────────────────────────────────────────────────
재해석
────────────────────────────────────────────────────────────────
전북 기상 9종을 전부 기각했는데, 그 기상은 전부 **전북 관측소**였다.
전북 상추는 시설 93.5%이고, 여름엔 준고랭지(진안·장수·무주)로 산지가
1.6% -> 12.2%로 옮겨간다. **둔감 + 회피** 두 겹으로 신호가 희석된다.

상추는 저온성이라 노지에서는 고온기에 녹거나 추대해 상품성을 잃는다.
그러므로 가격을 움직이는 경로는

    전북 시설이 더워짐(X)  ->  전북 공급 감소
    노지 비중 큰 산지가 무너짐(O)  ->  전국 공급 감소  ->  전북 가격 상승

전북은 오히려 수혜자다(여름 점유율 24.1% -> 32.7%).

────────────────────────────────────────────────────────────────
가중치를 가정하지 않는다
────────────────────────────────────────────────────────────────
노지/시설 면적비로 가중해 봤더니 노지가중과 시설가중 고온이 거의 같았다
(7월 16.3일 vs 16.5일). 두 재배방식이 지리적으로 섞여 있어서다.
게다가 시설도 균질하지 않다 — 무가온 단동 비닐하우스는 여름에 외기보다
더 덥고, 차광·유동팬·포그가 있어야 버틴다. 설비 수준은 통계에 없다.

그래서 **가중치를 자료에서 추정한다.** 각 시도의 출하량이 자기 지역 고온에
실제로 얼마나 반응하는지를 재고, 그 민감도를 가중치로 쓴다. 설비 수준까지
포함한 '실질 내성'이 그 안에 자동으로 반영된다.

[실행]
  python test_openfield_heat.py sensitivity   # 시도별 고온 민감도 추정
  python test_openfield_heat.py cv            # 예측력 검정
"""
from __future__ import annotations

import argparse
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

import lettuce_cv as CV
from scrape_lettuce_daily import MAIN_VARIETIES

_ROOT = Path(__file__).resolve().parent.parent
RAW = _ROOT / "data" / "raw"
PROC = _ROOT / "data" / "processed"
OUT = _ROOT / "outputs"

SIDO_MAP = {"경기": "경기도", "강원": "강원도", "충청남도": "충청남도",
            "충남": "충청남도", "충청북도": "충청북도", "충북": "충청북도",
            "경상북도": "경상북도", "경북": "경상북도",
            "전라남도": "전라남도", "전남": "전라남도",
            "경상남도": "경상남도", "경남": "경상남도",
            "전북": "전라북도", "전라북도": "전라북도"}


def sido_supply() -> pd.DataFrame:
    """시도 x 월 출하량(주력 품종)."""
    d = pd.read_csv(RAW / "lettuce_daily_raw.csv", dtype={"market_cd": str},
                    low_memory=False)
    d = d[d["variety"].isin(MAIN_VARIETIES)]
    d["date"] = pd.to_datetime(d["date"], format="mixed")
    d["ym"] = d["date"].dt.to_period("M")
    d["sd"] = (d["sido"].fillna("")
               .str.replace("특별자치도|특별자치시|특별시|광역시", "", regex=True)
               .map(SIDO_MAP))
    d = d.dropna(subset=["sd"])
    g = d.groupby(["ym", "sd"])["qty_kg"].sum().reset_index()
    g.columns = ["ym", "sido", "qty"]
    return g


def cmd_sensitivity() -> None:
    sup = sido_supply()
    w = pd.read_csv(PROC / "competitor_weather_by_sido.csv")
    w["ym"] = pd.PeriodIndex(w["ym"], freq="M")
    # 전북은 자체 파일에서
    jb = pd.read_csv(RAW / "daily_weather_lettuce.csv", dtype={"stn": str})
    jb["date"] = pd.to_datetime(jb["date"])
    jb["ym"] = jb["date"].dt.to_period("M")
    jb["_hot"] = jb["tmax"] >= 30
    jbm = jb.groupby(["ym", "stn"])["_hot"].sum().groupby("ym").mean().reset_index()
    jbm.columns = ["ym", "hot"]
    jbm["sido"] = "전라북도"
    w = pd.concat([w[["ym", "sido", "hot"]], jbm[["ym", "sido", "hot"]]],
                  ignore_index=True)

    m = sup.merge(w, on=["ym", "sido"], how="inner")
    m["month"] = m["ym"].dt.month
    m["lq"] = np.log(m["qty"].replace(0, np.nan))
    # 계절조정 — 시도별 달력월 평균 제거
    for c in ("lq", "hot"):
        m[c + "_a"] = m[c] - m.groupby(["sido", "month"])[c].transform("mean")

    AREA = {"전라북도": (95, 1376), "충청남도": (86, 954), "경기도": (253, 498),
            "강원도": (158, 15), "경상북도": (119, 126), "충청북도": (6, 208),
            "전라남도": (60, 127), "경상남도": (38, 91)}

    print("=" * 80)
    print("시도별 고온 민감도 — 자기 지역이 더울 때 출하량이 얼마나 줄어드나")
    print("=" * 80)
    print("  계절조정 후 회귀:  log(출하량) ~ 고온일수.  계수가 음수일수록 취약")
    print(f"  {'시도':<9}{'노지%':>7}{'계수':>10}{'표준오차':>9}{'t':>7}{'n':>5}   해석")
    rows = []
    for sd, g in m.groupby("sido"):
        g = g.dropna(subset=["lq_a", "hot_a"])
        if len(g) < 40 or g["hot_a"].std() == 0:
            continue
        x, y = g["hot_a"].values, g["lq_a"].values
        b = np.polyfit(x, y, 1)[0]
        resid = y - np.polyval(np.polyfit(x, y, 1), x)
        se = np.sqrt(np.sum(resid ** 2) / (len(x) - 2) / np.sum((x - x.mean()) ** 2))
        t = b / se if se else np.nan
        n_, s_ = AREA.get(sd, (0, 0))
        pct = n_ / (n_ + s_) * 100 if (n_ + s_) else np.nan
        tag = ("취약" if t < -2 else "내성" if t > 2 else "무반응")
        rows.append({"sido": sd, "nogi_pct": pct, "beta": b, "t": t, "n": len(g)})
        print(f"  {sd:<9}{pct:>6.0f}%{b:>+10.4f}{se:>9.4f}{t:>7.2f}{len(g):>5}   {tag}")
    r = pd.DataFrame(rows)
    r.to_csv(OUT / "sido_heat_sensitivity.csv", index=False, encoding="utf-8-sig")

    v = r.dropna(subset=["nogi_pct"])
    if len(v) > 3:
        c = np.corrcoef(v["nogi_pct"], v["beta"])[0, 1]
        print()
        print(f"  노지비율 vs 고온민감도 상관 {c:+.3f}")
        print("  (음수면 '노지가 많을수록 고온에 취약' = 가설 지지)")


def build_features() -> pd.DataFrame:
    """전북 가격 패널 + 경쟁산지 고온 피처."""
    p = CV.build_panel()
    w = pd.read_csv(PROC / "competitor_weather_monthly.csv")
    w["ym"] = pd.PeriodIndex(w["ym"], freq="M")
    p = p.merge(w, on="ym", how="left").sort_values("ym").reset_index(drop=True)

    # 민감도 가중 고온 — 추정된 취약도로 가중
    sens_path = OUT / "sido_heat_sensitivity.csv"
    if sens_path.exists():
        s = pd.read_csv(sens_path).set_index("sido")
        by = pd.read_csv(PROC / "competitor_weather_by_sido.csv")
        by["ym"] = pd.PeriodIndex(by["ym"], freq="M")
        # 취약(음의 계수)한 시도만, 계수 절댓값으로 가중
        wt = (-s["beta"]).clip(lower=0)
        by["w"] = by["sido"].map(wt).fillna(0)
        num = (by["hot"] * by["w"]).groupby(by["ym"]).sum()
        den = by.groupby("ym")["w"].sum()
        vul = (num / den.replace(0, np.nan)).rename("hot_vuln")
        p = p.merge(vul.reset_index(), on="ym", how="left")

    # 시차. 계절조정 상관이 당월 -0.01 / t-1 +0.21 / **t-2 +0.34** 로
    # t-2에서 가장 강했다. 고온 피해 -> 재정식 -> 4~8주 뒤 출하 공백이라는
    # 생리 경로와 맞는다. 처음엔 lag1만 넣어 놓쳤다.
    for c in [c for c in p.columns if c.startswith(
            ("hot_", "vhot_", "ehot_", "trop_", "germ_", "tmax_"))]:
        for L in (1, 2, 3):
            p[f"{c}_l{L}"] = p[c].shift(L)
        p[f"{c}_m23"] = p[c].shift(2).rolling(2).mean()   # t-2,t-3 평균
    return p


def cmd_cv() -> None:
    p = build_features()
    core = CV.FEATURE_SETS["가격시차"]
    h = CV.HORIZON
    cand = {
        "가격시차(기준)": [],
        "+전북고온 l1(기각확인)": ["hot_days_l1"] if "hot_days_l1" in p.columns else [],
        "+경기고온 l1": ["hot_gg_l1"],
        "+경기고온 l2": ["hot_gg_l2"],
        "+경기고온 l2+l3": ["hot_gg_l2", "hot_gg_l3"],
        "+경기고온 m23": ["hot_gg_m23"],
        "+노지가중 l2": ["hot_nogi_l2"],
        "+노지가중 m23": ["hot_nogi_m23"],
        "+민감도가중 l2": ["hot_vuln_l2"],
        "+극한고온 l2": ["ehot_nogi_l2"],
        "+경기 l2 + 강원 l2": ["hot_gg_l2", "hot_gw_l2"],
        "+노지 m23 + 전북 l1": ["hot_nogi_m23", "hot_days_l1"],
    }
    print("=" * 80)
    print("경쟁 산지 고온 -> 전북 가격  (h=1개월 walk-forward)")
    print("=" * 80)
    print(f"  {'피처집합':<20}{'모델':>8}{'기준':>8}{'개선':>8}{'승':>6}{'홀드아웃':>9}")
    res = {}
    for name, extra in cand.items():
        cols = core + [c for c in extra if c in p.columns]
        if extra and len(cols) == len(core):
            print(f"  {name:<20} 컬럼 없음")
            continue
        r = CV.walk_forward(p, cols)
        if r.empty:
            continue
        res[name] = cols
        tr = p[p["ym"].dt.year < CV.HOLDOUT_YEAR].dropna(subset=["price"])
        te = p[p["ym"].dt.year == CV.HOLDOUT_YEAR].dropna(subset=["price"])
        a, b = CV.tune(tr, cols)
        ho = CV.mape(te["price"].values, CV.fit_predict(tr, te, cols, a, b))
        w = int((r["model"] < r["baseline"]).sum())
        print(f"  {name:<20}{r['model'].mean():>7.2f}%{r['baseline'].mean():>7.2f}%"
              f"{r['baseline'].mean()-r['model'].mean():>+7.2f}%{w:>4}/{len(r)}"
              f"{ho:>8.2f}%")

    print()
    print("  블록 부트스트랩 — 기준 대비 95% 구간")
    for name, cols in res.items():
        if name == "가격시차(기준)":
            continue
        d, lo, hi = CV.block_bootstrap(p, cols, core)
        v = "개선" if hi < 0 else ("악화" if lo > 0 else "판정불가")
        print(f"    {name:<20}{d:>+7.2f}%p  [{lo:+.2f}, {hi:+.2f}]  {v}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["sensitivity", "cv"])
    a = ap.parse_args()
    {"sensitivity": cmd_sensitivity, "cv": cmd_cv}[a.cmd]()


if __name__ == "__main__":
    main()
