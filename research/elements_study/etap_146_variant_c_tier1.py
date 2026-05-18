"""etap_146: Tier-1 score>=0.50 filter applied to Variant C (V2+A2 combined).

Variant B + score>=0.50 (Tier-1, etap_141/142): BTC 22 trades / WR 86.4% / +33R / 0 DD.
OOS validated WR 88.9% (etap_142).

Тестируем: применяем score>=0.50 filter ко всему Variant C portfolio (A2 + V2\A2).
Если V2 unique trades респонсятся к score так же как A2 -- получаем большой
premium sample.

Также тестируем score>=0.25 как промежуточный фильтр.
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


def collect_setups(symbol, start_date):
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
        if s_a is not None:
            s_a["source"] = "A2"; a2_setups.append(s_a)
        s_v = first_v2_setup_per_ob(ob, df_l1, df_1h, df_2h, df_15m, df_20m)
        if s_v is not None:
            s_v["source"] = "V2"; v2_setups.append(s_v)
    a2_keys = set((s["signal_time"].floor("h"), s["direction"]) for s in a2_setups)
    v2_unique = [s for s in v2_setups if (s["signal_time"].floor("h"), s["direction"]) not in a2_keys]
    combined = a2_setups + v2_unique

    # attach score
    for s in combined:
        sl_arr = score_long.index.searchsorted(s["signal_time"], side="right") - 1
        if sl_arr < 0:
            s["score"] = float("nan")
        else:
            ss = score_long.iloc[sl_arr] if s["direction"] == "LONG" else score_short.iloc[sl_arr]
            s["score"] = float(ss) if not pd.isna(ss) else float("nan")
    return combined, df_1m, df_1h, score_long, score_short


def evaluate(setups, df_1m, df_1h, score_long, score_short, cap, th, cf, threshold):
    filtered = [s for s in setups if not pd.isna(s["score"]) and s["score"] >= threshold] if threshold is not None else setups
    trades = []
    for s in filtered:
        outc, R = simulate_floating(s, s["entry"], s["sl"], df_1m, df_1h,
                                     score_long, score_short, R_cap=cap,
                                     threshold=th, confirm=cf)
        if outc in ("win", "loss"):
            trades.append({"R": R, "year": s["signal_time"].year, "time": s["signal_time"],
                            "source": s.get("source", "?")})
    n = len(trades)
    if n == 0: return None
    W = sum(1 for t in trades if t["R"] > 0); pnl = sum(t["R"] for t in trades)
    yr_map = defaultdict(float)
    for t in trades: yr_map[t["year"]] += t["R"]
    bad = sum(1 for v in yr_map.values() if v < 0)
    trades_sorted = sorted(trades, key=lambda t: t["time"])
    cum = 0.0; peak = 0.0; dd = 0.0
    for t in trades_sorted:
        cum += t["R"]; peak = max(peak, cum); dd = max(dd, peak - cum)
    # source split
    by_src = defaultdict(int)
    for t in trades: by_src[t["source"]] += 1
    return {"n": n, "wr": W/n*100, "pnl": pnl, "rpt": pnl/n,
            "bad": bad, "ytot": len(yr_map), "dd": dd, "by_src": dict(by_src),
            "n_setups": len(filtered)}


def show(label, m):
    if m is None:
        print(f"  {label:<40} no data"); return
    src_str = " ".join(f"{k}={v}" for k, v in m["by_src"].items())
    print(f"  {label:<40} setups={m['n_setups']:>3d} n={m['n']:>3d} WR={m['wr']:>4.1f}% "
          f"PnL={m['pnl']:>+6.1f}R R/tr={m['rpt']:+.2f} bad={m['bad']}/{m['ytot']} "
          f"DD=-{m['dd']:>4.1f}R  src={src_str}")


def main():
    print("etap_146: Tier-1 score filter applied to Variant C (V2+A2 combined)")
    print()
    per_sym = {}
    for sym, start, cap, th, cf in SYMBOLS:
        print(f"  Computing {sym}...")
        setups, df_1m, df_1h, sl, ss = collect_setups(sym, start)
        print(f"    {sym}: {len(setups)} Variant C setups")
        per_sym[sym] = (setups, df_1m, df_1h, sl, ss, cap, th, cf)

    print()
    print("  Per-symbol breakdown:")
    print("  " + "="*110)
    for sym in per_sym:
        setups, df_1m, df_1h, sl_, ss_, cap, th, cf = per_sym[sym]
        print(f"\n  {sym}:")
        for label, threshold in [("Variant C baseline (no score filter)", None),
                                  ("Variant C + score >= 0",              0.0),
                                  ("Variant C + score >= +0.25",          0.25),
                                  ("Variant C + score >= +0.50 (Tier-1)", 0.50)]:
            m = evaluate(setups, df_1m, df_1h, sl_, ss_, cap, th, cf, threshold)
            show(label, m)

    print()
    print("  Portfolio merged BTC+ETH:")
    print("  " + "="*110)
    for label, threshold in [("Variant C baseline", None),
                              ("Variant C + score>=0", 0.0),
                              ("Variant C + score>=0.25", 0.25),
                              ("Variant C + score>=0.50 (Tier-1)", 0.50)]:
        all_trades = []
        all_setups_count = 0
        for sym in per_sym:
            setups, df_1m, df_1h, sl_, ss_, cap, th, cf = per_sym[sym]
            m = evaluate(setups, df_1m, df_1h, sl_, ss_, cap, th, cf, threshold)
            if m is None: continue
            # rebuild trade list to merge
            filtered = [s for s in setups if not pd.isna(s["score"]) and s["score"] >= threshold] if threshold is not None else setups
            for s in filtered:
                outc, R = simulate_floating(s, s["entry"], s["sl"], df_1m, df_1h,
                                             sl_, ss_, R_cap=cap, threshold=th, confirm=cf)
                if outc in ("win", "loss"):
                    all_trades.append({"R": R, "year": s["signal_time"].year, "time": s["signal_time"],
                                        "source": s.get("source", "?")})
            all_setups_count += len(filtered)
        n = len(all_trades)
        if n == 0:
            print(f"  {label:<40} no data"); continue
        W = sum(1 for t in all_trades if t["R"] > 0); pnl = sum(t["R"] for t in all_trades)
        yr_map = defaultdict(float)
        for t in all_trades: yr_map[t["year"]] += t["R"]
        bad = sum(1 for v in yr_map.values() if v < 0)
        all_trades.sort(key=lambda t: t["time"])
        cum = 0.0; peak = 0.0; dd = 0.0
        for t in all_trades:
            cum += t["R"]; peak = max(peak, cum); dd = max(dd, peak - cum)
        print(f"  {label:<40} setups={all_setups_count:>3d} n={n:>3d} WR={W/n*100:>4.1f}% "
              f"PnL={pnl:>+6.1f}R R/tr={pnl/n:+.2f} bad={bad}/{len(yr_map)} DD=-{dd:.1f}R")


if __name__ == "__main__":
    main()
