"""Этап 95: Strategy 1.1.7 - iFVG Structural Break Cascade.

Каскад:
  L1: iFVG на 4h или 1d (FVG-A untouched, FVG-B opposite forms at first touch)
  L2: Retest zone B (1h wick касается B после c2 B)
  L3: OB-1h (any direction = B.direction) с зоной overlapping B
  L4: FVG-15m inside L3 OB

SL: external side of B + 0.5*B_width buffer
TP: RR=2.0
allow_multi: 3 каскада на одну iFVG.

Прототип на BTC 1h+15m+1m за последние 2 года.
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
_spec93 = importlib.util.spec_from_file_location(
    "etap93_core", str(_Path(__file__).parent / "etap_93_inverse_fvg.py"))
_e93 = importlib.util.module_from_spec(_spec93)
_sys.modules["etap93_core"] = _e93
_spec93.loader.exec_module(_e93)

_spec66 = importlib.util.spec_from_file_location(
    "etap66_core", str(_Path(__file__).parent / "etap_66_114_chains_survey.py"))
_e66 = importlib.util.module_from_spec(_spec66)
_sys.modules["etap66_core"] = _e66
_spec66.loader.exec_module(_e66)


SYMBOL = "BTCUSDT"
START_DATE = "2024-01-01"
RR = 2.0
ENTRY_PCT = 0.70
SL_BUFFER_PCT = 0.5  # buffer beyond B as fraction of B width


def detect_117_setups(df_top, df_1h, df_15m, df_1m, top_tf: str,
                       allow_multi: int = 3) -> list[dict]:
    """Strategy 1.1.7 detector.

    df_top: 4h or 1d data (where iFVG forms)
    df_1h:  for L3 OB and L2 retest
    df_15m: for L4 entry FVG
    """
    # 1. Найти все iFVG на top_tf
    df_top_reset = df_top.reset_index().rename(columns={"open_time": "time"})
    df_top_reset.set_index("time", inplace=True)
    ifvg_results = _e93.find_inverse_fvgs(df_top_reset)
    if not ifvg_results:
        return []

    setups = []
    top_tf_hours = 4 if top_tf == "4h" else 24
    retest_window_days = 5 if top_tf == "4h" else 14

    obs_1h = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
    fvgs_15m = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")

    # Sort by time for binary search
    obs_1h_sorted = sorted(obs_1h, key=lambda x: x["prev_time"])
    obs_1h_starts = np.array([np.datetime64(
        o["prev_time"].tz_localize(None) if o["prev_time"].tz else o["prev_time"])
        for o in obs_1h_sorted])
    fvgs_15m_sorted = sorted(fvgs_15m, key=lambda x: x["c0_time"])
    fvgs_15m_c0s = np.array([np.datetime64(
        f["c0_time"].tz_localize(None) if f["c0_time"].tz else f["c0_time"])
        for f in fvgs_15m_sorted])

    for A, B, touch_idx in ifvg_results:
        b_c2_time = B.c2_time
        b_close_time = b_c2_time + pd.Timedelta(hours=top_tf_hours)
        cascade_end = b_close_time + pd.Timedelta(days=retest_window_days)

        # iFVG-B's direction = trade direction
        trade_dir = B.direction
        b_bot, b_top = B.bottom, B.top

        # L3 search window
        l3_start = b_close_time
        l3_end = min(cascade_end, df_top.index[-1])

        # Find OB-1h в направлении trade_dir с zone overlapping B
        n_setups = 0
        j0 = np.searchsorted(obs_1h_starts, np.datetime64(
            l3_start.tz_localize(None) if l3_start.tz else l3_start), side="left")
        j1 = np.searchsorted(obs_1h_starts, np.datetime64(
            l3_end.tz_localize(None) if l3_end.tz else l3_end), side="right")

        for oj in range(j0, j1):
            l3 = obs_1h_sorted[oj]
            if l3["direction"] != trade_dir: continue
            # L3 zone overlapping B
            if not _e66.zones_overlap(l3["bottom"], l3["top"], b_bot, b_top): continue

            l3_close = l3["time"] + pd.Timedelta(hours=1)
            # L4 FVG-15m inside L3 OB, synchron
            entry_td = pd.Timedelta(minutes=15)
            l4_max_c2 = l3_close - entry_td

            k0 = np.searchsorted(fvgs_15m_c0s, np.datetime64(
                l3["prev_time"].tz_localize(None) if l3["prev_time"].tz else l3["prev_time"]),
                side="left")
            f_entry = None
            for ek in range(k0, len(fvgs_15m_sorted)):
                f = fvgs_15m_sorted[ek]
                if f["c0_time"] < l3["prev_time"]: continue
                if f["time"] > l4_max_c2: continue
                if f["c0_time"] > l3_close: break
                if f["direction"] != trade_dir: continue
                # FVG-15m inside L3 OB
                if not _e66.zones_overlap(f["bottom"], f["top"], l3["bottom"], l3["top"]): continue
                # Also inside iFVG-B zone (or overlap)
                if not _e66.zones_overlap(f["bottom"], f["top"], b_bot, b_top): continue
                f_entry = f; break

            if f_entry is None: continue

            # Build entry/SL
            fb, ft = f_entry["bottom"], f_entry["top"]
            b_width = b_top - b_bot
            if trade_dir == "LONG":
                entry = fb + ENTRY_PCT * (ft - fb)
                sl = b_bot - SL_BUFFER_PCT * b_width
                if sl >= entry: continue
                # min_sl 1%
                sl = min(sl, entry - entry * 0.01)
            else:
                entry = ft - ENTRY_PCT * (ft - fb)
                sl = b_top + SL_BUFFER_PCT * b_width
                if sl <= entry: continue
                sl = max(sl, entry + entry * 0.01)

            setups.append({
                "fvg_b": fb, "fvg_t": ft,
                "ifvg_a_zone": (A.bottom, A.top),
                "ifvg_b_zone": (b_bot, b_top),
                "ifvg_a_dir": A.direction,
                "trade_dir": trade_dir,
                "direction": trade_dir,
                "x1_bottom": b_bot, "x1_top": b_top,
                "obh_b": l3["bottom"], "obh_t": l3["top"],
                "entry": entry,
                "sl": sl,
                "signal_time": l3_close,
                "year": l3_close.year,
                "top_tf": top_tf,
                "ifvg_b_c2_time": b_c2_time,
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


def simulate(s, df_1m, rr=RR):
    direction = s["direction"]
    entry = s["entry"]; sl = s["sl"]
    risk = abs(entry - sl)
    if risk <= 0: return ("invalid", 0.0)
    tp = entry + rr * risk if direction == "LONG" else entry - rr * risk
    start = s["signal_time"]
    end = start + pd.Timedelta(days=7)
    et64 = np.datetime64(start.tz_localize(None) if start.tz else start)
    ee64 = np.datetime64(end.tz_localize(None) if end.tz else end)
    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0: return ("no_data", 0.0)
    h = df_1m["high"].values[i0:i1].astype(np.float64)
    l = df_1m["low"].values[i0:i1].astype(np.float64)
    if direction == "LONG":
        ent = np.where(l <= entry)[0]; tp_pre = np.where(h >= tp)[0]
    else:
        ent = np.where(h >= entry)[0]; tp_pre = np.where(l <= tp)[0]
    ent_i = int(ent[0]) if ent.size else len(h) + 1
    tp_pre_i = int(tp_pre[0]) if tp_pre.size else len(h) + 1
    if tp_pre_i < ent_i: return ("no_entry", 0.0)
    if ent_i >= len(h): return ("not_filled", 0.0)
    post_h = h[ent_i:]; post_l = l[ent_i:]
    if direction == "LONG":
        sl_m = post_l <= sl; tp_m = post_h >= tp
    else:
        sl_m = post_h >= sl; tp_m = post_l <= tp
    sl_f = int(np.argmax(sl_m)) if sl_m.any() else -1
    tp_f = int(np.argmax(tp_m)) if tp_m.any() else -1
    if sl_f == -1 and tp_f == -1: return ("open", 0.0)
    if sl_f == -1 or (tp_f != -1 and tp_f < sl_f): return ("win", rr)
    return ("loss", -1.0)


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

    print(f"  cutoff: {cutoff}, last 1m: {df_1m.index[-1]}")

    print(f"\n[INFO] Detect 1.1.7 setups (iFVG-4h):")
    setups_4h = detect_117_setups(df_4h, df_1h, df_15m, df_1m, "4h", allow_multi=3)
    print(f"  iFVG-4h setups: {len(setups_4h)}")

    print(f"\n[INFO] Detect 1.1.7 setups (iFVG-1d):")
    setups_1d = detect_117_setups(df_1d, df_1h, df_15m, df_1m, "1d", allow_multi=3)
    print(f"  iFVG-1d setups: {len(setups_1d)}")

    # Combined dedup
    all_setups = setups_4h + setups_1d
    seen = set(); combined = []
    for s in all_setups:
        k = (s["signal_time"], s["direction"], round(s["fvg_b"], 2), round(s["fvg_t"], 2))
        if k in seen: continue
        seen.add(k); combined.append(s)
    print(f"  combined deduped: {len(combined)}")

    # Simulate
    print(f"\n[INFO] Simulate with RR=2.0:")
    for name, sets in [("4h", setups_4h), ("1d", setups_1d), ("combined", combined)]:
        outcomes = defaultdict(int)
        pnl = 0.0
        yearly = defaultdict(lambda: [0, 0, 0.0])
        for s in sets:
            o, R = simulate(s, df_1m)
            outcomes[o] += 1
            yearly_key = s["signal_time"].year
            if o == "win":
                pnl += R
                yearly[yearly_key][0] += 1; yearly[yearly_key][2] += R
            elif o == "loss":
                pnl += R
                yearly[yearly_key][1] += 1; yearly[yearly_key][2] += R
        closed = outcomes["win"] + outcomes["loss"]
        wr = outcomes["win"] / closed * 100 if closed else 0
        print(f"\n  --- {name} ---")
        print(f"  Total signals: {len(sets)}")
        print(f"  Outcomes: {dict(outcomes)}")
        print(f"  Closed: {closed}, WR: {wr:.1f}%, Total R: {pnl:+.1f}")
        if closed:
            print(f"  avg R/trade: {pnl/closed:+.3f}")
        if yearly:
            print(f"  Year breakdown:")
            for yr in sorted(yearly.keys()):
                w, l, p = yearly[yr]
                n = w + l
                if n == 0: continue
                ywr = w/n*100
                print(f"    {yr}: n={n} WR={ywr:.1f}% R={p:+.1f}")

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
