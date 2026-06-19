"""v2 feature builder orchestrator — Phase 2.

Pipeline:
  1. Load labels_v2.parquet (BTC + ETH events with TBM v2 outcomes)
  2. For each asset: load 1m, aggregate to TFs, build feature dict
     - HMA pruned + evolution
     - Candle morphology
     - Volume family
  3. Combine all events × all features
  4. Save features_v2_phase2.parquet
"""
from __future__ import annotations
import pathlib
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from features._common import load_1m_full, aggregate_all_tfs
from features.hma_pruned import build_hma_features_for_asset
from features.candles import build_candle_features_for_asset
from features.volume import build_volume_features_for_asset


REPO = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v2")
LABELS = REPO / "labels_v2.parquet"
OUT = REPO / "features_v2_phase2.parquet"


def main():
    t0 = time.time()
    print("=" * 72)
    print("v2 Phase 2 — Core Feature Builder")
    print("=" * 72)

    print("\n[1/4] Loading labels...")
    events = pd.read_parquet(LABELS)
    print(f"  events: {len(events):,}  ({events.asset.value_counts().to_dict()})")

    feature_dicts = {}  # asset -> {feat_name: array}

    for asset in ("BTC", "ETH"):
        symbol = f"{asset}USDT"
        mask = (events.asset == asset).to_numpy()
        born_subset = events.loc[mask, "born_ms"].to_numpy(dtype=np.int64)
        if len(born_subset) == 0:
            continue

        t1 = time.time()
        print(f"\n[2/4] [{asset}] loading 1m + aggregating...")
        rows_1m = load_1m_full(symbol)
        print(f"  1m bars: {len(rows_1m):,}")
        bars = aggregate_all_tfs(rows_1m)
        for tf, arr in bars.items():
            print(f"  {tf:>4}: {len(arr):,} bars", end="; ")
        print(f"\n  agg done ({time.time()-t1:.1f}s)")

        t2 = time.time()
        print(f"\n[3/4] [{asset}] building features...")
        feats = {}

        print(f"  HMA pruned + evolution...")
        feats.update(build_hma_features_for_asset(bars, born_subset))
        print(f"    HMA features so far: {len(feats)}")

        print(f"  Candle morphology...")
        feats.update(build_candle_features_for_asset(bars, born_subset))
        print(f"    after candles: {len(feats)}")

        print(f"  Volume family...")
        feats.update(build_volume_features_for_asset(bars, born_subset))
        print(f"    after volume: {len(feats)}")

        print(f"  [{asset}] features: {len(feats)}  ({time.time()-t2:.1f}s)")
        feature_dicts[asset] = feats

    # Combine: union of all feature names from both assets
    print(f"\n[4/4] combining BTC + ETH feature dicts...")
    all_keys = set()
    for d in feature_dicts.values():
        all_keys.update(d.keys())

    df_feat = pd.DataFrame(index=events.index)
    for k in sorted(all_keys):
        col = np.full(len(events), np.nan)
        for asset, d in feature_dicts.items():
            if k in d:
                mask = (events.asset == asset).to_numpy()
                col[mask] = d[k]
        df_feat[k] = col

    # Combine with key event metadata + labels
    keep = ["event_id", "asset", "born_ms", "direction", "t_id", "n_comp",
             "entry", "R", "r_pct", "r_pct_pass",
             "fill_touched", "fill_delay_min",
             "mfe_R", "mae_R", "sl_hit", "exit_reason",
             "hit_RR_14", "hit_RR_15", "hit_RR_17", "hit_RR_20",
             "hit_RR_23", "hit_RR_25", "hit_RR_28"]
    df_final = pd.concat([events[keep].reset_index(drop=True),
                           df_feat.reset_index(drop=True)], axis=1)

    df_final.to_parquet(OUT, index=False)
    size_mb = OUT.stat().st_size / 1024 / 1024
    print(f"\n[saved] {OUT}")
    print(f"  shape: {df_final.shape}")
    print(f"  features: {len(df_feat.columns)}")
    print(f"  size: {size_mb:.1f} MB")

    # Coverage by family
    print(f"\n── Coverage by family (% non-NaN, average) ──")
    fams = {
        "hma_*_above": [c for c in df_feat.columns if c.startswith("hma_") and c.endswith("_above")],
        "hma_*_dist_pct": [c for c in df_feat.columns if c.startswith("hma_") and c.endswith("_dist_pct")],
        "hma_*_slope*": [c for c in df_feat.columns if c.startswith("hma_") and "slope" in c],
        "hma_*_fan_compression": [c for c in df_feat.columns if c.startswith("hma_") and "fan_compression" in c],
        "hma_*_bars_since": [c for c in df_feat.columns if "bars_since" in c],
        "hma_*_cross_count": [c for c in df_feat.columns if "cross_count" in c],
        "aligned_count_*": [c for c in df_feat.columns if c.startswith("aligned_")],
        "cascade_*": [c for c in df_feat.columns if c.startswith("cascade_")],
        "slope_coherence_*": [c for c in df_feat.columns if c.startswith("slope_coherence_")],
        "candle (c_*)": [c for c in df_feat.columns if c.startswith("c_")],
        "volume (vol_*)": [c for c in df_feat.columns if c.startswith("vol_")],
    }
    for label, cols in fams.items():
        if not cols:
            continue
        cov = df_feat[cols].notna().mean(axis=1).mean() * 100
        print(f"  {label:<35} {len(cols):>4} fts  coverage {cov:>5.1f}%")

    print(f"\nTotal elapsed: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
