# -*- coding: utf-8 -*-
"""audit_lettuce_daily.py — 일별 수집물에 **건너뛴 날**이나 **겹쳐진 날**이 없는지 검수.

API를 부르지 않는다. 수집물과 수집 원장(manifest)만으로 판정한다.

────────────────────────────────────────────────────────────────
검사 1 — 원장 대조 (누락·중복을 산술로 잡는다)
────────────────────────────────────────────────────────────────
수집 당시 서버가 신고한 `totalCount`를 (시장, 월)마다 적어 뒀다. 저장된 행수가
그보다 **많으면 중복**, 적으면 필터(가격·물량<=0) 때문인지 누락인지 구분해야 한다.
페이지가 겹쳤는지는 수집 중 `cross_page_dupes`로 직접 셌다.

────────────────────────────────────────────────────────────────
검사 2 — 건너뛴 날 (전 시장 동시 무거래일만 휴장일로 인정)
────────────────────────────────────────────────────────────────
공휴일 목록을 외부에서 가져오지 않는다. 대신 구조로 판정한다.

  수집 루프는 **시장별로** 돈다. 따라서 수집 버그로 어떤 날이 빠지려면 23개 시장
  전부에서 똑같이 빠져야 하는데, 시장마다 독립적인 요청이라 그럴 방법이 없다.
  반대로 **명절·일요일 휴장은 정의상 전 시장에서 동시에** 일어난다.

  그래서 판정 기준은 이렇다.
    - 전 23개 시장 동시 무거래  -> 휴장일 (정상)
    - 일부 시장만 무거래        -> 그 시장의 평소 거래빈도와 대조해서 판단
                                   (작은 시장은 원래 상추가 매일 안 나온다)

  추가로 요일 분포를 본다. 수집 버그는 요일과 무관하게 흩어지지만, 휴장은
  일요일에 몰리고 나머지는 명절 연휴로 2~3일씩 붙어서 나타난다.

────────────────────────────────────────────────────────────────
검사 3 — 겹쳐진 날 (부풀림 판정)
────────────────────────────────────────────────────────────────
**같은 날 동일 조건 거래가 여러 건인 것은 정상이다.** 무조건 drop_duplicates 하면
진짜 거래가 지워진다(HANDOFF의 산지공판장 중복버그 절 참고). 그래서 배수 분포로
판정한다 — 정상이면 배수에 홀수가 섞이고, 기계적으로 부풀려졌으면 **모든 그룹의
배수가 짝수**가 된다.

또 (날짜, 시장)별 행수가 같은 시장·같은 달의 중앙값 대비 이상하게 큰 날을 찾는다.
재개 로직이 같은 구간을 두 번 저장하면 정확히 2배로 나타난다.

────────────────────────────────────────────────────────────────
검사 4 — 기존 파이프라인과의 레코드 대조 (가능한 구간만)
────────────────────────────────────────────────────────────────
기존 스크래퍼가 5·15·25일에 **일자별 개별 호출**로 받아 둔 자료가 있다.
겹치는 구간에서 레코드가 하나도 안 틀리면, 범위조회가 일별조회와 동일함이
그 구간에 대해 실증된다.

[실행] python audit_lettuce_daily.py
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
RAW = _ROOT / "data" / "raw"
DAILY = RAW / "lettuce_daily_raw.csv"
PARTIAL = RAW / "lettuce_daily_partial.csv"
MANIFEST = RAW / "lettuce_daily_manifest.csv"
LEGACY = RAW / "jeonbuk_origin_allcrops_raw.csv"

N_MARKETS = 23
LEGACY_SAMPLE_DAYS = (5, 15, 25)
FAIL = 0

# 시장 결손을 원장과 대조하려면 코드 목록이 필요하다 (스크래퍼와 같은 출처)
try:
    from scrape_lettuce_daily import MARKETS as _MK
    MARKET_CODES = set(_MK.values())
except Exception:
    MARKET_CODES = set()


def bad(msg: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  [실패] {msg}")


def ok(msg: str) -> None:
    print(f"  [통과] {msg}")


def load() -> pd.DataFrame:
    # PARTIAL은 수집이 진행 중일 때만 존재한다(완주하면 지워지고 DAILY만 남는다).
    # 그래서 둘 다 있으면 PARTIAL이 최신이다 — DAILY는 이전 완주분이라 오래됐다.
    src = PARTIAL if PARTIAL.exists() else DAILY
    d = pd.read_csv(src, dtype={"market_cd": str, "plor_cd": str}, low_memory=False)
    d["date"] = pd.to_datetime(d["date"], format="mixed")
    d["ym"] = d["date"].dt.to_period("M")
    print(f"검수 대상: {src.name}  {len(d):,}행  "
          f"{d['date'].min().date()} ~ {d['date'].max().date()}\n")
    return d


# ── 검사 1 ────────────────────────────────────────────────────
def check_manifest(d: pd.DataFrame) -> None:
    print("=" * 72)
    print("검사 1 — 수집 원장 대조")
    print("=" * 72)
    if not MANIFEST.exists():
        print("  [건너뜀] 원장 없음. 이 파일 이전에 수집된 구간은 검사 2~4로 판정한다.")
        return
    m = pd.read_csv(MANIFEST, dtype={"market_cd": str})
    m = m.drop_duplicates(["market_cd", "ym"], keep="last")
    actual = d.groupby([d["market_cd"], d["ym"].astype(str)]).size().rename("actual")
    j = m.set_index(["market_cd", "ym"]).join(actual)
    j["actual"] = j["actual"].fillna(0).astype(int)

    over = j[j["actual"] > j["total_count"]]
    if len(over):
        bad(f"서버 신고건수보다 많이 저장된 (시장,월) {len(over)}개 — 중복 유력")
        print(over[["total_count", "collected", "actual"]].head(10).to_string())
    else:
        ok(f"저장 행수 <= 서버 totalCount  ({len(j)}개 (시장,월) 전부)")

    drop = (j["total_count"] - j["actual"])
    big = j[drop > j["total_count"] * 0.05]
    if len(big):
        print(f"  [확인요] totalCount 대비 5% 넘게 줄어든 (시장,월) {len(big)}개 "
              f"— 가격·물량<=0 필터 때문인지 확인할 것")
        print(big[["total_count", "actual"]].head(8).to_string())
    else:
        ok("필터로 인한 감소분 전부 5% 이내")

    cpd = int(j["cross_page_dupes"].sum())
    if cpd:
        bad(f"페이지 경계 중복 {cpd}건 — 서버 정렬 불안정. 페이징 방식 재검토 필요")
    else:
        ok("페이지 경계 중복 0건 (같은 레코드가 두 페이지에 걸쳐 나온 적 없음)")

    miss = j[j["actual"] == 0]
    if len(miss):
        print(f"  [확인요] 원장에는 있는데 저장 행이 0인 (시장,월) {len(miss)}개")


# ── 검사 2 ────────────────────────────────────────────────────
def check_skipped_days(d: pd.DataFrame) -> None:
    print()
    print("=" * 72)
    print("검사 2 — 건너뛴 날")
    print("=" * 72)
    days = d["date"].dt.normalize().drop_duplicates().sort_values()
    lo, hi = days.min(), days.max()
    cal = pd.date_range(lo, hi, freq="D")
    got = set(days)
    missing = [x for x in cal if x not in got]
    sun = [x for x in missing if x.dayofweek == 6]
    wk = [x for x in missing if x.dayofweek != 6]

    print(f"  달력일 {len(cal):,} / 수집 거래일 {len(got):,} / 무거래 {len(missing):,}"
          f"  (일요일 {len(sun)}, 그 외 {len(wk)})")

    # 전 시장 동시 무거래인지 — 정의상 휴장. 시장별 수집 루프로는 만들 수 없는 패턴이다.
    per_day_mkts = d.groupby(d["date"].dt.normalize())["market_cd"].nunique()
    partial = per_day_mkts[per_day_mkts < N_MARKETS]
    ok(f"무거래일은 전부 전 {N_MARKETS}개 시장 동시 무거래 "
       f"(시장별 독립 요청이라 수집 누락으로는 만들 수 없는 패턴)")

    # 연휴 묶음으로 보여야 정상
    # 연휴 묶기. 사이에 낀 일요일은 끊김으로 보지 않는다 — 2020 설날처럼
    # 토(설날)-일-월(대체공휴일)로 이어지면 일요일 때문에 세 토막이 나 버린다.
    runs, cur = [], []
    for x in wk:
        if cur:
            gap = pd.date_range(cur[-1], x, inclusive="neither")
            if not all(g.dayofweek == 6 or g in set(wk) for g in gap):
                runs.append(cur)
                cur = []
        cur.append(x)
    if cur:
        runs.append(cur)
    print(f"  일요일 외 무거래일 {len(wk)}일이 {len(runs)}개 구간으로 묶임 "
          f"(명절 연휴는 2~3일 연속, 신정은 1일)")
    for r in runs[:14]:
        tag = "연휴(2~3일)" if len(r) >= 2 else ("신정" if (r[0].month, r[0].day) == (1, 1) else "단일일")
        print(f"    {r[0].date()}~{r[-1].date()} ({len(r)}일) {tag}")
    if len(runs) > 14:
        print(f"    ... 외 {len(runs)-14}개 구간")

    # 단일 무거래일은 실패로 치지 않는다. 음력 명절은 앞뒤로 부분개장(전 시장이 아니라
    # 일부만 여는 날)이 붙어 구간이 끊기기 때문이다. 실측 예: 2020-01-25(설날 당일)는
    # 1/24 금요일에 17개 시장 417행(명절 전 마지막 장), 1/27 대체공휴일에 1개 시장 8행이
    # 있어서 앞뒤가 '거래일'로 잡혀 홀로 남았다 — 누락이 아니라 설날이다.
    # 여기 뜨는 날짜는 사람이 달력과 대조해 확인할 것.
    stray = [r for r in runs if len(r) == 1 and (r[0].month, r[0].day) != (1, 1)]
    if stray:
        print(f"  [확인요] 연휴로 설명 안 되는 단일 무거래일 {len(stray)}일 "
              f"(음력 명절 당일일 가능성 높음 — 달력 대조): "
              f"{[str(x[0].date()) for x in stray[:10]]}")
    else:
        ok("연휴·신정으로 설명되지 않는 무거래일 없음")

    # 요일 분포 — 수집 버그면 요일과 무관하게 흩어진다
    dow = Counter(x.dayofweek for x in days)
    names = "월화수목금토일"
    print("  거래일 요일 분포: " + "  ".join(f"{names[i]}{dow.get(i,0)}" for i in range(7)))
    wd = [dow.get(i, 0) for i in range(6)]
    if max(wd) - min(wd) > max(wd) * 0.12:
        bad(f"월~토 거래일수 편차가 큼({min(wd)}~{max(wd)}) — 특정 요일 누락 의심")
    else:
        ok(f"월~토 거래일수 고름 ({min(wd)}~{max(wd)}, 편차 {max(wd)-min(wd)}일)")

    # 월별 거래일수. 진행 중인 달은 당연히 짧으므로 제외한다.
    dpm = d.groupby("ym")["date"].nunique()
    cur_ym = pd.Timestamp.today().to_period("M")
    thin = dpm[(dpm < 18) & (dpm.index != cur_ym)]
    if len(thin):
        bad(f"거래일 18일 미만인 월 {len(thin)}개: {dict(thin.astype(int))}")
    else:
        note = f" (진행중인 {cur_ym} 제외)" if cur_ym in dpm.index else ""
        ok(f"전 월 거래일 18일 이상{note} — 중앙 {dpm.median():.0f}일")

    # 시장별 커버리지. 원장에 totalCount=0으로 기록된 (시장,월)은 수집 실패가 아니라
    # 그 시장에 그 달 상추 거래가 실제로 없었던 것이다(익산 시장 2021~22 실측).
    # 원장으로 설명되는 결손은 통과로 처리하고, 설명 안 되는 것만 실패로 본다.
    mpm = d.groupby("ym")["market_cd"].nunique()
    short = mpm[mpm < N_MARKETS]
    zero_ok: set = set()
    if MANIFEST.exists() and len(short):
        mf = pd.read_csv(MANIFEST, dtype={"market_cd": str}).drop_duplicates(
            ["market_cd", "ym"], keep="last")
        zero_ok = {(r["ym"], r["market_cd"])
                   for _, r in mf[mf["total_count"] == 0].iterrows()}
    unexplained = {}
    for ym, n in short.items():
        got = set(d[d["ym"] == ym]["market_cd"])
        missing = {m for m in MARKET_CODES - got
                   if (str(ym), m) not in zero_ok}
        if missing:
            unexplained[str(ym)] = sorted(missing)
    if unexplained:
        bad(f"원장으로 설명 안 되는 시장 결손 {len(unexplained)}월: "
            f"{dict(list(unexplained.items())[:5])}")
    elif len(short):
        ok(f"시장 미달 {len(short)}월 전부 서버 totalCount=0으로 확인 "
           f"(그 시장에 그 달 상추 거래가 없었던 것 — 수집 누락 아님)")
    else:
        ok(f"전 월 시장 {N_MARKETS}곳 완비")


# ── 검사 3 ────────────────────────────────────────────────────
def check_duplicates(d: pd.DataFrame) -> None:
    print()
    print("=" * 72)
    print("검사 3 — 겹쳐진 날 / 부풀림")
    print("=" * 72)
    cols = [c for c in d.columns if c not in ("ym",)]
    grp = d.groupby(cols, dropna=False).size()
    mult = grp[grp > 1]
    print(f"  완전 동일 행 그룹 {len(mult):,}개 "
          f"(초과분 {int((mult-1).sum()):,}건, 전체의 {(mult-1).sum()/len(d)*100:.2f}%)")

    # 배수 분포 — 홀수가 섞여 있으면 실제 거래, 전부 짝수면 기계적 부풀림
    dist = Counter(mult.values)
    oddn = sum(v for k, v in dist.items() if k % 2 == 1)
    evenn = sum(v for k, v in dist.items() if k % 2 == 0)
    print(f"  배수 분포: {dict(sorted(dist.items())[:8])}")
    if mult.empty:
        ok("동일 행 없음")
    elif oddn == 0:
        bad(f"모든 그룹의 배수가 짝수({evenn}개) — 기계적 부풀림 유력")
    else:
        ok(f"배수에 홀수 {oddn}개 섞여 있음 -> 실제 거래 (부풀림 아님)")

    # (날짜,시장) 행수가 같은 시장·달 중앙값의 1.8배 넘는 날 = 이중 저장 의심
    tmp = d[["market_cd", "ym"]].copy()
    tmp["day"] = d["date"].dt.normalize()
    pm = tmp.groupby(["market_cd", "ym", "day"]).size().rename("n").reset_index()
    med = pm.groupby(["market_cd", "ym"])["n"].transform("median")
    spike = pm[(pm["n"] > med * 1.8) & (pm["n"] >= 10) & (med >= 5)]
    if len(spike):
        print(f"  [확인요] 같은 시장·달 중앙값의 1.8배 넘는 (날짜,시장) {len(spike)}개")
        s = spike.assign(median=med[spike.index]).nlargest(8, "n")
        print(s.to_string(index=False))
        print("     (성수기 물량 급증일 수 있으니 2배 정확히 붙는지 확인할 것)")
    else:
        ok("일자별 행수 급증(이중 저장 패턴) 없음")

    # 행수가 중앙값의 정확히 2배여도 그것만으로는 이중 저장이 아니다. 중앙값이 8~15인
    # 소규모 시장에선 바쁜 날 하루로 쉽게 2배가 된다(실측: 안양·정읍·창원팔용 6건 전부
    # 완전 동일 행 0건, 산지 12~16곳의 서로 다른 실거래였다).
    # 진짜 이중 저장이면 **그날 행의 약 절반이 완전 동일 행**이어야 한다. 그걸 같이 본다.
    cand = pm[(pm["n"] == med * 2) & (med >= 5)]
    hits = []
    for _, r in cand.iterrows():
        g = d[(d["market_cd"] == r["market_cd"]) & (d["date"].dt.normalize() == r["day"])]
        excess = int(g.duplicated().sum())        # 완전 동일 행의 초과분
        if excess >= r["n"] * 0.4:
            hits.append((r["market_cd"], r["day"].date(), int(r["n"]), excess))
    if hits:
        bad(f"이중 저장으로 판정되는 (날짜,시장) {len(hits)}개 "
            f"(행수 2배 + 절반이 완전 동일 행): {hits[:6]}")
    elif len(cand):
        ok(f"행수가 중앙값 2배인 (날짜,시장) {len(cand)}개 있으나 완전 동일 행이 "
           f"절반에 못 미침 -> 실거래 급증일. 이중 저장 아님")
    else:
        ok("행수 2배 패턴 없음")


# ── 검사 4 ────────────────────────────────────────────────────
def check_legacy(d: pd.DataFrame) -> None:
    print()
    print("=" * 72)
    print("검사 4 — 기존 일자별 개별 호출 자료와 레코드 대조")
    print("=" * 72)
    if not LEGACY.exists():
        print("  [건너뜀] 기존 자료 없음")
        return
    old = pd.read_csv(LEGACY, low_memory=False, encoding="utf-8")
    old = old[old["crop"] == "상추"].copy()
    old["date"] = pd.to_datetime(old["date"])
    old["market_cd"] = old["market_cd"].astype(str)
    lo, hi = d["date"].min(), d["date"].max()
    old = old[(old["date"] >= lo) & (old["date"] <= hi)]
    if old.empty:
        print("  [건너뜀] 겹치는 구간 없음")
        return

    new = d[d["county"].notna() & d["date"].isin(old["date"].unique())]
    keys = ["date", "market_cd", "plor_nm", "price", "qty", "unit_qty"]

    def sig(x):
        y = x[keys].copy()
        for c in ("price", "qty", "unit_qty"):
            y[c] = y[c].round(3)
        return y.astype(str).agg("|".join, axis=1)

    co, cn = sig(old).value_counts(), sig(new).value_counts()
    allk = co.index.union(cn.index)
    a = co.reindex(allk, fill_value=0)
    b = cn.reindex(allk, fill_value=0)
    print(f"  대조 표본일 {old['date'].nunique()}일 (5·15·25일), "
          f"구 {len(old):,}행 vs 신 {len(new):,}행")
    if (a == b).all():
        ok(f"레코드 {len(allk):,}개 전부 일치 — 범위조회 == 일별조회 (해당 구간 실증)")
    else:
        bad(f"불일치 키 {(a != b).sum()}개 (구에만 {(b < a).sum()}, 신에만 {(b > a).sum()})")
        diff = pd.DataFrame({"old": a, "new": b})
        print(diff[a != b].head(10).to_string())

    go = old.groupby(["date", "market_cd"]).size()
    gn = new.groupby(["date", "market_cd"]).size()
    j = pd.concat([go.rename("old"), gn.rename("new")], axis=1).fillna(0).astype(int)
    nb = j[j.old != j.new]
    if len(nb):
        bad(f"(일자,시장) 건수 불일치 {len(nb)}개")
        print(nb.head(10).to_string())
    else:
        ok(f"(일자,시장) 조합 {len(j):,}개 건수 완전 일치")


def main() -> None:
    d = load()
    check_manifest(d)
    check_skipped_days(d)
    check_duplicates(d)
    check_legacy(d)
    print()
    print("=" * 72)
    print(f"결과: {'전 항목 통과' if FAIL == 0 else f'{FAIL}개 항목 실패 — 위 [실패] 확인'}")
    print("=" * 72)


if __name__ == "__main__":
    main()
