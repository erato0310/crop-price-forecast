# -*- coding: utf-8 -*-
"""infer_cultivation_type.py — 읍면별 상추가 노지인지 시설인지 출하패턴으로 추론.

────────────────────────────────────────────────────────────────
왜 추론해야 하나
────────────────────────────────────────────────────────────────
노지/시설 구분 통계는 **시도 단위까지만** 있다(KOSIS DT_1ET0028, 전북 시설 93.5%).
읍면 단위 자료는 존재하지 않는다. 그런데 이 구분이 중요하다.

  - 시설: 외기 고온이 하우스 내부 축열로 증폭된다. 강수는 직접 영향 없음.
          겨울 일조가 제한요인. 연중 재배 가능.
  - 노지: 강수·서리에 직접 노출. 여름 고온기·겨울에 재배 불가.
          고랭지 노지는 여름에만 나온다.

같은 기상 변수라도 두 재배형태에서 작동 경로가 다르므로, 섞어 놓으면 신호가 상쇄된다.

────────────────────────────────────────────────────────────────
판별 원리 — 출하의 계절 구조가 재배형태를 드러낸다
────────────────────────────────────────────────────────────────
    시설(평지)      연중 균등 출하. 여름에 오히려 감소(고온 휴작)하나 0은 아니다
    노지(평지)      봄·가을 두 봉우리. 한여름·한겨울 출하 공백
    노지(고랭지)    여름에만 출하. 겨울 완전 공백

그래서 다음 지표로 가른다.
    active_months   출하가 있는 달 수 (12 = 연중)
    winter_share    12~2월 물량 비중 (노지면 0에 가깝다)
    summer_share    7~8월 물량 비중
    cv_month        월별 물량 변동계수 (시설일수록 작다)
    gap_max         연속 무출하 개월 최대

**검증 가능성** 전북 전체 시설 비중이 93.5%로 알려져 있으므로, 분류 결과의
물량가중 시설 비중이 그 근처로 나와야 한다. 크게 어긋나면 판별 규칙이 틀린 것이다.

[한계] 이것은 추론이지 관측이 아니다. 출하자 주소 기준이라 공동출하는
집하장 소재지로 잡히고, 한 읍면에 두 형태가 섞여 있으면 평균으로 나온다.

[실행] python infer_cultivation_type.py
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from scrape_lettuce_daily import MAIN_VARIETIES

_ROOT = Path(__file__).resolve().parent.parent
SRC = _ROOT / "data" / "raw" / "lettuce_daily_raw.csv"
OUT = _ROOT / "outputs"

_EUP = re.compile(r"(?:시|군)\s+([가-힣]+(?:읍|면|동))(?:\s|$)")
MIN_MONTHS = 40

# 전북 시설 비중 (KOSIS DT_1ET0028, 2024년 기준). 분류 결과 검증용
KNOWN_PROTECTED_SHARE = 93.5


def load() -> pd.DataFrame:
    d = pd.read_csv(SRC, dtype={"market_cd": str}, low_memory=False)
    d = d[d["variety"].isin(MAIN_VARIETIES)]
    d["date"] = pd.to_datetime(d["date"], format="mixed")
    d["ym"] = d["date"].dt.to_period("M")
    d["month"] = d["date"].dt.month
    j = d[d["county"].notna()].copy()
    j["eup"] = j["plor_nm"].str.extract(_EUP)
    j["unit"] = j["county"] + "·" + j["eup"].fillna("(미상)")
    return j


def features(j: pd.DataFrame) -> pd.DataFrame:
    rows = []
    n_years = j["ym"].dt.year.nunique()
    for u, g in j.groupby("unit"):
        months = g.groupby("ym")["qty_kg"].sum()
        if len(months) < MIN_MONTHS:
            continue
        # 달력월별 평균 물량 (연도 편차를 없앤 계절 프로파일)
        cal = g.groupby("month")["qty_kg"].sum() / n_years
        cal = cal.reindex(range(1, 13), fill_value=0.0)
        tot = cal.sum()
        if tot <= 0:
            continue
        sh = cal / tot * 100
        active = int((cal > tot * 0.005).sum())      # 연물량의 0.5% 넘는 달
        # 최대 연속 무출하
        flags = (cal > tot * 0.005).values
        gap = run = 0
        for x in list(flags) * 2:                     # 순환(12월->1월)
            run = 0 if x else run + 1
            gap = max(gap, run)
        gap = min(gap, 12)
        rows.append({
            "unit": u, "county": u.split("·")[0], "eup": u.split("·")[1],
            "qty_t": g["qty_kg"].sum() / 1000,
            "n_months": len(months),
            "active_months": active,
            "gap_max": gap,
            "winter_share": float(sh[[12, 1, 2]].sum()),
            "summer_share": float(sh[[7, 8]].sum()),
            "spring_share": float(sh[[4, 5]].sum()),
            "autumn_share": float(sh[[9, 10]].sum()),
            "cv_month": float(cal.std() / cal.mean()),
            "peak_month": int(cal.idxmax()),
            "min_share": float(sh.min()),
            "price": float((g["price_kg"] * g["qty_kg"]).sum() / g["qty_kg"].sum()),
        })
    return pd.DataFrame(rows)


def classify(f: pd.DataFrame) -> pd.DataFrame:
    """규칙 기반 분류. 기준은 생리·재배 상식에서 나오고, 전북 93.5%로 검증한다."""
    def rule(r):
        # 연중 출하 + 겨울 물량 존재 -> 시설. 무가온이라도 겨울 출하는 시설만 가능
        if r["active_months"] >= 11 and r["winter_share"] >= 10:
            return "시설"
        # 겨울 거의 없고 여름에 몰림 -> 고랭지 노지
        if r["winter_share"] < 5 and r["summer_share"] >= 30:
            return "노지(고랭지)"
        # 겨울 공백 + 봄가을 봉우리 -> 평지 노지
        if r["winter_share"] < 8 and r["gap_max"] >= 2:
            return "노지(평지)"
        if r["active_months"] >= 10 and r["winter_share"] >= 5:
            return "시설(추정)"
        return "혼재·불명"
    f = f.copy()
    f["type"] = f.apply(rule, axis=1)
    return f


def main() -> None:
    j = load()
    f = classify(features(j))
    f = f.sort_values("qty_t", ascending=False)
    f.to_csv(OUT / "cultivation_type_by_eup.csv", index=False, encoding="utf-8-sig")

    print("=" * 84)
    print("1. 읍면별 판별 결과 (물량 상위 20)")
    print("=" * 84)
    print(f"  {'단위':<15}{'물량t':>9}{'출하월':>6}{'겨울%':>7}{'여름%':>7}"
          f"{'최대공백':>8}{'변동계수':>8}{'원/kg':>8}  판별")
    for _, r in f.head(20).iterrows():
        print(f"  {r['unit']:<15}{r['qty_t']:>9,.0f}{r['active_months']:>6}"
              f"{r['winter_share']:>6.1f}%{r['summer_share']:>6.1f}%"
              f"{r['gap_max']:>7}개{r['cv_month']:>8.2f}{r['price']:>8,.0f}  {r['type']}")

    print()
    print("=" * 84)
    print("2. 검증 — 전북 전체 시설 비중이 KOSIS와 맞는가")
    print("=" * 84)
    g = f.groupby("type")["qty_t"].agg(["sum", "size"])
    g["share"] = g["sum"] / g["sum"].sum() * 100
    for t, r in g.sort_values("sum", ascending=False).iterrows():
        print(f"  {t:<14}{int(r['size']):>4}개 읍면{r['sum']:>12,.0f}t{r['share']:>8.1f}%")
    prot = g.loc[[i for i in g.index if "시설" in i], "sum"].sum() / g["sum"].sum() * 100
    print()
    print(f"  분류 결과 시설 비중 {prot:.1f}%")
    print(f"  KOSIS 전북 시설 비중 {KNOWN_PROTECTED_SHARE}%  "
          f"(차이 {prot - KNOWN_PROTECTED_SHARE:+.1f}%p)")
    if abs(prot - KNOWN_PROTECTED_SHARE) < 10:
        print("  -> 독립 통계와 부합. 판별 규칙이 타당하다고 볼 근거가 된다.")
    else:
        print("  -> 어긋난다. 판별 규칙 재검토 필요.")

    print()
    print("=" * 84)
    print("3. 노지로 판별된 읍면 — 월별 출하 프로파일")
    print("=" * 84)
    n_years = j["ym"].dt.year.nunique()
    nogi = f[f["type"].str.startswith("노지")]
    if nogi.empty:
        print("  없음")
    else:
        print("  " + " " * 16 + " ".join(f"{m:>5d}" for m in range(1, 13)))
        for _, r in nogi.head(10).iterrows():
            g2 = j[j["unit"] == r["unit"]]
            cal = g2.groupby("month")["qty_kg"].sum().reindex(range(1, 13), fill_value=0)
            sh = cal / cal.sum() * 100
            print(f"  {r['unit']:<16}" + " ".join(f"{sh[m]:4.0f}%" for m in range(1, 13)))
    print()
    print("  참고 — 시설로 판별된 대표 읍면 (대조군)")
    print("  " + " " * 16 + " ".join(f"{m:>5d}" for m in range(1, 13)))
    for _, r in f[f["type"] == "시설"].head(4).iterrows():
        g2 = j[j["unit"] == r["unit"]]
        cal = g2.groupby("month")["qty_kg"].sum().reindex(range(1, 13), fill_value=0)
        sh = cal / cal.sum() * 100
        print(f"  {r['unit']:<16}" + " ".join(f"{sh[m]:4.0f}%" for m in range(1, 13)))

    print()
    print("=" * 84)
    print("4. 재배형태별 가격 특성")
    print("=" * 84)
    print(f"  {'유형':<14}{'읍면수':>6}{'물량t':>11}{'평균원/kg':>11}{'여름/겨울 배율':>14}")
    for t, sub in f.groupby("type"):
        w = sub["qty_t"]
        pw = (sub["price"] * w).sum() / w.sum()
        ratio = (sub["summer_share"] / 2) / (sub["winter_share"] / 3).replace(0, np.nan)
        print(f"  {t:<14}{len(sub):>6}{w.sum():>11,.0f}{pw:>11,.0f}"
              f"{ratio.median():>13.2f}배")

    print()
    print("저장: outputs/cultivation_type_by_eup.csv")
    print()
    print("  [한계] 출하패턴 기반 추론이다. 관측 자료가 아니며, 한 읍면에 두 형태가")
    print("         섞여 있으면 평균으로 나온다. 공동출하는 집하장 소재지로 잡힌다.")


if __name__ == "__main__":
    main()
