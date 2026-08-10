# -*- coding: utf-8 -*-
"""build_geo.py — 전북 14개 시군 경계를 웹앱용 SVG path로 변환한다.

원본: 통계청(KOSTAT) 2018 시군구 경계를 정리해 공개한 southkorea-maps 데이터셋
      https://github.com/southkorea/southkorea-maps  (kostat/2018)
      전라북도는 코드 접두 '35'. 전주시는 완산구(35011)·덕진구(35012)로 나뉘어 있어
      하나로 합친다(우리 데이터는 시 단위이므로).

원본 그대로면 3만 점이 넘어 웹에 싣기엔 무겁다. 그래서
  1) Douglas-Peucker로 단순화(모양은 알아볼 수 있게, 점 수는 크게 줄여서)
  2) 아주 작은 섬(군산 고군산군도 등)은 제외 — 가격 데이터를 읽는 지도이지
     해안선을 정확히 보여주는 지도가 아니므로
  3) 등장방형(equirectangular) 투영 + 위도 보정으로 SVG 좌표계에 맞춤
하고 좌표를 소수점 1자리로 반올림해 저장한다.

출력: webapp/data/jeonbuk_geo.json
  { "viewBox": "0 0 W H", "counties": { "<county_id>": {"name": ..., "d": "<path>", "cx":, "cy":} } }

실행: python build_geo.py [원본 geojson 경로]
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "webapp" / "data" / "jeonbuk_geo.json"

# 이 데이터셋의 전라북도 시군구 코드 → 프로젝트 county_id
CODE_TO_ID = {
    "35011": "jeonju", "35012": "jeonju",   # 완산구 + 덕진구 → 전주시
    "35020": "gunsan", "35030": "iksan", "35040": "jeongeup", "35050": "namwon",
    "35060": "gimje", "35310": "wanju", "35320": "jinan", "35330": "muju",
    "35340": "jangsu", "35350": "imsil", "35360": "sunchang", "35370": "gochang",
    "35380": "buan",
}
ID_TO_NAME = {
    "jeonju": "전주시", "gunsan": "군산시", "iksan": "익산시", "jeongeup": "정읍시",
    "namwon": "남원시", "gimje": "김제시", "wanju": "완주군", "jinan": "진안군",
    "muju": "무주군", "jangsu": "장수군", "imsil": "임실군", "sunchang": "순창군",
    "gochang": "고창군", "buan": "부안군",
}

W, H = 760.0, 640.0          # SVG 논리 크기 (전북은 세로보다 가로가 넓다)
PAD = 14.0
MIN_AREA_RATIO = 0.012        # 가장 큰 조각 대비 이 비율 미만인 섬은 버림


def perp_dist(p, a, b) -> float:
    (x, y), (x1, y1), (x2, y2) = p, a, b
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(x - x1, y - y1)
    t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))


def simplify(pts: list, eps: float) -> list:
    """Douglas-Peucker. 재귀 대신 스택으로 — 점이 많아 재귀 한도에 걸릴 수 있다."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        dmax, idx = 0.0, i
        for k in range(i + 1, j):
            d = perp_dist(pts[k], pts[i], pts[j])
            if d > dmax:
                dmax, idx = d, k
        if dmax > eps:
            keep[idx] = True
            stack.append((i, idx))
            stack.append((idx, j))
    return [p for p, k in zip(pts, keep) if k]


def ring_area(ring: list) -> float:
    s = 0.0
    for i in range(len(ring) - 1):
        s += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
    return abs(s) / 2.0


def point_in_ring(x: float, y: float, ring: list) -> bool:
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) / (y2 - y1) * (x2 - x1)
            if x < xin:
                inside = not inside
    return inside


