"""Phase 2 — Per-anchor state snapshot generator.

Streaming через 15-min cadence на 6y. Per anchor:
  - Active zones (всех 12 элементов × 8 TF которые еще actionable)
  - Per-zone features (distance, age, mit_count, role)
  - Cross-TF intersection features (overlap, cluster, internal/external)
  - Past context (top-10 significant events за 72h)
  - Current price из 1m данных

Input:  events_2020-01-01_2026-06-15.parquet (1.36M events)
        BTCUSDT_1m_vic_vadim.csv (price lookup)
Output: snapshots.parquet (streaming, ~225K anchors × variable zones)
"""
from __future__ import annotations

import sys
import csv
import time
import bisect
import pathlib
import argparse
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd

SMC_LIB = pathlib.Path.home() / "smc-lib"
sys.path.insert(0, str(SMC_LIB))

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
EVENTS_PATH = SMC_LIB / "projects/живой-рынок/data/events_2020-01-01_2026-06-15.parquet"
OUT_PATH = SMC_LIB / "projects/живой-рынок/data/snapshots_2020-01-01_2026-06-15.parquet"

MS = 60_000
ANCHOR_MS = 0
UTC = timezone.utc

# 15-min cadence
CADENCE_MS = 15 * MS
PAST_WINDOW_MS = 72 * 3600 * 1000  # 72h
TOP_N_PAST_EVENTS = 10

# NO age cap — zone живёт до canon consumption (retire event).
# Если zone $30K из 2023 не была wick-filled / swept — она ОСТАЁТСЯ active в 2026.
# Performance — через PRICE RANGE FILTER per anchor (±$15K от current).
# Global state хранит ВСЕ active zones, per-anchor рассматривает только те в range.
PRICE_RANGE_USD = 15000.0

# Per-element TF weight (для force calculation — empirical TF priority)
TF_WEIGHT = {"15m": 1, "30m": 2, "1h": 3, "2h": 4, "4h": 6, "6h": 8, "12h": 12, "1D": 18}
# Per-action retirement: events that REMOVE zone from active set
RETIRING_ACTIONS = {"sweep", "fill_full", "break", "liq_first_touch"}
# Mit_partial increments
PARTIAL_ACTIONS = {"fill_partial"}
# Output 4h+ TFs (zone is candidate для main_goal output)
OUTPUT_TFS = {"4h", "6h", "12h", "1D"}


def load_1m_for_lookup():
    """Load 1m bars → array of (ts_ms, close) для price lookup."""
    print(f"Loading 1m for price lookup...", file=sys.stderr, flush=True)
    ts_arr = []
    close_arr = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f)
        next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0]).replace(tzinfo=UTC)
            ts_arr.append(int(t.timestamp() * 1000))
            close_arr.append(float(r[4]))
    return np.array(ts_arr, dtype=np.int64), np.array(close_arr, dtype=np.float64)


def lookup_price(ts_ms, ts_arr, close_arr):
    """Last 1m close at-or-before ts_ms (close of bar ending at ts_ms)."""
    idx = np.searchsorted(ts_arr, ts_ms - MS, side="right") - 1
    if idx < 0:
        return 0.0
    return float(close_arr[idx])


def make_zone_id(elem, tf, direction, level, born_ts):
    """Stable unique zone identifier for tracking active state."""
    return (elem, tf, direction, round(level, 2), born_ts)


def iter_anchors(start_ts, end_ts):
    """Yield anchor timestamps at 15-min cadence (0 UTC anchor)."""
    aligned = start_ts - (start_ts % CADENCE_MS)
    if aligned < start_ts:
        aligned += CADENCE_MS
    t = aligned
    while t <= end_ts:
        yield t
        t += CADENCE_MS


