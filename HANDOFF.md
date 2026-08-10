# 핸드오프 노트 (다른 Claude 세션에서 이어가는 경우 먼저 읽을 것)

작성: 2026-08-05, 갱신: 2026-08-06(시군별 산지가격) → 2026-08-07(**전체 작물로 확장** +
미래예측 신뢰구간) → **2026-08-07 밤(새 환경 이전 + 데이터 대수술 진행 중, 아래
"⏸ 중단 상태에서 재개하기" 최우선으로 읽을 것)**. 이 프로젝트를
처음 보는 세션은 이 파일 → `README.md` → `docs/RESOLVE_GUIDE.md` → `src/models.py`
docstring 순으로 읽으면 지금까지의 경위·근거를 대부분 따라잡을 수 있다.

## ⏸ 중단 상태에서 재개하기 (최종 갱신 2026-08-10 낮 — 데이터 대수술 완료)

**환경 이동 후 남아 있던 일이 전부 끝났다.** 2026-08-10에 완료된 것:

1. **katSale 재스크래핑 완주** (104/104개월, 네트워크 실패 0건): 원시 61.1만 행
   (이전 45.8만), `jeonbuk_origin_top10crops_by_county.csv` 8,017행. 체크포인트
   자동 삭제됨. (스크립트 말미 UnicodeEncodeError는 print의 em-dash가 cp949 콘솔에
   못 찍힌 것 — 데이터 무관, ASCII 구두점으로 수정 완료.)
2. **패널 재구축**(build_dataset.py): 140행 x 783열, `build_run10.log`.
3. **최종 CV**(crop_county_cv.py, `crop_county_cv_run3.log`): 유효 84→**93개 조합**
   (재스크래핑으로 정읍 4작물·상추 임실 등 9개 신규 진입). 공통 82개 정상 조합
   중앙값 MAPE 29.6→**28.3%**(개선 48 / 유지 15 / 악화 19). 방울토마토 정읍 72→36%,
   포도 김제 63→29% 등 대폭 개선. 재스크래핑 전 결과는
   `outputs/crop_county_cv_summary_before_rescrape.csv`에 백업.
   여전히 MAPE>100%인 2개(수박 부안 188%, 대파 김제 122%)는 데이터 문제(단위 오염/
   실제 파동)로 예측 제외 확정.
4. **county_predict 작물 축 일반화 완료**: `src/crop_county_predict.py` 신규 —
   파라미터를 하드코딩하지 않고 `crop_county_cv_summary.csv`에서 읽는다(CV 재실행
   시 자동 추종). 91개 조합의 2025 검증 + 2026 실적대조 + 폭등확률 산출물이
   `outputs/crop_county_predictions/`에 생성됨. 2025 검증: 모델이 베이스라인 이김
   60/90, 고구마 14.5%·토마토 20.3%가 최상위. 수박 2025(60%)는 부안 외 시군도
   과거 단위혼입 구간의 영향 의심 — 웹앱에 넣을 땐 조합별 metrics 확인 후 선별할 것.

5. **forecast_future 작물 축 일반화 완료**: `src/crop_county_forecast.py` 신규 —
   91개 조합 x 마지막 실측~2027-12 미래 예측(1,524행) →
   `outputs/future_forecast/crop_county_future_forecast.csv`. 방법론은
   forecast_future.py와 동일(평년값 대체 + lag 재귀 + 90% 구간 + 폭등확률),
   파라미터·reference MAPE는 CV summary에서 자동 로드. gpj 보조피처·작물유형
   변형(roll12/tavg)은 미래 구간에서 평년값·재귀로 처리. 주의: 시계열이 일찍
   끊긴 조합(대파x군산 2024-11 종료, 오이x무주·고구마x남원 등)은 예측 시작
   ym이 과거임 — 소비 측에서 ym으로 필터할 것.

