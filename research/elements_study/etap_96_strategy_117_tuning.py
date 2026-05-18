"""Этап 96: тюнинг Strategy 1.1.7 — variations.

Variations:
  A: RR sweep [1.5, 1.8, 2.0, 2.5]
  B: INVERSE direction (trade IN A direction = fade iFVG-B)
  C: strict retest L2 (price must leave B and return)
  D: 4h only (skip 1d)
  E: + Hull-4h(L78) aligned filter
  F: + ViC delta-4h aligned with B direction (or A direction if inverse)
  G: + anti-flat-zone (|norm_4h| > 0.05)

Cell tests:
  V1: baseline (1.1.7 v1 = 4h+1d, RR=2.0)
  V2: D + A_rr15 (4h only, RR=1.5)
  V3: B (inverse direction)
  V4: D + E (Hull-4h)
  V5: D + F (ViC delta)
  V6: D + E + F (Hull + ViC)
  V7: D + G (anti-flat)
  V8: D + C (strict retest)
  V9: D + E + F + G (best combo guess)
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from collections import defaultdict
import time
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df

import importlib.util
_spec95 = importlib.util.spec_from_file_location(
    "etap95_core", str(_Path(__file__).parent / "etap_95_strategy_117_ifvg.py"))
_e95 = importlib.util.module_from_spec(_spec95)
_sys.modules["etap95_core"] = _e95
_spec95.loader.exec_module(_e95)

_spec67 = importlib.util.spec_from_file_location(
    "etap67_core", str(_Path(__file__).parent / "etap_67_114_filter_grid_BF.py"))
_e67 = importlib.util.module_from_spec(_spec67)
_sys.modules["etap67_core"] = _e67
_spec67.loader.exec_module(_e67)

_e66 = _e95._e66
_e93 = _e95._e93

SYMBOL = "BTCUSDT"
START_DATE = "2024-01-01"


def hull_label_at(series, ts):
    """SAFE label lookup at ts — last closed bar."""
    if len(series) == 0: return "na"
    idx = series.index.searchsorted(ts, side="left") - 1
    if idx < 0 or idx >= len(series): return "na"
    v = series.iloc[idx]
    if pd.isna(v): return "na"
    return v


def hull_align(label, direction):
    if label == "na": return "na"
    is_up = label == "up"
    if direction == "LONG":
        return "aligned" if is_up else "counter"
    return "aligned" if not is_up else "counter"


def compute_vic_delta_4h(df_1m, ts):
    """ViC delta on prev 4h bar before ts."""
    bar_open = ts.floor("4h") - pd.Timedelta(hours=4)
    bar_end = bar_open + pd.Timedelta(hours=4)
    win = df_1m[(df_1m.index >= bar_open) & (df_1m.index < bar_end)]
    if win.empty: return 0.0, 0.0
    bull = win[win["close"] > win["open"]]
    bear = win[win["close"] < win["open"]]
    bullV = float(bull["volume"].sum()) if not bull.empty else 0.0
    bearV = float(bear["volume"].sum()) if not bear.empty else 0.0
    vol = bullV + bearV
    norm = (bullV - bearV) / vol if vol > 0 else 0.0
    return bullV - bearV, norm


def detect_with_retest(df_top, df_1h, df_15m, df_1m, top_tf, allow_multi=3):
    """Strict retest L2: цена должна уйти из B и вернуться."""
    df_top_reset = df_top.reset_index().rename(columns={"open_time": "time"})
    df_top_reset.set_index("time", inplace=True)
    ifvg_results = _e93.find_inverse_fvgs(df_top_reset)
    if not ifvg_results: return []

    setups = []
    top_tf_hours = 4 if top_tf == "4h" else 24
    retest_window_days = 5 if top_tf == "4h" else 14

    obs_1h = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
    fvgs_15m = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")
    obs_1h_sorted = sorted(obs_1h, key=lambda x: x["prev_time"])
    fvgs_15m_sorted = sorted(fvgs_15m, key=lambda x: x["c0_time"])

    for A, B, touch_idx in ifvg_results:
        b_c2_time = B.c2_time
        b_close_time = b_c2_time + pd.Timedelta(hours=top_tf_hours)
        cascade_end = b_close_time + pd.Timedelta(days=retest_window_days)
        trade_dir = B.direction
        b_bot, b_top = B.bottom, B.top

        # STRICT RETEST: цена должна уйти из B на 1 ATR хотя бы, потом вернуться
        # На 1h уровне. Берём бары в окне [b_close, cascade_end]
        df_h = df_1h[(df_1h.index >= b_close_time) & (df_1h.index < cascade_end)]
        if df_h.empty: continue

        # Find when price first leaves B (> 1 ATR away)
        atr_at_b = df_1h["atr14"].asof(b_close_time)
        if pd.isna(atr_at_b) or atr_at_b <= 0: continue

        left_zone_idx = None
        for k in range(len(df_h)):
            row = df_h.iloc[k]
            # For SHORT (B bear): we want price to first go DOWN below B
            if trade_dir == "SHORT" and row["low"] < b_bot - atr_at_b:
                left_zone_idx = k; break
            if trade_dir == "LONG" and row["high"] > b_top + atr_at_b:
                left_zone_idx = k; break
        if left_zone_idx is None: continue

        # Now find when price returns to B zone after leaving
        return_idx = None
        for k in range(left_zone_idx + 1, len(df_h)):
            row = df_h.iloc[k]
            if trade_dir == "SHORT" and row["high"] >= b_bot:
                return_idx = k; break
            if trade_dir == "LONG" and row["low"] <= b_top:
                return_idx = k; break
        if return_idx is None: continue

        retest_time = df_h.index[return_idx]

        # Find OB-1h after retest
        n_setups = 0
        for l3 in obs_1h_sorted:
            if l3["prev_time"] < retest_time: continue
            if l3["prev_time"] > cascade_end: break
            if l3["direction"] != trade_dir: continue
            if not _e66.zones_overlap(l3["bottom"], l3["top"], b_bot, b_top): continue

            l3_close = l3["time"] + pd.Timedelta(hours=1)
            entry_td = pd.Timedelta(minutes=15)
            l4_max_c2 = l3_close - entry_td

            f_entry = None
            for f in fvgs_15m_sorted:
                if f["c0_time"] < l3["prev_time"]: continue
                if f["time"] > l4_max_c2: continue
                if f["c0_time"] > l3_close: break
                if f["direction"] != trade_dir: continue
                if not _e66.zones_overlap(f["bottom"], f["top"], l3["bottom"], l3["top"]): continue
                if not _e66.zones_overlap(f["bottom"], f["top"], b_bot, b_top): continue
                f_entry = f; break

            if f_entry is None: continue

            fb, ft = f_entry["bottom"], f_entry["top"]
            b_width = b_top - b_bot
            if trade_dir == "LONG":
                entry = fb + _e95.ENTRY_PCT * (ft - fb)
                sl = b_bot - _e95.SL_BUFFER_PCT * b_width
                if sl >= entry: continue
                sl = min(sl, entry - entry * 0.01)
            else:
                entry = ft - _e95.ENTRY_PCT * (ft - fb)
                sl = b_top + _e95.SL_BUFFER_PCT * b_width
                if sl <= entry: continue
                sl = max(sl, entry + entry * 0.01)

            setups.append({
                "fvg_b": fb, "fvg_t": ft,
                "ifvg_a_zone": (A.bottom, A.top),
                "ifvg_b_zone": (b_bot, b_top),
                "direction": trade_dir,
                "trade_dir": trade_dir,
                "entry": entry, "sl": sl,
                "signal_time": l3_close,
                "year": l3_close.year,
                "top_tf": top_tf,
                "tf_minutes": 15,
            })
            n_setups += 1
            if n_setups >= allow_multi: break

    # Dedup
    seen = set(); out = []
    for s in setups:
        k = (s["signal_time"], s["direction"], round(s["fvg_b"], 2), round(s["fvg_t"], 2))
        if k in seen: continue
        seen.add(k); out.append(s)
    return out


def detect_inverse(df_top, df_1h, df_15m, df_1m, top_tf, allow_multi=3):
    """Inverse direction: trade in A direction (fade iFVG-B)."""
    df_top_reset = df_top.reset_index().rename(columns={"open_time": "time"})
    df_top_reset.set_index("time", inplace=True)
    ifvg_results = _e93.find_inverse_fvgs(df_top_reset)
    if not ifvg_results: return []

    setups = []
    top_tf_hours = 4 if top_tf == "4h" else 24
    retest_window_days = 5 if top_tf == "4h" else 14

    obs_1h = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
    fvgs_15m = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")
    obs_1h_sorted = sorted(obs_1h, key=lambda x: x["prev_time"])
    fvgs_15m_sorted = sorted(fvgs_15m, key=lambda x: x["c0_time"])

    for A, B, touch_idx in ifvg_results:
        b_c2_time = B.c2_time
        b_close_time = b_c2_time + pd.Timedelta(hours=top_tf_hours)
        cascade_end = b_close_time + pd.Timedelta(days=retest_window_days)
        trade_dir = A.direction  # INVERSE: trade in A direction
        a_bot, a_top = A.bottom, A.top

        n_setups = 0
        for l3 in obs_1h_sorted:
            if l3["prev_time"] < b_close_time: continue
            if l3["prev_time"] > cascade_end: break
            if l3["direction"] != trade_dir: continue
            # L3 overlap with A zone (we expect mean revert to A)
            if not _e66.zones_overlap(l3["bottom"], l3["top"], a_bot, a_top): continue

            l3_close = l3["time"] + pd.Timedelta(hours=1)
            entry_td = pd.Timedelta(minutes=15)
            l4_max_c2 = l3_close - entry_td

            f_entry = None
            for f in fvgs_15m_sorted:
                if f["c0_time"] < l3["prev_time"]: continue
                if f["time"] > l4_max_c2: continue
                if f["c0_time"] > l3_close: break
                if f["direction"] != trade_dir: continue
                if not _e66.zones_overlap(f["bottom"], f["top"], l3["bottom"], l3["top"]): continue
                if not _e66.zones_overlap(f["bottom"], f["top"], a_bot, a_top): continue
                f_entry = f; break

            if f_entry is None: continue

            fb, ft = f_entry["bottom"], f_entry["top"]
            a_width = a_top - a_bot
            if trade_dir == "LONG":
                entry = fb + _e95.ENTRY_PCT * (ft - fb)
                sl = a_bot - _e95.SL_BUFFER_PCT * a_width
                if sl >= entry: continue
                sl = min(sl, entry - entry * 0.01)
            else:
                entry = ft - _e95.ENTRY_PCT * (ft - fb)
                sl = a_top + _e95.SL_BUFFER_PCT * a_width
                if sl <= entry: continue
                sl = max(sl, entry + entry * 0.01)

            setups.append({
                "fvg_b": fb, "fvg_t": ft,
                "direction": trade_dir,
                "trade_dir": trade_dir,
                "entry": entry, "sl": sl,
                "signal_time": l3_close,
                "year": l3_close.year,
                "top_tf": top_tf,
                "tf_minutes": 15,
            })
            n_setups += 1
            if n_setups >= allow_multi: break

    seen = set(); out = []
    for s in setups:
        k = (s["signal_time"], s["direction"], round(s["fvg_b"], 2), round(s["fvg_t"], 2))
        if k in seen: continue
        seen.add(k); out.append(s)
    return out


def evaluate(setups, df_1m, df_4h, hull_4h_lbl=None, rr=2.0,
              hull_filter=False, vic_filter=False, anti_flat_filter=False):
    """Evaluate with optional filters."""
    closed_w = closed_l = ne = nf = open_ = 0
    pnl = 0.0
    yearly = defaultdict(lambda: [0, 0, 0.0])
    for s in setups:
        # Hull-4h filter
        if hull_filter and hull_4h_lbl is not None:
            lbl = hull_label_at(hull_4h_lbl, s["signal_time"])
            if hull_align(lbl, s["direction"]) != "aligned": continue
        # ViC delta filter
        if vic_filter:
            _, norm = compute_vic_delta_4h(df_1m, s["signal_time"])
            # Аligned: norm > 0 for LONG, norm < 0 for SHORT
            if s["direction"] == "LONG" and norm < 0.05: continue
            if s["direction"] == "SHORT" and norm > -0.05: continue
        # Anti-flat: skip if |norm_4h| <= 0.05
        if anti_flat_filter:
            _, norm = compute_vic_delta_4h(df_1m, s["signal_time"])
            if abs(norm) <= 0.05: continue

        o, R = _e95.simulate(s, df_1m, rr=rr)
        year = s["signal_time"].year
        if o == "win":
            closed_w += 1; pnl += R
            yearly[year][0] += 1; yearly[year][2] += R
        elif o == "loss":
            closed_l += 1; pnl += R
            yearly[year][1] += 1; yearly[year][2] += R
        elif o == "no_entry": ne += 1
        elif o == "open": open_ += 1
        else: nf += 1
    closed = closed_w + closed_l
    wr = closed_w / closed * 100 if closed else 0
    bad = sum(1 for y, (w, l, p) in yearly.items() if p < 0)
    return {
        "n_sigs": len(setups), "closed": closed, "wins": closed_w, "losses": closed_l,
        "ne": ne, "wr": wr, "total": pnl, "avg": pnl/closed if closed else 0,
        "bad": bad, "n_yrs": len(yearly), "yearly": dict(yearly),
    }


def main():
    t0 = time.time()
    print("[INFO] Загрузка данных")
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_1m = load_df(SYMBOL, "1m")
    df_15m = compose_from_base(df_1m, "15m")

    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_4h = df_4h[df_4h.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]

    for tf, df in [("1d", df_1d), ("4h", df_4h), ("1h", df_1h), ("15m", df_15m)]:
        df["atr14"] = _e66.compute_atr(df, 14)

    # Hull-4h L78 для filter E
    print("[INFO] Computing Hull-4h(L78)")
    hull_4h = _e67.hull_ma(df_4h["close"], 78)
    hull_4h_lbl = _e67.hull_label_series(df_4h["close"], hull_4h)

    print("\n[INFO] Detect baseline iFVG-4h setups")
    setups_4h = _e95.detect_117_setups(df_4h, df_1h, df_15m, df_1m, "4h", allow_multi=3)
    print(f"  iFVG-4h: {len(setups_4h)}")

    print("[INFO] Detect with strict retest (variant C)")
    setups_4h_retest = detect_with_retest(df_4h, df_1h, df_15m, df_1m, "4h", allow_multi=3)
    print(f"  iFVG-4h strict retest: {len(setups_4h_retest)}")

    print("[INFO] Detect inverse direction (variant B)")
    setups_4h_inv = detect_inverse(df_4h, df_1h, df_15m, df_1m, "4h", allow_multi=3)
    print(f"  iFVG-4h INVERSE: {len(setups_4h_inv)}")

    # Evaluate variations
    print(f"\n{'='*92}")
    print(f"VARIATIONS: Strategy 1.1.7 tuning grid (BTC 2024-2026)")
    print(f"{'='*92}")
    print(f"  {'Variant':<35} {'sigs':>5} {'closed':>7} {'WR':>6} {'total':>8} {'avg':>7} {'bad':>5}")

    variations = [
        ("V1: baseline (4h, RR=2.0)", setups_4h, 2.0, False, False, False),
        ("V2: 4h RR=1.5", setups_4h, 1.5, False, False, False),
        ("V2b: 4h RR=1.8", setups_4h, 1.8, False, False, False),
        ("V2c: 4h RR=2.5", setups_4h, 2.5, False, False, False),
        ("V3: INVERSE (fade B), RR=2.0", setups_4h_inv, 2.0, False, False, False),
        ("V3b: INVERSE RR=1.5", setups_4h_inv, 1.5, False, False, False),
        ("V4: 4h + Hull-4h aligned, RR=2", setups_4h, 2.0, True, False, False),
        ("V4b: 4h + Hull RR=1.5", setups_4h, 1.5, True, False, False),
        ("V5: 4h + ViC delta aligned, RR=2", setups_4h, 2.0, False, True, False),
        ("V6: 4h + Hull + ViC, RR=2", setups_4h, 2.0, True, True, False),
        ("V7: 4h + anti-flat-norm, RR=2", setups_4h, 2.0, False, False, True),
        ("V8: 4h strict retest, RR=2", setups_4h_retest, 2.0, False, False, False),
        ("V8b: 4h strict retest RR=1.5", setups_4h_retest, 1.5, False, False, False),
        ("V9: ALL filters (Hull+ViC+flat) RR=2", setups_4h, 2.0, True, True, True),
        ("V9b: ALL filters RR=1.5", setups_4h, 1.5, True, True, True),
    ]

    results = []
    for label, sets, rr, hull, vic, anti_flat in variations:
        m = evaluate(sets, df_1m, df_4h, hull_4h_lbl, rr=rr,
                      hull_filter=hull, vic_filter=vic, anti_flat_filter=anti_flat)
        results.append((label, m))
        flag = ""
        if m["closed"] > 0:
            if m["wr"] > 50 and m["avg"] > 0.3: flag = "**"
            elif m["wr"] > 45 and m["avg"] > 0: flag = "*"
        print(f"  {label:<35} {m['n_sigs']:>5} {m['closed']:>7} "
              f"{m['wr']:>5.1f}% {m['total']:>+7.1f}R {m['avg']:>+6.2f} "
              f"{m['bad']:>2}/{m['n_yrs']} {flag}")

    # Best variant year-by-year
    print(f"\n--- Year breakdown for top 3 by total R ---")
    top3 = sorted(results, key=lambda r: r[1]["total"], reverse=True)[:3]
    for label, m in top3:
        print(f"\n  {label}: closed={m['closed']}, WR={m['wr']:.1f}%, total={m['total']:+.1f}R")
        for yr in sorted(m["yearly"].keys()):
            w, l, p = m["yearly"][yr]
            n = w + l
            if n == 0: continue
            print(f"    {yr}: n={n} WR={w/n*100:.1f}% R={p:+.1f}")

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