def compute_past_context(events_df, anchor_ts, current_price):
    """Top-N significant events за 72h до anchor.

    Significant = HTF (12h+) ИЛИ magnitude_pct ≥ 0.5%.
    Returns dict of features.
    """
    window_start = anchor_ts - PAST_WINDOW_MS
    mask = (events_df["ts"] >= window_start) & (events_df["ts"] <= anchor_ts)
    window = events_df[mask]
    if len(window) == 0:
        return {f"past_{i}_present": 0 for i in range(TOP_N_PAST_EVENTS)}

    htf_set = {"12h", "1D"}
    sig_mask = (window["tf"].isin(htf_set)) | (window["magnitude_pct"].abs() >= 0.5)
    significant = window[sig_mask].sort_values("ts").tail(TOP_N_PAST_EVENTS)

    out = {}
    for i in range(TOP_N_PAST_EVENTS):
        if i < len(significant):
            row = significant.iloc[i]
            out[f"past_{i}_present"] = 1
            out[f"past_{i}_tf_weight"] = TF_WEIGHT.get(row["tf"], 0)
            out[f"past_{i}_time_delta_hr"] = (anchor_ts - row["ts"]) / 3600000
            out[f"past_{i}_magnitude_pct"] = float(row["magnitude_pct"])
            # action one-hot for top 4 actions
            for a in ["sweep", "fill_full", "born", "break"]:
                out[f"past_{i}_action_{a}"] = 1 if row["action"] == a else 0
        else:
            out[f"past_{i}_present"] = 0
            out[f"past_{i}_tf_weight"] = 0
            out[f"past_{i}_time_delta_hr"] = 0
            out[f"past_{i}_magnitude_pct"] = 0
            for a in ["sweep", "fill_full", "born", "break"]:
                out[f"past_{i}_action_{a}"] = 0
    return out


