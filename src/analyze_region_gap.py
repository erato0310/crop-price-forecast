# -*- coding: utf-8 -*-
"""analyze_region_gap.py — 지역 가격차를 무엇이 설명하는가 (최근 1년).

────────────────────────────────────────────────────────────────
문제
────────────────────────────────────────────────────────────────
같은 주·같은 품종·같은 시장 안에서 견줘도 시군 간 값 차이가 크다.
전 기간 기준 남원 1.077 vs 무주 0.711 — 37%p 벌어진다.

일교차로 설명하려던 시도는 다섯 설계에서 모두 실패했다(HANDOFF 1-E).
그래서 자료 안에 있는 다른 것들을 훑는다.

**최근 1년만 본다.** 8년치를 합치면 그 사이의 구조 변화(남원 산간 비중이
5%→28%로 바뀐 것 등)가 섞여 지금의 차이를 흐린다.

────────────────────────────────────────────────────────────────
후보
────────────────────────────────────────────────────────────────
    포장    평균 상자무게, 소형(≤2.5kg) 비율
    등급    특 비율
    거래    경매 비율 (정가수의는 값 형성이 다르다. 정읍은 정가수의가 66%다)
    로트    거래 1건당 물량 — 한 번에 많이 내면 값이 눌릴 수 있다
    판로    거래 시장 수, 최대 시장 집중도
    규칙성  주당 거래일수 — 꾸준히 내는 곳이 값을 더 받는가
    품종    적상추 비율 (품종은 셀에서 통제되지만 구성 자체가 지역 성격이다)
    규모    총 물량

────────────────────────────────────────────────────────────────
검정
────────────────────────────────────────────────────────────────
- 상대값은 같은 주·같은 품종·같은 시장 안에서의 비. 전국 시세·품종·시장은 빠져 있다.
- 시군이 14개뿐이다. 단변량 상관을 부트스트랩 구간과 함께 본다.
- **여러 개를 훑으면 하나쯤은 우연히 걸린다.** 걸린 것은 그대로 적되
  다중검정 보정(Holm)을 같이 낸다.
- 상관은 인과가 아니다. 걸린 것이 있으면 같은 시군 안에서 시간에 따라
  변하는지로 다시 확인한다.

[실행] python analyze_region_gap.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "outputs"

WEEKS = 53


def load_recent() -> pd.DataFrame:
    d = pd.read_csv(RAW / "lettuce_daily_raw.csv", low_memory=False,
                    usecols=["date", "market_cd", "county", "variety", "grade",
                             "trd_se", "unit_qty", "price_kg", "qty_kg"],
                    dtype={"market_cd": str})
    d = d[d["county"].notna()].dropna(subset=["price_kg", "qty_kg"])
    d = d[(d["qty_kg"] > 0) & (d["price_kg"] > 0)]
    d["date"] = pd.to_datetime(d["date"], format="mixed")
    cut = d["date"].max() - pd.Timedelta(weeks=WEEKS)
    d = d[d["date"] > cut].copy()
    d["wk"] = d["date"] - pd.to_timedelta(d["date"].dt.weekday, unit="D")
    return d


def relative(d: pd.DataFrame, extra_key: list[str] | None = None) -> pd.Series:
    key = ["wk", "variety", "market_cd"] + (extra_key or [])
    cell = (d.groupby(key + ["county"])
              .apply(lambda g: np.average(g["price_kg"], weights=g["qty_kg"]),
                     include_groups=False)
              .rename("p").reset_index())
    cell = cell[cell.groupby(key)["county"].transform("nunique") >= 2]
    cell["rel"] = cell["p"] / cell.groupby(key)["p"].transform("mean")
    return cell.groupby("county")["rel"].mean()


def features(d: pd.DataFrame) -> pd.DataFrame:
    GRADED = {"특", "상", "중", "하", "등외"}
    rows = []
    for c, x in d.groupby("county"):
        q = x["qty_kg"].sum()
        gq = x.loc[x["grade"].isin(GRADED), "qty_kg"].sum()
        mk = x.groupby("market_cd")["qty_kg"].sum()
        rows.append({
            "county": c,
            "물량t": q / 1000,
            "평균상자kg": np.average(x["unit_qty"].clip(0, 50).fillna(0), weights=x["qty_kg"]),
            "소형상자%": x.loc[x["unit_qty"] <= 2.5, "qty_kg"].sum() / q * 100,
            "특비율%": (x.loc[x["grade"] == "특", "qty_kg"].sum() / gq * 100) if gq else np.nan,
            "경매비율%": x.loc[x["trd_se"] == "경매", "qty_kg"].sum() / q * 100,
            "건당물량kg": q / len(x),
            "시장수": x["market_cd"].nunique(),
            "최대시장집중%": mk.max() / q * 100,
            "주당거래일": x.groupby("wk")["date"].nunique().mean(),
            "적상추%": x.loc[x["variety"] == "적상추", "qty_kg"].sum() / q * 100,
        })
    return pd.DataFrame(rows).set_index("county")


def boot_corr(x, y, n=4000, seed=20260814):
    rng = np.random.default_rng(seed)
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    r0 = float(np.corrcoef(x, y)[0, 1])
    bs = []
    for _ in range(n):
        i = rng.integers(0, len(x), len(x))
        if len(set(i.tolist())) < 3:
            continue
        with np.errstate(invalid="ignore"):
            c = np.corrcoef(x[i], y[i])[0, 1]
        if np.isfinite(c):
            bs.append(c)
    lo, hi = np.percentile(bs, [2.5, 97.5])
    # 부트스트랩 분포가 0의 어느 쪽에 얼마나 쏠렸는지로 p 근사
    p = 2 * min((np.array(bs) <= 0).mean(), (np.array(bs) >= 0).mean())
    return r0, float(lo), float(hi), float(max(p, 1 / n))


def holm(pvals: list[float]) -> list[float]:
    m = len(pvals)
    order = np.argsort(pvals)
    adj = np.empty(m)
    run = 0.0
    for rank, i in enumerate(order):
        v = (m - rank) * pvals[i]
        run = max(run, v)
        adj[i] = min(1.0, run)
    return adj.tolist()


def main() -> None:
    d = load_recent()
    print(f"최근 {WEEKS}주: {d['wk'].min().date()} ~ {d['wk'].max().date()} · {len(d):,}건")

    rel = relative(d)
    f = features(d)
    f["상대값"] = rel
    f = f.dropna(subset=["상대값"]).sort_values("상대값", ascending=False)

    print()
    print("=" * 92)
    print("시군별 — 같은 주·같은 품종·같은 시장 안에서의 상대값과 후보 변수")
    print("=" * 92)
    print(f"  폭: 최고 {f.index[0]} {f['상대값'].iloc[0]:.3f} / "
          f"최저 {f.index[-1]} {f['상대값'].iloc[-1]:.3f} "
          f"(표준편차 {f['상대값'].std():.4f})")
    print()
    print(f.round(2).to_string())

    cols = [c for c in f.columns if c != "상대값"]
    res = []
    for c in cols:
        r, lo, hi, p = boot_corr(f[c], f["상대값"])
        res.append({"변수": c, "r": r, "lo": lo, "hi": hi, "p": p})
    R = pd.DataFrame(res)
    R["p_holm"] = holm(R["p"].tolist())

    print()
    print("=" * 92)
    print("무엇이 상대값을 설명하는가 (시군 %d개)" % len(f))
    print("=" * 92)
    print(f"  {'변수':<14}{'r':>8}{'95% 구간':>22}{'p':>8}{'Holm 보정':>10}   판정")
    for _, r in R.sort_values("p").iterrows():
        raw = "관계 있음" if (r["lo"] > 0 or r["hi"] < 0) else "판정불가"
        adj = "유지" if r["p_holm"] < 0.05 else ("보정 후 탈락" if raw == "관계 있음" else "")
        print(f"  {r['변수']:<14}{r['r']:+8.3f}   [{r['lo']:+.3f}, {r['hi']:+.3f}]"
              f"{r['p']:8.3f}{r['p_holm']:10.3f}   {raw}{('  ' + adj) if adj else ''}")

    # 셀에 무엇을 더 넣으면 지역차가 줄어드는가 — 설명력을 직접 잰다
    print()
    print("=" * 92)
    print("셀 정의에 넣어 보면 지역차가 얼마나 줄어드는가")
    print("=" * 92)
    d2 = d.copy()
    d2["box"] = d2["unit_qty"].round(1)
    base = relative(d2).std()
    print(f"  {'통제':<34}{'지역차 표준편차':>14}{'축소':>8}")
    print(f"  {'주 x 품종 x 시장 (기준)':<34}{base:>14.4f}{'':>8}")
    for extra, lab in (["box"], "+ 상자규격"), (["grade"], "+ 등급"), \
                      (["trd_se"], "+ 거래구분"), (["box", "grade"], "+ 상자규격 + 등급"), \
                      (["box", "grade", "trd_se"], "+ 상자규격 + 등급 + 거래구분"):
        s = relative(d2, extra).std()
        print(f"  {'주 x 품종 x 시장 ' + lab:<34}{s:>14.4f}{(1 - s / base) * 100:>7.0f}%")

    OUT.mkdir(exist_ok=True)
    f.to_csv(OUT / "region_gap_features.csv", encoding="utf-8-sig")
    R.to_csv(OUT / "region_gap_corr.csv", index=False, encoding="utf-8-sig")
    print(f"\n저장: {OUT/'region_gap_features.csv'}")


if __name__ == "__main__":
    main()
