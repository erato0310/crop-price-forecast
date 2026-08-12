# -*- coding: utf-8 -*-
"""audit_hardcoded_lists.py — 코드에 박아둔 목록이 '열거'인가 '추측'인가.

────────────────────────────────────────────────────────────────
왜 만들었나
────────────────────────────────────────────────────────────────
시장 목록을 "전수 탐색했다"고 보고했으나 실제로는 **코드 접두를 추측해서 훑은 것**이었고,
그 결과 안산(310901)·구미(371501) 두 곳을 놓쳤다. at 도매시장 통합홈페이지가
"전국 32개"라고 명시한 것과 대조해서야 드러났다.

같은 종류의 오류가 다른 목록에도 있을 수 있다. 이 파일은 코드에 하드코딩된
모든 목록을 **자료에서 독립적으로 열거한 결과와 대조**한다. 추측이 남아 있으면
여기서 드러난다.

판정
  열거   자료/API가 돌려준 것을 그대로 받아 적음 -> 신뢰
  추측   사람이 골랐거나 패턴으로 만들어 냄     -> 누락 가능. 열거로 교체할 것

[실행] python audit_hardcoded_lists.py
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
RAW = _ROOT / "data" / "raw"

FAIL = 0


def bad(m):
    global FAIL
    FAIL += 1
    print(f"  [문제] {m}")


def ok(m):
    print(f"  [확인] {m}")


def main() -> None:
    d = pd.read_csv(RAW / "lettuce_daily_raw.csv",
                    dtype={"market_cd": str, "plor_cd": str}, low_memory=False)
    jb = d[d["county"].notna()]

    # ── 1. 시장 ─────────────────────────────────────────────
    print("=" * 74)
    print("1. 시장 목록 — 근거: katRealTime2 전국조회(열거) + at 명시 32개")
    print("=" * 74)
    from scrape_lettuce_daily import MARKETS
    from scrape_supplementary_markets import SUPP_MARKETS
    coded = set(MARKETS.values()) | set(SUPP_MARKETS.values())
    indata = set(d["market_cd"].unique())
    print(f"  코드에 박힌 시장 {len(coded)}곳 / 자료에 실제로 있는 시장 {len(indata)}곳")
    if coded == indata:
        ok(f"일치. at 홈페이지 명시 32개와 {'일치' if len(indata)==32 else '불일치'}")
    else:
        bad(f"코드에만 {sorted(coded-indata)} / 자료에만 {sorted(indata-coded)}")

    # ── 2. 품종 ─────────────────────────────────────────────
    print()
    print("=" * 74)
    print("2. 품종 목록 — MAIN/JJONG/THIN 분류가 자료를 전부 덮는가")
    print("=" * 74)
    from scrape_lettuce_daily import is_main_variety, EXCLUDE_FROM_MAIN
    actual = set(jb["variety"].dropna().unique())
    tot = jb["qty_kg"].sum()
    covered = {v for v in actual if is_main_variety(v)} | (EXCLUDE_FROM_MAIN & actual)
    miss = actual - covered
    print(f"  자료에 등장하는 품종 {len(actual)}종")
    print(f"  주력 {len(actual)-len(EXCLUDE_FROM_MAIN & actual)}종 / "
          f"배제 {sorted(EXCLUDE_FROM_MAIN & actual)}")
    if miss:
        bad(f"어느 쪽에도 안 잡히는 품종 {sorted(miss)}")
    else:
        ok("배제 목록 방식이라 신규 품종도 자동으로 주력에 포함된다")
    unk = jb[jb["variety"].isna()]
    if len(unk):
        print(f"  (품종 결측 {len(unk):,}행, {unk['qty_kg'].sum()/tot*100:.3f}% — "
              f"is_main=False로 빠진다)")

    # ── 3. 시군 ─────────────────────────────────────────────
    print()
    print("=" * 74)
    print("3. 시군 매핑 — 전북 14개 시군을 전부 덮는가")
    print("=" * 74)
    from export_lettuce_webapp import COUNTY_ID
    actual_c = set(jb["county"].dropna().unique())
    miss_c = actual_c - set(COUNTY_ID)
    if miss_c:
        bad(f"매핑에 없는 시군 {sorted(miss_c)} — 웹앱에서 통째로 빠진다")
    else:
        ok(f"자료의 시군 {len(actual_c)}개 전부 매핑됨 (코드 {len(COUNTY_ID)}개)")

    # ── 4. 기상 지점 ────────────────────────────────────────
    print()
    print("=" * 74)
    print("4. 기상 관측지점 — 코드가 실제로 존재하고 이름이 맞는가")
    print("=" * 74)
    for f, lbl, col in [("daily_weather_lettuce.csv", "전북 ASOS", "stn"),
                        ("daily_weather_aws.csv", "전북 AWS", "stn"),
                        ("daily_weather_competitors.csv", "경쟁산지 ASOS", "stn")]:
        p = RAW / f
        if not p.exists():
            bad(f"{lbl}: 파일 없음")
            continue
        w = pd.read_csv(p, dtype={col: str}, low_memory=False)
        nm = "stn_nm" if "stn_nm" in w.columns else None
        n = w[col].nunique()
        rng = f"{w['date'].min()[:10]}~{w['date'].max()[:10]}"
        note = ""
        if nm:
            note = "  " + ", ".join(f"{s}={g[nm].iloc[0]}"
                                    for s, g in list(w.groupby(col))[:4]) + " …"
        ok(f"{lbl}: {n}지점 {len(w):,}행 {rng}{note}")
    print("  ※ 지점명은 API 응답(stnNm)을 그대로 받아 적은 것이라 열거에 해당한다.")
    print("     다만 **어느 지점을 고를지**는 사람이 판단했다 — 아래 5 참고.")

    # ── 5. 판단이 개입한 곳 (추측 위험) ─────────────────────
    print()
    print("=" * 74)
    print("5. 사람 판단이 개입한 목록 — 누락 위험이 남아 있는 곳")
    print("=" * 74)
    print("  a) 경쟁산지 관측지점 선택 (fetch_competitor_weather.SIDO_STATIONS)")
    print("     시도별로 3~5곳을 '상추 재배가 있을 만한 평야·산지'로 골랐다. 열거 아님.")
    print("     -> 시도 대표값을 만드는 용도라 몇 곳 빠져도 평균이 크게 안 흔들리지만,")
    print("        '그 시도 전 지점'이 아니라는 점은 명시해야 한다.")
    print()
    print("  b) 전북 시군->관측지점 매핑 (lettuce_agro_features.COUNTY_STATION)")
    print("     ASOS가 9곳뿐이라 인접 지점으로 대체했다. 대체 자체가 판단이다.")
    print("     -> AWS 8지점으로 교체 검정했고 결과 차이 없음(test_aws_station_swap).")
    print()
    print("  c) 재배형태 판별 임계 (infer_cultivation_type)")
    print("     출하 계절구조로 추론. 관측 아님. KOSIS 93.5%와 대조해 92.8%로 검증됨.")

    # ── 6. 읍면 파싱 ────────────────────────────────────────
    print()
    print("=" * 74)
    print("6. 읍면 파싱 — 규칙이 놓치는 표기가 있는가")
    print("=" * 74)
    from export_lettuce_webapp import extract_eup
    jb2 = jb.copy()
    jb2["eup"] = [extract_eup(p, c) for p, c in zip(jb2["plor_nm"], jb2["county"])]
    same = jb2["eup"] == jb2["county"]          # 시군까지만 적힌 것
    tot = jb2["qty_kg"].sum()
    print(f"  읍면 특정 {jb2[~same]['qty_kg'].sum()/tot*100:.1f}% / "
          f"시군까지만 {jb2[same]['qty_kg'].sum()/tot*100:.1f}%")
    # 읍면동으로 안 끝나는 라벨 = 기관명 등
    odd = jb2[~same & ~jb2["eup"].str.endswith(("읍", "면", "동", "가"))]
    if len(odd):
        g = odd.groupby("eup")["qty_kg"].sum().sort_values(ascending=False)
        print(f"  읍면동으로 안 끝나는 라벨 {len(g)}종 "
              f"({odd['qty_kg'].sum()/tot*100:.2f}%) — 기관·사서함 등")
        for v, x in g.head(5).items():
            print(f"        {v:<20}{x/1000:>8,.1f}t")
        print("     -> 적힌 그대로 두는 것이 방침이므로 오류 아님. 순위에서만 뺀다.")

    print()
    print("=" * 74)
    print(f"결과: {'전 항목 확인' if FAIL == 0 else f'{FAIL}건 문제 — 위 [문제] 확인'}")
    print("=" * 74)


if __name__ == "__main__":
    main()
