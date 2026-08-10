# 미해결 값 해결 가이드

`sources.py`가 실동작하려면 채워야 할 값들의 **찾은 값 + 조회 방법**.
크로스워크(`crop_crosswalk.csv`/`region_crosswalk.csv`)와 환경변수에 반영한다.

---

## -2) [2026-08, 가장 중요] 전북 실제 공판장 가격 소스 확정 — `price_avg_jeonbuk`

몇 달째 "KAMIS는 전국평균, 가락시장은 서울"이라는 한계를 안고 갔었는데, data.go.kr에서
**"한국농수산식품유통공사_전국 공영도매시장 정산정보"**(신규승인, 자동승인) API를 찾아서
드디어 해결했다.

- **End Point**: `https://apis.data.go.kr/B552845/katSale/trades` (Method: GET)
- **필수 파라미터**: `serviceKey`, `cond[whsl_mrkt_cd::EQ]`(도매시장코드),
  `cond[trd_clcln_ymd::EQ]`(거래정산일자, `YYYY-MM-DD`)
- **응답 필드**: `avgprc`(평균가)/`lwprc`(최저가)/`hgprc`(최고가)/`unit_tot_qty`(단위총물량)/
  `gds_mclsf_nm`(품목중분류명, 상추는 `"상추"`)/`gds_sclsf_nm`(청상추/적상추)/
  `whsl_mrkt_nm`(시장명) 등
- **명세 확인 방법**: data.go.kr 마이페이지 → 활용신청 현황 → 해당 API 클릭 → "참고문서"에
  첨부된 xlsx 다운로드(로그인 세션이 있으면 `requests`로 그냥 GET해도 받아짐 — 별도 인증
  불필요, `www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=...&fileDetailSn=...` 패턴).

**도매시장코드(`whsl_mrkt_cd`)는 어디에도 문서화가 안 돼 있어서 실측으로 찾았다:**
1. at.agromarket.kr(도매시장 통합홈페이지) `/whsal/search.do`에서 전국 공영도매시장
   목록 확인 → **전북에 실재하는 공영도매시장은 전주·익산·정읍 3곳뿐**(진안·남원·완주·
   김제·고창·부안엔 자체 공영도매시장이 없음 — 아마 인근 3곳으로 출하).
2. 같은 API의 자매 API "전국 공영도매시장 실시간 경매정보"(`katRealTime2/trades2`)는
   `whsl_mrkt_cd`가 필수가 아니라서, 날짜만으로 조회해 응답의 `whsl_mrkt_nm`으로 찾음
   (페이지를 넘기며 `익산`이 나올 때까지 스캔 → `whsl_mrkt_cd: "350301"` 확인).
3. 패턴(앞 2자리=시도, 35=전라북도, KOSIS 코드와 일치)을 보고 나머지 후보를 던져
   `katSale/trades`에서 `totalCount>0`으로 검증 → **전주=350101, 익산=350301,
   정읍=350402** 확정. (패턴 추정이라 다른 지역으로 확장 시 반드시 같은 방식으로
   재검증할 것 — 자릿수 규칙이 100% 확실친 않음.)

**날짜 커버리지**: 2018-01-15는 데이터 있음, 2016-01-15는 없음 → 최소 2018년부터.

**수집 방식**: `src/scrape_jeonbuk_market.py`가 월별 표본일(5·15·25일) × 3개 시장을
호출해 물량가중평균으로 월별 근사치를 만든다(가락시장 스크래핑과 같은 패턴, 다만 HTML
파싱이 아니라 JSON API라 훨씬 빠르고 안정적). `data/raw/jeonbuk_market_lettuce_history.csv`
로 저장되고, `build_dataset.py`가 `monthly_panel.csv`에 `price_avg_jeonbuk` 컬럼으로
자동 반영한다. `models.TARGET`을 이걸로 전환함(자세한 CV 재검증 결과는 `models.py`
docstring·README 참고).

