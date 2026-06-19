"""v4 COMPREHENSIVE feature builder — все семейства honest.

v3.5 (601 HMA + 60 cross + 11 wait) + 88 NEW:
  77 candle structure (7 per TF × 11 TFs)
  11 volatility/regime (ATR per TF, BB width, ratios)
   5 calendar (hour, dow, dom, month, wom)

Total: ~750 features (cluster prune to ~250-350 on PC1)
For BTC + ETH + SOL.

Output: features_v4_comprehensive.parquet
"""
from __future__ import annotations
import pathlib
import sys
import time
import csv
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from features._common import load_1m_full, aggregate_all_tfs
from features.hma_at_entry_honest import build_hma_features_at_entry_honest
from features.cross_tf_crosses import build_cross_tf_features
from features.candle_structure import build_candle_features
from features.volatility_calendar import build_volatility_features, build_calendar_features
from features.wait_window import build_wait_window_features


REPO = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc")
LABELS_BTC_ETH = REPO / "ml_v2" / "labels_v2.parquet"
SOL_PARQUET = REPO / "data" / "SOLUSDT_2h_24types_full_tbm.parquet"
OUT = REPO / "ml_v3" / "features_v4_comprehensive.parquet"
SOL_CSV = pathlib.Path.home() / "traid-bot/data/SOLUSDT_1m_vic_vadim.csv"


