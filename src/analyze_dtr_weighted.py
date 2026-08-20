# -*- coding: utf-8 -*-
"""analyze_dtr_weighted.py — 일교차 검정을 물량가중으로 다시 한다.

────────────────────────────────────────────────────────────────
왜
────────────────────────────────────────────────────────────────
1-E의 다섯 설계는 전부 **동일가중**이었다. 그래서 두 군데가 걸린다.

1. **시군 간(설계 1·2)** — 물량 4톤인 군산이 8,712톤인 남원과 같은 한 점이다.
   전북 물량의 1%인 다섯 시군이 가격 폭의 절반을 만든다는 것이 1-F에서
   확인됐는데, 그 다섯이 상관계수도 절반쯤 쥐고 있었다는 뜻이다.
2. **시군 내 주별(설계 3·4)** — 시군×주 상대값을 낼 때 셀을 **단순평균**한다
   (`analyze_dtr_within.weekly_relative`의 `rel=("rel","mean")`).
   0.2톤짜리 셀과 50톤짜리 셀이 같은 무게다.

물량으로 가중하면 달라지는지 본다.

────────────────────────────────────────────────────────────────
결론 — 달라지지 않는다. 그리고 시군 간에서는 가중이 오히려 독이다
────────────────────────────────────────────────────────────────
**시군 간.** 물량가중은 유효표본을 무너뜨린다. Kish N_eff = **3.67**
(실제 14곳). 남원 38% + 익산 32%가 물량의 70%라 사실상 서너 점짜리 상관이 된다.
일교차는 가중해도 r=-0.245로 그대로고, 대조로 넣은 소형상자 비율은 +0.335에서
+0.814로 뛰지만 **95% 구간이 [-0.046, +0.978]로 0을 포함**하고 남원 한 곳을
빼면 +0.256으로 주저앉는다. 둘 다 판정불가다.

> 여기서 얻을 것: **가중은 표본을 늘리지 않는다.** 계수가 커 보여도 N_eff를
> 같이 보지 않으면 1-E에서 겪은 '집단 비교의 함정'을 가중치로 다시 짓는 꼴이다.
> 1-F가 얇은 곳을 *빼는* 쪽을 택한 것은 이래서 옳았다.

**시군 내 주별.** 여기는 표본이 4,000주대(주가중 N_eff 1,419)라 가중해도
안 무너진다. 네 조합 중 셋은 1-E 그대로 r≈0 · 판정불가다. 그런데 **셀·주를 둘 다
물량가중한 하나만** r=-0.056 [-0.084, -0.003]으로 구간이 0을 비껴간다.
얇은 5곳을 빼도 -0.057로 남는다.

**이것을 발견으로 세우지 않는다.** 이유 셋.

1. **부호가 가설과 반대다.** 일교차가 크면 값이 조금 *낮다*. 가설(두꺼운 잎 ->
   상품성 -> 높은 값)을 지지하는 방향이 아니다.
2. **네 설계 중 하나다.** 넷을 돌려 하나가 구간을 아슬하게(상단 -0.003) 비껴간
   것을 골라 쓰면 그게 사양 탐색이다.
3. **가중을 세게 할수록 계수가 커진다.** 일반적 효과라면 가중치 변환에 안정해야
   한다. 실측은 단조로 늘어난다.

       동일 -0.002 (N_eff 4,374) / log1p -0.005 (4,176)
       sqrt -0.028 (2,649)      / q     -0.056 (1,419)

   물량 상위 10%를 잘라내면 -0.019로 줄어든다(끊기는 지점 없이 매끄럽게).
   즉 **큰 주에만 있고 보통 주에는 없다.** 물량(d_lq)을 통제해도 남으므로
   단순한 물량-가격 교란은 아니지만, 크기가 r=-0.056(분산의 0.3%)이라
   해석을 얹을 자리가 아니다.

굳이 말하자면 '출하가 몰리는 주에 일교차가 크면 상대값이 미세하게 낮다' 정도인데,
품질보다 **그 주의 공급 쏠림**으로 읽는 편이 자연스럽다. 어느 쪽이든
1-E의 기각을 뒤집지 않는다.

[실행] python analyze_dtr_weighted.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_dtr_within import demean, weekly_weather   # 기상·차분 정의는 한 곳에서만

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "outputs"

# 1-F가 뺀 '얇은 시군'. 목록을 손으로 적지 않는다 — 1-F의 기준(물량 200t 미만)을
# 그대로 자료에 적용해 유도한다. 자료가 바뀌면 목록도 따라 바뀐다.
THIN_TON = 200.0


def thin_counties() -> tuple[str, ...]:
    g = pd.read_csv(OUT / "region_gap_features.csv")
    return tuple(g.loc[g["물량t"] < THIN_TON, "county"])


# ── 가중 통계 ────────────────────────────────────────────────
def wcorr(x, y, w) -> float:
    x, y, w = np.asarray(x, float), np.asarray(y, float), np.asarray(w, float)
    ok = np.isfinite(x) & np.isfinite(y) & np.isfinite(w) & (w > 0)
    x, y, w = x[ok], y[ok], w[ok]
    if len(x) < 3:
        return np.nan
    mx, my = np.average(x, weights=w), np.average(y, weights=w)
    vx, vy = np.average((x - mx) ** 2, weights=w), np.average((y - my) ** 2, weights=w)
    if vx <= 0 or vy <= 0:
        return np.nan
    return float(np.average((x - mx) * (y - my), weights=w) / np.sqrt(vx * vy))


def n_eff(w) -> float:
    """Kish 유효표본. 가중이 표본을 얼마나 깎았는지."""
    w = np.asarray(w, float)
    return float(w.sum() ** 2 / (w ** 2).sum())


def boot_by_county(df, xcol, ycol, wcol=None, n=4000, seed=20260820):
    """시군 단위 블록 부트스트랩 — 주 단위로 뽑으면 구간이 좁아진다(1-E와 같은 규칙)."""
    rng = np.random.default_rng(seed)
    ctys = df["county"].unique()
    w0 = df[wcol].values if wcol else np.ones(len(df))
    r0 = wcorr(df[xcol], df[ycol], w0)
    bs = []
    for _ in range(n):
        pick = rng.choice(ctys, len(ctys), replace=True)
        sub = pd.concat([df[df["county"] == c] for c in pick], ignore_index=True)
        if len(sub) < 30:
            continue
        r = wcorr(sub[xcol], sub[ycol], sub[wcol].values if wcol else np.ones(len(sub)))
        if np.isfinite(r):
            bs.append(r)
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return r0, float(lo), float(hi)


def verdict(lo, hi) -> str:
    return "판정불가" if lo < 0 < hi else "유의"


# ── 패널 — 원본과 같되 물량을 실어 둔다 ──────────────────────
def weekly_relative_w() -> pd.DataFrame:
    """시군 x 주 상대값. `analyze_dtr_within.weekly_relative`와 같은 설계인데
    (a) 셀 물량 `q`를 남기고 (b) 셀->주 합칠 때 단순평균과 물량가중 둘 다 낸다."""
    d = pd.read_csv(RAW / "lettuce_daily_raw.csv", low_memory=False,
                    usecols=["date", "market_cd", "county", "variety",
                             "price_kg", "qty_kg"], dtype={"market_cd": str})
    d = d[d["county"].notna()].dropna(subset=["price_kg", "qty_kg"])
    d = d[(d["qty_kg"] > 0) & (d["price_kg"] > 0)]
    d["date"] = pd.to_datetime(d["date"], format="mixed")
    d["wk"] = d["date"] - pd.to_timedelta(d["date"].dt.weekday, unit="D")

    key = ["wk", "variety", "market_cd"]
    cell = (d.groupby(key + ["county"])
              .apply(lambda g: pd.Series({
                  "p": np.average(g["price_kg"], weights=g["qty_kg"]),
                  "q": g["qty_kg"].sum()}), include_groups=False)
              .reset_index())
    # 같은 주·품종·시장에 시군이 둘 이상일 때만 — 비교 대상이 있어야 상대값이 뜻이 있다
    cell = cell[cell.groupby(key)["county"].transform("nunique") >= 2]
    cell["rel"] = cell["p"] / cell.groupby(key)["p"].transform("mean")

    def wm(g):
        return np.average(g["rel"], weights=g["q"])
    g = (cell.groupby(["county", "wk"])
             .apply(lambda x: pd.Series({
                 "rel": x["rel"].mean(),        # 원본과 같은 단순평균
                 "rel_w": wm(x),                # 셀 물량가중
                 "q": x["q"].sum(),             # 그 시군·그 주 총물량
                 "ncell": len(x)}), include_groups=False)
             .reset_index())
    return g[g["ncell"] >= 2]


def h(t: str) -> None:
    print("\n" + "=" * 74 + f"\n{t}\n" + "=" * 74)


def main() -> None:
    OUT.mkdir(exist_ok=True)

    # ── A. 시군 간 — 가중이 표본을 깎는다 ────────────────────
    h("A. 시군 간 — 물량가중하면 유효표본이 얼마나 남나")
    g = pd.read_csv(OUT / "region_gap_features.csv")
    p = pd.read_csv(OUT / "dtr_premium.csv")[["county", "dtr_all"]]
    m = g.merge(p, on="county").sort_values("물량t", ascending=False)
    w = m["물량t"].values
    print(f"  시군 {len(m)}개 / 총 {w.sum():,.0f}톤")
    print(f"  상위 2곳({m.county.iloc[0]}·{m.county.iloc[1]}) 이 "
          f"{w[:2].sum()/w.sum()*100:.0f}%")
    print(f"  Kish 유효표본 N_eff = {n_eff(w):.2f}   <- 14개가 아니라 이만큼이다")

    rng = np.random.default_rng(0)
    print(f"\n  {'변수':<12}{'동일가중':>9}{'물량가중':>10}   95%CI(물량가중)      판정")
    for col, nm in (("dtr_all", "일교차"), ("소형상자%", "소형상자비율")):
        x, y = m[col].values, m["상대값"].values
        r_eq, r_w = wcorr(x, y, np.ones(len(x))), wcorr(x, y, w)
        bs = []
        for _ in range(5000):
            i = rng.integers(0, len(m), len(m))
            r = wcorr(x[i], y[i], w[i])
            if np.isfinite(r):
                bs.append(r)
        lo, hi = np.percentile(bs, [2.5, 97.5])
        print(f"  {nm:<12}{r_eq:>+9.3f}{r_w:>+10.3f}   [{lo:+.3f}, {hi:+.3f}]   {verdict(lo, hi)}")

    print("\n  한 곳씩 빼면 (물량가중 r)")
    print(f"    {'뺀 시군':<10}{'일교차':>9}{'소형상자':>10}")
    for c in m.county.head(4):
        s = m[m.county != c]
        print(f"    {c:<10}{wcorr(s.dtr_all, s['상대값'], s['물량t']):>+9.3f}"
              f"{wcorr(s['소형상자%'], s['상대값'], s['물량t']):>+10.3f}")
    print("\n  -> 소형상자가 +0.814로 커 보이지만 남원 하나에 기대고 있다.")
    print("     가중은 표본을 늘리지 않는다. 1-F가 얇은 곳을 뺀 쪽이 옳았다.")

    # ── B. 시군 내 주별 — 여기는 가중해도 안 무너진다 ────────
    h("B. 시군 내 주별 — 표본이 충분한 곳에서 가중하면")
    rel = weekly_relative_w()
    wx = weekly_weather()
    d = rel.merge(wx, on=["county", "wk"], how="inner")
    d["woy"] = d["wk"].dt.isocalendar().week.astype(int)
    for c in ("rel", "rel_w"):
        d[c] = np.log(d[c])
    d["d_dtr"] = demean(d, "dtr")
    d["y"] = demean(d, "rel")
    d["y_w"] = demean(d, "rel_w")
    d = d.dropna(subset=["d_dtr", "y", "y_w", "q"])
    print(f"  표본 {len(d):,}주 / 시군 {d.county.nunique()}개")
    print(f"  주 가중 Kish N_eff = {n_eff(d['q']):,.0f}  <- 여기는 안 무너진다")

    print(f"\n  {'설계':<34}{'r':>8}   95%CI              판정")
    designs = [
        ("셀 단순평균 · 주 동일가중 (1-E 원본)", "d_dtr", "y", None),
        ("셀 물량가중 · 주 동일가중", "d_dtr", "y_w", None),
        ("셀 단순평균 · 주 물량가중", "d_dtr", "y", "q"),
        ("셀 물량가중 · 주 물량가중", "d_dtr", "y_w", "q"),
    ]
    rows = []
    for nm, xc, yc, wc in designs:
        r0, lo, hi = boot_by_county(d, xc, yc, wc, n=2000)
        print(f"  {nm:<34}{r0:>+8.3f}   [{lo:+.3f}, {hi:+.3f}]   {verdict(lo, hi)}")
        rows.append({"design": nm, "r": round(r0, 4),
                     "lo": round(lo, 4), "hi": round(hi, 4),
                     "verdict": verdict(lo, hi)})

    # 얇은 시군을 뺀 판도 — 1-F 기준과 맞춘다
    thin = thin_counties()
    d9 = d[~d.county.isin(thin)]
    r0, lo, hi = boot_by_county(d9, "d_dtr", "y_w", "q", n=2000)
    print(f"  {'셀·주 물량가중 · 얇은 5곳 제외':<34}{r0:>+8.3f}   "
          f"[{lo:+.3f}, {hi:+.3f}]   {verdict(lo, hi)}   ({len(d9):,}주)")
    rows.append({"design": "셀·주 물량가중 · 얇은5곳제외", "r": round(r0, 4),
                 "lo": round(lo, 4), "hi": round(hi, 4), "verdict": verdict(lo, hi)})

    # ── C. 유의하게 나온 하나를 의심한다 ────────────────────
    h("C. 진단 — 셀·주 물량가중만 유의한 것이 실제 효과인가")
    print("  일반적 효과라면 가중치를 어떻게 세우든 계수가 비슷해야 한다.")
    print(f"\n  {'가중치':<12}{'r':>10}{'N_eff':>10}")
    for nm, wv in (("동일", np.ones(len(d))), ("log1p(q)", np.log1p(d["q"])),
                   ("sqrt(q)", np.sqrt(d["q"])), ("q (원본)", d["q"])):
        print(f"  {nm:<12}{wcorr(d['d_dtr'], d['y_w'], wv):>+10.4f}{n_eff(wv):>10,.0f}")
    print("  -> 단조로 커진다. 큰 주에 쏠릴수록 세진다는 뜻이다.")

    print("\n  물량 상위 주를 잘라내면")
    ds = d.sort_values("q", ascending=False).reset_index(drop=True)
    print(f"    {'자른 비율':<12}{'남은 주':>9}{'남은 물량%':>11}{'r':>10}")
    for pct in (0, 1, 2, 5, 10):
        k = int(len(ds) * pct / 100)
        t = ds.iloc[k:]
        print(f"    상위 {pct:>4.1f}%   {len(t):>9,}{t['q'].sum()/ds['q'].sum()*100:>10.1f}%"
              f"{wcorr(t['d_dtr'], t['y_w'], t['q']):>+10.4f}")
    print("    -> 끊기는 지점 없이 매끄럽게 준다. 이상치 몇 개가 아니라")
    print("       '무거운 주에만 있는 것'이다. 보통 주에는 없다.")

    d["d_lq"] = demean(d.assign(lq=np.log(d["q"])), "lq")
    dd = d.dropna(subset=["d_lq"])
    W = np.asarray(dd["q"], float)

    def resid(col):
        A = np.c_[np.ones(len(dd)), dd["d_lq"].values]
        sw = np.sqrt(W / W.sum())[:, None]
        b = np.linalg.lstsq(A * sw, dd[col].values * sw[:, 0], rcond=None)[0]
        return dd[col].values - A @ b

    print(f"\n  물량 통제 편상관 r = {wcorr(resid('d_dtr'), resid('y_w'), W):+.4f}"
          f"   (통제 전 {wcorr(dd['d_dtr'], dd['y_w'], W):+.4f})")
    print("  -> 단순한 물량-가격 교란은 아니다. 그래도 크기가 분산의 0.3%라")
    print("     해석을 얹을 자리가 아니다. 1-E의 기각은 유지된다.")

    pd.DataFrame(rows).to_csv(OUT / "dtr_weighted.csv", index=False,
                              encoding="utf-8-sig")
    print(f"\n저장: {OUT / 'dtr_weighted.csv'}")


if __name__ == "__main__":
    main()