**참고로 확인한 다른 aT API들**(같은 계정으로 자동승인됨, 안 씀):
- `katSale`의 자매 API `katRealTime2`(실시간 경매정보) — 낙찰 건별 상세, market_cd
  선택사항. 위 코드 찾기에 씀.
- odcloud 15134477("공판장 가격 관련 정보")은 이미 예전에 확인함 — **시장/지역 구분
  필드가 아예 없어서** 전북 특정이 불가능했다(2024-01~08 8개월치뿐이기도 함). 이번
  katSale과는 다른 데이터셋이니 혼동 주의.

---

## 조회용 헬퍼 API (코드 찾을 때 이걸로)

| 무엇 | 요청주소 |
|---|---|
| KOSIS 통계표목록(표ID 검색) | `https://kosis.kr/openapi/statisticsList.do?method=getList` |
| KOSIS 표 메타(항목ID·분류코드) | `https://kosis.kr/openapi/statisticsData.do?method=getMeta&type=TBL` |
| 농진청 관측지대·지점 목록 | `http://apis.data.go.kr/1390802/AgriWeather/WeatherObsrInfo/GrdlInfo/getWeatherZoneCodeList` |
| 농진청 관측지점 상세(위경도) | data.go.kr 15078057 계열 |
| KMA ASOS 지점정보(위경도) | `https://data.kma.go.kr/tmeta/stn/selectStnList.do` |
| KAMIS 코드(품목·품종·부류·산지) | data.mafra.go.kr 코드조회 서비스 |
| 국립종자원 작물코드 | `https://www.data.go.kr/data/15058658/openapi.do` |
| 흙토람 작물코드 | soil.rda.go.kr / naas.go.kr |
| HS코드 | 관세법령정보포털(unipass) / tradedata.go.kr |
| 법정동코드(52 전환) | `https://www.code.go.kr/` |

---

## -2) [해결됨] 흙토람 토양적성(V2) — URL·파라미터명 둘 다 틀려 있었다

기존 코드(`_suit_real`)는 URL이 `.../SoilFitStat/getSoilCropFitInfo`였는데 실제로는
**`.../SoilFitStat/V2/getSoilCropFitInfo`로 "/V2/" 세그먼트가 빠져 있었다**
(`NO_OPENAPI_SERVICE_ERROR` — data.go.kr 15144182에서 실제 데이터셋을 다시 검색해서 확인함,
기존에 참고했던 서비스 문서가 V1이었던 것으로 보임). 파라미터명도 `BJD_Code`/`Crop_Code`로
추측해 뒀었는데 전부 틀렸다 — 실제로는 대소문자가 특이한 **`STDG_CD`**(법정동코드)와
**`soil_Crop_CD`**(작물코드)다. 이건 Swagger 스펙 JSON에 파라미터 정의 자체가 비어 있어서
(`spec.paths[...].get.parameters`가 없음) 흔한 네이밍 컨벤션(camelCase 등) 40여 가지를
직접 시도해봐도 안 나왔고, **첨부된 hwp 기술명세서를 다운로드해서(`pip install pyhwp`,
`hwp5html`로 변환) 표(表) 내용을 직접 읽고서야 확인**했다. 응답도 등급별 롱포맷이 아니라
한 행에 최적지/적지/가능지/저위생산지/기타 면적이 다 들어있는 와이드포맷이라
`_suit_real`을 다시 짰다.

**작물코드**: soil.rda.go.kr "작물별 토양적성도" 페이지엔 100작물 중 상당수가 아이콘
링크로 안 보여서(카테고리 텍스트로만 존재), 브라우저 JS로 DOM을 뒤져서
`go_Map('CCAreaPercent','COR_LETTUCE','CR044','','작물별토양적성도-상추')` 호출부를 찾아
`CR044`를 확인했다(양상추는 별도로 `CR045`).

