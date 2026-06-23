"""snapshot_generator_v6 — per-anchor active-zone snapshots (library-level, project-agnostic).

Универсальный snapshot: per 1h-close anchor — все активные зоны в досягаемости
цены (±20%). Никаких confluence/density aggregates — это уже baseline-уровень
конкретного проекта. snapshot только отвечает «что видит ML».

Reads events_v11.parquet (v10 + fix ошибки #19: invalid active_zone в simplified LTF).
13 SMC элементов × 8 TFs → per-1h-close anchor → sharded parallel → single parquet.

Spec:
  - Anchor cadence: 1h close-time
  - Per-row scope: **±20%** от current_price (overlap filter — диапазон досягаемости)
  - Output: hybrid (14-worker sharded build → concat → single parquet)

Per-row features (one row per active zone at anchor T):
  - anchor_ts, current_price
  - zone_id, element_type, tf, direction, role
  - zone_lo, zone_hi, last_active_lo, last_active_hi
  - level (midpoint), distance_signed_pct (from level)
  - price_in_zone (binary), dist_to_edge_pct (0 if inside)
  - age_ms, mit_pct

active_at(T) = (born_ts ≤ T) AND (retire_ts > T OR is NaN).
Для ob_vc: fill_partial с ts < born_ts (canon timing artifact) исключаются
при поиске last state.
"""
from __future__ import annotations
import sys
import csv as csvmod
import time
import pathlib
import argparse
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

SMC_LIB = pathlib.Path.home() / "smc-lib"
EVENTS_PATH = SMC_LIB / "projects/живой-рынок/data/events_v12_2020-01-01_2026-06-15.parquet"
CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
OUT_PATH = SMC_LIB / "projects/живой-рынок/data/snapshots_v7b_2020-01-01_2026-06-15.parquet"
SHARD_DIR = SMC_LIB / "projects/живой-рынок/data/snapshot_v7b_shards"

UTC = timezone.utc
ANCHOR_TF_MS = 60 * 60 * 1000               # 1h
PER_ROW_SCOPE_PCT = 10.0


# ─── Zones table ──────────────────────────────────────────

def build_zones_table(events_df):
    """Pair born + last fill state + retire per zone_id; one row per zone."""
    events_df = events_df.sort_values("ts").reset_index(drop=True)

    born = events_df[events_df["action"].isin(["born", "armed"])].set_index("zone_id")[
        ["ts", "element_type", "tf", "direction", "role", "zone_lo", "zone_hi"]
    ].rename(columns={"ts": "born_ts"})

    retire = (
        events_df[events_df["action"] == "retire"]
        .groupby("zone_id")["ts"].first().rename("retire_ts")
    )

    state = events_df[events_df["action"].isin(["born", "armed", "fill_partial"])].copy()
    state = state.merge(born.reset_index()[["zone_id", "born_ts"]],
                         on="zone_id", how="left")
    state = state[state["ts"] >= state["born_ts"]]
    last_state = (
        state.sort_values("ts").groupby("zone_id").tail(1).set_index("zone_id")
        [["active_zone_lo", "active_zone_hi"]]
        .rename(columns={"active_zone_lo": "last_active_lo",
                          "active_zone_hi": "last_active_hi"})
    )

    zones = born.join(retire, how="left").join(last_state, how="left")
    zones["last_active_lo"] = zones["last_active_lo"].fillna(zones["zone_lo"])
    zones["last_active_hi"] = zones["last_active_hi"].fillna(zones["zone_hi"])
    # Sanity: active bounds must be valid (lo ≤ hi)
    invalid = zones["last_active_lo"] > zones["last_active_hi"]
    if invalid.any():
        n_bad = invalid.sum()
        raise AssertionError(
            f"Sanity FAIL: {n_bad:,} zones have invalid active bounds (lo > hi). "
            f"events parquet has corrupted fill_partial — fix detector."
        )
    return zones.reset_index()


# ─── 1h bars (current_price lookup) ───────────────────────

def load_1h_bars(csv_path, start_ts, end_ts):
    """Aggregate 1m CSV → 1h bars (anchor_ts = bar_close, close price)."""
    bars = []
    with open(csv_path) as f:
        rd = csvmod.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0]).replace(tzinfo=UTC)
            ts = int(t.timestamp() * 1000)
            bars.append((ts, float(r[4])))
    bars.sort(key=lambda b: b[0])
    seen = set(); clean = []
    for b in bars:
        if b[0] in seen: continue
        seen.add(b[0]); clean.append(b)
    df = pd.DataFrame(clean, columns=["ts_1m", "close"])
    df["bucket"] = df["ts_1m"] - (df["ts_1m"] % ANCHOR_TF_MS)
    bars_1h = df.groupby("bucket")["close"].last().reset_index().rename(
        columns={"bucket": "open_ts"}
    )
    bars_1h["anchor_ts"] = bars_1h["open_ts"] + ANCHOR_TF_MS
    bars_1h = bars_1h[(bars_1h.anchor_ts >= start_ts) & (bars_1h.anchor_ts <= end_ts)]
    return bars_1h[["anchor_ts", "close"]].reset_index(drop=True)


# ─── Per-anchor computation ───────────────────────────────