def label_point(ring: list, steps: int = 42) -> tuple:
    """라벨 위치 = 폴리곤 내부에서 경계로부터 가장 먼 점(pole of inaccessibility 근사).
    완주군처럼 전주시를 감싸는 오목한 모양은 무게중심이 도형 밖(=남의 시군 안)으로
    떨어지므로 무게중심을 쓰면 안 된다."""
    xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    best, best_d = None, -1.0
    for i in range(steps):
        for j in range(steps):
            x = x0 + (x1 - x0) * (i + 0.5) / steps
            y = y0 + (y1 - y0) * (j + 0.5) / steps
            if not point_in_ring(x, y, ring):
                continue
            d = min(perp_dist((x, y), ring[k], ring[k + 1]) for k in range(len(ring) - 1))
            if d > best_d:
                best, best_d = (x, y), d
    if best is None:  # 극단적으로 얇은 도형 — 무게중심으로 대체
        return (sum(xs) / len(xs), sum(ys) / len(ys), 0.0)
    return (best[0], best[1], best_d)   # best_d = 그 점에서 경계까지 거리(=라벨 여유 공간)


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("kr_muni.json")
    if not src.exists():
        raise SystemExit(f"원본 GeoJSON을 찾을 수 없습니다: {src}")
    data = json.loads(src.read_text(encoding="utf-8"))

    # county_id별로 바깥 링(외곽선)만 모은다 — 구멍(내부 링)은 이 지도에선 불필요
    rings: dict[str, list] = {}
    for f in data["features"]:
        cid = CODE_TO_ID.get(f["properties"]["code"])
        if not cid:
            continue
        geom = f["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poly in polys:
            rings.setdefault(cid, []).append([tuple(pt) for pt in poly[0]])

    missing = set(ID_TO_NAME) - set(rings)
    if missing:
        raise SystemExit(f"누락된 시군: {missing}")

    # 버릴 섬을 먼저 걸러낸 뒤에 경계상자를 잡는다 — 나중에 지울 조각까지 넣어
    # 범위를 계산하면 지도 주위에 쓸데없는 여백이 생긴다.
    for cid, rs in rings.items():
        areas = [ring_area(r) for r in rs]
        biggest = max(areas)
        rings[cid] = [r for r, a in zip(rs, areas) if a >= biggest * MIN_AREA_RATIO]

    # 투영: 등장방형 + 평균 위도 보정(한국 위도에서 경도 1도가 위도 1도보다 짧은 것 반영)
    all_pts = [p for rs in rings.values() for r in rs for p in r]
    lon0 = min(p[0] for p in all_pts); lon1 = max(p[0] for p in all_pts)
    lat0 = min(p[1] for p in all_pts); lat1 = max(p[1] for p in all_pts)
    k = math.cos(math.radians((lat0 + lat1) / 2))
    gw, gh = (lon1 - lon0) * k, (lat1 - lat0)
    scale = min((W - 2 * PAD) / gw, (H - 2 * PAD) / gh)
    ox = (W - gw * scale) / 2
    oy = (H - gh * scale) / 2

    def project(pt):
        x = ox + (pt[0] - lon0) * k * scale
        y = oy + (lat1 - pt[1]) * scale          # 위도는 위아래 뒤집기
        return (x, y)

    out = {}
    total_pts = 0
    for cid, rs in rings.items():
        kept = [[project(p) for p in r] for r in rs]

        paths, simplified = [], []
        for r in kept:
            s = simplify(r, eps=0.9)
            if len(s) < 4:
                continue
            simplified.append(s)
            total_pts += len(s)
            paths.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in s) + "Z")

        # 라벨은 단순화된 최대 조각 기준 — 화면에 그려지는 모양과 어긋나지 않게
        main_ring = max(simplified, key=ring_area)
        lx, ly, room = label_point(main_ring)

        out[cid] = {
            "name": ID_TO_NAME[cid],
            "d": "".join(paths),
            "cx": round(lx, 1), "cy": round(ly, 1),
            # room: 라벨 자리에서 경계까지의 여유. 작은 시군(전주시 등)에 값까지 넣으면
            # 옆 시군을 침범하므로, 앱이 이 값을 보고 값 라벨을 생략한다.
            "room": round(room, 1),
            "parts": len(paths),
        }

    payload = {
        "viewBox": f"0 0 {W:.0f} {H:.0f}",
        "source": "통계청(KOSTAT) 2018 시군구 경계 / southkorea-maps",
        "counties": out,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
    print(f"저장 완료: {OUT_PATH} ({OUT_PATH.stat().st_size/1024:.0f} KB, "
          f"{len(out)}개 시군, 단순화 후 {total_pts}점)")


if __name__ == "__main__":
    main()
