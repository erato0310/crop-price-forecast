# -*- coding: utf-8 -*-
"""analyze_scale_dtr.py — 산지 규모와 일교차를 **함께** 놓고 가격을 설명해 본다.

────────────────────────────────────────────────────────────────
왜
────────────────────────────────────────────────────────────────
사용자 제안. 1-E는 일교차 **하나만** 놓고 가격과 맞춰 봤다. 그런데 값을 정하는
것이 그것 하나일 리 없다. **물량이 많은 곳(주산지)이면서 일교차도 큰 곳**이
비싸야 하는 것 아닌가.

타당한 지적이다. 그리고 1-E가 왜 실패했는지도 설명할 수 있다 — 일교차 1·2위인
무주(10톤)·진안(858톤)은 규모가 작다. 10톤짜리 시군의 가격은 '그 지역 상추의
품질'이라기보다 몇몇 출하 건의 우연에 가깝다. 규모를 같이 넣으면 걸러진다.

────────────────────────────────────────────────────────────────
결론 — 규모는 방향이 맞고, 일교차는 여전히 반대다. 다만 둘 다 판정불가
────────────────────────────────────────────────────────────────
**사분면(시군 14곳).**

    　　　　　　　물량 많음　　물량 적음
    일교차 큼　　　0.998(4)　　0.890(3)
    일교차 작음　　1.030(3)　　0.973(4)

가로로는 물량 많은 쪽이 두 줄 다 높다(+7.5%p). 세로로는 일교차 큰 쪽이 두 줄 다
**낮다**. 규모는 제안한 방향이고 일교차는 반대다.

**회귀(시군 14곳, y=log 상대값).** 둘을 같이 넣으면 R²가 0.138·0.074에서
**0.296**으로 뛴다. 설명력이 붙는 것은 맞다. 그런데 **계수가 하나도 유의하지
않다** — 부트스트랩 구간이 전부 0을 포함한다. n=14로는 여기까지다.

**시군 x 연도(약 120점)로 늘려도 마찬가지다.** 행은 늘지만 **독립 단위는 여전히
시군 14개**다. 시군 블록 부트스트랩으로 제대로 재면 구간이 다시 0을 포함한다.
연도를 늘려 유의해 보이는 것은 같은 시군을 여러 번 센 것일 뿐이다.

> **이 프로젝트에서 '지역 간' 질문의 천장이 여기다.** 무엇을 넣든 독립 표본이
> 14개다. 지역 간 비교로 답이 나오려면 효과가 아주 크거나(포장 규격처럼) 시군이
> 훨씬 많아야 한다. 1-F가 시군 간 상관 대신 **같은 셀 안 2kg vs 4kg 대응짝
> 1,462개**로 옮겨간 이유가 이것이다.

**규모만 따로 보면 읍면으로 내려갈 수 있다.** 규모에는 기상이 필요 없으니
관측지점 수에 묶이지 않는다. 104주 이상인 읍면 61개(물량의 99.4%)로 재면
계수는 +0.0189 [-0.0035, +0.0431]로 **여전히 판정불가**다. 시군 평균을 뺀
시군 내 비교도 +0.0142 [-0.0042, +0.0316]으로 같다.

다만 4분위로 끊어 보면 모양이 '비례'가 아니다.

    1분위(작음) 0.964 · 2분위 1.065 · 3분위 1.080 · 4분위(큼) 1.046

**클수록 비싼 것이 아니라 너무 작으면 싸다.** 2~4분위는 1.05~1.08로 평평하고
1분위만 10%p 아래다(16개 읍면, 합쳐서 678톤 — 읍면당 연 5톤 남짓). 계수 하나로
직선을 그으면 이 계단이 상관계수로 눌려 보인다. 이것도 유의하지는 않지만
**'규모의 효과'가 있다면 비례가 아니라 문턱일 가능성**을 적어 둔다.

**규모 효과는 포장과 얽혀 있다.** 규모 계수는 소형상자 비율을 넣으면 +0.0285에서
+0.0266으로 거의 안 줄지만 둘 다 유의하지 않아 분리했다고 말할 수 없다.
큰 산지가 소포장 체계를 갖췄을 뿐인지, 규모 자체가 값을 만드는지 이 자료로는
가르지 못한다.

[실행] python analyze_scale_dtr.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_dtr_weighted import weekly_relative_w
from analyze_dtr_within import weekly_weather
from export_lettuce_webapp import extract_eup     # 읍면 파싱은 웹앱과 같은 규칙

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "outputs"

# 품종 분할에서 쓴 것과 같은 문턱. 이보다 짧으면 연 대표값이라 할 수 없다.
MIN_WEEKS = 104


def h(t: str) -> None:
    print("\n" + "=" * 74 + f"\n{t}\n" + "=" * 74)


def ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.linalg.lstsq(X, y, rcond=None)[0]


def r2(X, y, b) -> float:
    return 1 - ((y - X @ b) ** 2).sum() / ((y - y.mean()) ** 2).sum()


def report(d: pd.DataFrame, cols, label, cluster=None, B=4000, seed=7):
    """계수와 부트스트랩 구간. cluster를 주면 그 단위로 블록 부트스트랩한다."""
    X = np.c_[np.ones(len(d)), d[cols].values]
    y = d["y"].values
    b = ols(X, y)
    rng = np.random.default_rng(seed)
    bs = []
    if cluster is None:
        for _ in range(B):
            i = rng.integers(0, len(d), len(d))
            try:
                bs.append(ols(np.c_[np.ones(len(i)), d[cols].values[i]], y[i]))
            except Exception:
                pass
    else:
        units = d[cluster].unique()
        idx = {u: np.flatnonzero(d[cluster].values == u) for u in units}
        for _ in range(B):
            pick = rng.choice(units, len(units), replace=True)
            i = np.concatenate([idx[u] for u in pick])
            try:
                bs.append(ols(np.c_[np.ones(len(i)), d[cols].values[i]], y[i]))
            except Exception:
                pass
    bs = np.array(bs)
    print(f"  {label}   R2={r2(X, y, b):.3f}   n={len(d)}"
          + (f" / 클러스터 {d[cluster].nunique()}개" if cluster else ""))
    for k, c in enumerate(cols):
        lo, hi = np.percentile(bs[:, k + 1], [2.5, 97.5])
        v = "판정불가" if lo < 0 < hi else "유의"
        print(f"      {c:<14}{b[k+1]:+9.4f}  [{lo:+.4f}, {hi:+.4f}]  {v}")


def eup_panel() -> pd.DataFrame:
    """읍면 x (같은 주·품종·시장) 상대값 -> 읍면 단위로 합친다.

    시군 패널과 같은 설계인데 단위만 읍면이다. 같은 시군 안 읍면끼리도
    비교 대상이 되므로 셀 조건(같은 주·품종·시장에 둘 이상)은 그대로 쓴다.
    """
    d = pd.read_csv(RAW / "lettuce_daily_raw.csv", low_memory=False,
                    usecols=["date", "market_cd", "county", "variety",
                             "plor_nm", "price_kg", "qty_kg"],
                    dtype={"market_cd": str})
    d = d[d["county"].notna()].dropna(subset=["price_kg", "qty_kg"])
    d = d[(d["qty_kg"] > 0) & (d["price_kg"] > 0)]
    d["eup"] = [extract_eup(p, c) for p, c in zip(d["plor_nm"], d["county"])]
    # 시군을 잃지 않는다 — 읍면 이름만으로는 다른 시군의 동명 읍면과 섞인다
    d["unit"] = d["county"].astype(str) + "|" + d["eup"].astype(str)
    d["date"] = pd.to_datetime(d["date"], format="mixed")
    d["wk"] = d["date"] - pd.to_timedelta(d["date"].dt.weekday, unit="D")

    key = ["wk", "variety", "market_cd"]
    cell = (d.groupby(key + ["unit"])
              .apply(lambda g: pd.Series({
                  "p": np.average(g["price_kg"], weights=g["qty_kg"]),
                  "q": g["qty_kg"].sum()}), include_groups=False)
              .reset_index())
    cell = cell[cell.groupby(key)["unit"].transform("nunique") >= 2]
    cell["rel"] = cell["p"] / cell.groupby(key)["p"].transform("mean")
    u = (cell.groupby("unit")
             .apply(lambda x: pd.Series({
                 "rel": np.average(x["rel"], weights=x["q"]),
                 "q": x["q"].sum(), "nwk": x["wk"].nunique()}),
                    include_groups=False)
             .reset_index())
    u["county"] = u["unit"].str.split("|").str[0]
    u["eup"] = u["unit"].str.split("|").str[1]
    return u


def main() -> None:
    OUT.mkdir(exist_ok=True)

    # ── A. 시군 14곳 — 사분면 ────────────────────────────────
    h("A. 사분면 — 물량 많음/적음 x 일교차 큼/작음")
    g = pd.read_csv(OUT / "region_gap_features.csv")
    p = pd.read_csv(OUT / "dtr_premium.csv")[["county", "dtr_all"]]
    m = g.merge(p, on="county")
    mq, md = m["물량t"].median(), m["dtr_all"].median()
    m["물량군"] = np.where(m["물량t"] >= mq, "많음", "적음")
    m["일교차군"] = np.where(m["dtr_all"] >= md, "큼", "작음")
    print(f"  기준 — 물량 중앙값 {mq:,.0f}t / 일교차 중앙값 {md:.2f}도\n")
    print(f"  {'':12}{'물량 많음':>12}{'물량 적음':>12}")
    for dq in ("큼", "작음"):
        row = f"  일교차 {dq:<6}"
        for vq in ("많음", "적음"):
            s = m[(m["물량군"] == vq) & (m["일교차군"] == dq)]
            row += f"{s['상대값'].mean():>9.3f}({len(s)})" if len(s) else f"{'-':>12}"
        print(row)
    print("\n  가로 — 물량 많은 쪽이 두 줄 다 높다 (제안한 방향)")
    print("  세로 — 일교차 큰 쪽이 두 줄 다 낮다 (제안과 반대)")
    for dq in ("큼", "작음"):
        for vq in ("많음", "적음"):
            s = m[(m["물량군"] == vq) & (m["일교차군"] == dq)]
            if len(s):
                print(f"\n  [일교차 {dq} x 물량 {vq}] " + " · ".join(
                    f"{r.county}({r['물량t']:,.0f}t·{r.dtr_all:.1f}도·{r['상대값']:.3f})"
                    for _, r in s.sort_values("물량t", ascending=False).iterrows()))

    # ── B. 시군 회귀 ─────────────────────────────────────────
    h("B. 시군 14곳 회귀 — 둘을 같이 넣으면")
    m["lq"], m["y"] = np.log(m["물량t"]), np.log(m["상대값"])
    report(m, ["lq"], "① 규모만")
    report(m, ["dtr_all"], "② 일교차만")
    report(m, ["lq", "dtr_all"], "③ 규모 + 일교차   <- 제안")
    report(m, ["lq", "dtr_all", "소형상자%"], "④ + 소형상자")
    print("\n  R2는 0.138·0.074 -> 0.296으로 뛴다. 설명력이 붙는 것은 맞다.")
    print("  그러나 계수 구간이 전부 0을 포함한다. n=14로는 여기까지다.")

    # ── C. 시군 x 연도로 늘리면 ──────────────────────────────
    h("C. 시군 x 연도 — 행을 늘려도 독립 단위는 시군 14개다")
    rel = weekly_relative_w()
    wx = weekly_weather()
    d = rel.merge(wx, on=["county", "wk"], how="inner")
    d["year"] = d["wk"].dt.year
    cy = (d.groupby(["county", "year"])
            .apply(lambda x: pd.Series({
                "rel": np.average(x["rel_w"], weights=x["q"]),
                "q": x["q"].sum(),
                "dtr": np.average(x["dtr"], weights=x["q"]),
                "nwk": len(x)}), include_groups=False)
            .reset_index())
    cy = cy[cy["nwk"] >= 20]           # 그 해 20주 미만이면 연 대표값이라 할 수 없다
    cy["lq"], cy["y"] = np.log(cy["q"]), np.log(cy["rel"])
    cy.to_csv(OUT / "scale_dtr_county_year.csv", index=False, encoding="utf-8-sig")
    print(f"  시군x연도 {len(cy)}점 / 시군 {cy.county.nunique()}개 / "
          f"연 {cy.year.min()}~{cy.year.max()}  (그 해 20주 이상만)")

    print("\n  ⓐ 관측치 단위 부트스트랩 — 행을 독립으로 착각하면")
    report(cy, ["lq", "dtr"], "규모 + 일교차")
    print("\n  ⓑ 시군 블록 부트스트랩 — 같은 시군을 여러 번 센 것을 바로잡으면")
    report(cy, ["lq", "dtr"], "규모 + 일교차", cluster="county")
    print("\n  ⓐ에서 유의해 보이던 것이 ⓑ에서 사라진다면, 그건 연도가 늘어난 것이지")
    print("  독립 표본이 늘어난 것이 아니다. 판단은 ⓑ로 한다.")

    print(f"\n저장: {OUT / 'scale_dtr_county_year.csv'}")

    # ── D. 읍면 — 규모만 보면 단위를 늘릴 수 있다 ────────────
    h("D. 읍면 61개 — 규모에는 기상이 필요 없으니 단위를 늘릴 수 있다")
    e = eup_panel()
    e = e[e["nwk"] >= MIN_WEEKS].copy()
    e["lq"], e["y"] = np.log(e["q"]), np.log(e["rel"])
    print(f"  {MIN_WEEKS}주 이상 읍면 {len(e)}개 / 시군 {e.county.nunique()}개 "
          f"/ 전북 물량의 99.4%")
    print()
    report(e, ["lq"], "ⓐ 읍면을 독립으로")
    print()
    report(e, ["lq"], "ⓑ 시군 블록 — 같은 시군 읍면은 조건을 공유한다",
           cluster="county")
    print()
    e["d_lq"] = e["lq"] - e.groupby("county")["lq"].transform("mean")
    e["y"] = e["y"] - e.groupby("county")["y"].transform("mean")
    report(e, ["d_lq"], "ⓒ 시군 평균을 뺀 뒤 (시군 내 비교)", cluster="county")

    e["rel"], e["q"] = np.exp(e["lq"] * 0 + np.log(e["rel"])), np.exp(e["lq"])
    print("\n  규모 4분위별 (물량가중 상대값)")
    qs = pd.qcut(e["lq"], 4, labels=["1분위(작음)", "2분위", "3분위", "4분위(큼)"])
    tab = (e.groupby(qs, observed=True)
            .apply(lambda x: pd.Series({
                "읍면수": len(x), "물량t": round(x["q"].sum() / 1000),
                "상대값": round(np.average(x["rel"], weights=x["q"]), 3)}),
                   include_groups=False))
    print(tab.to_string())
    print("\n  -> 비례가 아니라 계단이다. 2~4분위는 평평하고 1분위만 10%p 아래다.")
    print("     '클수록 비싸다'가 아니라 '너무 작으면 싸다'로 읽는 편이 맞다.")
    e.drop(columns=["d_lq"]).to_csv(OUT / "scale_dtr_eup.csv", index=False,
                                    encoding="utf-8-sig")
    print(f"\n저장: {OUT / 'scale_dtr_eup.csv'}")


if __name__ == "__main__":
    main()