def compute_zone_features(active_zones, current_price, anchor_ts):
    """VECTORIZED per-anchor zone features (NumPy).

    Хот-loop переписан на numpy: per-anchor compute = O(K + N) numpy ops
    вместо O(K×N) Python loop через bisect.
    """
    if not active_zones or current_price <= 0:
        return []

    # active_zones может быть dict (внутр.state) или list (caller передаёт values())
    if isinstance(active_zones, dict):
        zones = list(active_zones.values())
    else:
        zones = list(active_zones)
    n = len(zones)
    zlo_arr = np.empty(n, dtype=np.float64)
    zhi_arr = np.empty(n, dtype=np.float64)
    born_arr = np.empty(n, dtype=np.int64)
    mit_arr = np.empty(n, dtype=np.int32)
    elem_list = [None] * n
    tf_list = [None] * n
    dir_list = [None] * n
    role_list = [None] * n
    is_htf = np.zeros(n, dtype=bool)
    tf_weights = np.zeros(n, dtype=np.float32)
    is_long_arr = np.zeros(n, dtype=bool)
    for i, z in enumerate(zones):
        zlo_arr[i] = z["zone_lo"]
        zhi_arr[i] = z["zone_hi"]
        born_arr[i] = z["born_ts"]
        mit_arr[i] = z.get("mit_count", 0)
        elem_list[i] = z["element_type"]
        tf_list[i] = z["tf"]
        dir_list[i] = z["direction"]
        role_list[i] = z["role"]
        is_htf[i] = z["tf"] in OUTPUT_TFS
        tf_weights[i] = TF_WEIGHT.get(z["tf"], 0)
        is_long_arr[i] = z["direction"] in ("long", "low")

    # Price range filter (interval overlap)
    range_lo = current_price - PRICE_RANGE_USD
    range_hi = current_price + PRICE_RANGE_USD
    in_range_mask = (np.maximum(zlo_arr, range_lo) <= np.minimum(zhi_arr, range_hi))

    # Candidates: 4h+ AND in range
    candidate_mask = in_range_mask & is_htf
    if not candidate_mask.any():
        return []
    # Context: LTF (not 4h+) in range
    context_mask = in_range_mask & ~is_htf

    # Aggregate LTF context (vectorized)
    ctx_lo = zlo_arr[context_mask]
    ctx_hi = zhi_arr[context_mask]
    ctx_center = (ctx_lo + ctx_hi) * 0.5
    n_ltf_above = int((ctx_center > current_price).sum())
    n_ltf_below = int((ctx_center <= current_price).sum())
    n_ltf_within_2pct = int(
        (np.abs(ctx_center - current_price) / current_price * 100 <= 2).sum()
    )

    # Per-candidate features (vectorized)
    c_idx = np.flatnonzero(candidate_mask)
    c_lo = zlo_arr[c_idx]
    c_hi = zhi_arr[c_idx]
    c_center = (c_lo + c_hi) * 0.5
    c_dist_pct_signed = (c_center - current_price) / current_price * 100
    c_width_pct = (c_hi - c_lo) / current_price * 100 if current_price > 0 else np.zeros_like(c_lo)
    c_age_hr = (anchor_ts - born_arr[c_idx]) / 3600000.0
    c_tf_weight = tf_weights[c_idx]
    c_is_inside = (c_lo <= current_price) & (current_price <= c_hi)
    c_is_above = (~c_is_inside) & (c_center > current_price)
    c_is_below = (~c_is_inside) & (c_center <= current_price)
    c_is_long = is_long_arr[c_idx]

    # Vectorized overlap_count и overlap_htf_count.
    # Для каждого candidate i считаем сколько ALL active zones (включая context, не self)
    # пересекаются с [c_lo[i], c_hi[i]].
    # Overlap: zone_lo <= c_hi AND zone_hi >= c_lo (interval intersection).
    # Self-exclusion: тот же (zone_lo, zone_hi) — drop counter -1.
    # Используем broadcasting на (K, N) matrix, K=candidates, N=all_zones.
    # K obычно <100, N до 10K → 1M ops, vectorized 10-50ms.
    in_range_idx = np.flatnonzero(in_range_mask)
    all_lo = zlo_arr[in_range_idx]
    all_hi = zhi_arr[in_range_idx]
    all_is_htf = is_htf[in_range_idx]
    # broadcasting: c_lo[:, None] vs all_hi[None, :]
    overlap_matrix = (c_lo[:, None] <= all_hi[None, :]) & (c_hi[:, None] >= all_lo[None, :])
    # Self exclusion: zone with exact same (lo, hi) is self (approximation; same zid in dict)
    self_matrix = (c_lo[:, None] == all_lo[None, :]) & (c_hi[:, None] == all_hi[None, :])
    overlap_no_self = overlap_matrix & ~self_matrix
    overlap_count_arr = overlap_no_self.sum(axis=1).astype(int)
    overlap_htf_matrix = overlap_no_self & all_is_htf[None, :]
    overlap_htf_count_arr = overlap_htf_matrix.sum(axis=1).astype(int)

    # Build result rows
    rows = []
    for k, i in enumerate(c_idx):
        rows.append({
            "anchor_ts": anchor_ts,
            "current_price": current_price,
            "element_type": elem_list[i],
            "tf": tf_list[i],
            "direction": dir_list[i],
            "role": role_list[i],
            "zone_lo": float(c_lo[k]),
            "zone_hi": float(c_hi[k]),
            "zone_center": float(c_center[k]),
            "dist_pct_signed": float(c_dist_pct_signed[k]),
            "dist_pct_abs": float(abs(c_dist_pct_signed[k])),
            "width_pct": float(c_width_pct[k]),
            "age_hr": float(c_age_hr[k]),
            "mit_count": int(mit_arr[i]),
            "tf_weight": float(c_tf_weight[k]),
            "is_above": int(c_is_above[k]),
            "is_below": int(c_is_below[k]),
            "is_inside": int(c_is_inside[k]),
            "is_long": int(c_is_long[k]),
            "ltf_count_above": n_ltf_above,
            "ltf_count_below": n_ltf_below,
            "ltf_count_within_2pct": n_ltf_within_2pct,
            "overlap_count": int(overlap_count_arr[k]),
            "overlap_htf_count": int(overlap_htf_count_arr[k]),
        })
    return rows


