# -*- coding: utf-8 -*-
"""lettuce_probabilistic.py — 점예측을 넘어 확률·방향·구간으로.

────────────────────────────────────────────────────────────────
왜 문제를 다시 정의하는가
────────────────────────────────────────────────────────────────
오차 분해 결과, 남은 오차의 대부분이 **급등월**에 몰려 있고(편향 -30.9%)
그 달들은 전월·전년동월이 실제와 2~3배 어긋난다. 즉 시차 정보로는
**원리적으로 도달 불가**다. 어떤 변수·모형을 넣어도 못 맞힌다.

그렇다면 못 맞히는 것을 억지로 맞히려 하지 말고, **맞힐 수 있는 형태로**
질문을 바꾸는 편이 낫다. 농가가 실제로 묻는 것도 원 단위 정확한 값이 아니다.

  (a) 폭등 확률   "다음 달 평년 대비 1.3배를 넘을 확률은?"
  (b) 방향        "평년보다 비쌀까 쌀까?"
  (c) 예측 구간   "80% 확률로 어느 범위인가?"

이 셋은 점예측과 달리 **틀렸을 때의 손실이 완만**하고, 검증 지표도
정직하다(Brier, AUC, 구간 적중률).

────────────────────────────────────────────────────────────────
검증 규칙
────────────────────────────────────────────────────────────────
- 폭등 기준은 **학습구간의 평년가**로 정의한다. 검증구간 정보를 쓰면 누출이다.
- 반드시 **계절평균만으로 만든 대조군**과 비교한다. HANDOFF_rev2 4.3이
  AUC 0.908을 보고했는데 계절평균만으로도 0.889였다 — 대조군 없이 제시하면
  계절성 효과를 모델 성능으로 오인한다.
- 구간은 **적중률(coverage)** 로 검증한다. 80% 구간이 실제로 80%를 담아야 한다.

[실행]
  python lettuce_probabilistic.py spike     # 폭등 확률
  python lettuce_probabilistic.py direction # 방향 분류
  python lettuce_probabilistic.py interval  # 예측 구간
"""
from __future__ import annotations

import argparse
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

import lettuce_cv as CV

_ROOT = Path(__file__).resolve().parent.parent
OUT = _ROOT / "outputs"

SPIKE_MULT = 1.3          # 평년 대비 배수
FEATS = CV.FEATURE_SETS["가격시차"]


def auc(y: np.ndarray, s: np.ndarray) -> float:
    """ROC AUC. 순위 기반이라 scipy 없이도 계산된다."""
    y = np.asarray(y, int)
    s = np.asarray(s, float)
    m = np.isfinite(s)
    y, s = y[m], s[m]
    if y.sum() == 0 or y.sum() == len(y):
        return np.nan
    order = np.argsort(s)
    ranks = np.empty(len(s), float)
    ranks[order] = np.arange(1, len(s) + 1)
    # 동점 처리
    df = pd.DataFrame({"s": s, "r": ranks})
    ranks = df.groupby("s")["r"].transform("mean").values
    n1, n0 = y.sum(), (1 - y).sum()
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def brier(y, p) -> float:
    y, p = np.asarray(y, float), np.asarray(p, float)
    m = np.isfinite(p)
    return float(np.mean((p[m] - y[m]) ** 2))


def _fold_data(p: pd.DataFrame):
    """fold별 (학습, 검증, 점예측, 계절평균, 로그잔차 표준편차)."""
    for y in CV.TEST_YEARS + [CV.HOLDOUT_YEAR]:
        tr = p[p["ym"].dt.year < y].dropna(subset=["price"])
        te = p[p["ym"].dt.year == y].dropna(subset=["price"])
        if len(tr) < CV.MIN_TRAIN or te.empty:
            continue
        a, b = CV.tune(tr, FEATS)
        pred = CV.fit_predict(tr, te, FEATS, a, b)
        base_te = CV.seasonal_baseline(tr, te["ym"])
        # 학습구간 내부 out-of-sample 잔차로 sigma 추정 (in-sample은 과소평가)
        res = []
        yrs = sorted(tr["ym"].dt.year.unique())
        for iy in yrs[1:]:
            itr = tr[tr["ym"].dt.year < iy].dropna(subset=["price"])
            ite = tr[tr["ym"].dt.year == iy].dropna(subset=["price"])
            if len(itr) < CV.MIN_TRAIN or ite.empty:
                continue
            ia, ib = CV.tune(itr, FEATS)
            ip = CV.fit_predict(itr, ite, FEATS, ia, ib)
            res.extend(np.log(ite["price"].values) - np.log(ip))
        sigma = float(np.std(res)) if len(res) > 5 else 0.35
        yield y, tr, te, pred, base_te, sigma, res


