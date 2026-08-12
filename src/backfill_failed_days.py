# -*- coding: utf-8 -*-
"""backfill_failed_days.py — 재시도 5회로도 못 받은 (시장, 날짜)만 다시 받아 구멍을 메운다.

scrape_jeonbuk_all_crops.py는 실패한 요청을 조용히 삼키지 않고
`outputs/scrape_failures.csv`에 기록한다(2026-08-07에 고친 부분). 하지만 기록만 하고
끝이라 그 (시장,날짜)는 여전히 데이터에 구멍으로 남는다 — 2026-08-11 재스크래핑에서도
2021-09-15에 6개 시장, 2024-06-05에 3개 요청이 ConnectTimeout으로 빠졌다.

중복 방지가 이 스크립트의 핵심이다: **해당 (시장,날짜)의 기존 행을 전부 지우고
새로 받은 것으로 갈아끼운다.** 그냥 append하면 페이지 1은 성공하고 2만 실패한
경우에 1페이지가 두 번 들어간다. 같은 이유로 행 단위 drop_duplicates는 쓰지 않는다
(같은 날 같은 조건의 실제 거래가 여러 건인 것은 katSale에서 정상 — HANDOFF 참고).

사용:
    ..\\.venv\\Scripts\\python.exe backfill_failed_days.py
전체 재스크래핑이 끝난 뒤에 돌릴 것(원시 파일이 최종본이어야 함).
"""
from __future__ import annotations

import datetime as dt
import time
from pathlib import Path

import pandas as pd

from scrape_jeonbuk_all_crops import (
    CROP_NAME_TO_ID, OUT_DIR, aggregate_raw, fetch_day_market_all, FETCH_FAILURES,
)

ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = OUT_DIR / "jeonbuk_origin_allcrops_raw.csv"
# 스크래퍼가 OUT_DIR(=data/raw)에 쓴다 - outputs/가 아니다
FAILURES_PATH = OUT_DIR / "scrape_failures.csv"


def main() -> None:
    if not FAILURES_PATH.exists():
        print(f"실패 기록 없음({FAILURES_PATH.name}) - 메울 구멍이 없습니다.")
        return
    fails = pd.read_csv(FAILURES_PATH)
    fails["date"] = pd.to_datetime(fails["date"], format="mixed").dt.date
    # (시장,날짜) 단위로 묶는다 - 페이지 단위 실패도 그 조합을 통째로 다시 받는다
    targets = sorted(set(zip(fails["market_cd"].astype(str), fails["date"])))
    print(f"다시 받을 (시장,날짜) 조합: {len(targets)}개")

    raw = pd.read_csv(RAW_PATH)
    raw["date"] = pd.to_datetime(raw["date"], format="mixed").dt.date
    raw["market_cd"] = raw["market_cd"].astype(str)
    before = len(raw)

    new_rows: list[dict] = []
    ok, still_failing = 0, []
    for mkt, day in targets:
        n_before = len(FETCH_FAILURES)
        recs = fetch_day_market_all(mkt, day if isinstance(day, dt.date) else pd.Timestamp(day).date())
        if len(FETCH_FAILURES) > n_before:
            still_failing.append((mkt, day))
            print(f"  ! 여전히 실패: {mkt} {day} - 이번엔 갈아끼우지 않고 기존 행을 남깁니다")
            continue
        new_rows.extend(recs)
        ok += 1
        print(f"  OK {mkt} {day} -> {len(recs)}건", flush=True)
        time.sleep(0.35)

    replaced = {(m, d) for m, d in targets if (m, d) not in set(still_failing)}
    if not replaced:
        print("새로 받은 조합이 없어 원시 파일을 건드리지 않습니다.")
        return

    mask = raw.apply(lambda r: (r["market_cd"], r["date"]) in replaced, axis=1)
    print(f"기존 행 제거: {int(mask.sum())}건 (해당 시장x날짜)")
    merged = pd.concat([raw[~mask], pd.DataFrame(new_rows)], ignore_index=True)
    merged = merged.sort_values(["date", "market_cd"]).reset_index(drop=True)
    merged.to_csv(RAW_PATH, index=False, encoding="utf-8-sig")
    print(f"원시 파일 갱신: {before} -> {len(merged)}행 ({ok}/{len(targets)} 조합 복구)")

    # 집계 파일도 같은 규칙으로 재생성 (스크래퍼 main()과 동일 함수를 씀)
    agg = aggregate_raw(merged)
    agg_path = OUT_DIR / "jeonbuk_origin_top10crops_by_county.csv"
    agg.to_csv(agg_path, index=False, encoding="utf-8-sig")
    print(f"집계 재생성: {agg_path.name} ({len(agg)}행)")

    lettuce = agg[agg["crop"] == "상추"]
    if not lettuce.empty:
        out_lettuce = OUT_DIR / "jeonbuk_origin_lettuce_by_county.csv"
        lettuce.drop(columns=["crop", "crop_id"]).to_csv(
            out_lettuce, index=False, encoding="utf-8-sig")
        print(f"상추 전용 재생성: {out_lettuce.name} ({len(lettuce)}행)")

    if still_failing:
        print(f"\n[경고] 여전히 실패한 조합 {len(still_failing)}개 - 나중에 다시 시도할 것")
    else:
        FAILURES_PATH.unlink()
        print("\n모든 구멍을 메웠습니다 - scrape_failures.csv 제거")


if __name__ == "__main__":
    main()
