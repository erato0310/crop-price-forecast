# -*- coding: utf-8 -*-
"""predict_2026.py — 2021-09~2025-12 전체를 학습해 2026년 월별 가격을 예측하고,
지금까지 확보된 2026년 실거래(가락시장 스크래핑) 데이터와 비교한다.

[caveat] backtest.py와 마찬가지로 이 비교도 2026년 실측 강수량·환율을 그대로 피처로 쓴다.
즉 "미래 예측력"이 아니라 "지금까지 나온 2026년 실적을 관계식이 얼마나 잘 설명하는가"다.
2026-08 이후는 price_avg_garak_seoul 자체가 아직 없어(scrape_garak.py가 표본일 미도래로
"없음" 처리) 비교 대상에서 자동으로 빠진다 — dropna(subset=[TARGET])로 처리됨.
"""
from __future__ import annotations

from backtest import run_backtest

if __name__ == "__main__":
    run_backtest(train_start_year=2015, train_end_year=2025, test_year=2026)
