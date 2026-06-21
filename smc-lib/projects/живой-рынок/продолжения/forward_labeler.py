"""Phase 3 — Forward 30d ground truth labeler.

Per spec §5: для каждого 15-min anchor смотрим вперёд 30 дней на 1m данных
и находим первую 4h+ zone которая была hit (main_goal). Также находим correction
zone — первую 4h+ zone hit между anchor и main_goal arrival.

Input:
  - snapshots.parquet — per-anchor 4h+ candidates с zone_lo/hi
  - 1m CSV — для forward lookup

Output: labels.parquet с колонками:
  anchor_id, anchor_ts, current_price,
  main_goal_zone_id, main_goal_zone_center, main_goal_action, main_goal_time_hr, main_goal_magnitude_pct,
  correction_zone_id, correction_zone_center, correction_time_hr, correction_magnitude_pct,
  direction (up/down)
"""
from __future__ import annotations

import sys
import csv
import time
import bisect
import pathlib
import argparse
from datetime import datetime, timezone

import numpy as np
import pandas as pd

SMC_LIB = pathlib.Path.home() / "smc-lib"
sys.path.insert(0, str(SMC_LIB))

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
SNAPSHOTS_PATH = SMC_LIB / "projects/живой-рынок/data/snapshots_2020-01-01_2026-06-15.parquet"
OUT_PATH = SMC_LIB / "projects/живой-рынок/data/labels_2020-01-01_2026-06-15.parquet"

MS = 60_000
FORWARD_DAYS = 30
FORWARD_MS = FORWARD_DAYS * 24 * 3600 * 1000
UTC = timezone.utc


def load_1m_arrays():
    """Load 1m bars → arrays of (ts, high, low, close) для forward scan."""
    print(f"Loading 1m CSV...", file=sys.stderr, flush=True)
    ts, h, l, c = [], [], [], []
    with CSV_PATH.open() as f:
        rd = csv.reader(f)
        next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0]).replace(tzinfo=UTC)
            ts.append(int(t.timestamp() * 1000))
            h.append(float(r[2]))
            l.append(float(r[3]))
            c.append(float(r[4]))
    return np.array(ts), np.array(h), np.array(l), np.array(c)


def find_first_hit(zones_df, ts_arr, h_arr, l_arr, anchor_ts, horizon_ms):
    """Find first zone hit in forward window.

    A zone is "hit" when bar.low ≤ zone_hi AND bar.high ≥ zone_lo.
    Returns (zone_row, hit_idx_1m) или (None, None).
    """
    end_ts = anchor_ts + horizon_ms
    start_idx = np.searchsorted(ts_arr, anchor_ts, side="left")
    end_idx = np.searchsorted(ts_arr, end_ts, side="right")

    if start_idx >= end_idx:
        return None, None

    h_slice = h_arr[start_idx:end_idx]
    l_slice = l_arr[start_idx:end_idx]
    ts_slice = ts_arr[start_idx:end_idx]

    best_hit_idx = None
    best_zone = None
    for idx, row in zones_df.iterrows():
        zlo, zhi = row["zone_lo"], row["zone_hi"]
        # Bar hits zone if l ≤ zhi AND h ≥ zlo
        hit_mask = (l_slice <= zhi) & (h_slice >= zlo)
        hit_positions = np.where(hit_mask)[0]
        if len(hit_positions) == 0:
            continue
        first_hit = hit_positions[0]
        if best_hit_idx is None or first_hit < best_hit_idx:
            best_hit_idx = first_hit
            best_zone = (idx, row, ts_slice[first_hit])
    return best_zone, best_hit_idx


