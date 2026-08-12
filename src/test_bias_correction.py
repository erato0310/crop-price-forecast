# -*- coding: utf-8 -*-
"""test_bias_correction.py — 구조적 과소예측(-11%)을 교정할 수 있는가.

────────────────────────────────────────────────────────────────
관찰
────────────────────────────────────────────────────────────────
out-of-fold 부호 오차가 12개월 중 10개월에서 음수다.

    1월 -23.9  3월 -19.9  4월 -12.1  7월 -26.6  8월 -15.0  9월 -16.5  12월 -20.1
    (평균 약 -11%)

일관된 부호 = 구조적 편향 = 고칠 수 있다는 뜻이다. 다만 원인이 둘이고
**방향이 반대**라 그냥 올리면 안 된다.

  (1) 로그 역변환 편향
      모형은 log(price)에 적합하고 exp로 되돌린다. 그런데
      E[y] = exp(mu + sigma^2/2) > exp(mu) = exp(E[log y]) 이므로
      exp(예측)은 **평균을 체계적으로 과소평가**한다(Jensen).
      -> 올려야 맞다.

  (2) MAPE의 비대칭
      MAPE = E|A-f|/A 를 최소화하는 f는 **1/A 가중 중앙값**이다.
      작은 A에 큰 가중이 실리므로 최적해가 아래로 당겨진다.
      즉 -11% 편향의 일부는 'MAPE를 잘 최소화한 결과'일 수 있다.
      -> 올리면 MAPE는 나빠진다.

따라서 MAPE 하나로 판정하면 안 된다. 아래 네 지표를 같이 본다.

    MAPE     기존 지표 (고가월에 지배됨)
    RMSLE    로그공간 제곱오차 — 비율 오차를 대칭으로 취급
    편향     평균 부호오차 — 0에 가까울수록 좋다
    MdAPE    중앙 절대비율오차 — 이상치에 강건

────────────────────────────────────────────────────────────────
검정할 교정법
────────────────────────────────────────────────────────────────
  none        교정 없음 (현행)
  smearing    Duan 스미어링. exp(mu) * mean(exp(잔차)).
              잔차 분포를 가정하지 않는 비모수 보정. **학습구간에서만 추정**
  analytic    exp(mu + s^2/2). 잔차 정규성 가정
  calib       학습구간 out-of-sample 예측의 평균 비율로 곱셈 보정
  q55~q70     분위수회귀. 중앙값 대신 상위 분위를 예측해 급등을 따라감

전부 **학습구간 정보만** 사용한다. 검증 fold를 보고 조정하면 누출이다.

[실행] python test_bias_correction.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge, QuantileRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import lettuce_cv as CV

_ROOT = Path(__file__).resolve().parent.parent
OUT = _ROOT / "outputs"

FEATS = CV.FEATURE_SETS["가격시차"]


# ── 지표 ───────────────────────────────────────────────────────
def metrics(actual, pred) -> dict:
    a, f = np.asarray(actual, float), np.asarray(pred, float)
    m = np.isfinite(a) & np.isfinite(f) & (a > 0) & (f > 0)
    a, f = a[m], f[m]
    ape = np.abs(f / a - 1) * 100
    return {
        "MAPE": float(ape.mean()),
        "MdAPE": float(np.median(ape)),
        "RMSLE": float(np.sqrt(np.mean((np.log(f) - np.log(a)) ** 2))),
        "bias": float(((f / a - 1) * 100).mean()),
        "over": float((f > a).mean() * 100),      # 과대예측 비율. 50%면 중립
    }


# ── 예측기 ─────────────────────────────────────────────────────
def _fit_log_ridge(train, cols, alpha):
    med = train[cols].median(numeric_only=True)
    X = train[cols].fillna(med)
    mod = make_pipeline(StandardScaler(), Ridge(alpha=alpha)).fit(
        X, np.log(train["price"]))
    return mod, med


def predict(train, test, cols, alpha, blend, method="none") -> np.ndarray:
    """CV.fit_predict와 같되 로그->원 변환 단계에 교정을 넣는다."""
    if method.startswith("q"):
        q = int(method[1:]) / 100
        med = train[cols].median(numeric_only=True)
        X = train[cols].fillna(med)
        mod = make_pipeline(
            StandardScaler(),
            QuantileRegressor(quantile=q, alpha=alpha / len(X), solver="highs"),
        ).fit(X, np.log(train["price"]))
        reg = np.exp(mod.predict(test[cols].fillna(med)))
    else:
        mod, med = _fit_log_ridge(train, cols, alpha)
        mu = mod.predict(test[cols].fillna(med))
        reg = np.exp(mu)
        if method == "smearing":
            # Duan(1983). 학습 잔차의 exp 평균. 분포 가정 없음
            res = np.log(train["price"]) - mod.predict(train[cols].fillna(med))
            reg = reg * np.mean(np.exp(res))
        elif method == "analytic":
            res = np.log(train["price"]) - mod.predict(train[cols].fillna(med))
            reg = reg * np.exp(np.var(res) / 2)
        elif method == "calib":
            # 학습구간 내부 walk-forward 예측의 평균 실제/예측 비율
            ratios = []
            yrs = sorted(train["ym"].dt.year.unique())
            for y in yrs[1:]:
                tr = train[train["ym"].dt.year < y].dropna(subset=["price"])
                te = train[train["ym"].dt.year == y].dropna(subset=["price"])
                if len(tr) < CV.MIN_TRAIN or te.empty:
                    continue
                m2, md2 = _fit_log_ridge(tr, cols, alpha)
                pr = np.exp(m2.predict(te[cols].fillna(md2)))
                ratios.append(np.mean(te["price"].values / pr))
            if ratios:
                reg = reg * float(np.mean(ratios))

    lo, hi = train["price"].min() / 3, train["price"].max() * 3
    reg = np.clip(reg, lo, hi)
    base = CV.seasonal_baseline(train, test["ym"])
    return blend * base + (1 - blend) * reg


def oof(p, cols, method) -> pd.DataFrame:
    out = []
    for y in CV.TEST_YEARS:
        tr = p[p["ym"].dt.year < y].dropna(subset=["price"])
        te = p[p["ym"].dt.year == y].dropna(subset=["price"])
        if len(tr) < CV.MIN_TRAIN or te.empty:
            continue
        a, b = CV.tune(tr, cols)
        out.append(pd.DataFrame({
            "year": y, "ym": te["ym"].values, "month": te["month"].values,
            "actual": te["price"].values,
            "pred": predict(tr, te, cols, a, b, method),
        }))
    return pd.concat(out, ignore_index=True)


METHODS = ["none", "smearing", "analytic", "calib", "q55", "q60", "q65", "q70"]


def main() -> None:
    p = CV.build_panel()

    print("=" * 80)
    print("1. 교정법별 성적 (out-of-fold, 2020~2025)")
    print("=" * 80)
    print("   MAPE는 과소예측을 선호하므로, 편향 교정이 MAPE를 악화시키는 것은 정상이다.")
    print("   RMSLE·편향·과대예측비율을 같이 봐야 한다.")
    print(f"   {'교정법':<10}{'MAPE':>8}{'MdAPE':>8}{'RMSLE':>9}{'편향%':>8}{'과대%':>7}")
    res = {}
    for m in METHODS:
        try:
            d = oof(p, FEATS, m)
        except Exception as e:
            print(f"   {m:<10} 실패: {str(e)[:40]}")
            continue
        res[m] = d
        s = metrics(d["actual"], d["pred"])
        print(f"   {m:<10}{s['MAPE']:>7.2f}%{s['MdAPE']:>7.2f}%{s['RMSLE']:>9.4f}"
              f"{s['bias']:>+7.1f}%{s['over']:>6.0f}%")

    print()
    print("=" * 80)
    print("2. 월별 부호오차 — 편향이 실제로 줄었나 (양수=과대예측)")
    print("=" * 80)
    print("   " + " " * 11 + " ".join(f"{m:>6d}" for m in range(1, 13)) + f"{'평균':>8}")
    for m in ["none", "smearing", "calib", "q65"]:
        if m not in res:
            continue
        d = res[m]
        g = ((d["pred"] / d["actual"] - 1) * 100).groupby(d["month"]).mean()
        print(f"   {m:<11}" + " ".join(f"{g.get(x, np.nan):+6.1f}" for x in range(1, 13))
              + f"{g.mean():>+8.1f}")

    print()
    print("=" * 80)
    print("3. 급등월에서 실제로 따라가는가 (실제가 전월의 1.5배 이상인 달)")
    print("=" * 80)
    d0 = res["none"].copy()
    d0 = d0.sort_values("ym").reset_index(drop=True)
    d0["prev"] = p.set_index(p["ym"].astype(str)).reindex(
        d0["ym"].astype(str))["lag_h"].values
    spike = d0["actual"] / d0["prev"] > 1.5
    idx = d0.index[spike]
    print(f"   급등월 {len(idx)}개")
    print(f"   {'교정법':<10}{'급등월 MAPE':>12}{'급등월 편향':>12}{'평시 MAPE':>11}")
    for m in METHODS:
        if m not in res:
            continue
        d = res[m].sort_values("ym").reset_index(drop=True)
        sm = metrics(d.loc[idx, "actual"], d.loc[idx, "pred"])
        nm = metrics(d.loc[~d.index.isin(idx), "actual"],
                     d.loc[~d.index.isin(idx), "pred"])
        print(f"   {m:<10}{sm['MAPE']:>11.2f}%{sm['bias']:>+11.1f}%{nm['MAPE']:>10.2f}%")

    print()
    print("=" * 80)
    print("4. 독립 홀드아웃 2026")
    print("=" * 80)
    tr = p[p["ym"].dt.year < CV.HOLDOUT_YEAR].dropna(subset=["price"])
    te = p[p["ym"].dt.year == CV.HOLDOUT_YEAR].dropna(subset=["price"])
    a, b = CV.tune(tr, FEATS)
    print(f"   {'교정법':<10}{'MAPE':>8}{'RMSLE':>9}{'편향%':>8}")
    base = CV.seasonal_baseline(tr, te["ym"])
    s = metrics(te["price"].values, base)
    print(f"   {'계절평균':<10}{s['MAPE']:>7.2f}%{s['RMSLE']:>9.4f}{s['bias']:>+7.1f}%")
    for m in METHODS:
        try:
            pr = predict(tr, te, FEATS, a, b, m)
        except Exception:
            continue
        s = metrics(te["price"].values, pr)
        print(f"   {m:<10}{s['MAPE']:>7.2f}%{s['RMSLE']:>9.4f}{s['bias']:>+7.1f}%")

    pd.concat([v.assign(method=k) for k, v in res.items()]).to_csv(
        OUT / "bias_correction_oof.csv", index=False, encoding="utf-8-sig")
    print()
    print("저장: outputs/bias_correction_oof.csv")


if __name__ == "__main__":
    main()
