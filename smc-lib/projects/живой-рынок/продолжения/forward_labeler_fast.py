"""Vectorized + parallel forward_labeler для PC2.

Изменения от forward_labeler.py:
- find_first_hit_vec — vectorized matrix ops для всех zones одного anchor
- joblib parallel по anchor batches (N=6 workers)
- pyarrow ParquetFile.read_row_group для streaming
"""
from __future__ import annotations
import sys
import csv
import time
import pathlib
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from joblib import Parallel, delayed

SMC_LIB = pathlib.Path.home() / "smc-lib"
CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
SNAPSHOTS_PATH = SMC_LIB / "projects/живой-рынок/data/snapshots_2020-01-01_2026-06-15.parquet"
OUT_PATH = SMC_LIB / "projects/живой-рынок/data/labels_2020-01-01_2026-06-15.parquet"

MS = 60_000
FORWARD_DAYS = 30
FORWARD_MS = FORWARD_DAYS * 24 * 3600 * 1000
UTC = timezone.utc
N_WORKERS = 6


def load_1m_arrays():
    print(f"Loading 1m CSV...", file=sys.stderr, flush=True)
    ts, h, l = [], [], []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0]).replace(tzinfo=UTC)
            ts.append(int(t.timestamp() * 1000))
            h.append(float(r[2]))
            l.append(float(r[3]))
    return np.array(ts, dtype=np.int64), np.array(h, dtype=np.float32), np.array(l, dtype=np.float32)


def find_first_hit_vec(zones_lo, zones_hi, ts_arr, h_arr, l_arr,
                       anchor_ts, horizon_ms):
    """Vectorized first-hit search.
    Returns (best_zone_idx, hit_ts) or (None, None).
    """
    end_ts = anchor_ts + horizon_ms
    start_idx = np.searchsorted(ts_arr, anchor_ts, side="left")
    end_idx = np.searchsorted(ts_arr, end_ts, side="right")
    if start_idx >= end_idx:
        return None, None
    h_slice = h_arr[start_idx:end_idx]
    l_slice = l_arr[start_idx:end_idx]
    ts_slice = ts_arr[start_idx:end_idx]

    K = len(zones_lo)
    # (K, N_bars) — bar.low ≤ zone_hi AND bar.high ≥ zone_lo
    hit_mask = (l_slice[None, :] <= zones_hi[:, None]) & (h_slice[None, :] >= zones_lo[:, None])
    # Per-zone first hit position
    has_hit = hit_mask.any(axis=1)
    if not has_hit.any():
        return None, None
    first_hit_per_zone = np.where(hit_mask, np.arange(hit_mask.shape[1]), hit_mask.shape[1])
    first_hit_per_zone = first_hit_per_zone.min(axis=1)
    first_hit_per_zone[~has_hit] = hit_mask.shape[1]  # no-hit zones go to "infinity"

    best_zone = int(first_hit_per_zone.argmin())
    best_pos = int(first_hit_per_zone[best_zone])
    if best_pos >= hit_mask.shape[1]:
        return None, None
    return best_zone, int(ts_slice[best_pos])


