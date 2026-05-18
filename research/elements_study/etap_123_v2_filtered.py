"""etap_123: Combined filter test для V2 Wicked+Fractal OB-D.

Из forensic etap_122 нашли:
  - EMA-2h pro-trend: WR 51.9% vs 32.4% counter (★ strongest filter)
  - LONG only: WR 42.6% vs SHORT 30.8%
  - touch_delay < 60h: Q3 WR 45.5% vs Q4 29.8%
  - zone_pct > 2%: weak signal
  - fvg_depth > 0.7: Q3 WR 45.5% vs Q2 29.1%

Тестируем все relevant combinations:
  F0: no filter (baseline +24R / WR 36.9%)
  F1: EMA pro-trend only
  F2: LONG only
  F3: delay < 60h only
  F4: EMA pro AND LONG
  F5: EMA pro AND delay < 60h
  F6: LONG AND delay < 60h
  F7: EMA pro AND LONG AND delay < 60h (strict)
  F8: EMA pro AND LONG AND delay < 60h AND zone > 2%
  F9: EMA pro AND LONG AND delay < 60h AND fvg_depth > 0.7
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
import importlib.util as _ilu
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists(): _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path: _sys.path.insert(0, str(_ROOT))

from collections import defaultdict
from pathlib import Path
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df

_E122 = Path(__file__).parent / "etap_122_v2_forensic.py"
_spec = _ilu.spec_from_file_location("etap122_core", _E122)
_e122 = _ilu.module_from_spec(_spec); _sys.modules["etap122_core"] = _e122
_spec.loader.exec_module(_e122)

react_v2_detailed = _e122.react_v2_detailed

_E121 = Path(__file__).parent / "etap_121_wicked_fractal_ob.py"
_spec121 = _ilu.spec_from_file_location("etap121_core", _E121)
_e121 = _ilu.module_from_spec(_spec121); _sys.modules["etap121_core"] = _e121
_spec121.loader.exec_module(_e121)
collect_wicked_fractal_obs = _e121.collect_wicked_fractal_obs
find_first_touch_and_invalidation = _e121.find_first_touch_and_invalidation
simulate = _e121.simulate

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"


def main():
    print("etap_123: Combined filter test for V2 (BTC 6.3y)")
    print()
    df_1d = load_df(SYMBOL, "1d")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_2h = compose_from_base(df_1h, "2h")
    df_1m = load_df(SYMBOL, "1m")
    df_15m = compose_from_base(df_1m, "15m")
    df_20m = compose_from_base(df_1m, "20m")

    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_20m = df_20m[df_20m.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]

    df_2h["ema200"] = df_2h["close"].ewm(span=200, adjust=False).mean()

    print("[INFO] detecting setups")
    wf_1d = collect_wicked_fractal_obs(df_1d, 24)
    wf_12h = collect_wicked_fractal_obs(df_12h, 12)
    trades = []
    for ob_list, df_l1 in [(wf_1d, df_1d), (wf_12h, df_12h)]:
        for ob_d in ob_list:
            touch_t, inval_t = find_first_touch_and_invalidation(ob_d, df_l1)
            if touch_t is None: continue
            if inval_t is None: inval_t = ob_d.cur_close + pd.Timedelta(days=21)
            setup = react_v2_detailed(ob_d, touch_t, inval_t, df_15m, df_20m)
            if setup is None: continue
            outcome, R = simulate(setup, df_1m)
            setup["outcome"] = outcome; setup["R"] = R
            setup["year"] = setup["signal_time"].year
            # EMA-2h pro
            t = setup["signal_time"]
            idx = df_2h.index.searchsorted(t, side="right") - 1
            if idx >= 0 and not pd.isna(df_2h["ema200"].iloc[idx]):
                c = float(df_2h["close"].iloc[idx]); e = float(df_2h["ema200"].iloc[idx])
                setup["ema_pro"] = (c > e) if setup["direction"] == "LONG" else (c < e)
            else:
                setup["ema_pro"] = False
            trades.append(setup)
    # Dedup
    seen = {}
    for t in trades:
        k = (t["signal_time"], t["direction"], round(t["entry"], 2))
        if k not in seen: seen[k] = t
    trades = list(seen.values())
    print(f"  total unique: {len(trades)}")
    closed = [t for t in trades if t["outcome"] in ("win", "loss")]
    print(f"  closed: {len(closed)}")

    # Define filters
    def f_ema(t): return t["ema_pro"]
    def f_long(t): return t["direction"] == "LONG"
    def f_delay(t): return t["touch_delay_h"] < 60
    def f_zone(t): return t["zone_pct"] > 2.0
    def f_depth(t): return t["fvg_depth"] > 0.7

    filters = [
        ("F0: no filter (baseline)",                    lambda t: True),
        ("F1: EMA pro-trend",                           f_ema),
        ("F2: LONG only",                               f_long),
        ("F3: touch_delay < 60h",                       f_delay),
        ("F4: EMA pro AND LONG",                        lambda t: f_ema(t) and f_long(t)),
        ("F5: EMA pro AND delay < 60h",                 lambda t: f_ema(t) and f_delay(t)),
        ("F6: LONG AND delay < 60h",                    lambda t: f_long(t) and f_delay(t)),
        ("F7: EMA + LONG + delay < 60h",                lambda t: f_ema(t) and f_long(t) and f_delay(t)),
        ("F8: F7 + zone > 2%",                          lambda t: f_ema(t) and f_long(t) and f_delay(t) and f_zone(t)),
        ("F9: F7 + fvg_depth > 0.7",                    lambda t: f_ema(t) and f_long(t) and f_delay(t) and f_depth(t)),
        ("F10: F7 + zone > 2% + depth > 0.7",           lambda t: f_ema(t) and f_long(t) and f_delay(t) and f_zone(t) and f_depth(t)),
        # SHORT-friendly filters
        ("F11: SHORT + EMA pro + delay<60h",            lambda t: not f_long(t) and f_ema(t) and f_delay(t)),
        # OR variants
        ("F12: EMA pro OR LONG",                        lambda t: f_ema(t) or f_long(t)),
    ]

    print()
    print(f"  {'Filter':<42} {'n':>4} {'closed':>6} {'WR':>6} {'PnL':>9} {'top5':>6} {'bad':>5}")
    print("  " + "-"*100)
    results = []
    for label, fn in filters:
        filtered = [t for t in closed if fn(t)]
        n = len(filtered)
        if n == 0:
            print(f"  {label:<42} {0:>4d} {0:>6d}  no trades")
            continue
        W = sum(1 for t in filtered if t["R"] > 0)
        wr = W / n * 100
        pnl = sum(t["R"] for t in filtered)
        Rs = sorted([t["R"] for t in filtered], reverse=True)
        top5 = sum(Rs[:5]) / pnl * 100 if pnl > 0 else 0
        yr_map = defaultdict(float)
        for t in filtered: yr_map[t["year"]] += t["R"]
        bad = sum(1 for v in yr_map.values() if v < 0)
        sigs_count = sum(1 for t in trades if fn(t))
        print(f"  {label:<42} {sigs_count:>4d} {n:>6d} {wr:>5.1f}% {pnl:>+8.1f}R {top5:>5.1f}% {bad}/{len(yr_map)}")
        results.append({"label": label, "sigs": sigs_count, "n": n, "wr": wr, "pnl": pnl,
                        "top5": top5, "bad": bad, "n_yrs": len(yr_map)})

    print()
    print("=" * 100)
    print("RANKED by PnL × (1 - bad/7)  (PnL adjusted for robustness)")
    print("=" * 100)
    def score_fn(r):
        if r["n"] < 10: return -999
        return r["pnl"] * (1 - r["bad"] / max(r["n_yrs"], 1))
    sorted_r = sorted(results, key=score_fn, reverse=True)
    for r in sorted_r:
        s = score_fn(r)
        print(f"  {r['label']:<42}  n={r['n']:>3d}  WR={r['wr']:>4.1f}%  "
              f"PnL={r['pnl']:>+6.1f}R  bad={r['bad']}/{r['n_yrs']}  score={s:>+6.1f}")


if __name__ == "__main__":
    main()
