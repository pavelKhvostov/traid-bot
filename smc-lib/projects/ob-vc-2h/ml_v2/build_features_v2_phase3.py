"""v2 Phase 3 feature builder — Structure + Multi-TF resonance + Prior context.

Inputs:
  - features_v2_phase2.parquet (events + Phase 2 features)
Outputs:
  - features_v2_phase3.parquet (Phase 2 + Phase 3 features)
"""
from __future__ import annotations
import pathlib
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from features._common import load_1m_full, aggregate_all_tfs
from features.structure import build_structure_features_for_asset
from features.resonance import build_resonance_features_for_asset
from features.context import build_context_features_for_asset


REPO = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v2")
SRC = REPO / "features_v2_phase2.parquet"
OUT = REPO / "features_v2_phase3.parquet"


def main():
    t0 = time.time()
    print("=" * 72)
    print("v2 Phase 3 — Structure + Resonance + Context")
    print("=" * 72)

    print(f"\n[1/3] Loading Phase 2 features...")
    df = pd.read_parquet(SRC)
    print(f"  rows: {len(df):,}  cols: {df.shape[1]}")

    new_feats = {}  # feature_name -> array

    for asset in ("BTC", "ETH"):
        symbol = f"{asset}USDT"
        mask = (df.asset == asset).to_numpy()
        if mask.sum() == 0: continue
        born_subset = df.loc[mask, "born_ms"].to_numpy(dtype=np.int64)
        dir_subset = df.loc[mask, "direction"].to_numpy()
        entry_subset = df.loc[mask, "entry"].to_numpy(dtype=np.float64)

        t1 = time.time()
        print(f"\n[2/3] [{asset}] loading 1m + aggregating...")
        rows_1m = load_1m_full(symbol)
        bars = aggregate_all_tfs(rows_1m)
        print(f"  done ({time.time()-t1:.1f}s)")

        t2 = time.time()
        print(f"\n[3/3] [{asset}] building features...")

        print(f"  Structure (BOS/ChoCh/swing/premium-discount)...")
        feats = build_structure_features_for_asset(bars, born_subset)
        struct_n = len(feats)
        print(f"    structure features: {struct_n}")

        print(f"  Multi-TF resonance (ob_vc cascade)...")
        res = build_resonance_features_for_asset(asset, born_subset, dir_subset)
        feats.update(res)
        print(f"    resonance features: {len(res)}")

        print(f"  Prior context (FVG mitigation)...")
        ctx = build_context_features_for_asset(bars, born_subset, dir_subset, entry_subset)
        feats.update(ctx)
        print(f"    context features: {len(ctx)}")

        # Insert into new_feats with NaN for other assets
        for k, v in feats.items():
            if k not in new_feats:
                new_feats[k] = np.full(len(df), np.nan)
            new_feats[k][mask] = v

        print(f"  [{asset}] total new: {len(feats)}  ({time.time()-t2:.1f}s)")

    # Combine
    print(f"\nCombining...")
    new_df = pd.DataFrame(new_feats, index=df.index)
    df_final = pd.concat([df.reset_index(drop=True), new_df.reset_index(drop=True)], axis=1)
    df_final.to_parquet(OUT, index=False)
    size_mb = OUT.stat().st_size / 1024 / 1024
    print(f"  shape: {df_final.shape}  ({df_final.shape[1] - df.shape[1]} new fts)")
    print(f"  size: {size_mb:.1f} MB")
    print(f"  saved -> {OUT}")

    # Coverage report for new families
    print(f"\n── New family coverage ──")
    fams = {
        "struct_*_bos": [c for c in new_df.columns if c.startswith("struct_") and "bos" in c],
        "struct_*_choch": [c for c in new_df.columns if c.startswith("struct_") and "choch" in c],
        "struct_*_swing": [c for c in new_df.columns if c.startswith("struct_") and any(x in c for x in ["fh_", "fl_", "_count_5"])],
        "struct_*_premdisc": [c for c in new_df.columns if c.startswith("struct_") and "prem_disc" in c],
        "resonance_*": [c for c in new_df.columns if c.startswith("resonance_")],
        "ctx_*_fvg": [c for c in new_df.columns if c.startswith("ctx_")],
    }
    for lbl, cols in fams.items():
        if not cols: continue
        cov = new_df[cols].notna().mean(axis=1).mean() * 100
        print(f"  {lbl:<30} {len(cols):>4} fts  coverage {cov:>5.1f}%")

    print(f"\nTotal elapsed: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
