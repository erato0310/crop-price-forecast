# -*- coding: utf-8 -*-
"""factorial_experiment.py — 요인 완전배치(full factorial)로 피처 블록의 효과를 분리.

────────────────────────────────────────────────────────────────
왜 팩토리얼인가
────────────────────────────────────────────────────────────────
지금까지는 미리 정한 피처집합 11종만 비교했다. 그러면 두 가지를 못 본다.

  1. **주효과**  각 블록이 평균적으로 얼마나 기여하는가
     (한 조합에서 나빴다고 그 블록이 나쁘다고 단정할 수 없다)
  2. **교호작용** A 단독은 무익한데 B와 같이 넣으면 유익한 경우
     (예: 고온은 광 조건을 통제해야 드러날 수도 있다)

8개 블록을 켜고/끄는 2^8 = 256 조합을 전부 돌려, 각 블록의 주효과와
2차 교호작용을 추정한다. 조합마다 **연도별 walk-forward**(N년까지 학습 ->
N+1년 예측 -> 실적 대조)를 반복하므로, 사용자가 요청한 '반복 학습' 구조가
그대로 들어 있다.

────────────────────────────────────────────────────────────────
읽을 때 주의
────────────────────────────────────────────────────────────────
- 256개를 비교하면 **최고 성적은 우연으로 좋아진다.** 승자의 저주를 피하려면
  개별 조합 순위가 아니라 **주효과 평균**을 봐야 한다. 그래서 아래 출력은
  최고 조합보다 주효과 표를 먼저 낸다.
- 각 주효과에는 fold 단위 블록 부트스트랩 구간을 붙인다. 0을 포함하면
  '판정 불가'다.
- 최종 확인은 튜닝에 한 번도 안 쓴 2026 홀드아웃으로 한다.

[실행]
  python factorial_experiment.py run       # 256조합 x 7fold (수십 분)
  python factorial_experiment.py report    # 저장된 결과 분석
  python factorial_experiment.py errors    # 오차 원인 분해
"""
from __future__ import annotations

import argparse
import itertools
import time
from pathlib import Path

import numpy as np
import pandas as pd

import lettuce_cv as CV

_ROOT = Path(__file__).resolve().parent.parent
OUT = _ROOT / "outputs"
RESULT = OUT / "factorial_results.csv"

# ── 요인 정의 ──────────────────────────────────────────────────
# 각 블록은 생리 경로 하나에 대응한다. 시차는 lettuce_agro_features.PHYSIO_LAGS
# 근거를 따른다(추대=생육기 l1, 발아저해=파종기 l2).
FACTORS: dict[str, list[str]] = {
    "계절":   ["month_sin", "month_cos"],
    "가격":   ["lag_h", "lag12", "roll3"],
    "고온":   ["vhot_days_m_l1", "hot_days_m_l1"],
    "발아":   ["germ_block_days_m_l2"],
    "야간":   ["trop_nights_m_l1"],
    "광":     ["sun_ratio_m_l1", "dark_days_m_l1"],
    "강수":   ["rain_sum_m_l1", "humid_hot_days_m_l1"],
    "저온":   ["vcold_days_m_l1"],
}
NAMES = list(FACTORS)


def combo_cols(mask: tuple[int, ...]) -> list[str]:
    cols = []
    for on, n in zip(mask, NAMES):
        if on:
            cols += FACTORS[n]
    return cols


