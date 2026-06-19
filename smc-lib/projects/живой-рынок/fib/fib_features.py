"""Phase 5 — Augment snapshots с Fibonacci features.

Per (anchor_ts, zone) computim 8 fib-features:
  fib_nearest_dist_pct      distance к ближайшему fib level / zone_center * 100
  fib_within_zone           1 если любой fib level в [zone_lo, zone_hi]
  fib_confluence_count      число fib levels в ±0.5% от zone_center
  fib_golden_dist_pct       distance к ближайшему 61.8% retrace
  fib_extension_above_pct   distance к ближайшей extension сверху (resist candidate)
  fib_extension_below_pct   distance к ближайшей extension снизу (support candidate)
  fib_swing_size_pct        размер swing откуда взят nearest fib (среднее по top-3)
  fib_tf_weight_max         max TF weight среди fibs в zone (1D=8, 12h=6, ...)
"""
from __future__ import annotations
import sys
import time
import argparse
import pathlib
import pandas as pd
import numpy as np

SMC_LIB = pathlib.Path.home() / "smc-lib"
SNAPS_PATH = SMC_LIB / "projects/живой-рынок/data/snapshots_2020-01-01_2026-06-15.parquet"
FIBS_PATH = SMC_LIB / "projects/живой-рынок/data/fib_levels_2020-01-01_2026-06-15.parquet"
OUT_PATH = SMC_LIB / "projects/живой-рынок/data/snapshots_with_fib_2020-01-01_2026-06-15.parquet"

CONFLUENCE_PCT = 0.5     # ±0.5% = confluence threshold
FIB_MAX_AGE_DAYS = 365   # fib level живёт максимум 1 год


def compute_fib_features_for_anchor(zone_rows: pd.DataFrame, fibs_active: pd.DataFrame) -> pd.DataFrame:
    """Per-zone fib features для одного anchor.

    zone_rows: rows from snapshots с колонками [zone_lo, zone_hi, zone_center]
    fibs_active: fib levels active at anchor_ts (born_ts <= anchor_ts, age <= MAX_AGE)
    """
    if fibs_active.empty:
        zone_rows = zone_rows.copy()
        zone_rows["fib_nearest_dist_pct"] = 99.0
        zone_rows["fib_within_zone"] = 0
        zone_rows["fib_confluence_count"] = 0
        zone_rows["fib_golden_dist_pct"] = 99.0
        zone_rows["fib_extension_above_pct"] = 99.0
        zone_rows["fib_extension_below_pct"] = 99.0
        zone_rows["fib_swing_size_pct"] = 0.0
        zone_rows["fib_tf_weight_max"] = 0.0
        return zone_rows

    fib_prices = fibs_active["level_price"].to_numpy()
    fib_pcts = fibs_active["fib_pct"].to_numpy()
    fib_swing_sizes = fibs_active["swing_size_pct"].to_numpy()
    fib_tf_weights = fibs_active["tf_weight"].to_numpy()
    is_golden = fibs_active["fib_name"].values == "retrace_618"
    is_extension = fib_pcts > 1.0

    feats = []
    for _, row in zone_rows.iterrows():
        center = float(row["zone_center"])
        lo = float(row["zone_lo"])
        hi = float(row["zone_hi"])

        # Distance к nearest fib level (% от center)
        diffs = np.abs(fib_prices - center)
        nearest_dist_pct = float(diffs.min() / center * 100) if center > 0 else 99.0

        # Within zone — fib в [lo, hi]?
        within = ((fib_prices >= lo) & (fib_prices <= hi)).any()

        # Confluence count — fibs в ±CONFLUENCE_PCT от center
        threshold = center * CONFLUENCE_PCT / 100
        confluence_count = int(((fib_prices >= center - threshold)
                                & (fib_prices <= center + threshold)).sum())

        # Golden retrace distance
        if is_golden.any():
            golden_diffs = np.abs(fib_prices[is_golden] - center)
            golden_dist_pct = float(golden_diffs.min() / center * 100)
        else:
            golden_dist_pct = 99.0

        # Extension above/below
        ext_prices = fib_prices[is_extension]
        ext_above = ext_prices[ext_prices > center]
        ext_below = ext_prices[ext_prices < center]
        ext_above_pct = float((ext_above.min() - center) / center * 100) if len(ext_above) else 99.0
        ext_below_pct = float((center - ext_below.max()) / center * 100) if len(ext_below) else 99.0

        # Avg swing size of TOP-3 nearest fibs
        top3_idx = np.argsort(diffs)[:3]
        top3_swing = float(fib_swing_sizes[top3_idx].mean()) if len(top3_idx) > 0 else 0.0

        # Max TF weight среди fibs в zone (или в confluence range)
        in_zone_mask = (fib_prices >= lo) & (fib_prices <= hi)
        if in_zone_mask.any():
            tf_weight_max = float(fib_tf_weights[in_zone_mask].max())
        else:
            tf_weight_max = 0.0

        feats.append({
            "fib_nearest_dist_pct": nearest_dist_pct,
            "fib_within_zone": int(within),
            "fib_confluence_count": confluence_count,
            "fib_golden_dist_pct": golden_dist_pct,
            "fib_extension_above_pct": ext_above_pct,
            "fib_extension_below_pct": ext_below_pct,
            "fib_swing_size_pct": top3_swing,
            "fib_tf_weight_max": tf_weight_max,
        })

    zone_rows = zone_rows.copy().reset_index(drop=True)
    feats_df = pd.DataFrame(feats)
    return pd.concat([zone_rows, feats_df], axis=1)


