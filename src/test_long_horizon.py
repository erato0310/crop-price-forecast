# -*- coding: utf-8 -*-
"""test_long_horizon.py — 몇 개월 앞까지 모델이 계절평균을 이기는가.

────────────────────────────────────────────────────────────────
왜 먼저 재는가
────────────────────────────────────────────────────────────────
2027년까지 예측하려면 지금(2026-08)에서 최대 17개월 앞을 봐야 한다. 검증된
지평은 h=1개월뿐이다. 지평을 늘리면 두 가지가 동시에 일어난다.

  - lag1이 실측이 아니라 **예측값**이 된다 (재귀 누적오차)
  - lag12조차 예측 구간으로 들어간다 (13개월 이후)

그래서 어느 지점부터 '모델'이 '계절평균'보다 나쁜지를 먼저 재고, 그 결과에 따라
2027 예측 방법을 정한다. 무작정 재귀로 밀면 rev2가 겪은 것처럼 구간이
2,095~126,146원으로 폭발한다.

────────────────────────────────────────────────────────────────
비교 방법
────────────────────────────────────────────────────────────────
h를 1..18로 바꿔가며 **직접(direct) 예측**으로 walk-forward한다.
직접 예측 = 피처를 전부 t-h 이전 값으로 만들어 h개월 앞을 한 번에 맞힌다.
재귀보다 정직하다 — 예측값을 다시 입력으로 쓰지 않으므로 누적오차가 없다.

  seasonal   학습구간 달력월 평균 (기준선)
  direct     계절항 + t-h 이전 가격시차로 h개월 앞 직접 예측
  drift      계절평균 x 최근 12개월 수준비 (추세 보정)

[실행] python test_long_horizon.py
"""
from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

import lettuce_cv as CV

_ROOT = Path(__file__).resolve().parent.parent
OUT = _ROOT / "outputs"


def build(h: int) -> pd.DataFrame:
    """지평 h용 패널. 모든 피처가 t-h 이전만 참조한다."""
    p = CV.build_panel().copy()
    p["lag_h"] = p["price"].shift(h)
    p["lag_h2"] = p["price"].shift(h + 1)
    p["lag12"] = p["price"].shift(max(12, h))       # h>12면 lag12도 못 쓴다
    p["roll3"] = p["price"].shift(h).rolling(3).mean()
    p["roll12"] = p["price"].shift(h).rolling(12).mean()
    # 수준비: 최근 12개월 평균 / 그 이전 12개월 평균 (추세 대리)
    p["lvl"] = (p["price"].shift(h).rolling(12).mean()
                / p["price"].shift(h + 12).rolling(12).mean())
    # 시차 피처는 앞쪽이 반드시 비는데, CV.tune의 안쪽 fold에서 그 열이 통째로
    # NaN이 되면 Ridge가 죽는다(중앙값 대치도 중앙값 자체가 NaN이라 불가).
    # 시차 회귀의 정석대로 **결측 행을 떨어뜨린다**. h가 클수록 표본이 줄지만
    # 그게 실제 제약이므로 감추지 않는다.
    return p.dropna(subset=COLS).reset_index(drop=True)


COLS = ["month_sin", "month_cos", "lag_h", "lag_h2", "lag12", "roll3", "roll12"]
MIN_FOLD_TRAIN = 24     # 행을 떨어뜨리면 표본이 줄어 CV.MIN_TRAIN보다 낮춰 잡는다


def drift_forecast(train, test) -> np.ndarray:
    """계절평균 x 최근 수준비. 계절 모양은 유지하고 수준만 최근에 맞춘다."""
    base = CV.seasonal_baseline(train, test["ym"])
    r = test["lvl"].fillna(1.0).clip(0.6, 1.6).values
    return base * r


