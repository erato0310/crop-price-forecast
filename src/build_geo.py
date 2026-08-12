# -*- coding: utf-8 -*-
"""build_geo.py — 전북 시군·읍면 경계를 웹앱용 SVG path로 변환한다.

원본: 통계청(KOSTAT) 2018 경계를 정리해 공개한 southkorea-maps 데이터셋
      https://github.com/southkorea/southkorea-maps  (kostat/2018)
        시군: skorea-municipalities-2018-geo.json
        읍면: skorea-submunicipalities-2018-geo.json
      전라북도는 코드 접두 '35'. 전주시는 완산구(35011)·덕진구(35012)로 나뉘어 있어
      하나로 합친다(우리 데이터는 시 단위이므로).

원본 그대로면 3만 점이 넘어 웹에 싣기엔 무겁다. 그래서
  1) Douglas-Peucker로 단순화(모양은 알아볼 수 있게, 점 수는 크게 줄여서)
  2) 아주 작은 섬(군산 고군산군도 등)은 제외 — 가격 데이터를 읽는 지도이지
     해안선을 정확히 보여주는 지도가 아니므로
  3) 등장방형(equirectangular) 투영 + 위도 보정으로 SVG 좌표계에 맞춤
하고 좌표를 소수점 1자리로 반올림해 저장한다.

**시군과 읍면은 반드시 같은 투영을 쓴다.** 앱이 시군 선택 시 viewBox를 그 시군
경계상자로 좁혀 확대하는데, 좌표계가 다르면 읍면이 시군 밖으로 어긋난다.
그래서 투영 파라미터는 시군 파일 하나로 잡고 읍면에 그대로 적용한다.

출력:
  webapp/data/jeonbuk_geo.json      시군 (+ 확대용 bbox)
  webapp/data/jeonbuk_eup_geo.json  시군별 읍면 (앱이 드릴다운할 때 따로 불러감)

읍면 이름은 **우리 가격자료의 산지 라벨과 대조만 하고 고쳐 붙이지 않는다.**
법정동/행정동이 다르거나(전주 송천동2가 등) 읍 승격으로 이름이 바뀐 경우
(완주 용진면→용진읍) 억지로 잇지 않고 대조표에 남긴다 — 없는 라벨을 지어내는
것보다 "지도에 없음"이라고 말하는 편이 낫다.

실행: python build_geo.py [시군 geojson] [읍면 geojson]
      (생략하면 data/raw/skorea-{municipalities,submunicipalities}-2018-geo.json)
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "webapp" / "data" / "jeonbuk_geo.json"
EUP_OUT_PATH = ROOT / "webapp" / "data" / "jeonbuk_eup_geo.json"
RAW = ROOT / "data" / "raw"
APP_JSON = ROOT / "webapp" / "data" / "lettuce_app.json"   # 이름 대조용(없으면 건너뜀)

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

# 단순화 허용오차(투영 후 SVG 단위). 읍면은 시군의 10분의 1 크기라 같은 값을 쓰면
# 작은 면이 삼각형으로 뭉개진다. 확대해서 보는 용도이므로 더 촘촘히 남긴다.
EPS_COUNTY = 0.9
EPS_EUP = 0.30


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


def collect_rings(src: Path, key_of) -> dict:
    """geojson에서 {키: [바깥 링, ...]}을 모은다. 구멍(내부 링)은 이 지도에선 불필요."""
    data = json.loads(src.read_text(encoding="utf-8"))
    rings: dict = {}
    for f in data["features"]:
        k = key_of(f["properties"])
        if not k:
            continue
        geom = f["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poly in polys:
            rings.setdefault(k, []).append([tuple(pt) for pt in poly[0]])
    return rings


def drop_islets(rings: dict) -> None:
    """조각마다 가장 큰 것 대비 너무 작은 섬을 버린다(제자리 수정)."""
    for k, rs in rings.items():
        areas = [ring_area(r) for r in rs]
        biggest = max(areas)
        rings[k] = [r for r, a in zip(rs, areas) if a >= biggest * MIN_AREA_RATIO]


def build_shape(rs, project, eps) -> tuple:
    """링 목록 -> (svg path 문자열, 단순화된 링들, 남은 점 수). 그릴 게 없으면 (None, ...)."""
    paths, simplified, npts = [], [], 0
    for r in rs:
        s = simplify([project(p) for p in r], eps=eps)
        if len(s) < 4:
            continue
        simplified.append(s)
        npts += len(s)
        paths.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in s) + "Z")
    if not paths:
        return None, [], 0
    return "".join(paths), simplified, npts


def bbox_of(simplified) -> list:
    xs = [p[0] for s in simplified for p in s]
    ys = [p[1] for s in simplified for p in s]
    return [round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)]


def audit_names(eups: dict) -> str:
    """지도 읍면 이름 vs 우리 가격자료 산지 라벨. 고쳐 붙이지 않고 대조만 한다."""
    if not APP_JSON.exists():
        return "lettuce_app.json 이 없어 이름 대조를 건너뜀"
    app = json.loads(APP_JSON.read_text(encoding="utf-8"))
    lines, tot = [], {"match": 0, "unassigned": 0, "nogeo": 0}
    qty = {"match": 0.0, "unassigned": 0.0, "nogeo": 0.0}
    for cid, c in app["counties"].items():
        have = set(eups.get(cid, {}))
        for n, e in c["eups"].items():
            q = sum(w[4] for w in e["weekly"])
            if e.get("unassigned"):
                kind = "unassigned"
            elif n in have:
                kind = "match"
            else:
                kind = "nogeo"
            tot[kind] += 1
            qty[kind] += q
            if kind != "match":
                lines.append(f"{c['name']}\t{n}\t{q:.1f}t\t"
                             + ("산지를 시군까지만 적은 묶음" if kind == "unassigned"
                                else "지도에 같은 이름 없음"))
    tq = sum(qty.values()) or 1.0
    head = (f"읍면 라벨 {sum(tot.values())}개 — 지도와 이름 일치 {tot['match']}, "
            f"시군까지만 {tot['unassigned']}, 지도에 없음 {tot['nogeo']}\n"
            f"물량 기준 — 폴리곤 있음 {qty['match']/tq*100:.1f}%, "
            f"시군까지만 {qty['unassigned']/tq*100:.1f}%, "
            f"이름 불일치 {qty['nogeo']/tq*100:.1f}%\n")
    (ROOT / "outputs").mkdir(exist_ok=True)
    (ROOT / "outputs" / "eup_geo_match.txt").write_text(
        head + "\n" + "\n".join(lines), encoding="utf-8")
    return head.strip()


def main() -> None:
    src_c = Path(sys.argv[1]) if len(sys.argv) > 1 else RAW / "skorea-municipalities-2018-geo.json"
    src_e = Path(sys.argv[2]) if len(sys.argv) > 2 else RAW / "skorea-submunicipalities-2018-geo.json"
    if not src_c.exists():
        raise SystemExit(f"시군 GeoJSON을 찾을 수 없습니다: {src_c}")

    rings = collect_rings(src_c, lambda p: CODE_TO_ID.get(p["code"]))
    missing = set(ID_TO_NAME) - set(rings)
    if missing:
        raise SystemExit(f"누락된 시군: {missing}")

    # 버릴 섬을 먼저 걸러낸 뒤에 경계상자를 잡는다 — 나중에 지울 조각까지 넣어
    # 범위를 계산하면 지도 주위에 쓸데없는 여백이 생긴다.
    drop_islets(rings)

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

    out, total_pts = {}, 0
    for cid, rs in rings.items():
        d, simplified, npts = build_shape(rs, project, EPS_COUNTY)
        total_pts += npts
        # 라벨은 단순화된 최대 조각 기준 — 화면에 그려지는 모양과 어긋나지 않게
        lx, ly, room = label_point(max(simplified, key=ring_area))
        out[cid] = {
            "name": ID_TO_NAME[cid],
            "d": d,
            "cx": round(lx, 1), "cy": round(ly, 1),
            # room: 라벨 자리에서 경계까지의 여유. 작은 시군(전주시 등)에 값까지 넣으면
            # 옆 시군을 침범하므로, 앱이 이 값을 보고 값 라벨을 생략한다.
            "room": round(room, 1),
            "parts": len(simplified),
            # bbox: 앱이 이 시군으로 확대할 때 viewBox를 여기로 좁힌다
            "bbox": bbox_of(simplified),
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

    # ── 읍면 ─────────────────────────────────────────────
    # 시군과 **같은 project()** 를 그대로 쓴다. 좌표계가 갈리면 확대했을 때 어긋난다.
    if not src_e.exists():
        print(f"읍면 GeoJSON이 없어 건너뜀: {src_e}")
        return
    erings = collect_rings(
        src_e, lambda p: ((CODE_TO_ID.get(str(p["code"])[:5]), p["name"])
                          if CODE_TO_ID.get(str(p["code"])[:5]) else None))
    drop_islets(erings)

    eups: dict = {}
    epts = 0
    for (cid, name), rs in erings.items():
        d, simplified, npts = build_shape(rs, project, EPS_EUP)
        if not d:
            continue
        epts += npts
        # 라벨 자리 탐색은 격자 해상도가 곧 비용이다. 읍면은 240개라 성글게 잡는다.
        lx, ly, room = label_point(max(simplified, key=ring_area), steps=20)
        eups.setdefault(cid, {})[name] = {
            "d": d, "cx": round(lx, 1), "cy": round(ly, 1),
            "room": round(room, 1), "parts": len(simplified),
        }

    epayload = {
        "viewBox": f"0 0 {W:.0f} {H:.0f}",
        "source": "통계청(KOSTAT) 2018 읍면동 경계 / southkorea-maps",
        "note": "시군 지도와 같은 투영. 이름은 지도 원본 그대로이며 가격자료 라벨에 맞춰 고치지 않았다.",
        "counties": {cid: {"name": ID_TO_NAME[cid], "eups": e} for cid, e in eups.items()},
    }
    EUP_OUT_PATH.write_text(json.dumps(epayload, ensure_ascii=False, separators=(",", ":")),
                            encoding="utf-8")
    print(f"저장 완료: {EUP_OUT_PATH} ({EUP_OUT_PATH.stat().st_size/1024:.0f} KB, "
          f"{sum(len(e) for e in eups.values())}개 읍면, 단순화 후 {epts}점)")
    print(audit_names(eups))


if __name__ == "__main__":
    main()
