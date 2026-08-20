# -*- coding: utf-8 -*-
"""analyze_dtr_threshold.py — 여름 일교차 10℃ 문턱 가설.

────────────────────────────────────────────────────────────────
가설
────────────────────────────────────────────────────────────────
사용자 제안. **여름에 일최고−일최저가 10℃쯤 나는 지역과 안 나는 지역 사이에
가격 차이가 분명히 존재한다.**

앞선 `analyze_dtr_within.py` 는 일교차와 값의 **연속 상관**을 봤고 r≈0이었다.
그런데 생리에는 문턱이 흔하다. 잎이 두꺼워지는 데 필요한 야간 냉각이
어느 선을 넘어야 일어난다면, 상관은 0이어도 **문턱을 기준으로 가른 두 집단의
차이는 날 수 있다.** 그래서 따로 검정한다.

────────────────────────────────────────────────────────────────
설계 셋
────────────────────────────────────────────────────────────────
A. 시군 단위 — 여름 일교차 10℃ 이상 4곳 vs 미만 10곳의 상대값 차이.
   표본이 14개라 약하다. 순열검정으로 우연히 이만큼 갈릴 확률을 낸다.

B. **시군 × 주 단위** — 여름 주만 놓고, 그 주 일교차가 10℃를 넘었는지로 가른다.
   시군·주차 평년 대비 편차를 쓰므로 시군의 고정된 성질과 계절이 상쇄된다.
   같은 시군 안에서 "10℃ 넘은 주 vs 못 넘은 주"를 견주는 것이라 A보다 훨씬 세다.

C. 탐색 — 문턱을 8~12℃로 훑어 어디서 갈리는지 본다.
   **이건 탐색이다.** 여기서 제일 잘 갈리는 값을 골라 "유의하다"고 말하면
   다중검정이다. 참고로만 적는다.

────────────────────────────────────────────────────────────────
값 정의
────────────────────────────────────────────────────────────────
상대값 = 같은 주·같은 품종·같은 시장 안에서 그 시군이 받은 값 / 셀 평균.
전국 시세 변동과 품종·시장 차이는 이미 빠져 있다.

[실행] python analyze_dtr_threshold.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from analyze_dtr_premium import COUNTY_STN, load_weather, SUMMER
from analyze_dtr_within import weekly_relative, demean

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs"

THRESHOLD = 10.0
MIN_WEEKS = 40


def weekly_weather() -> pd.DataFrame:
    wx = load_weather()
    wx["wk"] = wx["date"] - pd.to_timedelta(wx["date"].dt.weekday, unit="D")
    rows = []
    for cty, (stns, _) in COUNTY_STN.items():
        s = wx[wx["stn"].isin(stns)]
        if s.empty:
            continue
        day = s.groupby("date").agg(dtr=("dtr", "mean"), wk=("wk", "first"))
        g = day.groupby("wk").agg(dtr=("dtr", "mean"), nday=("dtr", "size"))
        g = g[g["nday"] >= 5].reset_index()
        g["county"] = cty
        rows.append(g)
    return pd.concat(rows, ignore_index=True)


def perm_test(a, b, n=20000, seed=20260814):
    """두 집단 평균차의 순열검정. 표본이 작아 정규가정을 안 쓴다."""
    rng = np.random.default_rng(seed)
    a, b = np.asarray(a, float), np.asarray(b, float)
    obs = a.mean() - b.mean()
    pool = np.concatenate([a, b])
    k = len(a)
    cnt = 0
    for _ in range(n):
        rng.shuffle(pool)
        if abs(pool[:k].mean() - pool[k:].mean()) >= abs(obs):
            cnt += 1
    return obs, (cnt + 1) / (n + 1)


def boot_diff(df, group_col, val_col, by="county", n=4000, seed=20260814):
    """시군 단위 블록 부트스트랩으로 두 집단 평균차의 구간."""
    rng = np.random.default_rng(seed)
    ctys = df[by].unique()
    hi = df[df[group_col]][val_col].mean()
    lo = df[~df[group_col]][val_col].mean()
    obs = hi - lo
    bs = []
    for _ in range(n):
        pick = rng.choice(ctys, len(ctys), replace=True)
        sub = pd.concat([df[df[by] == c] for c in pick], ignore_index=True)
        h, l = sub[sub[group_col]][val_col], sub[~sub[group_col]][val_col]
        if len(h) < 20 or len(l) < 20:
            continue
        bs.append(h.mean() - l.mean())
    if len(bs) < 100:
        return obs, np.nan, np.nan
    return obs, *np.percentile(bs, [2.5, 97.5])


def main() -> None:
    wxw = weekly_weather()
    rel = weekly_relative()
    m = rel.merge(wxw, on=["county", "wk"], how="inner")
    m["month"] = m["wk"].dt.month
    m["woy"] = m["wk"].dt.isocalendar().week.astype(int)
    sm = m[m["month"].isin(SUMMER)].copy()

    # ── A. 시군 단위 ───────────────────────────────────────────
    print("=" * 78)
    print(f"A. 시군 단위 — 여름 일교차 {THRESHOLD}℃ 이상 vs 미만")
    print("=" * 78)
    cty = sm.groupby("county").agg(dtr=("dtr", "mean"), rel=("rel", "mean"),
                                   n=("rel", "size")).reset_index()
    cty = cty[cty["n"] >= MIN_WEEKS]
    cty["hi"] = cty["dtr"] >= THRESHOLD
    print(f"{'시군':<7}{'여름일교차':>10}{'상대값':>9}{'주수':>7}  집단")
    for _, r in cty.sort_values("dtr", ascending=False).iterrows():
        print(f"{r['county']:<7}{r['dtr']:10.1f}{r['rel']:9.3f}{int(r['n']):7d}  "
              f"{'10℃ 이상' if r['hi'] else '10℃ 미만'}")
    a, b = cty[cty["hi"]]["rel"], cty[~cty["hi"]]["rel"]
    print()
    print(f"  10℃ 이상 {len(a)}곳 평균 {a.mean():.3f}  /  미만 {len(b)}곳 평균 {b.mean():.3f}")
    if len(a) >= 2 and len(b) >= 2:
        d, p = perm_test(a, b)
        print(f"  차이 {d:+.3f}  순열검정 p = {p:.3f}"
              f"  -> {'차이 있음' if p < 0.05 else '판정불가'}")

    # ── B. 시군 × 주 단위 ──────────────────────────────────────
    print()
    print("=" * 78)
    print(f"B. 시군 × 주 단위 — 같은 시군 안에서 {THRESHOLD}℃ 넘은 주 vs 못 넘은 주")
    print("=" * 78)
    sm = sm[sm.groupby("county")["wk"].transform("size") >= MIN_WEEKS].copy()
    sm["lrel"] = np.log(sm["rel"])
    sm["y"] = demean(sm, "lrel")            # 시군·주차 평년 대비
    sm["hi"] = sm["dtr"] >= THRESHOLD
    n_hi, n_lo = int(sm["hi"].sum()), int((~sm["hi"]).sum())
    print(f"  여름 {len(sm):,}주 · 시군 {sm['county'].nunique()}개")
    print(f"  10℃ 이상 {n_hi:,}주 / 미만 {n_lo:,}주")
    # 두 집단이 다 있는 시군만 — 한쪽만 있는 시군은 비교에 기여하지 못한다
    both = sm.groupby("county")["hi"].nunique() == 2
    use = sm[sm["county"].isin(both[both].index)].copy()
    print(f"  두 집단이 다 있는 시군 {use['county'].nunique()}개 · {len(use):,}주")
    if len(use) > 100:
        d, lo, hi = boot_diff(use, "hi", "y")
        v = "차이 있음" if (lo > 0 or hi < 0) else "판정불가"
        print(f"  log 상대값 차이 {d:+.4f}  95% [{lo:+.4f}, {hi:+.4f}]  -> {v}")
        print(f"  (= 값으로 {np.exp(d)*100-100:+.1f}%)")
        print()
        print(f"  {'시군':<7}{'10℃이상':>9}{'10℃미만':>9}{'차이':>9}{'주수':>13}")
        for c, g in use.groupby("county"):
            h, l = g[g["hi"]]["y"], g[~g["hi"]]["y"]
            if len(h) < 5 or len(l) < 5:
                continue
            print(f"  {c:<7}{h.mean():+9.3f}{l.mean():+9.3f}{h.mean()-l.mean():+9.3f}"
                  f"{len(h):>7}/{len(l):<6}")

    # ── C. 탐색 ────────────────────────────────────────────────
    print()
    print("=" * 78)
    print("C. 탐색 — 문턱을 옮겨 보면 (※ 여기서 제일 센 값을 고르면 다중검정이다)")
    print("=" * 78)
    print(f"  {'문턱':>6}{'차이':>10}{'95% 구간':>22}{'이상 주수':>10}")
    for th in (8.0, 8.5, 9.0, 9.5, 10.0, 10.5, 11.0, 11.5, 12.0):
        s2 = sm.copy()
        s2["hi"] = s2["dtr"] >= th
        both2 = s2.groupby("county")["hi"].nunique() == 2
        u2 = s2[s2["county"].isin(both2[both2].index)]
        if len(u2) < 100 or u2["hi"].sum() < 30:
            print(f"  {th:6.1f}      표본 부족")
            continue
        d, lo, hi = boot_diff(u2, "hi", "y", n=1500)
        mark = " *" if (lo > 0 or hi < 0) else ""
        print(f"  {th:6.1f}{d:+10.4f}   [{lo:+.4f}, {hi:+.4f}]{int(u2['hi'].sum()):>9}{mark}")

    OUT.mkdir(exist_ok=True)
    sm.to_csv(OUT / "dtr_threshold.csv", index=False, encoding="utf-8-sig")
    print(f"\n저장: {OUT/'dtr_threshold.csv'}")


if __name__ == "__main__":
    main()
