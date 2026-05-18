"""etap_121: Wicked OB + Fractal на prev (i-1) + правильная геометрия.

Усиление etap_119:
1. Wicked filter: cur wick < prev wick / 2 (как было)
2. NEW: prev (i-1) должна быть fractal — LL для LONG OB, HH для SHORT OB
   - Fractal 5-bar: low(i-1) < low(i-3, i-2, i, i+1) для LL
3. FIX: geometry check на any_edge_inside (как canonical 1.1.4), не overlap

Fractal на prev требует бар i+1 → OB активна с конца бара i+1 (лаг 1 бар).

5 реакций (same as etap_119):
  V1: OB-1h/2h + FVG-15m/20m inside (standard)
  V2: FVG-entry only
  V3: RDRB-htf
  V4: OB-htf only
  V5: Marubozu-15m
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
import importlib.util as _ilu
from dataclasses import dataclass
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists(): _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path: _sys.path.insert(0, str(_ROOT))

from collections import defaultdict
from pathlib import Path
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg
from strategies.strategy_rdrb import detect_rdrb

_E119 = Path(__file__).parent / "etap_119_wicked_ob_reactions.py"
_spec = _ilu.spec_from_file_location("etap119_core", _E119)
_e119 = _ilu.module_from_spec(_spec); _sys.modules["etap119_core"] = _e119
_spec.loader.exec_module(_e119)

WickedOB = _e119.WickedOB
find_first_touch_and_invalidation = _e119.find_first_touch_and_invalidation
simulate = _e119.simulate

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
ENTRY_PCT = 0.70
SL_PCT = 0.35
RR = 2.0
MIN_SL_PCT = 1.0
MAX_HOLD_DAYS = 7


def any_edge_inside(b1, t1, b2, t2):
    """Любой край b1/t1 попадает в [b2, t2]."""
    return (b2 <= b1 <= t2) or (b2 <= t1 <= t2)


def detect_wicked_fractal_ob(df, idx, tf_hours):
    """OB-пара с wick filter + fractal на prev (i-1)."""
    if idx < 3 or idx + 1 >= len(df): return None  # need i-3..i+1
    prev = df.iloc[idx - 1]
    cur = df.iloc[idx]
    po, pc = float(prev["open"]), float(prev["close"])
    pl, ph = float(prev["low"]), float(prev["high"])
    co, cc = float(cur["open"]), float(cur["close"])
    cl, ch = float(cur["low"]), float(cur["high"])

    # Common fractal context
    l_m3 = float(df.iloc[idx - 3]["low"]); l_m2 = float(df.iloc[idx - 2]["low"])
    l_i = cl; l_p1 = float(df.iloc[idx + 1]["low"])
    h_m3 = float(df.iloc[idx - 3]["high"]); h_m2 = float(df.iloc[idx - 2]["high"])
    h_i = ch; h_p1 = float(df.iloc[idx + 1]["high"])

    # LONG OB: prev bearish + cur close > prev open + wick + LL fractal on prev
    if pc < po and cc > po:
        prev_wick = pc - pl
        cur_wick = min(co, cc) - cl
        if prev_wick <= 0: return None
        if cur_wick >= prev_wick / 2: return None
        # LL fractal at i-1: pl < l_m3, l_m2, l_i, l_p1
        is_ll = (pl < l_m3 and pl < l_m2 and pl < l_i and pl < l_p1)
        if not is_ll: return None
        ratio = cur_wick / prev_wick
        return WickedOB(direction="LONG", bottom=min(pl, cl), top=po,
                        prev_time=df.index[idx - 1], cur_time=df.index[idx],
                        cur_close=df.index[idx + 1] + pd.Timedelta(hours=tf_hours),  # +1 bar для fractal confirm
                        tf_hours=tf_hours, wick_ratio=ratio)

    # SHORT OB: prev bullish + cur close < prev open + wick + HH fractal on prev
    if pc > po and cc < po:
        prev_wick = ph - pc
        cur_wick = ch - max(co, cc)
        if prev_wick <= 0: return None
        if cur_wick >= prev_wick / 2: return None
        is_hh = (ph > h_m3 and ph > h_m2 and ph > h_i and ph > h_p1)
        if not is_hh: return None
        ratio = cur_wick / prev_wick
        return WickedOB(direction="SHORT", bottom=po, top=max(ph, ch),
                        prev_time=df.index[idx - 1], cur_time=df.index[idx],
                        cur_close=df.index[idx + 1] + pd.Timedelta(hours=tf_hours),
                        tf_hours=tf_hours, wick_ratio=ratio)
    return None


def collect_wicked_fractal_obs(df, tf_hours):
    out = []
    for idx in range(3, len(df) - 1):
        w = detect_wicked_fractal_ob(df, idx, tf_hours)
        if w is not None: out.append(w)
    return out


# Reaction detectors (используем any_edge_inside)
def react_v1(ob_d, touch_t, inval_t, df_1h, df_2h, df_15m, df_20m):
    for df_htf, htf_h, label in [(df_1h, 1, "1h"), (df_2h, 2, "2h")]:
        df_w = df_htf[(df_htf.index >= touch_t) & (df_htf.index < inval_t)]
        for i in range(1, len(df_w)):
            cand = detect_ob_pair(df_w, i)
            if cand is None or cand.direction != ob_d.direction: continue
            if not any_edge_inside(cand.bottom, cand.top, ob_d.bottom, ob_d.top): continue
            for df_ltf, tf_min, tf_label in [(df_15m, 15, "15m"), (df_20m, 20, "20m")]:
                end_t = cand.cur_time + pd.Timedelta(minutes=htf_h * 60 - tf_min)
                df_l = df_ltf[(df_ltf.index >= cand.prev_time) & (df_ltf.index <= end_t)]
                for k in range(2, len(df_l)):
                    fvg = detect_fvg(df_l, k)
                    if fvg is None or fvg.direction != ob_d.direction: continue
                    if not any_edge_inside(fvg.bottom, fvg.top, cand.bottom, cand.top): continue
                    fb, ft = fvg.bottom, fvg.top
                    if ob_d.direction == "LONG":
                        entry = fb + ENTRY_PCT * (ft - fb)
                        sl = cand.bottom + SL_PCT * (fb - cand.bottom)
                    else:
                        entry = ft - ENTRY_PCT * (ft - fb)
                        sl = cand.top - SL_PCT * (cand.top - ft)
                    if MIN_SL_PCT > 0:
                        d = entry * MIN_SL_PCT / 100
                        if ob_d.direction == "LONG":
                            sl = min(sl, entry - d)
                        else:
                            sl = max(sl, entry + d)
                    if abs(entry - sl) <= 0: continue
                    if (ob_d.direction == "LONG" and sl >= entry) or (ob_d.direction == "SHORT" and sl <= entry):
                        continue
                    return {"entry": entry, "sl": sl, "direction": ob_d.direction,
                            "signal_time": fvg.c2_time + pd.Timedelta(minutes=tf_min),
                            "reaction_tf": f"OB-{label}+FVG-{tf_label}"}
    return None


def react_v2(ob_d, touch_t, inval_t, df_15m, df_20m):
    for df_ltf, tf_min, tf_label in [(df_15m, 15, "15m"), (df_20m, 20, "20m")]:
        df_w = df_ltf[(df_ltf.index >= touch_t) & (df_ltf.index < inval_t)]
        for k in range(2, len(df_w)):
            fvg = detect_fvg(df_w, k)
            if fvg is None or fvg.direction != ob_d.direction: continue
            if not any_edge_inside(fvg.bottom, fvg.top, ob_d.bottom, ob_d.top): continue
            fb, ft = fvg.bottom, fvg.top
            if ob_d.direction == "LONG":
                entry = fb + ENTRY_PCT * (ft - fb)
                sl = ob_d.bottom + SL_PCT * (fb - ob_d.bottom)
            else:
                entry = ft - ENTRY_PCT * (ft - fb)
                sl = ob_d.top - SL_PCT * (ob_d.top - ft)
            if MIN_SL_PCT > 0:
                d = entry * MIN_SL_PCT / 100
                if ob_d.direction == "LONG":
                    sl = min(sl, entry - d)
                else:
                    sl = max(sl, entry + d)
            if abs(entry - sl) <= 0: continue
            if (ob_d.direction == "LONG" and sl >= entry) or (ob_d.direction == "SHORT" and sl <= entry):
                continue
            return {"entry": entry, "sl": sl, "direction": ob_d.direction,
                    "signal_time": fvg.c2_time + pd.Timedelta(minutes=tf_min),
                    "reaction_tf": f"FVG-{tf_label}"}
    return None


def react_v3(ob_d, touch_t, inval_t, df_1h, df_2h):
    for df_htf, htf_h, label in [(df_1h, 1, "1h"), (df_2h, 2, "2h")]:
        df_w = df_htf[(df_htf.index >= touch_t) & (df_htf.index < inval_t)]
        for k in range(2, len(df_w)):
            r = detect_rdrb(df_w, k)
            if r is None or r.direction != ob_d.direction: continue
            if not any_edge_inside(r.bottom, r.top, ob_d.bottom, ob_d.top): continue
            entry = (r.bottom + r.top) / 2
            if ob_d.direction == "LONG":
                sl = ob_d.bottom + SL_PCT * (entry - ob_d.bottom)
            else:
                sl = ob_d.top - SL_PCT * (ob_d.top - entry)
            if MIN_SL_PCT > 0:
                d = entry * MIN_SL_PCT / 100
                if ob_d.direction == "LONG":
                    sl = min(sl, entry - d)
                else:
                    sl = max(sl, entry + d)
            if abs(entry - sl) <= 0: continue
            if (ob_d.direction == "LONG" and sl >= entry) or (ob_d.direction == "SHORT" and sl <= entry):
                continue
            return {"entry": entry, "sl": sl, "direction": ob_d.direction,
                    "signal_time": df_w.index[k] + pd.Timedelta(hours=htf_h),
                    "reaction_tf": f"RDRB-{label}"}
    return None


def react_v4(ob_d, touch_t, inval_t, df_1h, df_2h):
    for df_htf, htf_h, label in [(df_1h, 1, "1h"), (df_2h, 2, "2h")]:
        df_w = df_htf[(df_htf.index >= touch_t) & (df_htf.index < inval_t)]
        for k in range(1, len(df_w)):
            cand = detect_ob_pair(df_w, k)
            if cand is None or cand.direction != ob_d.direction: continue
            if not any_edge_inside(cand.bottom, cand.top, ob_d.bottom, ob_d.top): continue
            entry = (cand.bottom + cand.top) / 2
            if ob_d.direction == "LONG":
                sl = ob_d.bottom + SL_PCT * (entry - ob_d.bottom)
            else:
                sl = ob_d.top - SL_PCT * (ob_d.top - entry)
            if MIN_SL_PCT > 0:
                d = entry * MIN_SL_PCT / 100
                if ob_d.direction == "LONG":
                    sl = min(sl, entry - d)
                else:
                    sl = max(sl, entry + d)
            if abs(entry - sl) <= 0: continue
            if (ob_d.direction == "LONG" and sl >= entry) or (ob_d.direction == "SHORT" and sl <= entry):
                continue
            return {"entry": entry, "sl": sl, "direction": ob_d.direction,
                    "signal_time": cand.cur_time + pd.Timedelta(hours=htf_h),
                    "reaction_tf": f"OB-{label}_only"}
    return None


def react_v5(ob_d, touch_t, inval_t, df_15m):
    df_w = df_15m[(df_15m.index >= touch_t) & (df_15m.index < inval_t)]
    for k in range(len(df_w)):
        row = df_w.iloc[k]
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        rng = h - l
        if rng <= 0: continue
        body = abs(c - o)
        if body / rng < 0.95: continue
        direction = "LONG" if c > o else ("SHORT" if c < o else None)
        if direction != ob_d.direction: continue
        zb, zt = (o, c) if direction == "LONG" else (c, o)
        if not any_edge_inside(zb, zt, ob_d.bottom, ob_d.top): continue
        entry = (zb + zt) / 2
        if ob_d.direction == "LONG":
            sl = ob_d.bottom + SL_PCT * (entry - ob_d.bottom)
        else:
            sl = ob_d.top - SL_PCT * (ob_d.top - entry)
        if MIN_SL_PCT > 0:
            d = entry * MIN_SL_PCT / 100
            if ob_d.direction == "LONG":
                sl = min(sl, entry - d)
            else:
                sl = max(sl, entry + d)
        if abs(entry - sl) <= 0: continue
        if (ob_d.direction == "LONG" and sl >= entry) or (ob_d.direction == "SHORT" and sl <= entry):
            continue
        return {"entry": entry, "sl": sl, "direction": ob_d.direction,
                "signal_time": df_w.index[k] + pd.Timedelta(minutes=15),
                "reaction_tf": "Marubozu-15m"}
    return None


def main():
    print("etap_121: Wicked + Fractal-on-prev OB-D/12h + 5 reactions (BTC 6.3y)")
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

    print("[INFO] collecting wicked+fractal OBs")
    wf_1d = collect_wicked_fractal_obs(df_1d, 24)
    wf_12h = collect_wicked_fractal_obs(df_12h, 12)
    print(f"  Wicked+Fractal 1d:  {len(wf_1d)}")
    print(f"  Wicked+Fractal 12h: {len(wf_12h)}")
    print()

    reactions = [
        ("V1: OB-htf + FVG-entry", lambda od, tt, it: react_v1(od, tt, it, df_1h, df_2h, df_15m, df_20m)),
        ("V2: FVG-entry only",      lambda od, tt, it: react_v2(od, tt, it, df_15m, df_20m)),
        ("V3: RDRB-htf",            lambda od, tt, it: react_v3(od, tt, it, df_1h, df_2h)),
        ("V4: OB-htf only",         lambda od, tt, it: react_v4(od, tt, it, df_1h, df_2h)),
        ("V5: Marubozu-15m",        lambda od, tt, it: react_v5(od, tt, it, df_15m)),
    ]

    print(f"  {'Reaction':<32} {'sigs':>4} {'closed':>6} {'WR':>5} {'PnL':>8} {'top5':>5} {'bad':>4}")
    print("  " + "-"*80)
    for r_label, r_fn in reactions:
        trades = []
        for ob_list, df_l1 in [(wf_1d, df_1d), (wf_12h, df_12h)]:
            for ob_d in ob_list:
                touch_t, inval_t = find_first_touch_and_invalidation(ob_d, df_l1)
                if touch_t is None: continue
                if inval_t is None: inval_t = ob_d.cur_close + pd.Timedelta(days=21)
                setup = r_fn(ob_d, touch_t, inval_t)
                if setup is None: continue
                outcome, R = simulate(setup, df_1m)
                setup["outcome"] = outcome; setup["R"] = R
                setup["year"] = setup["signal_time"].year
                trades.append(setup)
        seen = {}
        for t in trades:
            k = (t["signal_time"], t["direction"], round(t["entry"], 2))
            if k not in seen: seen[k] = t
        unique = list(seen.values())
        closed = [t for t in unique if t["outcome"] in ("win", "loss")]
        n = len(closed)
        if n == 0:
            print(f"  {r_label:<32} {len(unique):>4d} {n:>6d}  no data"); continue
        W = sum(1 for t in closed if t["R"] > 0)
        wr = W / n * 100
        pnl = sum(t["R"] for t in closed)
        Rs = sorted([t["R"] for t in closed], reverse=True)
        top5 = sum(Rs[:5]) / pnl * 100 if pnl > 0 else 0
        yr_map = defaultdict(float)
        for t in closed: yr_map[t["year"]] += t["R"]
        bad = sum(1 for v in yr_map.values() if v < 0)
        print(f"  {r_label:<32} {len(unique):>4d} {n:>6d} {wr:>4.1f}% {pnl:>+7.1f}R "
              f"{top5:>4.1f}% {bad}/{len(yr_map)}")


if __name__ == "__main__":
    main()