6. **3단계 웹앱 1차 완성** (2026-08-10): `webapp/` — **서버 없는 정적 사이트**.
   예측이 전부 사전 계산돼 있어 백엔드가 불필요하다고 판단, JSON 하나만 읽는 구조로 갔다
   (운영비 0, 정적 호스팅에 그대로 올라감, 폐쇄망·오프라인 동작).
   - `src/export_webapp_data.py` — CSV들 → `webapp/data/app_data.json`(190KB, 91개 조합)
   - `src/build_webapp.py` — CSS/JS/JSON 전부 인라인한 `webapp/dist/index.html`(단일 파일,
     더블클릭으로 열림 → 심사위원 전달용)
   - 차트는 외부 라이브러리 없이 SVG 직접 생성. 색은 dataviz 레퍼런스 팔레트를 쓰고
     검증기(validate_palette.js)를 실제로 돌려 라이트/다크 5개 검사 전부 PASS 확인.
   - **데이터 갱신 루틴**: 파이프라인 재실행 후 `export_webapp_data.py` →
     `build_webapp.py` 두 개만 돌리면 웹앱이 최신이 된다.
   - 배포 방법(GitHub Pages / Netlify / 파일 전달)은 `webapp/README.md`에 정리.
     **API 신청서용 홈페이지 주소가 필요하면 GitHub Pages 경로 권장.**
   - 주의해서 처리한 것: (a) 가격 단위는 거래단위당 단가라 작물 간 비교 불가 —
     푸터와 README에 명시(초안에 "10kg 상자 환산"이라고 잘못 쓴 것을 API 응답
     확인 후 정정), (b) 시계열이 끊긴 조합·gpj 타깃 조합·표본 부족 조합은 경고
     배너로 명시, (c) 결측월은 선을 끊어서 표시, (d) 먼 미래의 신뢰구간이 y축을
     지배하지 않도록 앞 6개월 기준으로 스케일 잡고 넘치는 부분은 clip.

**다음 작업 후보**: 웹앱 실제 배포(공개 URL 확보) → forecast_future.py의 전북 전체/상추
시군별 산출물도 웹앱에 통합(현재는 작물×시군 축만 노출) → KREI 월보 API 신청 결과 반영.

월별 데이터 갱신 루틴(필요할 때): scrape_jeonbuk_all_crops.py(신규 월만 이어받음)
→ scrape_gongpanjang.py(동일) → build_dataset.py → crop_county_cv.py →
crop_county_predict.py. katSale 일일 쿼터 ~1만 호출 주의(429 연속 시 다음날 재실행).

### 이번 세션(2026-08-07 밤)에서 한 일 요약

1. **새 환경 검증**: venv 새로 생성, API 키 5개 전부 정상 동작 확인(check_sources.py).
2. **데이터 무결성 검증**: 이전 환경의 나쁜 네트워크 때문에 **2026-05월이 대량 누락**
   확인(한 달 396건 vs 재조회 시 5개 시장×3일만으로 2,369건). 원인: 스크래퍼의
   `except: break`가 타임아웃을 조용히 삼킴 → 3~5회 재시도+실패 기록으로 수정.
   일요일 표본일은 휴장이라 원래 비는 게 정상(이제 월요일로 자동 이동).
3. **작물별 시장 재조사**(scan_crop_markets.py, katRealTime2 8일 표본 66,304건):
   상추 기준 TOP17 재사용의 커버리지 구멍 실측 — 수박 77%·고구마 90%·멜론 90%·복숭아
   93%. **구리·청주·천안·정읍·안양·수원 6개 시장 추가**(MARKETS, 23개) → 전 작물 96%+.
   근거: outputs/crop_market_coverage.csv.
4. **신규 소스: 산지공판장 정산가격**(농식품부 포털, 사용자가 MAFRA_KEY 발급→.env에
   저장됨). scrape_gongpanjang.py 신규 작성. 전북 공판장 4곳(군산원예농협·전주농협·
   김제원예농협·남원원협) 참여, 2020-01~. **도매시장 표본 부족으로 모델링 제외했던
   군산·임실·정읍·부안의 구원투수 후보**. build_dataset에 price_avg_gpj_{crop}_{county}
   컬럼으로 통합 완료, crop_county_cv는 (a) 표본 부족 조합의 대체 타깃, (b) 기존 조합의
   보조 피처(CV 개선 시에만 채택)로 쓰도록 수정 완료.
5. **교차작물 피처 실험**(cross_crop_cv.py): 90개 조합 CV 결과 **평균 +0.96pp 악화 →
   불채택 확정**(방울토마토→토마토 -0.29pp만 미미한 개선). outputs/cross_crop_cv_results.csv.
