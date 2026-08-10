# -*- coding: utf-8 -*-
"""parse_krei_monthly.py — KREI 농업관측센터 관측월보 PDF에서 출하전망(선행 공급지표) 추출.

개념증명(2026-08-08): 과채 관측월보 PDF의 텍스트 추출이 깨끗해 파싱 가능함을 확인.
"출하전망" 블록에서 품목별 (출하면적/단수/출하량) 전년 대비 증감률(%)을 뽑는다 —
현재 모델에 없는 유일한 '미래 공급' 신호라 예측 피처 후보로 가치가 있음.

다운로드 URL 패턴 (aglook.krei.re.kr):
  /main/uObserveMonth/{품목군코드}/download/{파일ID}/ORGTEXT_FILE   (개별 호)
  /main/uObserveMonth/{품목군코드}/zipDown/{연도}/pdf               (연간 일괄)
  품목군코드: 과채=OVR0000000031, 엽근채=OVR..., 양념채소=OVR... (사이트 메뉴 참고)

정식 경로는 KREI '월보API'(aglook.krei.re.kr/main/uMonthlyApi, 신청서 제출→검토→제공,
문의 061-820-2310)가 있으므로, 본격 활용 전에 API 신청을 권장. 이 파서는 API 승인
전까지의 백필/검증용.

한계: 호별로 레이아웃이 조금씩 다를 수 있어(연도별 양식 변경) 과거 호 전체를 돌릴 땐
파싱 실패 호를 로그로 남기고 수동 확인 필요.
"""
from __future__ import annotations

import re
import sys

from pypdf import PdfReader

# 관측월보 품목명 -> 우리 crop_id (과채 월보 기준; 다른 월보는 추가)
PUM_TO_CROP = {
    "일반토마토": "tomato", "대추형방울토마토": "cherrytomato",
    "원형방울토마토": "cherrytomato", "수박": "watermelon",
    "멜론": "melon", "백다다기오이": "cucumber", "취청오이": "cucumber",
    "가시오이": "cucumber",
}

_FORECAST = re.compile(
    r"출하전망\s*(\d+)월\s*출하량\s*전년\s*대비\s*([\d.]+)%\s*(증가|감소)")
_AREA = re.compile(r"출하면적\s*:?\s*전년\s*대비\s*([\d.]+)%\s*(증가|감소)")
_YIELD = re.compile(r"단수\s*:?\s*전년\s*대비\s*([\d.]+)%\s*(증가|감소)")


def parse_pdf(path: str) -> list[dict]:
    reader = PdfReader(path)
    rows = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        # 페이지에 어떤 품목 섹션인지: 알려진 품목명 중 처음 등장하는 것
        pum = next((p for p in PUM_TO_CROP if p in text), None)
        if pum is None:
            continue
        m = _FORECAST.search(text)
        if not m:
            continue
        month, pct, sign = int(m.group(1)), float(m.group(2)), m.group(3)
        row = {"pum": pum, "crop_id": PUM_TO_CROP[pum], "page": i + 1,
               "forecast_month": month,
               "shipment_yoy_pct": pct if sign == "증가" else -pct}
        a = _AREA.search(text)
        if a:
            row["area_yoy_pct"] = float(a.group(1)) * (1 if a.group(2) == "증가" else -1)
        y = _YIELD.search(text)
        if y:
            row["yield_yoy_pct"] = float(y.group(1)) * (1 if y.group(2) == "증가" else -1)
        rows.append(row)
    return rows


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        raise SystemExit("사용법: python parse_krei_monthly.py <관측월보.pdf>")
    for r in parse_pdf(path):
        print(r)