def cmd_spike() -> None:
    p = CV.build_panel()
    print("=" * 80)
    print(f"폭등 확률 — '평년(학습구간 달력월 평균)의 {SPIKE_MULT}배 초과'")
    print("=" * 80)
    rows = []
    for y, tr, te, pred, base_te, sigma, _ in _fold_data(p):
        thr = base_te * SPIKE_MULT                    # 학습구간 평년 기준
        actual = (te["price"].values > thr).astype(int)
        # 모델: 로그정규 가정으로 초과확률
        z = (np.log(thr) - np.log(pred)) / sigma
        prob = 1 - _norm_cdf(z)
        # 대조군 1: 계절평균만 (점예측=평년) -> 확률은 상수 = 계절성만 반영
        z_b = (np.log(thr) - np.log(base_te)) / sigma
        prob_b = 1 - _norm_cdf(z_b)
        # 대조군 2: 달력월별 과거 폭등 빈도
        hist = tr.copy()
        hb = CV.seasonal_baseline(tr, hist["ym"])
        hist["spk"] = (hist["price"].values > hb * SPIKE_MULT).astype(int)
        freq = hist.groupby(hist["ym"].dt.month)["spk"].mean()
        prob_f = np.array([freq.get(m.month, hist["spk"].mean()) for m in te["ym"]])
        rows.append(pd.DataFrame({
            "year": y, "ym": te["ym"].astype(str).values, "month": te["month"].values,
            "actual": actual, "prob_model": prob, "prob_base": prob_b,
            "prob_freq": prob_f, "price": te["price"].values, "thr": thr,
        }))
    d = pd.concat(rows, ignore_index=True)
    d.to_csv(OUT / "spike_probability.csv", index=False, encoding="utf-8-sig")

    cv = d[d["year"] < CV.HOLDOUT_YEAR]
    ho = d[d["year"] == CV.HOLDOUT_YEAR]
    print(f"  폭등 발생 {int(cv['actual'].sum())}/{len(cv)}건 "
          f"({cv['actual'].mean()*100:.1f}%)")
    print()
    print(f"  {'':<18}{'AUC':>8}{'Brier':>9}   해석")
    for lbl, col in [("모델", "prob_model"), ("계절평균 대조군", "prob_base"),
                     ("월별 빈도 대조군", "prob_freq")]:
        print(f"  {lbl:<18}{auc(cv['actual'], cv[col]):>8.3f}"
              f"{brier(cv['actual'], cv[col]):>9.4f}")
    gain = auc(cv["actual"], cv["prob_model"]) - auc(cv["actual"], cv["prob_base"])
    print(f"  -> 모델 순기여 AUC {gain:+.3f}")

    print()
    print("  월별 폭등 발생률 (계절성이 얼마나 설명하는가)")
    g = cv.groupby("month")["actual"].agg(["sum", "count", "mean"])
    print("    " + " ".join(f"{m:>6d}" for m in range(1, 13)))
    print("    " + " ".join(f"{g['mean'].get(m, 0)*100:5.0f}%" for m in range(1, 13)))

    print()
    print("  확률 구간별 실제 발생률 (보정 상태)")
    cv2 = cv.copy()
    cv2["bin"] = pd.cut(cv2["prob_model"], [0, .1, .25, .5, .75, 1.0])
    cal = cv2.groupby("bin", observed=True)["actual"].agg(["mean", "count"])
    for b, r in cal.iterrows():
        print(f"    {str(b):<14} 실제 {r['mean']*100:5.1f}%  (n={int(r['count'])})")

    if not ho.empty:
        print()
        print(f"  홀드아웃 {CV.HOLDOUT_YEAR}: 폭등 {int(ho['actual'].sum())}건 / "
              f"AUC {auc(ho['actual'], ho['prob_model']):.3f} "
              f"(대조군 {auc(ho['actual'], ho['prob_base']):.3f})")


def _norm_cdf(z):
    from math import erf, sqrt
    z = np.asarray(z, float)
    return np.array([0.5 * (1 + erf(v / sqrt(2))) for v in z.ravel()]).reshape(z.shape)


