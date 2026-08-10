# -*- coding: utf-8 -*-
"""features.py — 월별 패널(monthly_panel.csv)에 예측용 파생 피처를 추가."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _ensure_period(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if not isinstance(df["ym"].dtype, pd.PeriodDtype):
        df["ym"] = pd.PeriodIndex(pd.to_datetime(df["ym"].astype(str)), freq="M")
    return df


def add_seasonal_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    month = df["ym"].dt.month
    df["month"] = month
    df["month_sin"] = np.sin(2 * np.pi * month / 12)
    df["month_cos"] = np.cos(2 * np.pi * month / 12)
    return df


def add_price_lags(df: pd.DataFrame, col: str = "price_avg_jeonbuk") -> pd.DataFrame:
    df = df.copy()
    df[f"{col}_lag1"] = df[col].shift(1)
    df[f"{col}_lag12"] = df[col].shift(12)
    df[f"{col}_roll3"] = df[col].shift(1).rolling(3).mean()
    df[f"{col}_roll6"] = df[col].shift(1).rolling(6).mean()
    # roll12: "지금이 최근 몇 년 대비 대체로 비싼/싼 시기인가"를 알려주는 완만한 레벨 신호.
    # roll3/roll6보다 표본이 적은 초반(학습 40개월 중 앞쪽)에는 NaN이 많아지는 트레이드오프 있음.
    df[f"{col}_roll12"] = df[col].shift(1).rolling(12).mean()
    # 전년동월 대비 모멘텀: 최근 1개월이 작년 동월보다 얼마나 높/낮은지 (2025년 1~3월처럼
    # "예년보다 구조적으로 낮은 국면"에 들어섰는지를 계절평균만으로는 못 잡아내서 추가.
    lag1, lag12 = df[f"{col}_lag1"], df[f"{col}_lag12"]
    df[f"{col}_mom_yoy"] = (lag1 / lag12) - 1
    df[f"{col}_mom_yoy"] = df[f"{col}_mom_yoy"].replace([np.inf, -np.inf], np.nan)
    return df


def add_trend_feature(df: pd.DataFrame) -> pd.DataFrame:
    """월 순번 선형 추세 — 계절평균만으로는 못 잡는 다년간 구조적 하락/상승을 GBM이 배우게 함
    (예: 2022~2025년 7월 낙찰가가 43,716 -> 34,155 -> 28,564 -> 20,553원으로 매년 꾸준히 하락)."""
    df = df.copy()
    df["time_idx"] = np.arange(len(df))
    return df


def add_climate_lags(df: pd.DataFrame, cols=("tavg", "rain_sum", "sun_sum"), lags=(1, 2)) -> pd.DataFrame:
    df = df.copy()
    for c in cols:
        if c not in df.columns:
            continue
        for lag in lags:
            df[f"{c}_lag{lag}"] = df[c].shift(lag)
    return df


def add_supply_features(df: pd.DataFrame) -> pd.DataFrame:
    """전년 동월 대비 재배면적 증감률 (같은 달끼리 12개월 시차 비교)."""
    df = df.copy()
    if "area_ha" in df.columns:
        df["area_yoy_pct"] = df["area_ha"].pct_change(periods=12)
    return df


def add_macro_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in ("fx_usd", "csi"):
        if c in df.columns:
            df[f"{c}_pct_chg"] = df[c].pct_change()
    return df


def add_liquidity_feature(df: pd.DataFrame) -> pd.DataFrame:
    """거래물량(log) — 표본이 얇은 달(공판장 거래량 적음)은 평균가가 소수 거래에 좌우돼
    더 튀는 경향이 있어, "이 달 가격이 얼마나 두꺼운 거래 위에서 나온 값인가"를 알려주는
    신호로 CV상 도움이 됐다(price_avg_jeonbuk 타깃, models.py docstring 참고)."""
    df = df.copy()
    if "qty_total_jeonbuk" in df.columns:
        df["qty_log"] = np.log1p(df["qty_total_jeonbuk"])
    return df


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    df = _ensure_period(df).sort_values("ym").reset_index(drop=True)
    df = add_seasonal_features(df)
    df = add_trend_feature(df)
    df = add_price_lags(df)
    df = add_climate_lags(df)
    df = add_supply_features(df)
    df = add_macro_features(df)
    df = add_liquidity_feature(df)
    return df