def main(start_date: str = "2020-01-01", end_date: str = "2026-06-15"):
    """Streaming forward labeler — читает snapshots по row groups (bounded RAM)."""
    import pyarrow.parquet as pq
    import pyarrow.dataset as ds

    # Узнаём metadata без полной загрузки
    pf = pq.ParquetFile(SNAPSHOTS_PATH)
    total_rows = pf.metadata.num_rows
    print(f"Snapshots: {total_rows:,} rows × {len(pf.schema_arrow):,} cols (streaming mode)",
          file=sys.stderr, flush=True)

    ts_arr, h_arr, l_arr, c_arr = load_1m_arrays()
    print(f"  {len(ts_arr):,} 1m bars", file=sys.stderr, flush=True)

    # Streaming: читаем dataset партиями row groups, накапливаем rows для current anchor_id.
    # Snapshots отсортированы по anchor_ts → anchor_id contiguous.
    NEEDED_COLS = ["anchor_id", "anchor_ts", "current_price", "element_type",
                   "tf", "direction", "zone_lo", "zone_hi", "zone_center"]
    dataset = ds.dataset(str(SNAPSHOTS_PATH), format="parquet")
    out_rows = []
    t_start = time.time()
    n_processed = 0

    current_anchor_id = None
    group_buffer = []

    def flush_anchor(anchor_id, rows):
        if not rows:
            return
        group = pd.DataFrame(rows)
        anchor_ts = int(group["anchor_ts"].iloc[0])
        current_price = float(group["current_price"].iloc[0])
        first_hit, hit_idx = find_first_hit(group, ts_arr, h_arr, l_arr,
                                             anchor_ts, FORWARD_MS)
        if first_hit is None:
            return
        main_idx, main_row, main_ts = first_hit
        main_center = float(main_row["zone_center"])
        main_magnitude = (main_center - current_price) / current_price * 100
        main_direction = "up" if main_center > current_price else "down"
        main_time_hr = (main_ts - anchor_ts) / 3600000

        # Correction
        if main_time_hr > 0.25:
            sub_group = group[group.index != main_idx]
            corr_hit, _ = find_first_hit(sub_group, ts_arr, h_arr, l_arr,
                                         anchor_ts, main_ts - anchor_ts)
            if corr_hit:
                corr_idx, corr_row, corr_ts = corr_hit
                corr_center = float(corr_row["zone_center"])
                corr_magnitude = (corr_center - current_price) / current_price * 100
                corr_time_hr = (corr_ts - anchor_ts) / 3600000
                corr_zone_label = f"{corr_row['element_type']}_{corr_row['tf']}_{corr_row['direction']}"
            else:
                corr_zone_label, corr_center, corr_magnitude, corr_time_hr = "", 0.0, 0.0, 0.0
        else:
            corr_zone_label, corr_center, corr_magnitude, corr_time_hr = "", 0.0, 0.0, 0.0

        out_rows.append({
            "anchor_id": int(anchor_id),
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
            "correction_center": corr_center,
            "correction_time_hr": corr_time_hr,
            "correction_magnitude_pct": corr_magnitude,
            "main_zone_idx": int(main_idx),
        })

    # Streaming iteration
    for batch in dataset.to_batches(columns=NEEDED_COLS, batch_size=100_000):
        df_batch = batch.to_pandas()
        for _, row in df_batch.iterrows():
            aid = int(row["anchor_id"])
            if current_anchor_id is None:
                current_anchor_id = aid
            if aid != current_anchor_id:
                flush_anchor(current_anchor_id, group_buffer)
                n_processed += 1
                if n_processed % 5000 == 0:
                    elapsed = time.time() - t_start
                    rate = n_processed / elapsed
                    print(f"  [{n_processed:,}] {rate:.0f} anch/s, "
                          f"{len(out_rows):,} labels", file=sys.stderr, flush=True)
                current_anchor_id = aid
                group_buffer = [row.to_dict()]
            else:
                group_buffer.append(row.to_dict())
    # Flush last
    if group_buffer:
        flush_anchor(current_anchor_id, group_buffer)
        n_processed += 1

    # SKIP old loop (replaced by streaming above)
    if False:
      grouped = []
      for anchor_id, group in grouped:
        anchor_ts = int(group["anchor_ts"].iloc[0])
        current_price = float(group["current_price"].iloc[0])

        # First hit zone in 30d window
        first_hit, hit_idx = find_first_hit(group, ts_arr, h_arr, l_arr,
                                             anchor_ts, FORWARD_MS)
        if first_hit is None:
            n_processed += 1
            continue

        main_idx, main_row, main_ts = first_hit
        main_center = float(main_row["zone_center"])
        main_magnitude = (main_center - current_price) / current_price * 100
        main_direction = "up" if main_center > current_price else "down"
        main_time_hr = (main_ts - anchor_ts) / 3600000

        # Find correction: first hit zone in [anchor, main_goal_ts) that is NOT main_goal
        if main_time_hr > 0.25:  # >15 min — есть пространство для correction
            sub_group = group[group.index != main_idx]
            corr_hit, _ = find_first_hit(sub_group, ts_arr, h_arr, l_arr,
                                         anchor_ts, main_ts - anchor_ts)
            if corr_hit:
                corr_idx, corr_row, corr_ts = corr_hit
                corr_center = float(corr_row["zone_center"])
                corr_magnitude = (corr_center - current_price) / current_price * 100
                corr_time_hr = (corr_ts - anchor_ts) / 3600000
                corr_zone_label = f"{corr_row['element_type']}_{corr_row['tf']}_{corr_row['direction']}"
            else:
                corr_zone_label = ""
                corr_center = 0.0
                corr_magnitude = 0.0
                corr_time_hr = 0.0
        else:
            corr_zone_label = ""
            corr_center = 0.0
            corr_magnitude = 0.0
            corr_time_hr = 0.0

        out_rows.append({
            "anchor_id": anchor_id,
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
            "correction_center": corr_center,
            "correction_time_hr": corr_time_hr,
            "correction_magnitude_pct": corr_magnitude,
            "main_zone_idx": main_idx,
        })

        n_processed += 1
        if n_processed % 5000 == 0:
            elapsed = time.time() - t_start
            rate = n_processed / elapsed
            print(f"  [{n_processed:,}] {rate:.0f} anch/s, "
                  f"{len(out_rows):,} labels", file=sys.stderr, flush=True)

    df = pd.DataFrame(out_rows)
    df.to_parquet(OUT_PATH, index=False)
    print(f"\nProcessed: {n_processed:,} anchors", file=sys.stderr, flush=True)
    print(f"Labeled: {len(df):,} (skipped {n_processed - len(df):,} — no forward data)",
          file=sys.stderr, flush=True)
    if len(df) > 0:
        print(f"Direction up/down: {df['direction'].value_counts().to_dict()}",
              file=sys.stderr, flush=True)
        print(f"Magnitude: mean={df['main_goal_magnitude_pct'].abs().mean():.2f}%, "
              f"median={df['main_goal_magnitude_pct'].abs().median():.2f}%",
              file=sys.stderr, flush=True)
        print(f"Time to main_goal: mean={df['main_goal_time_hr'].mean():.1f}h, "
              f"median={df['main_goal_time_hr'].median():.1f}h",
              file=sys.stderr, flush=True)
        print(f"Top main_goal elements: {df['main_goal_element'].value_counts().to_dict()}",
              file=sys.stderr, flush=True)
        print(f"Top main_goal TFs: {df['main_goal_tf'].value_counts().to_dict()}",
              file=sys.stderr, flush=True)
    print(f"Saved: {OUT_PATH} ({OUT_PATH.stat().st_size / 1024 / 1024:.1f} MB)",
          file=sys.stderr, flush=True)
    print(f"Total time: {time.time() - t_start:.1f}s", file=sys.stderr, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2026-06-15")
    args = ap.parse_args()
    main(args.start, args.end)
