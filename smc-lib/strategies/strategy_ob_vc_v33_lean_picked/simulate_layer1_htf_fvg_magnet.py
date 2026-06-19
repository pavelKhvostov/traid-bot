"""Layer 1 — Dynamic TP via HTF FVG magnet.

For each v3.3 selected trade (top-1100 hit_RR_20 lgb):
  1. At born_ms, find UN-MITIGATED FVGs on 4h / 6h / 12h in TP direction
  2. Use nearest within [+2R, +4.5R] window as dynamic TP target
  3. Simulate exit: use 1m walk forward to find first hit (TP_dyn or SL)
  4. Compare Σ R, WR vs baseline fixed RR=2.0
"""
from __future__ import annotations
import csv
import pathlib
from datetime import datetime, timezone
from collections import defaultdict

import pandas as pd
import numpy as np


BTC_CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
ETH_CSV = pathlib.Path.home() / "traid-bot/data/ETHUSDT_1m_vic_vadim.csv"
FEATURES = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v3/features_v33_picked.parquet")
OOS = pathlib.Path("/Users/vadim/Desktop/output4/oos_predictions.parquet")
OUT_DIR = pathlib.Path("/Users/vadim/smc-lib/strategies/strategy_ob_vc_v33_lean_picked")

MS = 60_000
HTF_LIST = [("4h", 4 * 60 * MS), ("6h", 6 * 60 * MS), ("12h", 12 * 60 * MS)]

MIN_R = 2.0      # minimum dynamic TP (don't go below baseline)
MAX_R = 4.5      # maximum cap (per 1.1.1 canon)
BASELINE_RR = 2.0
MAX_HOLD_DAYS = 14


def load_1m(path):
    rows = []
    with path.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp()*1000),
                          float(r[1]), float(r[2]), float(r[3]),
                          float(r[4]), float(r[5])))
    return rows


def agg(d, tf_ms):
    """Aggregate 1m → tf_ms. Returns list of (ts, o, h, l, c)."""
    out = []
    cb = None; o = h = l = c = 0.0
    for ts, oo, hh, ll, cc, vv in d:
        b = ts - (ts % tf_ms)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c))
            cb = b; o, h, l, c = oo, hh, ll, cc
        else:
            h = max(h, hh); l = min(l, ll); c = cc
    if cb is not None: out.append((cb, o, h, l, c))
    return out


def detect_fvgs(bars, tf_ms):
    """Detect all FVGs on a given TF.
    Returns list of dicts: {created_ms, dir, bottom, top, mid}
    - long FVG: c1.high < c3.low → zone (c1.high, c3.low) [c3 is bullish gap]
    - short FVG: c1.low > c3.high → zone (c3.high, c1.low) [c3 is bearish gap]
    """
    fvgs = []
    for i in range(2, len(bars)):
        c1 = bars[i-2]
        c3 = bars[i]
        # Bullish FVG (gap up)
        if c1[2] < c3[3]:
            fvgs.append({
                "created_ms": c3[0] + tf_ms,  # at close of c3
                "dir": "long",
                "bottom": c1[2],
                "top": c3[3],
                "mid": (c1[2] + c3[3]) / 2,
            })
        # Bearish FVG (gap down)
        if c1[3] > c3[2]:
            fvgs.append({
                "created_ms": c3[0] + tf_ms,
                "dir": "short",
                "bottom": c3[2],
                "top": c1[3],
                "mid": (c3[2] + c1[3]) / 2,
            })
    return fvgs


def add_mitigation_ts(fvgs, bars_1m):
    """For each FVG, find first time price enters the zone after creation."""
    bars_sorted = sorted(bars_1m, key=lambda b: b[0])
    j = 0
    for fvg in fvgs:
        # Move j forward to created_ms
        while j < len(bars_sorted) and bars_sorted[j][0] < fvg["created_ms"]:
            j += 1
        mit_ms = None
        for k in range(j, len(bars_sorted)):
            ts, _, h, l, _, _ = bars_sorted[k]
            # Mitigated: price enters zone
            if l <= fvg["top"] and h >= fvg["bottom"]:
                mit_ms = ts
                break
        fvg["mitigated_ms"] = mit_ms
    return fvgs


