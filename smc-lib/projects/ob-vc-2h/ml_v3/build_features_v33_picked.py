"""Build features_v33_picked.parquet — only 22 ML-picked features.

22 features = 11 wait + 11 HMA (best L per TF from v3.2 permutation importance).
"""
from __future__ import annotations
import pathlib
import pandas as pd


SRC = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v3/features_v32_neighborhood.parquet")
OUT = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v3/features_v33_picked.parquet")


PICKED_HMA = [
    "hma_15m_7_dist_pct",
    "hma_20m_6_dist_pct",
    "hma_1h_4_dist_pct",
    "hma_90m_8_dist_pct",
    "hma_2h_4_dist_pct",
    "hma_4h_4_dist_pct",
    "hma_6h_6_dist_pct",
    "hma_12h_8_dist_pct",
    "hma_1d_8_dist_pct",
    "hma_2d_8_dist_pct",
    "hma_3d_12_dist_pct",
]


def main():
    df = pd.read_parquet(SRC)
    print(f"Loaded: {df.shape}")

    wait_cols = [c for c in df.columns if c.startswith("wait_") or c == "fill_delay_min"]
    print(f"Wait features ({len(wait_cols)}): {wait_cols}")

    feat_cols = wait_cols + PICKED_HMA
    print(f"\nTotal features: {len(feat_cols)}")

    meta_cols = [c for c in df.columns if c not in feat_cols and not c.startswith("hma_")]
    print(f"Metadata cols: {len(meta_cols)}")
    for c in meta_cols:
        print(f"  {c}")

    keep = meta_cols + feat_cols
    df_out = df[keep].copy()
    print(f"\nOutput shape: {df_out.shape}")

    df_out.to_parquet(OUT, index=False)
    print(f"Saved: {OUT} ({OUT.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
