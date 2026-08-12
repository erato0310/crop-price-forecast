# -*- coding: utf-8 -*-
"""fix_gongpanjang_dupes.py — 산지공판장 원시데이터의 API 중복을 바로잡고 재집계한다.

[문제] 농식품부 산지공판장 API가 특정 날짜에 **모든 행을 정확히 2배로** 돌려준다.
       스크래퍼 버그가 아니라 원천 API 문제다(같은 날짜를 새로 호출해도 재현됨).

[정상 중복과 구분하는 법]
  같은 날 같은 공판장에서 같은 품목·등급·단가·수량 거래가 여러 건 있는 것은 **정상**이다
  (2021~2024년은 중복률 17~24%, 배수 분포에 홀수가 대부분).
  반면 버그가 난 날짜는 **모든 그룹의 배수가 짝수**이고 홀수 배수가 하나도 없다
  (2025-05-15 이후 10개 날짜, 중복률 100%). 우연히 이렇게 될 확률은 사실상 0이므로
  "그 날짜에 홀수 배수 그룹이 하나도 없으면 API가 2배로 부풀린 것"으로 판정하고
  각 그룹의 행 수를 절반으로 줄인다. 무조건 drop_duplicates를 하면 정상 구간의
  진짜 거래까지 지워지므로 절대 그렇게 하면 안 된다.

실행: python fix_gongpanjang_dupes.py
      원본은 *_before_dupfix.csv 로 백업하고, 집계 파일까지 다시 만든다.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from scrape_gongpanjang import AGG_PATH, RAW_PATH, TOP10_CROPS, CROP_NAME_TO_ID, _wavg

BACKUP = RAW_PATH.with_name(RAW_PATH.stem + "_before_dupfix.csv")


def is_api_doubled(group: pd.DataFrame, cols: list[str]) -> bool:
    """그 날짜의 모든 중복 배수가 짝수면 API가 2배로 부풀린 것으로 본다."""
    counts = group.groupby(cols).size()
    return len(group) > 0 and bool((counts % 2 == 1).sum() == 0)


def main() -> None:
    if not RAW_PATH.exists():
        raise SystemExit(f"원시 파일이 없습니다: {RAW_PATH}")
    raw = pd.read_csv(RAW_PATH)
    cols = list(raw.columns)
    before = len(raw)

    if not BACKUP.exists():
        shutil.copy(RAW_PATH, BACKUP)
        print(f"원본 백업: {BACKUP}")

    fixed_parts, bad_days = [], []
    for day, g in raw.groupby("date", sort=False):
        orig = len(g)
        rounds = 0
        # 2026-07-15는 4배로 부풀려져 있었다(한 번 줄여도 여전히 전부 짝수).
        # 그래서 홀수 배수가 나타날 때까지 반복해서 절반으로 줄인다.
        # 그룹이 수백 개인데 전부 짝수일 확률은 사실상 0이므로 정상 데이터를 깎을 위험은 없다.
        while is_api_doubled(g, cols):
            g = g.groupby(cols, sort=False).apply(
                lambda x: x.iloc[: max(1, len(x) // 2)], include_groups=False
            ).reset_index()[cols]
            rounds += 1
        fixed_parts.append(g)
        if rounds:
            bad_days.append((day, orig, len(g), rounds))

    fixed = pd.concat(fixed_parts, ignore_index=True)
    print(f"\nAPI 중복 부풀림으로 판정한 날짜: {len(bad_days)}개")
    for day, b, a, rounds in bad_days:
        print(f"  {str(day)[:10]}  {b:6,} → {a:6,}행  ({2 ** rounds}배 부풀려짐)")
    print(f"\n전체: {before:,} → {len(fixed):,}행 ({before - len(fixed):,}행 제거)")

    fixed.to_csv(RAW_PATH, index=False, encoding="utf-8-sig")
    print(f"저장: {RAW_PATH}")

    # 집계 재생성 (scrape_gongpanjang.main()의 집계부와 동일 로직)
    # 파일에 "2020-02-05 00:00:00"과 "2021-07-05"가 섞여 있어 format 지정이 필요하다
    fixed["date"] = pd.to_datetime(fixed["date"], format="ISO8601")
    fixed["ym"] = fixed["date"].dt.to_period("M")
    top = fixed[fixed["crop"].isin(TOP10_CROPS)]
    rows = []
    for (ym, crop, county), grp in top.groupby(["ym", "crop", "county"]):
        rows.append({
            "ym": ym, "crop": crop, "crop_id": CROP_NAME_TO_ID.get(crop, crop),
            "county": county, "price_avg_kg": _wavg(grp),
            "qty_total_kg": grp["qty_kg"].sum(), "n_obs": len(grp),
        })
    agg = pd.DataFrame(rows)
    agg.to_csv(AGG_PATH, index=False, encoding="utf-8-sig")
    print(f"집계 재생성: {AGG_PATH} ({len(agg)}행)")


if __name__ == "__main__":
    main()