6. **CV 이상치 5개 수정**(오전): alpha 하한 2 + 예측 clip — 아래 섹션 참고.
7. 조사 결과 추가 API 중 쓸만한 것: 농넷은 여전히 미승인(E003), KREI는 보고서 API뿐,
   mafra 실시간 경매정보는 2024-05~라 이력 부족. **산지공판장이 유일한 실질 수확.**

### 문헌 기반 개선 실험 4종 (2026-08-08 저녁, 전부 CV로 판정)

문헌 근거: KREI 최병옥·최익창(2007) 과채류 월별가격 예측(농촌경제 30(1), "품목별
최적 모형이 다르다"), 강태훈(2004, 대파 등 충격지속 품목 불안정 — 우리 CV에서 대파
꼴찌인 것과 일치), arXiv 2310.18646 리뷰(저장성 vs 부패성 구분).

1. **작물 유형별 피처 차등** — `crop_county_cv.CROP_TYPE` + `_variant_feats()`:
   저장성(고구마)=roll3→roll12 교체, 엽채(상추·대파)=당월 평균기온(tavg) 추가.
   조합별로 CV 개선 시에만 채택. 결과: **8/84 조합 채택**(엽채+기온 7, 저장성 1).
2. **얇은 조합 컨센서스 파라미터 공유** — `apply_consensus()`: n_obs<60 조합은 같은
   작물의 두터운 조합(70개월+, 3개 이상) 합의 alpha/blend를 빌려와, 개별 튜닝이 2pp
   이상 확실히 못 이기면 컨센서스 채택(얇은 CV 과적합 방지). 결과: 4개 조합 채택.
   summary CSV에 params_source/consensus_* 컬럼 추가됨.
3. **GARCH 변동성**(garch_spike_cv.py): 대파·수박·고구마에 GARCH(1,1) 시변 σ vs
   현행 고정 σ로 폭등확률 Brier 비교 → **차이 무의미(±0.002), 불채택**. 등분산 유지.
4. **KREI 관측월보 파싱**(parse_krei_monthly.py): PDF 텍스트 추출 깨끗함, 출하전망
   (출하면적/단수/출하량 YoY%) 추출 개념증명 성공. **본격 활용 전 KREI 월보API 신청
   권장**(aglook.krei.re.kr/main/uMonthlyApi, 신청서 제출→검토, ☎061-820-2310) —
   사용자 액션 필요. 승인 전 백필은 zipDown URL로 연도별 일괄 다운로드 가능.

## 한 줄 요약

"지역×작목 농산물 가격예측 AI 웹앱" 공모전용. **전라북도 × 상추**로 시작해 파이프라인을
완결시킨 뒤(1.데이터수집 2.가격예측모델(전북전체+시군별) 3.폭등확률 4.지역추천(토양적성)
5.미래(2026하반기~2027)예측), **전북산 거래량 상위 10개 작물(상추·수박·포도·오이·토마토·
복숭아·고구마·방울토마토·멜론·대파) × 14개 시군 = 140개 조합**으로 확장했다. 3단계(웹앱)는
아직 시작 안 함.

## ⚡ 이상치 5개 수정 완료 (2026-08-07, 새 세션에서 처리)

이전 세션이 "정확도를 높일 방법은?" 질문에 답하다 끊기며 남긴 숙제(5개 깨진 조합)를
새 환경(venv 새로 생성)에서 처리했다. `crop_county_cv.py`에 두 가지 수정:
1. **alpha 탐색 하한 0.5 → 2로 상향** (얇은 표본에서 Ridge 계수 불안정 방지)
2. **예측값 clip 추가** — `cv_eval()`에서 로그공간 역변환 직후
   `np.clip(reg_pred, train_min/3, train_max*3)`. 학습 범위를 크게 벗어나는 외삽 차단.

재실행 결과 (`outputs/crop_county_cv_summary.csv` 갱신, 로그 `crop_county_cv_run2.log`):
- `cucumber×gochang` 27,119% → **75.9%**, `greenonion×buan` 5,513% → **53.2%**,
  `tomato×jinan` 121.6% → **37.6%** — 수치 폭발은 전부 해소.
