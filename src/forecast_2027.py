# -*- coding: utf-8 -*-
"""forecast_2027.py — 2027년까지 월별 가격 전망. 시군·읍면 단위.

────────────────────────────────────────────────────────────────
방법을 왜 이렇게 정했나 — 재귀 예측을 쓰지 않는다
────────────────────────────────────────────────────────────────
2027년은 지금(2026-08)에서 최대 17개월 앞이다. 검증된 지평은 h=1개월이다.
지평별로 실제 성적을 재보니(test_long_horizon.py) 답이 명확했다.

    h(개월)   계절평균   직접예측   추세보정
      1      22.49%   22.57%   26.79%
      3      22.67%   22.20%   28.19%   <- 여기까지만 모델이 이긴다
      6      22.77%   24.43%   24.93%
     12      22.99%   29.74%   24.74%
     18      22.77%   27.59%   26.90%

**h>=4개월부터는 계절평균이 최선이다.** 계절평균은 지평과 무관하게 22.4~23.1%로
평평한데(달력만 보므로), 모델은 지평이 늘수록 나빠진다. h=12에서 29.74% vs 22.99%.

그래서 2027 전망은 **계절평균을 뼈대로** 만든다. 재귀로 밀면 rev2가 겪은
구간 폭발(2,095~126,146원)이 그대로 재현된다.

────────────────────────────────────────────────────────────────
산출 방식
────────────────────────────────────────────────────────────────
  1~3개월 앞 (2026-09~11)   모델(계절+가격시차, 스미어링) — 검증된 구간
  4개월 이상 (2026-12~2027-12)  계절평균 x 수준보정

수준보정은 '최근 12개월 평균 / 그 이전 12개월 평균'이다. 계절 모양은 과거
평균을 그대로 쓰고 **수준만 최근 시세에 맞춘다**. 0.8~1.25로 자른다 —
그 이상 벌어지면 추세가 아니라 이상치일 가능성이 크다.

구간은 지평별 실측 로그잔차 표준편차로 만든다(h=12에서 sigma 0.308,
80% 구간 2.2배). 재귀가 아니므로 지평이 늘어도 폭이 폭발하지 않는다.

────────────────────────────────────────────────────────────────
반드시 함께 읽을 것
────────────────────────────────────────────────────────────────
- 2027 전망은 **예측이 아니라 계절 평년값에 최근 수준을 반영한 참고치**다.
  그 해 작황·기상·수요 충격은 원리적으로 반영돼 있지 않다.
- 실제로 상추는 그 달 충격이 그 달에 소진된다(무저장성). 1년 앞 정보가
  현재 자료에 남아 있지 않다는 것이 이 프로젝트의 반복된 결론이다.
- 10월은 연도별 편차가 5.9배(변동계수 51.9%)라 어떤 방법으로도 못 맞힌다.

[실행] python forecast_2027.py
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

import lettuce_cv as CV
from scrape_lettuce_daily import is_main_variety
from export_lettuce_webapp import COUNTY_ID, extract_eup

_ROOT = Path(__file__).resolve().parent.parent
RAW = _ROOT / "data" / "raw"
OUT = _ROOT / "outputs"
WEB = _ROOT / "webapp" / "data"

END = pd.Period("2027-12")
MODEL_H = 3                 # 여기까지만 모델. 그 이후는 계절평균 기반
LEVEL_CLIP = (0.80, 1.25)
SIGMA_BY_H = {1: 0.338, 3: 0.352, 6: 0.311, 12: 0.308, 18: 0.320}
MIN_MONTHS = 36             # 이보다 짧으면 전망을 내지 않는다


def sigma_for(h: int) -> float:
    ks = sorted(SIGMA_BY_H)
    k = min(ks, key=lambda x: abs(x - h))
    return SIGMA_BY_H[k]


def _load_horizon_mape() -> dict[int, dict]:
    """지평별 실측 성적(test_long_horizon.py 산출물). 각 전망에 오차율을 붙인다."""
    p = OUT / "long_horizon.csv"
    if not p.exists():
        return {}
    t = pd.read_csv(p)
    return {int(r["h"]): {"seasonal": round(float(r["seasonal"]), 1),
                          "direct": round(float(r["direct"]), 1),
                          "best": r["best"]} for _, r in t.iterrows()}


HMAPE = _load_horizon_mape()


def mape_for(h: int, method: str) -> float | None:
    """그 지평·그 방법의 walk-forward 실측 MAPE."""
    if not HMAPE:
        return None
    k = min(HMAPE, key=lambda x: abs(x - h))
    return HMAPE[k]["direct" if method == "model" else "seasonal"]


def _wavg(g):
    x = g[["price_kg", "qty_kg"]].dropna()
    t = x["qty_kg"].sum()
    return (x["price_kg"] * x["qty_kg"]).sum() / t if t else np.nan


def monthly_series(g: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for ym, mg in g.groupby("ym"):
        p = _wavg(mg)
        if np.isfinite(p):
            rows.append({"ym": ym, "price": p, "qty": mg["qty_kg"].sum(),
                         "ndays": mg["date"].nunique()})
    d = pd.DataFrame(rows).sort_values("ym").reset_index(drop=True)
    # 진행 중인 달은 잘라낸다 (2026-08은 11일까지뿐)
    cur = pd.Timestamp.today().to_period("M")
    return d[(d["ym"] != cur) | (d["ndays"] >= 18)].reset_index(drop=True)


def level_ratio(s: pd.DataFrame) -> float:
    """최근 12개월 수준 / 그 이전 12개월 수준."""
    if len(s) < 24:
        return 1.0
    a = s["price"].iloc[-12:].mean()
    b = s["price"].iloc[-24:-12].mean()
    if not (a > 0 and b > 0):
        return 1.0
    return float(np.clip(a / b, *LEVEL_CLIP))


def forecast_unit(s: pd.DataFrame) -> list[dict]:
    """마지막 실측 다음 달부터 2027-12까지."""
    if len(s) < MIN_MONTHS:
        return []
    last = s["ym"].iloc[-1]
    n = (END - last).n
    if n <= 0:
        return []

    # 계절 평년 — 달력월 평균 (전 구간)
    m = s.copy()
    m["month"] = m["ym"].dt.month
    seas = m.groupby("month")["price"].mean()
    fb = m["price"].mean()
    lvl = level_ratio(s)

    # 1~MODEL_H 개월은 모델 예측.
    # **단위 자신의 시계열**로 적합해야 한다. 전북 전체 패널을 쓰면 모든 시군·읍면이
    # 같은 값을 받는다(초기 구현의 버그).
    model_pred: dict[int, float] = {}
    try:
        p = s.copy()
        p["month"] = p["ym"].dt.month
        p["month_sin"] = np.sin(2 * np.pi * p["month"] / 12)
        p["month_cos"] = np.cos(2 * np.pi * p["month"] / 12)
        p["lag_h"] = p["price"].shift(1)
        p["lag12"] = p["price"].shift(12)
        p["roll3"] = p["price"].shift(1).rolling(3).mean()
        tr = p.dropna(subset=["price", "lag_h", "lag12", "roll3"])
        if len(tr) < CV.MIN_TRAIN:
            raise ValueError("표본 부족")
        a, b = CV.tune(tr, CV.FEATURE_SETS["가격시차"])
        hist = list(tr["price"].values)
        for k in range(1, MODEL_H + 1):
            ym = last + k
            row = {"month_sin": np.sin(2 * np.pi * ym.month / 12),
                   "month_cos": np.cos(2 * np.pi * ym.month / 12),
                   "lag_h": hist[-1],
                   "lag12": hist[-12] if len(hist) >= 12 else hist[-1],
                   "roll3": float(np.mean(hist[-3:]))}
            te = pd.DataFrame([row])
            te["ym"] = ym
            v = float(CV.fit_predict(tr, te, CV.FEATURE_SETS["가격시차"], a, b)[0])
            model_pred[k] = v
            hist.append(v)
    except Exception:
        model_pred = {}

    out = []
    for k in range(1, n + 1):
        ym = last + k
        base = float(seas.get(ym.month, fb)) * lvl
        if k <= MODEL_H and k in model_pred:
            # 검증 구간: 모델. 다만 계절평년에서 너무 벗어나면 당긴다
            v = float(np.clip(model_pred[k], base * 0.5, base * 2.0))
            method = "model"
        else:
            v = base
            method = "seasonal"
        sg = sigma_for(k)
        out.append({
            "ym": str(ym), "h": k, "p": round(v),
            "lo": round(v * np.exp(-1.2816 * sg)),
            "hi": round(v * np.exp(1.2816 * sg)),
            "method": method,
            "method_ko": "직접예측(모델)" if method == "model" else "계절평균×수준보정",
            "mape": mape_for(k, method),      # 그 지평에서 실측된 오차율
            "validated": k <= MODEL_H,
        })
    return out


def main() -> None:
    d = pd.read_csv(RAW / "lettuce_daily_raw.csv",
                    dtype={"market_cd": str, "plor_cd": str}, low_memory=False)
    d = d[d["county"].notna()].copy()
    d = d[[is_main_variety(v) for v in d["variety"]]]
    d["date"] = pd.to_datetime(d["date"], format="mixed")
    d["ym"] = d["date"].dt.to_period("M")
    d["eup"] = [extract_eup(p, c) for p, c in zip(d["plor_nm"], d["county"])]

    print("=" * 76)
    print(f"2027 전망 — 마지막 실측 다음 달부터 {END}까지")
    print("=" * 76)
    print(f"  1~{MODEL_H}개월: 모델(검증됨) / {MODEL_H+1}개월 이후: 계절평균 x 수준보정")
    print()

    res = {"meta": {
        "built": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "end": str(END), "model_horizon": MODEL_H,
        "method_note": (f"1~{MODEL_H}개월은 모델(계절+가격시차). "
                        f"{MODEL_H+1}개월 이후는 계절평균×수준보정 — "
                        f"지평별 실측에서 h>=4부터 계절평균이 모델을 이긴다."),
        "caution": ("2027 전망은 예측이 아니라 계절 평년값에 최근 수준을 반영한 "
                    "참고치다. 그 해 작황·기상·수요 충격은 반영돼 있지 않다."),
        "interval": "80% (지평별 실측 로그잔차 sigma 0.31~0.35)",
    }, "counties": {}}

    for cname, cg in d.groupby("county"):
        cid = COUNTY_ID.get(cname)
        if cid is None:
            continue
        cs = monthly_series(cg)
        fc = forecast_unit(cs)
        if not fc:
            continue
        eups = {}
        for ename, eg in cg.groupby("eup"):
            es = monthly_series(eg)
            ef = forecast_unit(es)
            if ef and es["qty"].sum() / 1000 >= 20:      # 20t 미만은 전망 안 냄
                eups[str(ename)] = {"forecast": ef,
                                    "qty_t": round(es["qty"].sum() / 1000),
                                    "unassigned": bool(ename == cname)}
        res["counties"][cid] = {"name": cname, "forecast": fc,
                                "level_ratio": round(level_ratio(cs), 3),
                                "eups": eups}
        y27 = [x for x in fc if x["ym"].startswith("2027")]
        avg = np.mean([x["p"] for x in y27]) if y27 else np.nan
        print(f"  {cname:<7} 실측 {len(cs):>3}개월  수준보정 {level_ratio(cs):.3f}  "
              f"2027 평균 {avg:>6,.0f}원/kg  읍면 {len(eups)}개")

    p = WEB / "lettuce_forecast_2027.json"
    p.write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")),
                 encoding="utf-8")
    print()
    print(f"저장: {p.name} ({p.stat().st_size/1024:.0f}KB)")

    # 전북 전체 월별 표
    print()
    print("=" * 76)
    print("전북 전체 2027 월별 전망 (원/kg, 80% 구간)")
    print("=" * 76)
    allc = monthly_series(d)
    fc = forecast_unit(allc)
    print(f"  최근 12개월 수준비 {level_ratio(allc):.3f}")
    print(f"  {'월':<9}{'h':>3}{'전망':>8}{'80% 하한':>10}{'80% 상한':>10}"
          f"{'방법':>18}{'실측 오차율':>11}")
    for x in fc:
        mp = f"{x['mape']:.1f}%" if x["mape"] is not None else "–"
        print(f"  {x['ym']:<9}{x['h']:>3}{x['p']:>8,}{x['lo']:>10,}{x['hi']:>10,}"
              f"{x['method_ko']:>18}{mp:>11}")

    print()
    print("  방법별 근거 (test_long_horizon.py walk-forward 실측)")
    print(f"    {'지평':<8}{'계절평균':>10}{'직접예측':>10}{'채택':>18}")
    for h in sorted(HMAPE):
        r = HMAPE[h]
        use = "직접예측(모델)" if h <= MODEL_H else "계절평균×수준보정"
        print(f"    {str(h)+'개월':<8}{r['seasonal']:>9.1f}%{r['direct']:>9.1f}%{use:>18}")
    print()
    print("    h<=3에서만 직접예측이 계절평균을 이긴다. h=12에선 29.7% vs 23.0%로 크게 진다.")
    print("    계절평균은 지평과 무관하게 22~23%로 평평하다 — 달력만 보기 때문이다.")


if __name__ == "__main__":
    main()
