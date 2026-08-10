# -*- coding: utf-8 -*-
"""
check_sources.py — 소스 레이어 단계 검증 하니스

용도
----
- 오프라인(키 없음): 모든 소스가 폴백/None으로 떨어지는지 + 가격 합성폴백 동작 확인.
- 로컬(키 세팅): 각 소스가 실데이터를 반환하는지 크로스워크 전체로 점검.
- 엔진 배선 참조: engine.py 의 `_*_real` 슬롯에서 아래 load_* 를 그대로 호출하면 됨.

실행
----
    python check_sources.py
    # 실검증: export KAMIS_CERT_KEY=... KAMIS_CERT_ID=... DATA_GO_KR_KEY=... \
    #                KOSIS_KEY=... BOK_ECOS_KEY=... INCOME_UDDI=uddi:... 후 실행
"""

from __future__ import annotations
import sources as S


PRICE_WIN = ("2024-01-01", "2024-03-31")
ASOS_WIN  = ("20240101", "20240131")     # YYYYMMDD
YM_WIN    = ("202401", "202403")         # YYYYMM


def _mark(df) -> str:
    """로더 결과 → 표기."""
    if df is None:
        return "· 미확정/폴백"
    try:
        n = len(df)
    except TypeError:
        return "? 형식이상"
    return f"✔ 실데이터 {n}행" if n else "· 빈응답"


def main():
    crops = list(S.crop_xwalk().index)
    regions = list(S.region_xwalk().index)
    c0, r0 = crops[0], regions[0]

    print("=" * 60)
    print("소스 상태(키/확정도)")
    print("=" * 60)
    print(S.status_report().to_string(index=False))

    print("\n" + "=" * 60)
    print(f"로더 점검 — 대표 조합 (crop={c0}, region={r0})")
    print("=" * 60)
    checks = [
        ("price(KAMIS)",  lambda: S.load_prices(c0, *PRICE_WIN)),
        ("income",        lambda: S.load_income(c0)),
        ("suit(흙토람)",   lambda: S.load_suit(r0, c0)),
        ("area(KOSIS)",   lambda: S.load_area(r0, c0)),
        ("weather(ASOS)", lambda: S.load_weather(r0, *ASOS_WIN)),
        ("gdd",           lambda: S.load_gdd(r0)),
        ("macro(fx_usd)", lambda: S.load_macro("fx_usd", ASOS_WIN[0], ASOS_WIN[1])),
        ("import(관세)",   lambda: S.load_import(c0, *YM_WIN)),
    ]
    for name, fn in checks:
        try:
            res = fn()
        except Exception as e:
            print(f"  {name:16s} ✗ 예외: {type(e).__name__}: {e}")
            continue
        src = ""
        if res is not None and hasattr(res, "attrs"):
            src = f"  [{res.attrs.get('source','')}]" if res.attrs.get("source") else ""
        print(f"  {name:16s} {_mark(res)}{src}")

    print("\n" + "=" * 60)
    print("가격 소스 매트릭스 — 작목별 real/synthetic")
    print("=" * 60)
    real = synth = 0
    for c in crops:
        d = S.load_prices(c, *PRICE_WIN)
        s = d.attrs.get("source", "")
        real += (s == "kamis"); synth += (s == "synthetic")
        print(f"  {c:12s} {s}")
    print(f"\n  요약: KAMIS 실데이터 {real} · 합성폴백 {synth} (총 {len(crops)})")

    print("\n판독:")
    print("  · 오프라인/키없음 → 전부 폴백·미확정이 정상.")
    print("  · 로컬+키 → CONFIRMED 소스가 ✔ 로 바뀌어야 함. VERIFY는 uddi/tblId/rda_spot 채운 뒤.")


if __name__ == "__main__":
    main()
