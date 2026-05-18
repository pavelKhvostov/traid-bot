"""etap_120: диагностика wicked OB-D + V1 реакции — печатает последние N сетапов
с полными деталями для визуальной проверки на TradingView.

Логика:
1. Wicked OB на 1d/12h (cur wick < prev wick / 2)
2. Touch — первый возврат в зону после cur close
3. V1: OB-1h/2h + FVG-15m/20m inside по времени
4. Печать всех деталей setup'a
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
import importlib.util as _ilu
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists(): _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path: _sys.path.insert(0, str(_ROOT))

from pathlib import Path
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg

_E119 = Path(__file__).parent / "etap_119_wicked_ob_reactions.py"
_spec = _ilu.spec_from_file_location("etap119_core", _E119)
_e119 = _ilu.module_from_spec(_spec); _sys.modules["etap119_core"] = _e119
_spec.loader.exec_module(_e119)

detect_wicked_ob = _e119.detect_wicked_ob
find_first_touch_and_invalidation = _e119.find_first_touch_and_invalidation
zones_overlap = _e119.zones_overlap

SYMBOL = "BTCUSDT"


def utc3(ts):
    return (pd.Timestamp(ts) + pd.Timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")


def find_v1_reaction_detailed(ob_d, touch_t, inval_t, df_1h, df_2h, df_15m, df_20m):
    """V1 реакция (OB-htf + FVG-entry), возвращает ВСЕ найденные сетапы (не первый)
    для понимания распределения."""
    found = []
    for df_htf, htf_h, label in [(df_1h, 1, "1h"), (df_2h, 2, "2h")]:
        df_w = df_htf[(df_htf.index >= touch_t) & (df_htf.index < inval_t)]
        if len(df_w) < 2: continue
        for i in range(1, len(df_w)):
            cand = detect_ob_pair(df_w, i)
            if cand is None or cand.direction != ob_d.direction: continue
            if not zones_overlap(cand.bottom, cand.top, ob_d.bottom, ob_d.top): continue
            for df_ltf, tf_min, tf_label in [(df_15m, 15, "15m"), (df_20m, 20, "20m")]:
                end_t = cand.cur_time + pd.Timedelta(minutes=htf_h * 60 - tf_min)
                df_l = df_ltf[(df_ltf.index >= cand.prev_time) & (df_ltf.index <= end_t)]
                for k in range(2, len(df_l)):
                    fvg = detect_fvg(df_l, k)
                    if fvg is None or fvg.direction != ob_d.direction: continue
                    if not zones_overlap(fvg.bottom, fvg.top, cand.bottom, cand.top): continue
                    found.append({
                        "ob_htf_tf": label, "ob_htf_prev": cand.prev_time,
                        "ob_htf_cur": cand.cur_time,
                        "ob_htf_bottom": cand.bottom, "ob_htf_top": cand.top,
                        "fvg_tf": tf_label, "fvg_c0": fvg.c0_time, "fvg_c2": fvg.c2_time,
                        "fvg_bottom": fvg.bottom, "fvg_top": fvg.top,
                    })
                    return found  # take first match per (htf_label, tf_label) combo
    return found


def main():
    print("etap_120: диагностика wicked OB-D + V1 реакции (BTC)")
    print()
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_2h = compose_from_base(df_1h, "2h")
    df_1m = load_df(SYMBOL, "1m")
    df_15m = compose_from_base(df_1m, "15m")
    df_20m = compose_from_base(df_1m, "20m")

    # Последние 12 месяцев
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=365)
    df_1d_f = df_1d[df_1d.index >= cutoff].copy()
    df_12h_f = df_12h[df_12h.index >= cutoff].copy()

    setups_found = []

    # Wicked OB на 1d
    for idx in range(2, len(df_1d_f) - 1):
        w = detect_wicked_ob(df_1d_f, idx, 24)
        if w is None: continue
        touch_t, inval_t = find_first_touch_and_invalidation(w, df_1d)
        if touch_t is None: continue
        if inval_t is None: inval_t = w.cur_close + pd.Timedelta(days=21)
        reactions = find_v1_reaction_detailed(w, touch_t, inval_t, df_1h, df_2h, df_15m, df_20m)
        if not reactions: continue
        setups_found.append({"ob_d": w, "tf_l1": "1d", "touch": touch_t,
                              "inval": inval_t, "reaction": reactions[0]})

    # Wicked OB на 12h
    for idx in range(2, len(df_12h_f) - 1):
        w = detect_wicked_ob(df_12h_f, idx, 12)
        if w is None: continue
        touch_t, inval_t = find_first_touch_and_invalidation(w, df_12h)
        if touch_t is None: continue
        if inval_t is None: inval_t = w.cur_close + pd.Timedelta(days=14)
        reactions = find_v1_reaction_detailed(w, touch_t, inval_t, df_1h, df_2h, df_15m, df_20m)
        if not reactions: continue
        setups_found.append({"ob_d": w, "tf_l1": "12h", "touch": touch_t,
                              "inval": inval_t, "reaction": reactions[0]})

    setups_found.sort(key=lambda s: s["ob_d"].cur_close, reverse=True)

    print(f"Найдено сетапов за последний год: {len(setups_found)}")
    print(f"Показываю последние 7:")
    print()
    for i, s in enumerate(setups_found[:7], 1):
        od = s["ob_d"]; r = s["reaction"]
        print(f"{'='*88}")
        print(f"#{i}  {s['tf_l1'].upper()}  {od.direction}  cur_close={utc3(od.cur_close)}")
        print(f"{'='*88}")
        print(f"  L1 OB-{s['tf_l1']} (wicked):")
        print(f"    prev bar:    {utc3(od.prev_time)}")
        print(f"    cur bar:     {utc3(od.cur_time)}")
        print(f"    cur close:   {utc3(od.cur_close)}")
        print(f"    wick ratio:  cur/prev = {od.wick_ratio:.2f}  (<0.5 = wicked filter passed)")
        print(f"    zone:        bottom={od.bottom:.2f}  top={od.top:.2f}  (height={od.top-od.bottom:.2f} = "
              f"{(od.top-od.bottom)/od.bottom*100:.2f}%)")
        print(f"  Touch (first return to zone):")
        print(f"    time:        {utc3(s['touch'])}")
        delta_touch = (s['touch'] - od.cur_close).total_seconds() / 3600
        print(f"    delay:       {delta_touch:.1f} h после cur_close")
        print(f"  Invalidation (close beyond far edge):")
        print(f"    time:        {utc3(s['inval'])}")
        print(f"  L2 OB-{r['ob_htf_tf']} reaction (after touch):")
        print(f"    prev bar:    {utc3(r['ob_htf_prev'])}")
        print(f"    cur bar:     {utc3(r['ob_htf_cur'])}")
        print(f"    zone:        bottom={r['ob_htf_bottom']:.2f}  top={r['ob_htf_top']:.2f}")
        print(f"  L3 entry FVG-{r['fvg_tf']} (inside OB-htf time):")
        print(f"    c0 time:     {utc3(r['fvg_c0'])}")
        print(f"    c2 time:     {utc3(r['fvg_c2'])}")
        print(f"    zone:        bottom={r['fvg_bottom']:.2f}  top={r['fvg_top']:.2f}")
        # Сравнение зон
        print(f"  Geometry check:")
        print(f"    FVG fits in OB-htf: "
              f"{r['fvg_bottom'] >= r['ob_htf_bottom'] and r['fvg_top'] <= r['ob_htf_top']}")
        print(f"    OB-htf fits in OB-{s['tf_l1']}: "
              f"{r['ob_htf_bottom'] >= od.bottom and r['ob_htf_top'] <= od.top}")
        print()


if __name__ == "__main__":
    main()
