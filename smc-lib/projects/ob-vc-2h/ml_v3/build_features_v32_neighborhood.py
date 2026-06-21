"""v3.2 neighborhood expansion — 11 HMA-9 baseline + 10 L variants per TF + 11 wait.

Output: features_v32_neighborhood.parquet (132 features)
"""
from __future__ import annotations
import pathlib
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from features._common import load_1m_full, aggregate_all_tfs, hma_np


SRC_BASELINE = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v3/features_v3_hma.parquet")
OUT = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v3/features_v32_neighborhood.parquet")

# Длины: baseline L=9 + 10 variants (5 левее, 5 правее)
HMA_LENGTHS = [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]


def main():
    t0 = time.time()
    print("Building v3.2 neighborhood (HMA L=4..14 + wait baseline)")

    # Load baseline для wait features + labels
    base = pd.read_parquet(SRC_BASELINE)
    print(f"\nBaseline events: {len(base):,}, cols: {base.shape[1]}")

    # Compute entry_fill_ms
    base["entry_fill_ms"] = np.where(
        base["fill_touched"],
        base["born_ms"] + (base["fill_delay_min"].fillna(0) * 60_000).astype(np.int64),
        -1
    ).astype(np.int64)

    feature_dicts = {}

    for asset in ("BTC", "ETH"):
        symbol = f"{asset}USDT"
        mask = (base.asset == asset).to_numpy()
        if mask.sum() == 0: continue
        entry_subset = base.loc[mask, "entry_fill_ms"].to_numpy(dtype=np.int64)

        t1 = time.time()
        print(f"\n[{asset}] loading 1m + aggregating...")
        rows_1m = load_1m_full(symbol)
        bars = aggregate_all_tfs(rows_1m)
        print(f"  done ({time.time()-t1:.1f}s)")

        t2 = time.time()
        print(f"[{asset}] computing HMA L=4..14 dist_pct on 11 TFs...")
        for tf, bar_arr in bars.items():
            ts_arr = bar_arr[:, 0].astype(np.int64)
            closes = bar_arr[:, 4]

            valid_event = entry_subset > 0
            idx_at_event = np.full(len(entry_subset), -1, dtype=np.int64)
            if valid_event.any():
                idx_at_event[valid_event] = np.searchsorted(
                    ts_arr, entry_subset[valid_event], side="right") - 1
            valid = (idx_at_event >= 0) & valid_event

            close_at_event = np.full(len(entry_subset), np.nan)
            close_at_event[valid] = closes[idx_at_event[valid]]

            for L in HMA_LENGTHS:
                if L >= len(closes):
                    continue
                hma_arr = hma_np(closes, L)
                val_now = np.full(len(entry_subset), np.nan)
                val_now[valid] = hma_arr[idx_at_event[valid]]
                with np.errstate(divide="ignore", invalid="ignore"):
                    dist_pct = np.where(np.abs(val_now) > 1e-9,
                                         (close_at_event - val_now) / val_now * 100, np.nan)

                col = f"hma_{tf}_{L}_dist_pct"
                if col not in feature_dicts:
                    feature_dicts[col] = np.full(len(base), np.nan)
                feature_dicts[col][mask] = dist_pct

        print(f"  done ({time.time()-t2:.1f}s)")

    # Combine: original wait + new HMA neighborhood
    print(f"\nCombining...")
    wait_cols = [c for c in base.columns if c.startswith("wait_") or c == "fill_delay_min"]
    keep_meta = ["event_id", "asset", "born_ms", "entry_fill_ms", "direction",
                  "t_id", "n_comp",
                  "entry", "R", "r_pct", "r_pct_pass",
                  "fill_touched", "mfe_R", "mae_R", "sl_hit", "exit_reason",
                  "hit_RR_14", "hit_RR_15", "hit_RR_17", "hit_RR_20",
                  "hit_RR_23", "hit_RR_25", "hit_RR_28"]
    keep_cols = keep_meta + wait_cols

    df_neighbor = pd.DataFrame(feature_dicts, index=base.index)
    df_final = pd.concat([base[keep_cols].reset_index(drop=True),
                            df_neighbor.reset_index(drop=True)], axis=1)
    df_final.to_parquet(OUT, index=False)
    size_mb = OUT.stat().st_size / 1024 / 1024
    print(f"  shape: {df_final.shape}  size: {size_mb:.1f} MB")
    print(f"  features (HMA neighborhood + wait): "
          f"{len([c for c in df_neighbor.columns]) + len(wait_cols)}")
    print(f"  saved -> {OUT}")
    print(f"\nTotal elapsed: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
