# -*- coding: utf-8 -*-
"""analyze_autumn_surge.py — 늦여름·가을 급등기를 정의하고, 맞힐 수 있는지 검정한다.

────────────────────────────────────────────────────────────────
왜 따로 보는가
────────────────────────────────────────────────────────────────
`lettuce_probabilistic.py`의 '폭등'은 **그 달 평년의 1.3배 초과**로 정의한다.
계절 효과를 일부러 빼는 정의라, 9월처럼 원래 비싼 달은 9,154원이어도
'정상'으로 처리된다(2025-09 실측: 가격 9,154 < 기준선 10,954).

그런데 농가가 묻는 것은 그게 아니다.

    "3,000원 하던 게 9,000원 되는 그 시기가 언제 시작해서 몇 주 가나"

이건 계절 효과를 **빼는 게 아니라 그 자체가 답**인 질문이다. 그래서 정의를
다시 세운다.

────────────────────────────────────────────────────────────────
급등기 정의 (누출 없음)
────────────────────────────────────────────────────────────────
    기준가 base_y = 그 해 1~6월 주간가격의 중앙값
    급등 상태      주간가격 > base_y × RATIO   (기본 2.0배)
    급등기         7~11월 안에서 급등 상태가 이어지는 최장 구간
                   (1주짜리 끊김은 이어 붙인다 — 한 주 쉬었다고 끝난 게 아니다)

**기준가를 상반기로 잡은 이유**: 연중앙값을 쓰면 급등기 자신이 중앙값을
끌어올려 정의가 자기참조가 되고, 무엇보다 7월 시점에 아직 모르는 값이라
예측에 못 쓴다. 상반기 중앙값은 6월 말이면 확정된다.

────────────────────────────────────────────────────────────────
검정 규칙 (프로젝트 공통)
────────────────────────────────────────────────────────────────
- 반드시 대조군과 함께 본다. 여기서는 둘을 쓴다.
    (1) 주차 기후값 — 그 주차가 과거에 급등 상태였던 비율
    (2) 지속성     — 이번 주 상태가 다음 주에도 이어진다
  지속성을 빼면 "다음 주도 급등"이라는 쉬운 예측을 실력으로 오인한다.
- 연도 단위 walk-forward. 학습에 미래 연도가 섞이면 안 된다.
- 블록 부트스트랩 95% 구간이 0을 포함하면 **판정불가**이지 개선이 아니다.
- CV에서 고른 것을 홀드아웃 성적으로 다시 고르지 않는다.

[실행]
  python analyze_autumn_surge.py            # 기술통계 + 예측 검정 전부
  python analyze_autumn_surge.py describe   # 기술통계만
  python analyze_autumn_surge.py predict    # 예측 검정만
  python analyze_autumn_surge.py --ratio 1.8
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "outputs"

RATIO = 2.0            # 급등 기준 배율
SEASON = (7, 11)       # 급등기를 찾는 달 범위(포함)
GAP = 1                # 이 주수 이하의 끊김은 이어 붙인다
MIN_WEEKS_HALF1 = 12   # 상반기 주가 이보다 적으면 그 해는 기준가를 못 잡는다


# ── 자료 ────────────────────────────────────────────────────────
def weekly_price(by_county: pd.DataFrame, county: str | None = None) -> pd.DataFrame:
    """주간 물량가중 평균가. county=None이면 전북 전체."""
    d = by_county
    if county:
        d = d[d["county"] == county]
    d = d.dropna(subset=["price_kg", "qty_kg"])
    d = d[d["qty_kg"] > 0]
    if d.empty:
        return pd.DataFrame(columns=["week", "price", "qty"])
    # 주 시작일(월요일)로 묶는다 — 웹앱 주간 계열과 같은 기준
    wk = d["date"] - pd.to_timedelta(d["date"].dt.weekday, unit="D")
    g = d.assign(week=wk).groupby("week")
    out = pd.DataFrame({
        "price": g.apply(lambda x: np.average(x["price_kg"], weights=x["qty_kg"])),
        "qty": g["qty_kg"].sum() / 1000.0,          # t
    }).reset_index()
    return out.sort_values("week").reset_index(drop=True)


def load_county() -> pd.DataFrame:
    p = RAW / "lettuce_daily_by_county.csv"
    d = pd.read_csv(p, encoding="utf-8-sig")
    d["date"] = pd.to_datetime(d["date"], format="%Y-%m-%d")
    return d


def load_weather() -> pd.DataFrame:
    """전북 ASOS 지점 평균의 주간 요약. 급등 원인 후보(고온·일조)를 만든다."""
    p = RAW / "daily_weather_lettuce.csv"
    if not p.exists():
        return pd.DataFrame(columns=["week"])
    w = pd.read_csv(p, encoding="utf-8-sig")
    w["date"] = pd.to_datetime(w["date"], errors="coerce")
    w = w.dropna(subset=["date"])
    day = w.groupby("date").agg(tmax=("tmax", "mean"), tavg=("tavg", "mean"),
                                rain=("rain", "mean"), sun=("sun_hr", "mean"))
    day["hot"] = (day["tmax"] >= 30).astype(float)
    day["vhot"] = (day["tmax"] >= 33).astype(float)
    wk = day.index - pd.to_timedelta(day.index.weekday, unit="D")
    g = day.assign(week=wk).groupby("week")
    return pd.DataFrame({
        "tmax": g["tmax"].mean(), "hot": g["hot"].sum(), "vhot": g["vhot"].sum(),
        "rain": g["rain"].sum(), "sun": g["sun"].sum(),
    }).reset_index()


# ── 급등기 ──────────────────────────────────────────────────────
def mark_surge(wp: pd.DataFrame, ratio: float = RATIO) -> pd.DataFrame:
    """주간 계열에 base_y(상반기 중앙값)와 급등 상태를 붙인다."""
    d = wp.copy()
    d["year"] = d["week"].dt.year
    d["month"] = d["week"].dt.month
    d["woy"] = d["week"].dt.isocalendar().week.astype(int)
    base = {}
    for y, g in d.groupby("year"):
        h1 = g[g["month"] <= 6]["price"]
        base[y] = h1.median() if len(h1) >= MIN_WEEKS_HALF1 else np.nan
    d["base"] = d["year"].map(base)
    d["rel"] = d["price"] / d["base"]
    d["surge"] = (d["rel"] > ratio).astype(float)
    d.loc[d["base"].isna(), "surge"] = np.nan
    return d


def surge_periods(d: pd.DataFrame, gap: int = GAP) -> pd.DataFrame:
    """연도별 급등기(최장 구간)를 뽑는다. SEASON 달 안에서만 찾는다."""
    rows = []
    for y, g in d.groupby("year"):
        g = g[(g["month"] >= SEASON[0]) & (g["month"] <= SEASON[1])].reset_index(drop=True)
        if g.empty or g["base"].isna().all():
            continue
        idx = list(g.index[g["surge"] == 1])
        if not idx:
            rows.append({"year": y, "base": g["base"].iloc[0], "n_weeks": 0})
            continue
        # gap 이하로 떨어진 것은 같은 구간으로 본다
        runs, cur = [], [idx[0]]
        for a, b in zip(idx, idx[1:]):
            if b - a <= gap + 1:
                cur.append(b)
            else:
                runs.append(cur); cur = [b]
        runs.append(cur)
        best = max(runs, key=lambda r: (r[-1] - r[0] + 1))
        seg = g.loc[best[0]:best[-1]]
        peak = seg.loc[seg["price"].idxmax()]
        rows.append({
            "year": y,
            "base": round(float(g["base"].iloc[0])),
            "start": seg["week"].iloc[0].date(),
            "end": seg["week"].iloc[-1].date(),
            "n_weeks": len(seg),
            "peak_week": peak["week"].date(),
            "peak": round(float(peak["price"])),
            "peak_x": round(float(peak["rel"]), 2),
            "mean_x": round(float(seg["rel"].mean()), 2),
            "qty_t": round(float(seg["qty"].sum())),
        })
    return pd.DataFrame(rows)


# ── 기술통계 ────────────────────────────────────────────────────
def describe(ratio: float) -> pd.DataFrame:
    by = load_county()
    wp = weekly_price(by)
    d = mark_surge(wp, ratio)
    per = surge_periods(d)

    print("=" * 78)
    print(f"전북 급등기 — 상반기 중앙값의 {ratio}배 초과, {SEASON[0]}~{SEASON[1]}월에서 탐색")
    print("=" * 78)
    if per.empty:
        print("  탐지된 구간이 없다")
        return per
    full = per[per["n_weeks"] > 0]
    print(f"{'연도':>5} {'기준가':>7} {'시작':>11} {'종료':>11} {'주수':>4} "
          f"{'최고주':>11} {'최고가':>7} {'배율':>5} {'구간평균배율':>7}")
    for _, r in per.iterrows():
        if r["n_weeks"] == 0:
            print(f"{r['year']:>5} {r['base']:>7} {'—':>11} {'—':>11} {0:>4}")
            continue
        print(f"{r['year']:>5} {r['base']:>7} {str(r['start']):>11} {str(r['end']):>11} "
              f"{r['n_weeks']:>4} {str(r['peak_week']):>11} {r['peak']:>7} "
              f"{r['peak_x']:>5} {r['mean_x']:>7}")
    if len(full):
        st = pd.to_datetime(full["start"])
        print()
        print(f"  시작 주: 중앙값 {st.dt.strftime('%m-%d').median() if False else ''}"
              f"{sorted(st.dt.strftime('%m-%d'))[len(st)//2]} "
              f"(가장 이른 {st.dt.strftime('%m-%d').min()} / 늦은 {st.dt.strftime('%m-%d').max()})")
        print(f"  지속:   중앙값 {int(full['n_weeks'].median())}주 "
              f"({int(full['n_weeks'].min())}~{int(full['n_weeks'].max())}주)")
        print(f"  최고가: 중앙값 기준가의 {full['peak_x'].median():.1f}배 "
              f"({full['peak_x'].min():.1f}~{full['peak_x'].max():.1f}배)")
        print(f"  해당 연도 {len(full)}/{len(per)}")

    OUT.mkdir(exist_ok=True)
    per.to_csv(OUT / "autumn_surge_periods.csv", index=False, encoding="utf-8-sig")

    # 시군별 — 물량이 충분한 곳만
    by_c = []
    for c, g in by.groupby("county"):
        wpc = weekly_price(by, c)
        if len(wpc) < 150:
            continue
        dc = mark_surge(wpc, ratio)
        pc = surge_periods(dc)
        pc = pc[pc["n_weeks"] > 0]
        if len(pc) < 4:
            continue
        st = pd.to_datetime(pc["start"])
        by_c.append({
            "county": c, "years": len(pc),
            "start_med": sorted(st.dt.strftime("%m-%d"))[len(st) // 2],
            "weeks_med": int(pc["n_weeks"].median()),
            "peak_x_med": round(float(pc["peak_x"].median()), 1),
        })
    bc = pd.DataFrame(by_c).sort_values("start_med")
    if len(bc):
        print()
        print("시군별 (급등기가 4개 연도 이상 잡히는 곳)")
        print(f"{'시군':>7} {'연도수':>5} {'시작 중앙값':>11} {'지속':>5} {'최고배율':>7}")
        for _, r in bc.iterrows():
            print(f"{r['county']:>7} {r['years']:>5} {r['start_med']:>11} "
                  f"{r['weeks_med']:>4}주 {r['peak_x_med']:>6}배")
        bc.to_csv(OUT / "autumn_surge_by_county.csv", index=False, encoding="utf-8-sig")
    return per


# ── 예측 ────────────────────────────────────────────────────────
def build_features(ratio: float) -> pd.DataFrame:
    by = load_county()
    d = mark_surge(weekly_price(by), ratio)
    w = load_weather()
    d = d.merge(w, on="week", how="left")
    d = d[d["base"].notna()].reset_index(drop=True)

    d["lrel"] = np.log(d["rel"])
    d["lrel1"] = d["lrel"].shift(1)
    d["lrel4"] = d["lrel"].shift(4)
    d["mom4"] = d["lrel"] - d["lrel4"]
    d["qty_l"] = np.log1p(d["qty"])
    d["qty_mom4"] = d["qty_l"] - d["qty_l"].shift(4)
    for c in ("hot", "vhot", "sun", "rain"):
        if c in d:
            d[c + "_4"] = d[c].rolling(4, min_periods=1).sum()
    d["sin"] = np.sin(2 * np.pi * d["woy"] / 52.0)
    d["cos"] = np.cos(2 * np.pi * d["woy"] / 52.0)
    # 타깃: 다음 주 급등 상태
    d["y"] = d["surge"].shift(-1)
    d["surge_now"] = d["surge"]
    return d.dropna(subset=["y", "lrel1", "mom4"]).reset_index(drop=True)


FEATS = ["sin", "cos", "lrel", "lrel1", "mom4", "qty_l", "qty_mom4",
         "hot_4", "vhot_4", "sun_4", "rain_4"]


def auc(y: np.ndarray, p: np.ndarray) -> float:
    y = np.asarray(y); p = np.asarray(p)
    pos, neg = y == 1, y == 0
    if pos.sum() == 0 or neg.sum() == 0:
        return np.nan
    r = pd.Series(p).rank().to_numpy()      # 동점은 평균 순위 — 지속성 대조군에 필수
    return (r[pos].sum() - pos.sum() * (pos.sum() + 1) / 2) / (pos.sum() * neg.sum())


def brier(y, p):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def predict(ratio: float) -> None:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import make_pipeline

    d = build_features(ratio)
    feats = [c for c in FEATS if c in d.columns]
    years = sorted(d["year"].unique())
    folds = [y for y in years if y >= 2020 and y <= 2025]

    print()
    print("=" * 78)
    print("다음 주 급등 상태 예측 — 연도 walk-forward")
    print("=" * 78)
    print(f"  표본 {len(d)}주 · 급등 상태 {int(d['y'].sum())}주 ({d['y'].mean()*100:.1f}%)")
    print(f"  피처 {len(feats)}개: {', '.join(feats)}")

    rec = []
    for ty in folds:
        tr = d[d["year"] < ty]
        te = d[d["year"] == ty]
        if te.empty or tr["y"].nunique() < 2:
            continue
        m = make_pipeline(StandardScaler(),
                          LogisticRegression(C=0.5, max_iter=2000, class_weight="balanced"))
        m.fit(tr[feats], tr["y"])
        p_model = m.predict_proba(te[feats])[:, 1]
        # 대조군 1: 주차 기후값 — 학습구간에서 그 주차가 급등이던 비율
        clim = tr.groupby("woy")["y"].mean()
        p_clim = te["woy"].map(clim).fillna(tr["y"].mean()).to_numpy()
        # 대조군 2: 지속성 — 이번 주 상태를 그대로
        p_pers = te["surge_now"].to_numpy()
        for nm, p in (("model", p_model), ("clim", p_clim), ("pers", p_pers)):
            rec.append({"year": ty, "which": nm, "auc": auc(te["y"], p),
                        "brier": brier(te["y"], p), "n": len(te)})
    R = pd.DataFrame(rec)
    if R.empty:
        print("  검정할 fold가 없다")
        return

    print()
    print(f"  {'':10}{'AUC':>8}{'Brier':>9}   fold별 AUC")
    for nm, lab in (("model", "모델"), ("clim", "주차 기후값"), ("pers", "지속성")):
        s = R[R["which"] == nm]
        per_fold = " ".join(f"{v:.2f}" if pd.notna(v) else " — " for v in s["auc"])
        print(f"  {lab:<10}{s['auc'].mean():>8.3f}{s['brier'].mean():>9.4f}   {per_fold}")

    # 블록 부트스트랩 — fold(=연도) 단위로 다시 뽑는다. 주 단위로 뽑으면
    # 이웃 주가 강하게 붙어 있어 구간이 실제보다 좁아진다.
    piv = R.pivot(index="year", columns="which", values="auc").dropna()
    rng = np.random.default_rng(20260813)
    for other, lab in (("clim", "주차 기후값"), ("pers", "지속성")):
        diff = (piv["model"] - piv[other]).to_numpy()
        if len(diff) < 3:
            continue
        bs = [rng.choice(diff, len(diff), replace=True).mean() for _ in range(4000)]
        lo, hi = np.percentile(bs, [2.5, 97.5])
        verdict = "개선" if lo > 0 else ("악화" if hi < 0 else "판정불가")
        print(f"  모델 − {lab:<9} AUC {diff.mean():+.3f}  95% [{lo:+.3f}, {hi:+.3f}]  → {verdict}")

    # 홀드아웃 2026 — CV에서 아무것도 다시 고르지 않는다
    tr = d[d["year"] < 2026]; te = d[d["year"] == 2026]
    if len(te) and te["y"].nunique() > 1:
        m = make_pipeline(StandardScaler(),
                          LogisticRegression(C=0.5, max_iter=2000, class_weight="balanced"))
        m.fit(tr[feats], tr["y"])
        p = m.predict_proba(te[feats])[:, 1]
        clim = tr.groupby("woy")["y"].mean()
        pc = te["woy"].map(clim).fillna(tr["y"].mean()).to_numpy()
        print()
        print(f"  홀드아웃 2026 ({len(te)}주, 급등 {int(te['y'].sum())}주): "
              f"모델 AUC {auc(te['y'], p):.3f} / 기후값 {auc(te['y'], pc):.3f}")
    else:
        print()
        print(f"  홀드아웃 2026: 급등 주가 {int(te['y'].sum()) if len(te) else 0}주라 AUC를 낼 수 없다")

    R.to_csv(OUT / "autumn_surge_cv.csv", index=False, encoding="utf-8-sig")
    print(f"\n  저장: {OUT/'autumn_surge_cv.csv'}")


def onset(ratio: float, horizon: int = 4) -> None:
    """진짜 어려운 문제 — **아직 급등이 안 왔는데 곧 시작하는가.**

    `predict`의 AUC 0.95는 대부분 지속성이다. 이번 주가 기준가의 3배면 다음 주도
    2배를 넘는 게 당연하다. 농가가 7월 초에 묻는 것은 그게 아니라
    "지금은 조용한데 앞으로 4주 안에 오르기 시작하느냐"이다.
    그래서 **아직 급등에 들어가지 않은 주만** 남기고 다시 검정한다.
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import make_pipeline

    d = build_features(ratio)
    # 그 해 급등이 시작되기 전 주만 남긴다. 시작 이후는 '이미 아는 상태'다.
    first = d[d["surge"] == 1].groupby("year")["week"].min()
    d["first"] = d["year"].map(first)
    pre = d[(d["first"].isna()) | (d["week"] < d["first"])].copy()
    pre = pre[(pre["month"] >= 5) & (pre["month"] <= 9)]
    # 타깃: 앞으로 horizon주 안에 급등이 시작되는가
    weeks_to = (pre["first"] - pre["week"]).dt.days / 7.0
    pre["y_on"] = ((weeks_to > 0) & (weeks_to <= horizon)).astype(float)
    pre = pre.dropna(subset=["lrel1", "mom4"]).reset_index(drop=True)

    feats = [c for c in FEATS if c in pre.columns]
    print()
    print("=" * 78)
    print(f"급등 시작 예측 — 아직 급등 전인 주만, '{horizon}주 안에 시작하는가'")
    print("=" * 78)
    print(f"  표본 {len(pre)}주 (5~9월, 급등 시작 전) · 양성 {int(pre['y_on'].sum())}주 "
          f"({pre['y_on'].mean()*100:.1f}%)")

    rec = []
    for ty in [y for y in sorted(pre['year'].unique()) if 2020 <= y <= 2025]:
        tr, te = pre[pre["year"] < ty], pre[pre["year"] == ty]
        if te.empty or tr["y_on"].nunique() < 2 or te["y_on"].nunique() < 2:
            rec.append({"year": ty, "auc_m": np.nan, "auc_c": np.nan, "n": len(te)})
            continue
        m = make_pipeline(StandardScaler(),
                          LogisticRegression(C=0.5, max_iter=2000, class_weight="balanced"))
        m.fit(tr[feats], tr["y_on"])
        p = m.predict_proba(te[feats])[:, 1]
        clim = tr.groupby("woy")["y_on"].mean()
        pc = te["woy"].map(clim).fillna(tr["y_on"].mean()).to_numpy()
        rec.append({"year": ty, "auc_m": auc(te["y_on"], p), "auc_c": auc(te["y_on"], pc),
                    "n": len(te), "pos": int(te["y_on"].sum())})
    R = pd.DataFrame(rec)
    ok = R.dropna(subset=["auc_m", "auc_c"])
    # fold별 표본을 같이 찍는다. n이 한 자리면 AUC 1.00은 실력이 아니라
    # 그냥 줄 세울 것이 몇 개 없다는 뜻이다.
    print(f"  fold 표본: "
          + ", ".join(f"{int(r.year)} n={int(r.n)}(양성 {int(r.pos)})" for r in R.itertuples()))
    print(f"  {'':10}{'AUC':>8}   fold별")
    for col, lab in (("auc_m", "모델"), ("auc_c", "주차 기후값")):
        print(f"  {lab:<10}{ok[col].mean():>8.3f}   "
              + " ".join(f"{v:.2f}" for v in R[col].fillna(np.nan)
                         if pd.notna(v)))
    if len(ok) >= 3:
        diff = (ok["auc_m"] - ok["auc_c"]).to_numpy()
        rng = np.random.default_rng(20260813)
        bs = [rng.choice(diff, len(diff), replace=True).mean() for _ in range(4000)]
        lo, hi = np.percentile(bs, [2.5, 97.5])
        verdict = "개선" if lo > 0 else ("악화" if hi < 0 else "판정불가")
        print(f"  모델 − 기후값  AUC {diff.mean():+.3f}  95% [{lo:+.3f}, {hi:+.3f}]  → {verdict}")
    else:
        print("  fold가 3개 미만이라 구간을 낼 수 없다 → 판정불가")
    R.to_csv(OUT / "autumn_surge_onset_cv.csv", index=False, encoding="utf-8-sig")


