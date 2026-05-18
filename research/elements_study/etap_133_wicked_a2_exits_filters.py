"""etap_133: A2 (Wicked 4-stage 1.1.1 no-SWEPT) + direction filters + floating TP / BE-ratchet.

BTC A2 baseline (etap_131): 69 closed, WR 50.7%, +36R, 1 bad / R/tr +0.52.
WR близок к 50% (borderline для floating-TP law). Counter-trend strategy
ожидаем floating fails -- но 4-stage cascade чище V2, протестируем.
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
first_setup_per_ob = _e131.first_setup_per_ob
simulate_baseline = _e128.simulate_baseline
simulate_floating = _e128.simulate_floating
simulate_be_ratchet = _e128.simulate_be_ratchet
build_score_series = _e103.build_score_series

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
RR = 2.0


def report(label, results):
    closed = [r for r in results if r[0] in ("win", "loss")]
    n = len(closed)
    if n == 0:
        print(f"  {label:<55} closed=0  no data"); return
    W = sum(1 for r in closed if r[1] > 0)
    pnl = sum(r[1] for r in closed)
    wr = W/n*100
    rpt = pnl/n
    print(f"  {label:<55} n={n:>3d} WR={wr:>4.1f}% PnL={pnl:>+6.1f}R R/tr={rpt:+.2f}")


def main():
    print("etap_133: A2 BTC + direction filters + floating TP + BE-ratchet")
    print("Baseline A2: 69 closed / WR 50.7% / +36R / +0.52R/tr / 1 bad")
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
    df_2h["ema200"] = df_2h["close"].ewm(span=200, adjust=False).mean()

    wf_1d = collect_wicked_fractal_obs(df_1d, 24)
    wf_12h = collect_wicked_fractal_obs(df_12h, 12)
    all_ob_d = [(ob, df_1d) for ob in wf_1d] + [(ob, df_12h) for ob in wf_12h]
    print(f"  wicked+fractal OB total: {len(all_ob_d)}")

    setups = []
    for ob, df_l1 in all_ob_d:
        s = first_setup_per_ob(ob, df_l1, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
                               macro_kind="FVG", swept_required=False,
                               entry_pct=0.80, sl_pct=0.35)
        if s is not None: setups.append(s)
    print(f"  A2 setups: {len(setups)}")
    print()

    score_long, score_short = build_score_series(df_1h)
    print("  Direction filters:")
    print("  " + "-"*70)
    for label, filt in [
        ("ALL",        lambda s: True),
        ("LONG only",  lambda s: s["direction"] == "LONG"),
        ("SHORT only", lambda s: s["direction"] == "SHORT"),
    ]:
        results = []
        for s in setups:
            if not filt(s): continue
            tp = s["entry"] + RR*(s["entry"]-s["sl"]) if s["direction"]=="LONG" else s["entry"] - RR*(s["sl"]-s["entry"])
            outc, R, *_ = simulate_baseline(s, s["entry"], s["sl"], tp, df_1m)
            results.append((outc, R))
        report(label, results)

    print()
    print("  Exit alternatives (ALL setups):")
    print("  " + "-"*70)
    # baseline
    base_results = []
    for s in setups:
        tp = s["entry"] + RR*(s["entry"]-s["sl"]) if s["direction"]=="LONG" else s["entry"] - RR*(s["sl"]-s["entry"])
        outc, R, *_ = simulate_baseline(s, s["entry"], s["sl"], tp, df_1m)
        base_results.append((outc, R))
    report("baseline RR=2.0", base_results)

    for R_cap, th, cf in [(4.5, -0.25, 2), (3.5, 0.0, 1), (5.0, -0.5, 3)]:
        results = []
        for s in setups:
            outc, R = simulate_floating(s, s["entry"], s["sl"], df_1m, df_1h,
                                         score_long, score_short, R_cap=R_cap,
                                         threshold=th, confirm=cf)
            results.append((outc, R))
        report(f"floating TP cap={R_cap} th={th} cf={cf}", results)

    for trig in [1.0, 1.5]:
        results = []
        for s in setups:
            outc, R = simulate_be_ratchet(s, s["entry"], s["sl"], df_1m, trigger_R=trig, rr=RR)
            results.append((outc, R))
        report(f"BE-ratchet @+{trig}R", results)


if __name__ == "__main__":
    main()