def main():
    """Streaming version: читает snapshots по batches, augments, пишет инкрементально."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    import pyarrow.dataset as ds

    print(f"Loading fib levels from {FIBS_PATH.name}...", file=sys.stderr, flush=True)
    fibs = pd.read_parquet(FIBS_PATH)
    print(f"  {len(fibs):,} fib levels", file=sys.stderr, flush=True)
    fibs = fibs.sort_values("ts").reset_index(drop=True)
    fib_ts_arr = fibs["ts"].to_numpy()
    max_age_ms = FIB_MAX_AGE_DAYS * 24 * 3600 * 1000

    pf = pq.ParquetFile(SNAPS_PATH)
    total_rows = pf.metadata.num_rows
    print(f"Snapshots: {total_rows:,} rows (streaming mode)", file=sys.stderr, flush=True)

    dataset = ds.dataset(str(SNAPS_PATH), format="parquet")
    writer = None
    t0 = time.time()
    rows_written = 0
    current_anchor_ts = None
    anchor_buffer_rows = []
    fibs_active_cache = None
    anchor_count = 0
    last_print = t0

    def flush_anchor(anchor_ts, rows_list, fibs_active):
        nonlocal writer, rows_written, anchor_count
        if not rows_list:
            return
        zone_rows = pd.DataFrame(rows_list)
        if "zone_center" not in zone_rows.columns:
            zone_rows["zone_center"] = (zone_rows["zone_lo"] + zone_rows["zone_hi"]) / 2
        augmented = compute_fib_features_for_anchor(zone_rows, fibs_active)
        table = pa.Table.from_pandas(augmented, preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(str(OUT_PATH), table.schema, compression="snappy")
        writer.write_table(table)
        rows_written += len(table)
        anchor_count += 1

    for batch in dataset.to_batches(batch_size=200_000):
        df_batch = batch.to_pandas()
        anchor_col = "anchor_ts" if "anchor_ts" in df_batch.columns else "ts"
        for _, row in df_batch.iterrows():
            a_ts = int(row[anchor_col])
            if current_anchor_ts is None:
                current_anchor_ts = a_ts
                min_ts = a_ts - max_age_ms
                lo_idx = np.searchsorted(fib_ts_arr, min_ts, side="left")
                hi_idx = np.searchsorted(fib_ts_arr, a_ts, side="right")
                fibs_active_cache = fibs.iloc[lo_idx:hi_idx]
            if a_ts != current_anchor_ts:
                flush_anchor(current_anchor_ts, anchor_buffer_rows, fibs_active_cache)
                current_anchor_ts = a_ts
                min_ts = a_ts - max_age_ms
                lo_idx = np.searchsorted(fib_ts_arr, min_ts, side="left")
                hi_idx = np.searchsorted(fib_ts_arr, a_ts, side="right")
                fibs_active_cache = fibs.iloc[lo_idx:hi_idx]
                anchor_buffer_rows = [row.to_dict()]
                if time.time() - last_print > 30:
                    elapsed = time.time() - t0
                    print(f"  [{anchor_count:,}] {anchor_count/elapsed:.0f} anchors/s, "
                          f"{rows_written:,} rows written", file=sys.stderr, flush=True)
                    last_print = time.time()
            else:
                anchor_buffer_rows.append(row.to_dict())

    # Flush last anchor
    if anchor_buffer_rows:
        flush_anchor(current_anchor_ts, anchor_buffer_rows, fibs_active_cache)

    if writer is not None:
        writer.close()

    size_mb = OUT_PATH.stat().st_size / 1024 / 1024
    print(f"\nSaved: {OUT_PATH} ({size_mb:.1f} MB, {rows_written:,} rows) "
          f"in {time.time()-t0:.0f}s",
          file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
