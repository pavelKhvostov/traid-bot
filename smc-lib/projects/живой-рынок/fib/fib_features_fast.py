"""Vectorized + parallel fib_features для PC2.

Изменения от fib_features.py:
- compute_fib_features_for_anchor — fully numpy vectorized (no iterrows)
- joblib parallel по anchor batches (N=6 workers)
- pyarrow datset filter для streaming чтения по batch
- output: per-worker parquet, потом merge

Ожидаемая скорость: 100-300 anch/s × 6 workers = ~1500 anch/s → 228K за 2-3 мин.
"""
from __future__ import annotations
import sys
import time
import argparse
import pathlib
import pandas as pd
import numpy as np
from joblib import Parallel, delayed

SMC_LIB = pathlib.Path.home() / "smc-lib"
SNAPS_PATH = SMC_LIB / "projects/живой-рынок/data/snapshots_2020-01-01_2026-06-15.parquet"
FIBS_PATH = SMC_LIB / "projects/живой-рынок/data/fib_levels_2020-01-01_2026-06-15.parquet"
OUT_PATH = SMC_LIB / "projects/живой-рынок/data/snapshots_with_fib_2020-01-01_2026-06-15.parquet"

CONFLUENCE_PCT = 0.5
FIB_MAX_AGE_DAYS = 365
N_WORKERS = 6


def compute_fib_for_anchor_vec(
    anchor_centers: np.ndarray,
    anchor_los: np.ndarray,
    anchor_his: np.ndarray,
    fibs_active_prices: np.ndarray,
    fibs_active_pcts: np.ndarray,
    fibs_swing_sizes: np.ndarray,
    fibs_tf_weights: np.ndarray,
    fibs_is_golden: np.ndarray,
    fibs_is_ext: np.ndarray,
) -> dict[str, np.ndarray]:
    """Vectorized: K zones × M fibs → 8 feature arrays of length K."""
    K = len(anchor_centers)
    M = len(fibs_active_prices)
    if M == 0:
        return {
            "fib_nearest_dist_pct": np.full(K, 99.0),
            "fib_within_zone": np.zeros(K, dtype=int),
            "fib_confluence_count": np.zeros(K, dtype=int),
            "fib_golden_dist_pct": np.full(K, 99.0),
            "fib_extension_above_pct": np.full(K, 99.0),
            "fib_extension_below_pct": np.full(K, 99.0),
            "fib_swing_size_pct": np.zeros(K),
            "fib_tf_weight_max": np.zeros(K),
        }

    # (K, M) matrix
    diffs = np.abs(fibs_active_prices[None, :] - anchor_centers[:, None])
    nearest_dist = diffs.min(axis=1)
    fib_nearest_dist_pct = (nearest_dist / anchor_centers * 100).astype(np.float32)

    within_mask = ((fibs_active_prices[None, :] >= anchor_los[:, None]) &
                  (fibs_active_prices[None, :] <= anchor_his[:, None]))
    fib_within_zone = within_mask.any(axis=1).astype(np.int8)

    threshold = anchor_centers * CONFLUENCE_PCT / 100.0
    conf_mask = ((fibs_active_prices[None, :] >= (anchor_centers - threshold)[:, None]) &
                 (fibs_active_prices[None, :] <= (anchor_centers + threshold)[:, None]))
    fib_confluence_count = conf_mask.sum(axis=1).astype(np.int16)

    if fibs_is_golden.any():
        golden_diffs = np.abs(fibs_active_prices[fibs_is_golden][None, :] - anchor_centers[:, None])
        golden_min = golden_diffs.min(axis=1)
        fib_golden_dist_pct = (golden_min / anchor_centers * 100).astype(np.float32)
    else:
        fib_golden_dist_pct = np.full(K, 99.0, dtype=np.float32)

    ext_prices = fibs_active_prices[fibs_is_ext]
    if len(ext_prices) > 0:
        diffs_ext = ext_prices[None, :] - anchor_centers[:, None]  # (K, M_ext)
        # Above (positive diff)
        above_mask = diffs_ext > 0
        ext_above_dist = np.where(above_mask, diffs_ext, np.inf).min(axis=1)
        fib_extension_above_pct = np.where(np.isinf(ext_above_dist), 99.0,
                                            ext_above_dist / anchor_centers * 100).astype(np.float32)
        below_mask = diffs_ext < 0
        ext_below_dist = np.where(below_mask, -diffs_ext, np.inf).min(axis=1)
        fib_extension_below_pct = np.where(np.isinf(ext_below_dist), 99.0,
                                            ext_below_dist / anchor_centers * 100).astype(np.float32)
    else:
        fib_extension_above_pct = np.full(K, 99.0, dtype=np.float32)
        fib_extension_below_pct = np.full(K, 99.0, dtype=np.float32)

    # top-3 nearest swing sizes
    sort_idx = np.argsort(diffs, axis=1)[:, :3]
    top3_swings = fibs_swing_sizes[sort_idx]
    fib_swing_size_pct = top3_swings.mean(axis=1).astype(np.float32)

    # tf_weight max in zone
    in_zone_arr = within_mask
    weights_broadcast = np.broadcast_to(fibs_tf_weights[None, :], (K, M))
    weights_masked = np.where(in_zone_arr, weights_broadcast, 0.0)
    fib_tf_weight_max = weights_masked.max(axis=1).astype(np.float32)

    return {
        "fib_nearest_dist_pct": fib_nearest_dist_pct,
        "fib_within_zone": fib_within_zone,
        "fib_confluence_count": fib_confluence_count,
        "fib_golden_dist_pct": fib_golden_dist_pct,
        "fib_extension_above_pct": fib_extension_above_pct,
        "fib_extension_below_pct": fib_extension_below_pct,
        "fib_swing_size_pct": fib_swing_size_pct,
        "fib_tf_weight_max": fib_tf_weight_max,
    }


