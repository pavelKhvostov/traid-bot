"""v3 HMA-only feature builder — entry_fill_ms anchor + wait-window summary.

Input:  labels_v2.parquet (events + TBM v2 outcomes)
Output: features_v3_hma.parquet
"""
from __future__ import annotations
import pathlib
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from features._common import load_1m_full, aggregate_all_tfs
from features.hma_at_entry import build_hma_features_at_entry
from features.wait_window import build_wait_window_features


REPO = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc")
LABELS = REPO / "ml_v2" / "labels_v2.parquet"
OUT = REPO / "ml_v3" / "features_v3_hma.parquet"


def main():
    t0 = time.time()
    print("=" * 72)
    print("v3 HMA-only Feature Builder (entry_fill_ms anchor)")
    print("=" * 72)

    print("\n[1/4] Loading labels...")
    events = pd.read_parquet(LABELS)
    print(f"  events: {len(events):,}")

    # Compute entry_fill_ms for events that touched entry
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
        if mask.sum() == 0:
            continue

        born_subset = events.loc[mask, "born_ms"].to_numpy(dtype=np.int64)
        entry_subset = events.loc[mask, "entry_fill_ms"].to_numpy(dtype=np.int64)
        sl_subset = np.where(
            events.loc[mask, "direction"] == "long",
            events.loc[mask, "drop_lo"].astype(np.float64),
            events.loc[mask, "drop_hi"].astype(np.float64),
        )
        entry_levels = events.loc[mask, "entry"].to_numpy(dtype=np.float64)

        t1 = time.time()
        print(f"\n[2/4] [{asset}] loading 1m + aggregating...")
        rows_1m = load_1m_full(symbol)
        bars = aggregate_all_tfs(rows_1m)
        print(f"  1m: {len(rows_1m):,}  bars per TF computed  ({time.time()-t1:.1f}s)")

        t2 = time.time()
        print(f"\n[3/4] [{asset}] building features...")

        print(f"  HMA @ entry_fill_ms (11 TFs × 10 lens × 5 derivs)...")
        feats = build_hma_features_at_entry(bars, entry_subset)
        print(f"    HMA features: {len(feats)}")

        print(f"  Wait-window summary...")
        direction_subset = events.loc[mask, "direction"].to_numpy()
        ww = build_wait_window_features(rows_1m, born_subset, entry_subset,
                                          sl_subset, entry_levels, direction_subset)
        feats.update(ww)
        print(f"    wait-window features: {len(ww)}")

        for k, v in feats.items():
            if k not in feature_dicts:
                feature_dicts[k] = np.full(len(events), np.nan)
            feature_dicts[k][mask] = v

        print(f"  [{asset}] features done  ({time.time()-t2:.1f}s)")

    # Combine
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
    ]  # fill_delay_min is included via wait_window features
    df_final = pd.concat([events[keep_event_cols].reset_index(drop=True),
                            df_feat.reset_index(drop=True)], axis=1)
    df_final.to_parquet(OUT, index=False)
    size_mb = OUT.stat().st_size / 1024 / 1024
    print(f"  shape: {df_final.shape}")
    print(f"  features: {len(df_feat.columns)}")
    print(f"  size: {size_mb:.1f} MB")
    print(f"  saved -> {OUT}")

    # Coverage report
    print(f"\n── Coverage by family ──")
    hma_cols = [c for c in df_feat.columns if c.startswith("hma_") or
                  c.startswith("aligned_") or c.startswith("slope_coherence_") or
                  c.startswith("cascade_")]
    ww_cols = [c for c in df_feat.columns if c.startswith("wait_") or
                 c == "fill_delay_min"]
    print(f"  HMA family:           {len(hma_cols):>4} fts  cov {df_feat[hma_cols].notna().mean(axis=1).mean()*100:>5.1f}%")
    print(f"  Wait-window summary:  {len(ww_cols):>4} fts  cov {df_feat[ww_cols].notna().mean(axis=1).mean()*100:>5.1f}%")

    # Diagnostic: how many touched SL before entry?
    print(f"\n── Diagnostic: critical wait flags ──")
    df_valid = df_final[df_final.fill_touched]
    if "wait_touched_sl_before_entry" in df_final.columns:
        sl_touched_before = (df_valid["wait_touched_sl_before_entry"] > 0.5).sum()
        print(f"  wait_touched_sl_before_entry == 1: {sl_touched_before:,} "
              f"({sl_touched_before/len(df_valid)*100:.1f}% of touched events)")
        print(f"    → setups where price reached SL before entry → INVALID")

    print(f"\nTotal elapsed: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
