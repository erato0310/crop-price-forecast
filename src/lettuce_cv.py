# -*- coding: utf-8 -*-
"""lettuce_cv.py — 전일자 타깃 기준 walk-forward 검증 하네스.

────────────────────────────────────────────────────────────────
이 파일이 지키는 규칙 (HANDOFF_rev2가 어긴 것들)
────────────────────────────────────────────────────────────────
1. **예측 시점 미관측 변수 금지.** h=1이면 t-1까지 관측된 값만 쓴다.
   rev2 원본이 당월 강수·당월 거래물량을 넣어 26.64%를 냈는데 그건 설명력이지
   예측력이 아니었다. 여기서는 모든 피처를 shift로 강제한다.

2. **선택도 fold 안에서.** rev2 3.4는 hot_days를 "21개 조건 중 18개 개선"으로
   채택했는데, 그 조건들이 튜닝에 쓴 같은 fold였다. 검증셋으로 고른 변수를
   같은 검증셋으로 정당화한 순환이다. 여기서는
     - 하이퍼파라미터(alpha, blend)는 fold별 **학습구간 내부 CV**로만 고른다
     - 변수집합 비교는 **모든 fold에서 같은 절차**를 반복해 평균으로 판정한다
     - 최종 판정은 튜닝에 한 번도 안 쓴 **독립 구간**으로 확인한다

3. **가중치도 fold 안에서.** 출하량 가중 기상은 학습구간 평년 비중으로만
   계산한다(lettuce_agro_features.build_weights(train_end=...)).
   전 구간 비중을 쓰면 미래 정보가 샌다.

4. **반복 검증.** 단일 fold 평균으로 판정하지 않는다.
     (a) walk-forward 6~8 fold
     (b) fold별 승패 부호 일관성
     (c) 블록 부트스트랩으로 차이의 불확실성 구간
     (d) 독립 홀드아웃

[실행]
  python lettuce_cv.py baseline     # 타깃·베이스라인 점검
  python lettuce_cv.py compare      # 피처집합 비교 (본론)
  python lettuce_cv.py holdout      # 독립 구간 확인
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

_ROOT = Path(__file__).resolve().parent.parent
RAW = _ROOT / "data" / "raw"
PROC = _ROOT / "data" / "processed"
OUT = _ROOT / "outputs"
OUT.mkdir(exist_ok=True)

PRICE_DAILY = RAW / "lettuce_daily_by_county.csv"
AGRO = PROC / "agro_features_monthly.csv"

HORIZON = 1                       # h개월 앞
TEST_YEARS = [2019, 2020, 2021, 2022, 2023, 2024, 2025]   # walk-forward folds
HOLDOUT_YEAR = 2026               # 튜닝에 절대 쓰지 않는 구간
ALPHAS = [0.01, 0.1, 1.0, 3.0, 10.0, 30.0]
BLENDS = [0.0, 0.2, 0.4, 0.6]
MIN_TRAIN = 24


# ═══════════════════════════════════════════════════════════════
# 자료 구성
# ═══════════════════════════════════════════════════════════════

def load_target() -> pd.DataFrame:
    """전북 전체 월별 주력 상추 가격(원/kg, 물량가중) + 물량.

    price_kg / qty_kg 는 이미 '주력 9종'만 담긴 열이다
    (scrape_lettuce_daily.MAIN_VARIETIES, 쫑상추·솎음은 별도 열).
    """
    d = pd.read_csv(PRICE_DAILY)
    d["date"] = pd.to_datetime(d["date"])
    d["ym"] = d["date"].dt.to_period("M")
    rows = []
    for ym, g in d.groupby("ym"):
        w = g[["price_kg", "qty_kg"]].dropna()
        tq = w["qty_kg"].sum()
        jj = g[["price_kg_jjong", "qty_kg_jjong"]].dropna()
        tjj = jj["qty_kg_jjong"].sum()
        rows.append({
            "ym": ym,
            "price": (w["price_kg"] * w["qty_kg"]).sum() / tq if tq else np.nan,
            "qty": tq,
            "price_jjong": ((jj["price_kg_jjong"] * jj["qty_kg_jjong"]).sum() / tjj
                            if tjj else np.nan),
            "qty_jjong": tjj,
            "qty_thin": g["qty_kg_thin"].sum(min_count=1),
            "n_days": g["date"].nunique(),
        })
    t = pd.DataFrame(rows).sort_values("ym").reset_index(drop=True)
    # 진행 중인 달은 거래일이 모자라 월평균이 편향된다 — 뺀다
    cur = pd.Timestamp.today().to_period("M")
    t = t[(t["ym"] != cur) | (t["n_days"] >= 18)]
    return t


def build_panel() -> pd.DataFrame:
    """타깃 + 시차 피처. **모든 피처는 t-HORIZON 시점까지만 관측된 값.**"""
    t = load_target()
    if not AGRO.exists():
        sys.exit("agro_features_monthly.csv 없음 — lettuce_agro_features.py build 먼저")
    a = pd.read_csv(AGRO)
    a["ym"] = pd.PeriodIndex(a["ym"], freq="M")

    p = t.merge(a, on="ym", how="left").sort_values("ym").reset_index(drop=True)
    p["month"] = p["ym"].dt.month
    p["month_sin"] = np.sin(2 * np.pi * p["month"] / 12)
    p["month_cos"] = np.cos(2 * np.pi * p["month"] / 12)
    p["logp"] = np.log(p["price"])

    h = HORIZON
    # 가격 계열 — 예측 시점(t-h)에 알 수 있는 것만
    p["lag_h"] = p["price"].shift(h)
    p["lag12"] = p["price"].shift(12)
    p["roll3"] = p["price"].shift(h).rolling(3).mean()
    p["roll6"] = p["price"].shift(h).rolling(6).mean()
    # 수급 — 당월 물량은 내생·미관측이라 금지. 시차만 쓴다(rev2가 통째로 버린 것)
    p["qty_log_l"] = np.log(p["qty"].replace(0, np.nan)).shift(h)
    # 쫑상추 계열 — 작기 종료·대체수요 지표. 반드시 시차
    p["jjong_rel_l"] = (p["price_jjong"] / p["price"]).shift(h)
    p["jjong_share_l"] = (p["qty_jjong"] / (p["qty"] + p["qty_jjong"])).shift(h)
    p["thin_share_l"] = (p["qty_thin"] / p["qty"]).shift(h)
    return p


# 피처집합. 생리 근거는 lettuce_agro_features.PHYSIO_LAGS 주석 참고.
# _m = 지점 단순평균, _w = 출하량 가중, _spread = 평지-준고랭지 격차
FEATURE_SETS: dict[str, list[str]] = {
    "계절만":      ["month_sin", "month_cos"],
    "가격시차":    ["month_sin", "month_cos", "lag_h", "lag12", "roll3"],
    "rev2재현":    ["month_sin", "month_cos", "lag_h", "lag12", "roll3",
                    "hot_days_m_l1", "hot_days_m_l2"],
    "+광":         ["month_sin", "month_cos", "lag_h", "lag12", "roll3",
                    "dark_days_m_l1", "sun_ratio_m_l1"],
    "+고온(파종기)": ["month_sin", "month_cos", "lag_h", "lag12", "roll3",
                    "vhot_days_m_l1", "germ_block_days_m_l2"],
    "+광+고온":    ["month_sin", "month_cos", "lag_h", "lag12", "roll3",
                    "dark_days_m_l1", "sun_ratio_m_l1",
                    "vhot_days_m_l1", "germ_block_days_m_l2"],
    "+가중기상":   ["month_sin", "month_cos", "lag_h", "lag12", "roll3",
                    "dark_days_w_l1", "sun_ratio_w_l1",
                    "vhot_days_w_l1", "germ_block_days_w_l2"],
    "+격차":       ["month_sin", "month_cos", "lag_h", "lag12", "roll3",
                    "dark_days_m_l1", "sun_ratio_m_l1",
                    "vhot_days_spread_l1", "germ_block_days_spread_l2"],
    "+물량시차":   ["month_sin", "month_cos", "lag_h", "lag12", "roll3",
                    "dark_days_m_l1", "sun_ratio_m_l1", "qty_log_l"],
    "+쫑상추":     ["month_sin", "month_cos", "lag_h", "lag12", "roll3",
                    "dark_days_m_l1", "sun_ratio_m_l1", "jjong_rel_l"],
    "전부":        ["month_sin", "month_cos", "lag_h", "lag12", "roll3",
                    "dark_days_m_l1", "sun_ratio_m_l1", "vhot_days_m_l1",
                    "germ_block_days_m_l2", "qty_log_l", "jjong_rel_l"],
}


# ═══════════════════════════════════════════════════════════════
# 모형
# ═══════════════════════════════════════════════════════════════

def mape(a, f) -> float:
    a, f = np.asarray(a, float), np.asarray(f, float)
    m = np.isfinite(a) & np.isfinite(f) & (a != 0)
    return float(np.mean(np.abs((a[m] - f[m]) / a[m])) * 100) if m.any() else np.nan


def seasonal_baseline(train: pd.DataFrame, target_ym: pd.Series) -> np.ndarray:
    """학습구간 달력월 평균. fold마다 다시 계산된다."""
    mavg = train.groupby(train["ym"].dt.month)["price"].mean()
    fb = train["price"].mean()
    return np.array([mavg.get(m.month, fb) for m in target_ym])


def fit_predict(train: pd.DataFrame, test: pd.DataFrame, cols: list[str],
                alpha: float, blend: float) -> np.ndarray:
    med = train[cols].median(numeric_only=True)
    X = train[cols].fillna(med)
    mod = make_pipeline(StandardScaler(), Ridge(alpha=alpha)).fit(X, np.log(train["price"]))
    reg = np.exp(mod.predict(test[cols].fillna(med)))
    # 학습 범위를 크게 벗어나는 외삽 차단 (crop_county_cv.py의 clip과 같은 취지)
    lo, hi = train["price"].min() / 3, train["price"].max() * 3
    reg = np.clip(reg, lo, hi)
    base = seasonal_baseline(train, test["ym"])
    return blend * base + (1 - blend) * reg


def tune(train: pd.DataFrame, cols: list[str]) -> tuple[float, float]:
    """**학습구간 내부**에서만 alpha/blend를 고른다. 검증 fold를 절대 안 본다."""
    yrs = sorted(train["ym"].dt.year.unique())
    inner = [y for y in yrs[1:] if (train["ym"].dt.year < y).sum() >= MIN_TRAIN]
    if len(inner) < 2:
        return 1.0, 0.2
    best, best_s = (1.0, 0.2), np.inf
    for a in ALPHAS:
        for b in BLENDS:
            errs = []
            for y in inner:
                tr = train[train["ym"].dt.year < y].dropna(subset=["price"])
                te = train[train["ym"].dt.year == y].dropna(subset=["price"])
                if len(tr) < MIN_TRAIN or te.empty:
                    continue
                errs.append(mape(te["price"].values, fit_predict(tr, te, cols, a, b)))
            if errs and np.mean(errs) < best_s:
                best_s, best = float(np.mean(errs)), (a, b)
    return best


def walk_forward(p: pd.DataFrame, cols: list[str],
                 years: list[int] = None) -> pd.DataFrame:
    years = years or TEST_YEARS
    rows = []
    for y in years:
        tr = p[p["ym"].dt.year < y].dropna(subset=["price"])
        te = p[p["ym"].dt.year == y].dropna(subset=["price"])
        if len(tr) < MIN_TRAIN or te.empty:
            continue
        a, b = tune(tr, cols)
        pred = fit_predict(tr, te, cols, a, b)
        base = seasonal_baseline(tr, te["ym"])
        rows.append({"year": y, "n_train": len(tr), "n_test": len(te),
                     "alpha": a, "blend": b,
                     "baseline": mape(te["price"].values, base),
                     "model": mape(te["price"].values, pred)})
    return pd.DataFrame(rows)


def block_bootstrap(p: pd.DataFrame, cols_a: list[str], cols_b: list[str],
                    n: int = 400, seed: int = 0) -> tuple[float, float, float]:
    """두 피처집합의 fold별 MAPE 차이에 대한 블록 부트스트랩 구간.

    월별 오차는 자기상관이 있으므로 개별 관측이 아니라 **fold(연도) 단위**로
    재표집한다. 차이의 95% 구간이 0을 포함하면 '우열 판정 불가'다.
    """
    ra, rb = walk_forward(p, cols_a), walk_forward(p, cols_b)
    m = ra.merge(rb, on="year", suffixes=("_a", "_b"))
    diff = (m["model_a"] - m["model_b"]).values
    if len(diff) < 3:
        return np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    boots = [rng.choice(diff, len(diff), replace=True).mean() for _ in range(n)]
    return float(diff.mean()), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


# ═══════════════════════════════════════════════════════════════

def cmd_baseline(p: pd.DataFrame) -> None:
    print("=" * 76)
    print("타깃 점검 — 전북 주력 상추 월평균가 (원/kg, 물량가중)")
    print("=" * 76)
    t = p.dropna(subset=["price"])
    print(f"  구간 {t['ym'].min()} ~ {t['ym'].max()}  ({len(t)}개월)")
    print(f"  가격 중앙 {t['price'].median():,.0f}  최소 {t['price'].min():,.0f}"
          f"  최대 {t['price'].max():,.0f}")
    print(f"  월 거래일 중앙 {t['n_days'].median():.0f}일")
    print()
    print("  월별 평균가")
    m = t.groupby("month")["price"].mean()
    print("    " + " ".join(f"{x:>7d}" for x in range(1, 13)))
    print("    " + " ".join(f"{m.get(x, np.nan):7,.0f}" for x in range(1, 13)))
    print()
    r = walk_forward(p, FEATURE_SETS["계절만"])
    print("  계절평균 베이스라인 (fold별)")
    print("    " + "  ".join(f"{int(x.year)}:{x.baseline:.1f}%" for _, x in r.iterrows()))
    print(f"    평균 {r['baseline'].mean():.2f}%")


def cmd_compare(p: pd.DataFrame) -> None:
    print("=" * 76)
    print("피처집합 비교 — walk-forward, fold별 재튜닝")
    print("=" * 76)
    print(f"  fold {TEST_YEARS}  |  h={HORIZON}  |  홀드아웃 {HOLDOUT_YEAR} 제외")
    print()
    res = {}
    print(f"  {'피처집합':<14}{'모델':>8}{'베이스':>8}{'개선':>8}{'승':>6}  fold별 모델 MAPE")
    for name, cols in FEATURE_SETS.items():
        miss = [c for c in cols if c not in p.columns]
        if miss:
            print(f"  {name:<14} 컬럼없음: {miss[:3]}")
            continue
        r = walk_forward(p, cols)
        if r.empty:
            continue
        res[name] = r
        win = int((r["model"] < r["baseline"]).sum())
        imp = r["baseline"].mean() - r["model"].mean()
        detail = " ".join(f"{x:.0f}" for x in r["model"])
        print(f"  {name:<14}{r['model'].mean():>7.2f}%{r['baseline'].mean():>7.2f}%"
              f"{imp:>+7.2f}%{win:>4}/{len(r)}  {detail}")

    pd.concat([v.assign(featureset=k) for k, v in res.items()]).to_csv(
        OUT / "lettuce_cv_compare.csv", index=False, encoding="utf-8-sig")

    # 반복검증 (c): 최고 후보 vs 가격시차 기준선의 차이 구간
    print()
    print("  블록 부트스트랩 — '가격시차' 대비 차이의 95% 구간 (fold 단위 재표집)")
    print("  구간이 0을 포함하면 우열 판정 불가")
    ref = FEATURE_SETS["가격시차"]
    for name in ["rev2재현", "+광", "+고온(파종기)", "+광+고온", "+가중기상",
                 "+격차", "+물량시차", "+쫑상추", "전부"]:
        if name not in res:
            continue
        d, lo, hi = block_bootstrap(p, FEATURE_SETS[name], ref)
        verdict = "개선" if hi < 0 else ("악화" if lo > 0 else "판정불가")
        print(f"    {name:<14}{d:>+7.2f}%p  [{lo:+.2f}, {hi:+.2f}]  {verdict}")


def cmd_holdout(p: pd.DataFrame) -> None:
    print("=" * 76)
    print(f"독립 홀드아웃 {HOLDOUT_YEAR} — 튜닝에 한 번도 쓰지 않은 구간")
    print("=" * 76)
    tr = p[p["ym"].dt.year < HOLDOUT_YEAR].dropna(subset=["price"])
    te = p[p["ym"].dt.year == HOLDOUT_YEAR].dropna(subset=["price"])
    if te.empty:
        sys.exit("홀드아웃 구간 없음")
    print(f"  학습 {len(tr)}개월 / 검증 {len(te)}개월 ({te['ym'].min()}~{te['ym'].max()})")
    print()
    base = seasonal_baseline(tr, te["ym"])
    print(f"  {'피처집합':<14}{'MAPE':>8}{'vs계절평균':>11}   월별오차%")
    print(f"  {'계절평균':<14}{mape(te['price'].values, base):>7.2f}%{'':>11}   "
          + " ".join(f"{x:+.0f}" for x in (base - te['price'].values)
                     / te['price'].values * 100))
    for name, cols in FEATURE_SETS.items():
        if any(c not in p.columns for c in cols):
            continue
        a, b = tune(tr, cols)
        pred = fit_predict(tr, te, cols, a, b)
        mp = mape(te["price"].values, pred)
        bm = mape(te["price"].values, base)
        err = (pred - te["price"].values) / te["price"].values * 100
        print(f"  {name:<14}{mp:>7.2f}%{bm-mp:>+10.2f}%   "
              + " ".join(f"{x:+.0f}" for x in err))
    print()
    print("  주의: 홀드아웃은 한 번만 보는 것이다. 여기 맞춰 재튜닝하면 의미를 잃는다.")


def _oof(p: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """fold별 out-of-fold 예측을 모아 월 단위 진단에 쓴다."""
    out = []
    for y in TEST_YEARS:
        tr = p[p["ym"].dt.year < y].dropna(subset=["price"])
        te = p[p["ym"].dt.year == y].dropna(subset=["price"])
        if len(tr) < MIN_TRAIN or te.empty:
            continue
        a, b = tune(tr, cols)
        out.append(pd.DataFrame({
            "ym": te["ym"].values, "month": te["month"].values,
            "actual": te["price"].values,
            "pred": fit_predict(tr, te, cols, a, b),
            "base": seasonal_baseline(tr, te["ym"]),
        }))
    return pd.concat(out, ignore_index=True)


def cmd_diag(p: pd.DataFrame) -> None:
    """월별로 어디서 도움이 되고 어디서 해가 되는지. rev2는 '9월 집중'을 주장했다."""
    print("=" * 76)
    print("진단 1 — 월별 오차 (out-of-fold, 2020~2025)")
    print("=" * 76)
    ref = _oof(p, FEATURE_SETS["가격시차"])
    ref["e"] = np.abs(ref["pred"] / ref["actual"] - 1) * 100
    ref["eb"] = np.abs(ref["base"] / ref["actual"] - 1) * 100
    rows = {"계절평균": ref.groupby("month")["eb"].mean(),
            "가격시차": ref.groupby("month")["e"].mean()}
    for name in ["+광", "+고온(파종기)", "rev2재현", "+격차"]:
        d = _oof(p, FEATURE_SETS[name])
        d["e"] = np.abs(d["pred"] / d["actual"] - 1) * 100
        rows[name] = d.groupby("month")["e"].mean()
    print("  " + " " * 14 + " ".join(f"{m:>6d}" for m in range(1, 13)) + f"{'평균':>8}")
    for k, v in rows.items():
        print(f"  {k:<14}" + " ".join(f"{v.get(m, np.nan):6.1f}" for m in range(1, 13))
              + f"{v.mean():>8.1f}")
    print()
    print("  '가격시차' 대비 개선폭(음수=개선)")
    for k, v in rows.items():
        if k in ("계절평균", "가격시차"):
            continue
        d = v - rows["가격시차"]
        print(f"  {k:<14}" + " ".join(f"{d.get(m, np.nan):+6.1f}" for m in range(1, 13))
              + f"{d.mean():>+8.1f}")

    print()
    print("=" * 76)
    print("진단 2 — fold별 선택된 하이퍼파라미터")
    print("=" * 76)
    print(f"  {'피처집합':<14}" + "".join(f"{y:>12d}" for y in TEST_YEARS[1:]))
    for name in ["가격시차", "+광", "rev2재현", "전부"]:
        r = walk_forward(p, FEATURE_SETS[name])
        s = "".join(f"{'a'+str(x.alpha)+'/b'+str(x.blend):>12}" for _, x in r.iterrows())
        print(f"  {name:<14}{s}")
    print("  blend가 크면 회귀가 아니라 계절평균에 의존한다는 뜻이다.")

    print()
    print("=" * 76)
    print("진단 3 — 로그오차 기준 (MAPE는 고가월에 지배된다)")
    print("=" * 76)
    print(f"  {'피처집합':<14}{'MAPE':>9}{'RMSLE':>9}{'중앙절대%':>10}")
    for name, cols in FEATURE_SETS.items():
        if any(c not in p.columns for c in cols):
            continue
        d = _oof(p, cols)
        ape = np.abs(d["pred"] / d["actual"] - 1) * 100
        rmsle = float(np.sqrt(np.mean((np.log(d["pred"]) - np.log(d["actual"])) ** 2)))
        print(f"  {name:<14}{ape.mean():>8.2f}%{rmsle:>9.4f}{ape.median():>9.2f}%")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["baseline", "compare", "holdout", "diag"])
    a = ap.parse_args()
    p = build_panel()
    {"baseline": cmd_baseline, "compare": cmd_compare,
     "holdout": cmd_holdout, "diag": cmd_diag}[a.cmd](p)


if __name__ == "__main__":
    main()