def process_anchor_batch(
    snaps_batch_df: pd.DataFrame,
    fibs_ts_arr: np.ndarray,
    fibs_df: pd.DataFrame,
    max_age_ms: int,
):
    """Process one batch of (presorted by anchor_ts) snapshot rows."""
    if "zone_center" not in snaps_batch_df.columns:
        snaps_batch_df = snaps_batch_df.copy()
        snaps_batch_df["zone_center"] = (snaps_batch_df["zone_lo"] + snaps_batch_df["zone_hi"]) / 2

    anchor_col = "anchor_ts" if "anchor_ts" in snaps_batch_df.columns else "ts"
    grouped = snaps_batch_df.groupby(anchor_col, sort=False)
    new_cols = {k: [] for k in (
        "fib_nearest_dist_pct", "fib_within_zone", "fib_confluence_count",
        "fib_golden_dist_pct", "fib_extension_above_pct", "fib_extension_below_pct",
        "fib_swing_size_pct", "fib_tf_weight_max",
    )}

    # Precompute fib arrays
    all_fib_prices = fibs_df["level_price"].to_numpy()
    all_fib_pcts = fibs_df["fib_pct"].to_numpy()
    all_fib_swings = fibs_df["swing_size_pct"].to_numpy()
    all_fib_tfws = fibs_df["tf_weight"].to_numpy()
    all_fib_is_golden = fibs_df["fib_name"].values == "retrace_618"
    all_fib_is_ext = all_fib_pcts > 1.0

    for anchor_ts, grp in grouped:
        anchor_ts = int(anchor_ts)
        min_ts = anchor_ts - max_age_ms
        lo_idx = np.searchsorted(fibs_ts_arr, min_ts, side="left")
        hi_idx = np.searchsorted(fibs_ts_arr, anchor_ts, side="right")
        if hi_idx <= lo_idx:
            f_prices = np.array([])
            f_pcts = f_swings = f_tfws = np.array([])
            f_golden = f_ext = np.array([], dtype=bool)
        else:
            f_prices = all_fib_prices[lo_idx:hi_idx]
            f_pcts = all_fib_pcts[lo_idx:hi_idx]
            f_swings = all_fib_swings[lo_idx:hi_idx]
            f_tfws = all_fib_tfws[lo_idx:hi_idx]
            f_golden = all_fib_is_golden[lo_idx:hi_idx]
            f_ext = all_fib_is_ext[lo_idx:hi_idx]

        centers = grp["zone_center"].to_numpy()
        los = grp["zone_lo"].to_numpy()
        his = grp["zone_hi"].to_numpy()

        feats = compute_fib_for_anchor_vec(
            centers, los, his, f_prices, f_pcts, f_swings, f_tfws, f_golden, f_ext
        )
        for k, v in feats.items():
            new_cols[k].extend(v.tolist())

    snaps_batch_df = snaps_batch_df.reset_index(drop=True)
    for k, v in new_cols.items():
        snaps_batch_df[k] = v
    return snaps_batch_df


def worker_process_rg(rg_idx, snaps_path, fibs_df, max_age_ms):
    """Module-level worker — pickleable for joblib."""
    import pyarrow.parquet as pq
    pf = pq.ParquetFile(snaps_path)
    table = pf.read_row_group(rg_idx)
    df = table.to_pandas()
    fibs_ts_arr = fibs_df["ts"].to_numpy()
    return process_anchor_batch(df, fibs_ts_arr, fibs_df, max_age_ms)


def main():
    import pyarrow as pa
    import pyarrow.parquet as pq

    print(f"Loading fib levels...", file=sys.stderr, flush=True)
    fibs = pd.read_parquet(FIBS_PATH)
    fibs = fibs.sort_values("ts").reset_index(drop=True)
    max_age_ms = FIB_MAX_AGE_DAYS * 24 * 3600 * 1000
    print(f"  {len(fibs):,} fib levels", file=sys.stderr, flush=True)

    pf = pq.ParquetFile(SNAPS_PATH)
    total_rows = pf.metadata.num_rows
    n_row_groups = pf.metadata.num_row_groups
    print(f"Snapshots: {total_rows:,} rows × {n_row_groups} row groups",
          file=sys.stderr, flush=True)

    print(f"\nParallel processing with {N_WORKERS} workers...", file=sys.stderr, flush=True)
    t0 = time.time()

    writer = None
    rows_written = 0
    CHUNK = N_WORKERS  # Pool batch size
    snaps_path_str = str(SNAPS_PATH)
    for batch_start in range(0, n_row_groups, CHUNK):
        batch_end = min(batch_start + CHUNK, n_row_groups)
        results = Parallel(n_jobs=N_WORKERS, backend="loky", batch_size=1)(
            delayed(worker_process_rg)(rg, snaps_path_str, fibs, max_age_ms)
            for rg in range(batch_start, batch_end)
        )
        for df in results:
            table = pa.Table.from_pandas(df, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(str(OUT_PATH), table.schema, compression="snappy")
            writer.write_table(table)
            rows_written += len(table)
        elapsed = time.time() - t0
        rate_rg = batch_end / elapsed
        eta_min = (n_row_groups - batch_end) / rate_rg / 60
        print(f"  [{batch_end}/{n_row_groups} rg] {rows_written:,} rows, "
              f"{elapsed:.0f}s, ETA {eta_min:.1f}min", file=sys.stderr, flush=True)

    if writer is not None:
        writer.close()

    size_mb = OUT_PATH.stat().st_size / 1024 / 1024
    print(f"\nSaved: {OUT_PATH} ({size_mb:.1f} MB, {rows_written:,} rows) "
          f"in {time.time()-t0:.0f}s", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