**법정동코드(전북 8시군)**: code.go.kr에서 전북특별자치도=52(시/도 드롭다운) 확인 후,
시/군/구 드롭다운의 `<option value="...">`을 그대로 읽으면 시군구코드 3자리가 나온다
(예: 부안군=800). 대표 법정동코드(그 시/군 전체) = `"52" + 시군구코드(3자리) + "00000"`
(예: 부안군 5280000000) — 부안군은 실제 검색 결과로도 직접 재확인함.

```
jinan(진안군)=5272000000   namwon(남원시)=5219000000   jeongeup(정읍시)=5218000000
wanju(완주군)=5271000000   iksan(익산시)=5214000000     gimje(김제시)=5221000000
gochang(고창군)=5279000000 buan(부안군)=5280000000
```

`python region_recommend.py`로 8개 시군 전체 실데이터 확인 완료 — 정읍시가 상추 토양적성
1위(가중점수 기준). README "3-3" 절 참고.

---

## -1) [중요] KAMIS periodProductList는 "최근 1년"만 조회된다 — 실측 확인됨

실제 발급받은 키로 테스트한 결과(2026-08-04):
- 최근 1년 이내 날짜 범위(예: 2025-09~2025-11, 2026-07)를 요청하면 **정상적으로 그 날짜 그대로** 응답.
- 1년보다 오래된 날짜(2015, 2022, 2023, 2024)를 요청하면 **에러 없이(error_code 000)** 조용히
  "오늘 기준 최근 1년" 데이터로 바뀌어서 응답한다(20~35초 걸림). 요청한 과거 날짜는 완전히 무시됨.
- 즉 `_kamis_real`로는 **10년치 히스토리를 가져올 수 없다.** 이건 파라미터 실수가 아니라
  이 API 액션 자체의(혹은 이 계정 등급의) 제약으로 보인다.

**대안 후보 (조사됨, 검증 필요):**
1. **data.go.kr 파일데이터 15134477** — "한국농수산식품유통공사_공판장 가격 관련 정보"
   (https://www.data.go.kr/data/15134477/fileData.do) — CSV, **로그인 없이 바로 다운로드 가능**,
   92,572행, 연 1회 갱신. "공판장 가격"이라는 이름이 이 프로젝트 타깃과 정확히 일치.
   단, 한 번에 몇 년치가 들어있는지는 실제로 열어봐야 확인됨(연간 스냅샷일 수도).
2. **data.go.kr 오픈API 15109052** — "농림수산식품교육문화정보원_산지공판장별경락가격조회"
   (https://www.data.go.kr/data/15109052/openapi.do) — KAMIS가 아닌 다른 기관(농식품교육문화정보원)
   제공이라 별도 활용신청 필요. 조회 가능 기간이 페이지에 명시돼 있지 않아 활용신청 후 직접 확인 필요.
3. **KAMIS 홈페이지 자체의 "과거가격자료" 수동 다운로드** — 소매는 `~'20.3`까지로 끊긴 페이지가
   확인됨(https://www.kamis.or.kr/customer/price/eco/item.do). 도매/공판장 쪽에도 유사한
   기간 한정 아카이브 페이지가 있을 수 있음 — KAMIS 사이트에서 직접 "가격정보 > 부가정보"를 확인해봐야 함.

**추가로 확인된 것**: 응답 속도가 날짜 범위와 무관하게 대체로 느리다(수 초~67초까지 편차 큼).
처음엔 "365일 이내면 빠르다"고 추정했으나 실측해보니 365일 이내(350일 전)도 67초 걸려서
기존 25초 타임아웃에 매번 실패했다. → `sources.py`의 `_request` 기본 타임아웃을
25초→60초로, 재시도는 2회→1회로 조정해서 느린 응답도 받아내도록 고침(대신 실패 시
확인까지 최대 ~2분 걸릴 수 있음 — 원래 자주 호출하는 API가 아니라 감수 가능).

**후속 조사 결과 (해결됨)**: 1)·2)번 모두 확인해본 결과 기간이 부족했다 —
15134477(odcloud)은 2024-01~08 약 8개월치뿐이고, 15109052는 명세만 있고 실제 데이터 기간
불명. 대신 **3)번 계열의 KAMIS 홈페이지 "가락시장 경락가격 > 기간별"**
(`https://www.kamis.or.kr/customer/price/market/period.do?regday=YYYY.MM.DD&marketcode=1&itemcode=21400`)
을 실측 이분탐색한 결과 **로그인·키 없이 약 5년 전(2021-08~09 무렵)부터 오늘까지** 서버
렌더링으로 실데이터를 준다는 걸 확인했다(2021-08-04는 없고 2021-09-15는 있음 — 2021년
폭우 상추파동 시점과 일치하는 실제 가격 76,999원도 확인). 단, 이 페이지는 하루(`regday`)
단위로만 조회되고 대량 range 쿼리 UI는 자동화가 불안정해서, `src/scrape_garak.py`가
월별 표본일(5·15·25일, 실패 시 인접일 폴백)을 스크래핑해 월평균으로 근사하는 방식을 씀.
**주의**: 이 값은 "가락시장"(서울 단일 시장) 낙찰가이고, KAMIS API의 `price_avg`는
"전국평균"이라 시장 범위가 다르다 — 레벨이 다를 수 있어 `price_avg_garak_seoul`이라는
별도 컬럼으로 붙이고 `price_avg`와 합치지 않는다.