def find_target_R(entry, sl_dist, direction, asset_fvgs, at_ms):
    """Find best HTF FVG magnet target as of at_ms.
    Returns R-distance (within [MIN_R, MAX_R]) or None.
    Prefers nearest valid magnet.
    """
    candidates = []
    for tf_name, tf_ms in HTF_LIST:
        for fvg in asset_fvgs[tf_name]:
            # Must be created before at_ms
            if fvg["created_ms"] > at_ms: continue
            # Must be UNmitigated as of at_ms
            if fvg["mitigated_ms"] is not None and fvg["mitigated_ms"] <= at_ms:
                continue
            # Must be in TP direction
            if direction == "long":
                # Target = bottom of FVG (price comes up to fill from below)
                target = fvg["bottom"]
                if target <= entry: continue
                R = (target - entry) / sl_dist
            else:
                # Target = top of FVG
                target = fvg["top"]
                if target >= entry: continue
                R = (entry - target) / sl_dist
            if R < MIN_R or R > MAX_R: continue
            candidates.append((R, tf_name))
    if not candidates:
        return None, None
    # Pick nearest in R (within range)
    R, tf = min(candidates, key=lambda x: x[0])
    return R, tf


def simulate_trade_with_dynamic_tp(bars_1m, entry_fill_ms, entry, sl, tp_dyn, direction):
    """Walk 1m bars to find first TP_dyn or SL hit. Returns (exit_R, exit_type, exit_ms)."""
    end_ms = entry_fill_ms + MAX_HOLD_DAYS * 86400 * 1000
    sl_dist = abs(entry - sl)
    for ts, o, h, l, c, _ in bars_1m:
        if ts < entry_fill_ms: continue
        if ts > end_ms: break
        if direction == "long":
            if l <= sl:
                return -1.0, "sl", ts
            if h >= tp_dyn:
                tp_R = (tp_dyn - entry) / sl_dist
                return tp_R, "tp", ts
        else:
            if h >= sl:
                return -1.0, "sl", ts
            if l <= tp_dyn:
                tp_R = (entry - tp_dyn) / sl_dist
                return tp_R, "tp", ts
    # Mark to market at end
    last = bars_1m[-1] if bars_1m else None
    if last is None: return 0.0, "timeout", None
    last_close = last[4]
    if direction == "long":
        unrealized_R = (last_close - entry) / sl_dist
    else:
        unrealized_R = (entry - last_close) / sl_dist
    return unrealized_R, "timeout", last[0]


