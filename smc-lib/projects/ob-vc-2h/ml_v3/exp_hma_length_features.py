"""Build HMA-L dist_pct features for L = 9, 10, ..., 21 on all 11 TFs.

Output: features_hma_lengths_9_21.parquet (143 new features + metadata)
"""
from __future__ import annotations
import pathlib
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from features._common import load_1m_full, aggregate_all_tfs, TF_SPECS, hma_np


LABELS = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v2/labels_v2.parquet")
OUT = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v3/features_hma_lengths_9_21.parquet")
LENGTHS = list(range(9, 22))   # 9, 10, 11, ..., 21


def build_hma_length_features(bars: dict[str, np.ndarray],
                                entry_ms_array: np.ndarray) -> dict[str, np.ndarray]:
    n_events = len(entry_ms_array)
    out = {}

    for tf, bar_arr in bars.items():
        closes = bar_arr[:, 4]
        ts_arr = bar_arr[:, 0].astype(np.int64)
        valid_event = entry_ms_array > 0
        idx_at_event = np.full(n_events, -1, dtype=np.int64)
        if valid_event.any():
            idx_at_event[valid_event] = np.searchsorted(
                ts_arr, entry_ms_array[valid_event], side="right") - 1
        valid = (idx_at_event >= 0) & valid_event

        close_at_event = np.full(n_events, np.nan)
        close_at_event[valid] = closes[idx_at_event[valid]]

        for L in LENGTHS:
            if L >= len(closes):
                continue
            hma_arr = hma_np(closes, L)
            val_now = np.full(n_events, np.nan)
            val_now[valid] = hma_arr[idx_at_event[valid]]
            with np.errstate(divide="ignore", invalid="ignore"):
                dist_pct = np.where(np.abs(val_now) > 1e-9,
                                     (close_at_event - val_now) / val_now * 100, np.nan)
            out[f"hma_{tf}_{L}_dist_pct"] = dist_pct

    return out


def main():
    t0 = time.time()
    print("Building HMA-L features for L=9..21 on all 11 TFs")

    events = pd.read_parquet(LABELS)
    events["entry_fill_ms"] = np.where(
        events["fill_touched"],
        events["born_ms"] + (events["fill_delay_min"].fillna(0) * 60_000).astype(np.int64),
        -1
    ).astype(np.int64)

    feature_dicts = {}
    for asset in ("BTC", "ETH"):
        symbol = f"{asset}USDT"
        mask = (events.asset == asset).to_numpy()
        if mask.sum() == 0: continue
        entry_subset = events.loc[mask, "entry_fill_ms"].to_numpy(dtype=np.int64)

        t1 = time.time()
        print(f"\n[{asset}] loading 1m + aggregating...")
        rows_1m = load_1m_full(symbol)
        bars = aggregate_all_tfs(rows_1m)
        print(f"  done ({time.time()-t1:.1f}s)")

        t2 = time.time()
        print(f"[{asset}] computing HMA-L dist_pct (13 lengths × 11 TFs)...")
        feats = build_hma_length_features(bars, entry_subset)
        print(f"  features: {len(feats)} ({time.time()-t2:.1f}s)")

        for k, v in feats.items():
            if k not in feature_dicts:
                feature_dicts[k] = np.full(len(events), np.nan)
            feature_dicts[k][mask] = v

    print(f"\nCombining...")
    df_feat = pd.DataFrame(feature_dicts, index=events.index)
    keep = ["event_id", "asset", "born_ms", "direction", "t_id", "n_comp",
             "entry", "R", "r_pct", "r_pct_pass",
             "fill_touched", "fill_delay_min", "mfe_R",
             "hit_RR_14", "hit_RR_15", "hit_RR_17", "hit_RR_20",
             "hit_RR_23", "hit_RR_25", "hit_RR_28"]
    df_final = pd.concat([events[keep].reset_index(drop=True),
                            df_feat.reset_index(drop=True)], axis=1)
    df_final["entry_fill_ms"] = events["entry_fill_ms"].values
    df_final.to_parquet(OUT, index=False)
    size_mb = OUT.stat().st_size / 1024 / 1024
    print(f"  shape: {df_final.shape}  size: {size_mb:.1f} MB")
    print(f"  saved -> {OUT}")
    print(f"\nTotal elapsed: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
