"""etap_134: A2 LONG-only + floating TP cross-symbol на BTC/ETH/SOL.

Комбинируем лучшие настройки из etap_131/132/133:
- A2 cascade (Wicked OB-D + 1.1.1 no-SWEPT, e=0.80, RR=2.0)
- LONG only filter (etap_133: R/tr +0.63, best)
- Floating TP cap=5.0 th=-0.5 cf=3 (etap_133: +40.9R на BTC ALL)

Проверяем additive effect: LONG+floating дают ли лучше чем по отдельности.
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
build_score_series = _e103.build_score_series

SYMBOLS = [
    ("BTCUSDT", "2020-01-01"),
    ("ETHUSDT", "2020-05-15"),
    ("SOLUSDT", "2020-08-11"),
]
RR = 2.0


def report(label, results):
    closed = [r for r in results if r[0] in ("win", "loss")]
    n = len(closed)
    if n == 0:
        print(f"  {label:<50} closed=0  no data"); return None
    Rs = [r[1] for r in closed]
    yrs = [r[2] for r in closed]
    W = sum(1 for r in Rs if r > 0)
    pnl = sum(Rs)
    wr = W/n*100
    rpt = pnl/n
    yr_map = defaultdict(float)
    for R, yr in zip(Rs, yrs): yr_map[yr] += R
    bad = sum(1 for v in yr_map.values() if v < 0)
    print(f"  {label:<50} n={n:>3d} WR={wr:>4.1f}% PnL={pnl:>+6.1f}R R/tr={rpt:+.2f} bad={bad}/{len(yr_map)}")
    return (n, wr, pnl, rpt, bad, len(yr_map))


def run_symbol(symbol, start_date):
    print(f"\n{'='*80}\n  {symbol}  (cutoff {start_date})\n{'='*80}")
    df_1d = load_df(symbol, "1d"); df_1h = load_df(symbol, "1h"); df_1m = load_df(symbol, "1m")
    if len(df_1d) == 0 or len(df_1h) == 0 or len(df_1m) == 0:
        print(f"  NO DATA for {symbol}"); return {}
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
    df_2h["ema200"] = df_2h["close"].ewm(span=200, adjust=False).mean()

    wf_1d = collect_wicked_fractal_obs(df_1d, 24)
    wf_12h = collect_wicked_fractal_obs(df_12h, 12)
    all_ob_d = [(ob, df_1d) for ob in wf_1d] + [(ob, df_12h) for ob in wf_12h]

    setups = []
    for ob, df_l1 in all_ob_d:
        s = first_setup_per_ob(ob, df_l1, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
                               macro_kind="FVG", swept_required=False,
                               entry_pct=0.80, sl_pct=0.35)
        if s is not None: setups.append(s)
    longs = [s for s in setups if s["direction"] == "LONG"]
    print(f"  A2 setups: {len(setups)} (LONG={len(longs)})")

    score_long, score_short = build_score_series(df_1h)

    # 1. ALL baseline
    res = []
    for s in setups:
        tp = s["entry"] + RR*(s["entry"]-s["sl"]) if s["direction"]=="LONG" else s["entry"] - RR*(s["sl"]-s["entry"])
        outc, R, *_ = simulate_baseline(s, s["entry"], s["sl"], tp, df_1m)
        res.append((outc, R, s["year"]))
    summary = {}
    summary["all_base"] = report("ALL baseline RR=2.0", res)

    # 2. LONG only baseline
    res = []
    for s in longs:
        tp = s["entry"] + RR*(s["entry"]-s["sl"])
        outc, R, *_ = simulate_baseline(s, s["entry"], s["sl"], tp, df_1m)
        res.append((outc, R, s["year"]))
    summary["long_base"] = report("LONG-only baseline RR=2.0", res)

    # 3. ALL + floating
    res = []
    for s in setups:
        outc, R = simulate_floating(s, s["entry"], s["sl"], df_1m, df_1h,
                                     score_long, score_short, R_cap=5.0,
                                     threshold=-0.5, confirm=3)
        res.append((outc, R, s["year"]))
    summary["all_float"] = report("ALL + floating cap=5.0 th=-0.5 cf=3", res)

    # 4. LONG + floating (combo)
    res = []
    for s in longs:
        outc, R = simulate_floating(s, s["entry"], s["sl"], df_1m, df_1h,
                                     score_long, score_short, R_cap=5.0,
                                     threshold=-0.5, confirm=3)
        res.append((outc, R, s["year"]))
    summary["long_float"] = report("LONG + floating cap=5.0 th=-0.5 cf=3", res)

    return summary


def main():
    print("etap_134: A2 LONG + floating cross-symbol")
    print("Test: does LONG-only + floating TP have additive effect?")
    by_sym = {}
    for sym, start in SYMBOLS:
        by_sym[sym] = run_symbol(sym, start)

    print(f"\n{'='*80}\n  TOTALS (sum 3 symbols)\n{'='*80}")
    for key, label in [("all_base", "ALL baseline"),
                        ("long_base", "LONG-only baseline"),
                        ("all_float", "ALL + floating"),
                        ("long_float", "LONG + floating")]:
        tot_n = 0; tot_pnl = 0.0; tot_W = 0; bad_total = 0
        for sym in by_sym:
            s = by_sym[sym].get(key)
            if s is None: continue
            n, wr, pnl, rpt, bad, ytot = s
            tot_n += n; tot_pnl += pnl
            tot_W += int(round(wr * n / 100))
            bad_total += bad
        wr_tot = tot_W / tot_n * 100 if tot_n else 0
        rpt = tot_pnl / tot_n if tot_n else 0
        print(f"  {label:<40} n={tot_n:>3d} WR={wr_tot:>4.1f}% PnL={tot_pnl:>+6.1f}R R/tr={rpt:+.2f} bad_total={bad_total}")


if __name__ == "__main__":
    main()