---

## 0) 상추(lettuce) 코드 — 최우선 (이번 프로젝트의 1차 타깃 작목)

`crop_crosswalk.csv`에 `lettuce` 행은 추가해 뒀지만 전부 TODO. 상추는 청상추/적상추 등
품종이 갈리고 노지·시설 혼재라 다른 작목보다 확인할 게 많다.

- **`kamis_item`/`kamis_kind`**: KAMIS 홈페이지(kamis.or.kr) → 가격정보 → 채소류 → 상추 조회 시
  URL 파라미터에 노출되는 `itemcode`/`kindcode`를 그대로 쓰거나, data.mafra.go.kr 코드조회에서
  "상추"로 검색. 청상추/적상추가 `kindcode`로 갈릴 가능성이 높음 — 둘 다 확인해서 어느 쪽을
  대표 시계열로 쓸지 정할 것 (청상추가 물량·데이터 연속성 면에서 무난할 가능성 높음).
- **`kosis_item`**: KOSIS 농림 > 농작물생산조사에서 "엽채류" 또는 "상추" 재배면적 표 검색.
  기존에 확인된 시설작물 표(`DT_1ET0017`, 딸기·방울토마토·파프리카)에 상추가 같이 들어있는지
  먼저 확인 — 있으면 재조사 없이 `itmId`만 상추로 바꿔 재사용 가능.
- **`soil_code`**: 흙토람 작물별 토양적성 목록에서 상추(엽채류) 코드 확인.
- **`hs_code`**: 신선 상추는 사실상 수입이 없어(부패 빠름) 비워 둠 — `_import_real`은 자동으로
  `TODO`/빈값 처리되어 폴백된다. 굳이 채울 필요 없음.
- **`income_code`**: 소득조사 자료집에 상추가 있는지 확인, 없으면 income 피처는 생략해도
  가격 예측 파이프라인 자체는 동작함 (선택 피처).

---

## 1) 소득조사 → CSV 방식으로 확정 (odcloud API 경로 폐기)

3060748(농축산물 소득정보)은 원래 odcloud API로 접근하려 했으나:
- data.go.kr 활용신청 과정에서 uddi 발급 자체가 오류로 막힘
- 설령 발급되더라도 API 데이터가 **2014년까지만** 있어 2015~2025 백테스트 구간과 안 맞음

