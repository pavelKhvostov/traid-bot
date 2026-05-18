"""etap_135: BTC+ETH portfolio A2 + floating TP, year-by-year + drawdown.

Объединяем все trades A2+float по BTC и ETH (drop SOL, broken).
Анализируем:
- year-by-year breakdown
- max drawdown по unit-R timeline
- monthly cadence
- direction split

Pre-anticipated: ~+78R / 146 closed / 4 bad years total.
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
simulate_floating = _e128.simulate_floating
build_score_series = _e103.build_score_series

SYMBOLS = [("BTCUSDT", "2020-01-01"), ("ETHUSDT", "2020-05-15")]
RR = 2.0


def collect_trades(symbol, start_date):
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

    setups = []
    for ob, df_l1 in all_ob_d:
        s = first_setup_per_ob(ob, df_l1, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
                               macro_kind="FVG", swept_required=False,
                               entry_pct=0.80, sl_pct=0.35)
        if s is not None: setups.append(s)
    score_long, score_short = build_score_series(df_1h)
    trades = []
    for s in setups:
        outc, R = simulate_floating(s, s["entry"], s["sl"], df_1m, df_1h,
                                     score_long, score_short, R_cap=5.0,
                                     threshold=-0.5, confirm=3)
        if outc in ("win", "loss"):
            trades.append({"R": R, "year": s["signal_time"].year,
                            "month": s["signal_time"].strftime("%Y-%m"),
                            "time": s["signal_time"],
                            "direction": s["direction"], "symbol": symbol})
    return trades


def main():
    print("etap_135: A2 + floating BTC+ETH portfolio analysis (SOL excluded)")
    print()
    all_trades = []
    for sym, start in SYMBOLS:
        ts = collect_trades(sym, start)
        all_trades.extend(ts)
        print(f"  {sym}: {len(ts)} trades collected")
    all_trades.sort(key=lambda t: t["time"])
    print(f"  Total: {len(all_trades)} trades")
    print()

    # Year-by-year
    print("  YEAR breakdown:")
    print("  " + "-"*70)
    by_year = defaultdict(lambda: {"n": 0, "W": 0, "R": 0.0})
    for t in all_trades:
        by_year[t["year"]]["n"] += 1
        if t["R"] > 0: by_year[t["year"]]["W"] += 1
        by_year[t["year"]]["R"] += t["R"]
    for yr in sorted(by_year):
        d = by_year[yr]
        wr = d["W"]/d["n"]*100 if d["n"] else 0
        marker = " <- BAD" if d["R"] < 0 else ""
        print(f"  {yr}: n={d['n']:>3d} WR={wr:>4.1f}% PnL={d['R']:>+6.1f}R{marker}")
    bad_years = sum(1 for yr in by_year if by_year[yr]["R"] < 0)
    tot_n = sum(by_year[yr]["n"] for yr in by_year)
    tot_R = sum(by_year[yr]["R"] for yr in by_year)
    tot_W = sum(by_year[yr]["W"] for yr in by_year)
    print(f"  TOTAL: n={tot_n} WR={tot_W/tot_n*100:.1f}% PnL={tot_R:+.1f}R bad={bad_years}/{len(by_year)}")
    print()

    # Symbol split
    print("  Symbol split:")
    print("  " + "-"*70)
    by_sym = defaultdict(lambda: {"n": 0, "W": 0, "R": 0.0})
    for t in all_trades:
        by_sym[t["symbol"]]["n"] += 1
        if t["R"] > 0: by_sym[t["symbol"]]["W"] += 1
        by_sym[t["symbol"]]["R"] += t["R"]
    for sym in by_sym:
        d = by_sym[sym]
        wr = d["W"]/d["n"]*100
        print(f"  {sym}: n={d['n']:>3d} WR={wr:>4.1f}% PnL={d['R']:>+6.1f}R")
    print()

    # Direction split
    by_dir = defaultdict(lambda: {"n": 0, "W": 0, "R": 0.0})
    for t in all_trades:
        by_dir[t["direction"]]["n"] += 1
        if t["R"] > 0: by_dir[t["direction"]]["W"] += 1
        by_dir[t["direction"]]["R"] += t["R"]
    print("  Direction split:")
    print("  " + "-"*70)
    for dr in by_dir:
        d = by_dir[dr]
        wr = d["W"]/d["n"]*100
        print(f"  {dr}: n={d['n']:>3d} WR={wr:>4.1f}% PnL={d['R']:>+6.1f}R")
    print()

    # Drawdown curve (unit-R per trade, cumulative)
    cum = 0.0; peak = 0.0; max_dd = 0.0
    for t in all_trades:
        cum += t["R"]
        peak = max(peak, cum)
        dd = peak - cum
        max_dd = max(max_dd, dd)
    print(f"  Max drawdown: -{max_dd:.1f}R (peak={peak:.1f}R, final={cum:.1f}R)")

    # Cadence
    months = set(t["month"] for t in all_trades)
    if months:
        first_m = min(months); last_m = max(months)
        total_months = (pd.Timestamp(last_m + "-01") - pd.Timestamp(first_m + "-01")).days / 30.44
        cad = len(all_trades) / total_months if total_months > 0 else 0
        print(f"  Cadence: {cad:.1f} trades/month ({len(all_trades)} trades / {total_months:.1f} months)")


if __name__ == "__main__":
    main()
