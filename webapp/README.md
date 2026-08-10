# 웹앱 (3단계)

전북 14개 시군 × 10개 작물의 가격 예측을 보여주는 **서버 없는 정적 웹앱**입니다.

예측은 `crop_county_predict.py` / `crop_county_forecast.py`가 미리 다 계산해 두므로,
웹앱은 그 결과 JSON 하나만 읽습니다. **백엔드도, 데이터베이스도, 서버 비용도 없습니다** —
정적 호스팅에 올리면 그대로 동작합니다.

## 구성

```
webapp/
  index.html          화면 구조
  style.css           스타일 (라이트/다크 자동 + 수동 토글)
  app.js              렌더링 + SVG 차트 (외부 라이브러리 없음)
  data/app_data.json  사전 계산된 예측 데이터 (약 190KB)
  dist/index.html     ↑ 전부 인라인한 배포용 단일 파일 (약 230KB)
```

외부 CDN·폰트·라이브러리를 하나도 쓰지 않습니다. 인터넷이 끊겨도, 폐쇄망에서도 동작합니다.

## 기능

- 작물·시군 선택 → 실제 거래가격 추이 + 2027년까지의 예측 (90% 예측 범위 포함)
- 다음 달 예측가격, 최근 대비 변화율, **가격 폭등 위험**(확률), 조합별 예측 정확도
- 마우스를 올리면 해당 월의 값을 보여주는 크로스헤어 + 툴팁
- "표로 보기" — 차트와 같은 내용의 접근 가능한 표 (스크린리더·인쇄 대응)
- 검증 성적 비교(모델 vs 단순 예측), 토양 기준 재배 적합 지역(상추)
- 데이터가 오래됐거나 표본이 적은 조합은 **경고 배너로 명시** — 조용히 넘어가지 않습니다

## 데이터 갱신

원천 데이터를 새로 받은 뒤 아래 두 개를 실행하면 웹앱이 자동으로 최신이 됩니다.

```bash
cd src
..\.venv\Scripts\python.exe export_webapp_data.py   # CSV → webapp/data/app_data.json
..\.venv\Scripts\python.exe build_webapp.py         # → webapp/dist/index.html (단일 파일)
```

전체 파이프라인(스크래핑부터)은 프로젝트 루트의 `HANDOFF.md`를 참고하세요.

## 로컬에서 보기

`dist/index.html`은 **더블클릭만 하면** 브라우저에서 열립니다(서버 불필요).

원본 폴더로 개발할 때는 `fetch`가 `file://`에서 막히므로 간단한 서버가 필요합니다.

```bash
cd webapp
..\.venv\Scripts\python.exe -m http.server 8777
```

그 다음 브라우저에서 `http://127.0.0.1:8777` 을 엽니다.

## 배포 — 공개 URL 받기

공공데이터 API 신청서에 적을 **서비스 홈페이지 주소**가 필요하다면 아래 중 하나를 쓰면 됩니다.
셋 다 무료이고, 정적 사이트라 트래픽 비용이 들지 않습니다.

### 방법 1. GitHub Pages (권장 — 주소가 안 바뀌고 갱신이 쉬움)

1. GitHub에서 새 저장소를 만듭니다(예: `crop-price-forecast`). 공개(Public)로 설정.
2. 프로젝트 루트에서:

```bash
git init
git add .
git commit -m "전북 농산물 가격예측 웹앱"
git branch -M main
git remote add origin https://github.com/<사용자명>/crop-price-forecast.git
git push -u origin main
```

3. 저장소 → **Settings → Pages** → Source를 `Deploy from a branch`,
   Branch를 `main` / 폴더를 `/ (root)`로 지정하고 저장합니다.
4. 1~2분 뒤 아래 주소로 공개됩니다.

```
https://<사용자명>.github.io/crop-price-forecast/webapp/
```

`.gitignore`가 `.env`(API 키)와 `data/raw/`(대용량 원본)를 이미 제외하므로
**키가 저장소에 올라가지 않습니다.** 푸시 전에 `git status`로 `.env`가 목록에 없는지 한 번 확인하세요.

### 방법 2. Netlify / Vercel (드래그 앤 드롭)

`webapp` 폴더를 [app.netlify.com/drop](https://app.netlify.com/drop)에 끌어다 놓으면
즉시 `https://<임의이름>.netlify.app` 주소가 나옵니다. 계정을 만들면 주소를 고정할 수 있습니다.

### 방법 3. 파일로 전달

`dist/index.html` 하나만 메일에 첨부하거나 USB에 담아 전달합니다.
받는 사람은 더블클릭만 하면 되고, 인터넷 연결도 필요 없습니다.

## 알려진 한계

- **가격 단위**: 도매시장 정산정보의 거래 단위당 단가입니다. 포장 단위가 작물마다 달라
  **작물 간 가격 비교는 의미가 없습니다**(같은 작물의 시점·시군 비교에 쓰세요).
- **군산 등 일부 시군**은 도매시장 표본이 부족해 산지공판장 정산가를 대신 사용합니다 —
  가격 수준이 다른 시군과 직접 비교되지 않으며, 앱에서 배너로 안내합니다.
- **12개월 이상 앞선 예측**은 예측 범위가 급격히 넓어집니다. 버그가 아니라
  누적된 불확실성을 정직하게 표시한 것입니다. 3~6개월 이내를 참고하세요.
- 수박×부안, 대파×김제 조합은 데이터 품질 문제로 예측에서 제외했습니다.
