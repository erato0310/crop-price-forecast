# 다음 세션 인수인계 (2026-08-14 갱신)

> **읽는 순서**: 이 파일 → `HANDOFF.md`(전체 경위·검정 결과) → 필요한 소스 docstring
> `HANDOFF.md`가 기준 문서다. 이 파일은 **지금 어디까지 왔고 다음에 뭘 하면 되는지**만 적는다.

---

## 지금 상태 — 완료된 것

### 자료 (완결)
```
data/raw/lettuce_daily_raw.csv     2,164,359행 / 268MB
                                   전국 32개 공영도매시장 전수
                                   2018-01-02 ~ 2026-08-11, 전 거래일
                                   전북산 476,188행 / 시군 14개 / 읍면 63개
data/raw/daily_weather_lettuce.csv 전북 ASOS 9지점 x 11필드
data/raw/daily_weather_aws.csv     전북 AWS 8지점
data/raw/daily_weather_competitors.csv  경쟁 7개 시도 26지점
```
검수(`audit_lettuce_daily.py`) 전 항목 통과. 목록 감사(`audit_hardcoded_lists.py`)도 통과.

### 모델 (확정)
| 용도 | 구성 | 성적 |
|---|---|---|
| 월간 h=1개월 | 계절+가격시차, Ridge+스미어링 | CV 23.03% / 홀드아웃 11.17% (계절평균 25.45%/12.67%) |
| 주간 h=1주 | +광, Ridge+GBM 앙상블 | CV 21.50%, 6/6 전승 (주차평균 31.17%) |
| 2027 전망 | 1~3개월 모델 / 4개월+ 계절평균×수준보정 | 지평별 22~23% |
| 품종별(포기찹·청상추·적상추) | 같은 주간 모델을 품종마다 다시 | 계열 104주 미만이면 **예측 안 냄** |
| 급등 상태 h=1주 | 로지스틱 | AUC 0.950 (지속성 0.857) 개선 |
| 급등 **시작 시기** | 로지스틱 | **판정불가** — 달력 이상 없음 |
| 출하처 선택 | 같은 주·같은 품종 대응짝 | 관행 대비 +10.0% [+8.0, +12.0] |

### 웹앱 (2026-08-14 기준 · 실서버 확인 완료)

공개 주소 <https://erato0310.github.io/crop-price-forecast/>

```
webapp/lettuce.html                     한 파일에 화면·스타일·렌더링 전부
webapp/data/lettuce_app.json     1.2MB  전체(주력 17품종 합산) — 첫 화면
webapp/data/lettuce_destinations.json  427KB  출하처 도매시장·품종 (기간별)
webapp/data/lettuce_forecast_2027.json 194KB
webapp/data/jeonbuk_eup_geo.json 169KB  읍면 경계 — 드릴다운할 때만
webapp/data/lettuce_surge.json    18KB  여름·가을 급등기
webapp/data/lettuce_var_chung.json     977KB  청상추 ─┐
webapp/data/lettuce_var_jeok.json      851KB  적상추  ├ 품종을 고를 때만
webapp/data/lettuce_var_pogichap.json  560KB  포기찹 ─┘
```
첫 화면이 받는 것은 1.9MB. 나머지는 필요할 때만 받는다.

띄우는 법:
```bash
cd "C:/Users/지리산 살래농장/Documents/project 1/crop-price-forecast" && .venv/Scripts/python.exe -m http.server 8731 --directory webapp
```
→ `http://localhost:8731/lettuce.html`

> **캐시 주의.** `python http.server`는 캐시 방지 헤더를 안 보낸다. 고친 게 안 보이면
> `?v=2` 같은 걸 붙이거나 Ctrl+Shift+R. 이것 때문에 "수정이 하나도 안 됐다"고
> 한참 헤맸다. 공개 사이트도 마찬가지다.

