# -*- coding: utf-8 -*-
"""compare_model_classes.py — 모형 구조를 바꾸면 좋아지는가.

────────────────────────────────────────────────────────────────
왜 필요한가
────────────────────────────────────────────────────────────────
지금까지 '어떤 변수를 넣을까'만 바꿔 왔고, 모형은 줄곧 하나였다.

    log(price) ~ Ridge(계절항 + 가격시차)  ->  exp  ->  계절평균과 블렌딩

이 구조 자체가 제약일 수 있다. 특히 두 가지가 의심된다.
  - 계절을 sin/cos 두 항으로만 표현한다. 실제 계절 모양은 7~9월에 뾰족한
    비대칭 곡선인데, 저차 조화항으로는 그 봉우리를 못 그린다.
  - 수준(level)이 시간에 따라 변하는 것을 못 따라간다. 2020년 같은 구조 변화
    구간에서 특히 불리하다.

계절차분(SARIMA)이나 상태공간(구조적 시계열)은 두 문제를 다르게 다룬다.
한 번도 안 써 봤으므로 여기서 검정한다.

────────────────────────────────────────────────────────────────
비교 대상
────────────────────────────────────────────────────────────────
  seasonal_mean   계절(월)평균 — 베이스라인
  ridge           현행. 로그 Ridge + 스미어링 + 블렌딩
  sarima          SARIMA(p,d,q)(P,D,Q,12) on log — 계절차분
  ets             지수평활(Holt-Winters, 곱셈 계절)
  theta           Theta 법 — M3 대회 우승 계열, 강력한 단변량 기준선
  structural      비관측성분(국소수준 + 확률적 계절)
  gbm             Gradient Boosting — 비선형·문턱 반응 포착 가능
  rf              Random Forest

전부 **같은 walk-forward**(연도별, 학습구간만 사용)로 돌린다.
외생변수 없이 순수 단변량으로 비교해 '구조'의 효과만 분리한다.

[실행]
  python compare_model_classes.py monthly
  python compare_model_classes.py weekly
"""
from __future__ import annotations

import argparse
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

_ROOT = Path(__file__).resolve().parent.parent
OUT = _ROOT / "outputs"


def mape(a, f) -> float:
    a, f = np.asarray(a, float), np.asarray(f, float)
    m = np.isfinite(a) & np.isfinite(f) & (a != 0)
    return float(np.mean(np.abs((a[m] - f[m]) / a[m])) * 100) if m.any() else np.nan


def rmsle(a, f) -> float:
    a, f = np.asarray(a, float), np.asarray(f, float)
    m = np.isfinite(a) & np.isfinite(f) & (a > 0) & (f > 0)
    return float(np.sqrt(np.mean((np.log(f[m]) - np.log(a[m])) ** 2))) if m.any() else np.nan


# ═══════════════════════════════════════════════════════════════
# 각 모형: (train_series, n_ahead, period) -> 예측 배열
# 전부 로그공간에서 적합하고 exp로 되돌린다(가격은 양수·비율 변동)
# ═══════════════════════════════════════════════════════════════

def m_seasonal_mean(y: pd.Series, n: int, period: int, seas_idx) -> np.ndarray:
    s = pd.Series(y.values, index=seas_idx[: len(y)])
    avg = s.groupby(level=0).mean()
    fb = s.mean()
    return np.array([avg.get(k, fb) for k in seas_idx[len(y): len(y) + n]])


def m_sarima(y: pd.Series, n: int, period: int, seas_idx) -> np.ndarray:
    from statsmodels.tsa.statespace.sarimax import SARIMAX
    ly = np.log(y.values)
    best, best_aic = None, np.inf
    # 작은 격자만 — 표본이 작아 복잡한 모형은 어차피 발산한다
    for order in [(1, 0, 0), (1, 1, 1), (2, 0, 0)]:
        for sorder in [(0, 1, 1, period), (1, 0, 0, period)]:
            try:
                m = SARIMAX(ly, order=order, seasonal_order=sorder,
                            enforce_stationarity=False,
                            enforce_invertibility=False).fit(disp=False)
                if m.aic < best_aic:
                    best_aic, best = m.aic, m
            except Exception:
                continue
    if best is None:
        return np.full(n, np.exp(ly[-1]))
    f = best.forecast(n)
    return np.exp(f)