- **여전히 나쁜 2개는 모델 문제가 아니라 데이터 문제**로 확인:
  - `watermelon×buan`(463%): 베이스라인 자체가 298%. 2018-07 월평균이 175,000원
    (중앙값 12,245원의 14배) — 수박은 통 단위/kg 단위 거래가 섞여 단가가 오염된 것으로
    의심. 예측 대상에서 제외 권장.
  - `greenonion×gimje`(111%): 베이스라인 148%. 실제 대파 가격 파동(2024-11~2025-01,
    실물량 2만+ 상자에서 중앙값의 5~6배)이 섞여 있어 진짜 변동성임. 시계열 자체가
    예측 불가능한 수준(상추의 무주와 같은 케이스).
- 정상 76개(모델 MAPE<100%) 요약: 중앙값 29.8%, **고구마 여전히 1위(평균 22.6%,
  고창 11.7%)**, 대파 꼴찌(39.3%). 모델이 베이스라인에 지는 조합 23/78(29%).

"정확도를 높이는 방법"에 대해 아직 안 해본 것(이전 세션이 남긴 아이디어, 여전히 유효):
- 작물별 시장 목록 재조사: 지금은 상추 기준 17개 시장을 전 작물에 재사용 중 —
  수박·포도처럼 유통망이 다른 작물은 katRealTime2로 작물별 상위 시장을 다시 뽑으면
  커버리지가 좋아질 수 있음.
- 교차작물 피처: 엽채류 그룹(상추·오이 등) 가격을 서로의 피처로 넣는 것 — 미시도.
- 표본 40~60개월대 얇은 조합은 근본 한계 — 데이터 축적 외 뾰족한 수 없음.

## 지금 상태 (2026-08-06 기준)

- **가격 데이터, 3계층으로 존재**:
  1. `price_avg_jeonbuk` — 전북에 실재하는 공영도매시장 3곳(전주·익산·정읍)의 실제 상추
     거래 물량가중평균("시장 위치" 기준), 2018-01~현재.
  2. `price_avg_{jeonju,iksan,jeongeup}` — 위 3개 시장을 안 합치고 개별로 낸 버전.
  3. **`price_avg_origin_{county_id}`** (전북 14개 시군, `build_dataset.COUNTY_NAME_TO_ID`
     참고) — **산지(생산지) 기준**. 실측해보니 전북산 상추의 94%가 전북 안의 3개 시장이
     아니라 전국 각지(광주·서울가락·부산·대구·대전·순천·창원 등)로 팔려서, "시장이 어디
     있는가"가 아니라 katSale/trades API의 `plor_nm`(산지) 필드로 "어느 시군에서 난
     상추인가"를 추적해 만들었다. **이게 제일 정확한 "그 지역 가격"이다** — 자세한 경위는
     `src/scrape_jeonbuk_origin.py` 상단 docstring.
  (`price_avg`=KAMIS 전국평균, `price_avg_garak_seoul`=서울 가락시장은 둘 다 예전에 쓰던
  "전북의 대리(proxy)"였는데 위 3계층으로 대체됨.)
- **모델(전북 전체, `models.py`)**: log(price) + Ridge 회귀(alpha=30.0) + 베이스라인(계절
  평균)과 80:20 블렌딩. 피처: 계절성 + 가격지연(lag1/lag12/roll3/roll6) + 당월 강수량 +
  거래물량(log). GBM·Lasso·ElasticNet·Huber·로그차분·시간추세 등 여러 대안을 CV로 시도
  했지만 전부 이 구성보다 나빴다 — 자세한 수치는 `src/models.py` docstring.
- **시군별 개별 모델(`src/county_cv.py`/`src/county_predict.py`)**: 산지 기준 14개 시군
  중 10개(관측 40개월 이상)에 대해 같은 방법론(로그+Ridge+블렌딩)을 시군마다 따로
  튜닝했다. 부안·임실·정읍·군산은 표본이 너무 적어(13~34개월) 모델링 제외. 시군마다
  최적 alpha/blend가 다 다르다 — `county_predict.COUNTY_PARAMS`에 하드코딩돼 있음(CV
  재실행하면 값이 바뀔 수 있으니 주기적으로 재확인할 것). CV 결과 요약:
    - 우수(모델 MAPE 25~29%): 익산·장수·완주·남원
    - 양호(30% 안팎): 순창·전주
    - 보통~나쁨: 김제(36%)·진안(42%)·고창(43%)
    - 사실상 예측 불가: 무주(베이스라인 자체가 112%로 극단적으로 불규칙)
  **주의**: 시군 단위는 표본이 작아(2026년 테스트가 4~8개월뿐) 연도별 변동이 크다 —
  2025년엔 모델이 이겼는데 2026년엔 베이스라인이 이기는 시군도 있었다(완주·김제·전주).
