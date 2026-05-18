"""etap_127: Wicked+Fractal OB-D V2 + F12 на ETH и SOL (cross-symbol валидация).

BTC reference (etap_123 F12): +42R / WR 43.5% / 138 closed / 2 bad / 6.3y.

Прогон same pipeline на:
  - ETHUSDT (full 6y from 2020-05-15)
  - SOLUSDT (5.76y from 2020-08-11)
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
_spec122 = _ilu.spec_from_file_location("etap122_core", _E122)
_e122 = _ilu.module_from_spec(_spec122); _sys.modules["etap122_core"] = _e122
_spec122.loader.exec_module(_e122)
react_v2_detailed = _e122.react_v2_detailed

_E121 = Path(__file__).parent / "etap_121_wicked_fractal_ob.py"
_spec121 = _ilu.spec_from_file_location("etap121_core", _E121)
_e121 = _ilu.module_from_spec(_spec121); _sys.modules["etap121_core"] = _e121
_spec121.loader.exec_module(_e121)
collect_wicked_fractal_obs = _e121.collect_wicked_fractal_obs
find_first_touch_and_invalidation = _e121.find_first_touch_and_invalidation
simulate = _e121.simulate


def run_symbol(symbol):
    print(f"\n{'#'*72}\n#  {symbol}\n{'#'*72}")
    df_1d = load_df(symbol, "1d")
    df_1h = load_df(symbol, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_2h = compose_from_base(df_1h, "2h")
    df_1m = load_df(symbol, "1m")
    df_15m = compose_from_base(df_1m, "15m")
    df_20m = compose_from_base(df_1m, "20m")

    cutoff = df_1m.index[0]
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_20m = df_20m[df_20m.index >= cutoff].copy()
    df_2h["ema200"] = df_2h["close"].ewm(span=200, adjust=False).mean()

    years = (df_1d.index[-1] - df_1d.index[0]).days / 365
    print(f"  cutoff: {cutoff.date()}  years: {years:.2f}")

    wf_1d = collect_wicked_fractal_obs(df_1d, 24)
    wf_12h = collect_wicked_fractal_obs(df_12h, 12)
    print(f"  Wicked+Fractal: 1d={len(wf_1d)}  12h={len(wf_12h)}")

    raw = []
    for ob_list, df_l1 in [(wf_1d, df_1d), (wf_12h, df_12h)]:
        for ob_d in ob_list:
            touch_t, inval_t = find_first_touch_and_invalidation(ob_d, df_l1)
            if touch_t is None: continue
            if inval_t is None: inval_t = ob_d.cur_close + pd.Timedelta(days=21)
            s = react_v2_detailed(ob_d, touch_t, inval_t, df_15m, df_20m)
            if s is None: continue
            outcome, R = simulate(s, df_1m)
            s["outcome"] = outcome; s["R"] = R
            s["year"] = s["signal_time"].year
            t = s["signal_time"]
            idx = df_2h.index.searchsorted(t, side="right") - 1
            if idx >= 0 and not pd.isna(df_2h["ema200"].iloc[idx]):
                c = float(df_2h["close"].iloc[idx]); e = float(df_2h["ema200"].iloc[idx])
                s["ema_pro"] = (c > e) if s["direction"] == "LONG" else (c < e)
            else:
                s["ema_pro"] = False
            raw.append(s)
    seen = {}
    for s in raw:
        k = (s["signal_time"], s["direction"], round(s["entry"], 2))
        if k not in seen: seen[k] = s
    setups = list(seen.values())

    def f_long(t): return t["direction"] == "LONG"
    def f_ema(t): return t["ema_pro"]
    def f_delay(t): return t["touch_delay_h"] < 60

    filters = [
        ("F0: baseline", lambda t: True),
        ("F2: LONG only", f_long),
        ("F6: LONG + delay<60h", lambda t: f_long(t) and f_delay(t)),
        ("F7: EMA + LONG + delay<60h", lambda t: f_ema(t) and f_long(t) and f_delay(t)),
        ("F12: EMA pro OR LONG", lambda t: f_ema(t) or f_long(t)),
    ]

    print(f"\n  {'Filter':<32} {'n':>4} {'closed':>6} {'WR':>5} {'PnL':>8} {'top5':>6} {'bad':>5}")
    print("  " + "-"*92)
    rows = []
    for label, fn in filters:
        filtered = [s for s in setups if fn(s)]
        closed = [s for s in filtered if s["outcome"] in ("win", "loss")]
        n = len(closed)
        if n == 0:
            print(f"  {label:<32} {len(filtered):>4d} {0:>6d}  no closed"); continue
        W = sum(1 for s in closed if s["R"] > 0)
        wr = W / n * 100
        pnl = sum(s["R"] for s in closed)
        Rs = sorted([s["R"] for s in closed], reverse=True)
        top5 = sum(Rs[:5]) / pnl * 100 if pnl > 0 else 0
        yr_map = defaultdict(float)
        for s in closed: yr_map[s["year"]] += s["R"]
        bad = sum(1 for v in yr_map.values() if v < 0)
        print(f"  {label:<32} {len(filtered):>4d} {n:>6d} {wr:>4.1f}% {pnl:>+7.1f}R "
              f"{top5:>5.1f}% {bad}/{len(yr_map)}")
        rows.append({"label": label, "n": n, "wr": wr, "pnl": pnl, "bad": bad,
                     "n_yrs": len(yr_map)})
    return rows


def main():
    print("etap_127: Wicked+Fractal OB-D V2 + F12 — cross-symbol validation")
    print("BTC reference (etap_123 F12): +42R / WR 43.5% / 138 closed / 2 bad / 6.3y")

    results = {}
    for sym in ["ETHUSDT", "SOLUSDT"]:
        rows = run_symbol(sym)
        results[sym] = rows

    print()
    print("=" * 92)
    print("FINAL: BTC vs ETH vs SOL (V2 + filters)")
    print("=" * 92)
    btc_ref = {  # из etap_123
        "F0: baseline": (222, 36.9, 24.0, 4, 7),
        "F2: LONG only": (115, 42.6, 32.0, 1, 7),
        "F6: LONG + delay<60h": (85, 47.1, 35.0, 1, 7),
        "F7: EMA + LONG + delay<60h": (27, 59.3, 21.0, 0, 6),
        "F12: EMA pro OR LONG": (138, 43.5, 42.0, 2, 7),
    }
    print(f"  {'Filter':<32} {'symbol':<8} {'n':>4} {'WR':>5} {'PnL':>8} {'bad':>5}")
    print("  " + "-"*72)
    for label in ["F0: baseline", "F2: LONG only", "F6: LONG + delay<60h",
                   "F7: EMA + LONG + delay<60h", "F12: EMA pro OR LONG"]:
        bn, bwr, bpnl, bbad, byr = btc_ref[label]
        print(f"  {label:<32} {'BTC':<8} {bn:>4d} {bwr:>4.1f}% {bpnl:>+7.1f}R {bbad}/{byr}")
        for sym in ["ETHUSDT", "SOLUSDT"]:
            row = next((r for r in results[sym] if r["label"] == label), None)
            if row:
                print(f"  {' ':<32} {sym:<8} {row['n']:>4d} {row['wr']:>4.1f}% "
                      f"{row['pnl']:>+7.1f}R {row['bad']}/{row['n_yrs']}")
        print()


if __name__ == "__main__":
    main()
