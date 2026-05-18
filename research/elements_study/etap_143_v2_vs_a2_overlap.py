"""etap_143: V2 vs A2 setup overlap analysis на BTC.

V2 (3-stage): Wicked-OB-D + OB-1h/2h + FVG-15m/20m. BTC-only. +42R F12.
A2 (4-stage): Wicked-OB-D + FVG-4h/6h + OB-1h/2h + FVG-15m/20m. BTC+ETH. +43R Variant B.

Гипотеза: A2 ⊂ V2 (любой A2 setup ∈ V2). V2 \ A2 = setups без macro FVG-4h/6h.
Если V2 \ A2 имеет positive edge -- комбинированный portfolio лучше Variant B.

Тестируем:
  - count setups в V2, A2, V2 ∩ A2, V2 \ A2
  - simulate каждый subset
  - compare PnL/WR
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
import importlib.util as _ilu
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists(): _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path: _sys.path.insert(0, str(_ROOT))

from collections import defaultdict
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg

_E121 = _Path(__file__).parent / "etap_121_wicked_fractal_ob.py"
_E131 = _Path(__file__).parent / "etap_131_wicked_4stage_strict_dedup.py"
_E128 = _Path(__file__).parent / "etap_128_115_improve.py"
_E103 = _Path(__file__).parent / "etap_103_floating_tp.py"
for nm, p in [("etap121_core", _E121), ("etap131_core", _E131),
               ("etap128_core", _E128), ("etap103_core", _E103)]:
    _spec = _ilu.spec_from_file_location(nm, p)
    _m = _ilu.module_from_spec(_spec); _sys.modules[nm] = _m
    _spec.loader.exec_module(_m)

_e121 = _sys.modules["etap121_core"]
_e131 = _sys.modules["etap131_core"]
_e128 = _sys.modules["etap128_core"]
_e103 = _sys.modules["etap103_core"]

collect_wicked_fractal_obs = _e121.collect_wicked_fractal_obs
find_first_touch_and_invalidation = _e121.find_first_touch_and_invalidation
any_edge_inside = _e121.any_edge_inside
first_setup_per_ob = _e131.first_setup_per_ob
simulate_floating = _e128.simulate_floating
simulate_baseline = _e128.simulate_baseline
build_score_series = _e103.build_score_series

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
MIN_SL_PCT = 1.0
RR = 2.0


def first_v2_setup_per_ob(ob_d, df_l1, df_1h, df_2h, df_15m, df_20m):
    """V2 (3-stage): Wicked-OB-D -> OB-1h/2h -> FVG-15m/20m. Возвращает первый match."""
    touch_t, inval_t = find_first_touch_and_invalidation(ob_d, df_l1)
    if touch_t is None: return None
    if inval_t is None: inval_t = ob_d.cur_close + pd.Timedelta(days=21)
    for df_h, h_h, h_tf in [(df_1h, 1, "1h"), (df_2h, 2, "2h")]:
        dfw_h = df_h[(df_h.index >= touch_t) & (df_h.index < inval_t)]
        if len(dfw_h) < 2: continue
        for i in range(1, len(dfw_h)):
            cand = detect_ob_pair(dfw_h, i)
            if cand is None or cand.direction != ob_d.direction: continue
            if not any_edge_inside(cand.bottom, cand.top, ob_d.bottom, ob_d.top): continue
            for df_l, tf_min, tf_lbl in [(df_15m, 15, "15m"), (df_20m, 20, "20m")]:
                end_t = cand.cur_time + pd.Timedelta(minutes=h_h * 60 - tf_min)
                dfw_l = df_l[(df_l.index >= cand.prev_time) & (df_l.index <= end_t)]
                for k in range(2, len(dfw_l)):
                    fvg = detect_fvg(dfw_l, k)
                    if fvg is None or fvg.direction != ob_d.direction: continue
                    if not any_edge_inside(fvg.bottom, fvg.top, cand.bottom, cand.top): continue
                    fb, ft = fvg.bottom, fvg.top
                    obb, obt = cand.bottom, cand.top
                    if ob_d.direction == "LONG":
                        entry = fb + 0.70 * (ft - fb)  # V2 uses 0.70 entry per etap_121
                        sl = obb + 0.35 * (fb - obb)
                    else:
                        entry = ft - 0.70 * (ft - fb)
                        sl = obt - 0.35 * (obt - ft)
                    d = entry * MIN_SL_PCT / 100
                    if ob_d.direction == "LONG":
                        sl = min(sl, entry - d)
                    else:
                        sl = max(sl, entry + d)
                    if abs(entry - sl) <= 0: continue
                    if (ob_d.direction == "LONG" and sl >= entry) or (ob_d.direction == "SHORT" and sl <= entry):
                        continue
                    signal_time = fvg.c2_time + pd.Timedelta(minutes=tf_min)
                    return {"entry": entry, "sl": sl, "direction": ob_d.direction,
                            "signal_time": signal_time, "year": signal_time.year,
                            "source": "V2"}
    return None


def report(label, setups, df_1m, df_1h, score_long, score_short, use_float=True):
    trades = []
    for s in setups:
        if use_float:
            outc, R = simulate_floating(s, s["entry"], s["sl"], df_1m, df_1h,
                                         score_long, score_short, R_cap=5.0,
                                         threshold=0.0, confirm=1)
        else:
            tp = s["entry"] + RR*(s["entry"]-s["sl"]) if s["direction"]=="LONG" else s["entry"] - RR*(s["sl"]-s["entry"])
            outc, R, *_ = simulate_baseline(s, s["entry"], s["sl"], tp, df_1m)
        if outc in ("win", "loss"):
            trades.append({"R": R, "year": s["signal_time"].year})
    n = len(trades)
    if n == 0:
        print(f"  {label:<35} setups={len(setups):>3d} closed=0  no data"); return
    W = sum(1 for t in trades if t["R"] > 0); pnl = sum(t["R"] for t in trades)
    yr_map = defaultdict(float)
    for t in trades: yr_map[t["year"]] += t["R"]
    bad = sum(1 for v in yr_map.values() if v < 0)
    print(f"  {label:<35} setups={len(setups):>3d} closed={n:>3d} WR={W/n*100:>4.1f}% "
          f"PnL={pnl:>+6.1f}R R/tr={pnl/n:+.2f} bad={bad}/{len(yr_map)}")


def main():
    print("etap_143: V2 vs A2 setup overlap (BTC)")
    print()
    df_1d = load_df(SYMBOL, "1d"); df_1h = load_df(SYMBOL, "1h"); df_1m = load_df(SYMBOL, "1m")
    df_12h = compose_from_base(df_1h, "12h")
    df_4h = compose_from_base(df_1h, "4h"); df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = compose_from_base(df_1m, "15m"); df_20m = compose_from_base(df_1m, "20m")
    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_4h = df_4h[df_4h.index >= cutoff].copy()
    df_6h = df_6h[df_6h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_20m = df_20m[df_20m.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]

    wf_1d = collect_wicked_fractal_obs(df_1d, 24)
    wf_12h = collect_wicked_fractal_obs(df_12h, 12)
    all_ob_d = [(ob, df_1d) for ob in wf_1d] + [(ob, df_12h) for ob in wf_12h]
    print(f"  wicked+fractal OB-D total: {len(all_ob_d)}")

    # A2 setups
    a2_setups = []
    for ob, df_l1 in all_ob_d:
        s = first_setup_per_ob(ob, df_l1, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
                               macro_kind="FVG", swept_required=False,
                               entry_pct=0.80, sl_pct=0.35)
        if s is not None:
            s["source"] = "A2"; a2_setups.append(s)

    # V2 setups
    v2_setups = []
    for ob, df_l1 in all_ob_d:
        s = first_v2_setup_per_ob(ob, df_l1, df_1h, df_2h, df_15m, df_20m)
        if s is not None:
            v2_setups.append(s)

    print(f"  A2 setups: {len(a2_setups)}")
    print(f"  V2 setups: {len(v2_setups)}")

    # Overlap by signal_time (round to 1h) + direction
    a2_keys = set((s["signal_time"].floor("h"), s["direction"]) for s in a2_setups)
    v2_keys = set((s["signal_time"].floor("h"), s["direction"]) for s in v2_setups)
    overlap = a2_keys & v2_keys
    v2_unique = [s for s in v2_setups if (s["signal_time"].floor("h"), s["direction"]) not in a2_keys]
    a2_unique = [s for s in a2_setups if (s["signal_time"].floor("h"), s["direction"]) not in v2_keys]
    print(f"\n  A2 ∩ V2 (overlap): {len(overlap)} setups")
    print(f"  V2 only (V2 \\ A2): {len(v2_unique)} setups")
    print(f"  A2 only (A2 \\ V2): {len(a2_unique)} setups")
    print()

    score_long, score_short = build_score_series(df_1h)
    print("  Subset performance (Variant B floating: cap=5.0 th=0.0 cf=1):")
    print("  " + "="*100)
    report("A2 (all)",        a2_setups, df_1m, df_1h, score_long, score_short)
    report("V2 (all, floating)", v2_setups, df_1m, df_1h, score_long, score_short)
    report("V2 \\ A2 (V2 only)", v2_unique, df_1m, df_1h, score_long, score_short)
    report("A2 \\ V2 (A2 only)", a2_unique, df_1m, df_1h, score_long, score_short)
    combined = a2_setups + v2_unique
    report("A2 + (V2 \\ A2)",  combined, df_1m, df_1h, score_long, score_short)

    print()
    print("  V2 (all, baseline RR=2.0 no floating, для сравнения с etap_123 +42R):")
    report("V2 baseline RR=2.0", v2_setups, df_1m, df_1h, score_long, score_short, use_float=False)


if __name__ == "__main__":
    main()
