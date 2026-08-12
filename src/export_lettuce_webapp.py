# -*- coding: utf-8 -*-
"""export_lettuce_webapp.py — 웹앱용 JSON 생성. 시군 -> 읍면 2단계 + 품종 + 예측.

────────────────────────────────────────────────────────────────
만드는 것
────────────────────────────────────────────────────────────────
  시군 14개    주간 평균/최저/최고/물량, 품종 구성, 예측(4주), 신뢰도
  읍면 55개    같은 항목. 관측 100주 이상만(물량 100% 커버)
  랭킹         선택한 주에 어느 읍면이 최고가·최저가였는지

주간 최고/최저는 **그 주 안의 일별 물량가중가**의 최대·최소다. 주 평균 하나만
보여주면 "그 주에 얼마까지 받았나"를 알 수 없어서, 농가 관점에서 폭을 같이 낸다.

────────────────────────────────────────────────────────────────
예측의 정직한 한계 (UI에 반드시 표시)
────────────────────────────────────────────────────────────────
검증된 것은 **h=1주**뿐이다. 지평별 개선폭(주차평균 대비):

    1주 +7.65%p (6/6 전승)   2주 +1.50%p   4주 +0.32%p

2주부터는 주차평균과 거의 같아진다. 그래서 4주까지만 내보내되
`reliable_weeks=1`을 함께 실어 UI가 2주 이후를 흐리게 표시하도록 한다.

읍면 예측은 표본이 얇을수록 불안정하므로, 단위별 walk-forward MAPE를 같이 실어
신뢰도를 노출한다. CV가 주차평균을 못 이기는 단위는 `beats_baseline=false`로 표시.

[실행] python export_lettuce_webapp.py
"""
from __future__ import annotations

import json
import re
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

import lettuce_weekly as WK
from scrape_lettuce_daily import (MAIN_VARIETIES, JJONG_VARIETIES, THIN_VARIETIES,
                                  EXCLUDE_FROM_MAIN, MARKETS)
from scrape_supplementary_markets import SUPP_MARKETS

_ROOT = Path(__file__).resolve().parent.parent
RAW = _ROOT / "data" / "raw"
WEB = _ROOT / "webapp" / "data"
WEB.mkdir(parents=True, exist_ok=True)

MIN_WEEKS_EUP = 100          # 읍면 채택 기준 (55개, 물량 100%)
FORECAST_WEEKS = 4
RELIABLE_WEEKS = 1           # 검증된 지평

COUNTY_ID = {
    "전주시": "jeonju", "군산시": "gunsan", "익산시": "iksan", "정읍시": "jeongeup",
    "남원시": "namwon", "김제시": "gimje", "완주군": "wanju", "진안군": "jinan",
    "무주군": "muju", "장수군": "jangsu", "임실군": "imsil", "순창군": "sunchang",
    "고창군": "gochang", "부안군": "buan",
}
_SIDO_PRE = re.compile(r"^전(?:북특별자치도|라북도|북)\s*")


def extract_eup(plor: str, county: str) -> str:
    """산지 표기에서 시군 **다음 단계를 적힌 그대로** 뽑는다.

    라벨을 지어내지 않는다. 실제 자료가 이렇게 들어온다:

        전북특별자치도 남원시 금지면 귀석리        -> 금지면
        전북특별자치도 전주시 덕진구 송천동2가      -> 송천동2가   (구는 건너뜀)
        전북특별자치도 남원시 남원우체국사서함      -> 남원우체국사서함
        전북특별자치도 익산시                    -> 익산시      (시군까지만 적힘)

    마지막 경우는 출하자가 주소를 시군까지만 적은 것이다. 그 사실 자체가 정보이므로
    '미기재' 같은 말로 바꾸지 않고 시군명 그대로 둔다. 전북산 물량의 약 42%가
    여기 해당하고 그 3분의 2가 익산이다 — 자료의 한계지 우리가 만든 값이 아니다.
    """
    if not isinstance(plor, str):
        return county
    s = _SIDO_PRE.sub("", plor).strip()
    rest = s[len(county):].strip() if s.startswith(county) else s
    if not rest:
        return county
    toks = rest.split()
    # 전주시만 자치구가 한 단계 더 있다
    if toks[0].endswith("구") and len(toks) > 1:
        toks = toks[1:]
    return toks[0]