def compute_anchor_snapshot(anchor_ts, current_price, zones_df, born_ts_arr):
    """Active zones touching ±20% band at T + per-zone geometry/age/mit features."""
    band_lo_row = current_price * (1 - PER_ROW_SCOPE_PCT / 100)
    band_hi_row = current_price * (1 + PER_ROW_SCOPE_PCT / 100)

    born_idx = np.searchsorted(born_ts_arr, anchor_ts, side="right")
    if born_idx == 0:
        return None
    candidates = zones_df.iloc[:born_idx]
    retire_ts = candidates["retire_ts"].values
    alive = candidates[np.isnan(retire_ts) | (retire_ts > anchor_ts)]
    if len(alive) == 0:
        return None

    overlap_row = (alive["zone_hi"] >= band_lo_row) & (alive["zone_lo"] <= band_hi_row)
    rows = alive[overlap_row].copy()
    if len(rows) == 0:
        return None

    rows["level"] = (rows["zone_lo"] + rows["zone_hi"]) / 2.0
    rows["distance_signed_pct"] = (current_price - rows["level"]) / current_price * 100.0
    rows["price_in_zone"] = (rows["zone_lo"] <= current_price) & (current_price <= rows["zone_hi"])
    dist_edge = np.maximum(0.0, np.maximum(
        rows["zone_lo"].values - current_price,
        current_price - rows["zone_hi"].values
    ))
    rows["dist_to_edge_pct"] = dist_edge / current_price * 100.0
    rows["age_ms"] = anchor_ts - rows["born_ts"]
    zone_w = (rows["zone_hi"] - rows["zone_lo"]).replace(0, np.nan)
    cur_w = rows["last_active_hi"] - rows["last_active_lo"]
    rows["mit_pct"] = (1.0 - cur_w / zone_w).clip(0, 1).fillna(0)

    rows["anchor_ts"] = anchor_ts
    rows["current_price"] = current_price
    return rows


def process_anchor_chunk(chunk_idx, anchor_chunk, price_chunk, zones_df, born_ts_arr):
    parts = []
    for anchor_ts, cur_price in zip(anchor_chunk, price_chunk):
        snap = compute_anchor_snapshot(int(anchor_ts), float(cur_price),
                                        zones_df, born_ts_arr)
        if snap is not None and len(snap) > 0:
            parts.append(snap)
    if not parts:
        return None, 0
    df = pd.concat(parts, ignore_index=True)
    shard_path = SHARD_DIR / f"shard_{chunk_idx:05d}.parquet"
    df.to_parquet(shard_path, compression="zstd", compression_level=9)
    return shard_path, len(df)


# ─── Main ─────────────────────────────────────────────────

def main(start, end, n_workers=14, chunk_size=500):
    start_ts = int(datetime.fromisoformat(start).replace(tzinfo=UTC).timestamp() * 1000)
    end_ts = int(datetime.fromisoformat(end).replace(tzinfo=UTC).timestamp() * 1000)

    print(f"Loading events from {EVENTS_PATH.name}...", file=sys.stderr, flush=True)
    events_df = pd.read_parquet(EVENTS_PATH)
    print(f"  {len(events_df):,} events", file=sys.stderr)

    print("Building zones table...", file=sys.stderr, flush=True)
    t0 = time.time()
    zones_df = build_zones_table(events_df)
    del events_df
    print(f"  {len(zones_df):,} zones in {time.time() - t0:.0f}s", file=sys.stderr)

    print("Loading 1h bars...", file=sys.stderr, flush=True)
    bars_1h = load_1h_bars(CSV_PATH, start_ts, end_ts)
    print(f"  {len(bars_1h):,} 1h anchors", file=sys.stderr)

    zones_df = zones_df.sort_values("born_ts").reset_index(drop=True)
    born_ts_arr = zones_df["born_ts"].values

    anchor_ts_list = bars_1h["anchor_ts"].values
    cur_prices = bars_1h["close"].values
    chunks = [
        (i // chunk_size, anchor_ts_list[i:i + chunk_size], cur_prices[i:i + chunk_size])
        for i in range(0, len(anchor_ts_list), chunk_size)
    ]
    print(f"\nProcessing {len(anchor_ts_list):,} anchors in {len(chunks)} chunks of ≤{chunk_size}...",
          file=sys.stderr, flush=True)

    SHARD_DIR.mkdir(exist_ok=True, parents=True)
    for p in SHARD_DIR.glob("shard_*.parquet"):
        p.unlink()

    t1 = time.time()
    results = Parallel(n_jobs=n_workers, backend="loky", verbose=5)(
        delayed(process_anchor_chunk)(idx, chunk, cps, zones_df, born_ts_arr)
        for idx, chunk, cps in chunks
    )
    total_rows = sum(n for _, n in results)
    print(f"Shard build done in {time.time() - t1:.0f}s, {total_rows:,} rows", file=sys.stderr)

    print("Concatenating shards...", file=sys.stderr, flush=True)
    t2 = time.time()
    dfs = [pd.read_parquet(p) for p, n in results if p is not None]
    df = pd.concat(dfs, ignore_index=True).sort_values(["anchor_ts", "tf", "element_type"])
    df.to_parquet(OUT_PATH, compression="zstd", compression_level=9, index=False)
    print(f"Concat+save done in {time.time() - t2:.0f}s", file=sys.stderr)
    print(f"\nSaved {len(df):,} rows → {OUT_PATH}", file=sys.stderr)
    per_anchor = df.groupby("anchor_ts").size()
    print(f"Per-anchor zones distribution: "
          f"min={per_anchor.min()} median={int(per_anchor.median())} "
          f"mean={per_anchor.mean():.0f} max={per_anchor.max()}", file=sys.stderr)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2026-06-15")
    ap.add_argument("--workers", type=int, default=14)
    ap.add_argument("--chunk-size", type=int, default=500)
    a = ap.parse_args()
    main(a.start, a.end, a.workers, a.chunk_size)
