# -*- coding: utf-8 -*-
"""models.py — 베이스라인(계절 평균) + 회귀 모델 정의.

[모델 선택 근거] 원래 GBM(GradientBoostingRegressor)을 썼으나, 학습 데이터가 40개월뿐인
상황에서 어블레이션 실측 결과 "로그변환 타깃 + Ridge 회귀"가 더 좋았다(MAPE 23.8%->20.7%).
가격은 폭우·폭염 때 배 이상 뛰는 곱셈적(승법) 패턴이라 원 스케일 제곱오차(GBM 기본 손실)는
비싼 달(7~10월)의 절대오차에 손실이 쏠려 싼 달(1~3월)의 상대오차를 희생시키는 경향이 있었다.
로그 스케일로 학습하면 손실이 "상대오차"에 가까워져 우리가 실제로 보는 지표(MAPE)와 더
잘 맞는다.

[중요 — 2026-08 재검증으로 rain_sum/fx_usd_pct_chg 제거함] 원래는 rain_sum+fx_usd_pct_chg가
"최적"이라고 결론냈었다(2025년 단일 홀드아웃 MAPE 20.7%). 하지만 이건 **2025년 딱 한 해에만
맞춰 고른 것**이었다 — 2022~2025년 4개 연도를 각각 테스트로 돌리는 walk-forward 교차검증을
해보니, rain_sum을 넣은 모델은 2025년엔 잘 맞아도(20.7%) 2023년엔 MAPE 87%까지 폭발하는 등
연도별로 극단적으로 불안정했다(4개 fold 평균 45.8%). 반면 rain_sum·tavg 등 기후변수를 전부
빼고 **계절성(month_sin/cos)+가격 지연(lag1/lag12/roll3/roll6)만** 쓰면 fold 평균 MAPE가
25.9%(alpha=5.0 기준, 2022년 fold는 학습 4개월뿐이라 노이즈라 판단해 평균에서 제외)로
훨씬 안정적이었다(범위 22.5~32.7, 최악의 해도 87%까지 안 감). fx_usd_pct_chg는 있으나 없으나
결과가 거의 동일해(있어도 해 안 됨) 같이 뺐다. **교훈**: 테스트 연도 1개짜리 홀드아웃으로
피처를 고르면 그 해에 우연히 잘 맞는 피처를 "최적"으로 오판하기 쉽다 — 데이터가 더 쌓이면
(특히 2026년, 2027년 실적이 나오면) rain_sum/tavg를 다시 넣고 재검증할 가치가 있다(2026-01
한파처럼 기온이 실제로 중요해 보이는 사례가 있었음 — outputs 대화기록 참고).

Ridge를 쓴 이유는: 순수 OLS(정규화 없는 선형회귀)가 단일 홀드아웃에서는 근소하게 더
좋았지만, lag1/lag12/roll3/roll6 네 피처가 서로 상관관계가 매우 높아 계수가 사실상
임의로 갈라지는(불안정한) 현상이 있어 — 다른 학습셋이면 계수가 크게 바뀔 위험이 있는
회귀임. alpha는 walk-forward CV(2023~2025 fold 평균)로 재탐색해 5.0으로 올림
(alpha=1.0 대비 fold 평균 MAPE 27.9%->25.9%).

[중요 — 베이스라인과 50:50 블렌딩] Lasso/ElasticNet/Huber, lag 피처 부분집합, 로그차분
재구성 등을 CV로 재탐색해봤지만 전부 현재 Ridge 구성보다 나쁘거나 훨씬 나빴다(Huber는
설정을 더 파봐야 할 정도로 발산함). 대신 **베이스라인(계절평균)과 회귀모델 예측을
단순 평균(50:50)** 내면 2023~2025 fold 평균 MAPE가 25.9%->22.1%로 개선되고, **개별
fold 전부**(특히 가장 나빴던 2024년 fold: 32.7%->25.2%) 좋아진다 — 두 방법이 서로
다른 종류의 오차를 내서 평균이 분산을 줄여주는 전형적인 앙상블 효과로 보인다. w=0.5
근방(0.4~0.6)에서 평균이 가장 낮았고 이 구간에서 평평해서 소수점까지 정교하게 맞추진
않았다. **주의**: 2022 fold(학습 4개월)만은 블렌딩하면 오히려 나빠진다(순수모델 30.7%->
블렌드 51.6%) — 베이스라인 자체가 표본이 너무 적어 신뢰 못 할 때는 블렌딩이 역효과.
실제 서비스에서는 학습 데이터가 계속 늘어나기만 하므로(가락시장 스크래핑 누적) 이
문제는 초기 한 번뿐이라고 보고 그냥 둔다.

[검토함 — 온난화 추세, 2026-08] "기후변화 가속화를 수식으로 반영" 아이디어를 검토했다.
1) 실제로 연평균기온(2015~2025)엔 유의한 온난화 추세가 있다(+0.11℃/년, p=0.034,
   R²=0.41) — 진짜 신호. 2) 하지만 2026-01 미스의 원인이었던 **겨울철(12~2월) 기온은
   추세가 없다**(+0.044℃/년, p=0.68, R²=0.02 — 완전히 노이즈 수준). 겨울철은 온난화가
   진행돼도 극단적 한파가 오히려 잦아질 수 있다는 게 알려진 현상(북극 온난화->제트기류
   약화->한파 남하)이라 "따뜻해지니까 다음 겨울은 더 안전할 것"이라는 가정 자체가 안
   맞을 수 있다. 3) 그래서 연도추세(`year_trend`) 피처를 CV로 실측했는데, 현재 alpha=5
   기준으론 오히려 악화(22.1%->23.3%), 정규화를 아주 세게(alpha=50) 줘야 근소하게
   나아지는데(21.9%) 이건 사실상 그 피처의 영향력을 거의 0으로 눌러버린 것과 같아서
   실질적 이득이 아니다. tavg×연도 상호작용도 CV로 더 나빴다(25.7~26.5%). **결론**:
   온난화는 실재하지만 우리가 가진 가격 데이터(52~64개월)로 "가속화율"까지 추정해
   반영하기엔 표본이 턱없이 부족하다 — 기후 추세 추정은 원래 수십 년 단위 통계라, 5년
   짜리로 하면 신호보다 노이즈를 학습할 위험이 크다. 데이터가 몇 년 더 쌓이면(특히 겨울
   한파 사례가 더 들어오면) 재검증할 가치 있음.

[중요 — 2026-08 타깃 전면 전환: price_avg_garak_seoul → price_avg_jeonbuk]
data.go.kr에서 신규 승인된 "한국농수산식품유통공사_전국 공영도매시장 정산정보"
(katSale/trades, https://apis.data.go.kr/B552845/katSale) API로 **전북에 실재하는 공영
도매시장 3곳(전주·익산·정읍)의 실제 상추 거래 데이터**를 찾았다(시장코드 전주=350101,
익산=350301, 정읍=350402, 실측 확인 — 문서화 안 돼 있어 katRealTime2/trades2를 날짜만
으로 스캔해서 whsl_mrkt_nm 매칭 후 역으로 찾음). 2018-01부터 현재까지 커버돼서
price_avg_garak_seoul(서울 가락시장, 2021-09~)보다 훨씬 길고, 무엇보다 **이 프로젝트가
원래 원했던 "전북 지역" 가격 그 자체**다(price_avg=KAMIS 전국평균, price_avg_garak_seoul=
서울 단일 시장 — 둘 다 전북의 대리(proxy)였을 뿐). src/scrape_jeonbuk_market.py로 월별
물량가중평균을 만들어 `price_avg_jeonbuk` 컬럼으로 반영했다.

타깃이 바뀌었으니 위의 모든 피처/alpha/블렌딩 결론을 처음부터 CV로 재검증했다(2018년치가
있어 2020~2025 6개 fold 사용 — 예전 3~4개 fold보다 훨씬 안정적인 검증):
- **rain_sum이 이번엔 6개 fold 전부에서 일관되게 개선**시켰다(예전 target에서는 특정
  연도에 MAPE 90%+ 폭발해서 뺐던 것과 정반대 — 다른 시장 데이터라 노이즈 구조 자체가
  다른 것으로 보임). tavg는 여전히 도움 안 됨. fx/csi/area는 여전히 계수가 사실상 0.
- alpha 재탐색: 10.0이 최적(기존 5.0에서 상향).
- 베이스라인 블렌딩 비율 재탐색: 0.3이 최적(기존 0.5에서 하향 — rain_sum이 이미 어느
  정도 설명력을 갖고 있어서 베이스라인 의존도가 줄어든 것으로 해석).
- 최종 CV 평균 MAPE(2020~2025, 6 fold): **27.05%** (베이스라인 단독 32.31%, lag만 30.88%).
  2020년 fold가 유독 나쁜데(37~64%대) 코로나 시기 수급 교란으로 추정 — 모델 결함이라기
  보다 그 해 자체가 예외적으로 어려웠을 가능성.

[중요 — 2026-08 2차 개선: 거래물량(qty_log) 추가] 2020년 fold를 더 뜯어봤다
(2020-01 -63%, 2020-02 +78%, 2020-10 +160% 등 양방향으로 크게 틀림). 거래물량이 유독
적은 달(예: 2020-01 qty=4,363, 다른 달 평균 10,000~18,000대)에서 극단치가 나오는
경향이 보여서 — 표본이 얇을수록 소수 거래가 평균가를 좌우해 튀는 게 자연스럽다 —
`log1p(qty_total_jeonbuk)`를 피처로 추가했다(`qty_log`, `features.add_liquidity_feature`).
CV로 alpha·블렌딩 비율까지 다시 맞춘 결과:
  - alpha: 10.0 → 30.0 (더 강한 정규화가 유리해짐)
  - blend_w: 0.3 → 0.2
  - 6 fold 평균 MAPE: 27.05% → **26.64%** (2021 fold 25.4%->23.3%, 2025 fold
    13.3%->10.8%로 크게 좋아지고 2020 fold는 39.6%->40.0%로 거의 그대로 — 순개선).
lag 피처 부분집합(1개/2개짜리 조합)도 다시 CV로 시도했지만 여전히 4개 전부 쓰는 게
최선이었고, 겨울철(12~2월) 기온 상호작용도 여전히 유의미한 차이가 없었다(과거 타깃
때와 같은 결론).

**주의**: 이 재조정은 2020~2025 CV 평균을 기준으로 한 것이라, 2026년 실측 대조
(`predict_2026.py`)에서는 오히려 MAPE가 소폭 나빠졌다(19.1%->23.2%, 2026-01 한파 미스가
-57%->-60%로 더 벌어짐). CV 평균 개선이 모든 개별 미래 해의 개선을 보장하진 않는다는
걸 보여주는 사례 — 특히 2026-01처럼 학습 데이터에 없던 극단적 사례는 CV로도 못 잡는다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.linear_model import Ridge

TARGET = "price_avg_jeonbuk"  # 전북 실제 공판장(전주·익산·정읍) 물량가중평균, 2018-01~현재.
                               # price_avg(KAMIS 전국평균)·price_avg_garak_seoul(서울 가락시장)은
                               # 둘 다 전북의 대리(proxy)였을 뿐 — 이게 진짜 전북 지역 가격이다.

FEATURE_COLS_BASE = ["month_sin", "month_cos"]
# time_idx는 일부러 뺐다: GBM(트리 앙상블)은 학습 구간 밖 값으로 외삽이 안 돼서
# (리프값이 학습 최대 time_idx에서 그대로 고정됨), 2025년처럼 미래 구간을 예측할 때
# 오히려 다른 피처들의 분할을 왜곡시켜 MAE/MAPE가 더 나빠지는 걸 실측으로 확인함.
FEATURE_COLS_LAG = [f"{TARGET}_lag1", f"{TARGET}_lag12", f"{TARGET}_roll3", f"{TARGET}_roll6"]
# roll12/mom_yoy도 features.py엔 계산돼 있지만 여기 목록엔 일부러 뺐다: 학습 40개월 규모에서
# 어블레이션 실측 결과 오히려 MAE/MAPE를 악화시킴(과적합·표본부족 추정) — outputs/ablation 기록 참고.

FEATURE_COLS_CLIMATE = ["rain_sum"]
# price_avg_jeonbuk 타깃으로 재검증(2020~2025, 6 fold)한 결과 rain_sum이 모든 fold에서
# 일관되게 개선시켜서 다시 포함함(예전 price_avg_garak_seoul 타깃에서는 정반대로 특정
# 연도에 MAPE가 폭발해서 뺐었다 — 타깃이 바뀌면서 노이즈 구조 자체가 달라진 것으로 보임).
# tavg는 여전히 도움 안 됨(제외), 겨울철(12~2월) 상호작용으로 넣어봐도 유의미한 차이 없음.
FEATURE_COLS_SUPPLY_MACRO = []
# fx_usd_pct_chg/csi_pct_chg/area_yoy_pct는 새 타깃에서도 CV 재검증 결과 계수가 사실상
# 0으로 수렴해 있으나 없으나 결과가 완전히 동일했다(뺌). area_yoy_pct는 KOSIS가 연 1회
# 갱신이라 최근 테스트 구간엔 값이 아직 없어(중앙값으로 채워짐) 애초에 정보가 없었다.

FEATURE_COLS_LIQUIDITY = ["qty_log"]
# 거래물량(log). 2020년 fold를 들여다보니 표본이 얇은 달(거래량 적음)일수록 평균가가
# 소수 거래에 좌우돼 극단치가 나오는 경향이 보였다(예: 2020-10 qty=15329인데도 160%
# 벗어남 — 물량 자체보다 그 달의 시장 상황이 원인일 수도 있어 완전한 설명은 아님). CV
# 재검증 결과 넣으니 평균 MAPE가 소폭 개선됐다(27.05%->26.64%, alpha=10->30, blend
# 0.3->0.2로 재조정 후) — 2021·2025 fold는 뚜렷이 좋아지고 2020 fold는 약간 나빠지는
# trade-off가 있지만 전체 평균은 이긴다.

ALL_FEATURE_COLS = (FEATURE_COLS_BASE + FEATURE_COLS_LAG + FEATURE_COLS_CLIMATE
                    + FEATURE_COLS_SUPPLY_MACRO + FEATURE_COLS_LIQUIDITY)


def seasonal_naive_predict(train: pd.DataFrame, target_months: pd.PeriodIndex, col: str = TARGET) -> pd.Series:
    """월별(계절) 평균만으로 예측하는 베이스라인 — '방정식 기반 시뮬레이션' 1차 검증용."""
    monthly_avg = train.groupby(train["ym"].dt.month)[col].mean()
    fallback = train[col].mean()
    preds = [monthly_avg.get(m.month, fallback) for m in target_months]
    return pd.Series(preds, index=target_months)


RIDGE_ALPHA = 30.0  # walk-forward CV(2020~2025 fold 평균, price_avg_jeonbuk+qty_log)로 재탐색한 값.


def fit_model(train: pd.DataFrame, feature_cols: list[str] | None = None, target: str = TARGET):
    """log(target) + Ridge 회귀 학습. 전부 NaN인 컬럼(예: API 키가 없어 비어있는 기후·거시
    피처)은 학습에서 제외한다."""
    feature_cols = feature_cols or ALL_FEATURE_COLS
    cols = [c for c in feature_cols if c in train.columns and train[c].notna().any()]
    if not cols:
        cols = ["month_sin", "month_cos"]
    X = train[cols].fillna(train[cols].median(numeric_only=True))
    y = np.log(train[target])
    model = Ridge(alpha=RIDGE_ALPHA)
    model.fit(X, y)
    return model, cols


def predict_model(model, cols: list[str], df: pd.DataFrame, train_medians: pd.Series | None = None) -> np.ndarray:
    fill = train_medians if train_medians is not None else df[cols].median(numeric_only=True)
    X = df[cols].fillna(fill)
    return np.exp(model.predict(X))


BLEND_WEIGHT = 0.2  # 베이스라인(계절평균) 비중. walk-forward CV(price_avg_jeonbuk+qty_log)로 재탐색한 값.


def predict_blended(train: pd.DataFrame, model, cols: list[str], df: pd.DataFrame,
                     train_medians: pd.Series | None = None, w: float = BLEND_WEIGHT) -> np.ndarray:
    """예측 = w*베이스라인(계절평균) + (1-w)*회귀모델. df는 train 자신이어도 된다(폭등모델의
    in-sample 잔차 계산용)."""
    baseline = seasonal_naive_predict(train, df["ym"]).values
    reg = predict_model(model, cols, df, train_medians=train_medians)
    return w * baseline + (1 - w) * reg


# ─────────────────────────────────────────────────────────────
# 폭등확률(spike probability) — 잔차 분포 기반
# ─────────────────────────────────────────────────────────────
#
# [검증 근거] 점예측(현재는 predict_blended)의 로그공간 잔차가 정규분포를 따른다고 가정하고,
# "가격이 학습기간 상위 20% 문턱을 넘을 확률"을 정규분포 CDF로 추정한다. walk-forward
# CV(2023~2025, 36개월 풀링)로 Brier score 검증한 결과:
#   잔차분포 기반 0.058 vs 월별 과거비율 베이스라인 0.096 vs 고정확률 베이스라인 0.155
# — 세 배 가까이 더 잘 보정돼 있다(확률 구간별 예측확률과 실제발생률이 잘 맞음). 이 검증은
# 블렌딩 전(순수 회귀모델) 기준으로 했지만, 블렌딩도 같은 로그공간 잔차 가정을 그대로
# 쓰므로 구조는 동일하다 — 재검증은 아직 안 함(TODO).
# 폭등 문턱(SPIKE_QUANTILE=0.80)은 반드시 "학습 데이터만"으로 계산해야 한다(테스트 구간
# 정보가 새어들어가면 안 됨) — fit_spike_model이 train_actual/train_pred만 받는 이유.

SPIKE_QUANTILE = 0.80  # "폭등" 정의: 학습기간 가격분포 상위 20%


def fit_spike_model(train_actual, train_pred, quantile: float = SPIKE_QUANTILE) -> dict:
    """train_actual/train_pred: 학습기간의 실제값·점예측값(레벨 스케일, 같은 길이).
    로그공간 잔차 표준편차와 폭등문턱(train_actual 분포 기준)을 구한다. 점예측이 어떤
    방식(순수 회귀든 블렌딩이든)이든 상관없이 쓸 수 있게 레벨값만 받는다."""
    train_actual = np.asarray(train_actual, dtype=float)
    train_pred = np.asarray(train_pred, dtype=float)
    resid = np.log(train_actual) - np.log(train_pred)
    return {
        "resid_std": float(np.std(resid, ddof=1)),
        "threshold": float(np.quantile(train_actual, quantile)),
        "quantile": quantile,
    }


def predict_spike_prob(pred_level, spike_params: dict) -> np.ndarray:
    """P(그 달 가격 > 폭등문턱). pred_level은 레벨 스케일 점예측(순수/블렌딩 무관).
    로그공간 잔차가 정규분포라는 가정."""
    pred_log = np.log(np.asarray(pred_level, dtype=float))
    threshold_log = np.log(spike_params["threshold"])
    z = (threshold_log - pred_log) / spike_params["resid_std"]
    return 1 - norm.cdf(z)
