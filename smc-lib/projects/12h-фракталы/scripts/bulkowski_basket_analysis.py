"""Bulkowski patterns на 12h pivot i-bars (CLOSE) → P(move ≥ 2/3/4/5%) в ожидаемое направление.

Dataset: 1357 baseline pivots (confirmable, all i-candles, by direction).
Anchor: close of 12h pivot bar = ts_ms + 12h.
Direction expected: LOW pivot → UP move, HIGH pivot → DOWN move.

Bulkowski patterns at i-close (strict causal, only bars ≤ close):
  4h × {engulf, hammer, db, busted}  long+short
  1d × {engulf, hammer, db, busted}  long+short

Realized move % in EXPECTED direction over horizon (default 14 days):
  LOW pivot:  max(high[i+1..]) / close[i] - 1
  HIGH pivot: 1 - min(low[i+1..])  / close[i]

Output:
  - per-pattern probability table
  - features parquet for ML
"""
from __future__ import annotations
import sys, pathlib, time
from datetime import datetime
import numpy as np
import pandas as pd

# Order matters: 12h-fractal-new _lib first (has load_12h), then ob_vc scripts for detectors
sys.path.insert(0, str(pathlib.Path.home() / "smc-lib/projects/ob-vc/scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from _lib import load_1m, load_12h, MS_M
from bulkowski_detectors import (
    detect_engulfing, detect_hammer,
    detect_double_bottom, detect_double_top,
    detect_busted_double_top, detect_busted_double_bottom,
    annotate_with_ts,
)


TF12_MS = 12 * 60 * MS_M
TF4H_MS = 4 * 60 * MS_M
TF1D_MS = 24 * 60 * MS_M
HORIZON_MS = 14 * 24 * 60 * MS_M  # 14 days realized move

# Lookback windows for pattern relevance (must fire near i-close)
LOOKBACK = {
    "engulf": 7 * 24 * 60 * MS_M,    # 7d
    "hammer": 7 * 24 * 60 * MS_M,    # 7d
    "db":     60 * 24 * 60 * MS_M,   # 60d
    "busted": 30 * 24 * 60 * MS_M,   # 30d
}


class Candle:
    __slots__ = ("open_time", "open", "high", "low", "close", "volume")
    def __init__(self, t, o, h, l, c, v):
        self.open_time = t; self.open = o; self.high = h
        self.low = l; self.close = c; self.volume = v


def aggregate_tf(rows, tf_ms):
    out = []
    cb = None; o = h = l = c = v = 0.0
    for ts, oo, hh, ll, cc, vv in rows:
        b = ts - (ts % tf_ms)
        if b != cb:
            if cb is not None: out.append(Candle(cb, o, h, l, c, v))
            cb = b; o, h, l, c, v = oo, hh, ll, cc, vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v += vv
    if cb is not None: out.append(Candle(cb, o, h, l, c, v))
    return out


def events_by_dir(events, direction):
    return np.array(sorted(e[3] for e in events if e[1] == direction), dtype=np.int64)


def has_event(ts_arr, close_ms, lookback_ms):
    """Pattern fires in (close_ms - lookback_ms, close_ms]."""
    if len(ts_arr) == 0:
        return False
    lo = close_ms - lookback_ms
    i = np.searchsorted(ts_arr, close_ms, side="right")
    if i == 0:
        return False
    return ts_arr[i - 1] > lo


def compute_realized_move(ts_1m, h_1m, l_1m, close_ms, direction, horizon_ms):
    """Movement % in expected direction.
    direction: 'low' = LONG (expect UP), 'high' = SHORT (expect DOWN).
    Returns: (move_pct, max_high, min_low) — move_pct in expected direction (signed positive).
    """
    end_ms = close_ms + horizon_ms
    i0 = int(np.searchsorted(ts_1m, close_ms, side="right"))
    i1 = int(np.searchsorted(ts_1m, end_ms, side="right"))
    if i1 <= i0:
        return np.nan, np.nan, np.nan
    seg_h = h_1m[i0:i1]
    seg_l = l_1m[i0:i1]
    # close price at i-bar close = price at 1m bar just before close_ms
    # use the 1m close at close_ms - 60s
    k_close = int(np.searchsorted(ts_1m, close_ms, side="right")) - 1
    if k_close < 0:
        return np.nan, np.nan, np.nan
    close_price = float(np.nan)  # will compute from 1m close at idx
    # use last 1m bar high/low as close anchor — close=close of 12h bar
    # We don't have 1m close array here; use last seg_h before close_ms? simpler: read close-near.
    # The aggregate function we have stores close. Better: load 12h close directly via load_12h.
    return None  # placeholder — implemented below with proper anchor


def main():
    out = pathlib.Path.home() / "Desktop/12h-fractal-new-out"
    out.mkdir(exist_ok=True)
    t0 = time.time()

    # ─── Load baseline pivots ──────────────────
    baseline = pd.read_parquet(pathlib.Path.home() / "Desktop/pred12h_baseline_v2.parquet")
    baseline = baseline.drop_duplicates(["pivot_open_ts_ms", "direction"]).reset_index(drop=True)
    print(f"baseline: {len(baseline)} (high={int((baseline.direction=='high').sum())} low={int((baseline.direction=='low').sum())})")

    # ─── Load 12h to get close price per pivot ───
    b12 = load_12h()
    t12 = b12["t"]; c12 = b12["c"]
    ts_to_close = dict(zip(t12.tolist(), c12.tolist()))

    # ─── Load 1m for realized move ───
    rows = load_1m()
    ts_1m = np.array([r[0] for r in rows], dtype=np.int64)
    h_1m = np.array([r[2] for r in rows], dtype=np.float64)
    l_1m = np.array([r[3] for r in rows], dtype=np.float64)
    print(f"1m bars: {len(ts_1m):,}")

    # ─── Aggregate 4h, 1d for Bulkowski ───
    cans_4h = aggregate_tf(rows, TF4H_MS)
    cans_1d = aggregate_tf(rows, TF1D_MS)
    print(f"4h bars: {len(cans_4h):,}  1d bars: {len(cans_1d):,}")

    # ─── Detect ALL Bulkowski events ───
    print("\nDetecting Bulkowski patterns...")
    e4 = annotate_with_ts(detect_engulfing(cans_4h, min_body_pct=0.005), cans_4h)
    h4 = annotate_with_ts(detect_hammer(cans_4h), cans_4h)
    db4 = annotate_with_ts(detect_double_bottom(cans_4h, threshold_pct=0.03), cans_4h)
    dt4 = annotate_with_ts(detect_double_top(cans_4h, threshold_pct=0.03), cans_4h)
    bdt4 = annotate_with_ts(detect_busted_double_top(cans_4h, threshold_pct=0.03), cans_4h)
    bdb4 = annotate_with_ts(detect_busted_double_bottom(cans_4h, threshold_pct=0.03), cans_4h)

    e1d = annotate_with_ts(detect_engulfing(cans_1d, min_body_pct=0.005), cans_1d)
    h1d = annotate_with_ts(detect_hammer(cans_1d), cans_1d)
    db1d = annotate_with_ts(detect_double_bottom(cans_1d, threshold_pct=0.05), cans_1d)
    dt1d = annotate_with_ts(detect_double_top(cans_1d, threshold_pct=0.05), cans_1d)
    bdt1d = annotate_with_ts(detect_busted_double_top(cans_1d, threshold_pct=0.05), cans_1d)
    bdb1d = annotate_with_ts(detect_busted_double_bottom(cans_1d, threshold_pct=0.05), cans_1d)

    EVENTS = {
        "4h_engulf": (events_by_dir(e4, "long"), events_by_dir(e4, "short")),
        "4h_hammer": (events_by_dir(h4, "long"), events_by_dir(h4, "short")),
        "4h_db":     (events_by_dir(db4, "long"), events_by_dir(dt4, "short")),
        "4h_busted": (events_by_dir(bdt4, "long"), events_by_dir(bdb4, "short")),
        "1d_engulf": (events_by_dir(e1d, "long"), events_by_dir(e1d, "short")),
        "1d_hammer": (events_by_dir(h1d, "long"), events_by_dir(h1d, "short")),
        "1d_db":     (events_by_dir(db1d, "long"), events_by_dir(dt1d, "short")),
        "1d_busted": (events_by_dir(bdt1d, "long"), events_by_dir(bdb1d, "short")),
    }
    for k, (l, s) in EVENTS.items():
        lb = "engulf" if "engulf" in k else ("hammer" if "hammer" in k else ("db" if k.endswith("db") else "busted"))
        print(f"  {k}: long={len(l):4d}  short={len(s):4d}  lookback={LOOKBACK[lb]//(24*60*MS_M)}d")

    # ─── Build per-pivot feature row ───
    print("\nBuilding feature rows...")
    rows_out = []
    skipped = 0
    for _, p in baseline.iterrows():
        ts = int(p.pivot_open_ts_ms)
        close_ms = ts + TF12_MS  # close = open + 12h
        if ts not in ts_to_close:
            skipped += 1; continue
        close_price = float(ts_to_close[ts])
        is_long = (p.direction == "low")   # FL = expect UP
        dir_idx = 0 if is_long else 1
        # Realized move in EXPECTED direction
        end_ms = close_ms + HORIZON_MS
        i0 = int(np.searchsorted(ts_1m, close_ms, side="right"))
        i1 = int(np.searchsorted(ts_1m, end_ms, side="right"))
        if i1 <= i0:
            skipped += 1; continue
        if is_long:
            move_pct = (float(h_1m[i0:i1].max()) / close_price - 1.0) * 100.0
        else:
            move_pct = (1.0 - float(l_1m[i0:i1].min()) / close_price) * 100.0
        # Bulkowski features (each pattern fired in lookback before close, direction-aligned)
        feats = {}
        for k, (long_arr, short_arr) in EVENTS.items():
            lb = "engulf" if "engulf" in k else ("hammer" if "hammer" in k else ("db" if k.endswith("db") else "busted"))
            arr = long_arr if is_long else short_arr
            feats[k] = int(has_event(arr, close_ms, LOOKBACK[lb]))
        rows_out.append({
            "ts_ms": ts,
            "close_ms": close_ms,
            "direction": p.direction,
            "is_long": int(is_long),
            "confirmed": int(p.confirmed),
            "close_price": close_price,
            "body_pct": float(p.body_pct),
            "wick_pct": float(p.wick_pct),
            "color": int(p.color),
            "move_pct": move_pct,
            **feats,
        })

    df = pd.DataFrame(rows_out)
    print(f"  built: {len(df)}  skipped: {skipped}")
    df.to_parquet(out / "bulkowski_basket_features.parquet", index=False)
    print(f"  saved: {out / 'bulkowski_basket_features.parquet'}")

    # ─── P(move ≥ X%) per pattern × direction ───
    print(f"\n{'─'*88}")
    print(f"P(move ≥ X%) in EXPECTED direction  (horizon=14d, N_total={len(df)})")
    print(f"{'─'*88}")
    print(f"{'Pattern':<14} {'Dir':<6} {'N':>5}  {'P≥2%':>6} {'P≥3%':>6} {'P≥4%':>6} {'P≥5%':>6} {'P≥7%':>6} {'P≥10%':>6}  {'mean%':>6} {'med%':>6}")

    def thr_row(mask, label, dirname):
        n = int(mask.sum())
        if n == 0:
            return None
        sub = df.loc[mask, "move_pct"].dropna()
        if len(sub) == 0:
            return None
        r = {"pattern": label, "direction": dirname, "n": len(sub)}
        for t in (2, 3, 4, 5, 7, 10):
            r[f"P_ge_{t}"] = float((sub >= t).mean())
        r["mean_pct"] = float(sub.mean())
        r["med_pct"] = float(sub.median())
        return r

    out_rows = []
    # Baseline first
    for dirname, mask in [
        ("BOTH",  pd.Series(True, index=df.index)),
        ("long",  df.is_long == 1),
        ("short", df.is_long == 0),
    ]:
        r = thr_row(mask, "BASELINE", dirname)
        if r:
            out_rows.append(r)
            print(f"{'BASELINE':<14} {dirname:<6} {r['n']:>5}  "
                  f"{r['P_ge_2']*100:>5.1f}% {r['P_ge_3']*100:>5.1f}% {r['P_ge_4']*100:>5.1f}% "
                  f"{r['P_ge_5']*100:>5.1f}% {r['P_ge_7']*100:>5.1f}% {r['P_ge_10']*100:>5.1f}%  "
                  f"{r['mean_pct']:>6.2f} {r['med_pct']:>6.2f}")

    print(f"{'─'*88}")
    for pat in EVENTS.keys():
        for dirname, dir_mask in [("long", df.is_long == 1), ("short", df.is_long == 0)]:
            mask = dir_mask & (df[pat] == 1)
            r = thr_row(mask, pat, dirname)
            if not r:
                continue
            out_rows.append(r)
            print(f"{pat:<14} {dirname:<6} {r['n']:>5}  "
                  f"{r['P_ge_2']*100:>5.1f}% {r['P_ge_3']*100:>5.1f}% {r['P_ge_4']*100:>5.1f}% "
                  f"{r['P_ge_5']*100:>5.1f}% {r['P_ge_7']*100:>5.1f}% {r['P_ge_10']*100:>5.1f}%  "
                  f"{r['mean_pct']:>6.2f} {r['med_pct']:>6.2f}")

    pd.DataFrame(out_rows).to_csv(out / "bulkowski_basket_probabilities.csv", index=False)
    print(f"\nSaved: {out / 'bulkowski_basket_probabilities.csv'}")
    print(f"\nElapsed: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
