# -*- coding: utf-8 -*-
"""analyze_crop_cycle_signal.py — 품종 구성에서 '작기 단계'를 읽어낸다.

────────────────────────────────────────────────────────────────
착안 (현장 지식)
────────────────────────────────────────────────────────────────
쫑상추는 별개 품종이 아니라 **한 작기가 끝날 무렵 순을 꺾어 내는 것**이다.
즉 쫑상추가 시장에 나온다 = 그 산지의 작기가 마무리됐다 = 곧 그 산지 공급이 끊긴다.

그렇다면 쫑상추 출하 비중은 **다음 달 공급 감소의 선행지표**가 될 수 있다.
같은 논리로 다른 부산물도 단계 신호일 수 있다.

    상추솎음  정식 후 솎아내기      -> 작기 **초반**
    상추순    순 채취              -> 작기 후반(쫑상추와 유사)
    쫑상추    작기 마무리 순 꺾기   -> 작기 **종료**
    포기찹/청상추/적상추            -> 정상 수확기 (주력, 91.9%)

이게 맞다면 두 가지 함의가 있다.
 1. **쫑상추를 가격 평균에 섞으면 안 된다.** 1,564원/kg짜리가 주력(3,100~3,800원)
    평균을 끌어내려, 가격 하락처럼 보이지만 실제로는 상품 구성이 바뀐 것이다.
 2. **쫑상추 비중은 피처로 써야 한다.** 버리지 말고 분리한다.

이 파일은 그 가설을 실제로 검정한다.

[검정 방법]
  A. 부산물 품종의 계절 프로파일 — 작기 구조와 맞는가
  B. 쫑상추 비중(t) -> 다음 달 총물량 변화(t+1) 상관. 음수여야 가설 지지
  C. 쫑상추 비중(t) -> 다음 달 가격 변화(t+1) 상관. 양수여야 가설 지지
  D. 시군별 재현성

[주의] 표본 38개월. 계절조정 후 유효표본은 30 안팎이다. 탐색적 결과다.

[실행] python analyze_crop_cycle_signal.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
SRC = _ROOT / "data" / "raw" / "lettuce_daily_raw.csv"
OUT = _ROOT / "outputs"
OUT.mkdir(exist_ok=True)

MAIN = ["포기찹", "청상추", "적상추", "적포기", "청포기", "꽃적상추", "흑적",
        "상추(일반)", "토말린"]          # 정상 수확물
END_CYCLE = ["쫑상추", "상추순"]          # 작기 종료 신호
EARLY_CYCLE = ["상추솎음"]                # 작기 초반 신호


def wa(g: pd.DataFrame, p="price_kg", q="qty_kg") -> float:
    x = g[[p, q]].dropna()
    t = x[q].sum()
    return (x[p] * x[q]).sum() / t if t else np.nan


def corr(x: pd.Series, y: pd.Series) -> tuple[float, int]:
    m = x.notna() & y.notna()
    n = int(m.sum())
    if n < 8 or x[m].std() == 0 or y[m].std() == 0:
        return np.nan, n
    return float(np.corrcoef(x[m], y[m])[0, 1]), n


def main() -> None:
    d = pd.read_csv(SRC, dtype={"market_cd": str}, low_memory=False)
    d["date"] = pd.to_datetime(d["date"])
    d["ym"] = d["date"].dt.to_period("M")
    d["month"] = d["date"].dt.month
    jb = d[d["county"].notna()].copy()

    def stage(v):
        if v in END_CYCLE:
            return "종료(쫑상추·상추순)"
        if v in EARLY_CYCLE:
            return "초반(솎음)"
        if v in MAIN:
            return "수확기(주력)"
        return "기타"

    jb["stage"] = jb["variety"].map(stage)

    print("=" * 78)
    print("A. 작기 단계별 계절 프로파일 (전북산 물량 비중 %)")
    print("=" * 78)
    piv = jb.pivot_table(index="month", columns="stage", values="qty_kg", aggfunc="sum")
    sh = piv.div(piv.sum(axis=1), axis=0) * 100
    cols = [c for c in ["수확기(주력)", "종료(쫑상추·상추순)", "초반(솎음)", "기타"]
            if c in sh.columns]
    print("  월 | " + " ".join(f"{c[:9]:>11s}" for c in cols) + "   총물량t")
    for m in range(1, 13):
        if m not in sh.index:
            continue
        print(f"  {m:2d} | " + " ".join(f"{sh.loc[m, c]:10.2f}%" for c in cols)
              + f"  {piv.loc[m].sum()/1000:>8,.0f}")

    # 쫑상추 단독
    print()
    print("  쫑상추만 (물량 비중 % / 절대 톤)")
    jj = jb[jb["variety"] == "쫑상추"]
    tt = jb.groupby("month")["qty_kg"].sum()
    js = jj.groupby("month")["qty_kg"].sum()
    print("     " + " ".join(f"{m:>7d}" for m in range(1, 13)))
    print("   % " + " ".join(f"{js.get(m,0)/tt[m]*100:6.2f}%" for m in range(1, 13)))
    print("   t " + " ".join(f"{js.get(m,0)/1000:7.0f}" for m in range(1, 13)))

    # ── 월 패널 ─────────────────────────────────────────────
    rows = []
    for (ym, c), g in jb.groupby(["ym", "county"]):
        tot = g["qty_kg"].sum()
        if tot <= 0:
            continue
        main_g = g[g["variety"].isin(MAIN)]
        rows.append({
            "ym": ym, "county": c, "month": ym.month,
            "qty_all": tot,
            "qty_main": main_g["qty_kg"].sum(),
            "price_main": wa(main_g),          # 주력 품종만의 가격 (제안 타깃)
            "price_all": wa(g),                # 전 품종 혼합 (현행)
            "jjong_share": g[g["variety"].isin(END_CYCLE)]["qty_kg"].sum() / tot * 100,
            "sokum_share": g[g["variety"].isin(EARLY_CYCLE)]["qty_kg"].sum() / tot * 100,
        })
    p = pd.DataFrame(rows).sort_values(["county", "ym"]).reset_index(drop=True)

    # 다음 달 변화율. 물량이 0인 달이 있어 비율을 그대로 쓰면 inf가 생기고
    # 상관이 통째로 nan이 된다 -> 로그차분으로 바꾸고 0은 결측 처리한다.
    g = p.groupby("county")
    qm = p["qty_main"].where(p["qty_main"] > 0)
    pm = p["price_main"].where(p["price_main"] > 0)
    p["qty_next_chg"] = np.log(g["qty_main"].shift(-1).where(lambda x: x > 0)) - np.log(qm)
    p["price_next_chg"] = np.log(g["price_main"].shift(-1).where(lambda x: x > 0)) - np.log(pm)
    p[["qty_next_chg", "price_next_chg"]] = p[
        ["qty_next_chg", "price_next_chg"]].replace([np.inf, -np.inf], np.nan)
    # 계절조정 (시군x달력월 평균 제거)
    for col in ("jjong_share", "sokum_share", "qty_next_chg", "price_next_chg"):
        p[col + "_adj"] = p[col] - p.groupby(["county", "month"])[col].transform("mean")
    p.to_csv(OUT / "crop_cycle_panel.csv", index=False, encoding="utf-8-sig")

    print()
    print("=" * 78)
    print("B/C. 쫑상추 비중 -> 다음 달 (전 시군 패널)")
    print("=" * 78)
    print("   가설: 쫑상추가 늘면 작기가 끝나가는 것 -> 다음 달 물량 감소(-), 가격 상승(+)")
    for lbl, col in [("다음달 주력물량 변화", "qty_next_chg"),
                     ("다음달 주력가격 변화", "price_next_chg")]:
        r_raw, n1 = corr(p["jjong_share"], p[col])
        r_adj, n2 = corr(p["jjong_share_adj"], p[col + "_adj"])
        print(f"   쫑상추비중 vs {lbl:<14} raw {r_raw:+.3f}  계절조정 {r_adj:+.3f}  (n={n2})")
    for lbl, col in [("다음달 주력물량 변화", "qty_next_chg")]:
        r_adj, n2 = corr(p["sokum_share_adj"], p[col + "_adj"])
        print(f"   솎음비중   vs {lbl:<14} {'':>10}계절조정 {r_adj:+.3f}  (n={n2})"
              f"   <- 작기 초반이면 양수 기대")

    # ── D. 시군별 ───────────────────────────────────────────
    print()
    print("=" * 78)
    print("D. 시군별 재현성 (계절조정 상관)")
    print("=" * 78)
    print(f"   {'시군':<8}{'n':>4}{'쫑상추연중%':>12}{'->물량(t+1)':>13}{'->가격(t+1)':>13}")
    tot_q = p.groupby("county")["qty_all"].sum().sort_values(ascending=False)
    for c in tot_q.index:
        g2 = p[p["county"] == c]
        if len(g2) < 15 or g2["jjong_share"].sum() == 0:
            continue
        rq, n = corr(g2["jjong_share_adj"], g2["qty_next_chg_adj"])
        rp, _ = corr(g2["jjong_share_adj"], g2["price_next_chg_adj"])
        sh_c = g2["jjong_share"].mean()
        print(f"   {c:<8}{n:>4}{sh_c:>11.2f}%"
              f"{'-' if np.isnan(rq) else f'{rq:+.2f}':>13}"
              f"{'-' if np.isnan(rp) else f'{rp:+.2f}':>13}")

    # ── E. 타깃 비교 ────────────────────────────────────────
    print()
    print("=" * 78)
    print("E. 타깃 후보 비교 — 주력만 vs 전 품종 혼합")
    print("=" * 78)
    m = p.groupby("month")[["price_main", "price_all"]].mean()
    m["차이%"] = (m["price_main"] / m["price_all"] - 1) * 100
    print(f"   {'월':>3}{'주력만':>10}{'전품종':>10}{'차이':>8}")
    for mm in range(1, 13):
        if mm not in m.index:
            continue
        r = m.loc[mm]
        print(f"   {mm:>3}{r['price_main']:>10,.0f}{r['price_all']:>10,.0f}"
              f"{r['차이%']:>+7.1f}%")
    print()
    print(f"   연중 진폭:  주력만 {m['price_main'].max()/m['price_main'].min():.2f}배"
          f"   전품종 {m['price_all'].max()/m['price_all'].min():.2f}배")
    # ── F. 일 단위 검정 ─────────────────────────────────────
    print()
    print("=" * 78)
    print("F. 일 단위 — 쫑상추 출하 이후 그 산지 물량이 실제로 끊기는가")
    print("=" * 78)
    print("   월 집계는 여러 농가의 어긋난 작기가 섞여 신호가 뭉개진다.")
    print("   같은 (시군, 주) 단위로 좁혀서 다시 본다.")
    jb["week"] = jb["date"].dt.to_period("W")
    wk = []
    for (w, c), g in jb.groupby(["week", "county"]):
        t = g["qty_kg"].sum()
        if t <= 0:
            continue
        wk.append({"week": w, "county": c,
                   "qty_main": g[g["variety"].isin(MAIN)]["qty_kg"].sum(),
                   "jjong": g[g["variety"].isin(END_CYCLE)]["qty_kg"].sum(),
                   "jjong_share": g[g["variety"].isin(END_CYCLE)]["qty_kg"].sum() / t * 100})
    w = pd.DataFrame(wk).sort_values(["county", "week"]).reset_index(drop=True)
    gw = w.groupby("county")
    print(f"   {'선행주수':>8}{'물량 로그변화 상관':>20}{'n':>7}")
    for k in (1, 2, 3, 4, 6):
        fut = gw["qty_main"].shift(-k).where(lambda x: x > 0)
        cur = w["qty_main"].where(w["qty_main"] > 0)
        chg = (np.log(fut) - np.log(cur)).replace([np.inf, -np.inf], np.nan)
        # 시군별 평균 제거(고정효과)
        tmp = pd.DataFrame({"c": w["county"], "x": w["jjong_share"], "y": chg})
        tmp["x"] = tmp["x"] - tmp.groupby("c")["x"].transform("mean")
        tmp["y"] = tmp["y"] - tmp.groupby("c")["y"].transform("mean")
        r, n = corr(tmp["x"], tmp["y"])
        print(f"   +{k}주{'':>4}{r:>+19.3f}{n:>7}")
    print("   (가설이 맞으면 음수여야 한다 — 쫑상추가 나온 뒤 물량이 줄어야 함)")

    # ── G. 가격 가설 ────────────────────────────────────────
    print()
    print("=" * 78)
    print("G. 가격 가설 — 주력이 귀하면 쫑상추 가격이 오르는가")
    print("=" * 78)
    pr = []
    for (ym, c), g in jb.groupby(["ym", "county"]):
        mg = g[g["variety"].isin(MAIN)]
        jg = g[g["variety"].isin(END_CYCLE)]
        if mg["qty_kg"].sum() <= 0 or jg["qty_kg"].sum() <= 0:
            continue
        pr.append({"ym": ym, "county": c, "month": ym.month,
                   "p_main": wa(mg), "q_main": mg["qty_kg"].sum(),
                   "p_jj": wa(jg), "q_jj": jg["qty_kg"].sum()})
    q = pd.DataFrame(pr).sort_values(["county", "ym"]).reset_index(drop=True)
    q["rel"] = q["p_jj"] / q["p_main"]
    for c in ("p_main", "p_jj", "q_main", "rel"):
        q[c + "_a"] = q[c] - q.groupby(["county", "month"])[c].transform("mean")
    tests = [
        ("주력가격 vs 쫑상추가격 (동월)", "p_main_a", "p_jj_a", "동조 확인용"),
        ("주력물량 vs 쫑상추가격", "q_main_a", "p_jj_a", "음수면 가설 지지"),
        ("주력물량 vs 상대가(쫑/주력)", "q_main_a", "rel_a", "음수면 대체수요"),
    ]
    for lbl, x, y, note in tests:
        r, n = corr(q[x], q[y])
        print(f"  {lbl:<28}{r:>+7.3f}  (n={n})  {note}")

    print()
    print("  선행성 — 쫑상추 지표(t)가 주력 가격(t+k)을 예고하는가")
    for k in (1, 2, 3):
        q[f"pm_f{k}"] = q.groupby("county")["p_main"].shift(-k)
        q[f"pm_f{k}_a"] = q[f"pm_f{k}"] - q.groupby(["county", "month"])[
            f"pm_f{k}"].transform("mean")
        r1, n1 = corr(q["p_jj_a"], q[f"pm_f{k}_a"])
        r2, _ = corr(q["rel_a"], q[f"pm_f{k}_a"])
        print(f"    t+{k}:  쫑상추가격 {r1:+.3f}   상대가 {r2:+.3f}   (n={n1})")
    r0, _ = corr(q["p_jj_a"], q["p_main_a"])
    print(f"    동월:  쫑상추가격 {r0:+.3f}          <- 이보다 커야 선행지표다")

    # ── H. 읍면 해상도 ──────────────────────────────────────
    print()
    print("=" * 78)
    print("H. 읍면 해상도 — 집계 수준을 낮추면 신호가 살아나는가")
    print("=" * 78)
    print("   월/시군 집계는 작기가 어긋난 농가 수백 곳이 섞여 상쇄될 수 있다.")
    print("   산지 표기의 65%가 읍면까지 특정되므로 그 단위로 다시 본다.")
    import re
    EUP = re.compile(r"(?:시|군)\s+([가-힣]+(?:읍|면|동))(?:\s|$)")
    jb2 = jb.copy()
    jb2["eup"] = jb2["plor_nm"].str.extract(EUP)
    e = jb2[jb2["eup"].notna()].copy()
    e["key"] = e["county"] + "·" + e["eup"]
    er = []
    for (ym, k), g in e.groupby(["ym", "key"]):
        tot = g["qty_kg"].sum()
        mg = g[g["variety"].isin(MAIN)]
        if tot <= 0 or mg["qty_kg"].sum() <= 0:
            continue
        er.append({"ym": ym, "key": k, "month": ym.month,
                   "q_main": mg["qty_kg"].sum(),
                   "jj_share": g[g["variety"].isin(END_CYCLE)]["qty_kg"].sum() / tot * 100})
    ep = pd.DataFrame(er).sort_values(["key", "ym"]).reset_index(drop=True)
    # 관측이 두터운 읍면만 (얇으면 비중이 튄다)
    keep = ep.groupby("key")["q_main"].count()
    ep = ep[ep["key"].isin(keep[keep >= 60].index)]
    ep["q_next"] = np.log(ep.groupby("key")["q_main"].shift(-1).where(lambda x: x > 0)) \
        - np.log(ep["q_main"].where(lambda x: x > 0))
    ep["q_next"] = ep["q_next"].replace([np.inf, -np.inf], np.nan)
    for c in ("jj_share", "q_next"):
        ep[c + "_a"] = ep[c] - ep.groupby(["key", "month"])[c].transform("mean")
    r, n = corr(ep["jj_share_a"], ep["q_next_a"])
    print(f"   읍면 {ep['key'].nunique()}곳 (관측 60개월 이상)")
    print(f"   쫑상추비중 -> 다음달 주력물량 로그변화  {r:+.3f}  (n={n})")
    print("   시군 단위 결과와 비교해 절댓값이 커졌으면 집계가 원인이었던 것")
    print()
    print(f"   {'읍면':<14}{'n':>5}{'쫑상추%':>9}{'->물량(t+1)':>13}")
    for k, g in ep.groupby("key"):
        rr, nn = corr(g["jj_share_a"], g["q_next_a"])
        if nn < 40:
            continue
        print(f"   {k:<14}{nn:>5}{g['jj_share'].mean():>8.2f}%"
              f"{'-' if np.isnan(rr) else f'{rr:+.2f}':>13}")

    print()
    print("저장: outputs/crop_cycle_panel.csv")


if __name__ == "__main__":
    main()
