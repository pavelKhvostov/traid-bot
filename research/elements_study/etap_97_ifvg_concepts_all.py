"""Этап 97: тестирование всех 7 концепций iFVG.

Период: BTC 2024-01-01 to 2026-05-13 (~28 месяцев).

C1: Failed iFVG (double inversion) — standalone
C2: iFVG anti-filter for 1.1.4 BFJK
C3: iFVG as TP target — SKIPPED (требует кастомный simulator)
C4: iFVG count regime filter for 1.1.4 BFJK
C5: 1.1.7 + FVG-A age filter
C6: 1.1.7 + maxV-1d confluence filter
C7: 1.1.7 breakout entry (no retest)
C8: iFVG sequence patterns — SKIPPED (требует FSM)
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


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    _sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_e93 = _load_module("etap93_core", str(_Path(__file__).parent / "etap_93_inverse_fvg.py"))
_e95 = _load_module("etap95_core", str(_Path(__file__).parent / "etap_95_strategy_117_ifvg.py"))
_e66 = _e95._e66

SYMBOL = "BTCUSDT"
START_DATE = "2024-01-01"


# =================== C1: Failed iFVG ===================

def detect_failed_ifvg(df_top, df_1h, df_15m, df_1m, top_tf, allow_multi=3):
    """Failed iFVG: цена пробивает B обратно через A.

    После c2 iFVG-B ждём CLOSE через противоположную границу B.
    Это означает что iFVG не сработал — fade.

    Trade direction = A.direction (opposite of B).
    SL = противоположная сторона B + buffer
    """
    df_top_reset = df_top.reset_index().rename(columns={"open_time": "time"})
    df_top_reset.set_index("time", inplace=True)
    ifvg_results = _e93.find_inverse_fvgs(df_top_reset)
    if not ifvg_results: return []

    top_tf_hours = 4 if top_tf == "4h" else 24
    setups = []
    obs_1h = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
    fvgs_15m = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")
    obs_1h_sorted = sorted(obs_1h, key=lambda x: x["prev_time"])
    fvgs_15m_sorted = sorted(fvgs_15m, key=lambda x: x["c0_time"])

    for A, B, touch_idx in ifvg_results:
        b_close_time = B.c2_time + pd.Timedelta(hours=top_tf_hours)
        # Trade in A direction (fade B)
        trade_dir = A.direction

        # Ждём failure: для bear B (trade LONG) — close above B.top на 1h
        df_h = df_1h[(df_1h.index >= b_close_time) &
                       (df_1h.index < b_close_time + pd.Timedelta(days=14))]
        if df_h.empty: continue

        fail_time = None
        for k in range(len(df_h)):
            row = df_h.iloc[k]
            if trade_dir == "LONG" and row["close"] > B.top:
                fail_time = df_h.index[k] + pd.Timedelta(hours=1); break
            if trade_dir == "SHORT" and row["close"] < B.bottom:
                fail_time = df_h.index[k] + pd.Timedelta(hours=1); break
        if fail_time is None: continue

        # Now find OB-1h in trade direction after fail
        cascade_end = fail_time + pd.Timedelta(days=5)
        n_setups = 0
        for l3 in obs_1h_sorted:
            if l3["prev_time"] < fail_time: continue
            if l3["prev_time"] > cascade_end: break
            if l3["direction"] != trade_dir: continue
            # L3 should be in A direction reasonable area
            if not _e66.zones_overlap(l3["bottom"], l3["top"], A.bottom, A.top): continue

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
                f_entry = f; break

            if f_entry is None: continue

            fb, ft = f_entry["bottom"], f_entry["top"]
            b_width = B.top - B.bottom
            if trade_dir == "LONG":
                entry = fb + _e95.ENTRY_PCT * (ft - fb)
                # SL = below B (failed iFVG = was bear B, now invalid; SL under B)
                sl = B.bottom - _e95.SL_BUFFER_PCT * b_width
                if sl >= entry: continue
                sl = min(sl, entry - entry * 0.01)
            else:
                entry = ft - _e95.ENTRY_PCT * (ft - fb)
                sl = B.top + _e95.SL_BUFFER_PCT * b_width
                if sl <= entry: continue
                sl = max(sl, entry + entry * 0.01)

            setups.append({
                "fvg_b": fb, "fvg_t": ft, "direction": trade_dir,
                "entry": entry, "sl": sl,
                "signal_time": l3_close, "year": l3_close.year,
                "tf_minutes": 15, "fail_time": fail_time,
            })
            n_setups += 1
            if n_setups >= allow_multi: break

    seen = set(); out = []
    for s in setups:
        k = (s["signal_time"], s["direction"], round(s["fvg_b"], 2), round(s["fvg_t"], 2))
        if k in seen: continue
        seen.add(k); out.append(s)
    return out


# =================== C2: Anti-filter for 1.1.4 ===================

def find_ifvg_against_trade(df_4h, trade_time, trade_dir, lookback_days=7):
    """Check if iFVG of opposite direction formed in last N days before trade_time."""
    cutoff_start = trade_time - pd.Timedelta(days=lookback_days)
    df_window = df_4h[(df_4h.index >= cutoff_start) & (df_4h.index <= trade_time)]
    if len(df_window) < 5: return False
    df_window_reset = df_window.reset_index().rename(columns={"open_time": "time"})
    df_window_reset.set_index("time", inplace=True)
    ifvgs = _e93.find_inverse_fvgs(df_window_reset)
    # iFVG-B with direction opposite to trade
    opposite = "SHORT" if trade_dir == "LONG" else "LONG"
    for A, B, touch in ifvgs:
        if B.direction == opposite:
            return True
    return False


# =================== C4: Regime detector ===================

def ifvg_count_last_n_days(df_4h, trade_time, days=7):
    cutoff = trade_time - pd.Timedelta(days=days)
    df_window = df_4h[(df_4h.index >= cutoff) & (df_4h.index <= trade_time)]
    if len(df_window) < 5: return 0
    df_reset = df_window.reset_index().rename(columns={"open_time": "time"})
    df_reset.set_index("time", inplace=True)
    return len(_e93.find_inverse_fvgs(df_reset))


# =================== C5/C6: 1.1.7 with extra filters ===================

def filter_ifvg_setups_by_age(setups, df_4h, min_untouched_bars=5):
    """C5: only iFVGs where FVG-A was untouched >= min_untouched_bars."""
    # Need to recompute from raw iFVG data
    # For prototype: assume setups already have access; this is simpler if computed during detection
    # Workaround: re-detect with extra meta
    df_reset = df_4h.reset_index().rename(columns={"open_time": "time"})
    df_reset.set_index("time", inplace=True)
    ifvgs = _e93.find_inverse_fvgs(df_reset)
    # Map (A.c2_idx, touch_idx) → age
    age_map = {}
    for A, B, touch in ifvgs:
        age = touch - A.c2_idx
        age_map[(B.c0_time, B.c2_time)] = age

    filtered = []
    for s in setups:
        # We need to find the iFVG-B underlying this setup
        # Setup has "signal_time" = l3_close, after B.c2_close
        # Approximate: find B such that B.c2_time < signal_time and B.direction == trade_dir
        # Closest B before signal_time
        sig_time = s["signal_time"]
        best_age = None
        for (bc0, bc2), age in age_map.items():
            if bc2 < sig_time and (sig_time - bc2) < pd.Timedelta(days=7):
                if best_age is None or age > best_age:
                    best_age = age
        if best_age is not None and best_age >= min_untouched_bars:
            filtered.append(s)
    return filtered


def filter_ifvg_by_maxv_confluence(setups, df_1m, df_1h, threshold_atr=0.3):
    """C6: keep only setups where iFVG-B overlaps maxV-1d.

    For each setup, compute maxV-1d at signal_time. Check if maxV is within
    iFVG-B zone (within threshold_atr of either border).
    """
    atr_1h = df_1h["atr14"]
    filtered = []
    for s in setups:
        sig_time = s["signal_time"]
        # Get yesterday's daily maxV
        day = sig_time.normalize() - pd.Timedelta(days=1)
        from vic_levels import calculate_vic_d
        maxV = calculate_vic_d(df_1m, day, ltf_minutes=15)
        if maxV is None: continue
        # Check confluence with our setup's "x1" zone (which IS iFVG-B zone in 1.1.7)
        # For 1.1.7 setups: x1_bottom/x1_top = B zone (we don't have them, use entry-based)
        atr_idx = atr_1h.index.searchsorted(sig_time, side="left") - 1
        atr = float(atr_1h.iloc[atr_idx]) if atr_idx >= 0 else 0
        if atr <= 0: continue
        # Confluence: maxV near entry? Or far?
        # For continuation thesis: want maxV NEAR entry (volume zone confirms structure)
        # Try: maxV within 1 ATR of entry
        if abs(s["entry"] - maxV) <= atr:
            filtered.append(s)
    return filtered


# =================== C7: Breakout entry (no retest) ===================

def detect_breakout_entry(df_top, df_1m, top_tf, allow_multi=3):
    """C7: enter at c2 close of iFVG-B without waiting for retest."""
    df_top_reset = df_top.reset_index().rename(columns={"open_time": "time"})
    df_top_reset.set_index("time", inplace=True)
    ifvg_results = _e93.find_inverse_fvgs(df_top_reset)
    if not ifvg_results: return []

    top_tf_hours = 4 if top_tf == "4h" else 24
    setups = []
    for A, B, touch_idx in ifvg_results:
        # Entry: c2 close price
        sig_time = B.c2_time + pd.Timedelta(hours=top_tf_hours)
        # Find c2 close in df_top
        if B.c2_time not in df_top.index: continue
        c2_close_price = float(df_top.loc[B.c2_time, "close"])
        # c1 high/low for SL
        c1_high = float(df_top.loc[B.c1_time, "high"])
        c1_low = float(df_top.loc[B.c1_time, "low"])

        trade_dir = B.direction
        entry = c2_close_price
        if trade_dir == "LONG":
            sl = c1_low * 0.999  # below c1 low
            if sl >= entry: continue
            sl = min(sl, entry * 0.99)
        else:
            sl = c1_high * 1.001
            if sl <= entry: continue
            sl = max(sl, entry * 1.01)

        setups.append({
            "fvg_b": entry - 0.001, "fvg_t": entry + 0.001,
            "direction": trade_dir, "entry": entry, "sl": sl,
            "signal_time": sig_time, "year": sig_time.year,
            "tf_minutes": top_tf_hours * 60,
        })

    seen = set(); out = []
    for s in setups:
        k = (s["signal_time"], s["direction"])
        if k in seen: continue
        seen.add(k); out.append(s)
    return out


# =================== Helper: evaluate ===================

def evaluate(setups, df_1m, rr=2.0):
    closed_w = closed_l = ne = nf = 0
    pnl = 0.0
    yearly = defaultdict(lambda: [0, 0, 0.0])
    for s in setups:
        o, R = _e95.simulate(s, df_1m, rr=rr)
        year = s["signal_time"].year
        if o == "win":
            closed_w += 1; pnl += R
            yearly[year][0] += 1; yearly[year][2] += R
        elif o == "loss":
            closed_l += 1; pnl += R
            yearly[year][1] += 1; yearly[year][2] += R
        elif o == "no_entry": ne += 1
        else: nf += 1
    closed = closed_w + closed_l
    wr = closed_w / closed * 100 if closed else 0
    bad = sum(1 for y, (w, l, p) in yearly.items() if p < 0)
    return {
        "n_sigs": len(setups), "closed": closed,
        "wr": wr, "total": pnl, "avg": pnl/closed if closed else 0,
        "bad": bad, "n_yrs": len(yearly),
    }


def fmt(label, m, rr):
    print(f"  {label:<55} sigs={m['n_sigs']:>4} closed={m['closed']:>4} "
          f"WR={m['wr']:>5.1f}% R={m['total']:>+7.1f} avg={m['avg']:>+5.2f} "
          f"bad={m['bad']}/{m['n_yrs']} [RR={rr}]")


def main():
    t0 = time.time()
    print("[INFO] Загрузка")
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
    for tf, df in [("4h", df_4h), ("1h", df_1h), ("15m", df_15m)]:
        df["atr14"] = _e66.compute_atr(df, 14)

    # Baseline 1.1.7 V2c reference
    baseline_setups = _e95.detect_117_setups(df_4h, df_1h, df_15m, df_1m, "4h", allow_multi=3)

    print(f"\n{'='*100}")
    print(f"7 КОНЦЕПЦИЙ iFVG — все на BTC 2024-2026, RR=2.5 (best from 1.1.7 tuning)")
    print(f"{'='*100}\n")

    print("BASELINE для сравнения:")
    m_base = evaluate(baseline_setups, df_1m, rr=2.5)
    fmt("1.1.7 V2c baseline (4h continuation, RR=2.5)", m_base, 2.5)

    # === C1: Failed iFVG ===
    print(f"\n--- C1: Failed iFVG (double inversion, fade B, trade A direction) ---")
    failed_setups = detect_failed_ifvg(df_4h, df_1h, df_15m, df_1m, "4h", allow_multi=3)
    for rr in [1.5, 2.0, 2.5]:
        m = evaluate(failed_setups, df_1m, rr=rr)
        fmt(f"C1 Failed iFVG", m, rr)

    # === C2: Anti-filter on 1.1.4 BFJK trades ===
    print(f"\n--- C2: iFVG anti-filter applied to 1.1.4 BFJK trades ---")
    csv_114 = _Path("research/elements_study/output/etap74_BFJK_fixed_portfolio.csv")
    if csv_114.exists():
        df_114 = pd.read_csv(csv_114, encoding="utf-8-sig")
        closed_114 = df_114[df_114["outcome"].isin(["win", "loss"])].copy()
        # For each trade, check iFVG against
        keep = []
        skip = []
        for idx, row in closed_114.iterrows():
            ts = pd.Timestamp(row["signal_time"])
            if ts.tz is None: ts = ts.tz_localize("UTC")
            against = find_ifvg_against_trade(df_4h, ts, row["direction"], lookback_days=7)
            if against:
                skip.append(row)
            else:
                keep.append(row)
        kept = pd.DataFrame(keep) if keep else pd.DataFrame()
        skipped = pd.DataFrame(skip) if skip else pd.DataFrame()

        def stats(df):
            if df.empty: return "empty"
            w = (df["outcome"] == "win").sum()
            wr = w/len(df)*100
            tot = df["R"].sum()
            return f"n={len(df)} WR={wr:.1f}% total={tot:+.1f}R avg={tot/len(df):+.2f}"

        print(f"  Baseline 1.1.4: {stats(closed_114)}")
        print(f"  C2 kept (no iFVG-against): {stats(kept)}")
        print(f"  C2 skipped (iFVG-against): {stats(skipped)}")

    # === C4: Regime detector ===
    print(f"\n--- C4: iFVG count regime filter on 1.1.4 BFJK ---")
    if csv_114.exists():
        df_114_with_count = closed_114.copy()
        df_114_with_count["ifvg_count_7d"] = [
            ifvg_count_last_n_days(df_4h, pd.Timestamp(row["signal_time"]).tz_convert("UTC")
                                     if pd.Timestamp(row["signal_time"]).tz else
                                     pd.Timestamp(row["signal_time"]).tz_localize("UTC"),
                                     days=7)
            for _, row in df_114_with_count.iterrows()
        ]
        # Buckets
        try:
            df_114_with_count["bucket"] = pd.qcut(df_114_with_count["ifvg_count_7d"],
                                                     q=4, duplicates="drop")
            grp = df_114_with_count.groupby("bucket", observed=True).agg(
                n=("R", "size"),
                wins=("outcome", lambda x: (x == "win").sum()),
                total=("R", "sum"),
            )
            grp["WR"] = (grp["wins"] / grp["n"] * 100).round(1)
            grp["avg"] = (grp["total"] / grp["n"]).round(3)
            print(grp.to_string())
        except Exception as e:
            print(f"  binning failed: {e}")
            # Manual bins
            for thresh in [3, 5, 7]:
                low = df_114_with_count[df_114_with_count["ifvg_count_7d"] < thresh]
                high = df_114_with_count[df_114_with_count["ifvg_count_7d"] >= thresh]
                print(f"  iFVG count < {thresh}: n={len(low)} {stats(low)}")
                print(f"  iFVG count >= {thresh}: n={len(high)} {stats(high)}")

    # === C5: 1.1.7 + FVG-A age filter ===
    print(f"\n--- C5: 1.1.7 + FVG-A age filter (min untouched bars) ---")
    for min_age in [5, 10, 20, 50]:
        filtered = filter_ifvg_setups_by_age(baseline_setups, df_4h, min_untouched_bars=min_age)
        m = evaluate(filtered, df_1m, rr=2.5)
        fmt(f"C5 age >= {min_age} bars", m, 2.5)

    # === C6: 1.1.7 + maxV confluence ===
    print(f"\n--- C6: 1.1.7 + maxV-1d confluence (entry within 1 ATR of maxV) ---")
    try:
        filtered_c6 = filter_ifvg_by_maxv_confluence(baseline_setups, df_1m, df_1h)
        m = evaluate(filtered_c6, df_1m, rr=2.5)
        fmt(f"C6 maxV confluence", m, 2.5)
    except Exception as e:
        print(f"  C6 error: {e}")

    # === C7: Breakout entry no retest ===
    print(f"\n--- C7: Breakout entry on c2 close (no retest, no L3/L4) ---")
    breakout_setups = detect_breakout_entry(df_4h, df_1m, "4h", allow_multi=1)
    for rr in [1.5, 2.0, 2.5, 3.0]:
        m = evaluate(breakout_setups, df_1m, rr=rr)
        fmt(f"C7 breakout c2 entry", m, rr)

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
