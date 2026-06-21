"""v2 Phase 4 feature builder — Living organism features.

Inputs:  features_v2_phase3.parquet
Outputs: features_v2_phase4.parquet  (final v2 dataset for ML)

Adds:
  - Volatility regime (req #11)
  - Pulse / rhythm (req #13)
  - Trend exhaustion (req #14)
  - Predator / prey (req #15)
  - Tension / release (req #16)
"""
from __future__ import annotations
import pathlib
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from features._common import load_1m_full, aggregate_all_tfs
from features.volatility import build_volatility_features_for_asset
from features.rhythm import build_rhythm_features_for_asset
from features.exhaustion import build_exhaustion_features_for_asset
from features.predator import build_predator_features_for_asset
from features.tension import build_tension_features_for_asset


REPO = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v2")
SRC = REPO / "features_v2_phase3.parquet"
OUT = REPO / "features_v2_phase4.parquet"


def main():
    t0 = time.time()
    print("=" * 72)
    print("v2 Phase 4 — Living Organism Features")
    print("=" * 72)

    print(f"\n[1/3] Loading Phase 3 features...")
    df = pd.read_parquet(SRC)
    print(f"  rows: {len(df):,}  cols: {df.shape[1]}")

    new_feats = {}

    for asset in ("BTC", "ETH"):
        symbol = f"{asset}USDT"
        mask = (df.asset == asset).to_numpy()
        if mask.sum() == 0: continue
        born_subset = df.loc[mask, "born_ms"].to_numpy(dtype=np.int64)

        t1 = time.time()
        print(f"\n[2/3] [{asset}] loading 1m + aggregating...")
        rows_1m = load_1m_full(symbol)
        bars = aggregate_all_tfs(rows_1m)
        print(f"  done ({time.time()-t1:.1f}s)")

        t2 = time.time()
        print(f"\n[3/3] [{asset}] building features...")

        print(f"  Volatility regime (#11)...")
        feats = build_volatility_features_for_asset(bars, born_subset)
        print(f"    + {len(feats)}")

        print(f"  Pulse / rhythm (#13)...")
        r = build_rhythm_features_for_asset(bars, born_subset)
        feats.update(r); print(f"    + {len(r)}")

        print(f"  Trend exhaustion (#14)...")
        e = build_exhaustion_features_for_asset(bars, born_subset)
        feats.update(e); print(f"    + {len(e)}")

        print(f"  Predator/prey (#15)...")
        p = build_predator_features_for_asset(bars, born_subset)
        feats.update(p); print(f"    + {len(p)}")

        print(f"  Tension/release (#16)...")
        t = build_tension_features_for_asset(bars, born_subset)
        feats.update(t); print(f"    + {len(t)}")

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
    print(f"  shape: {df_final.shape}  (+{df_final.shape[1] - df.shape[1]} fts)")
    print(f"  size: {size_mb:.1f} MB")
    print(f"  saved -> {OUT}")

    # Coverage report
    print(f"\n── Phase 4 family coverage ──")
    fams = {
        "vol_*_atr*":      [c for c in new_df.columns if c.startswith("vol_") and "atr" in c],
        "vol_*_compression/expansion": [c for c in new_df.columns if c.startswith("vol_") and ("compression" in c or "expansion" in c)],
        "vol_*_realized/vov": [c for c in new_df.columns if c.startswith("vol_") and ("realized" in c or "vov" in c)],
        "vol_*_bb":        [c for c in new_df.columns if c.startswith("vol_") and "bb" in c],
        "rhy_*":           [c for c in new_df.columns if c.startswith("rhy_")],
        "exh_*":           [c for c in new_df.columns if c.startswith("exh_")],
        "pred_*":          [c for c in new_df.columns if c.startswith("pred_")],
        "tens_*":          [c for c in new_df.columns if c.startswith("tens_")],
    }
    for lbl, cols in fams.items():
        if not cols: continue
        cov = new_df[cols].notna().mean(axis=1).mean() * 100
        print(f"  {lbl:<35} {len(cols):>4} fts  coverage {cov:>5.1f}%")

    print(f"\nTotal elapsed: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