def m_ets(y: pd.Series, n: int, period: int, seas_idx) -> np.ndarray:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    try:
        m = ExponentialSmoothing(np.log(y.values), trend=None,
                                 seasonal="add", seasonal_periods=period).fit()
        return np.exp(m.forecast(n))
    except Exception:
        return np.full(n, y.values[-1])


def m_theta(y: pd.Series, n: int, period: int, seas_idx) -> np.ndarray:
    from statsmodels.tsa.forecasting.theta import ThetaModel
    try:
        s = pd.Series(np.log(y.values))
        m = ThetaModel(s, period=period, deseasonalize=True).fit()
        return np.exp(m.forecast(n).values)
    except Exception:
        return np.full(n, y.values[-1])


def m_structural(y: pd.Series, n: int, period: int, seas_idx) -> np.ndarray:
    from statsmodels.tsa.statespace.structural import UnobservedComponents
    try:
        m = UnobservedComponents(np.log(y.values), level="local level",
                                 seasonal=period, stochastic_seasonal=True
                                 ).fit(disp=False)
        return np.exp(m.forecast(n))
    except Exception:
        return np.full(n, y.values[-1])


def _tree_matrix(p: pd.DataFrame, cols: list[str]):
    return p[cols]


def m_tree(kind: str):
    def f(train: pd.DataFrame, test: pd.DataFrame, cols: list[str]) -> np.ndarray:
        from sklearn.ensemble import (GradientBoostingRegressor,
                                      RandomForestRegressor)
        med = train[cols].median(numeric_only=True)
        X = train[cols].fillna(med)
        y = np.log(train["price"])
        if kind == "gbm":
            mod = GradientBoostingRegressor(n_estimators=200, max_depth=2,
                                            learning_rate=0.05, subsample=0.8,
                                            random_state=0)
        else:
            mod = RandomForestRegressor(n_estimators=300, max_depth=4,
                                        min_samples_leaf=5, random_state=0,
                                        n_jobs=-1)
        mod.fit(X, y)
        pred = np.exp(mod.predict(test[cols].fillna(med)))
        pred = pred * float(np.mean(np.exp(y - mod.predict(X))))   # 스미어링
        return np.clip(pred, train["price"].min() / 3, train["price"].max() * 3)
    return f


UNIVARIATE = {"seasonal_mean": m_seasonal_mean, "sarima": m_sarima,
              "ets": m_ets, "theta": m_theta, "structural": m_structural}


# ═══════════════════════════════════════════════════════════════