그래서 API 대신 **정적 CSV**로 확정. `sources.py`의 `load_income()`은 이제
`data/raw/income.csv`를 먼저 찾고(`_income_csv`), 없을 때만 API(`_income_real`, uddi 있는 경우)로
폴백한다. **주의**: 이 income 데이터는 가격 예측 파이프라인(`build_dataset.py`)에 아직
연결돼 있지 않다 — 수확량·수익성 참고용 선택 데이터라 없어도 가격 예측 자체는 정상 동작한다.

- **CSV 만드는 법**: 농사로(nongsaro.go.kr) 또는 KOSIS에서 "농축산물소득자료집"을 다운로드
  → `docs/income_csv_template.csv` 형식(`crop_id,year,gross,cost,net`)으로 정리
  → `data/raw/income.csv`로 저장 (이 폴더는 `.gitignore`에 포함되어 있음).
- 상추 데이터가 자료집에 없으면 이 항목은 그냥 비워두고 넘어가도 된다 — 필수 아님.

---

## 2) KOSIS 재배면적 표ID  →  `crop_crosswalk.kosis_item`/`kosis_itm_id`

**채운 것(확인됨):**
- 벼 → `DT_1ET0033` (시군별 논벼 재배면적, **시군 제공**)
- 딸기·방울토마토·파프리카 → `DT_1ET0017` (시설작물 재배면적)
- 사과·복숭아·블루베리 → `DT_1AG20411` (과수 재배 농가 및 면적)
- **상추 → `DT_1ET0028`("채소생산량(엽채류)") · itmId=`T66`("상추:면적")** — `getMeta(type=ITM)`으로
  전체 62개 항목 중 실측 확인함(노지+시설 합계 T66, 세분화하려면 노지상추=T72/시설상추=T78도 있음).
  실데이터 2015~2024년까지 확인됨(442ha~1471ha 등). **단, 시군이 아니라 시도(전라북도=35) 단위로만
  제공** — `getMeta(type=OBJ_ID)`는 안 먹고, 지역 코드가 `type=ITM` 응답 안에 시도 목록(11 서울 ~
  39 제주, 35=전라북도)으로 같이 섞여 나옴. 8개 시군이 전부 같은 도 단위 값을 공유하므로
  `build_dataset.py`의 `build_area_yearly()`는 `sum()`이 아니라 `mean()`으로 집계해야
  8중복(x8)을 피할 수 있음(이미 반영됨).

**남은 것(콩·고추·오미자):** `getStatList`로 "재배면적" 검색하거나
KOSIS 농림 > 농작물생산조사 목록에서 표ID 확인. K1_19(농작물생산조사) 하위 표 목록을
`method=getList&parentListId=K1_19`로 훑으면 됨(상추 찾을 때 쓴 방법과 동일).

**중요 — itmId/objL1:** 한 표에 여러 작목이 들어있으므로, `getMeta(type=ITM)`으로
해당 작물의 **항목코드(itmId)**를 확인해 `_area_real`의 `itmId`에 넣어야 특정 작물만
걸러진다(예전엔 `"ALL"`로 하드코딩돼 있어 62개 항목이 다 섞여서 나오는 버그가 있었음 — 고침).
지역 분류코드(`objL1`)는 `getMeta(type=ITM)` 응답에 같이 섞여 나오는 경우가 많다
(`type=OBJ_ID`/`type=OBJ`는 이 표에서 404성 에러 남 — 표마다 다를 수 있음).

**주의:** 표마다 시군 제공 여부가 다르다. 시도만 있는 표는 지역 해상도가 제한된다
(기존 caveat: KAMIS 가격이 지역단위 아님과 같은 맥락).

---

## 2-1) [버그 수정] 소비자심리지수(csi)가 계속 비어있던 이유

