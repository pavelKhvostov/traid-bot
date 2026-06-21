"""Build 22 picked features for SOL ob_vc events (transfer test for v3.3).

Output: features_v33_picked_SOL.parquet (same schema as BTC+ETH v33 picked)
"""
from __future__ import annotations
import csv
import pathlib
import sys
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v3")))
from features._common import aggregate_all_tfs, hma_np
from features.wait_window import build_wait_window_features


SOL_CSV = pathlib.Path.home() / "traid-bot/data/SOLUSDT_1m_vic_vadim.csv"
SOL_TBM = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/data/SOLUSDT_2h_24types_full_tbm.parquet")
OUT = pathlib.Path("/Users/vadim/smc-lib/strategies/strategy_ob_vc_v33_lean_picked/features_v33_picked_SOL.parquet")

PICKED_HMA = [
    ("15m", 7),  ("20m", 6),  ("1h", 4),   ("90m", 8),  ("2h", 4),
    ("4h", 4),   ("6h", 6),   ("12h", 8),  ("1d", 8),   ("2d", 8),  ("3d", 12),
]
HORIZON_MS = 14 * 24 * 3600 * 1000


def load_1m():
    rows = []
    with SOL_CSV.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
            rows.append((t, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return np.array(rows, dtype=np.float64)


def main():
    t0 = time.time()
    print("=" * 72)
    print("Building SOL 22 picked features for v3.3 transfer test")
    print("=" * 72)

    print("\n[1/5] Loading 1m...")
    rows_1m = load_1m()
    ts_1m = rows_1m[:, 0].astype(np.int64)
    h_1m = rows_1m[:, 2]; l_1m = rows_1m[:, 3]
    print(f"  bars: {len(rows_1m):,}")

    print("\n[2/5] Loading SOL ob_vc events...")
    events = pd.read_parquet(SOL_TBM)
    print(f"  events: {len(events):,}")
    print(f"  touched: {events.touched.sum():,}")

    # Recompute fill_touched + entry_fill_ms via 1m walk (born_ms → first entry touch)
    print("\n[3/5] Computing entry_fill_ms per event...")
    fill_touched = np.zeros(len(events), dtype=bool)
    entry_fill_ms = np.full(len(events), -1, dtype=np.int64)
    for i, row in events.iterrows():
        if pd.isna(row.entry) or pd.isna(row.R):
            continue
        entry = float(row.entry); R = float(row.R)
        born_ms = int(row.born_ms); direction = row.direction
        i_start = int(np.searchsorted(ts_1m, born_ms))
        i_end = min(len(ts_1m) - 1, int(np.searchsorted(ts_1m, born_ms + HORIZON_MS)))
        if i_start >= i_end: continue
        if direction == "long":
            slice_l = l_1m[i_start:i_end+1]
            touch_arr = slice_l <= entry
            if not touch_arr.any(): continue
            touch_rel = int(np.argmax(touch_arr))
        else:
            slice_h = h_1m[i_start:i_end+1]
            touch_arr = slice_h >= entry
            if not touch_arr.any(): continue
            touch_rel = int(np.argmax(touch_arr))
        entry_fill_ms[i] = int(ts_1m[i_start + touch_rel])
        fill_touched[i] = True

    events["entry_fill_ms"] = entry_fill_ms
    events["fill_touched"] = fill_touched
    print(f"  fill_touched: {fill_touched.sum():,}")

    # Compute r_pct & r_pct_pass
    events["r_pct"] = (events.R / events.entry * 100).fillna(0)
    events["r_pct_pass"] = events.r_pct >= 0.5
    print(f"  r_pct_pass: {events.r_pct_pass.sum():,}")
    print(f"  viable (fill_touched & r_pct_pass): {(events.fill_touched & events.r_pct_pass).sum():,}")

    print("\n[4/5] Aggregating to TFs + computing features...")
    bars = aggregate_all_tfs(rows_1m)
    print(f"  TF aggregates: {list(bars.keys())}")

    # ─── Wait features ────────────────────────────
    born_ms_arr = events.born_ms.to_numpy(dtype=np.int64)
    entry_ms_arr = events.entry_fill_ms.to_numpy(dtype=np.int64)
    sl_levels = np.where(
        events.direction == "long",
        events.drop_lo.astype(np.float64),
        events.drop_hi.astype(np.float64),
    )
    entry_levels = events.entry.fillna(0).to_numpy(dtype=np.float64)
    direction_arr = events.direction.to_numpy()

    print("  building wait-window features...")
    wait_feats = build_wait_window_features(
        rows_1m, born_ms_arr, entry_ms_arr, sl_levels, entry_levels, direction_arr)
    print(f"    wait features: {len(wait_feats)}")

    # ─── HMA picked features ────────────────────────
    print("  computing HMA picked (11 features)...")
    hma_feats = {}
    for tf, L in PICKED_HMA:
        if tf not in bars: continue
        bar_arr = bars[tf]
        ts_arr = bar_arr[:, 0].astype(np.int64)
        closes = bar_arr[:, 4]
        if L >= len(closes): continue

        valid_event = entry_ms_arr > 0
        idx_at_event = np.full(len(entry_ms_arr), -1, dtype=np.int64)
        if valid_event.any():
            idx_at_event[valid_event] = np.searchsorted(
                ts_arr, entry_ms_arr[valid_event], side="right") - 1
        valid = (idx_at_event >= 0) & valid_event

        close_at_event = np.full(len(entry_ms_arr), np.nan)
        close_at_event[valid] = closes[idx_at_event[valid]]

        hma_arr = hma_np(closes, L)
        val_now = np.full(len(entry_ms_arr), np.nan)
        val_now[valid] = hma_arr[idx_at_event[valid]]
        with np.errstate(divide="ignore", invalid="ignore"):
            dist_pct = np.where(np.abs(val_now) > 1e-9,
                                  (close_at_event - val_now) / val_now * 100, np.nan)
        col = f"hma_{tf}_{L}_dist_pct"
        hma_feats[col] = dist_pct
    print(f"    HMA features: {len(hma_feats)}")

    # ─── Combine into output ────────────────────────
    print("\n[5/5] Saving...")
    # event_id = synthetic
    events["event_id"] = np.arange(len(events))
    events["asset"] = "SOL"

    keep_meta = ["event_id", "asset", "born_ms", "entry_fill_ms", "direction",
                  "t_id", "n_comp", "entry", "R", "r_pct", "r_pct_pass",
                  "fill_touched", "mfe_R", "mae_R", "sl_hit",
                  "hit_RR_14", "hit_RR_15", "hit_RR_17", "hit_RR_20",
                  "hit_RR_23", "hit_RR_25", "hit_RR_28"]
    out_df = events[keep_meta].copy()
    for k, v in wait_feats.items():
        out_df[k] = v
    for k, v in hma_feats.items():
        out_df[k] = v

    print(f"  shape: {out_df.shape}")
    print(f"  columns: {[c for c in out_df.columns if c.startswith('hma_') or c.startswith('wait_') or c == 'fill_delay_min']}")
    out_df.to_parquet(OUT, index=False)
    print(f"  saved → {OUT} ({OUT.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"\nElapsed: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