def _wavg(g, p="price_kg", q="qty_kg"):
    x = g[[p, q]].dropna()
    t = x[q].sum()
    return (x[p] * x[q]).sum() / t if t else np.nan


def load() -> pd.DataFrame:
    d = pd.read_csv(RAW / "lettuce_daily_raw.csv",
                    dtype={"market_cd": str, "plor_cd": str}, low_memory=False)
    d = d[d["county"].notna()].copy()
    d["date"] = pd.to_datetime(d["date"], format="mixed")
    d["wk"] = d["date"].dt.to_period("W")
    d["eup"] = [extract_eup(p, c) for p, c in zip(d["plor_nm"], d["county"])]
    return d


def daily_then_weekly(g: pd.DataFrame) -> pd.DataFrame:
    """일별 물량가중가를 먼저 만들고, 그 위에서 주간 평균/최저/최고를 낸다.

    바로 주간 가중평균만 내면 '그 주 안의 변동폭'이 사라진다. 농가는 폭을 알아야
    출하일을 고를 수 있으므로 일별을 거친다.
    """
    main = g[g["variety"].isin(MAIN_VARIETIES)]
    if main.empty:
        return pd.DataFrame()
    rows = []
    for dt_, dg in main.groupby("date"):
        p = _wavg(dg)
        if np.isfinite(p):
            i = dg["price"].idxmax()
            rows.append({"date": dt_, "wk": dg["wk"].iloc[0], "p": p,
                         "q": dg["qty_kg"].sum(),
                         "bh": float(dg.loc[i, "price"]),      # 그날 최고 상자단가
                         "bkg": float(dg.loc[i, "unit_qty"])})  # 그 상자의 무게
    if not rows:
        return pd.DataFrame()
    dd = pd.DataFrame(rows)
    out = dd.groupby("wk").apply(lambda x: pd.Series({
        "avg": np.average(x["p"], weights=x["q"]) if x["q"].sum() else x["p"].mean(),
        "lo": x["p"].min(), "hi": x["p"].max(),
        "qty": x["q"].sum(), "ndays": len(x),
        # 상자단가도 같이 낸다. 농가는 상자 단위로 거래하고, 실제로 4kg 상자가
        # 13만원에 낙찰된 적이 있다(2024-10). 원/kg만 보여주면 "10만원 넘은 적
        # 있는데 왜 3만원이냐"는 오독이 생긴다.
        "box_hi": x["bh"].max(), "box_kg": x.loc[x["bh"].idxmax(), "bkg"],
    }), include_groups=False).reset_index()
    return out


def variety_mix(g: pd.DataFrame) -> dict:
    """품종 구성 + 품종별 평균가. 적/청 지역 분화, 쫑상추 편재를 보여준다."""
    tot = g["qty_kg"].sum()
    if not tot:
        return {}
    out = {}
    for v, vg in g.groupby("variety"):
        share = vg["qty_kg"].sum() / tot * 100
        if share < 0.3:
            continue
        out[str(v)] = {"share": round(share, 1), "price": round(_wavg(vg) or 0)}
    return dict(sorted(out.items(), key=lambda x: -x[1]["share"]))


def make_panel(wkly: pd.DataFrame) -> pd.DataFrame:
    """주간 시계열 -> lettuce_weekly와 같은 피처 구조."""
    p = wkly.rename(columns={"avg": "price"}).copy()
    p = p.sort_values("wk").reset_index(drop=True)
    p["year"] = p["wk"].dt.year
    p["woy"] = p["wk"].dt.week
    p["woy_sin"] = np.sin(2 * np.pi * p["woy"] / 52)
    p["woy_cos"] = np.cos(2 * np.pi * p["woy"] / 52)
    p["woy_sin2"] = np.sin(4 * np.pi * p["woy"] / 52)
    p["woy_cos2"] = np.cos(4 * np.pi * p["woy"] / 52)
    h = 1
    p["lag_h"] = p["price"].shift(h)
    p["lag_h2"] = p["price"].shift(h + 1)
    p["lag_h4"] = p["price"].shift(h + 3)
    p["lag52"] = p["price"].shift(52)
    p["roll4"] = p["price"].shift(h).rolling(4).mean()
    return p


