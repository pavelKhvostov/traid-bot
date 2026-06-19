"""v3.5 HONEST feature builder — v3 HONEST + cross-TF HMA cross features.

601 features (v3 honest) + 60 cross-TF features = 661 total.

Output: features_v35_hma_honest_cross.parquet
"""
from __future__ import annotations
import pathlib
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from features._common import load_1m_full, aggregate_all_tfs
from features.hma_at_entry_honest import build_hma_features_at_entry_honest
from features.cross_tf_crosses import build_cross_tf_features
from features.wait_window import build_wait_window_features


REPO = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc")
LABELS = REPO / "ml_v2" / "labels_v2.parquet"
OUT = REPO / "ml_v3" / "features_v35_hma_honest_cross.parquet"


def main():
    t0 = time.time()
    print("=" * 72)
    print("v3.5 HONEST + CROSS-TF (entry_fill_ms anchor, INTRADAY live)")
    print("=" * 72)

    print("\n[1/4] Loading labels...")
    events = pd.read_parquet(LABELS)
    print(f"  events: {len(events):,}")

    events["entry_fill_ms"] = np.where(
        events["fill_touched"],
        events["born_ms"] + (events["fill_delay_min"].fillna(0) * 60_000).astype(np.int64),
        -1
    ).astype(np.int64)
    print(f"  fill touched: {(events.entry_fill_ms > 0).sum():,}")

    feature_dicts = {}

    for asset in ("BTC", "ETH"):
        symbol = f"{asset}USDT"
        mask = (events.asset == asset).to_numpy()
        if mask.sum() == 0: continue

        born_subset = events.loc[mask, "born_ms"].to_numpy(dtype=np.int64)
        entry_subset = events.loc[mask, "entry_fill_ms"].to_numpy(dtype=np.int64)
        sl_subset = np.where(
            events.loc[mask, "direction"] == "long",
            events.loc[mask, "drop_lo"].astype(np.float64),
            events.loc[mask, "drop_hi"].astype(np.float64))
        entry_levels = events.loc[mask, "entry"].to_numpy(dtype=np.float64)
        direction_subset = events.loc[mask, "direction"].to_numpy()

        t1 = time.time()
        print(f"\n[2/4] [{asset}] loading 1m + aggregating...")
        rows_1m = load_1m_full(symbol)
        bars = aggregate_all_tfs(rows_1m)
        print(f"  1m: {len(rows_1m):,}  ({time.time()-t1:.1f}s)")

        t2 = time.time()
        print(f"[3/4] [{asset}] building features...")

        print(f"  HMA honest intraday...")
        feats = build_hma_features_at_entry_honest(bars, rows_1m, entry_subset)
        print(f"    HMA features: {len(feats)}")

        t3 = time.time()
        print(f"  Cross-TF cross features (honest live)...")
        cross_feats = build_cross_tf_features(bars, rows_1m, entry_subset)
        feats.update(cross_feats)
        print(f"    cross features: {len(cross_feats)}  ({time.time()-t3:.1f}s)")

        ww = build_wait_window_features(rows_1m, born_subset, entry_subset,
                                          sl_subset, entry_levels, direction_subset)
        feats.update(ww)
        print(f"    wait features: {len(ww)}")
        print(f"  [{asset}] done  ({time.time()-t2:.1f}s)")

        for k, v in feats.items():
            if k not in feature_dicts:
                feature_dicts[k] = np.full(len(events), np.nan)
            feature_dicts[k][mask] = v

    print(f"\n[4/4] Combining + saving...")
    df_feat = pd.DataFrame(feature_dicts, index=events.index)

    keep_event_cols = [
        "event_id", "asset", "born_ms", "entry_fill_ms", "direction",
        "t_id", "n_comp", "extreme",
        "entry", "R", "r_pct", "r_pct_pass",
        "fill_touched",
        "mfe_R", "mae_R", "sl_hit", "exit_reason",
        "hit_RR_14", "hit_RR_15", "hit_RR_17", "hit_RR_20",
        "hit_RR_23", "hit_RR_25", "hit_RR_28",
    ]
    df_final = pd.concat([events[keep_event_cols].reset_index(drop=True),
                            df_feat.reset_index(drop=True)], axis=1)
    df_final.to_parquet(OUT, index=False)
    size_mb = OUT.stat().st_size / 1024 / 1024
    print(f"  shape: {df_final.shape}  size: {size_mb:.1f} MB")
    print(f"  saved -> {OUT}")
    print(f"\nTotal: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
