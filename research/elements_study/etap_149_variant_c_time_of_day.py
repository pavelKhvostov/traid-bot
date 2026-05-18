"""etap_149: Time-of-day analysis для Variant C portfolio.

Signal_time hour (UTC) split. 513 trades hopefully даёт statistical power
для определения "best hours" -- ICT концепции (London/NY sessions) могут
давать edge.

Trading sessions (UTC):
  Asia:   00-07
  London: 07-12
  Overlap:12-16  (London+NY)
  NY:     16-21
  Late:   21-24

Per-hour breakdown + per-session aggregation.
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
_E143 = _Path(__file__).parent / "etap_143_v2_vs_a2_overlap.py"
for nm, p in [("etap121_core", _E121), ("etap131_core", _E131),
               ("etap128_core", _E128), ("etap103_core", _E103),
               ("etap143_core", _E143)]:
    _spec = _ilu.spec_from_file_location(nm, p)
    _m = _ilu.module_from_spec(_spec); _sys.modules[nm] = _m
    _spec.loader.exec_module(_m)

_e121 = _sys.modules["etap121_core"]
_e131 = _sys.modules["etap131_core"]
_e128 = _sys.modules["etap128_core"]
_e103 = _sys.modules["etap103_core"]
_e143 = _sys.modules["etap143_core"]

collect_wicked_fractal_obs = _e121.collect_wicked_fractal_obs
first_setup_per_ob = _e131.first_setup_per_ob
first_v2_setup_per_ob = _e143.first_v2_setup_per_ob
simulate_floating = _e128.simulate_floating
build_score_series = _e103.build_score_series

SYMBOLS = [
    ("BTCUSDT", "2020-01-01", 5.0, 0.0, 1),
    ("ETHUSDT", "2020-05-15", 5.0, -0.5, 3),
]
SESSIONS = [
    ("Asia (00-07)",      0, 7),
    ("London (07-12)",    7, 12),
    ("Overlap (12-16)",  12, 16),
    ("NY (16-21)",       16, 21),
    ("Late (21-24)",     21, 24),
]


def collect_variant_c_trades(symbol, start_date, cap, th, cf):
    df_1d = load_df(symbol, "1d"); df_1h = load_df(symbol, "1h"); df_1m = load_df(symbol, "1m")
    df_12h = compose_from_base(df_1h, "12h")
    df_4h = compose_from_base(df_1h, "4h"); df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = compose_from_base(df_1m, "15m"); df_20m = compose_from_base(df_1m, "20m")
    cutoff = pd.Timestamp(start_date, tz="UTC")
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
    score_long, score_short = build_score_series(df_1h)

    a2_setups, v2_setups = [], []
    for ob, df_l1 in all_ob_d:
        s_a = first_setup_per_ob(ob, df_l1, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
                                 macro_kind="FVG", swept_required=False,
                                 entry_pct=0.80, sl_pct=0.35)
        if s_a is not None: a2_setups.append(s_a)
        s_v = first_v2_setup_per_ob(ob, df_l1, df_1h, df_2h, df_15m, df_20m)
        if s_v is not None: v2_setups.append(s_v)
    a2_keys = set((s["signal_time"].floor("h"), s["direction"]) for s in a2_setups)
    v2_unique = [s for s in v2_setups if (s["signal_time"].floor("h"), s["direction"]) not in a2_keys]
    combined = a2_setups + v2_unique

    trades = []
    for s in combined:
        outc, R = simulate_floating(s, s["entry"], s["sl"], df_1m, df_1h,
                                     score_long, score_short, R_cap=cap,
                                     threshold=th, confirm=cf)
        if outc in ("win", "loss"):
            trades.append({"R": R, "year": s["signal_time"].year,
                            "hour": s["signal_time"].hour, "time": s["signal_time"]})
    return trades


def main():
    print("etap_149: Time-of-day analysis на Variant C portfolio")
    print()
    all_trades = []
    for sym, start, cap, th, cf in SYMBOLS:
        print(f"  Computing {sym}...")
        ts = collect_variant_c_trades(sym, start, cap, th, cf)
        for t in ts: t["symbol"] = sym
        all_trades.extend(ts)
        print(f"    {sym}: {len(ts)} trades")
    print(f"  Total: {len(all_trades)} trades")
    print()

    # Per-hour breakdown
    print("  Per-hour (UTC) breakdown:")
    print("  " + "="*80)
    print(f"    {'Hour':>4}  {'n':>3}  {'WR':>5}  {'PnL':>8}  {'R/tr':>6}")
    print("  " + "-"*80)
    by_hour = defaultdict(lambda: {"n":0, "W":0, "R":0.0})
    for t in all_trades:
        by_hour[t["hour"]]["n"] += 1
        if t["R"] > 0: by_hour[t["hour"]]["W"] += 1
        by_hour[t["hour"]]["R"] += t["R"]
    for h in range(24):
        d = by_hour[h]
        wr = d["W"]/d["n"]*100 if d["n"] else 0
        rpt = d["R"]/d["n"] if d["n"] else 0
        bar = "+" * int(max(0, d["R"]/2)) if d["R"] > 0 else "-" * int(max(0, -d["R"]/2))
        print(f"    {h:>2}    {d['n']:>3d}  {wr:>4.1f}%  {d['R']:>+6.1f}R  {rpt:>+5.2f}  {bar}")
    print()

    # Per-session aggregation
    print("  Per-session breakdown:")
    print("  " + "="*80)
    print(f"    {'Session':<22}  {'n':>4}  {'WR':>5}  {'PnL':>8}  {'R/tr':>6}  {'bad':>5}")
    for label, h_start, h_end in SESSIONS:
        sess_trades = [t for t in all_trades if h_start <= t["hour"] < h_end]
        n = len(sess_trades)
        if n == 0:
            print(f"    {label:<22}  no trades"); continue
        W = sum(1 for t in sess_trades if t["R"] > 0)
        pnl = sum(t["R"] for t in sess_trades)
        yr_map = defaultdict(float)
        for t in sess_trades: yr_map[t["year"]] += t["R"]
        bad = sum(1 for v in yr_map.values() if v < 0)
        print(f"    {label:<22}  {n:>4d}  {W/n*100:>4.1f}%  {pnl:>+6.1f}R  {pnl/n:+.2f}  {bad}/{len(yr_map)}")

    # Best session combinations
    print()
    print("  Top sessions by R/tr (n>=30):")
    print("  " + "-"*80)
    candidates = []
    for label, h_start, h_end in SESSIONS:
        sess_trades = [t for t in all_trades if h_start <= t["hour"] < h_end]
        n = len(sess_trades)
        if n < 30: continue
        pnl = sum(t["R"] for t in sess_trades)
        candidates.append((label, h_start, h_end, n, pnl, pnl/n))
    candidates.sort(key=lambda x: -x[-1])
    for label, h_start, h_end, n, pnl, rpt in candidates:
        print(f"    {label:<22}  n={n}  PnL={pnl:+.1f}R  R/tr={rpt:+.2f}")


if __name__ == "__main__":
    main()