def main(start_date: str = "2020-01-01", end_date: str = "2026-06-15",
         max_anchors: int = 0, shard_suffix: str = ""):
    """Run snapshot generator. shard_suffix isolates output to per-worker chunks."""
    print(f"Loading events from {EVENTS_PATH.name}...", file=sys.stderr, flush=True)
    events_df = pd.read_parquet(EVENTS_PATH)
    events_df = events_df.sort_values("ts").reset_index(drop=True)
    print(f"  {len(events_df):,} events loaded", file=sys.stderr, flush=True)

    ts_arr, close_arr = load_1m_for_lookup()
    print(f"  {len(ts_arr):,} 1m bars loaded", file=sys.stderr, flush=True)

    start_ts = int(datetime.fromisoformat(start_date).replace(tzinfo=UTC).timestamp() * 1000)
    end_ts = int(datetime.fromisoformat(end_date).replace(tzinfo=UTC).timestamp() * 1000)

    # ─── State tracking: active zones dict ──────────
    # key = zone_id, val = dict (element, tf, direction, role, level, born_ts, ...)
    active_zones: dict = {}

    # Index events by ts for chunked replay
    events_ts_arr = events_df["ts"].values
    snapshot_idx = 0
    last_event_idx = 0
    t_start = time.time()

    # Streaming write: chunked parquet writes (избегаем OOM на больших batch)
    import pyarrow as pa
    import pyarrow.parquet as pq
    CHUNK_SIZE = 500   # anchors per chunk (smaller to avoid OOM при росте active_zones)
    chunk_dir_name = f"snapshot_chunks_{shard_suffix}" if shard_suffix else "snapshot_chunks"
    chunk_dir = OUT_PATH.parent / chunk_dir_name
    chunk_dir.mkdir(exist_ok=True)
    chunk_buffer = []
    chunk_idx = 0
    total_rows_written = 0

    anchor_count = 0
    for anchor_ts in iter_anchors(start_ts, end_ts):
        if max_anchors and anchor_count >= max_anchors:
            break

        # Replay events up to anchor_ts
        while last_event_idx < len(events_df) and events_ts_arr[last_event_idx] <= anchor_ts:
            ev = events_df.iloc[last_event_idx]
            elem = ev["element_type"]
            tf = ev["tf"]
            direction = ev["direction"]
            action = ev["action"]
            level = float(ev["level"])

            if action in ("born", "armed"):  # "armed" = born для breaker/MB
                zid = make_zone_id(elem, tf, direction, level, int(ev["ts"]))
                # Canon 2026-06-15: event payload содержит REAL zone_lo/zone_hi
                # (для точечных элементов fractal/marubozu/choch_bos: zone_lo == zone_hi == level)
                z_lo = float(ev["zone_lo"]) if "zone_lo" in ev and ev["zone_lo"] is not None else level
                z_hi = float(ev["zone_hi"]) if "zone_hi" in ev and ev["zone_hi"] is not None else level
                active_zones[zid] = {
                    "element_type": elem,
                    "tf": tf,
                    "direction": direction,
                    "role": ev["role"],
                    "level": level,
                    "zone_lo": z_lo,
                    "zone_hi": z_hi,
                    "born_ts": int(ev["ts"]),
                    "mit_count": 0,
                }
            elif action in RETIRING_ACTIONS:
                # Canon 2026-06-15: retire события содержат zone_lo/zone_hi (exact match).
                # Если есть zone_lo/zone_hi — match exact (надёжно).
                # Fallback: level ± 0.1% (для старых stale events без zone bounds).
                ev_zlo = float(ev["zone_lo"]) if ("zone_lo" in ev and ev["zone_lo"] is not None) else None
                ev_zhi = float(ev["zone_hi"]) if ("zone_hi" in ev and ev["zone_hi"] is not None) else None
                if ev_zlo is not None and ev_zhi is not None:
                    to_remove = [
                        zid for zid, z in active_zones.items()
                        if z["element_type"] == elem and z["tf"] == tf
                        and z["direction"] == direction
                        and abs(z["zone_lo"] - ev_zlo) < 0.01  # exact bounds
                        and abs(z["zone_hi"] - ev_zhi) < 0.01
                    ]
                else:
                    to_remove = [
                        zid for zid, z in active_zones.items()
                        if z["element_type"] == elem and z["tf"] == tf
                        and z["direction"] == direction
                        and abs(z["level"] - level) < level * 0.001
                    ]
                for zid in to_remove:
                    del active_zones[zid]
            elif action in PARTIAL_ACTIONS:
                # Match by zone bounds (canon 2026-06-15) или fallback level±0.1%
                ev_zlo = float(ev["zone_lo"]) if ("zone_lo" in ev and ev["zone_lo"] is not None) else None
                ev_zhi = float(ev["zone_hi"]) if ("zone_hi" in ev and ev["zone_hi"] is not None) else None
                for zid, z in active_zones.items():
                    if not (z["element_type"] == elem and z["tf"] == tf
                            and z["direction"] == direction):
                        continue
                    if ev_zlo is not None and ev_zhi is not None:
                        if abs(z["zone_lo"] - ev_zlo) < 0.01 and abs(z["zone_hi"] - ev_zhi) < 0.01:
                            z["mit_count"] = z.get("mit_count", 0) + 1
                    elif abs(z["level"] - level) < level * 0.001:
                        z["mit_count"] = z.get("mit_count", 0) + 1
            last_event_idx += 1

        # NO age cap. Zones live until canon retirement event.

        # Now snapshot at anchor_ts
        current_price = lookup_price(anchor_ts, ts_arr, close_arr)
        if current_price <= 0:
            anchor_count += 1
            continue

        active_list = list(active_zones.values())
        if not active_list:
            anchor_count += 1
            continue

        zone_rows = compute_zone_features(active_list, current_price, anchor_ts)
        past_ctx = compute_past_context(events_df, anchor_ts, current_price)

        # Attach past context to each zone row (anchor-level features)
        for row in zone_rows:
            row.update(past_ctx)
            row["anchor_id"] = snapshot_idx
        chunk_buffer.extend(zone_rows)
        snapshot_idx += 1
        anchor_count += 1

        # Flush chunk every CHUNK_SIZE anchors
        if snapshot_idx % CHUNK_SIZE == 0 and chunk_buffer:
            chunk_path = chunk_dir / f"chunk_{chunk_idx:04d}.parquet"
            pd.DataFrame(chunk_buffer).to_parquet(chunk_path, index=False)
            total_rows_written += len(chunk_buffer)
            chunk_buffer = []
            chunk_idx += 1

        if anchor_count % 5000 == 0:
            elapsed = time.time() - t_start
            rate = anchor_count / elapsed
            print(f"  [{anchor_count:,}] {rate:.0f} anch/s, "
                  f"{total_rows_written + len(chunk_buffer):,} rows written, "
                  f"{len(active_zones):,} active zones, "
                  f"{chunk_idx} chunks",
                  file=sys.stderr, flush=True)

    # Flush remaining buffer
    if chunk_buffer:
        chunk_path = chunk_dir / f"chunk_{chunk_idx:04d}.parquet"
        pd.DataFrame(chunk_buffer).to_parquet(chunk_path, index=False)
        total_rows_written += len(chunk_buffer)
        chunk_idx += 1
        chunk_buffer = []

    print(f"\nTotal anchors: {snapshot_idx:,}", file=sys.stderr, flush=True)
    print(f"Total zone-rows: {total_rows_written:,}", file=sys.stderr, flush=True)
    print(f"Chunks: {chunk_idx}", file=sys.stderr, flush=True)

    # If running as shard — DON'T merge or cleanup. Coordinator does that.
    if shard_suffix:
        print(f"Shard {shard_suffix} done. {chunk_idx} chunks in {chunk_dir}",
              file=sys.stderr, flush=True)
        print(f"Total time: {time.time() - t_start:.1f}s", file=sys.stderr, flush=True)
        return

    # Stream-merge all chunks (incremental, bounded RAM ~50MB per chunk).
    # Старый pd.concat загружал ВСЕ chunks в память → OOM на 292M rows × 30 cols.
    print(f"Stream-merging {chunk_idx} chunks...", file=sys.stderr, flush=True)
    import pyarrow as pa
    import pyarrow.parquet as pq
    chunk_files = sorted(chunk_dir.glob("chunk_*.parquet"))
    writer = None
    total_rows_merged = 0
    for i, f in enumerate(chunk_files):
        table = pq.read_table(f)
        if writer is None:
            writer = pq.ParquetWriter(str(OUT_PATH), table.schema, compression="snappy")
        writer.write_table(table)
        total_rows_merged += len(table)
        if (i + 1) % 50 == 0:
            print(f"  merged [{i+1}/{len(chunk_files)}] {total_rows_merged:,} rows",
                  file=sys.stderr, flush=True)
    if writer is not None:
        writer.close()
    print(f"Saved: {OUT_PATH} ({OUT_PATH.stat().st_size / 1024 / 1024:.1f} MB, "
          f"{total_rows_merged:,} rows)", file=sys.stderr, flush=True)
    # Cleanup chunks
    for f in chunk_files:
        f.unlink()
    chunk_dir.rmdir()
    print(f"Total time: {time.time() - t_start:.1f}s", file=sys.stderr, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2026-06-15")
    ap.add_argument("--max_anchors", type=int, default=0,
                    help="0 = no limit, иначе ограничить для smoke test")
    ap.add_argument("--shard-suffix", type=str, default="",
                    help="Если задан — output идёт в snapshot_chunks_<suffix>, без merge")
    args = ap.parse_args()
    main(args.start, args.end, args.max_anchors, args.shard_suffix)
