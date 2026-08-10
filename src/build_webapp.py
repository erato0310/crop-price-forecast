# -*- coding: utf-8 -*-
"""build_webapp.py — webapp/을 배포용 단일 HTML 파일로 묶는다.

CSS·JS·데이터(JSON)를 전부 인라인해서 `webapp/dist/index.html` 하나만 남긴다.
파일 하나라 어디에나 올릴 수 있고(메일 첨부·USB·아무 정적 호스팅), fetch를 쓰지
않으므로 file:// 로 그냥 열어도 동작한다 — 심사위원에게 파일로 전달할 때 유용.

여러 파일로 나뉜 원본(webapp/index.html + style.css + app.js + data/)은 그대로
두고 개발에 쓴다. GitHub Pages 등에 올릴 때는 원본 폴더째 올리는 쪽이 캐시 효율이 좋다.

실행: python build_webapp.py   (먼저 export_webapp_data.py로 데이터부터 갱신할 것)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEBAPP = ROOT / "webapp"
DIST = WEBAPP / "dist" / "index.html"


def main() -> None:
    html = (WEBAPP / "index.html").read_text(encoding="utf-8")
    css = (WEBAPP / "style.css").read_text(encoding="utf-8")
    js = (WEBAPP / "app.js").read_text(encoding="utf-8")
    data = json.loads((WEBAPP / "data" / "app_data.json").read_text(encoding="utf-8"))
    geo = json.loads((WEBAPP / "data" / "jeonbuk_geo.json").read_text(encoding="utf-8"))

    # fetch 대신 인라인 상수를 읽도록 진입점만 교체 (원본 app.js는 그대로 둔다)
    fetch_block = """const [a, g] = await Promise.all([
    fetch("data/app_data.json").then((r) => r.json()),
    fetch("data/jeonbuk_geo.json").then((r) => r.json()),
  ]);
  DATA = a; GEO = g;"""
    js_inline = js.replace(fetch_block, "DATA = window.__APP_DATA__; GEO = window.__GEO_DATA__;")
    if "window.__APP_DATA__" not in js_inline:
        raise SystemExit("app.js의 데이터 로딩 부분을 찾지 못했습니다 — build_webapp.py를 함께 수정하세요.")

    html = html.replace(
        '<link rel="stylesheet" href="style.css">',
        f"<style>\n{css}\n</style>",
    )
    def embed(obj) -> str:
        # </script> 가 문자열 안에 들어가 파싱이 깨지는 것 방지
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    html = html.replace(
        '<script src="app.js"></script>',
        f"<script>window.__APP_DATA__={embed(data)};"
        f"window.__GEO_DATA__={embed(geo)};</script>\n<script>\n{js_inline}\n</script>",
    )

    DIST.parent.mkdir(parents=True, exist_ok=True)
    DIST.write_text(html, encoding="utf-8")
    print(f"저장 완료: {DIST} ({DIST.stat().st_size / 1024:.0f} KB)")
    print("이 파일 하나만 있으면 브라우저에서 바로 열립니다(서버 불필요).")


if __name__ == "__main__":
    main()
