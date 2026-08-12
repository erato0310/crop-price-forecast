# -*- coding: utf-8 -*-
"""analyze_sampling_error.py — "5·15·25일 3일 표본"이 만든 측정오차를 정량화한다.

[질문]
기존 파이프라인은 매월 5·15·25일만 수집해 그 3일의 물량가중평균을 '그 달의 가격'으로
썼다(scrape_jeonbuk_origin.SAMPLE_DAYS, scrape_jeonbuk_market.SAMPLE_DAYS). 한 달에
거래일이 22~27일이니 87~89%를 버린 것이다. 그렇다면 **모델이 맞히려던 타깃 자체가
얼마나 틀려 있었는가?**

[방법]
scrape_lettuce_daily.py가 받은 전 일자 자료에서 같은 달의 월평균을 두 가지로 만든다.
  full   = 그 달 전 거래일의 물량가중평균  (참값에 가장 가까운 추정)
  sample = 5·15·25일만 쓴 물량가중평균     (기존 파이프라인이 쓰던 값)
둘의 차이가 곧 표본 측정오차이며, 이는 **어떤 모델로도 줄일 수 없는 오차 하한**이다.
모델 MAPE 26~28%를 이 값과 나란히 놓고 봐야 한다.

[실행] python analyze_sampling_error.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
RAW = _ROOT / "data" / "raw" / "lettuce_daily_raw.csv"
OUT = _ROOT / "outputs"
OUT.mkdir(exist_ok=True)

SAMPLE_DAYS = (5, 15, 25)


def wavg(d: pd.DataFrame, p: str = "price_kg", q: str = "qty_kg") -> float:
    d = d[[p, q]].dropna()
    t = d[q].sum()
    return (d[p] * d[q]).sum() / t if t else np.nan


def mape(a, f) -> float:
    a, f = np.asarray(a, float), np.asarray(f, float)
    m = np.isfinite(a) & np.isfinite(f) & (a != 0)
    return float(np.mean(np.abs((a[m] - f[m]) / a[m])) * 100) if m.any() else np.nan


def main() -> None:
    raw = pd.read_csv(RAW, dtype={"market_cd": str, "plor_cd": str}, low_memory=False)
    raw["date"] = pd.to_datetime(raw["date"], format="mixed")
    raw["ym"] = raw["date"].dt.to_period("M")
    raw["day"] = raw["date"].dt.day
    print(f"원자료 {len(raw):,}행  {raw['ym'].min()} ~ {raw['ym'].max()}")

    # 타깃 정의와 맞춘다 — 쫑상추·솎음은 별개 계열이라 여기서 제외
    from scrape_lettuce_daily import MAIN_VARIETIES
    raw = raw[raw["variety"].isin(MAIN_VARIETIES)]
    print(f"  주력 {len(MAIN_VARIETIES)}종만: {len(raw):,}행")

    jb = raw[raw["county"].notna()].copy()
    print(f"전북산 {len(jb):,}행 ({len(jb)/len(raw)*100:.1f}%), "
          f"시군 {jb['county'].nunique()}개\n")

    # ── 1. 전북 전체 축 ────────────────────────────────────────
    print("=" * 72)
    print("1. 표본오차 — 전북산 상추 월평균가 (원/kg)")
    print("=" * 72)
    rows = []
    for ym, g in jb.groupby("ym"):
        s = g[g["day"].isin(SAMPLE_DAYS)]
        rows.append({
            "ym": ym, "full": wavg(g), "sample": wavg(s) if len(s) else np.nan,
            "n_days_full": g["date"].nunique(), "n_days_sample": s["date"].nunique(),
            "n_obs_full": len(g), "n_obs_sample": len(s),
        })
    d = pd.DataFrame(rows)
    d["err_pct"] = (d["sample"] - d["full"]) / d["full"] * 100
    d.to_csv(OUT / "sampling_error_jeonbuk.csv", index=False, encoding="utf-8-sig")

    e = d["err_pct"].dropna()
    print(f"  표본오차 MAPE            {mape(d['full'], d['sample']):.2f}%")
    print(f"  중앙 절대오차            {e.abs().median():.2f}%")
    print(f"  |오차| > 10%인 달        {(e.abs() > 10).sum()}/{len(e)}개 "
          f"({(e.abs() > 10).mean()*100:.0f}%)")
    print(f"  |오차| > 20%인 달        {(e.abs() > 20).sum()}/{len(e)}개")
    print(f"  최대 오차                {e.abs().max():.1f}% "
          f"({d.loc[e.abs().idxmax(), 'ym']})")
    print(f"  평균 편향(bias)          {e.mean():+.2f}%  "
          f"— 0에서 멀면 계통오차, 0 근처면 순수 잡음")
    print(f"  3일 표본이 0~1일뿐인 달   "
          f"{(d['n_days_sample'] <= 1).sum()}개  (MIN_OBS_PER_MONTH 필터에 걸리는 구간)")
    print(f"  월 거래일수  중앙 {d['n_days_full'].median():.0f}일 / "
          f"최소 {d['n_days_full'].min()}일")
    print(f"  월 관측건수  3일표본 중앙 {d['n_obs_sample'].median():.0f}건 → "
          f"전일자 중앙 {d['n_obs_full'].median():.0f}건 "
          f"({d['n_obs_full'].median()/max(d['n_obs_sample'].median(),1):.1f}배)")

    print("\n  오차 상위 8개월")
    top = d.reindex(e.abs().sort_values(ascending=False).index).head(8)
    print("    ym       전일자     3일표본     오차    표본일수")
    for _, r in top.iterrows():
        print(f"    {str(r['ym'])}  {r['full']:8.0f}  {r['sample']:9.0f}  "
              f"{r['err_pct']:+7.1f}%   {int(r['n_days_sample'])}일")

    # 계절별로 오차가 몰리는가 — 여름 급변동기에 크다면 모델 평가가 그 구간에서 왜곡된다
    d["month"] = d["ym"].dt.month
    ms = d.groupby("month")["err_pct"].apply(lambda x: x.abs().mean())
    print("\n  월별 평균 |표본오차|")
    print("    " + " ".join(f"{m:>5d}" for m in range(1, 13)))
    print("    " + " ".join(f"{ms.get(m, np.nan):4.1f}%" for m in range(1, 13)))

    # ── 2. 시군 축 ────────────────────────────────────────────
    print()
    print("=" * 72)
    print("2. 표본오차 — 시군별 (표본이 얇을수록 커진다)")
    print("=" * 72)
    crows = []
    for (ym, c), g in jb.groupby(["ym", "county"]):
        s = g[g["day"].isin(SAMPLE_DAYS)]
        crows.append({"ym": ym, "county": c, "full": wavg(g),
                      "sample": wavg(s) if len(s) else np.nan,
                      "n_obs_full": len(g), "n_obs_sample": len(s),
                      "n_days_sample": s["date"].nunique()})
    cd = pd.DataFrame(crows)
    cd.to_csv(OUT / "sampling_error_by_county.csv", index=False, encoding="utf-8-sig")
    print("    시군      월수  표본오차MAPE  표본결측월  월중앙관측(3일→전일자)")
    for c, g in cd.groupby("county"):
        miss = int(g["n_days_sample"].le(1).sum())
        print(f"    {c:8s}  {len(g):4d}  {mape(g['full'], g['sample']):10.1f}%  "
              f"{miss:8d}개  {g['n_obs_sample'].median():6.0f} → "
              f"{g['n_obs_full'].median():.0f}건")

    # ── 3. 산지 이동 ──────────────────────────────────────────
    print()
    print("=" * 72)
    print("3. 월별 산지 구성 — 고랭지 대체 실측 (전국 물량 kg 기준)")
    print("=" * 72)
    raw["sido_g"] = raw["sido"].fillna("미상").str.replace(
        "특별자치도|특별자치시|특별시|광역시", "", regex=True)
    piv = raw.pivot_table(index=raw["date"].dt.month, columns="sido_g",
                          values="qty_kg", aggfunc="sum")
    share = piv.div(piv.sum(axis=1), axis=0) * 100
    keep = share.mean().sort_values(ascending=False).head(7).index
    print("    월 | " + " ".join(f"{c[:4]:>6s}" for c in keep) + " |    총 kg")
    for m in range(1, 13):
        print(f"    {m:2d} | " + " ".join(f"{share.loc[m, c]:5.1f}%" for c in keep)
              + f" | {piv.loc[m].sum():12,.0f}")

    print()
    print("    전북 내부 — 준고랭지(진안·장수·무주) 비중")
    UP = {"진안군", "장수군", "무주군"}
    cp = jb.pivot_table(index=jb["date"].dt.month, columns="county",
                        values="qty_kg", aggfunc="sum")
    csh = cp.div(cp.sum(axis=1), axis=0) * 100
    cols = [c for c in csh.columns if c in UP]
    main_c = csh.mean().sort_values(ascending=False).head(4).index
    print("    월 | " + " ".join(f"{c[:3]:>6s}" for c in main_c)
          + " | 준고랭지합")
    for m in range(1, 13):
        up = sum(csh.loc[m, c] for c in cols if not pd.isna(csh.loc[m, c]))
        print(f"    {m:2d} | " + " ".join(f"{csh.loc[m, c]:5.1f}%" for c in main_c)
              + f" |  {up:5.1f}%")

    # ── 4. 품종 구성 ──────────────────────────────────────────
    print()
    print("=" * 72)
    print("4. 품종 구성/가격 — 타깃이 품종 혼합 평균이라는 점의 확인")
    print("=" * 72)
    vp = jb.pivot_table(index=jb["date"].dt.month, columns="variety",
                        values="qty_kg", aggfunc="sum")
    vsh = vp.div(vp.sum(axis=1), axis=0) * 100
    vk = vsh.mean().sort_values(ascending=False).head(5).index
    print("    물량비중  월 | " + " ".join(f"{v[:4]:>6s}" for v in vk))
    for m in range(1, 13):
        print(f"              {m:2d} | " + " ".join(f"{vsh.loc[m, v]:5.1f}%" for v in vk))
    print("\n    품종별 원/kg (연평균) 및 계절진폭")
    for v in vk:
        g = jb[jb["variety"] == v]
        mm = g.groupby(g["date"].dt.month).apply(wavg, include_groups=False)
        if mm.notna().sum() < 6:
            continue
        print(f"      {v:8s} 연평균 {wavg(g):7.0f}원/kg  "
              f"최고월 {mm.idxmax():2d}월 {mm.max():7.0f}  "
              f"최저월 {mm.idxmin():2d}월 {mm.min():6.0f}  진폭 {mm.max()/mm.min():4.1f}배")

    print(f"\n저장: outputs/sampling_error_jeonbuk.csv, sampling_error_by_county.csv")


if __name__ == "__main__":
    main()
