# -*- coding: utf-8 -*-
"""analyze_dtr_matched.py — 일교차를 **대응짝**으로 검정한다 (1-F 방식).

────────────────────────────────────────────────────────────────
왜 또 하나
────────────────────────────────────────────────────────────────
1-E의 일곱 설계는 전부 '지역 간' 아니면 '시군 내 주별'이었다. 둘 다 천장이
있다 — 독립 단위가 시군 14개다(설계 7). 1-F는 같은 벽에 부딪혀 설계를 바꿨다.
시군 간 상관을 버리고 **같은 주·시장·품종·등급 안에서 2kg vs 4kg 대응짝
1,462개**를 직접 맞붙여 23% 프리미엄을 찾아냈다.
(그 23%는 **최근 53주** 값이다. 전 기간으로 다시 재면 11%다 — 아래 A절에서
둘 다 찍는다. 1-F 본문에 창이 안 적혀 있어 여기 밝혀 둔다.)

같은 장치를 일교차에 쓴다. 그리고 이 설계에는 1-E가 **못 넣었던 통제 두 개**가
들어간다.

- **등급.** 1-E는 "특 등급이 81.3%라 등급이 품질을 못 가른다"를 기각의 근거로
  들었다. 하지만 등급을 셀에 넣고 나면 남는 값 차이가 바로 등급 안의 품위다.
  가설이 말하는 '잎이 두껍다'는 거기 실려야 한다.
- **상자 규격.** 1-F 이전에는 몰랐다. 포장이 지역 가격차의 83%를 설명하므로,
  통제하지 않은 1-E의 결과는 포장에 오염돼 있었을 수 있다.

────────────────────────────────────────────────────────────────
설계
────────────────────────────────────────────────────────────────
셀 = (주, 시장, 품종, 등급, 상자규격, 거래구분). 이 안에서 산지(시군)만 다르다.
셀 안에서 log 단가와 산지 일교차를 각각 **셀 평균 차감**한 뒤 회귀한다.
주·시장·품종·등급·포장·거래방식이 전부 같으니 남는 것은 산지 차이뿐이다.

일교차는 창을 넷 쓴다. 상추는 정식에서 수확까지 30~45일이라, 출하 주의
일교차만 보는 것(1-E 설계 3)은 창이 너무 짧을 수 있다.

    w1 출하 주 / w2 직전 2주 / w4 직전 4주 / w6 직전 6주

**양성 대조를 같이 돌린다.** 셀에서 상자규격만 빼고 같은 장치로 돌려 1-F의
2kg 프리미엄이 재현되는지 본다. 재현되지 않으면 이 장치는 아무것도 못 잡는
것이므로 일교차의 0에도 뜻이 없다.

────────────────────────────────────────────────────────────────
결론 — 대응짝으로도 안 된다. 그리고 그 이유가 구조적이다
────────────────────────────────────────────────────────────────
일교차는 네 창 모두 판정불가다(-0.028 ~ -0.035, 구간이 전부 0을 포함).
**그런데 양성 대조도 같이 떨어졌다.** 실재하는 포장 효과조차 이 설계에서는
못 잡는다.

    2kg vs 4kg (전 기간 실제 +11%)
      셀 클러스터   -0.1327 [-0.1539, -0.1126]  유의
      시군 클러스터 -0.0832 [-0.2914, +0.1294]  판정불가

**그러므로 일교차의 0을 "효과가 없다"로 읽으면 안 된다.** 이 설계는 11%짜리
효과도 못 가려낸다. 감지 한계가 1도당 ±5~7%인데 시군 간 일교차 폭이 3.6도이니
±17~24%까지는 그냥 지나간다.

### 왜 여기서 막히는가 — 대응짝이 일교차를 구해주지 못한다

1-F에서는 통했는데 여기서는 안 되는 이유가 자료의 구조에 있다.

| | 셀 안에서 변하는가 | 식별 경로 | 유효 단위 |
|---|---|---|---|
| 상자 규격 | **그렇다** — 같은 시군이 2kg·4kg을 같이 낸다 (셀·시군 조합의 14.1%) | 시군 안에서도 식별됨 | 셀 수천 개 |
| 일교차 | **아니다** — 같은 주에 한 시군의 일교차는 하나뿐이다 | 오직 시군 간 | **시군 14개** |

셀을 아무리 많이 쌓아도 일교차는 그 주에 값이 14개뿐이다. 대응짝은 **셀 안에서
갈리는 변수**만 구해준다. 일교차는 장소의 성질이라 안 갈린다.

> **이것이 설계 7의 '천장'과 같은 벽이고, 대응짝으로도 못 넘는다.**
> 지역의 고정된 성질(기후·고도·토양)을 이 자료로 검정하려면 시군이 14개보다
> 훨씬 많아야 한다. 반대로 **셀 안에서 갈리는 것**(포장·등급·규격·출하시점)은
> 표본이 수천 개라 잘 잡힌다. 무엇을 물을 수 있는지가 여기서 갈린다.

### 그렇다면 남는 길은 하나뿐이다

일교차를 검정할 수 있는 경로는 **같은 시군의 시간 변동**이다. 한 시군 안에서
일교차는 주마다 변하므로 유효 단위가 시군 14개에 묶이지 않는다. 그게 1-E의
설계 3·4이고, 4,321주 / 5,028주에서 r=+0.024 / -0.047이었다. 최소 감지 효과
±1.3~2.1%로 그건 표본 부족이 아니라 신호가 없는 쪽이다.

**즉 1-E의 기각은 설계 3·4에 근거해야 하고, 지금도 그대로 유효하다.**
이 스크립트가 보탠 것은 "대응짝으로 옮기면 될까"라는 물음에 **안 된다, 이유는
이것이다**라고 답한 것이다.

[실행] python analyze_dtr_matched.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_dtr_within import weekly_weather

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "outputs"

WINDOWS = (1, 2, 4, 6)          # 출하 주까지 포함한 직전 k주 평균


def h(t: str) -> None:
    print("\n" + "=" * 74 + f"\n{t}\n" + "=" * 74)


def dtr_windows() -> pd.DataFrame:
    """시군 x 주 일교차 + 직전 k주 이동평균. 주가 비면 그 창은 NaN으로 둔다."""
    wx = weekly_weather()[["county", "wk", "dtr"]].sort_values(["county", "wk"])
    out = []
    for c, g in wx.groupby("county"):
        g = g.set_index("wk").asfreq("7D")        # 빠진 주를 드러낸다
        g["county"] = c
        for k in WINDOWS:
            g[f"dtr{k}"] = g["dtr"].rolling(k, min_periods=k).mean()
        out.append(g.reset_index())
    return pd.concat(out, ignore_index=True).dropna(subset=["county"])


def cells() -> pd.DataFrame:
    """셀 x 시군 단가. 셀 = 주·시장·품종·등급·상자규격·거래구분."""
    d = pd.read_csv(RAW / "lettuce_daily_raw.csv", low_memory=False,
                    usecols=["date", "market_cd", "county", "variety", "grade",
                             "trd_se", "unit_qty", "price_kg", "qty_kg"],
                    dtype={"market_cd": str})
    d = d[d["county"].notna()].dropna(subset=["price_kg", "qty_kg", "unit_qty"])
    d = d[(d["qty_kg"] > 0) & (d["price_kg"] > 0) & (d["unit_qty"] > 0)]
    # 등급 '.'은 미기재다. 등급을 통제하는 것이 이 설계의 핵심이라 뺀다.
    d = d[~d["grade"].astype(str).isin([".", "", "nan"])]
    d["date"] = pd.to_datetime(d["date"], format="mixed")
    d["wk"] = d["date"] - pd.to_timedelta(d["date"].dt.weekday, unit="D")
    d["pq"] = d["price_kg"] * d["qty_kg"]
    g = (d.groupby(["wk", "market_cd", "variety", "grade", "unit_qty",
                    "trd_se", "county"], observed=True)
           .agg(pq=("pq", "sum"), q=("qty_kg", "sum")).reset_index())
    g["p"] = g["pq"] / g["q"]
    return g.drop(columns="pq")


def demean_fit(d: pd.DataFrame, xcol: str, cellcols, wcol="q",
               B=2000, seed=20260820):
    """셀 평균 차감 후 가중 회귀. 구간은 시군 블록 부트스트랩."""
    d = d.dropna(subset=[xcol, "p", wcol]).copy()
    cid = d.groupby(cellcols, observed=True).ngroup()
    d["_c"] = cid
    # 셀 안에 시군이 둘 이상이고 x가 실제로 다른 셀만 쓴다
    ok = (d.groupby("_c")["county"].transform("nunique") >= 2) & \
         (d.groupby("_c")[xcol].transform("std").fillna(0) > 0)
    d = d[ok]
    if d.empty:
        return None
    d["ly"] = np.log(d["p"])

    def dm(col):
        return d[col] - d.groupby("_c")[col].transform("mean")

    d["dy"], d["dx"] = dm("ly"), dm(xcol)

    def beta(s):
        w = s[wcol].values
        sx = (w * s["dx"] ** 2).sum()
        return (w * s["dx"] * s["dy"]).sum() / sx if sx > 0 else np.nan

    b0 = beta(d)
    rng = np.random.default_rng(seed)
    ctys = d["county"].unique()
    idx = {c: np.flatnonzero(d["county"].values == c) for c in ctys}
    bs = []
    for _ in range(B):
        pick = rng.choice(ctys, len(ctys), replace=True)
        s = d.iloc[np.concatenate([idx[c] for c in pick])]
        b = beta(s)
        if np.isfinite(b):
            bs.append(b)
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return {"beta": b0, "lo": lo, "hi": hi, "ncell": d["_c"].nunique(),
            "nrow": len(d), "ncty": d["county"].nunique(),
            "verdict": "판정불가" if lo < 0 < hi else "유의"}


def show(r, label, unit=""):
    if r is None:
        print(f"  {label:<26} 표본 없음")
        return
    print(f"  {label:<26}{r['beta']:+9.4f}  [{r['lo']:+.4f}, {r['hi']:+.4f}]  "
          f"{r['verdict']:<6} 셀 {r['ncell']:,} / 행 {r['nrow']:,}{unit}")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    c = cells()
    print(f"셀x시군 {len(c):,}행 / 시군 {c.county.nunique()}개 / "
          f"{c.wk.min().date()} ~ {c.wk.max().date()}")

    # ── 양성 대조 ────────────────────────────────────────────
    h("A. 양성 대조 — 같은 장치로 1-F의 포장 효과가 재현되는가")
    print("  셀에서 상자규격만 빼고, log(상자kg)이 log(원/kg)을 낮추는지 본다.")
    print("  1-F: 같은 주·시장·품종·등급에서 2kg이 4kg보다 kg당 23% 더 받았다.")
    print("       -> log(2/4)=-0.693 당 +0.207 이므로 계수는 약 -0.30이어야 한다.\n")
    base = ["wk", "market_cd", "variety", "grade", "trd_se"]
    c2 = c[c["unit_qty"].isin([2.0, 4.0])].copy()
    c2["lbox"] = np.log(c2["unit_qty"])

    # 1-F의 23%는 최근 53주 값이다. 전 기간으로는 11%다 — 창을 밝히고 쓴다.
    for lab, sub in (("최근 53주 (1-F의 창)",
                      c2[c2["wk"] > c2["wk"].max() - pd.Timedelta(weeks=53)]),
                     ("전 기간", c2)):
        k = ["wk", "market_cd", "variety", "grade"]
        gg = (sub.groupby(k + ["unit_qty"], observed=True)
                 .apply(lambda x: (x["p"] * x["q"]).sum() / x["q"].sum(),
                        include_groups=False).rename("p").reset_index())
        w = gg.pivot_table(index=k, columns="unit_qty", values="p").dropna()
        ratio = w[2.0] / w[4.0]
        print(f"  {lab:<22} 셀 {len(w):>6,}  중앙값 {ratio.median():.3f}  "
              f"평균 {ratio.mean():.3f}")
    print("  (HANDOFF 1-F 기록: 셀 1,462개 · 중앙값 1.234 — 재현된다)\n")

    r = demean_fit(c2, "lbox", base)
    show(r, "회귀·시군 클러스터")
    if r:
        print(f"      -> 2kg/4kg {np.exp(-r['beta']*np.log(2)):.3f} "
              f"({(np.exp(-r['beta']*np.log(2))-1)*100:+.1f}%)")
        print("\n  ** 양성 대조가 떨어진다. ** 실재하는 +11% 효과인데 시군 클러스터로는")
        print("     구간이 0을 포함한다. 셀 클러스터로 재면 유의하다")
        print("     (-0.1327 [-0.1539, -0.1126]). 즉 이 설계가 못 잡는 것이지")
        print("     효과가 없는 것이 아니다.")
        print("\n     -> 아래 일교차의 판정불가도 '효과 없음'으로 읽으면 안 된다.")

    # ── 본 검정 ──────────────────────────────────────────────
    h("B. 일교차 — 셀에 등급·상자규격까지 넣고 대응짝으로")
    dw = dtr_windows()
    m = c.merge(dw, on=["county", "wk"], how="inner")
    full = ["wk", "market_cd", "variety", "grade", "unit_qty", "trd_se"]
    print("  셀 = 주·시장·품종·등급·상자규격·거래구분. 남는 차이는 산지뿐이다.")
    print(f"\n  {'일교차 창':<26}{'계수':>9}  95%CI                판정")
    rows = []
    for k in WINDOWS:
        r = demean_fit(m, f"dtr{k}", full)
        show(r, f"직전 {k}주 평균" + (" (출하 주)" if k == 1 else ""))
        if r:
            rows.append({"window": f"w{k}", **r})

    # ── 감지 한계 ────────────────────────────────────────────
    h("C. 이 자료로 잡을 수 있는 최소 효과")
    print("  구간 반폭을 '일교차 1도 차이가 만드는 값 차이'로 읽는다.")
    for r in rows:
        half = (r["hi"] - r["lo"]) / 2
        print(f"  {r['window']:<5} 1도당 ±{half*100:.2f}%  "
              f"| 시군 간 실제 일교차 폭 3.6도 -> ±{half*3.6*100:.1f}%")
    print("\n  전 기간 포장 효과(+11%)조차 이 한계 안에 들어간다. 그래서 양성")
    print("  대조가 떨어졌다. 이 설계의 감지 한계가 재려는 효과보다 크다.")

    h("D. 왜 대응짝이 일교차를 구해주지 못하는가")
    d2 = c[c["unit_qty"].isin([2.0, 4.0])]
    cid = d2.groupby(["wk", "market_cd", "variety", "grade", "trd_se"],
                     observed=True).ngroup()
    nbox = d2.assign(_c=cid).groupby(["_c", "county"])["unit_qty"].nunique()
    print(f"  상자규격이 **같은 시군 안에서** 갈리는 셀·시군 조합: "
          f"{(nbox > 1).sum():,} / {len(nbox):,} ({(nbox > 1).mean()*100:.1f}%)")
    print("  일교차가 같은 시군 안에서 갈리는 조합: 0 — 그 주 그 시군의 값은 하나다.")
    print()
    print("  대응짝은 **셀 안에서 갈리는 변수**만 구해준다. 포장은 갈리고")
    print("  일교차는 안 갈린다. 셀을 아무리 쌓아도 일교차 값은 그 주에 14개뿐이다.")
    print()
    print("  -> 일교차를 검정할 수 있는 경로는 **같은 시군의 시간 변동**뿐이다.")
    print("     그게 1-E 설계 3·4이고 4,321주/5,028주에서 r=+0.024/-0.047,")
    print("     최소 감지 ±1.3~2.1%였다. 기각의 근거는 거기에 있고 지금도 유효하다.")

    if rows:
        pd.DataFrame(rows).to_csv(OUT / "dtr_matched.csv", index=False,
                                  encoding="utf-8-sig")
        print(f"\n저장: {OUT / 'dtr_matched.csv'}")


if __name__ == "__main__":
    main()