COLS = ["woy_sin", "woy_cos", "woy_sin2", "woy_cos2",
        "lag_h", "lag_h2", "lag_h4", "lag52", "roll4"]


def reliability(p: pd.DataFrame) -> dict:
    """단위별 walk-forward 성적. 주차평균을 못 이기면 UI에 경고를 띄운다."""
    try:
        r = WK.walk_forward(p, COLS)
    except Exception:
        return {"cv_mape": None, "baseline": None, "beats": False, "folds": 0}
    if r.empty:
        return {"cv_mape": None, "baseline": None, "beats": False, "folds": 0}
    return {"cv_mape": round(float(r["model"].mean()), 1),
            "baseline": round(float(r["baseline"].mean()), 1),
            "beats": bool(r["model"].mean() < r["baseline"].mean()),
            "folds": f"{int((r['model'] < r['baseline']).sum())}/{len(r)}"}


def forecast(p: pd.DataFrame, n: int = FORECAST_WEEKS) -> list:
    """재귀 다단계 예측 + 잔차 기반 구간. 단계마다 sqrt(k)로 넓힌다."""
    tr = p.dropna(subset=["price"])
    if len(tr) < WK.MIN_TRAIN:
        return []
    a, b = WK.tune(tr, COLS)
    # 학습구간 out-of-sample 잔차로 sigma (in-sample은 과소평가)
    res = []
    yrs = sorted(tr["year"].unique())
    for y in yrs[1:]:
        itr = tr[tr["year"] < y]
        ite = tr[tr["year"] == y]
        if len(itr) < WK.MIN_TRAIN or ite.empty:
            continue
        ia, ib = WK.tune(itr, COLS)
        ip = WK.fit_predict(itr, ite, COLS, ia, ib)
        res.extend(np.log(ite["price"].values) - np.log(ip))
    sigma = float(np.std(res)) if len(res) > 20 else 0.30

    hist = list(tr["price"].values)
    last_wk = tr["wk"].iloc[-1]
    out = []
    for k in range(1, n + 1):
        wk = last_wk + k
        row = {
            "woy_sin": np.sin(2 * np.pi * wk.week / 52),
            "woy_cos": np.cos(2 * np.pi * wk.week / 52),
            "woy_sin2": np.sin(4 * np.pi * wk.week / 52),
            "woy_cos2": np.cos(4 * np.pi * wk.week / 52),
            "lag_h": hist[-1], "lag_h2": hist[-2] if len(hist) > 1 else hist[-1],
            "lag_h4": hist[-4] if len(hist) > 3 else hist[-1],
            "lag52": hist[-52] if len(hist) > 51 else np.nan,
            "roll4": float(np.mean(hist[-4:])),
        }
        te = pd.DataFrame([row])
        te["wk"] = wk
        te["woy"] = wk.week
        pred = float(WK.fit_predict(tr, te, COLS, a, b)[0])
        hist.append(pred)
        z = 1.2816 * sigma * np.sqrt(k)          # 80% 구간, 재귀 단계로 확대
        out.append({"wk": str(wk.start_time.date()), "p": round(pred),
                    "lo": round(pred * np.exp(-z)), "hi": round(pred * np.exp(z)),
                    "reliable": k <= RELIABLE_WEEKS})
    return out


def pack(wkly: pd.DataFrame) -> list:
    """[주시작일, 평균원/kg, 최저원/kg, 최고원/kg, 물량t, 거래일, 최고상자단가, 상자kg]"""
    return [[str(r.wk.start_time.date()), round(r.avg), round(r.lo), round(r.hi),
             round(r.qty / 1000, 1), int(r.ndays),
             round(r.box_hi), round(r.box_kg, 1)] for r in wkly.itertuples()]


