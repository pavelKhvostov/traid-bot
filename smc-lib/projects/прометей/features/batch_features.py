"""Прометей Phase 2 — batch feature extraction.

Walks a batch directory of snapshot JSONs, computes features per snapshot,
writes a single parquet file (one row per cutoff).

If snapshot lacks current_price field (early snapshots before Phase 2.0),
patches it from 1m CSV via timestamp lookup.

Usage:
    python3 batch_features.py BATCH_DIR [--out PATH]
    e.g. python3 batch_features.py snapshots/batch_2026-06-08_2026-06-14
"""
from __future__ import annotations

import sys
import json
import time
import bisect
import pathlib
import argparse

import pandas as pd

SMC_LIB = pathlib.Path.home() / "smc-lib"
sys.path.insert(0, str(SMC_LIB))

from projects.прометей.features.build_features import extract_features  # noqa: E402
from projects.прометей.detectors.snapshot_builder import load_1m_csv  # noqa: E402


def patch_prices_if_missing(snapshots: list[dict], bars_1m: list, bars_1m_ts: list[int]) -> None:
    """In-place add current_price to snapshots missing it (legacy)."""
    n_patched = 0
    for snap in snapshots:
        if snap.get("current_price") is not None:
            continue
        t0_ms = snap["t0"] * 1000  # snap stores t0 in seconds
        idx = bisect.bisect_right(bars_1m_ts, t0_ms - 60_000) - 1
        if idx >= 0:
            snap["current_price"] = bars_1m[idx][4]
            n_patched += 1
    if n_patched:
        print(f"  Patched current_price for {n_patched} snapshots", file=sys.stderr, flush=True)


def main(batch_dir: pathlib.Path, out_path: pathlib.Path):
    files = sorted(batch_dir.glob("*.json"))
    if not files:
        print(f"No snapshots in {batch_dir}", file=sys.stderr)
        sys.exit(1)
    print(f"Loading {len(files)} snapshots from {batch_dir}", file=sys.stderr, flush=True)
    t0 = time.time()
    snapshots = [json.loads(f.read_text()) for f in files]
    print(f"  loaded in {time.time() - t0:.1f}s", file=sys.stderr, flush=True)

    # Patch missing prices if needed
    missing = sum(1 for s in snapshots if s.get("current_price") is None)
    if missing:
        print(f"  {missing}/{len(snapshots)} need price patch; loading 1m CSV...",
              file=sys.stderr, flush=True)
        bars_1m = load_1m_csv()
        bars_1m_ts = [b[0] for b in bars_1m]
        patch_prices_if_missing(snapshots, bars_1m, bars_1m_ts)

    # Extract features
    print(f"Extracting features...", file=sys.stderr, flush=True)
    t1 = time.time()
    rows = []
    for snap in snapshots:
        rows.append(extract_features(snap))
    df = pd.DataFrame(rows)
    print(f"  {len(df)} rows × {len(df.columns)} cols in {time.time() - t1:.1f}s",
          file=sys.stderr, flush=True)

    # Sanity checks
    n_missing_price = df["current_price"].eq(0).sum()
    if n_missing_price:
        print(f"  ⚠ {n_missing_price} rows have current_price=0",
              file=sys.stderr, flush=True)
    n_nans = df.isna().sum().sum()
    if n_nans:
        print(f"  ⚠ {n_nans} NaN cells (will fill with 0)", file=sys.stderr, flush=True)
        df = df.fillna(0)

    # Save
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    print(
        f"Saved: {out_path}\n"
        f"  shape: {df.shape}\n"
        f"  date range: {df['t0_iso_msk'].iloc[0]} → {df['t0_iso_msk'].iloc[-1]}\n"
        f"  price range: ${df['current_price'].min():,.0f} → ${df['current_price'].max():,.0f}\n"
        f"  size: {out_path.stat().st_size / 1024:.1f} KB",
        file=sys.stderr,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("batch_dir", help="snapshot batch directory")
    ap.add_argument("--out", default=None, help="output parquet path")
    args = ap.parse_args()
    batch_dir = pathlib.Path(args.batch_dir).resolve()
    if args.out:
        out = pathlib.Path(args.out)
    else:
        out = SMC_LIB / "projects/прометей/features" / f"{batch_dir.name}.parquet"
    main(batch_dir, out)
