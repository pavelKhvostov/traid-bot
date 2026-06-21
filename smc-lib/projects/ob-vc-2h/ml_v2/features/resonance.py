"""Multi-TF ob_vc resonance per req #12.

For each 2h event, check whether HTF ob_vc is active at born_ms:
  - Parent HTF: 4h, 6h, 12h, 1d, 2d, 3d
  - Cascade 1.1.1 v1 (nested): OB-1d/12h ⊇ FVG-4h/6h ⊇ 2h.OB ⊇ FVG-15m/20m

Source: ob_vc_phase1_5.parquet (BTC only — ETH would need rebuild,
        for v1.5 we use BTC values; ETH features will be NaN).

Features per event:
  resonance_parent_{tf}_active   bool: parent HTF ob_vc same dir is born
  resonance_parent_count         number of parent HTFs with resonance
  resonance_cascade_l1           same direction across 2+ HTF tiers
  resonance_cascade_l2           same direction across 3+ HTF tiers
"""
from __future__ import annotations
import pathlib

import numpy as np
import pandas as pd


PHASE15_PATH = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/data/ob_vc_phase1_5.parquet")
PARENT_TFS = ["4h", "6h", "12h", "1d", "2d", "3d"]


def build_resonance_features_for_asset(asset: str, born_ms_array: np.ndarray,
                                         directions: np.ndarray) -> dict[str, np.ndarray]:
    """For each event (born_ms + direction), check parent ob_vc presence per TF.

    Note: phase1_5.parquet is BTC only. For ETH, features return NaN.
    """
    n_events = len(born_ms_array)
    out = {}

    if asset != "BTC" or not PHASE15_PATH.exists():
        # ETH or missing — fill NaN
        for tf in PARENT_TFS:
            out[f"resonance_parent_{tf}_active"] = np.full(n_events, np.nan)
        out["resonance_parent_count"] = np.full(n_events, np.nan)
        out["resonance_cascade_l1"] = np.full(n_events, np.nan)
        out["resonance_cascade_l2"] = np.full(n_events, np.nan)
        return out

    df = pd.read_parquet(PHASE15_PATH)
    # Group ob_vc by (htf, direction): list of (cur_open_ms, cur_close_ms, valid_until_ms)
    per_tf_dir = {}
    for tf in PARENT_TFS:
        sub = df[df.htf == tf]
        for dir_ in ("long", "short"):
            ss = sub[sub.direction == dir_].drop_duplicates(["ob_cur_open_ms"])
            arr = ss[["ob_cur_open_ms", "ob_cur_close_ms", "valid_until_ms"]].to_numpy()
            arr = arr[arr[:, 0].argsort()]
            per_tf_dir[(tf, dir_)] = arr

    for tf in PARENT_TFS:
        active = np.full(n_events, np.nan)
        for i, (b, d) in enumerate(zip(born_ms_array, directions)):
            arr = per_tf_dir.get((tf, d))
            if arr is None or len(arr) == 0:
                active[i] = 0
                continue
            # find ob_vc where cur_close_ms <= b < valid_until_ms
            mask = (arr[:, 1] <= b) & (b < arr[:, 2])
            active[i] = 1.0 if mask.any() else 0.0
        out[f"resonance_parent_{tf}_active"] = active

    # Parent count: how many TFs show active resonance
    counts = np.zeros(n_events)
    for tf in PARENT_TFS:
        arr = out[f"resonance_parent_{tf}_active"]
        v = ~np.isnan(arr)
        counts[v] += arr[v]
    out["resonance_parent_count"] = counts

    # Cascade L1: 2+ parents active
    out["resonance_cascade_l1"] = (counts >= 2).astype(np.float64)
    # Cascade L2: 3+ parents active
    out["resonance_cascade_l2"] = (counts >= 3).astype(np.float64)

    return out