def main() -> None:
    d = load()
    print(f"원자료 {len(d):,}행, 시군 {d['county'].nunique()}개")

    counties = {}
    for cname, cg in d.groupby("county"):
        cid = COUNTY_ID.get(cname)
        if cid is None:
            continue
        cw = daily_then_weekly(cg)
        if cw.empty or len(cw) < 60:
            continue
        cp = make_panel(cw)
        eups = {}
        for ename, eg in cg.groupby("eup"):
            ew = daily_then_weekly(eg)
            if len(ew) < MIN_WEEKS_EUP:
                continue
            ep = make_panel(ew)
            eups[str(ename)] = {
                "weekly": pack(ew),
                "variety": variety_mix(eg),
                "qty_t": round(eg["qty_kg"].sum() / 1000),
                # 이름이 시군명과 같으면 주소가 시군까지만 적힌 것이다.
                # 실제 거래지만 '어느 읍면인지'는 모르므로 최고·최저 순위에서만 뺀다.
                "unassigned": bool(ename == cname),
                "reliability": reliability(ep),
                "forecast": forecast(ep),
            }
        counties[cid] = {
            "name": cname,
            "weekly": pack(cw),
            "variety": variety_mix(cg),
            "qty_t": round(cg["qty_kg"].sum() / 1000),
            "reliability": reliability(cp),
            "forecast": forecast(cp),
            "eups": dict(sorted(eups.items(), key=lambda x: -x[1]["qty_t"])),
        }
        print(f"  {cname:<7} 주 {len(cw):>3}  읍면 {len(eups):>2}개  "
              f"CV {counties[cid]['reliability']['cv_mape']}%")

    geo = json.loads((WEB / "jeonbuk_geo.json").read_text(encoding="utf-8"))
    out = {
        "meta": {
            "crop": "상추",
            "built": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
            "period": [str(d["wk"].min().start_time.date()),
                       str(d["wk"].max().end_time.date())],
            # d는 전북산만 남긴 것이라 nunique는 '전북산이 거래된 시장 수'다.
            # 조사 대상 수(32)와 다르므로 둘을 구분해 싣는다.
            "markets_with_jeonbuk": int(d["market_cd"].nunique()),
            "markets_surveyed": len(MARKETS) + len(SUPP_MARKETS),
            "rows": int(len(d)),
            "target": (f"주력 {len(MAIN_VARIETIES)}품종 물량가중 원/kg "
                       f"({'·'.join(sorted(EXCLUDE_FROM_MAIN))} 제외)"),
            "unit_note": ("모든 가격은 **원/kg**이다. 도매시장 원자료는 상자단가라 "
                          "상자무게(unit_qty)로 나눠 환산했다. 같은 거래라도 4kg 상자가 "
                          "13만원에 낙찰되면 상자단가 130,000원 = 32,500원/kg이다. "
                          "표에 최고 상자단가를 함께 표시한다."),
            "reliable_weeks": RELIABLE_WEEKS,
            "forecast_weeks": FORECAST_WEEKS,
            "horizon_note": ("검증된 지평은 1주뿐. 주차평균 대비 개선폭이 "
                             "1주 +7.65%p / 2주 +1.50%p / 4주 +0.32%p로 급락한다."),
            "weekly_cols": ["주시작일", "평균원/kg", "최저원/kg", "최고원/kg",
                            "물량t", "거래일", "최고상자단가원", "그상자kg"],
            "unit_note": ("가격은 모두 원/kg. 원자료는 상자단가라 상자무게로 나눴다. "
                          "4kg 상자 13만원 = 32,500원/kg."),
        },
        "geo": geo,
        "counties": counties,
    }
    p = WEB / "lettuce_app.json"
    p.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")),
                 encoding="utf-8")
    n_eup = sum(len(c["eups"]) for c in counties.values())
    print(f"\n저장: {p.name}  ({p.stat().st_size/1024/1024:.2f}MB)")
    print(f"  시군 {len(counties)}개 / 읍면 {n_eup}개")


if __name__ == "__main__":
    main()
