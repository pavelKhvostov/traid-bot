"""Этап 40: расширение оригинального optimize_1_1_1_swept_stage3 с
переключателями для честного сравнения.

ВЕРСИИ:
  V1 (REPRODUCE): 3y, SWEPT, sl=0.40 symmetric, no min_sl  → ожидаем ~+46R/RR=2.0
  V2 (EXTEND):    6.33y same params  → влияние data window
  V3 (FUTURES):   6.33y + min_sl=1% (futures-realistic)
  V4 (NO_SWEPT):  6.33y без SWEPT-фильтра (как мой etap_39)
  V5 (HULL):      6.33y + SWEPT + min_sl=1% + Hull-4h aligned (safe)
  V6 (USER_ASYM): 6.33y + SWEPT + sl=0.35L/0.65S + min_sl=1% (ваша асимметрия)
  V7 (ALL):       V5 + ICT(london|ny) + RR=2.0/2.5 — best deployable
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
from pathlib import Path
import time
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals

SYMBOL = "BTCUSDT"
ENTRY_PCT = 0.80


def check_swept(sig, df_1h, df_2h):
    df_top = df_1h if sig["ob_htf_tf"] == "1h" else df_2h
    cur_time = pd.Timestamp(sig["ob_htf_cur_time"])
    prev_time = pd.Timestamp(sig["ob_htf_prev_time"])
    if cur_time.tz is None: cur_time = cur_time.tz_localize("UTC")
    if prev_time.tz is None: prev_time = prev_time.tz_localize("UTC")
    if prev_time not in df_top.index or cur_time not in df_top.index:
        return None
    pi = df_top.index.get_loc(prev_time)
    if pi < 2: return None
    ci = df_top.index.get_loc(cur_time)
    c1l = float(df_top.iloc[pi]["low"]); c2l = float(df_top.iloc[ci]["low"])
    c1h = float(df_top.iloc[pi]["high"]); c2h = float(df_top.iloc[ci]["high"])
    n1l = float(df_top.iloc[pi-1]["low"]); n2l = float(df_top.iloc[pi-2]["low"])
    n1h = float(df_top.iloc[pi-1]["high"]); n2h = float(df_top.iloc[pi-2]["high"])
    if sig["direction"] == "LONG":
        return min(c1l, c2l) < min(n1l, n2l)
    return max(c1h, c2h) > max(n1h, n2h)


def precompute(sig, df_1m):
    fvg_b, fvg_t = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    direction = sig["direction"]
    tf_minutes = 15 if sig["fvg_tf"] == "15m" else 20
    forward = df_1m[df_1m.index >= sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)]
    if forward.empty: return None
    return {
        "direction": direction,
        "fvg_b": float(fvg_b), "fvg_t": float(fvg_t),
        "obh_b": float(obh_b), "obh_t": float(obh_t),
        "highs": forward["high"].values.astype(np.float64),
        "lows": forward["low"].values.astype(np.float64),
        "signal_time": sig["signal_time"],
        "year": pd.Timestamp(sig["signal_time"]).year,
    }


def simulate(s, entry, sl, tp, no_entry=True):
    highs, lows = s["highs"], s["lows"]
    n = len(highs)
    if s["direction"] == "LONG":
        ent_idxs = np.where(lows <= entry)[0]
        tp_pre_idxs = np.where(highs >= tp)[0]
    else:
        ent_idxs = np.where(highs >= entry)[0]
        tp_pre_idxs = np.where(lows <= tp)[0]
    ent_idx = int(ent_idxs[0]) if ent_idxs.size else n + 1
    tp_pre = int(tp_pre_idxs[0]) if tp_pre_idxs.size else n + 1
    if no_entry and tp_pre < ent_idx:
        return "no_entry"
    if ent_idx >= n: return "not_filled"
    post_l = lows[ent_idx:]; post_h = highs[ent_idx:]
    if s["direction"] == "LONG":
        sl_m = post_l <= sl; tp_m = post_h >= tp
    else:
        sl_m = post_h >= sl; tp_m = post_l <= tp
    sl_first = int(np.argmax(sl_m)) if sl_m.any() else -1
    tp_first = int(np.argmax(tp_m)) if tp_m.any() else -1
    if sl_first == -1 and tp_first == -1: return "open"
    if sl_first == -1: return "win"
    if tp_first == -1: return "loss"
    return "win" if tp_first < sl_first else "loss"


def build_sl(s, sl_pct_long, sl_pct_short, min_sl_pct):
    direction = s["direction"]
    fw = s["fvg_t"] - s["fvg_b"]
    if direction == "LONG":
        entry = s["fvg_b"] + ENTRY_PCT * fw
        sl_lo = s["obh_b"]; sl_hi = s["fvg_b"]
        sl = sl_lo + sl_pct_long * (sl_hi - sl_lo)
        if min_sl_pct > 0:
            min_sl = entry * min_sl_pct / 100
            sl = min(sl, entry - min_sl)
        if sl >= entry: return None
    else:
        entry = s["fvg_t"] - ENTRY_PCT * fw
        sl_hi = s["obh_t"]; sl_lo = s["fvg_t"]
        sl = sl_hi - sl_pct_short * (sl_hi - sl_lo)
        if min_sl_pct > 0:
            min_sl = entry * min_sl_pct / 100
            sl = max(sl, entry + min_sl)
        if sl <= entry: return None
    return entry, sl


def evaluate(setups, sl_pct_long, sl_pct_short, rr, min_sl_pct=0.0,
              no_entry=True):
    rows = []
    for s in setups:
        tup = build_sl(s, sl_pct_long, sl_pct_short, min_sl_pct)
        if tup is None: continue
        entry, sl = tup
        risk = abs(entry - sl)
        tp = entry + rr * risk if s["direction"] == "LONG" else entry - rr * risk
        outcome = simulate(s, entry, sl, tp, no_entry=no_entry)
        if outcome == "win":
            R = rr
        elif outcome == "loss":
            R = -1.0
        else:
            R = 0.0
        rows.append({"outcome": outcome, "R": R, "year": s["year"],
                      "direction": s["direction"]})
    return pd.DataFrame(rows)


def report(label, df_e, n_total):
    cl = df_e[df_e["outcome"].isin(["win", "loss"])]
    if cl.empty:
        print(f"  {label}: no closed"); return
    no_ent = (df_e["outcome"] == "no_entry").sum() if "no_entry" in df_e["outcome"].values else 0
    not_filled = (df_e["outcome"] == "not_filled").sum() if "not_filled" in df_e["outcome"].values else 0
    n_closed = len(cl)
    wr = (cl["outcome"] == "win").mean() * 100
    tot = cl["R"].sum()
    rt = cl["R"].mean()
    yr = cl.groupby("year")["R"].sum()
    bad = (yr < 0).sum()
    print(f"  {label}")
    print(f"    n_total={n_total}, n_eval={len(df_e)}, no_entry={no_ent}, "
          f"not_filled={not_filled}, closed={n_closed}")
    print(f"    WR={wr:.1f}%  total_R={tot:+.1f}  R/tr={rt:+.3f}  bad_yrs={bad}/{len(yr)}")


# ---------- safe Hull-4h lookup ----------

def wma_fast(arr, period):
    period = max(int(period), 1)
    weights = np.arange(1, period + 1, dtype=float)
    weights /= weights.sum()
    out = np.full_like(arr, np.nan, dtype=float)
    if len(arr) < period: return out
    valid = np.convolve(arr, weights[::-1], mode="valid")
    out[period - 1:] = valid
    return out


def hull_ma(close, length=78):
    arr = close.to_numpy(dtype=float)
    half = max(int(length / 2), 1)
    sqrt_len = max(int(round(np.sqrt(length))), 1)
    raw = 2.0 * wma_fast(arr, half) - wma_fast(arr, length)
    hull = wma_fast(np.where(np.isnan(raw), 0.0, raw), sqrt_len)
    hull[:length + sqrt_len] = np.nan
    return pd.Series(hull, index=close.index)


def hull_trend_safe_aligned(close_series, hull_series, ts, direction):
    """Returns True if Hull-aligned with direction at last CLOSED bar."""
    idx = hull_series.index.searchsorted(ts, side="right") - 1
    if idx < 3: return False
    last_closed = idx - 1
    c = close_series.iloc[last_closed]; h2 = hull_series.iloc[last_closed - 2]
    if pd.isna(c) or pd.isna(h2): return False
    up = c > h2
    if direction == "LONG": return up
    return not up


def main():
    t0 = time.time()
    print("[INFO] loading all TFs")
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")
    today = pd.Timestamp.now(tz="UTC").normalize()

    # Build hull-4h once on full data
    hull_4h = hull_ma(df_4h["close"], 78)

    def build_signals(days_back):
        cutoff = today - pd.Timedelta(days=days_back)
        df_1d_f = df_1d[df_1d.index >= cutoff]
        raw = detect_strategy_1_1_1_signals(
            df_1d_f, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
            verbose=False)
        groups = defaultdict(list)
        for s in raw:
            key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
            sw = check_swept(s, df_1h, df_2h)
            if sw is None: continue
            groups[key].append({"sig": s, "swept": sw})
        # SWEPT-only reps
        swept_reps = [next(p["sig"] for p in paths if p["swept"])
                      for key, paths in groups.items()
                      if any(p["swept"] for p in paths)]
        # ALL reps (no swept filter)
        all_reps = [paths[0]["sig"] for paths in groups.values()]
        cache_swept = [c for c in (precompute(s, df_1m) for s in swept_reps) if c]
        cache_all = [c for c in (precompute(s, df_1m) for s in all_reps) if c]
        return cache_swept, cache_all

    # ---------- V1: REPRODUCE 3y ----------
    print(f"\n{'='*70}\nV1: REPRODUCE original (3y, SWEPT, sl=0.40 sym, no min_sl, no_entry)")
    print(f"{'='*70}")
    cache_3y_swept, cache_3y_all = build_signals(1095)
    print(f"  cache: SWEPT={len(cache_3y_swept)}, ALL={len(cache_3y_all)}")
    for rr in [1.0, 2.0, 2.2, 4.0, 4.6]:
        df_e = evaluate(cache_3y_swept, 0.40, 0.40, rr, min_sl_pct=0.0, no_entry=True)
        report(f"V1 3y SWEPT sl=0.40 RR={rr}", df_e, len(cache_3y_swept))

    # ---------- V2: EXTEND to 6.33y ----------
    print(f"\n{'='*70}\nV2: EXTEND to 6.33y (SWEPT, sl=0.40 sym, no min_sl)")
    print(f"{'='*70}")
    cache_6y_swept, cache_6y_all = build_signals(2313)
    print(f"  cache: SWEPT={len(cache_6y_swept)}, ALL={len(cache_6y_all)}")
    for rr in [1.0, 2.0, 2.5, 3.0, 4.6]:
        df_e = evaluate(cache_6y_swept, 0.40, 0.40, rr, min_sl_pct=0.0, no_entry=True)
        report(f"V2 6.33y SWEPT sl=0.40 RR={rr}", df_e, len(cache_6y_swept))

    # ---------- V3: FUTURES-realistic with min_sl=1% ----------
    print(f"\n{'='*70}\nV3: FUTURES (6.33y, SWEPT, sl=0.40 sym, MIN_SL=1%)")
    print(f"{'='*70}")
    for rr in [1.0, 2.0, 2.5, 3.0]:
        df_e = evaluate(cache_6y_swept, 0.40, 0.40, rr, min_sl_pct=1.0, no_entry=True)
        report(f"V3 6.33y SWEPT sl=0.40 min_sl=1% RR={rr}", df_e, len(cache_6y_swept))

    # ---------- V4: NO SWEPT filter ----------
    print(f"\n{'='*70}\nV4: NO SWEPT (6.33y, all signals, sl=0.40 sym, no min_sl)")
    print(f"{'='*70}")
    for rr in [1.0, 2.0, 2.5]:
        df_e = evaluate(cache_6y_all, 0.40, 0.40, rr, min_sl_pct=0.0, no_entry=True)
        report(f"V4 6.33y ALL sl=0.40 RR={rr}", df_e, len(cache_6y_all))

    # ---------- V5: + Hull-4h aligned filter (safe) ----------
    print(f"\n{'='*70}\nV5: + HULL-4h aligned filter (6.33y, SWEPT, sl=0.40, min_sl=1%)")
    print(f"{'='*70}")
    cache_6y_hull = [c for c in cache_6y_swept
                      if hull_trend_safe_aligned(df_4h["close"], hull_4h,
                                                  c["signal_time"], c["direction"])]
    print(f"  after Hull-4h filter: {len(cache_6y_hull)}/{len(cache_6y_swept)}")
    for rr in [1.0, 1.5, 2.0, 2.5, 3.0]:
        df_e = evaluate(cache_6y_hull, 0.40, 0.40, rr, min_sl_pct=1.0, no_entry=True)
        report(f"V5 6.33y SWEPT+Hull4h min_sl=1% sl=0.40 RR={rr}",
               df_e, len(cache_6y_hull))

    # ---------- V6: USER asymmetric SL ----------
    print(f"\n{'='*70}\nV6: USER ASYM (6.33y, SWEPT, sl=0.35L/0.65S, min_sl=1%)")
    print(f"{'='*70}")
    for rr in [1.0, 2.0, 2.5]:
        df_e = evaluate(cache_6y_swept, 0.35, 0.65, rr, min_sl_pct=1.0, no_entry=True)
        report(f"V6 6.33y SWEPT sl=0.35L/0.65S min_sl=1% RR={rr}",
               df_e, len(cache_6y_swept))

    # ---------- V7: ALL — Hull + ICT-london|ny ----------
    print(f"\n{'='*70}\nV7: ALL FILTERS (Hull-4h + ICT london|ny, sl=0.40, min_sl=1%)")
    print(f"{'='*70}")
    def in_ict(ts):
        h = pd.Timestamp(ts).hour
        return 7 <= h < 17  # london+ny combined
    cache_v7 = [c for c in cache_6y_hull if in_ict(c["signal_time"])]
    print(f"  after ICT filter: {len(cache_v7)}/{len(cache_6y_hull)}")
    for rr in [1.0, 1.5, 2.0, 2.5, 3.0]:
        df_e = evaluate(cache_v7, 0.40, 0.40, rr, min_sl_pct=1.0, no_entry=True)
        report(f"V7 6.33y SWEPT+Hull+ICT min_sl=1% sl=0.40 RR={rr}",
               df_e, len(cache_v7))

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