def main():
    print("=" * 72)
    print("Layer 1 simulation — Dynamic TP via HTF FVG magnet")
    print("=" * 72)

    # ─── Step 1. Build full HTF FVG database for BTC+ETH ─────
    print("\n[1/4] Building HTF FVG database...")
    asset_fvgs = {}
    asset_bars_1m = {}
    for asset, path in [("BTC", BTC_CSV), ("ETH", ETH_CSV)]:
        print(f"  Loading {asset} 1m from {path.name}...")
        d = load_1m(path)
        asset_bars_1m[asset] = d
        print(f"    {len(d):,} bars 1m loaded")
        fvgs_by_tf = {}
        for tf_name, tf_ms in HTF_LIST:
            bars = agg(d, tf_ms)
            fvgs = detect_fvgs(bars, tf_ms)
            fvgs = add_mitigation_ts(fvgs, d)
            fvgs_by_tf[tf_name] = fvgs
            unmit = sum(1 for f in fvgs if f["mitigated_ms"] is None)
            print(f"    {tf_name}: {len(fvgs):,} FVGs ({unmit:,} never mitigated)")
        asset_fvgs[asset] = fvgs_by_tf

    # ─── Step 2. Get v3.3 selected trades ─────
    print("\n[2/4] Loading v3.3 selected trades...")
    oos = pd.read_parquet(OOS)
    sub = oos[(oos.target == 'hit_RR_20') & (oos.model == 'lgb')]
    agg_oos = sub.groupby('event_idx').agg(
        proba=('proba', 'mean'), y_true=('y_true', 'first')
    ).reset_index()
    sel = agg_oos.sort_values('proba', ascending=False).head(1100).reset_index(drop=True)

    feats = pd.read_parquet(FEATURES)
    feats = feats[feats.fill_touched & feats.r_pct_pass].reset_index(drop=True)
    feats["row_idx"] = feats.index

    merged = sel.merge(
        feats[["row_idx", "asset", "direction", "t_id", "born_ms",
                "entry_fill_ms", "entry", "r_pct", "mfe_R", "mae_R", "sl_hit"]],
        left_on='event_idx', right_on='row_idx', how='left')
    print(f"  Selected: {len(merged):,} trades")

    # ─── Step 3. For each trade — find magnet and simulate ─────
    print("\n[3/4] Simulating dynamic TP per trade...")
    results = []
    for i, row in merged.iterrows():
        if i > 0 and i % 200 == 0:
            print(f"  {i}/{len(merged)}...")
        asset = row["asset"]
        direction = row["direction"]
        entry = float(row["entry"])
        r_pct = float(row["r_pct"])
        sl_dist = entry * r_pct / 100
        if direction == "long":
            sl = entry - sl_dist
        else:
            sl = entry + sl_dist
        born_ms = int(row["born_ms"])
        entry_fill_ms = int(row["entry_fill_ms"])

        # Magnet from FVGs at born_ms (or entry_fill_ms — try both)
        # Use born_ms (signal time, before entry fill)
        target_R, magnet_tf = find_target_R(
            entry, sl_dist, direction, asset_fvgs[asset], born_ms)
        if target_R is None:
            # Fallback to baseline 2R
            target_R = MIN_R
            magnet_tf = None

        if direction == "long":
            tp_dyn = entry + target_R * sl_dist
        else:
            tp_dyn = entry - target_R * sl_dist

        # Simulate exit using 1m data
        exit_R_dyn, exit_type_dyn, exit_ms_dyn = simulate_trade_with_dynamic_tp(
            asset_bars_1m[asset], entry_fill_ms, entry, sl, tp_dyn, direction)

        # Baseline: fixed RR=2.0 (just use mfe_R from features for consistency)
        mfe_R = float(row["mfe_R"])
        if mfe_R >= 2.0:
            baseline_R = 2.0
        else:
            baseline_R = -1.0

        results.append({
            "event_idx": int(row["event_idx"]),
            "asset": asset, "direction": direction, "t_id": row["t_id"],
            "born_ms": born_ms, "entry": entry, "r_pct": r_pct,
            "magnet_tf": magnet_tf, "target_R": target_R,
            "tp_dyn": tp_dyn,
            "exit_R_dyn": exit_R_dyn, "exit_type_dyn": exit_type_dyn,
            "baseline_R": baseline_R, "y_true_base": int(baseline_R > 0),
            "win_dyn": int(exit_R_dyn > 0),
            "delta_R": exit_R_dyn - baseline_R,
        })

    df_r = pd.DataFrame(results)
    df_r.to_csv(OUT_DIR / "layer1_simulation.csv", index=False)

    # ─── Step 4. Compare ─────
    print("\n[4/4] Comparison")
    print("\n── Overall ──")
    print(f"Baseline fixed RR=2.0:    "
          f"N={len(df_r)}, WR={df_r.y_true_base.mean()*100:.1f}%, "
          f"Σ R={df_r.baseline_R.sum():.0f}")
    print(f"Dynamic TP (HTF FVG):     "
          f"N={len(df_r)}, WR={df_r.win_dyn.mean()*100:.1f}%, "
          f"Σ R={df_r.exit_R_dyn.sum():.0f}")
    print(f"Δ Σ R: {df_r.exit_R_dyn.sum() - df_r.baseline_R.sum():+.1f}R "
          f"({(df_r.exit_R_dyn.sum() / df_r.baseline_R.sum() - 1)*100:+.1f}%)")

    print("\n── Magnet usage ──")
    mag = df_r.copy()
    mag["has_magnet"] = mag.magnet_tf.notna()
    by_mag = mag.groupby("has_magnet").agg(
        n=("event_idx", "count"),
        mean_target_R=("target_R", "mean"),
        sum_R_base=("baseline_R", "sum"),
        sum_R_dyn=("exit_R_dyn", "sum"),
        wr_base=("y_true_base", "mean"),
        wr_dyn=("win_dyn", "mean"),
    )
    print(by_mag)

    print("\n── Target R distribution ──")
    print(df_r["target_R"].describe())

    print("\n── By asset ──")
    by_asset = df_r.groupby("asset").agg(
        n=("event_idx", "count"),
        wr_base=("y_true_base", "mean"),
        wr_dyn=("win_dyn", "mean"),
        sum_R_base=("baseline_R", "sum"),
        sum_R_dyn=("exit_R_dyn", "sum"),
    )
    by_asset["delta_R"] = by_asset.sum_R_dyn - by_asset.sum_R_base
    print(by_asset)

    print("\n── Magnet TF breakdown ──")
    for tf in ["4h", "6h", "12h", None]:
        sub = df_r[df_r.magnet_tf == tf] if tf else df_r[df_r.magnet_tf.isna()]
        if len(sub) == 0: continue
        label = tf if tf else "no magnet"
        print(f"  {label:>10s}: N={len(sub):>4d}, "
              f"avg target={sub.target_R.mean():.2f}R, "
              f"WR_dyn={sub.win_dyn.mean()*100:.1f}%, "
              f"Σ R_dyn={sub.exit_R_dyn.sum():+.0f}R, "
              f"Δ_R={sub.delta_R.sum():+.0f}R")


if __name__ == "__main__":
    main()
