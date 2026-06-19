"""Orchestrator: build the full v1.5 feature dataset.

Pipeline:
  1. Load ob_vc events from BTC + ETH 24-types parquets
  2. Build per-channel features (funding, OI, DVOL, cross-asset, macro)
  3. Build HMA features (heavy: ~700 per event)
  4. Concatenate -> single parquet

Output: ~/smc-lib/projects/ob-vc/ml_v15/feature_dataset_v1.parquet
"""
from __future__ import annotations
import pathlib
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from feature_channels import build_channel_features
from feature_hma import build_hma_features


REPO = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc")
OUT = pathlib.Path(__file__).parent / "feature_dataset_v1.parquet"

REGIME_CUT_MS = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


def load_events() -> pd.DataFrame:
    parts = []
    for sym in ("BTCUSDT", "ETHUSDT"):
        df = pd.read_parquet(REPO / "data" / f"{sym}_2h_24types.parquet")
        df["asset"] = sym[:3]
        parts.append(df)
    df = pd.concat(parts, ignore_index=True)
    df["event_id"] = df["asset"] + "_" + df.index.astype(str).str.zfill(6)
    # decisive label
    df["label"] = df["outcome"].map({"win": 1, "loss": 0}).astype("Int64")
    df["decisive"] = df["outcome"].isin(["win", "loss"])
    df["regime"] = np.where(df["born_ms"] < REGIME_CUT_MS, "pre_2023", "post_2023")
    return df


def main():
    t0 = time.time()
    print("=" * 70)
    print("Build v1.5 feature dataset")
    print("=" * 70)

    print("\n[1/3] Loading ob_vc events...")
    events = load_events()
    print(f"  total events: {len(events):,}")
    print(f"  by asset: {events.asset.value_counts().to_dict()}")
    print(f"  decisive: {events.decisive.sum():,} ({events.decisive.mean()*100:.1f}%)")
    print(f"  win rate (decisive): {events.loc[events.decisive,'label'].mean()*100:.1f}%")

    t1 = time.time()
    print(f"\n[2/3] Building channel features (funding/OI/DVOL/cross/macro)...")
    ch_feat = build_channel_features(events)
    print(f"  channel features: {ch_feat.shape[1]}  ({time.time()-t1:.1f}s)")

    t2 = time.time()
    print(f"\n[3/3] Building HMA features (this is heavy: ~5-10 min on Mac)...")
    hma_feat = build_hma_features(events)
    print(f"  HMA features: {hma_feat.shape[1]}  ({time.time()-t2:.1f}s)")

    # Combine
    print(f"\nCombining...")
    df_final = pd.concat([
        events[["event_id", "asset", "born_ms", "direction", "t_id", "n_comp",
                 "entry", "R", "touched", "outcome", "label", "decisive", "regime"]],
        ch_feat,
        hma_feat,
    ], axis=1)
    print(f"  final shape: {df_final.shape}  ({df_final.shape[1] - 13} features)")
    print(f"  saving -> {OUT}")
    df_final.to_parquet(OUT, index=False)
    size_mb = OUT.stat().st_size / 1024 / 1024
    print(f"  size: {size_mb:.1f} MB")

    # Quick stats
    print(f"\n── Feature coverage (% non-NaN) by family ──")
    fams = ["fund_", "oi_", "dvol_", "cross_", "macro_", "hma_", "aligned_", "slope_coherence_"]
    for fam in fams:
        cols = [c for c in df_final.columns if c.startswith(fam)]
        if not cols:
            continue
        cov = df_final[cols].notna().mean(axis=1).mean() * 100
        print(f"  {fam:<25}: {len(cols):>4} fts  coverage {cov:>5.1f}%")

    print(f"\nTotal elapsed: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
