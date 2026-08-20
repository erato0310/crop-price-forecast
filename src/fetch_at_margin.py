# -*- coding: utf-8 -*-
"""fetch_at_margin.py — aT 유통실태조사 「품목별 유통비용」 전 품목·전 연도 수집.

────────────────────────────────────────────────────────────────
왜
────────────────────────────────────────────────────────────────
`docs/유통단계별_가격_2026-08-20.html` 6절이 상추 농가수취율을 **20% 안팎**으로
추정하면서, 출하단계 비용률에 **전 품목 평균 9.4%p**를 대입했다. 상추 개별
수치가 없어서 쓴 대리값이고, 문서에도 추정이라고 적어 뒀다.

aT는 품목별 유통비용을 **단계별(출하·도매·소매)** 로 낸다. 상추 개별 수치가
있으면 그 대리값을 실측으로 바꿀 수 있다. 이 스크립트가 그걸 받는다.

────────────────────────────────────────────────────────────────
수치의 뜻 — 분모가 소비자가격이다
────────────────────────────────────────────────────────────────
표의 모든 %는 **소비자가격 100 기준의 몫**이다. 두 갈래로 같은 합을 쪼갠다.

    비용별  계 = 직접비 + 간접비 + 이윤
    단계별  계 = 출하  + 도매   + 소매

따라서 그 해의 **농가수취율 = 100 − 계**이고,
**경락가 수준 = 100 − (도매 + 소매)** 다. 출하비용은 경락가에서 다시 빠진다.

    농가수취 ── 출하 ── [경락] ── 도매 ── 소매 ── 소비자가격 100

우리 분석의 '경락가 수준'(소매 대비 산지가 비율)과 견줄 수 있는 자리가
바로 `100 − 도매 − 소매`다. 그냥 `100 − 계`와 견주면 한 단계 어긋난다.

────────────────────────────────────────────────────────────────
주의
────────────────────────────────────────────────────────────────
- **상추는 2012년이 마지막이다.** 2013년부터 조사 품목에서 빠졌다. 2024년
  엽근채소류 조사 품목은 배추 4종·무 4종·당근·양배추뿐이다. 이건 추측이 아니라
  `--check-drop` 이 연도별 결측을 세어 확인해 준다.
- **1998~2012 중 2011과 2012 행이 완전히 동일하다.** 9개 값이 전부 같다.
  재조사 없이 이월된 것으로 보인다. 상추만이 아니라 여러 품목에서 그렇다
  (`--check-drop` 이 함께 센다). 그래서 '2012년 값'이라고 쓸 때는
  **실질적으로 2011년 조사값**일 수 있음을 함께 적어야 한다.
- 품목 목록은 **열거해서 받는다**(HANDOFF의 목록 방침). 부류는 페이지 HTML의
  `setSearchBox('NN','itemclasscode')` 에서, 품목은 `get_code_list.do` 에서
  가져온다. 코드를 손으로 적지 않는다.
- 부류마다 `가중평균`(코드 90)이라는 의사품목이 있다. 그 부류의 가중평균이고,
  **전 품목 평균이 아니다.** 전 품목 평균은 이 화면에 없다.
- 응답은 UTF-8인데 `requests`가 헤더만 보고 다르게 잡을 때가 있어 못박는다.

[실행] python fetch_at_margin.py               # 전 부류·전 품목
       python fetch_at_margin.py --check-drop  # 조사 중단 연도·이월 행 점검
"""
from __future__ import annotations

import argparse
import io
import re
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = RAW / "kamis_margin_by_item.csv"

BASE = "https://www.kamis.or.kr"
PAGE = f"{BASE}/customer/circulation/domestic/product.do"
CODES = f"{BASE}/common/get_code_list.do"
UA = {"User-Agent": "Mozilla/5.0"}
DELAY = 0.3

# 단계별 표의 열 순서. 표 헤더가 2단(비용별/단계별)이라 위치로 받는다.
COLS = ["year", "cost_total", "cost_direct", "cost_indirect", "cost_profit",
        "stage_total", "stage_ship", "stage_whole", "stage_retail"]


def get(url: str, **params) -> requests.Response:
    r = requests.get(url, params=params or None, headers=UA, timeout=60)
    r.raise_for_status()
    r.encoding = "utf-8"          # 헤더를 믿지 않는다
    return r


