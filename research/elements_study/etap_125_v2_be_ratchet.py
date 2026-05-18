"""etap_125: BE-ratchet trail на V2 F12 (best PnL filter).

Идея: после MFE ≥ +1R → SL→entry (break-even). После MFE ≥ +2R → выход по TP.
TP=2R остаётся, но losing trades могут стать BE.

Гипотеза: для counter-trend reversal trades drawdown часто значительный,
после прибыли price может откатываться к SL. BE-ratchet защищает.
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

_E124 = Path(__file__).parent / "etap_124_v2_floating_tp.py"
_spec = _ilu.spec_from_file_location("etap124_core", _E124)
_e124 = _ilu.module_from_spec(_spec); _sys.modules["etap124_core"] = _e124
_spec.loader.exec_module(_e124)

_E122 = Path(__file__).parent / "etap_122_v2_forensic.py"
_spec122 = _ilu.spec_from_file_location("etap122_core", _E122)
_e122 = _ilu.module_from_spec(_spec122); _sys.modules["etap122_core"] = _e122
_spec122.loader.exec_module(_e122)

_E121 = Path(__file__).parent / "etap_121_wicked_fractal_ob.py"
_spec121 = _ilu.spec_from_file_location("etap121_core", _E121)
_e121 = _ilu.module_from_spec(_spec121); _sys.modules["etap121_core"] = _e121
_spec121.loader.exec_module(_e121)

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
RR = 2.0
MAX_HOLD_DAYS = 7


def simulate_be_ratchet(setup, df_1m, be_trigger_R=1.0, rr=RR):
    """BE-ratchet: after MFE >= be_trigger_R, move SL to entry. TP fixed."""
    direction = setup["direction"]; entry = setup["entry"]; sl = setup["sl"]
    risk = abs(entry - sl)
    if risk <= 0: return ("invalid", 0.0)
    tp = entry + rr*risk if direction == "LONG" else entry - rr*risk
    start = setup["signal_time"]
    end = start + pd.Timedelta(days=MAX_HOLD_DAYS)
    et64 = np.datetime64(start.tz_localize(None) if start.tz else start)
    ee64 = np.datetime64(end.tz_localize(None) if end.tz else end)
    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0: return ("no_data", 0.0)
    h = df_1m["high"].values[i0:i1].astype(np.float64)
    l = df_1m["low"].values[i0:i1].astype(np.float64)
    n = len(h)

    # wait for entry fill
    if direction == "LONG":
        ent = np.where(l <= entry)[0]
        tp_pre = np.where(h >= tp)[0]
    else:
        ent = np.where(h >= entry)[0]
        tp_pre = np.where(l <= tp)[0]
    ent_i = int(ent[0]) if ent.size else n + 1
    tp_pre_i = int(tp_pre[0]) if tp_pre.size else n + 1
    if tp_pre_i < ent_i: return ("no_entry", 0.0)
    if ent_i >= n: return ("not_filled", 0.0)

    post_h = h[ent_i:]; post_l = l[ent_i:]
    current_sl = sl
    triggered_be = False
    for j in range(len(post_h)):
        if direction == "LONG":
            mfe = post_h[j]
            mfe_R = (mfe - entry) / risk
            if mfe_R >= be_trigger_R and not triggered_be:
                current_sl = max(current_sl, entry)  # move to BE
                triggered_be = True
            if post_l[j] <= current_sl:
                if triggered_be:
                    return ("flat", 0.0)  # BE hit
                else:
                    return ("loss", -1.0)
            if post_h[j] >= tp:
                return ("win", rr)
        else:
            mfe = post_l[j]
            mfe_R = (entry - mfe) / risk
            if mfe_R >= be_trigger_R and not triggered_be:
                current_sl = min(current_sl, entry)
                triggered_be = True
            if post_h[j] >= current_sl:
                if triggered_be:
                    return ("flat", 0.0)
                else:
                    return ("loss", -1.0)
            if post_l[j] <= tp:
                return ("win", rr)
    return ("open", 0.0)


def main():
    print("etap_125: BE-ratchet on V2 (BTC 6.3y)")
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

    wf_1d = _e121.collect_wicked_fractal_obs(df_1d, 24)
    wf_12h = _e121.collect_wicked_fractal_obs(df_12h, 12)
    raw = []
    for ob_list, df_l1 in [(wf_1d, df_1d), (wf_12h, df_12h)]:
        for ob_d in ob_list:
            touch_t, inval_t = _e121.find_first_touch_and_invalidation(ob_d, df_l1)
            if touch_t is None: continue
            if inval_t is None: inval_t = ob_d.cur_close + pd.Timedelta(days=21)
            s = _e122.react_v2_detailed(ob_d, touch_t, inval_t, df_15m, df_20m)
            if s is None: continue
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

    # filters
    def f_ema(t): return t["ema_pro"]
    def f_long(t): return t["direction"] == "LONG"
    def f_delay(t): return t["touch_delay_h"] < 60
    filters = [
        ("F0: baseline", lambda t: True),
        ("F2: LONG only", f_long),
        ("F6: LONG + delay<60h", lambda t: f_long(t) and f_delay(t)),
        ("F7: EMA + LONG + delay<60h", lambda t: f_ema(t) and f_long(t) and f_delay(t)),
        ("F12: EMA pro OR LONG", lambda t: f_ema(t) or f_long(t)),
    ]

    print(f"  {'Filter':<32} {'mode':<14} {'n':>4} {'W':>3} {'BE':>3} {'L':>3} {'WR':>5} {'PnL':>8} {'bad':>5}")
    print("  " + "-"*100)
    for f_label, f_fn in filters:
        filtered = [s for s in setups if f_fn(s)]
        # baseline
        rows_b = []
        for s in filtered:
            outc, R, _ = _e124.simulate_baseline_rr(s, df_1m)
            if outc in ("win", "loss"):
                rows_b.append({"R": R, "year": s["signal_time"].year, "outc": outc})
        # BE-ratchet @+1R
        rows_be1 = []
        for s in filtered:
            outc, R = simulate_be_ratchet(s, df_1m, be_trigger_R=1.0)
            if outc in ("win", "loss", "flat"):
                rows_be1.append({"R": R, "year": s["signal_time"].year, "outc": outc})
        # BE-ratchet @+1.5R
        rows_be15 = []
        for s in filtered:
            outc, R = simulate_be_ratchet(s, df_1m, be_trigger_R=1.5)
            if outc in ("win", "loss", "flat"):
                rows_be15.append({"R": R, "year": s["signal_time"].year, "outc": outc})

        for mode, rows in [("baseline RR=2.0", rows_b),
                            ("BE-ratchet@1R", rows_be1),
                            ("BE-ratchet@1.5R", rows_be15)]:
            n = len(rows)
            if n == 0:
                print(f"  {f_label:<32} {mode:<14} {0:>4d}  no data"); continue
            W = sum(1 for r in rows if r["R"] > 0)
            BE = sum(1 for r in rows if r["outc"] == "flat")
            L = sum(1 for r in rows if r["R"] < 0)
            wr = W / n * 100
            pnl = sum(r["R"] for r in rows)
            yr_map = defaultdict(float)
            for r in rows: yr_map[r["year"]] += r["R"]
            bad = sum(1 for v in yr_map.values() if v < 0)
            print(f"  {f_label:<32} {mode:<14} {n:>4d} {W:>3d} {BE:>3d} {L:>3d} "
                  f"{wr:>4.1f}% {pnl:>+7.1f}R {bad}/{len(yr_map)}")


if __name__ == "__main__":
    main()