def main() -> None:
    print("=" * 78)
    print("지평별 성적 — 몇 개월 앞까지 모델이 계절평균을 이기는가")
    print("=" * 78)
    print(f"  {'h(개월)':<8}{'계절평균':>10}{'직접예측':>10}{'추세보정':>10}"
          f"{'최선':>10}{'승(직접)':>9}")
    rows = []
    for h in [1, 2, 3, 4, 6, 8, 10, 12, 15, 18]:
        p = build(h)
        errs = {"seasonal": [], "direct": [], "drift": []}
        wins = 0
        nf = 0
        for y in CV.TEST_YEARS:
            tr = p[p["ym"].dt.year < y].dropna(subset=["price"])
            te = p[p["ym"].dt.year == y].dropna(subset=["price"])
            if len(tr) < MIN_FOLD_TRAIN or te.empty:
                continue
            act = te["price"].values
            base = CV.seasonal_baseline(tr, te["ym"])
            # h가 커지면 roll12(=shift(h)+12개월)가 27개월 이력을 요구해
            # 초기 fold에서 통째로 NaN이 된다. 그런 열은 그 fold에서 뺀다 —
            # 중앙값 대치도 불가능(중앙값 자체가 NaN)해서 Ridge가 죽는다.
            a, b = CV.tune(tr, COLS)
            dr = CV.fit_predict(tr, te, COLS, a, b)
            df = drift_forecast(tr, te)
            errs["seasonal"].append(CV.mape(act, base))
            errs["direct"].append(CV.mape(act, dr))
            errs["drift"].append(CV.mape(act, df))
            wins += int(CV.mape(act, dr) < CV.mape(act, base))
            nf += 1
        m = {k: float(np.mean(v)) for k, v in errs.items() if v}
        best = min(m, key=m.get)
        ko = {"seasonal": "계절평균", "direct": "직접예측", "drift": "추세보정"}[best]
        print(f"  {h:<8}{m['seasonal']:>9.2f}%{m['direct']:>9.2f}%{m['drift']:>9.2f}%"
              f"{ko:>10}{wins:>6}/{nf}")
        rows.append({"h": h, **m, "best": best, "wins": f"{wins}/{nf}"})
    d = pd.DataFrame(rows)
    d.to_csv(OUT / "long_horizon.csv", index=False, encoding="utf-8-sig")

    print()
    print("=" * 78)
    print("판정")
    print("=" * 78)
    w = d[d["direct"] < d["seasonal"]]
    if len(w):
        print(f"  직접예측이 계절평균을 이기는 지평: h <= {int(w['h'].max())}개월")
    else:
        print("  직접예측이 계절평균을 이기는 지평 없음")
    b = d[d["drift"] < d["seasonal"]]
    if len(b):
        print(f"  추세보정이 계절평균을 이기는 지평: {sorted(b['h'].tolist())}")
    print()
    print("  2026-08 기준 2027년 각 월까지의 거리:")
    for m_ in (1, 6, 12, 17):
        tgt = pd.Period("2026-08") + m_
        row = d.iloc[(d["h"] - m_).abs().argmin()]
        print(f"    {tgt} (h={m_:>2}) -> 권장 {row['best']}, "
              f"참고 MAPE {row[row['best']]:.1f}%")

    # 잔차 표준편차 — 구간 폭 산정용
    print()
    print("=" * 78)
    print("지평별 로그잔차 표준편차 (예측구간 폭 산정 근거)")
    print("=" * 78)
    print(f"  {'h':<5}{'sigma':>8}{'80% 구간 배율':>14}{'95% 구간 배율':>14}")
    for h in [1, 3, 6, 12, 18]:
        p = build(h)
        res = []
        for y in CV.TEST_YEARS:
            tr = p[p["ym"].dt.year < y].dropna(subset=["price"])
            te = p[p["ym"].dt.year == y].dropna(subset=["price"])
            if len(tr) < MIN_FOLD_TRAIN or te.empty:
                continue
            base = CV.seasonal_baseline(tr, te["ym"])
            r = te["lvl"].fillna(1.0).clip(0.6, 1.6).values
            pred = base * r
            res.extend(np.log(te["price"].values) - np.log(pred))
        s = float(np.std(res))
        print(f"  {h:<5}{s:>8.3f}{np.exp(2*1.2816*s):>13.1f}배{np.exp(2*1.96*s):>13.1f}배")


if __name__ == "__main__":
    main()