**화면 구성**
- 3단계 확대: 전북 → 시군(3.1배) → 읍면(9.4배). 뒤로가기도 한 칸씩 나온다.
- 확대해 들어가면 지도 옆에 그 지역 요약(값·물량·출하처·품종·급등기·예측)이 뜬다.
- **설명은 카드마다 오른쪽 위 물음표 안에** 있다. 카드 본문에는 한 줄만 둔다.
  한계에 관한 말은 접어 두되 지우지 않았다 — 물음표 안 경고 상자에 있다.
- 상단 걸개 둘: **기간**(8주/6개월/1년/3년/전체/직접) · **품종**(전체/포기찹/청상추/적상추)
- 급등기가 진행 중이면 맨 위에 주의 배너. 판단 기준은 브라우저 날짜가 아니라
  **자료의 마지막 주**다.

**얇은 계열을 다루는 규칙(세 군데에 같은 잣대)**
값만 보고 세우면 몇 주치뿐인 곳이 1위로 올라온다. 실제로 세 번 겪었다.
1. 읍면 표 — 남원 산동면 0.2t·1주가 9,622원으로 1위
2. 시군 표(품종 선택 시) — 군산 청상추 22주가 7,714원으로 1위
3. 지도 색 척도 — 위 둘이 척도를 다 차지해 진짜 산지가 옅어 보임

→ 순위·지표·색척도 **셋 다에서 빼고** 표 아래로 내린다. 표에는 남긴다(실제 거래다).

---

## 2026-08-13~14에 새로 만든 것

| 무엇 | 스크립트 | 결과 |
|---|---|---|
| 읍면 경계 | `build_geo.py` (확장) | 시군과 **같은 투영**. 이름은 지도 원본 그대로 두고 가격자료 라벨에 맞춰 고치지 않았다. 물량 기준 48.4%만 폴리곤이 붙는다 |
| 여름·가을 급등기 | `analyze_autumn_surge.py` | 9년 중 9년 발생. 시작 중앙값 07-27, 지속 7주, 꼭대기 상반기 대비 4.9배 |
| 출하처 도매시장 | `export_destinations.py` | 시군·읍면별 상위 6곳 + 품종 구성. 익산=서울가락 67%, 운봉읍=부산엄궁 83% |
| 출하처 **선택 검정** | `analyze_market_choice.py` | 같은 주·같은 품종 대응짝 13,909개. 관행 대비 **+10.0%** |
| 품종 3분할 | `export_by_variety.py` | 포기찹·청상추·적상추. 상위 3품종이 물량의 90.8% |

### 품종 분할에서 지킨 원칙
셋으로 나누면 계열이 3분의 1로 얇아진다. **값과 예측을 다르게 다룬다.**
- 값(평균·최고·최저·물량) — 세는 것이므로 자료가 있으면 낸다
- 예측·검증 성적 — **104주 미만이면 아예 내지 않는다.** 짧은 자료로 낸 예측은
  맞는지 확인할 방법이 없다. 화면에는 `자료 얇음`으로 뜬다

실측: 청상추는 군산 빼고 전 시군 가능 / 포기찹은 6곳 미달(고창 46주·임실 44주·부안 37주)
/ 군산은 세 품종 다 부족.

---

## 바로 다음에 할 일 (우선순위)

1. **`scrape_jeonbuk_all_crops.py`의 `qty_kg` 버그 수정** — 10작물 라인이 4배 부풀려져 있다.
   `:231`의 `d["qty_kg"] = d["qty"] * d["unit_qty"]`가 범인이고, `unit_tot_qty`는
   **이미 kg 총량**이라 상자무게를 또 곱하는 꼴이다 (HANDOFF 7.1). 상추 라인은 수정됨.
   이 버그 때문에 10작물 앱을 사이트에서 내렸다. **고쳐야 다시 올릴 수 있다.**
2. 지역추천 재구성 — 토양적성도는 전북 상추 면적의 6.5%만 설명 (HANDOFF 9.5)
3. 남원 산간 구조 변화 추적 — 운봉이 2023년 0t → 2026년 1,193t (HANDOFF 10.5)

---

## 사용자가 정한 방침 (바꾸지 말 것)