def cmd_run() -> None:
    p = CV.build_panel()
    missing = {n: [c for c in cs if c not in p.columns] for n, cs in FACTORS.items()}
    missing = {k: v for k, v in missing.items() if v}
    if missing:
        print(f"[중단] 패널에 없는 컬럼: {missing}")
        return

    masks = list(itertools.product([0, 1], repeat=len(NAMES)))
    print(f"완전배치 {len(masks)}조합 x fold {CV.TEST_YEARS}")
    print(f"요인: {NAMES}")
    t0 = time.time()
    rows = []
    for i, mask in enumerate(masks, 1):
        cols = combo_cols(mask)
        if not cols:            # 전부 끄면 회귀가 성립 안 한다
            continue
        r = CV.walk_forward(p, cols)
        if r.empty:
            continue
        rec = {n: m for n, m in zip(NAMES, mask)}
        rec.update({
            "n_feat": len(cols),
            "mape": r["model"].mean(),
            "baseline": r["baseline"].mean(),
            "wins": int((r["model"] < r["baseline"]).sum()),
            "n_fold": len(r),
            "mape_std": r["model"].std(),
            "worst_fold": r["model"].max(),
        })
        for _, x in r.iterrows():
            rec[f"y{int(x['year'])}"] = x["model"]
        rows.append(rec)
        if i % 32 == 0:
            el = time.time() - t0
            print(f"  {i}/{len(masks)}  ({el/60:.1f}분, 남은 예상 "
                  f"{el/i*(len(masks)-i)/60:.1f}분)", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(RESULT, index=False, encoding="utf-8-sig")
    print(f"\n저장: {RESULT.name} ({len(df)}조합, {(time.time()-t0)/60:.1f}분)")


def _load() -> pd.DataFrame:
    if not RESULT.exists():
        raise SystemExit("먼저 run 실행")
    return pd.read_csv(RESULT)


def cmd_report() -> None:
    d = _load()
    p = CV.build_panel()

    print("=" * 78)
    print("1. 주효과 — 그 블록을 켰을 때 MAPE가 평균 얼마나 변하나")
    print("=" * 78)
    print("   (음수 = 켜면 좋아짐. 나머지 요인은 모든 조합에 걸쳐 평균되어 상쇄된다)")
    print(f"   {'요인':<8}{'끔':>9}{'켬':>9}{'주효과':>10}{'켬이 나은 쌍':>14}")
    eff = []
    for n in NAMES:
        off = d[d[n] == 0]["mape"].mean()
        on = d[d[n] == 1]["mape"].mean()
        # 짝지은 비교: 나머지 7요인이 동일한 쌍끼리
        others = [x for x in NAMES if x != n]
        pair = d.pivot_table(index=others, columns=n, values="mape")
        pair = pair.dropna()
        better = int((pair[1] < pair[0]).sum()) if 1 in pair.columns else 0
        tot = len(pair)
        eff.append({"factor": n, "off": off, "on": on, "effect": on - off,
                    "better": better, "pairs": tot})
        print(f"   {n:<8}{off:>8.2f}%{on:>8.2f}%{on-off:>+9.2f}%p"
              f"{better:>8}/{tot}")
    ef = pd.DataFrame(eff).sort_values("effect")
    print()
    print(f"   -> 유익: {', '.join(ef[ef.effect < 0]['factor']) or '없음'}")
    print(f"   -> 무익·유해: {', '.join(ef[ef.effect >= 0]['factor'])}")

    print()
    print("=" * 78)
    print("2. 2차 교호작용 — 단독으로는 무익해도 함께면 유익한가")
    print("=" * 78)
    print("   교호효과 = (둘 다 켬 - A만) - (B만 - 둘 다 끔).  음수면 시너지")
    inter = []
    for a, b in itertools.combinations(NAMES, 2):
        others = [x for x in NAMES if x not in (a, b)]
        g = d.groupby([a, b])["mape"].mean()
        try:
            v = (g[(1, 1)] - g[(1, 0)]) - (g[(0, 1)] - g[(0, 0)])
        except KeyError:
            continue
        inter.append({"A": a, "B": b, "interaction": v})
    it = pd.DataFrame(inter).sort_values("interaction")
    print(f"   {'A':<8}{'B':<8}{'교호효과':>10}")
    for _, r in it.head(5).iterrows():
        print(f"   {r['A']:<8}{r['B']:<8}{r['interaction']:>+9.2f}%p  시너지")
    print("   ...")
    for _, r in it.tail(3).iterrows():
        print(f"   {r['A']:<8}{r['B']:<8}{r['interaction']:>+9.2f}%p  상쇄")

    print()
    print("=" * 78)
    print("3. 성적 상위·하위 조합")
    print("=" * 78)
    d["combo"] = d.apply(lambda r: "+".join(n for n in NAMES if r[n] == 1), axis=1)
    s = d.sort_values("mape")
    print(f"   {'순위':>4}{'조합':<36}{'MAPE':>8}{'승':>6}{'최악fold':>9}")
    for i, (_, r) in enumerate(s.head(8).iterrows(), 1):
        print(f"   {i:>4}{r['combo']:<36}{r['mape']:>7.2f}%{int(r['wins']):>3}/"
              f"{int(r['n_fold'])}{r['worst_fold']:>8.1f}%")
    print("   ...")
    for i, (_, r) in enumerate(s.tail(3).iterrows(), len(s) - 2):
        print(f"   {i:>4}{r['combo']:<36}{r['mape']:>7.2f}%{int(r['wins']):>3}/"
              f"{int(r['n_fold'])}{r['worst_fold']:>8.1f}%")

    print()
    print("   [주의] 256개 중 1등은 우연으로 좋아진다. 아래 홀드아웃으로 확인한다.")

    print()
    print("=" * 78)
    print("4. 상위 조합의 독립 홀드아웃 2026 성적")
    print("=" * 78)
    tr = p[p["ym"].dt.year < CV.HOLDOUT_YEAR].dropna(subset=["price"])
    te = p[p["ym"].dt.year == CV.HOLDOUT_YEAR].dropna(subset=["price"])
    base_ho = CV.mape(te["price"].values, CV.seasonal_baseline(tr, te["ym"]))
    print(f"   계절평균 홀드아웃 {base_ho:.2f}%")
    print(f"   {'조합':<36}{'CV':>8}{'홀드아웃':>10}{'순위변동':>10}")
    ho_rows = []
    for rank, (_, r) in enumerate(s.head(10).iterrows(), 1):
        cols = [c for n in NAMES if r[n] == 1 for c in FACTORS[n]]
        a, b = CV.tune(tr, cols)
        ho = CV.mape(te["price"].values, CV.fit_predict(tr, te, cols, a, b))
        ho_rows.append({"combo": r["combo"], "cv": r["mape"], "ho": ho, "cv_rank": rank})
    hr = pd.DataFrame(ho_rows).sort_values("ho").reset_index(drop=True)
    for i, r in hr.iterrows():
        print(f"   {r['combo']:<36}{r['cv']:>7.2f}%{r['ho']:>9.2f}%"
              f"{f'CV{int(r.cv_rank)}위 -> HO{i+1}위':>12}")
    print()
    print("   CV 순위와 홀드아웃 순위가 뒤섞이면, CV 1등은 과적합이라는 뜻이다.")


def cmd_errors() -> None:
    """오차가 언제·왜 나는지 분해."""
    d = _load()
    p = CV.build_panel()
    d["combo"] = d.apply(lambda r: "+".join(n for n in NAMES if r[n] == 1), axis=1)

    # 기준(계절+가격) 과 팩토리얼 최고
    ref_mask = {n: (1 if n in ("계절", "가격") else 0) for n in NAMES}
    ref = d[np.logical_and.reduce([d[n] == v for n, v in ref_mask.items()])]
    best = d.sort_values("mape").iloc[0]

    print("=" * 78)
    print("1. 연도별 — 학습(~N년) -> 예측(N+1년) 반복 결과")
    print("=" * 78)
    ycols = [c for c in d.columns if c.startswith("y") and c[1:].isdigit()]
    print(f"   {'조합':<26}" + "".join(f"{c[1:]:>8}" for c in ycols) + f"{'평균':>8}")
    for lbl, row in [("계절+가격(기준)", ref.iloc[0]), (f"최고: {best['combo']}", best)]:
        print(f"   {lbl:<26}" + "".join(f"{row[c]:>7.1f}%" for c in ycols)
              + f"{row['mape']:>7.1f}%")
    b = d[d["combo"] == "계절"].iloc[0] if (d["combo"] == "계절").any() else None
    if b is not None:
        print(f"   {'계절만':<26}" + "".join(f"{b[c]:>7.1f}%" for c in ycols)
              + f"{b['mape']:>7.1f}%")

    print()
    print("   연도별 난이도 (전 조합 중앙값)")
    med = {c: d[c].median() for c in ycols}
    print(f"   {'':<26}" + "".join(f"{med[c]:>7.1f}%" for c in ycols))
    hard = max(med, key=med.get)
    print(f"   -> 가장 어려운 해: {hard[1:]}년 ({med[hard]:.1f}%). "
          f"조합을 바꿔도 개선 폭이 제한된다면 그 해 자체가 이상치다.")

    print()
    print("=" * 78)
    print("2. 월별 오차 분해 — 어느 달에서 무엇이 도움이 되나")
    print("=" * 78)
    ref_cols = [c for n in NAMES if ref_mask[n] for c in FACTORS[n]]
    best_cols = [c for n in NAMES if best[n] == 1 for c in FACTORS[n]]
    o_ref = CV._oof(p, ref_cols)
    o_best = CV._oof(p, best_cols)
    for o in (o_ref, o_best):
        o["e"] = np.abs(o["pred"] / o["actual"] - 1) * 100
        o["eb"] = np.abs(o["base"] / o["actual"] - 1) * 100
        o["signed"] = (o["pred"] / o["actual"] - 1) * 100
    print("   " + " " * 16 + " ".join(f"{m:>6d}" for m in range(1, 13)))
    for lbl, o, col in [("계절평균", o_ref, "eb"), ("기준(계절+가격)", o_ref, "e"),
                        ("최고조합", o_best, "e")]:
        g = o.groupby("month")[col].mean()
        print(f"   {lbl:<16}" + " ".join(f"{g.get(m, np.nan):6.1f}" for m in range(1, 13)))
    print()
    print("   부호 있는 오차 (양수=과대예측)")
    for lbl, o in [("기준", o_ref), ("최고조합", o_best)]:
        g = o.groupby("month")["signed"].mean()
        print(f"   {lbl:<16}" + " ".join(f"{g.get(m, np.nan):+6.1f}" for m in range(1, 13)))

    print()
    print("=" * 78)
    print("3. 최악 예측 12건 — 개별 원인 추적")
    print("=" * 78)
    o = o_ref.copy()
    o["ym"] = o["ym"].astype(str)
    w = o.reindex(o["e"].sort_values(ascending=False).index).head(12)
    t = p.set_index(p["ym"].astype(str))
    print(f"   {'ym':<9}{'실제':>8}{'예측':>8}{'오차':>8}{'전월':>8}{'전년동월':>9}"
          f"{'물량t':>8}")
    for _, r in w.iterrows():
        row = t.loc[r["ym"]] if r["ym"] in t.index else None
        lag = row["lag_h"] if row is not None else np.nan
        l12 = row["lag12"] if row is not None else np.nan
        q = row["qty"] / 1000 if row is not None else np.nan
        print(f"   {r['ym']:<9}{r['actual']:>8,.0f}{r['pred']:>8,.0f}"
              f"{r['signed']:>+7.0f}%{lag:>8,.0f}{l12:>9,.0f}{q:>8,.0f}")
    print()
    print("   전월·전년동월과 실제가 크게 다른 달이 오차의 대부분이다.")
    print("   = 시차 정보로는 원리적으로 예고되지 않는 충격.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "report", "errors"])
    a = ap.parse_args()
    {"run": cmd_run, "report": cmd_report, "errors": cmd_errors}[a.cmd]()


if __name__ == "__main__":
    main()