- **검증 방법론**: `python src/cross_validate.py`(전북 전체)/`county_cv.py`(시군별) —
  walk-forward, **`backtest.py` 단일 홀드아웃만 보고 피처를 고르면 안 된다**(과적합
  사례가 `models.py`에 기록돼 있음). 전북 전체 CV 평균 MAPE 26.6%(베이스라인 32.3%).
- **폭등확률**: `models.fit_spike_model`/`predict_spike_prob` — 잔차분포 기반, Brier
  score로 검증(계절성 베이스라인보다 확실히 나음). 레벨 스케일 예측만 받게 만들어서
  전북 전체든 시군별이든 그대로 재사용 가능(`county_predict.py`에서 실제로 그렇게 씀).
- **지역추천**: `src/region_recommend.py` — 흙토람 토양적성 데이터로 "전북 8개 시군 중
  상추 재배 적합도" 리포트. `outputs/region_recommend_lettuce.csv` 참고.
- **미래(2026 하반기~2027) 예측**: `src/forecast_future.py` — 실측 데이터가 없는 미래
  구간은 기후·거래물량을 "평년값(계절별 과거평균)"으로 대체하고, 가격지연(lag)은 예측값을
  다음 달 입력으로 재귀적으로 먹여가며 만든다. 12개월(lag12) 넘게 미래로 갈수록 lag 자체가
  실측이 아니라 예측값이 되어 불확실성이 누적된다 — 출력에 `lag12_is_forecast` 같은 플래그로
  표시해 뒀다. **진짜 미래 예측이라 검증 불가능** — 실적이 나오면 나중에 대조해볼 것.
- **알려진 미해결 문제**: 2026년 1월(관측 이래 최저기온) 예측이 계속 크게 빗나간다
  (-60%대). 기온을 피처로 넣어봐도 CV상 다른 연도들이 불안정해져서 아직 못 넣고 있다 —
  데이터(특히 겨울 한파 사례)가 더 쌓이면 재검토 대상.
- **농넷(nongnet) API**: 신청은 해뒀지만 아직 미승인(`E003`, 2026-08-07 재확인). 원래
  이걸로 지역별 가격을 풀려고 했는데 data.go.kr의 다른 API(katSale)로 이미 해결해서
  **더 이상 급하지 않음**. 승인되면 검증·보완용으로만 참고.

## 전체 작물 확장 (2026-08-07, 최신)

katRealTime2/trades2로 "산지=전북"인 거래 전체를 스캔해보니 **79개 작물**이 나왔다(가장
잘 팔리는 상위 10개가 거래량의 79%를 차지, `outputs`에 로그 없음 — 대화로만 확인).
사용자가 상위 10개로 확장 결정: **상추·수박·포도·오이·토마토·복숭아·고구마·방울토마토·
멜론·대파**.

- **스크래핑**: `scrape_jeonbuk_all_crops.py` — `scrape_jeonbuk_origin.py`와 시장×날짜
  조합은 완전히 동일(같은 상위 17개 시장, 상추 기준으로 뽑은 목록 그대로 재사용 — 수박·
  포도 등은 커버리지가 상추만큼(97.9%) 정확하지 않을 수 있음). 품목 필터만 빼서 **한 번의
  스크래핑으로 79개 작물을 동시에 받음**(호출 횟수는 그대로, 응답 크기만 커져서 원래
  ~1.5시간이던 게 ~6시간 걸림). 결과:
    - `data/raw/jeonbuk_origin_top10crops_by_county.csv` — 상위10 작물×시군 월별 집계(7,134행)
    - `data/raw/jeonbuk_origin_allcrops_raw.csv` — 79개 작물 전부의 원시 레코드(45.8만행,
      나중에 다른 작물 추가할 때 재스크래핑 없이 바로 씀)