def run(freq: str) -> None:
    if freq == "monthly":
        import lettuce_cv as CV
        p = CV.build_panel().dropna(subset=["price"]).reset_index(drop=True)
        p["ykey"] = p["ym"].dt.year
        seas = p["month"].values
        period = 12
        cols = CV.FEATURE_SETS["가격시차"]
        ridge_fp, ridge_tune = CV.fit_predict, CV.tune
        years = CV.TEST_YEARS
        holdout = CV.HOLDOUT_YEAR
        min_train = CV.MIN_TRAIN
    else:
        import lettuce_weekly as WK
        p = WK.build_panel().dropna(subset=["price"]).reset_index(drop=True)
        p["ykey"] = p["year"]
        seas = p["woy"].values
        period = 52
        cols = WK.CORE + WK.PRICE_L
        ridge_fp, ridge_tune = WK.fit_predict, WK.tune
        years = WK.TEST_YEARS
        holdout = WK.HOLDOUT_YEAR
        min_train = WK.MIN_TRAIN

    print("=" * 80)
    print(f"모형 구조 비교 — {freq}, walk-forward {years}")
    print("=" * 80)
    print(f"  표본 {len(p)}개, 계절주기 {period}")
    print()

    results: dict[str, list] = {k: [] for k in
                                list(UNIVARIATE) + ["ridge", "gbm", "rf"]}
    for y in years:
        tr = p[p["ykey"] < y]
        te = p[p["ykey"] == y]
        if len(tr) < min_train or te.empty:
            continue
        n = len(te)
        yv = tr["price"]
        sidx = np.concatenate([seas[: len(tr)], seas[len(tr): len(tr) + n]])
        act = te["price"].values

        for name, fn in UNIVARIATE.items():
            try:
                pred = fn(yv, n, period, sidx)
            except Exception:
                pred = np.full(n, np.nan)
            results[name].append({"year": y, "mape": mape(act, pred),
                                  "rmsle": rmsle(act, pred)})
        # Ridge (현행)
        a, b = ridge_tune(tr, cols)
        pr = ridge_fp(tr, te, cols, a, b)
        results["ridge"].append({"year": y, "mape": mape(act, pr),
                                 "rmsle": rmsle(act, pr)})
        # 트리
        for k in ("gbm", "rf"):
            pr = m_tree(k)(tr, te, cols)
            results[k].append({"year": y, "mape": mape(act, pr),
                               "rmsle": rmsle(act, pr)})

    print(f"  {'모형':<16}{'MAPE':>9}{'RMSLE':>9}{'최악fold':>10}   fold별 MAPE")
    summ = []
    for name, rs in results.items():
        if not rs:
            continue
        d = pd.DataFrame(rs)
        detail = " ".join(f"{x:.0f}" for x in d["mape"])
        summ.append({"model": name, "mape": d["mape"].mean(),
                     "rmsle": d["rmsle"].mean(), "worst": d["mape"].max()})
        print(f"  {name:<16}{d['mape'].mean():>8.2f}%{d['rmsle'].mean():>9.4f}"
              f"{d['mape'].max():>9.1f}%   {detail}")
    s = pd.DataFrame(summ).sort_values("mape")
    s.to_csv(OUT / f"model_class_{freq}.csv", index=False, encoding="utf-8-sig")

    print()
    print(f"  순위: " + " < ".join(s["model"]))

    # ── 홀드아웃 ────────────────────────────────────────────
    print()
    print("=" * 80)
    print(f"독립 홀드아웃 {holdout}")
    print("=" * 80)
    tr = p[p["ykey"] < holdout]
    te = p[p["ykey"] == holdout]
    if te.empty:
        print("  홀드아웃 없음")
        return
    n = len(te)
    sidx = np.concatenate([seas[: len(tr)], seas[len(tr): len(tr) + n]])
    act = te["price"].values
    print(f"  {'모형':<16}{'MAPE':>9}{'RMSLE':>9}")
    rows = []
    for name, fn in UNIVARIATE.items():
        try:
            pred = fn(tr["price"], n, period, sidx)
        except Exception:
            continue
        rows.append((name, mape(act, pred), rmsle(act, pred)))
    a, b = ridge_tune(tr, cols)
    pr = ridge_fp(tr, te, cols, a, b)
    rows.append(("ridge", mape(act, pr), rmsle(act, pr)))
    for k in ("gbm", "rf"):
        pr = m_tree(k)(tr, te, cols)
        rows.append((k, mape(act, pr), rmsle(act, pr)))
    for nm, mp, rl in sorted(rows, key=lambda x: x[1]):
        print(f"  {nm:<16}{mp:>8.2f}%{rl:>9.4f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("freq", choices=["monthly", "weekly"])
    a = ap.parse_args()
    run(a.freq)


if __name__ == "__main__":
    main()
