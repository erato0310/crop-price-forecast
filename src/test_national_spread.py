# -*- coding: utf-8 -*-
"""test_national_spread.py — 전국 시세를 외생 정보로 넣으면 전북 예측이 좋아지는가.

────────────────────────────────────────────────────────────────
왜 이 방향인가
────────────────────────────────────────────────────────────────
패널 검정에서 **월 고정효과가 -2.31%p** 기여했다(28.99% -> 26.68%). 즉 시군
가격 변동의 상당 부분이 '그 달 전국 공통 충격'이고, 시군별 기상은 그 위에
얹을 게 없었다. 그렇다면 그 공통 충격 자체를 변수로 넣으면 되지 않겠는가.

**중요 — 그대로는 못 쓴다.** 월 고정효과는 *당월* 정보다. 9월 전북 가격을
예측하려는데 9월 전국 가격을 쓰면 rev2 3.1이 지적한 당월변수 누출과 같다.
h=1 예측에서 쓸 수 있는 것은 **t-1까지 관측된 전국 정보**뿐이다.

그래서 이 파일은 두 가지를 분리해서 본다.

  상한(참고용)  월 고정효과 = 당월 공통충격을 완전히 안다고 가정했을 때
  실현 가능     전국 시차 변수만 = 실제 운용에서 쓸 수 있는 것

둘의 격차가 "원리적으로 못 가져오는 정보량"이다.

────────────────────────────────────────────────────────────────
검정할 시차 변수 (전부 t-1 이전)
────────────────────────────────────────────────────────────────
  natl_price_l1     전국 평균가(전 산지, 23개 시장) 1개월 전
  spread_l1         log(전북/전국) 1개월 전  — 평균회귀 성분
  spread_l12        전년 동월 스프레드
  natl_qty_l1       전국 물량
  natl_qty_yoy_l1   전국 물량 전년비 — 작황 대리
  gangwon_share_l1  강원(고랭지) 점유율 — 여름 대체공급 압력
  chungnam_share_l1 충남 점유율 — 최대 경쟁 산지

[실행]
  python test_national_spread.py agg     # 전북 집계 시계열
  python test_national_spread.py panel   # 시군 패널
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

import lettuce_cv as CV
import lettuce_panel_cv as PN
from scrape_lettuce_daily import MAIN_VARIETIES

_ROOT = Path(__file__).resolve().parent.parent
SRC = _ROOT / "data" / "raw" / "lettuce_daily_raw.csv"
OUT = _ROOT / "outputs"


def _wavg(g, p="price_kg", q="qty_kg"):
    x = g[[p, q]].dropna()
    t = x[q].sum()
    return (x[p] * x[q]).sum() / t if t else np.nan


def national_monthly() -> pd.DataFrame:
    """전국(23개 시장 전 산지) 월별 주력 상추 가격·물량 + 주요 산지 점유율."""
    d = pd.read_csv(SRC, dtype={"market_cd": str}, low_memory=False)
    d = d[d["variety"].isin(MAIN_VARIETIES)]
    d["date"] = pd.to_datetime(d["date"], format="mixed")
    d["ym"] = d["date"].dt.to_period("M")
    d["sido_g"] = d["sido"].fillna("미상").str.replace(
        "특별자치도|특별자치시|특별시|광역시", "", regex=True)

    rows = []
    for ym, g in d.groupby("ym"):
        tot = g["qty_kg"].sum()
        sh = g.groupby("sido_g")["qty_kg"].sum() / tot * 100 if tot else {}
        rows.append({
            "ym": ym,
            "natl_price": _wavg(g),
            "natl_qty": tot,
            "gangwon_share": float(sh.get("강원", 0.0)),
            "chungnam_share": float(sh.get("충청남도", 0.0) + sh.get("충남", 0.0)),
            "gyeonggi_share": float(sh.get("경기도", 0.0) + sh.get("경기", 0.0)),
        })
    n = pd.DataFrame(rows).sort_values("ym").reset_index(drop=True)
    n["natl_qty_yoy"] = n["natl_qty"] / n["natl_qty"].shift(12) - 1
    return n


def add_national(p: pd.DataFrame, n: pd.DataFrame, price_col: str,
                 by_county: bool) -> pd.DataFrame:
    """전국 변수를 붙이고 시차 처리. 모든 변수는 t-1 이전만 참조."""
    p = p.merge(n, on="ym", how="left").copy()
    p["spread"] = np.log(p[price_col]) - np.log(p["natl_price"])
    g = p.groupby("county") if by_county else None

    def sh(col, k):
        return g[col].shift(k) if by_county else p[col].shift(k)

    p["natl_price_l1"] = sh("natl_price", 1)
    p["natl_qty_l1"] = np.log(sh("natl_qty", 1).replace(0, np.nan))
    p["natl_qty_yoy_l1"] = sh("natl_qty_yoy", 1)
    p["gangwon_share_l1"] = sh("gangwon_share", 1)
    p["chungnam_share_l1"] = sh("chungnam_share", 1)
    p["gyeonggi_share_l1"] = sh("gyeonggi_share", 1)
    p["spread_l1"] = sh("spread", 1)
    p["spread_l12"] = sh("spread", 12)
    return p


NAT_BASIC = ["natl_price_l1", "spread_l1"]
NAT_FULL = ["natl_price_l1", "spread_l1", "spread_l12", "natl_qty_l1",
            "natl_qty_yoy_l1", "gangwon_share_l1", "chungnam_share_l1"]


def cmd_agg() -> None:
    n = national_monthly()
    base = CV.build_panel()
    p = add_national(base, n, "price", by_county=False)

    print("=" * 78)
    print("전북 집계 시계열 — 전국 시차 변수 추가")
    print("=" * 78)
    core = CV.FEATURE_SETS["가격시차"]
    sets = {
        "가격시차(기준)": core,
        "+전국가격·스프레드": core + NAT_BASIC,
        "+전국 전부": core + NAT_FULL,
        "+강원점유율만": core + ["gangwon_share_l1"],
        "+전국물량YoY만": core + ["natl_qty_yoy_l1"],
    }
    print(f"  {'피처집합':<20}{'CV':>9}{'기준':>9}{'개선':>9}{'승':>6}  홀드아웃2026")
    for name, cols in sets.items():
        miss = [c for c in cols if c not in p.columns]
        if miss:
            print(f"  {name:<20} 없음 {miss}")
            continue
        r = CV.walk_forward(p, cols)
        tr = p[p["ym"].dt.year < CV.HOLDOUT_YEAR].dropna(subset=["price"])
        te = p[p["ym"].dt.year == CV.HOLDOUT_YEAR].dropna(subset=["price"])
        a, b = CV.tune(tr, cols)
        ho = CV.mape(te["price"].values, CV.fit_predict(tr, te, cols, a, b))
        w = int((r["model"] < r["baseline"]).sum())
        print(f"  {name:<20}{r['model'].mean():>8.2f}%{r['baseline'].mean():>8.2f}%"
              f"{r['baseline'].mean()-r['model'].mean():>+8.2f}%{w:>4}/{len(r)}"
              f"{ho:>10.2f}%")

    print()
    print("  블록 부트스트랩 — 기준 대비 차이 95% 구간")
    for name in ["+전국가격·스프레드", "+전국 전부", "+강원점유율만", "+전국물량YoY만"]:
        d, lo, hi = CV.block_bootstrap(p, sets[name], core)
        v = "개선" if hi < 0 else ("악화" if lo > 0 else "판정불가")
        print(f"    {name:<20}{d:>+7.2f}%p  [{lo:+.2f}, {hi:+.2f}]  {v}")

    # 스프레드 자체의 성질
    print()
    print("=" * 78)
    print("스프레드 진단 — log(전북/전국)")
    print("=" * 78)
    s = p.dropna(subset=["spread"])
    print(f"  평균 {s['spread'].mean():+.4f}  표준편차 {s['spread'].std():.4f}")
    print(f"  1개월 자기상관 {s['spread'].autocorr(1):+.3f}   "
          f"12개월 {s['spread'].autocorr(12):+.3f}")
    m = s.groupby("month")["spread"].mean()
    print("  월별 평균 스프레드 (양수=전북이 전국보다 비쌈)")
    print("    " + " ".join(f"{x:>7d}" for x in range(1, 13)))
    print("    " + " ".join(f"{m.get(x, np.nan):+7.3f}" for x in range(1, 13)))


def cmd_panel() -> None:
    n = national_monthly()
    p = PN.build_panel()
    p = add_national(p, n, "price", by_county=True)

    print("=" * 78)
    print("시군 패널 — 전국 시차 변수가 월 고정효과를 대신할 수 있는가")
    print("=" * 78)
    core = PN.CORE
    sets = {
        "가격시차": (core, False),
        "+전국가격·스프레드": (core + NAT_BASIC, False),
        "+전국 전부": (core + NAT_FULL, False),
        "[상한] 월고정효과": (core, True),
        "[상한] 월FE+전국": (core + NAT_FULL, True),
    }
    print(f"  {'설정':<20}{'CV':>9}{'기준':>9}{'개선':>9}{'승':>6}")
    for name, (cols, mfe) in sets.items():
        miss = [c for c in cols if c not in p.columns]
        if miss:
            continue
        r = PN.run(p, cols, county_fe=True, month_fe=mfe)
        if r.empty:
            continue
        w = int((r["model"] < r["baseline"]).sum())
        print(f"  {name:<20}{r['model'].mean():>8.2f}%{r['baseline'].mean():>8.2f}%"
              f"{r['baseline'].mean()-r['model'].mean():>+8.2f}%{w:>4}/{len(r)}")
    print()
    print("  [상한]은 당월 공통충격을 안다고 가정한 것이라 실제 예측엔 쓸 수 없다.")
    print("  '전국 시차'가 [상한]에 얼마나 근접하는지가 이 검정의 핵심이다.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["agg", "panel"])
    a = ap.parse_args()
    {"agg": cmd_agg, "panel": cmd_panel}[a.cmd]()


if __name__ == "__main__":
    main()