- **상추 단일 작목.** `all_crops`는 신경 쓰지 않는다.
- **도매시장(katSale)만.** 산지공판장은 도매시장으로 재유입되므로 이중계상 (HANDOFF 1-B).
- **라벨을 지어내지 않는다.** 산지가 시군까지만 적혀 있으면 `익산시` 그대로 쓴다.
  `(미상)`·`읍면 미기재` 같은 말로 바꾸지 않는다.
- **단위를 반드시 명시.** 모든 가격은 원/kg, 상자단가는 `원/4kg 상자`로 병기.

---

## 반드시 지킬 방법론 (내가 두 번 어겨서 사고 냄)

### 목록은 **추측하지 말고 열거**한다

두 번 같은 실수를 했다.

| | 잘못한 것 | 결과 | 올바른 방법 |
|---|---|---|---|
| 시장 | 코드 접두를 추측해 훑고 "전수 탐색"이라 보고 | 안산·구미 누락 (30개로 착각) | `katRealTime2/trades2`를 **시장코드 없이 날짜만으로** 조회 |
| 품종 | 눈에 보이는 품종을 손으로 적음 | 5종 2.17% 누락 | **배제 목록 방식** — 뺄 것만 적고 나머지는 전부 포함 |

`audit_hardcoded_lists.py`를 돌리면 코드에 박힌 목록과 자료를 대조한다.
**새 목록을 추가하면 이 감사에도 추가할 것.**

열거가 불가능해 사람 판단이 들어간 3곳은 감사 출력에 명시돼 있다
(경쟁산지 지점 선택, 시군-지점 대체, 재배형태 추론).

### 성능 주장은 반드시 대조군과 함께

- 계절평균(또는 주차평균) 없이 MAPE만 제시하면 계절성 효과를 모델 성능으로 오인한다.
- 블록 부트스트랩 95% 구간이 0을 포함하면 **"판정불가"이지 "개선"이 아니다.**
- CV에서 고른 것을 홀드아웃 성적으로 다시 고르면 안 된다(rev2가 빠진 함정).

---

## 자주 쓰는 명령

```bash
cd "C:/Users/지리산 살래농장/Documents/project 1/crop-price-forecast/src"
P=../.venv/Scripts/python.exe

$P scrape_lettuce_daily.py --start 2018-01   # 수집(이어받기 자동)
$P audit_lettuce_daily.py                    # 수집 검수
$P audit_hardcoded_lists.py                  # 목록 감사
$P scrape_lettuce_daily.py --reaggregate     # 집계만 재생성

$P lettuce_cv.py compare                     # 월간 피처집합 비교
$P lettuce_weekly.py compare                 # 주간
$P test_long_horizon.py                      # 지평별 성적
$P forecast_2027.py                          # 2027 전망 생성
$P export_lettuce_webapp.py                  # 웹앱 JSON 생성 (~10분)

$P analyze_autumn_surge.py                   # 여름·가을 급등기 (기술통계+검정+export)
$P export_destinations.py                    # 출하처 도매시장·품종 (기간별)
$P build_geo.py                              # 시군·읍면 경계 (원본은 data/raw)
```

웹앱이 읽는 파일은 5개다. `export_lettuce_webapp.py`만 10분 걸리고 나머지는 1~2분.
```
lettuce_app.json 1.2MB · lettuce_destinations.json 333KB · lettuce_forecast_2027.json 194KB
jeonbuk_eup_geo.json 172KB(드릴다운 때만) · lettuce_surge.json 18KB
```

예약 작업 `lettuce_daily_resume`가 매일 00:10에 수집을 이어받는다(완주 상태면 즉시 종료).

---

## API 키·쿼터

`.env`에 8개 (gitignore됨). 쿼터 실측치:

| API | 한도 | 비고 |
|---|---|---|
| katSale (data.go.kr) | **약 1,900회/일** | HANDOFF에 적혀 있던 "~1만"은 틀림 |
| ASOS (data.go.kr) | katSale과 **별개** | 같은 날 병행 수집 가능 |
| KMA API 허브 | 별도 키 `KMA_APIHUB_KEY` | API마다 활용신청 필요 |
| at.agromarket | `AT_AGROMARKET_KEY` | **남은 API가 산지공판장뿐이라 현재 용도 없음** |

