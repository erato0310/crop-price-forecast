# -*- coding: utf-8 -*-
"""export_by_variety.py — 상위 3품종을 따로 떼어 값·예측을 낸다.

────────────────────────────────────────────────────────────────
왜
────────────────────────────────────────────────────────────────
지금까지는 주력 17품종을 물량가중으로 **합쳐서** 하나의 값으로 냈다.
그런데 농가가 심는 것은 '상추'가 아니라 청상추이고 포기찹이다.
같은 시군 안에서도 품종에 따라 값이 갈린다 — 남원 부산엄궁행은 포기찹,
광주서부행은 청상추다.

전북 물량의 **90.8%가 상위 3품종**(포기찹 39.8 / 청상추 35.1 / 적상추 16.0)이라
이 셋만 떼어도 대부분을 덮는다.

────────────────────────────────────────────────────────────────
표본이 얇아지는 문제 — 값과 예측을 구분한다
────────────────────────────────────────────────────────────────
셋으로 나누면 계열 하나가 3분의 1로 얇아진다. 실측:

    시군 단위   남원·익산·완주·장수·김제·전주는 품종별로도 400주 이상
                고창 포기찹 46주, 임실 44주, 군산은 세 품종 다 불가
    읍면 단위   432개 조합 중 104주 이상은 120개(28%)

그래서 둘을 다르게 다룬다.

    값(평균·최고·최저·물량)   세는 것이므로 자료가 있으면 낸다
    예측·검증 성적            계열이 짧으면 **아예 내지 않는다**

못 내는 것을 억지로 내면 '평균 60% 빗나감' 같은 숫자가 화면에 남고,
그걸 본 사람은 그 값을 믿을지 말지 판단할 근거가 없다. 없으면 없다고 적는다.

────────────────────────────────────────────────────────────────
출력
────────────────────────────────────────────────────────────────
webapp/data/lettuce_var_<품종키>.json  품종마다 한 파일.
앱이 그 품종을 고를 때만 받아 간다 — 첫 화면을 3배로 무겁게 할 이유가 없다.

[실행] python export_by_variety.py
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import lettuce_weekly as WK                                        # noqa: E402
from export_lettuce_webapp import (load, daily_then_weekly, make_panel,   # noqa: E402
                                   reliability, forecast, pack,
                                   MIN_WEEKS_EUP, COUNTY_ID)

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "webapp" / "data"

# 물량 상위 3품종. 자료로 확인한 순서다(포기찹 39.8 / 청상추 35.1 / 적상추 16.0).
TOP_VARIETIES = {"pogichap": "포기찹", "chung": "청상추", "jeok": "적상추"}

# 예측을 내는 최소 길이. 주간 모델의 MIN_TRAIN(60주)에 검증 여유를 더한 값이다.
# 이보다 짧으면 walk_forward 가 fold 를 못 만들거나 한두 개로 성적을 내게 된다.
MIN_WEEKS_FORECAST = 104


def series_for(g: pd.DataFrame, variety: str) -> pd.DataFrame:
    """그 단위 · 그 품종만 남긴 주간 계열."""
    sub = g[g["variety"] == variety]
    if sub.empty:
        return pd.DataFrame()
    return daily_then_weekly(sub)


def unit_payload(g: pd.DataFrame, variety: str) -> dict | None:
    """한 단위(시군 또는 읍면)의 한 품종. 값은 되도록 내고, 예측은 조건을 건다."""
    w = series_for(g, variety)
    if w.empty or len(w) < 12:
        return None
    out = {"weekly": pack(w), "weeks": int(len(w)),
           "qty_t": round(float(w["qty"].sum()) / 1000, 1)}
    if len(w) >= MIN_WEEKS_FORECAST:
        p = make_panel(w)
        out["reliability"] = reliability(p)
        out["forecast"] = forecast(p)
    else:
        # 왜 없는지 화면에 적을 수 있게 이유를 남긴다
        out["reliability"] = {"cv_mape": None, "baseline": None,
                              "beats": False, "folds": 0}
        out["forecast"] = []
        out["thin"] = True
    return out


def main() -> None:
    d = load()
    print(f"자료 {len(d):,}행")

    for key, vname in TOP_VARIETIES.items():
        counties = {}
        n_fc = n_thin = 0
        for cname, cg in d.groupby("county"):
            cid = COUNTY_ID.get(str(cname))
            if not cid:                      # 알 수 없는 시군은 넣지 않는다
                continue
            cu = unit_payload(cg, vname)
            if not cu:
                continue
            cu["name"] = str(cname)
            eups = {}
            for ename, eg in cg.groupby("eup"):
                # 시군 채택 기준과 같은 잣대를 읍면에도 쓴다
                if eg["wk"].nunique() < MIN_WEEKS_EUP:
                    continue
                eu = unit_payload(eg, vname)
                if eu:
                    eups[str(ename)] = eu
                    n_fc += 1 if eu.get("forecast") else 0
                    n_thin += 1 if eu.get("thin") else 0
            cu["eups"] = dict(sorted(eups.items(), key=lambda x: -x[1]["qty_t"]))
            counties[cid] = cu
            mark = "예측O" if cu.get("forecast") else "예측X(얇음)"
            print(f"  {vname} {cname:<7} {cu['weeks']:>3}주 "
                  f"{cu['qty_t']:>8.0f}t  {mark}  읍면 {len(eups)}곳")

        payload = {
            "meta": {
                "variety": vname,
                "built": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "min_weeks_forecast": MIN_WEEKS_FORECAST,
                "note_ko": (f"{vname}만 떼어 다시 센 값입니다. "
                            f"계열이 {MIN_WEEKS_FORECAST}주보다 짧으면 예측을 내지 않습니다 — "
                            "짧은 자료로 낸 예측은 맞는지 확인할 방법이 없습니다."),
            },
            "counties": counties,
        }
        dst = WEB / f"lettuce_var_{key}.json"
        dst.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                       encoding="utf-8")
        print(f"  -> {dst.name} ({dst.stat().st_size/1024:.0f} KB, "
              f"시군 {len(counties)}개, 읍면 예측 {n_fc}곳 / 얇음 {n_thin}곳)\n")


if __name__ == "__main__":
    main()
