# -*- coding: utf-8 -*-
"""compare_target_definitions.py — 타깃 정의를 바꾸면 정확도가 얼마나 달라지는가.

────────────────────────────────────────────────────────────────
왜 필요한가
────────────────────────────────────────────────────────────────
HANDOFF_rev2는 6-fold CV에서 계절평균 32.31% / 모델 27.82%를 보고했다.
지금 파이프라인은 계절평균 25.45% / 모델 23.28%다. 그냥 비교하면
"7%p 좋아졌다"가 되는데, **타깃 자체가 달라서 그렇게 말하면 안 된다.**

rev2와 현행 사이에는 서로 다른 축이 세 개 얽혀 있다.

  (1) 표본     매월 5·15·25일 3일  vs  전 거래일 23~27일
  (2) 기준     시장 위치(전주·익산·정읍 3곳)  vs  산지(plor_nm, 23개 시장)
  (3) 단위     상자단가(avgprc)  vs  원/kg + 주력 품종만

이 파일은 축을 하나씩만 바꿔 가며 순수 효과를 분리한다. 전부 **같은 원자료
(lettuce_daily_raw.csv)** 에서 만들므로 수집 시점·시장 목록 차이가 개입하지 않는다.

────────────────────────────────────────────────────────────────
해석 주의 — MAPE는 타깃이 다르면 직접 비교가 안 된다
────────────────────────────────────────────────────────────────
변동성이 큰 타깃은 MAPE가 자동으로 커진다. 그래서 절대 MAPE보다
**계절평균 대비 개선폭**을 같이 봐야 한다. 그리고 3일 표본 타깃의 MAPE는
'잡음 낀 값을 맞히는 정확도'라 애초에 의미가 다르다 — 그래서 아래 (C)에서
**학습만 잡음으로 하고 평가는 참값으로** 하는 교차 실험을 따로 둔다.

[실행] python compare_target_definitions.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import lettuce_cv as CV
from scrape_lettuce_daily import MAIN_VARIETIES

_ROOT = Path(__file__).resolve().parent.parent
SRC = _ROOT / "data" / "raw" / "lettuce_daily_raw.csv"
OUT = _ROOT / "outputs"

SAMPLE_DAYS = (5, 15, 25)
JEONBUK_MARKETS = {"350101", "350301", "350402"}   # 전주·익산·정읍 = rev2의 TARGET
FEATS = CV.FEATURE_SETS["가격시차"]


def _wavg(g, p, q):
    x = g[[p, q]].dropna()
    t = x[q].sum()
    return (x[p] * x[q]).sum() / t if t else np.nan


def build_targets() -> dict[str, pd.DataFrame]:
    d = pd.read_csv(SRC, dtype={"market_cd": str}, low_memory=False)
    d["date"] = pd.to_datetime(d["date"], format="mixed")
    d["ym"] = d["date"].dt.to_period("M")
    d["day"] = d["date"].dt.day

    variants: dict[str, pd.DataFrame] = {}

    def make(name, df, price_col, qty_col):
        rows = []
        for ym, g in df.groupby("ym"):
            rows.append({"ym": ym, "price": _wavg(g, price_col, qty_col),
                         "n_days": g["date"].nunique(), "n_obs": len(g)})
        variants[name] = pd.DataFrame(rows).sort_values("ym").reset_index(drop=True)

    origin = d[d["county"].notna()]
    origin_main = origin[origin["variety"].isin(MAIN_VARIETIES)]
    market = d[d["market_cd"].isin(JEONBUK_MARKETS)]        # 산지 무관 = rev2 방식

    # 축 (1) 표본 — 나머지 고정(산지·원/kg·주력)
    make("A 현행: 전일자·산지·원/kg·주력", origin_main, "price_kg", "qty_kg")
    make("B 3일표본·산지·원/kg·주력",
         origin_main[origin_main["day"].isin(SAMPLE_DAYS)], "price_kg", "qty_kg")

    # 축 (2) 기준 — 전일자·상자단가 고정
    make("C 전일자·시장위치·상자단가", market, "price", "qty")
    make("D 전일자·산지·상자단가", origin, "price", "qty")

    # 축 (3) 단위/품종
    make("E 전일자·산지·원/kg·전품종", origin, "price_kg", "qty_kg")

    # rev2 원형 재현 — 3일표본 + 시장위치 + 상자단가
    make("F rev2원형: 3일·시장위치·상자단가",
         market[market["day"].isin(SAMPLE_DAYS)], "price", "qty")
    return variants


def evaluate(t: pd.DataFrame, label: str) -> dict:
    """lettuce_cv와 동일한 walk-forward 절차. 타깃만 갈아끼운다."""
    p = t.copy()
    p["month"] = p["ym"].dt.month
    p["month_sin"] = np.sin(2 * np.pi * p["month"] / 12)
    p["month_cos"] = np.cos(2 * np.pi * p["month"] / 12)
    h = CV.HORIZON
    p["lag_h"] = p["price"].shift(h)
    p["lag12"] = p["price"].shift(12)
    p["roll3"] = p["price"].shift(h).rolling(3).mean()
    cur = pd.Timestamp.today().to_period("M")
    p = p[(p["ym"] != cur) | (p["n_days"] >= 18)]

    r = CV.walk_forward(p, FEATS)
    ho_tr = p[p["ym"].dt.year < CV.HOLDOUT_YEAR].dropna(subset=["price"])
    ho_te = p[p["ym"].dt.year == CV.HOLDOUT_YEAR].dropna(subset=["price"])
    ho_m = ho_b = np.nan
    if not ho_te.empty and len(ho_tr) >= CV.MIN_TRAIN:
        a, b = CV.tune(ho_tr, FEATS)
        ho_m = CV.mape(ho_te["price"].values, CV.fit_predict(ho_tr, ho_te, FEATS, a, b))
        ho_b = CV.mape(ho_te["price"].values,
                       CV.seasonal_baseline(ho_tr, ho_te["ym"]))
    return {"target": label, "n_months": int(p["price"].notna().sum()),
            "cv_base": r["baseline"].mean(), "cv_model": r["model"].mean(),
            "cv_gain": r["baseline"].mean() - r["model"].mean(),
            "wins": f"{int((r['model'] < r['baseline']).sum())}/{len(r)}",
            "ho_base": ho_b, "ho_model": ho_m}


def cross_experiment(v: dict[str, pd.DataFrame]) -> None:
    """학습은 3일 표본으로, 평가는 전일자 참값으로 — 잡음 입력의 순수 손해."""
    print()
    print("=" * 80)
    print("C. 교차 실험 — 잡음 낀 자료로 배우면 참값 예측이 얼마나 나빠지나")
    print("=" * 80)
    a = v["A 현행: 전일자·산지·원/kg·주력"].set_index("ym")
    b = v["B 3일표본·산지·원/kg·주력"].set_index("ym")
    ym = a.index.intersection(b.index)

    def panel(src):
        p = src.loc[ym].reset_index()
        p["month"] = p["ym"].dt.month
        p["month_sin"] = np.sin(2 * np.pi * p["month"] / 12)
        p["month_cos"] = np.cos(2 * np.pi * p["month"] / 12)
        p["lag_h"] = p["price"].shift(CV.HORIZON)
        p["lag12"] = p["price"].shift(12)
        p["roll3"] = p["price"].shift(CV.HORIZON).rolling(3).mean()
        return p

    pa, pb = panel(a), panel(b)
    truth = pa["price"].values
    rows = []
    for lbl, src in [("전일자로 학습", pa), ("3일표본으로 학습", pb)]:
        errs, bases = [], []
        for y in CV.TEST_YEARS:
            m_tr = src["ym"].dt.year < y
            m_te = src["ym"].dt.year == y
            tr = src[m_tr].dropna(subset=["price"])
            te = src[m_te].dropna(subset=["price"])
            if len(tr) < CV.MIN_TRAIN or te.empty:
                continue
            al, bl = CV.tune(tr, FEATS)
            pred = CV.fit_predict(tr, te, FEATS, al, bl)
            base = CV.seasonal_baseline(tr, te["ym"])
            # ** 평가는 항상 참값(전일자)으로 **
            act = truth[m_te.values][: len(pred)]
            errs.append(CV.mape(act, pred))
            bases.append(CV.mape(act, base))
        rows.append({"학습자료": lbl, "모델": np.mean(errs), "계절평균": np.mean(bases)})
    r = pd.DataFrame(rows)
    print(f"  {'학습자료':<16}{'모델':>9}{'계절평균':>10}   (평가는 둘 다 전일자 참값)")
    for _, x in r.iterrows():
        print(f"  {x['학습자료']:<16}{x['모델']:>8.2f}%{x['계절평균']:>9.2f}%")
    d_m = r.loc[1, "모델"] - r.loc[0, "모델"]
    d_b = r.loc[1, "계절평균"] - r.loc[0, "계절평균"]
    print()
    print(f"  -> 3일 표본으로 배우면 모델이 {d_m:+.2f}%p, 계절평균이 {d_b:+.2f}%p 나빠진다.")
    print(f"     이게 '수집 방식만 바꿔서 얻은 순수 이득'이다.")


def main() -> None:
    v = build_targets()
    print("=" * 80)
    print("A/B. 타깃 정의별 walk-forward 성적 (피처·절차 완전 동일)")
    print("=" * 80)
    res = [evaluate(t, k) for k, t in v.items()]
    df = pd.DataFrame(res)
    print(f"  {'타깃 정의':<30}{'월수':>5}{'계절평균':>9}{'모델':>8}{'개선':>8}{'승':>6}"
          f"{'2026홀드아웃':>13}")
    for _, r in df.iterrows():
        print(f"  {r['target']:<30}{r['n_months']:>5}{r['cv_base']:>8.2f}%"
              f"{r['cv_model']:>7.2f}%{r['cv_gain']:>+7.2f}%{r['wins']:>6}"
              f"   {r['ho_model']:>5.2f}% (기준 {r['ho_base']:.1f}%)")
    df.to_csv(OUT / "target_definition_compare.csv", index=False, encoding="utf-8-sig")

    print()
    print("  축별 순수 효과 (다른 조건 고정)")
    g = df.set_index("target")
    def diff(x, y, name):
        print(f"    {name:<28}계절평균 {g.loc[y,'cv_base']-g.loc[x,'cv_base']:+6.2f}%p"
              f"   모델 {g.loc[y,'cv_model']-g.loc[x,'cv_model']:+6.2f}%p")
    diff("B 3일표본·산지·원/kg·주력", "A 현행: 전일자·산지·원/kg·주력", "표본: 3일 -> 전일자")
    diff("C 전일자·시장위치·상자단가", "D 전일자·산지·상자단가", "기준: 시장위치 -> 산지")
    diff("E 전일자·산지·원/kg·전품종", "A 현행: 전일자·산지·원/kg·주력", "품종: 전체 -> 주력만")
    diff("D 전일자·산지·상자단가", "E 전일자·산지·원/kg·전품종", "단위: 상자 -> 원/kg")
    print("    (음수 = 그 방향으로 바꾸면 오차가 준다)")

    cross_experiment(v)


if __name__ == "__main__":
    main()