katSale 전 구간 재수집은 약 2,100요청 / 70분.

---

## git 함정 (2026-08-12에 걸린 것)

**1. 이 폴더의 `.git`이 한 번 사라진 적 있다.** zip으로 옮기면서 빠졌다.
저장소는 멀쩡히 살아 있었는데 로컬만 연결이 끊겨 "git 설정을 안 했나" 싶은 상황이 됐다.
복구는 `git clone` 받아서 그 `.git`만 작업 폴더로 옮기면 된다. 파일은 손대지 않는다.

**2. 자격증명이 다른 계정으로 캐시돼 있다.** 저장소 주인은 `erato0310`인데
Windows 자격증명 관리자에는 `pilos050804`가 저장돼 있어서 push가 403으로 막혔다.
그래서 원격 주소에 계정을 박아 뒀다 — `https://erato0310@github.com/...`.

캐시를 지우고 다시 로그인하려면:
```bash
printf 'protocol=https\nhost=github.com\n\n' | git credential reject
```

**3. push는 반드시 사람이 쓰는 터미널에서 할 것.** 에이전트 셸에서는
자격증명 로그인 창을 띄우지 못해 그냥 멈춘다(5분 대기 후 타임아웃).
`/dev/tty`가 없어서 device 코드조차 표시하지 못한다.

**4. 로그인 창이 아예 안 뜨는 문제가 있었다.** GCM이 GUI 프롬프트를 못 띄웠다.
그래서 창 대신 **터미널에 코드가 찍히는 device 방식**으로 바꿔 뒀고, 그걸로 통과했다.
설정은 `.git/config`에 있으니 clone을 다시 받으면 또 해줘야 한다:
```bash
git config credential.gitHubAuthModes device
git config credential.guiPrompt false
```
push하면 터미널에 `github.com/login/device` 주소와 8자리 코드가 뜬다.
브라우저에서 그 코드를 넣으면 push가 이어진다.

**5. `core.autocrlf`가 시스템 전역에서 true다.** 이 저장소는 `false`로 덮어 놨다.
안 그러면 줄바꿈만 바뀐 파일이 수십 개씩 변경된 것처럼 잡힌다.
`git status`가 `M`인데 `git diff --numstat`에 안 나오면 stat 캐시 노이즈다.

---

## 사이트 구조 (2026-08-12 개편)

```
/                    → webapp/lettuce.html 로 이동
/webapp/             → lettuce.html 로 이동 (예전 10작물 앱 자리, 밖에 적어둔 주소라 살려 둠)
/webapp/lettuce.html 상추 앱 본체
```

10작물 앱(`app.js`·`style.css`·`dist/`·`app_data.json`)은 **사이트에서 내렸다.**
qty_kg 4배 부풀림 위에 계산된 숫자라 공개해 둘 수 없었다.
파일은 커밋 `2c1c9a1`에 남아 있으니 버그를 고치면 되살릴 수 있다.

---

## 마지막 검증 상태 (2026-08-12)

```
audit_lettuce_daily.py      전 항목 통과
audit_hardcoded_lists.py    전 항목 통과
월간 CV 23.28% / 홀드아웃 11.17%     (32개 시장·17품종 기준, 30개 시장과 동일)
주간 광 -0.52%p [-0.95, -0.10]      개선 판정 유지
웹앱 지도14·시군13·읍면63·차트·2027전망  전부 렌더 확인
공개 사이트 https://erato0310.github.io/crop-price-forecast/  (2026-08-14, 136c6f4)
  → 3단계 확대·설명 창 9개·품종 3분할·출하처 막대 전부 실서버 확인
품종 파일 대조         3품종 x 14시군 주수·물량이 원자료와 불일치 0건
회귀 검사              전체 화면이 개편 전과 동일(진안 6,008 / 전주 3,293 / 21,821t)
키 노출 검사           추적 파일 210개 x 키 7개 — 없음
```