- **패널 반영**: `build_dataset.build_all_crops_origin_history()` — long을
  `price_avg_origin_{crop_id}_{county_id}` 형태 wide 컬럼으로 피벗(예:
  `price_avg_origin_watermelon_namwon`). `CROP_NAME_TO_ID`는
  `scrape_jeonbuk_all_crops.py`에 있음(상추=lettuce, 수박=watermelon, 포도=grape,
  오이=cucumber, 토마토=tomato, 복숭아=peach, 고구마=sweetpotato,
  방울토마토=cherrytomato, 멜론=melon, 대파=greenonion).
- **CV 튜닝**: `crop_county_cv.py` — `county_cv.py`를 작물 축으로 일반화, 10작물×14시군
  =140개 조합 전부 alpha/blend 탐색. 결과 `outputs/crop_county_cv_summary.csv`:
    - 78/140 유효(40개월 이상), 62개는 표본부족 스킵
    - ~~5개는 수치가 깨짐~~ → **해결됨**(위 "이상치 5개 수정 완료" 참고 — alpha 하한
      상향 + 예측 clip. 남은 2개는 데이터 문제로 예측 제외 권장)
    - 정상 76개: **고구마가 압도적 1위(평균 22.6%, 고창 11.7%!)**, 대파가 꼴찌(39.3%)
    - 23/78(29%)은 모델이 베이스라인보다 나쁨 — 시군 단위 표본 한계
- **아직 안 한 것**: 다른 작물들의 실제 backtest/predict_2026/forecast_future(상추는
  county_predict.py로 다 만들었지만, 다른 9개 작물은 CV 튜닝까지만 하고 실제 예측 산출물은
  아직 안 만듦 — county_predict.py를 작물 축으로 한 번 더 일반화하면 됨).

## 미래예측 신뢰구간 (2026-08-07)

`forecast_future.py`에 오차율 표시 기능 추가:
- `reference_mape_pct`: CV로 검증된 고정 참고치(entity별, `ENTITY_CV_MAPE` 딕셔너리에
  하드코딩 — 시군별 CV 재실행하면 갱신 필요)
- `pred_lower_90`/`pred_upper_90`: 로그정규 잔차 가정 + 재귀 단계마다 `sqrt(재귀단계수)`로
  폭을 넓히는 근사 90% 구간. **12개월 이상 앞은 구간이 기하급수적으로 벌어짐**(예: 전북
  전체 12개월 뒤 예측은 2,095~126,146원까지 벌어짐) — 버그가 아니라 로그공간 불확실성이
  누적되면 원화 스케일에서 곱셈적으로 폭발하기 때문. 3~6개월 이내는 참고할 만하지만
  그 이후는 정성적 신호(방향성)로만 볼 것.

## 폴더 구조 / 실행 순서

```
data/crosswalk/    작물·지역 코드 매핑 (crop_crosswalk.csv, region_crosswalk.csv)
data/raw/          scrape_*.py가 만든 원시 스크래핑 결과:
                      garak_lettuce_history.csv (가락시장, 참고용)
                      jeonbuk_market_lettuce_history.csv / _by_region.csv ("시장 위치" 기준)
                      jeonbuk_origin_lettuce_by_county.csv / _raw.csv ("산지" 기준, 지금 주력)
data/processed/    build_dataset.py 결과 (monthly_panel.csv) — 재실행하면 덮어써짐
src/               sources.py(API 래퍼) + build_dataset/features/models/backtest/predict_2026/
                    cross_validate(전북 전체) + region_cv/county_cv/county_predict(상추 시군별) +
                    crop_county_cv(**10작물x14시군 140개 조합 CV, 최신**) +
                    region_recommend(지역추천) + forecast_future(미래 예측, 신뢰구간 포함) +
                    scrape_garak/scrape_jeonbuk_market(시장 기준)/scrape_jeonbuk_origin(상추 산지 기준)/
                    scrape_jeonbuk_all_crops(**10작물 산지 기준, 최신**)
docs/               API 키 신청 가이드, 미해결 코드값 조회 가이드(RESOLVE_GUIDE.md — 이게 제일 상세함)
outputs/           백테스트/예측 결과 CSV·차트, county_predictions/(시군별 산출물), 각종 실행 로그
.env               실제 발급받은 API 키 (5개 다 승인·동작 확인됨) — 새 환경으로 옮길 때 이 파일 그대로 복사하면 바로 됨
```

