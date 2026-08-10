# -*- coding: utf-8 -*-
"""backtest.py — 학습 → 2025년 월별 가격 예측 → 실제 2025와 비교.

타깃은 `models.TARGET`(=price_avg_garak_seoul, 가락시장/서울 경락가격 2021-09~현재)이다.
KAMIS API 전국평균(price_avg)은 최근 15개월치뿐이라 학습 데이터로 못 써서 이쪽으로 전환했다
(docs/RESOLVE_GUIDE.md, README 참고). TRAIN_START_YEAR=2015로 넓게 잡아도 dropna가
데이터 없는 2021-08 이전을 자동으로 걸러내므로 실제 학습 구간은 2021-09~2024-12(40개월)다.

[caveat] 이 백테스트에 쓰는 2025년 기후·거시(환율/소비자심리) 값은 사후 확정된 실측치다.
따라서 이 결과는 "미래 예측력"이 아니라 "가격-설명변수 관계식의 설명력" 검증에 가깝다.
실제 차년도(예: 2027) 예측 단계에서는 기후·거시 변수를 예측치/평년값으로 대체해야 한다.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
matplotlib.rcParams["font.family"] = "Malgun Gothic"  # 윈도우 기본 한글 폰트
matplotlib.rcParams["axes.unicode_minus"] = False
import numpy as np
import pandas as pd

from features import build_features
import models as M

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "processed" / "monthly_panel.csv"
OUT_DIR = Path(__file__).resolve().parent.parent / "outputs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TRAIN_START_YEAR = 2015
TRAIN_END_YEAR = 2024
TEST_YEAR = 2025


def load_panel() -> pd.DataFrame:
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"{DATA_PATH} 이 없습니다. 먼저 `python build_dataset.py`를 실행하세요.")
    df = pd.read_csv(DATA_PATH)
    df["ym"] = pd.PeriodIndex(pd.to_datetime(df["ym"].astype(str)), freq="M")
    return df


def mape(y_true, y_pred) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    mask = y_true != 0
    if not mask.any():
        return float("nan")
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


def run_backtest(train_start_year: int = TRAIN_START_YEAR, train_end_year: int = TRAIN_END_YEAR,
                  test_year: int = TEST_YEAR, label: str | None = None):
    """train_end_year까지 학습 → test_year 예측·비교. label이 없으면 '{test_year}(실제확정)' 등
    파일명/제목에 test_year를 그대로 쓴다 — 2026처럼 아직 그 해가 다 안 지났으면 test 구간은
    dropna로 실제 데이터가 있는 달만 자동으로 남는다(예측인지 검증인지는 호출부에서 구분해 표기)."""
    test_year_label = label or str(test_year)
    df = build_features(load_panel())
    train = df[(df["ym"].dt.year >= train_start_year) & (df["ym"].dt.year <= train_end_year)].dropna(subset=[M.TARGET])
    test = df[df["ym"].dt.year == test_year].dropna(subset=[M.TARGET])

    if train.empty or test.empty:
        print("학습 또는 테스트 구간에 유효한 가격 데이터가 없습니다.")
        print(f"build_dataset.py 결과(monthly_panel.csv)의 {M.TARGET} 컬럼과 연도 범위를 확인하세요.")
        return None

    baseline_pred = M.seasonal_naive_predict(train, test["ym"])

    model, cols = M.fit_model(train)
    train_medians = train[cols].median(numeric_only=True)
    model_pred = M.predict_blended(train, model, cols, test, train_medians=train_medians)

    # 폭등모델의 잔차는 "실제로 리포트하는 점예측"(블렌딩)의 in-sample 잔차로 구한다.
    train_pred_blend = M.predict_blended(train, model, cols, train, train_medians=train_medians)
    spike_params = M.fit_spike_model(train[M.TARGET].values, train_pred_blend)
    spike_prob = M.predict_spike_prob(model_pred, spike_params)

    result = pd.DataFrame({
        "ym": test["ym"].astype(str),
        "actual": test[M.TARGET].values,
        "baseline_pred": baseline_pred.values,
        "model_pred": model_pred,
        "spike_prob": spike_prob,
        "actual_spike": (test[M.TARGET].values > spike_params["threshold"]).astype(int),
    })
    result["baseline_err_pct"] = (result["baseline_pred"] - result["actual"]) / result["actual"] * 100
    result["model_err_pct"] = (result["model_pred"] - result["actual"]) / result["actual"] * 100

    metrics = {
        "baseline_MAE": float(np.mean(np.abs(result["baseline_pred"] - result["actual"]))),
        "baseline_MAPE": mape(result["actual"], result["baseline_pred"]),
        "model_MAE": float(np.mean(np.abs(result["model_pred"] - result["actual"]))),
        "model_MAPE": mape(result["actual"], result["model_pred"]),
    }

    out_csv = OUT_DIR / f"backtest_{test_year_label}_monthly.csv"
    result.to_csv(out_csv, index=False, encoding="utf-8-sig")

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(result["ym"], result["actual"], marker="o", label="실제")
    ax.plot(result["ym"], result["baseline_pred"], marker="x", label="베이스라인(계절평균)")
    ax.plot(result["ym"], result["model_pred"], marker="s", label="블렌딩(계절평균+Ridge)")
    ax.set_title(f"상추 가락시장(서울) 경락가격 — {test_year_label}년 월별 예측 vs 실제")
    ax.set_xlabel("연월")
    ax.set_ylabel("가격")
    ax.legend()
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    chart_path = OUT_DIR / f"backtest_{test_year_label}_chart.png"
    fig.savefig(chart_path, dpi=150)
    plt.close(fig)

    print(f"학습기간: {train['ym'].min()} ~ {train['ym'].max()} ({len(train)}개월)")
    print(f"폭등 문턱(학습기간 상위 {int((1-spike_params['quantile'])*100)}%): "
          f"{spike_params['threshold']:,.0f}원")
    print(f"결과 저장: {out_csv}")
    print(f"차트 저장: {chart_path}")
    print("\n=== 오차 지표 ===")
    for k, v in metrics.items():
        print(f"  {k}: {v:.2f}")
    print("\n=== 월별 상세 ===")
    print(result.to_string(index=False))
    print(f"\n[caveat] 이 백테스트는 {test_year}년 실측 기후·거시값을 그대로 사용했다 —")
    print("         '미래 예측력'이 아니라 '관계식 설명력' 검증이다. README 참고.")
    return result, metrics


if __name__ == "__main__":
    run_backtest()
