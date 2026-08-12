# -*- coding: utf-8 -*-
"""analyze_variety_mix.py — 상추 품종 구성이 '지역 가격차'를 얼마나 만들어내는가.

────────────────────────────────────────────────────────────────
문제
────────────────────────────────────────────────────────────────
katSale의 `gds_mclsf_nm='상추'`는 단일 품목이 아니다. 하위 품종(`gds_sclsf_nm`)이
포기찹·청상추·적포기·쫑상추·청포기·흑적·적상추로 나뉘고 **가격 수준이 다르다**
(2025-09 가락 실측: 포기찹 9,502 / 청상추 8,775 / 쫑상추 3,754 원/kg).

그런데 지금까지 낸 '시군별 가격'은 그 시군 출하량으로 가중한 **품종 혼합 평균**이다.
그래서 두 가지가 섞여 있다.

    지역 가격차 = (구성효과) 어느 품종을 심느냐 + (가격효과) 같은 품종을 얼마에 파느냐

완주 2,790원/kg vs 진안 4,291원/kg 이 1.5배 차이가 "진안 상추가 비싸다"인지
"진안은 비싼 품종을 심는다"인지 구분해야 한다. 전자면 지역 특성이고, 후자면
품종을 통제하지 않은 채 지역을 비교한 오류다.

계절성도 마찬가지다. 전북산 품종 구성이 3월 포기찹 86.3% -> 7월 65.9%로 움직인다.
그러면 여름 가격 상승의 일부는 **실제 가격 상승이 아니라 구성 변화**다.

────────────────────────────────────────────────────────────────
방법
────────────────────────────────────────────────────────────────
1. 품종별 물량·가격·계절 프로파일
2. 시군별 품종 구성
3. 분해 — 각 시군 가격을 전북 평균과 비교해 두 성분으로 나눈다
       구성효과 = sum_v (share_v,region - share_v,전체) * price_v,전체
       가격효과 = sum_v  share_v,전체 * (price_v,region - price_v,전체)
   (교차항은 잔차로 둔다. Oaxaca 분해의 단순형)
4. **고정가중 가격지수** — 품종 구성을 기준기로 고정해 구성 변화 영향을 제거한
   가격 시계열. 모델 타깃 후보다.

[실행] python analyze_variety_mix.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
SRC = _ROOT / "data" / "raw" / "lettuce_daily_raw.csv"
OUT = _ROOT / "outputs"
OUT.mkdir(exist_ok=True)


def wa(g: pd.DataFrame, p="price_kg", q="qty_kg") -> float:
    x = g[[p, q]].dropna()
    t = x[q].sum()
    return (x[p] * x[q]).sum() / t if t else np.nan


def main() -> None:
    d = pd.read_csv(SRC, dtype={"market_cd": str}, low_memory=False)
    d["date"] = pd.to_datetime(d["date"])
    d["month"] = d["date"].dt.month
    d["ym"] = d["date"].dt.to_period("M")
    jb = d[d["county"].notna()].copy()

    print("=" * 80)
    print("1. 품종별 — 전북산 상추 (2018-01~2021-02)")
    print("=" * 80)
    rows = []
    for v, g in jb.groupby("variety"):
        mm = g.groupby("month").apply(wa, include_groups=False)
        rows.append({
            "variety": v, "qty_t": g["qty_kg"].sum() / 1000,
            "share": g["qty_kg"].sum() / jb["qty_kg"].sum() * 100,
            "price_kg": wa(g), "n_rec": len(g),
            "peak_m": int(mm.idxmax()) if mm.notna().any() else 0,
            "peak_p": mm.max(), "low_p": mm.min(),
            "amp": mm.max() / mm.min() if mm.min() else np.nan,
            "n_county": g["county"].nunique(),
        })
    vd = pd.DataFrame(rows).sort_values("qty_t", ascending=False)
    print(f"  {'품종':<8}{'물량t':>9}{'비중':>7}{'원/kg':>8}{'최고월':>7}"
          f"{'최고가':>8}{'최저가':>8}{'진폭':>7}{'출하시군':>7}")
    for _, r in vd.iterrows():
        print(f"  {str(r['variety']):<8}{r['qty_t']:>9,.0f}{r['share']:>6.1f}%"
              f"{r['price_kg']:>8,.0f}{r['peak_m']:>6}월{r['peak_p']:>8,.0f}"
              f"{r['low_p']:>8,.0f}{r['amp']:>6.1f}배{r['n_county']:>7.0f}")
    vd.to_csv(OUT / "variety_summary.csv", index=False, encoding="utf-8-sig")

    top_v = list(vd[vd["share"] >= 1.0]["variety"])

    # ── 2. 시군별 품종 구성 ─────────────────────────────────
    print()
    print("=" * 80)
    print("2. 시군별 품종 구성 (물량 %) — 지역마다 심는 품종이 다른가")
    print("=" * 80)
    order = jb.groupby("county")["qty_kg"].sum().sort_values(ascending=False)
    keep = [c for c in order.index if order[c] / order.sum() > 0.003]
    mix = jb[jb["county"].isin(keep)].pivot_table(
        index="county", columns="variety", values="qty_kg", aggfunc="sum").fillna(0)
    mix = mix.reindex(keep)
    mixs = mix.div(mix.sum(axis=1), axis=0) * 100
    print(f"  {'시군':<8}" + "".join(f"{str(v)[:6]:>8}" for v in top_v) + f"{'원/kg':>9}")
    for c in keep:
        print(f"  {c:<8}" + "".join(f"{mixs.loc[c, v]:>7.1f}%" if v in mixs.columns
                                    else f"{'-':>8}" for v in top_v)
              + f"{wa(jb[jb['county'] == c]):>9,.0f}")

    # ── 3. 분해 ─────────────────────────────────────────────
    print()
    print("=" * 80)
    print("3. 시군 가격차 분해 — 구성효과 vs 가격효과")
    print("=" * 80)
    p_all = {v: wa(jb[jb["variety"] == v]) for v in top_v}
    s_all = {v: jb[jb["variety"] == v]["qty_kg"].sum() / jb["qty_kg"].sum()
             for v in top_v}
    base = sum(s_all[v] * p_all[v] for v in top_v if not np.isnan(p_all[v]))

    print(f"  전북 전체 기준가 {base:,.0f}원/kg")
    print(f"  {'시군':<8}{'실제':>8}{'격차':>8}{'구성효과':>10}{'가격효과':>10}{'잔차':>8}  해석")
    dec = []
    for c in keep:
        g = jb[jb["county"] == c]
        tot = g["qty_kg"].sum()
        s_r = {v: g[g["variety"] == v]["qty_kg"].sum() / tot for v in top_v}
        p_r = {v: wa(g[g["variety"] == v]) for v in top_v}
        actual = wa(g)
        comp = sum((s_r[v] - s_all[v]) * p_all[v]
                   for v in top_v if not np.isnan(p_all[v]))
        pric = sum(s_all[v] * (p_r[v] - p_all[v])
                   for v in top_v if not np.isnan(p_r[v]) and not np.isnan(p_all[v]))
        gap = actual - base
        resid = gap - comp - pric
        tag = ("구성이 주원인" if abs(comp) > abs(pric) * 1.5 else
               "가격이 주원인" if abs(pric) > abs(comp) * 1.5 else "둘 다")
        print(f"  {c:<8}{actual:>8,.0f}{gap:>+8,.0f}{comp:>+10,.0f}{pric:>+10,.0f}"
              f"{resid:>+8,.0f}  {tag}")
        dec.append({"county": c, "actual": actual, "gap": gap,
                    "composition": comp, "price": pric, "residual": resid})
    pd.DataFrame(dec).to_csv(OUT / "variety_decomposition.csv", index=False,
                             encoding="utf-8-sig")

    # ── 4. 계절 구성 변화 + 고정가중 지수 ───────────────────
    print()
    print("=" * 80)
    print("4. 계절성 — 가격 상승 중 얼마가 '구성 변화'인가")
    print("=" * 80)
    # 기준 가중치: 전 기간 평균 품종 구성 (Laspeyres 방식)
    w0 = {v: s_all[v] for v in top_v}
    rows2 = []
    for ym, g in jb.groupby("ym"):
        tot = g["qty_kg"].sum()
        pv = {v: wa(g[g["variety"] == v]) for v in top_v}
        sv = {v: g[g["variety"] == v]["qty_kg"].sum() / tot for v in top_v}
        # 고정가중: 품종별 가격은 그 달 실제, 가중치는 기준기 고정
        num = sum(w0[v] * pv[v] for v in top_v if not np.isnan(pv[v]))
        den = sum(w0[v] for v in top_v if not np.isnan(pv[v]))
        rows2.append({"ym": ym, "month": ym.month, "actual": wa(g),
                      "fixed_weight": num / den if den else np.nan,
                      **{f"s_{v}": sv[v] for v in top_v}})
    ix = pd.DataFrame(rows2)
    ix["mix_effect"] = ix["actual"] - ix["fixed_weight"]
    ix.to_csv(OUT / "variety_fixed_weight_index.csv", index=False, encoding="utf-8-sig")

    mp = ix.groupby("month")[["actual", "fixed_weight", "mix_effect"]].mean()
    print(f"  {'월':>3}{'실제':>9}{'고정가중':>10}{'구성효과':>10}{'구성기여%':>10}")
    for m in range(1, 13):
        if m not in mp.index:
            continue
        r = mp.loc[m]
        rel = r["mix_effect"] / r["actual"] * 100
        print(f"  {m:>3}{r['actual']:>9,.0f}{r['fixed_weight']:>10,.0f}"
              f"{r['mix_effect']:>+10,.0f}{rel:>+9.1f}%")
    amp_a = mp["actual"].max() / mp["actual"].min()
    amp_f = mp["fixed_weight"].max() / mp["fixed_weight"].min()
    print()
    print(f"  연중 진폭:  실제 {amp_a:.2f}배  vs  품종 고정 {amp_f:.2f}배")
    print(f"  -> 계절 진폭의 {(amp_a-amp_f)/(amp_a-1)*100:.0f}%가 품종 구성 변화에서 온다"
          if amp_a > 1 else "")

    print()
    print("저장: outputs/variety_summary.csv, variety_decomposition.csv,")
    print("      variety_fixed_weight_index.csv")


if __name__ == "__main__":
    main()
