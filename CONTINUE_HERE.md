# 다음 세션 인수인계 (2026-08-12 작성)

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

### 웹앱 (동작 확인)
```
webapp/lettuce.html                 시군 지도 → 읍면 드릴다운
webapp/data/lettuce_app.json        1.20MB (시군 13 / 읍면 63)
webapp/data/lettuce_forecast_2027.json  194KB
```
띄우는 법:
```bash
cd "C:/Users/지리산 살래농장/Documents/project 1/crop-price-forecast" && .venv/Scripts/python.exe -m http.server 8731 --directory webapp
```
→ `http://localhost:8731/lettuce.html`

기능: 주간 평균/최저/최고 + 최고 상자단가, 읍면별 순위(최고·최저 발생 주 표시),
품종 구성, 주간 예측 4주, **2027년까지 월별 전망(방법·오차율 병기)**.

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
공개 사이트 https://erato0310.github.io/crop-price-forecast/
  → 상추 앱으로 배포 완료. 지도·읍면 드릴다운·2027 전망·/webapp/ 이동 전부 실서버 확인
```