실행 순서(키가 이미 `.env`에 있으므로 바로 실데이터로 동작):
```bash
cd "crop-price-forecast"
.venv\Scripts\python.exe -m pip install -r requirements.txt   # 새 환경이면 venv부터 새로 만들 것
cd src
..\.venv\Scripts\python.exe build_dataset.py      # monthly_panel.csv 생성 (기후 API 호출 때문에 8~10분 걸림)
..\.venv\Scripts\python.exe cross_validate.py     # 전북 전체 6-fold CV
..\.venv\Scripts\python.exe backtest.py           # 전북 전체 2025년 검증
..\.venv\Scripts\python.exe predict_2026.py       # 전북 전체 2026년 실적 대조
..\.venv\Scripts\python.exe county_cv.py          # 시군별 CV(alpha/blend 재탐색, COUNTY_PARAMS 갱신용)
..\.venv\Scripts\python.exe county_predict.py     # 시군별 2025검증+2026실적대조+폭등확률
..\.venv\Scripts\python.exe forecast_future.py    # 2026 하반기~2027 진짜 미래 예측
..\.venv\Scripts\python.exe region_recommend.py   # 지역추천 리포트
```

가격 원시데이터를 다시 긁어야 하면(보통 필요 없음, 이미 `data/raw/`에 저장돼 있음):
```bash
..\.venv\Scripts\python.exe scrape_jeonbuk_origin.py    # 산지 기준(지금 주력), 17개 시장 x 3표본일, ~1시간
..\.venv\Scripts\python.exe scrape_jeonbuk_market.py    # 시장 위치 기준(참고용), ~20분
..\.venv\Scripts\python.exe scrape_garak.py             # 가락시장(참고용, 이제 타깃 아님), ~20분
```

## 다음으로 하면 좋을 것 (우선순위 순)

1. **3단계: 웹앱** — 아직 손 안 댐. `county_predict.py`/`forecast_future.py` 출력(월별
   예측·`spike_prob`)이 백엔드 로직 초안이 될 수 있음.
2. 폭등확률(`fit_spike_model`)을 새 타깃(`price_avg_jeonbuk`/시군별) 기준으로 Brier
   score 재검증 (현재는 구 타깃 기준 검증치만 있음).
3. 2026년 1월 한파 미스 — 데이터 더 쌓이면 기온 피처 재검토.
4. 농넷 API 승인되면 katSale 데이터와 교차검증용으로만 참고.
5. KOSIS 재배면적(`area_yoy_pct`)이 2025년치 발표되면 재검증 (현재는 시차 때문에
   최근 구간에 정보가 없어 안 쓰고 있음).
6. `forecast_future.py`의 미래 예측치를 실제 2026 하반기/2027 실적이 나오는 대로
   대조·재검증할 것 — 지금은 검증 불가능한 순수 forward forecast임.
7. 부안·임실·정읍·군산은 표본이 쌓이면(각 40개월 이상) `county_predict.COUNTY_PARAMS`에
   추가해 모델링 대상에 포함시킬 것.
6. 상추 외 다른 작목(딸기·사과·벼 등)으로 확장 — crosswalk에 행은 있지만 TODO 많음.

## 참고: 이번 세션에서 겪은 주요 삽질(재발 방지용)

- **data.go.kr 키 이중 URL 인코딩**: `requests`의 `params=`에 이미 인코딩된 키를 넣으면
  이중 인코딩돼서 `SERVICE_KEY_IS_NOT_REGISTERED_ERROR`남. `sources.py`가 자동으로
  디코딩해서 보관하도록 고쳐놨음(`_decoded_key`).
- **ASOS는 "어제까지"만 제공**: 오늘 날짜를 endDt로 넣으면 통째로 실패. `sources.py`에서
  자동으로 어제로 캡됨.
- **KOSIS `itmId="ALL"`로 두면 다른 작물 데이터까지 섞여 들어옴**: 반드시 작물별 itmId
  지정(`crop_crosswalk.kosis_itm_id`).
- **월간(YYYYMM) 날짜를 `pd.to_datetime`에 포맷 없이 넣으면 조용히 NaT됨**: csi가
  이 버그로 계속 비어있었음. `build_dataset.py`의 `_CYCLE_DATE_FMT`로 고침.
- **단일 연도 홀드아웃으로 피처를 고르면 과적합**: 반드시 `cross_validate.py`(다년도
  walk-forward)로 검증할 것. `models.py` docstring에 실패 사례 상세 기록.