def load_sol_1m():
    rows = []
    with SOL_CSV.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
            rows.append((t, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return np.array(rows, dtype=np.float64)


def prepare_sol_events():
    """SOL events with same schema as labels_v2.parquet for unified processing."""
    sol = pd.read_parquet(SOL_PARQUET)
    sol = sol.copy()
    sol["asset"] = "SOL"
    sol["event_id"] = np.arange(len(sol)) + 1_000_000
    sol["r_pct"] = (sol.R / sol.entry * 100).fillna(0)
    sol["r_pct_pass"] = sol.r_pct >= 0.5

    rows_1m = load_sol_1m()
    ts_1m = rows_1m[:, 0].astype(np.int64)
    h_1m = rows_1m[:, 2]; l_1m = rows_1m[:, 3]
    HORIZON_MS = 14 * 24 * 3600 * 1000

    fill_touched = np.zeros(len(sol), dtype=bool)
    entry_fill_ms = np.full(len(sol), -1, dtype=np.int64)
    fill_delay_min = np.full(len(sol), np.nan)
    for i, row in sol.iterrows():
        if pd.isna(row.entry) or pd.isna(row.R): continue
        entry = float(row.entry); direction = row.direction
        born_ms = int(row.born_ms)
        i_start = int(np.searchsorted(ts_1m, born_ms))
        i_end = min(len(ts_1m) - 1, int(np.searchsorted(ts_1m, born_ms + HORIZON_MS)))
        if i_start >= i_end: continue
        if direction == "long":
            arr = l_1m[i_start:i_end+1] <= entry
        else:
            arr = h_1m[i_start:i_end+1] >= entry
        if not arr.any(): continue
        rel = int(np.argmax(arr))
        entry_fill_ms[i] = int(ts_1m[i_start + rel])
        fill_touched[i] = True
        fill_delay_min[i] = (entry_fill_ms[i] - born_ms) / 60_000

    sol["entry_fill_ms"] = entry_fill_ms
    sol["fill_touched"] = fill_touched
    sol["fill_delay_min"] = fill_delay_min
    sol["extreme"] = sol.extreme
    return sol


def main():
    t0 = time.time()
    print("=" * 72)
    print("v4 COMPREHENSIVE Feature Builder (BTC + ETH + SOL)")
    print("=" * 72)

    print("\n[1/5] Loading BTC + ETH labels...")
    events_be = pd.read_parquet(LABELS_BTC_ETH)
    print(f"  BTC+ETH events: {len(events_be):,}")

    events_be["entry_fill_ms"] = np.where(
        events_be["fill_touched"],
        events_be["born_ms"] + (events_be["fill_delay_min"].fillna(0) * 60_000).astype(np.int64),
        -1
    ).astype(np.int64)

    print("\n[1.5/5] Loading + processing SOL events...")
    events_sol = prepare_sol_events()
    print(f"  SOL events: {len(events_sol):,}, touched: {events_sol.fill_touched.sum():,}")

    # Unify columns: only keep what both have
    common_cols = ["event_id", "asset", "born_ms", "entry_fill_ms", "direction",
                    "t_id", "n_comp", "entry", "R", "r_pct", "r_pct_pass",
                    "fill_touched", "mfe_R", "mae_R", "sl_hit",
                    "hit_RR_14", "hit_RR_15", "hit_RR_17", "hit_RR_20",
                    "hit_RR_23", "hit_RR_25", "hit_RR_28"]
    # Add hit_RR_10 (RR=1) — calculate from mfe_R
    events_be["hit_RR_10"] = (events_be.mfe_R >= 1.0).astype(int)
    events_sol["hit_RR_10"] = (events_sol.mfe_R >= 1.0).astype(int)

    common_cols.insert(-7, "hit_RR_10")

    # SOL doesn't have exit_reason — skip it. Be ok.
    events = pd.concat([
        events_be[common_cols].reset_index(drop=True),
        events_sol[common_cols].reset_index(drop=True),
    ], ignore_index=True)
    print(f"  Combined events: {len(events):,} (BTC+ETH+SOL)")
    print(f"  Viable (fill & r_pct≥0.5%): {(events.fill_touched & events.r_pct_pass).sum():,}")

    feature_dicts = {}

    for asset in ("BTC", "ETH", "SOL"):
        symbol = f"{asset}USDT"
        mask = (events.asset == asset).to_numpy()
        if mask.sum() == 0: continue

        born_subset = events.loc[mask, "born_ms"].to_numpy(dtype=np.int64)
        entry_subset = events.loc[mask, "entry_fill_ms"].to_numpy(dtype=np.int64)
        entry_levels = events.loc[mask, "entry"].fillna(0).to_numpy(dtype=np.float64)
        direction_subset = events.loc[mask, "direction"].to_numpy()
        # SL levels (NEEDS drop_lo/drop_hi from original — fallback: derive from R)
        # For wait features SL passed-in (but we don't have drop_lo in unified events)
        # Use derived: SL = entry - R for long, entry + R for short
        R_vals = events.loc[mask, "R"].fillna(0).to_numpy(dtype=np.float64)
        sl_subset = np.where(direction_subset == "long",
                              entry_levels - R_vals, entry_levels + R_vals)

        t1 = time.time()
        print(f"\n[2/5] [{asset}] loading 1m + aggregating...")
        if asset == "SOL":
            rows_1m = load_sol_1m()
        else:
            rows_1m = load_1m_full(symbol)
        bars = aggregate_all_tfs(rows_1m)
        print(f"  1m: {len(rows_1m):,}  ({time.time()-t1:.1f}s)")

        t2 = time.time()
        print(f"[3/5] [{asset}] building features...")

        print(f"  HMA honest live...")
        feats = build_hma_features_at_entry_honest(bars, rows_1m, entry_subset)
        print(f"    {len(feats)} HMA features")

        print(f"  Cross-TF crosses...")
        cross = build_cross_tf_features(bars, rows_1m, entry_subset)
        feats.update(cross)
        print(f"    {len(cross)} cross features")

        print(f"  Candle structure...")
        candle = build_candle_features(bars, entry_subset)
        feats.update(candle)
        print(f"    {len(candle)} candle features")

        print(f"  Volatility...")
        vol = build_volatility_features(bars, entry_subset)
        feats.update(vol)
        print(f"    {len(vol)} volatility features")

        print(f"  Calendar...")
        cal = build_calendar_features(entry_subset)
        feats.update(cal)
        print(f"    {len(cal)} calendar features")

        print(f"  Wait window...")
        ww = build_wait_window_features(rows_1m, born_subset, entry_subset,
                                          sl_subset, entry_levels, direction_subset)
        feats.update(ww)
        print(f"    {len(ww)} wait features")

        print(f"  Total per asset: {len(feats)} features  ({time.time()-t2:.1f}s)")

        for k, v in feats.items():
            if k not in feature_dicts:
                feature_dicts[k] = np.full(len(events), np.nan)
            feature_dicts[k][mask] = v

    print(f"\n[4/5] Combining + saving...")
    df_feat = pd.DataFrame(feature_dicts, index=events.index)

    df_final = pd.concat([events.reset_index(drop=True),
                            df_feat.reset_index(drop=True)], axis=1)
    # Normalize event_id to string (BTC+ETH had str, SOL had int)
    df_final["event_id"] = df_final["event_id"].astype(str)
    df_final.to_parquet(OUT, index=False)
    size_mb = OUT.stat().st_size / 1024 / 1024
    print(f"\n  shape: {df_final.shape}  size: {size_mb:.1f} MB")
    print(f"  features built: {len(df_feat.columns)}")
    print(f"  saved -> {OUT}")
    print(f"\n[5/5] Done. Total: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