def list_classes() -> list[tuple[str, str]]:
    """부류 (코드, 이름) — 페이지 HTML에서 열거한다."""
    html = get(PAGE).text
    ul = re.search(r'id="ulitemclasscode".*?</ul>', html, re.S)
    if not ul:
        raise SystemExit("부류 목록을 찾지 못했습니다 — 페이지 구조가 바뀌었습니다")
    got = re.findall(
        r"setSearchBox\('(\d+)','itemclasscode'\)[^>]*>\s*([^<]+?)\s*</a>", ul.group(0))
    if not got:
        raise SystemExit("부류 코드를 뽑지 못했습니다 — 페이지 구조가 바뀌었습니다")
    return got


def list_items(class_code: str) -> list[tuple[str, str]]:
    """품목 (코드, 이름) — 코드목록 API에서 열거한다. 가중평균(90)도 그대로 둔다."""
    js = get(CODES, action="circulationItemcodeList", itemclasscode=class_code).json()
    return [(str(d["code"]), str(d["name"])) for d in js if d.get("useyn") == "Y"]


def fetch_item(class_code: str, item_code: str) -> pd.DataFrame:
    """한 품목의 연도별 유통비용. 자료가 없으면 빈 DataFrame."""
    html = get(PAGE, action="list", itemclasscode=class_code, itemcode=item_code).text
    try:
        t = pd.read_html(io.StringIO(html))[0]
    except (ValueError, IndexError):
        return pd.DataFrame()
    if t.shape[1] != len(COLS):
        return pd.DataFrame()
    t.columns = COLS
    t = t[pd.to_numeric(t["year"], errors="coerce").notna()]
    for c in COLS:
        t[c] = pd.to_numeric(t[c], errors="coerce")
    return t.reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-drop", action="store_true",
                    help="조사 중단 연도와 전년 이월(동일 행)을 점검한다")
    a = ap.parse_args()

    rows: list[pd.DataFrame] = []
    for cc, cname in list_classes():
        for ic, iname in list_items(cc):
            d = fetch_item(cc, ic)
            print(f"  {cname:<8} {iname:<8} {len(d):>3}년"
                  f"{'' if len(d) else '   (자료 없음)'}", flush=True)
            if len(d):
                d.insert(0, "item", iname)
                d.insert(0, "item_code", ic)
                d.insert(0, "item_class", cname)
                d.insert(0, "item_class_code", cc)
                rows.append(d)
            time.sleep(DELAY)

    if not rows:
        raise SystemExit("받은 자료가 없습니다")
    d = pd.concat(rows, ignore_index=True)

    # 파생값 두 개. 계산식은 docstring 참조 — 여기서 한 번만 정의한다.
    d["farm_share"] = (100 - d["stage_total"]).round(1)
    d["auction_share"] = (100 - d["stage_whole"] - d["stage_retail"]).round(1)

    d = d.sort_values(["item_class_code", "item_code", "year"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"\n저장: {OUT} ({len(d):,}행 / 품목 {d['item'].nunique()}개)")

    if a.check_drop:
        check_drop(d)

    # 상추는 이 분석의 목적이므로 항상 찍는다
    let = d[d["item"] == "상추"]
    if len(let):
        print("\n── 상추 (단위 %, 분모는 소비자가격) ──")
        print(let[["year", "stage_ship", "stage_whole", "stage_retail",
                   "stage_total", "auction_share", "farm_share"]]
              .to_string(index=False))


def check_drop(d: pd.DataFrame) -> None:
    """언제 조사에서 빠졌는지, 어느 행이 전년 이월인지."""
    print("\n── 품목별 조사 구간 ──")
    g = d.groupby(["item_class", "item"])["year"].agg(["min", "max", "size"])
    last = int(d["year"].max())
    g["중단"] = g["max"].apply(lambda y: "" if y == last else f"← {int(y)}에서 끊김")
    print(g.to_string())

    print("\n── 전년과 9개 값이 전부 같은 행 (재조사 없이 이월된 것으로 보임) ──")
    vals = ["cost_total", "cost_direct", "cost_indirect", "cost_profit",
            "stage_total", "stage_ship", "stage_whole", "stage_retail"]
    hits = []
    for (_, item), grp in d.groupby(["item_class", "item"]):
        grp = grp.sort_values("year")
        same = (grp[vals].diff().abs().sum(axis=1) == 0) & (grp["year"].diff() == 1)
        for y in grp.loc[same, "year"]:
            hits.append({"item": item, "year": int(y)})
    if hits:
        h = pd.DataFrame(hits)
        print(h.to_string(index=False))
        print(f"  총 {len(h)}건 / {h['item'].nunique()}품목")
    else:
        print("  없음")


if __name__ == "__main__":
    main()
