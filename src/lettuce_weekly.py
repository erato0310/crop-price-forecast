# -*- coding: utf-8 -*-
"""lettuce_weekly.py — 주간 해상도 모델. 월간(104관측)의 표본 제약을 정면으로 푼다.

────────────────────────────────────────────────────────────────
왜 주간인가
────────────────────────────────────────────────────────────────
일별 200만 행을 모아 놓고 **월 104개 점으로 압축해서** 모델링하고 있었다.
지금까지 모든 기각 판정(기후 9종, 쫑상추, 전국시세, 추석)의 근본 원인이
표본 부족이었는데, 해상도를 올리면 그 제약이 직접 완화된다.

  해상도   관측수   lag1     lag2     lag4    lag52   로그차분 표준편차
  월        104   +0.599   +0.127   -0.247            0.4467
  주        450   +0.837   +0.653   +0.456  +0.554    0.3170
  일      2,669   +0.975   +0.934   +0.853

세 가지가 동시에 유리하다.
  1. 표본 4.3배 (104 -> 450)
  2. 자기상관이 훨씬 높다 (lag1 +0.837 vs +0.599) — 다음 주의 많은 부분이 이번 주에 있다
  3. 변동성이 작다 (0.317 vs 0.447)

그리고 **주간이 실용적으로 더 유용하다.** 농가 출하 결정은 한 달 전이 아니라
며칠~1주 전에 내린다.

일 단위는 안 쓴다. lag1 +0.975는 예측이 쉬워 보이지만 거의 전부가 지속성이고,
휴장·소량거래일 잡음이 커서 의사결정 단위로도 부적절하다.

────────────────────────────────────────────────────────────────
두 가지 예측 문제
────────────────────────────────────────────────────────────────
  h=1주   새 문제. 더 쉽고 더 유용하다
  h=4주   기존 월간 예측(h=1개월)과 직접 비교 가능한 지평

────────────────────────────────────────────────────────────────
지키는 규칙 (lettuce_cv.py와 동일)
────────────────────────────────────────────────────────────────
  - 모든 피처는 t-h 시점까지 관측된 값만
  - 하이퍼파라미터는 학습구간 내부에서만 탐색
  - fold는 연도 단위 walk-forward, 2026은 홀드아웃
  - 로그 역변환은 Duan 스미어링으로 교정 (test_bias_correction.py 채택안)

[실행]
  python lettuce_weekly.py baseline
  python lettuce_weekly.py compare      # 피처집합 비교 (기후 재검정 포함)
  python lettuce_weekly.py horizon      # h=1,2,4,8주 지평별
  python lettuce_weekly.py holdout
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

_ROOT = Path(__file__).resolve().parent.parent
RAW = _ROOT / "data" / "raw"
OUT = _ROOT / "outputs"
OUT.mkdir(exist_ok=True)

PRICE_DAILY = RAW / "lettuce_daily_by_county.csv"
ASOS = RAW / "daily_weather_lettuce.csv"

HORIZON = 1                      # 주 단위
TEST_YEARS = [2019, 2020, 2021, 2022, 2023, 2024, 2025]
HOLDOUT_YEAR = 2026
ALPHAS = [0.01, 0.1, 1.0, 3.0, 10.0, 30.0]
BLENDS = [0.0, 0.2, 0.4, 0.6]
MIN_TRAIN = 60                   # 주. 월간 MIN_TRAIN=24개월과 대략 대응
MIN_DAYS_PER_WEEK = 3            # 거래일이 이보다 적은 주는 평균이 불안정


# ═══════════════════════════════════════════════════════════════
# 자료 구성
# ═══════════════════════════════════════════════════════════════

def load_weekly_target() -> pd.DataFrame:
    d = pd.read_csv(PRICE_DAILY)
    d["date"] = pd.to_datetime(d["date"])
    d["wk"] = d["date"].dt.to_period("W")
    rows = []
    for wk, g in d.groupby("wk"):
        w = g[["price_kg", "qty_kg"]].dropna()
        tq = w["qty_kg"].sum()
        jj = g[["price_kg_jjong", "qty_kg_jjong"]].dropna()
        tjj = jj["qty_kg_jjong"].sum()
        rows.append({
            "wk": wk,
            "price": (w["price_kg"] * w["qty_kg"]).sum() / tq if tq else np.nan,
            "qty": tq,
            "price_jjong": ((jj["price_kg_jjong"] * jj["qty_kg_jjong"]).sum() / tjj
                            if tjj else np.nan),
            "qty_jjong": tjj,
            "n_days": g["date"].nunique(),
            "n_obs": g["n_obs"].sum(),
        })
    t = pd.DataFrame(rows).sort_values("wk").reset_index(drop=True)
    # 거래일이 모자란 주(연말연시·명절)는 평균이 튄다 — 결측 처리하고 시차만 잇는다
    t.loc[t["n_days"] < MIN_DAYS_PER_WEEK, "price"] = np.nan
    return t


def weekly_weather() -> pd.DataFrame:
    """주간 기상. 월 집계로 뭉개졌던 신호를 다시 볼 기회다."""
    a = pd.read_csv(ASOS, dtype={"stn": str})
    a["date"] = pd.to_datetime(a["date"])
    a["wk"] = a["date"].dt.to_period("W")
    a["_hot"] = a["tmax"] >= 30
    a["_vhot"] = a["tmax"] >= 33
    a["_trop"] = a["tmin"] >= 20
    a["_germ"] = a["tavg"] >= 25
    a["_cold"] = a["tmin"] <= 0
    a["_dark"] = a["sun_hr"] <= 3.0
    # 지점 단순평균 후 주간 집계 (월간에서 가중/단순 차이가 없었으므로 단순으로)
    g = a.groupby(["wk", "stn"]).agg(
        hot=("_hot", "sum"), vhot=("_vhot", "sum"), trop=("_trop", "sum"),
        germ=("_germ", "sum"), cold=("_cold", "sum"), dark=("_dark", "sum"),
        tavg=("tavg", "mean"), tmax=("tmax", "max"),
        rain=("rain", "sum"), sun=("sun_hr", "sum"),
    ).reset_index()
    return g.groupby("wk").mean(numeric_only=True).reset_index()


def build_panel(h: int = HORIZON) -> pd.DataFrame:
    t = load_weekly_target()
    w = weekly_weather()
    p = t.merge(w, on="wk", how="left").sort_values("wk").reset_index(drop=True)

    p["year"] = p["wk"].dt.year
    p["woy"] = p["wk"].dt.week            # 1~53
    p["month"] = p["wk"].dt.start_time.dt.month
    # 계절항 — 주 단위이므로 52주 주기. 월 주기도 같이 둔다(수요 패턴은 월 단위)
    p["woy_sin"] = np.sin(2 * np.pi * p["woy"] / 52)
    p["woy_cos"] = np.cos(2 * np.pi * p["woy"] / 52)
    p["woy_sin2"] = np.sin(4 * np.pi * p["woy"] / 52)
    p["woy_cos2"] = np.cos(4 * np.pi * p["woy"] / 52)
    p["month_sin"] = np.sin(2 * np.pi * p["month"] / 12)
    p["month_cos"] = np.cos(2 * np.pi * p["month"] / 12)

    # 가격 시차 — 전부 t-h 이전
    p["lag_h"] = p["price"].shift(h)
    p["lag_h2"] = p["price"].shift(h + 1)
    p["lag_h4"] = p["price"].shift(h + 3)
    p["lag52"] = p["price"].shift(52)
    p["roll4"] = p["price"].shift(h).rolling(4).mean()
    p["roll8"] = p["price"].shift(h).rolling(8).mean()
    p["qty_log_l"] = np.log(p["qty"].replace(0, np.nan)).shift(h)
    p["jjong_rel_l"] = (p["price_jjong"] / p["price"]).shift(h)
    # 모멘텀 — 주간에서만 의미 있는 성분
    p["mom_h"] = np.log(p["price"].shift(h)) - np.log(p["price"].shift(h + 1))
    p["mom_h4"] = np.log(p["price"].shift(h)) - np.log(p["price"].shift(h + 3))

    # 기상 시차. 주 단위이므로 생리 시차를 주로 환산한다
    #   추대·고온장해  생육 후기      -> 2~4주 전
    #   발아 저해      파종기          -> 6~8주 전
    #   광 부족        생육 전 기간    -> 1~4주 전
    for c in ("hot", "vhot", "trop", "germ", "cold", "dark", "tavg", "rain", "sun"):
        for L in (0, 2, 4, 6, 8):
            p[f"{c}_l{L}"] = p[c].shift(h + L)
        p[f"{c}_m4"] = p[c].shift(h).rolling(4).mean()   # 최근 4주 누적
        p[f"{c}_m8"] = p[c].shift(h).rolling(8).mean()
    return p


CORE = ["woy_sin", "woy_cos", "woy_sin2", "woy_cos2"]
PRICE_L = ["lag_h", "lag_h2", "lag_h4", "lag52", "roll4"]

FEATURE_SETS: dict[str, list[str]] = {
    "계절만":      CORE,
    "가격시차":    CORE + PRICE_L,
    "+모멘텀":     CORE + PRICE_L + ["mom_h", "mom_h4"],
    "+고온(2~4주)": CORE + PRICE_L + ["vhot_l2", "vhot_l4", "hot_m4"],
    "+발아(6~8주)": CORE + PRICE_L + ["germ_l6", "germ_l8"],
    "+광":         CORE + PRICE_L + ["dark_m4", "sun_m4"],
    "+기상전부":   CORE + PRICE_L + ["vhot_l2", "vhot_l4", "hot_m4",
                                    "germ_l6", "germ_l8", "dark_m4", "sun_m4",
                                    "trop_l2", "cold_l2", "rain_m4"],
    "+물량":       CORE + PRICE_L + ["qty_log_l"],
    "+쫑상추":     CORE + PRICE_L + ["jjong_rel_l"],
    "전부":        CORE + PRICE_L + ["mom_h", "mom_h4", "vhot_l2", "vhot_l4",
                                    "germ_l6", "dark_m4", "qty_log_l", "jjong_rel_l"],
}


# ═══════════════════════════════════════════════════════════════
# 모형 — lettuce_cv와 동일 구조 + 스미어링
# ═══════════════════════════════════════════════════════════════

def mape(a, f) -> float:
    a, f = np.asarray(a, float), np.asarray(f, float)
    m = np.isfinite(a) & np.isfinite(f) & (a != 0)
    return float(np.mean(np.abs((a[m] - f[m]) / a[m])) * 100) if m.any() else np.nan


def rmsle(a, f) -> float:
    a, f = np.asarray(a, float), np.asarray(f, float)
    m = np.isfinite(a) & np.isfinite(f) & (a > 0) & (f > 0)
    return float(np.sqrt(np.mean((np.log(f[m]) - np.log(a[m])) ** 2))) if m.any() else np.nan


def seasonal_baseline(train: pd.DataFrame, target_woy: pd.Series) -> np.ndarray:
    """학습구간 '주차별' 평균. 월간의 달력월 평균에 대응."""
    wavg = train.groupby("woy")["price"].mean()
    fb = train["price"].mean()
    return np.array([wavg.get(w, fb) for w in target_woy])


def fit_predict(train, test, cols, alpha, blend, smear=True) -> np.ndarray:
    med = train[cols].median(numeric_only=True)
    X = train[cols].fillna(med)
    y = np.log(train["price"])
    mod = make_pipeline(StandardScaler(), Ridge(alpha=alpha)).fit(X, y)
    reg = np.exp(mod.predict(test[cols].fillna(med)))
    if smear:
        # Duan 스미어링 — 학습 잔차의 exp 평균. 로그 역변환 편향 교정
        reg = reg * float(np.mean(np.exp(y - mod.predict(X))))
    lo, hi = train["price"].min() / 3, train["price"].max() * 3
    reg = np.clip(reg, lo, hi)
    base = seasonal_baseline(train, test["woy"])
    return blend * base + (1 - blend) * reg


def tune(train, cols) -> tuple[float, float]:
    yrs = sorted(train["year"].unique())
    inner = [y for y in yrs[1:] if (train["year"] < y).sum() >= MIN_TRAIN]
    if len(inner) < 2:
        return 1.0, 0.2
    best, best_s = (1.0, 0.2), np.inf
    for a in ALPHAS:
        for b in BLENDS:
            errs = []
            for y in inner:
                tr = train[train["year"] < y].dropna(subset=["price"])
                te = train[train["year"] == y].dropna(subset=["price"])
                if len(tr) < MIN_TRAIN or te.empty:
                    continue
                errs.append(mape(te["price"].values, fit_predict(tr, te, cols, a, b)))
            if errs and np.mean(errs) < best_s:
                best_s, best = float(np.mean(errs)), (a, b)
    return best


def walk_forward(p, cols, years=None) -> pd.DataFrame:
    years = years or TEST_YEARS
    rows = []
    for y in years:
        tr = p[p["year"] < y].dropna(subset=["price"] + cols[:1])
        te = p[p["year"] == y].dropna(subset=["price"])
        if len(tr) < MIN_TRAIN or te.empty:
            continue
        a, b = tune(tr, cols)
        pred = fit_predict(tr, te, cols, a, b)
        base = seasonal_baseline(tr, te["woy"])
        rows.append({"year": y, "n_train": len(tr), "n_test": len(te),
                     "alpha": a, "blend": b,
                     "baseline": mape(te["price"].values, base),
                     "model": mape(te["price"].values, pred),
                     "rmsle": rmsle(te["price"].values, pred)})
    return pd.DataFrame(rows)


def block_bootstrap(p, cols_a, cols_b, n=400, seed=0):
    ra, rb = walk_forward(p, cols_a), walk_forward(p, cols_b)
    m = ra.merge(rb, on="year", suffixes=("_a", "_b"))
    diff = (m["model_a"] - m["model_b"]).values
    if len(diff) < 3:
        return np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    boots = [rng.choice(diff, len(diff), replace=True).mean() for _ in range(n)]
    return float(diff.mean()), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


# ═══════════════════════════════════════════════════════════════

def cmd_baseline(p) -> None:
    t = p.dropna(subset=["price"])
    print("=" * 78)
    print("주간 타깃 점검")
    print("=" * 78)
    print(f"  구간 {t['wk'].min()} ~ {t['wk'].max()}  ({len(t)}주, 결측 {p['price'].isna().sum()}주)")
    print(f"  가격 중앙 {t['price'].median():,.0f}  최소 {t['price'].min():,.0f}"
          f"  최대 {t['price'].max():,.0f}")
    print(f"  주당 거래일 중앙 {t['n_days'].median():.0f}일, 레코드 중앙 {t['n_obs'].median():,.0f}건")
    print()
    r = walk_forward(p, CORE)
    print("  주차평균 베이스라인 (fold별)")
    print("    " + "  ".join(f"{int(x.year)}:{x.baseline:.1f}%" for _, x in r.iterrows()))
    print(f"    평균 {r['baseline'].mean():.2f}%   (참고: 월간 계절평균 25.45%)")


def cmd_compare(p) -> None:
    print("=" * 78)
    print(f"주간 피처집합 비교 — h={HORIZON}주, walk-forward {TEST_YEARS}")
    print("=" * 78)
    print(f"  {'피처집합':<16}{'모델':>8}{'베이스':>8}{'개선':>8}{'RMSLE':>8}{'승':>6}")
    res = {}
    for name, cols in FEATURE_SETS.items():
        miss = [c for c in cols if c not in p.columns]
        if miss:
            print(f"  {name:<16} 컬럼없음 {miss[:2]}")
            continue
        r = walk_forward(p, cols)
        if r.empty:
            continue
        res[name] = r
        w = int((r["model"] < r["baseline"]).sum())
        print(f"  {name:<16}{r['model'].mean():>7.2f}%{r['baseline'].mean():>7.2f}%"
              f"{r['baseline'].mean()-r['model'].mean():>+7.2f}%{r['rmsle'].mean():>8.4f}"
              f"{w:>4}/{len(r)}")
    pd.concat([v.assign(featureset=k) for k, v in res.items()]).to_csv(
        OUT / "lettuce_weekly_compare.csv", index=False, encoding="utf-8-sig")

    print()
    print("  블록 부트스트랩 — '가격시차' 대비 95% 구간")
    ref = FEATURE_SETS["가격시차"]
    for name in [k for k in FEATURE_SETS if k not in ("계절만", "가격시차")]:
        if name not in res:
            continue
        d, lo, hi = block_bootstrap(p, FEATURE_SETS[name], ref)
        v = "개선" if hi < 0 else ("악화" if lo > 0 else "판정불가")
        print(f"    {name:<16}{d:>+7.2f}%p  [{lo:+.2f}, {hi:+.2f}]  {v}")


def cmd_horizon() -> None:
    print("=" * 78)
    print("예측 지평별 — 몇 주 앞까지 유효한가")
    print("=" * 78)
    print(f"  {'지평':<8}{'계절평균':>10}{'가격시차':>10}{'개선':>9}{'RMSLE':>9}{'승':>6}")
    for h in (1, 2, 4, 8, 12):
        p = build_panel(h)
        r = walk_forward(p, CORE + PRICE_L)
        if r.empty:
            continue
        w = int((r["model"] < r["baseline"]).sum())
        print(f"  {str(h)+'주':<8}{r['baseline'].mean():>9.2f}%{r['model'].mean():>9.2f}%"
              f"{r['baseline'].mean()-r['model'].mean():>+8.2f}%{r['rmsle'].mean():>9.4f}"
              f"{w:>4}/{len(r)}")
    print()
    print("  참고: 월간 h=1개월(약 4주)  계절평균 25.45% / 가격시차 23.28%")


def cmd_holdout(p) -> None:
    print("=" * 78)
    print(f"독립 홀드아웃 {HOLDOUT_YEAR}")
    print("=" * 78)
    tr = p[p["year"] < HOLDOUT_YEAR].dropna(subset=["price"])
    te = p[p["year"] == HOLDOUT_YEAR].dropna(subset=["price"])
    if te.empty:
        sys.exit("홀드아웃 없음")
    print(f"  학습 {len(tr)}주 / 검증 {len(te)}주")
    base = seasonal_baseline(tr, te["woy"])
    print(f"  {'피처집합':<16}{'MAPE':>8}{'RMSLE':>9}{'vs계절평균':>11}")
    print(f"  {'계절평균':<16}{mape(te['price'].values, base):>7.2f}%"
          f"{rmsle(te['price'].values, base):>9.4f}")
    for name, cols in FEATURE_SETS.items():
        if any(c not in p.columns for c in cols):
            continue
        a, b = tune(tr, cols)
        pr = fit_predict(tr, te, cols, a, b)
        print(f"  {name:<16}{mape(te['price'].values, pr):>7.2f}%"
              f"{rmsle(te['price'].values, pr):>9.4f}"
              f"{mape(te['price'].values, base)-mape(te['price'].values, pr):>+10.2f}%")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["baseline", "compare", "horizon", "holdout"])
    a = ap.parse_args()
    if a.cmd == "horizon":
        cmd_horizon()
        return
    p = build_panel()
    {"baseline": cmd_baseline, "compare": cmd_compare, "holdout": cmd_holdout}[a.cmd](p)


if __name__ == "__main__":
    main()