def process_anchor_group(anchor_ts, group_df, ts_arr, h_arr, l_arr):
    """Process one anchor's zones."""
    anchor_ts = int(anchor_ts)
    current_price = float(group_df["current_price"].iloc[0])
    zones_lo = group_df["zone_lo"].to_numpy(dtype=np.float32)
    zones_hi = group_df["zone_hi"].to_numpy(dtype=np.float32)
    zones_center = group_df["zone_center"].to_numpy(dtype=np.float32)

    best_zone_idx, hit_ts = find_first_hit_vec(zones_lo, zones_hi, ts_arr, h_arr, l_arr,
                                                anchor_ts, FORWARD_MS)
    if best_zone_idx is None:
        return None

    main_row = group_df.iloc[best_zone_idx]
    main_center = float(zones_center[best_zone_idx])
    main_magnitude = (main_center - current_price) / current_price * 100
    main_direction = "up" if main_center > current_price else "down"
    main_time_hr = (hit_ts - anchor_ts) / 3600000

    # Correction: first hit zone in [anchor, main_ts) excluding main
    if main_time_hr > 0.25:
        mask = np.ones(len(zones_lo), dtype=bool)
        mask[best_zone_idx] = False
        sub_lo = zones_lo[mask]
        sub_hi = zones_hi[mask]
        sub_center = zones_center[mask]
        sub_orig_idx = np.flatnonzero(mask)
        corr_zone_idx_sub, corr_ts = find_first_hit_vec(
            sub_lo, sub_hi, ts_arr, h_arr, l_arr,
            anchor_ts, hit_ts - anchor_ts
        )
        if corr_zone_idx_sub is not None:
            corr_zone_idx = int(sub_orig_idx[corr_zone_idx_sub])
            corr_row = group_df.iloc[corr_zone_idx]
            corr_center_v = float(sub_center[corr_zone_idx_sub])
            corr_magnitude = (corr_center_v - current_price) / current_price * 100
            corr_time_hr = (corr_ts - anchor_ts) / 3600000
            corr_zone_label = f"{corr_row['element_type']}_{corr_row['tf']}_{corr_row['direction']}"
        else:
            corr_zone_label, corr_center_v, corr_magnitude, corr_time_hr = "", 0.0, 0.0, 0.0
    else:
        corr_zone_label, corr_center_v, corr_magnitude, corr_time_hr = "", 0.0, 0.0, 0.0

    return {
        "anchor_id": int(group_df["anchor_id"].iloc[0]),
        "anchor_ts": anchor_ts,
        "current_price": current_price,
        "main_goal_element": main_row["element_type"],
        "main_goal_tf": main_row["tf"],
        "main_goal_direction": main_row["direction"],
        "main_goal_zone_lo": float(main_row["zone_lo"]),
        "main_goal_zone_hi": float(main_row["zone_hi"]),
        "main_goal_center": main_center,
        "main_goal_time_hr": main_time_hr,
        "main_goal_magnitude_pct": main_magnitude,
        "direction": main_direction,
        "correction_label": corr_zone_label,
        "correction_center": corr_center_v,
        "correction_time_hr": corr_time_hr,
        "correction_magnitude_pct": corr_magnitude,
        "main_zone_idx": int(best_zone_idx),
    }


# Worker-local cache: each subprocess loads 1m once
_WORKER_TS = None
_WORKER_H = None
_WORKER_L = None


def _ensure_worker_1m_loaded():
    global _WORKER_TS, _WORKER_H, _WORKER_L
    if _WORKER_TS is None:
        _WORKER_TS, _WORKER_H, _WORKER_L = load_1m_arrays()


def worker_process_row_group(rg_idx):
    """Worker: load 1m arrays once (cached), process one row group."""
    import pyarrow.parquet as pq
    _ensure_worker_1m_loaded()
    pf = pq.ParquetFile(SNAPSHOTS_PATH)
    table = pf.read_row_group(rg_idx)
    df = table.to_pandas()
    if "zone_center" not in df.columns:
        df["zone_center"] = (df["zone_lo"] + df["zone_hi"]) / 2
    out = []
    anchor_col = "anchor_ts" if "anchor_ts" in df.columns else "ts"
    for anchor_ts, grp in df.groupby(anchor_col, sort=False):
        r = process_anchor_group(anchor_ts, grp, _WORKER_TS, _WORKER_H, _WORKER_L)
        if r is not None:
            out.append(r)
    return out


def main():
    import pyarrow.parquet as pq
    pf = pq.ParquetFile(SNAPSHOTS_PATH)
    n_row_groups = pf.metadata.num_row_groups
    print(f"Snapshots: {pf.metadata.num_rows:,} rows × {n_row_groups} row groups",
          file=sys.stderr, flush=True)

    print(f"\nParallel processing with {N_WORKERS} workers (each loads 1m once)...",
          file=sys.stderr, flush=True)
    t0 = time.time()

    # Process all row groups in parallel. Workers self-cache 1m arrays.
    all_results = Parallel(n_jobs=N_WORKERS, backend="loky", verbose=5)(
        delayed(worker_process_row_group)(rg)
        for rg in range(n_row_groups)
    )

    flat = [r for sublist in all_results for r in sublist]
    df = pd.DataFrame(flat)
    df.to_parquet(OUT_PATH, index=False)

    print(f"\nProcessed: {len(flat):,} labels", file=sys.stderr, flush=True)
    print(f"Saved: {OUT_PATH} ({OUT_PATH.stat().st_size / 1024 / 1024:.1f} MB) "
          f"in {time.time()-t0:.0f}s", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