def export(ratio: float) -> None:
    """웹앱용 JSON. 기술통계만 싣는다 — 시작 시기 예측은 판정불가라 싣지 않는다."""
    import json
    from datetime import datetime

    by = load_county()

    def pack(wp: pd.DataFrame) -> dict | None:
        d = mark_surge(wp, ratio)
        per = surge_periods(d)
        full = per[per["n_weeks"] > 0]
        if len(full) < 3:
            return None
        st = pd.to_datetime(full["start"])
        return {
            "periods": [
                {"year": int(r["year"]), "base": int(r["base"]),
                 "start": str(r["start"]), "end": str(r["end"]),
                 "weeks": int(r["n_weeks"]), "peak_week": str(r["peak_week"]),
                 "peak": int(r["peak"]), "peak_x": float(r["peak_x"])}
                for _, r in full.iterrows()
            ],
            "years_total": int(len(per)),
            "years_hit": int(len(full)),
            "start_med": sorted(st.dt.strftime("%m-%d"))[len(st) // 2],
            "start_min": st.dt.strftime("%m-%d").min(),
            "start_max": st.dt.strftime("%m-%d").max(),
            "weeks_med": int(full["n_weeks"].median()),
            "weeks_min": int(full["n_weeks"].min()),
            "weeks_max": int(full["n_weeks"].max()),
            "peak_x_med": round(float(full["peak_x"].median()), 1),
            "peak_x_min": round(float(full["peak_x"].min()), 1),
            "peak_x_max": round(float(full["peak_x"].max()), 1),
        }

    out = {
        "meta": {
            "ratio": ratio,
            "season": list(SEASON),
            "built": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "def_ko": f"그 해 1~6월 주간가격 중앙값의 {ratio}배를 넘는 구간",
            "why_ko": ("계절 효과를 빼는 '폭등확률'과 다르다. 9월은 원래 비싸서 "
                       "평년 대비로는 정상으로 잡히지만, 농가가 겪는 것은 "
                       "상반기 대비 몇 배냐다."),
            # 검정 결과를 화면에 그대로 적기 위해 같이 싣는다. 좋게 포장하지 않는다.
            # 앞머리("시작 시기는 맞히지 못한다")는 화면 쪽에서 붙이므로 여기 넣지 않는다.
            "limit_ko": ("아직 급등 전인 주만 놓고 "
                         "'4주 안에 시작하는가'를 검정했더니 fold당 표본이 8~12주에 "
                         "양성 4주뿐이라 AUC가 1.00까지 나오지만, 주차 기후값(달력) "
                         "대비 개선폭 95% 구간이 0을 포함해 판정불가다. "
                         "달력이 아는 것 이상을 더한다는 증거가 없다."),
        },
        "jeonbuk": pack(weekly_price(by)),
        "counties": {},
    }
    for c, _ in by.groupby("county"):
        wpc = weekly_price(by, c)
        if len(wpc) < 150:
            continue
        p = pack(wpc)
        if p:
            out["counties"][c] = p

    dst = ROOT / "webapp" / "data" / "lettuce_surge.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    print(f"저장: {dst} ({dst.stat().st_size/1024:.0f} KB, "
          f"전북 + 시군 {len(out['counties'])}곳)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", nargs="?", default="all",
                    choices=["all", "describe", "predict", "onset", "export"])
    ap.add_argument("--ratio", type=float, default=RATIO)
    a = ap.parse_args()
    if a.mode in ("all", "describe"):
        describe(a.ratio)
    if a.mode in ("all", "predict"):
        predict(a.ratio)
    if a.mode in ("all", "onset"):
        onset(a.ratio)
    if a.mode in ("all", "export"):
        export(a.ratio)


if __name__ == "__main__":
    main()