def cmd_direction() -> None:
    p = CV.build_panel()
    print("=" * 80)
    print("방향 분류 — '평년보다 비쌀 것인가'")
    print("=" * 80)
    rows = []
    for y, tr, te, pred, base_te, sigma, _ in _fold_data(p):
        actual = (te["price"].values > base_te).astype(int)
        prob = 1 - _norm_cdf((np.log(base_te) - np.log(pred)) / sigma)
        rows.append(pd.DataFrame({
            "year": y, "month": te["month"].values, "actual": actual,
            "prob": prob, "pred_up": (pred > base_te).astype(int),
        }))
    d = pd.concat(rows, ignore_index=True)
    cv = d[d["year"] < CV.HOLDOUT_YEAR]
    ho = d[d["year"] == CV.HOLDOUT_YEAR]
    print(f"  실제 상승 {cv['actual'].mean()*100:.1f}%  (동전이면 50%)")
    print(f"  정확도 {(cv['pred_up'] == cv['actual']).mean()*100:.1f}%   "
          f"AUC {auc(cv['actual'], cv['prob']):.3f}   Brier {brier(cv['actual'], cv['prob']):.4f}")
    print()
    print("  연도별 정확도")
    g = cv.groupby("year").apply(lambda x: (x["pred_up"] == x["actual"]).mean() * 100,
                                 include_groups=False)
    print("    " + "  ".join(f"{int(k)}:{v:.0f}%" for k, v in g.items()))
    print()
    print("  월별 정확도")
    gm = cv.groupby("month").apply(lambda x: (x["pred_up"] == x["actual"]).mean() * 100,
                                   include_groups=False)
    print("    " + " ".join(f"{m:>6d}" for m in range(1, 13)))
    print("    " + " ".join(f"{gm.get(m, np.nan):5.0f}%" for m in range(1, 13)))
    if not ho.empty:
        print()
        print(f"  홀드아웃 {CV.HOLDOUT_YEAR}: 정확도 "
              f"{(ho['pred_up'] == ho['actual']).mean()*100:.1f}%  "
              f"AUC {auc(ho['actual'], ho['prob']):.3f}")


def cmd_interval() -> None:
    p = CV.build_panel()
    print("=" * 80)
    print("예측 구간 — 명목 적중률이 실제로 지켜지는가")
    print("=" * 80)
    levels = [0.5, 0.8, 0.9]
    zs = {0.5: 0.6745, 0.8: 1.2816, 0.9: 1.6449}
    rows = []
    for y, tr, te, pred, base_te, sigma, res in _fold_data(p):
        rec = {"year": y, "n": len(te), "sigma": sigma}
        act = te["price"].values
        for lv in levels:
            z = zs[lv]
            lo, hi = pred * np.exp(-z * sigma), pred * np.exp(z * sigma)
            rec[f"cov{int(lv*100)}"] = float(np.mean((act >= lo) & (act <= hi)) * 100)
            rec[f"wid{int(lv*100)}"] = float(np.mean(hi / lo))
            # 경험분위 구간 — 정규 가정 없이 학습 잔차 분위수 사용
            if len(res) > 20:
                ql, qh = np.percentile(res, [(1-lv)/2*100, (1+lv)/2*100])
                lo2, hi2 = pred * np.exp(ql), pred * np.exp(qh)
                rec[f"ecov{int(lv*100)}"] = float(np.mean((act >= lo2) & (act <= hi2)) * 100)
        rows.append(rec)
    d = pd.DataFrame(rows)
    cv = d[d["year"] < CV.HOLDOUT_YEAR]
    print(f"  학습구간 out-of-sample 로그잔차 sigma 중앙 {cv['sigma'].median():.3f}")
    print()
    print(f"  {'명목':<8}{'정규가정 적중':>13}{'경험분위 적중':>14}{'구간 배율':>11}")
    for lv in levels:
        k = int(lv * 100)
        e = cv[f"ecov{k}"].mean() if f"ecov{k}" in cv else np.nan
        print(f"  {k}%{'':<5}{cv[f'cov{k}'].mean():>12.1f}%{e:>13.1f}%"
              f"{cv[f'wid{k}'].mean():>10.1f}배")
    print()
    print("  적중률이 명목보다 낮으면 구간이 좁은 것(과신), 높으면 넓은 것.")
    print()
    print("  연도별 80% 구간 적중률")
    print("    " + "  ".join(f"{int(r.year)}:{r.cov80:.0f}%" for _, r in d.iterrows()))
    d.to_csv(OUT / "interval_coverage.csv", index=False, encoding="utf-8-sig")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["spike", "direction", "interval"])
    a = ap.parse_args()
    {"spike": cmd_spike, "direction": cmd_direction, "interval": cmd_interval}[a.cmd]()


if __name__ == "__main__":
    main()
