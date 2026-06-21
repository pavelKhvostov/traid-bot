"""Parallel snapshot_generator launcher: разбивает 2020-2026 на год-шарды,
запускает N workers через multiprocessing, потом merge'ит chunks в финальный parquet.

Каждый worker делает warm-up replay (events до начала своего шарда), затем
считает features только для anchors в своём шарде. Wasteful warm-up
(~10 sec на worker) компенсируется параллельностью на 14-20 cores.

Usage: python3 parallel_runner.py --workers 13 (PC1) / 19 (PC2)
"""
from __future__ import annotations
import sys
import os
import time
import argparse
import pathlib
import subprocess
import multiprocessing as mp
from datetime import datetime, timezone, timedelta

import pandas as pd

SMC_LIB = pathlib.Path.home() / "smc-lib"
SCRIPT_DIR = SMC_LIB / "projects/живой-рынок/состояния"
DATA_DIR = SMC_LIB / "projects/живой-рынок/data"
SCRIPT_PATH = SCRIPT_DIR / "snapshot_generator.py"
OUT_PATH = DATA_DIR / "snapshots_2020-01-01_2026-06-15.parquet"


def split_date_range(start_dt: datetime, end_dt: datetime, n_shards: int) -> list[tuple[str, str]]:
    """Split [start, end] in N равных по времени шардов."""
    total_seconds = (end_dt - start_dt).total_seconds()
    shard_seconds = total_seconds / n_shards
    shards = []
    for i in range(n_shards):
        s = start_dt + timedelta(seconds=i * shard_seconds)
        e = start_dt + timedelta(seconds=(i + 1) * shard_seconds) if i < n_shards - 1 else end_dt
        shards.append((s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d")))
    return shards


def run_shard(args):
    """Run single shard via subprocess (изоляция памяти)."""
    shard_id, start_date, end_date, log_dir = args
    log_path = pathlib.Path(log_dir) / f"shard_{shard_id:02d}.log"
    suffix = f"{shard_id:02d}"
    cmd = [
        "python3", str(SCRIPT_PATH),
        "--start", start_date,
        "--end", end_date,
        "--shard-suffix", suffix,
    ]
    t0 = time.time()
    with log_path.open("w") as f:
        result = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT)
    dt = time.time() - t0
    return shard_id, result.returncode, dt, log_path


def main(n_workers: int, start_date: str, end_date: str, log_dir: str):
    log_dir_p = pathlib.Path(log_dir)
    log_dir_p.mkdir(parents=True, exist_ok=True)

    start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)

    shards = split_date_range(start_dt, end_dt, n_workers)
    print(f"Splitting into {n_workers} shards:", file=sys.stderr, flush=True)
    for i, (s, e) in enumerate(shards):
        print(f"  shard {i:02d}: {s} → {e}", file=sys.stderr, flush=True)

    tasks = [(i, s, e, str(log_dir_p)) for i, (s, e) in enumerate(shards)]

    t_start = time.time()
    with mp.Pool(n_workers) as pool:
        results = pool.map(run_shard, tasks)

    print(f"\nAll shards finished in {time.time() - t_start:.1f}s", file=sys.stderr, flush=True)
    for shard_id, returncode, dt, log in results:
        status = "OK" if returncode == 0 else f"FAIL ({returncode})"
        print(f"  shard {shard_id:02d}: {status} in {dt:.1f}s, log={log.name}",
              file=sys.stderr, flush=True)

    # Merge chunks from all shard dirs
    print(f"\nMerging chunks from all shards...", file=sys.stderr, flush=True)
    all_chunks = []
    for i in range(n_workers):
        chunk_dir = DATA_DIR / f"snapshot_chunks_{i:02d}"
        if not chunk_dir.exists():
            continue
        files = sorted(chunk_dir.glob("chunk_*.parquet"))
        all_chunks.extend(files)
    print(f"  {len(all_chunks)} chunk files found", file=sys.stderr, flush=True)

    dfs = []
    for f in all_chunks:
        dfs.append(pd.read_parquet(f))
    df = pd.concat(dfs, ignore_index=True)

    # CRITICAL FIX 2026-06-15: каждый shard стартовал anchor_id с 0 → коллизии после concat.
    # Переприсваиваем anchor_id уникально на base of anchor_ts (ordered by time).
    if "anchor_ts" in df.columns:
        ts_col = "anchor_ts"
    elif "ts" in df.columns:
        ts_col = "ts"
    else:
        ts_col = None
    if ts_col is not None:
        df = df.sort_values(ts_col).reset_index(drop=True)
        # Map unique anchor_ts → new anchor_id (sequential)
        unique_ts = df[ts_col].drop_duplicates().reset_index(drop=True)
        ts_to_aid = {t: i for i, t in enumerate(unique_ts.values)}
        df["anchor_id"] = df[ts_col].map(ts_to_aid).astype("int64")
        print(f"  anchor_id reassigned: {len(unique_ts):,} unique anchors → 0..{len(unique_ts)-1}",
              file=sys.stderr, flush=True)
    df.to_parquet(OUT_PATH, index=False)
    size_mb = OUT_PATH.stat().st_size / 1024 / 1024
    print(f"Saved: {OUT_PATH} ({size_mb:.1f} MB, {len(df):,} rows)",
          file=sys.stderr, flush=True)

    # Cleanup chunk dirs
    import shutil
    for i in range(n_workers):
        chunk_dir = DATA_DIR / f"snapshot_chunks_{i:02d}"
        if chunk_dir.exists():
            shutil.rmtree(chunk_dir)

    print(f"\nTotal pipeline time: {time.time() - t_start:.1f}s", file=sys.stderr, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=mp.cpu_count() - 1,
                    help="Parallel workers (default: CPU - 1)")
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2026-06-15")
    ap.add_argument("--log-dir", default="/tmp/snapshot_shards")
    args = ap.parse_args()
    main(args.workers, args.start, args.end, args.log_dir)