`sources.py`의 `_macro_real`/`load_macro`는 정상 동작해서 csi 실데이터(2015-01~2026-07,
139행)를 제대로 반환하는데도 `monthly_panel.csv`엔 계속 비어있었다. 원인은
`build_dataset.py`의 `build_macro_monthly()`가 `pd.to_datetime(d["date"])`을 포맷 지정
없이 호출한 것 — ECOS의 월간(`cycle="M"`) 날짜는 `"202501"`처럼 6자리라 pandas가
자동인식 못 하고 **조용히 전부 NaT로 만든 뒤 dropna로 사라짐**(일별 `fx_usd`는 8자리
`"20250101"`이라 우연히 자동인식돼서 문제가 안 드러났었다). `_CYCLE_DATE_FMT`로
cycle별 포맷(`D→%Y%m%d, M→%Y%m, Y→%Y`)을 명시해서 고침.

---

## 3) 생장도일 관측지점코드  →  `region_crosswalk.rda_spot`

KMA ASOS 번호(`asos_station`)와 **다른 체계**다. 열은 이미 추가해 뒀다(값 TODO).

- **찾는 법**: `getWeatherZoneCodeList`로 관측지대별 지점코드·지점명을 받거나,
  관측지점 상세(15078057)로 지점 **위경도**를 받아 → 8개 시군 중심좌표에 **최근접 지점** 배정.
- 생장도일 요청 파라미터는 `Page_No/Page_Size/search_Year` 패턴(블로그 확인) →
  지점 필터 방식은 첫 실호출 시 응답에서 지점코드 필드 확인 후 확정.

---

## 4) 코드값 (crosswalk 나머지 TODO)

| 열 | 조회처 | 비고 |
|---|---|---|
| `kamis_item`/`kind` | data.mafra.go.kr 코드조회(품목·품종 표준코드) | 기존 5개(딸기226 등) 대조 확인 |
| `income_code` | 소득자료집 목차 / 조사입력항목코드(data.go.kr 15069669) | 소득조사 작목코드 |
| `soil_code` | 흙토람 작물별 토양적성 작물 목록 | SoilFitStat 작물코드 |
| `hs_code` | unipass / tradedata.go.kr | 품목별 HS 6~10단위(실 세번 확인) |
| `ldong_code` | code.go.kr | **전북특별자치도=52**, 고창·부안 재확인 |
| `asos_station` | data.kma.go.kr 지점정보 | 위경도로 최근접 확정 |
| `rda_spot` | 위 3) 참조 | 농진청 지점 |

---

## 5) 파라미터·응답 필드 최종 대조 (첫 실호출 때)

| 소스 | 확인할 것 |
|---|---|
| 흙토람 SoilFitStat | 법정동/작물코드 파라미터명, 응답 등급·면적 필드명 (XML) |
| 생장도일 GrwDay | 지점 필터 파라미터, 응답 생장도일 필드명 (XML) |
| 관세 nitemtrade | params `hsSgn/strtYymm/endYymm`, 응답 `impWgt/impDlr` (XML) — 코드에 반영됨 |

> 확정 방법: 로컬에서 키 세팅 후 `python check_sources.py` 실행 →
> CONFIRMED 소스가 `✔`로 바뀌는지 확인, 필드명 어긋나면 응답 원본 보고 매핑 수정.

---

## 채우는 우선순위 (예측 엔진 최소 실행)

이번 프로젝트는 **상추(lettuce) × 전북 8시군** 단일 조합만 먼저 완결시키면 되므로,
아래 순서를 상추 기준으로 최소화한다.

1. `ldong_code`(전북 8시군 전체) + `kamis_item`/`kamis_kind`(상추) — 지역 조인키 + 가격. **이게 없으면 아무것도 안 됨.**
2. `asos_station`은 이미 채워져 있음 — 기후 피처는 바로 사용 가능.
3. `kosis_item`(상추 재배면적 표ID) + itmId — 공급측 피처(선택이지만 있으면 정확도 개선).
4. `income_code` / `soil_code` / `rda_spot` — 정적 스코어·생리, 없어도 가격 예측 자체는 동작.

다른 작목(콩·고추·오미자 등)의 TODO는 상추 파이프라인이 끝난 뒤, 지역·작목 확대 단계에서 채운다.
