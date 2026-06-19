"""SOL transfer test: train v3.3 model on full BTC+ETH, predict on SOL events.

Steps:
  1. Load BTC+ETH features → train HistGradientBoosting × 3 seeds
  2. Load SOL features → predict proba via ensemble
  3. Filter top-N (matching ETA = trades/year × SOL years)
  4. Report WR/Σ R per (asset, t_id) breakdown
  5. Compare BTC vs ETH vs SOL transfer performance
"""
from __future__ import annotations
import pathlib
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

warnings.filterwarnings("ignore")
sys.path.insert(0, str(pathlib.Path("/Users/vadim/Desktop/compute-archives/compute-2026-06-09-ob-vc-hma-v3-pc1")))
from ml.sample_weights import compute_sample_weights
from sklearn.ensemble import HistGradientBoostingClassifier


BTC_ETH = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v3/features_v33_picked.parquet")
SOL_FEATS = pathlib.Path("/Users/vadim/smc-lib/strategies/strategy_ob_vc_v33_lean_picked/features_v33_picked_SOL.parquet")
OUT_DIR = pathlib.Path("/Users/vadim/smc-lib/strategies/strategy_ob_vc_v33_lean_picked")

TARGET = "hit_RR_20"
RR = 2.0

FEAT_COLS = [
    # 11 wait
    "fill_delay_min", "wait_max_high_pct", "wait_min_low_pct",
    "wait_touched_sl_before_entry", "wait_volume_total", "wait_directional_efficiency",
    "wait_net_move_pct", "wait_bars_count_15m", "wait_bars_count_1h",
    "wait_bars_count_4h", "wait_volatility_change_pct",
    # 11 HMA
    "hma_15m_7_dist_pct", "hma_20m_6_dist_pct", "hma_1h_4_dist_pct",
    "hma_90m_8_dist_pct", "hma_2h_4_dist_pct", "hma_4h_4_dist_pct",
    "hma_6h_6_dist_pct", "hma_12h_8_dist_pct", "hma_1d_8_dist_pct",
    "hma_2d_8_dist_pct", "hma_3d_12_dist_pct",
]


def make_model(seed=42):
    return HistGradientBoostingClassifier(
        learning_rate=0.05, max_iter=300, max_leaf_nodes=31, max_depth=None,
        min_samples_leaf=40, l2_regularization=0.1, random_state=seed,
    )


def main():
    print("=" * 72)
    print("SOL transfer test (v3.3): train BTC+ETH → predict SOL")
    print("=" * 72)

    # ─── Step 1: Train on full BTC+ETH ────
    print("\n[1/4] Loading BTC+ETH training data...")
    train = pd.read_parquet(BTC_ETH)
    train = train[train.fill_touched & train.r_pct_pass].reset_index(drop=True)
    print(f"  viable: {len(train):,} (BTC={sum(train.asset=='BTC')}, ETH={sum(train.asset=='ETH')})")

    # Compute sample weights
    train["sample_weight"] = compute_sample_weights(train)

    X_tr = train[FEAT_COLS].to_numpy(dtype=np.float32)
    y_tr = train[TARGET].to_numpy()
    w_tr = train.sample_weight.to_numpy()

    print(f"\n[2/4] Training ensemble (3 seeds)...")
    seeds = (42, 1337, 2024)
    models = []
    for seed in seeds:
        m = make_model(seed=seed)
        m.fit(X_tr, y_tr, sample_weight=w_tr)
        # In-sample AUC sanity check
        proba_in = m.predict_proba(X_tr)[:, 1]
        auc = roc_auc_score(y_tr, proba_in)
        print(f"  seed={seed}: in-sample AUC={auc:.4f}")
        models.append(m)

    # ─── Step 3: Predict on SOL ────
    print(f"\n[3/4] Loading SOL features + predicting...")
    sol = pd.read_parquet(SOL_FEATS)
    sol_viable = sol[sol.fill_touched & sol.r_pct_pass].reset_index(drop=True)
    print(f"  SOL viable: {len(sol_viable):,}")

    # Check for NaN
    nan_per_col = sol_viable[FEAT_COLS].isna().sum()
    if (nan_per_col > 0).any():
        print(f"  ⚠ NaN counts:")
        for c, n in nan_per_col.items():
            if n > 0: print(f"    {c}: {n}")
        sol_viable = sol_viable.dropna(subset=FEAT_COLS).reset_index(drop=True)
        print(f"  after NaN drop: {len(sol_viable):,}")

    X_sol = sol_viable[FEAT_COLS].to_numpy(dtype=np.float32)

    # Ensemble prediction
    proba_ensemble = np.mean(
        [m.predict_proba(X_sol)[:, 1] for m in models], axis=0)
    sol_viable["proba"] = proba_ensemble

    # SOL AUC (honest — model never saw SOL)
    if (sol_viable[TARGET] == 0).any() and (sol_viable[TARGET] == 1).any():
        sol_auc = roc_auc_score(sol_viable[TARGET], proba_ensemble)
        print(f"\n  SOL out-of-asset AUC: {sol_auc:.4f}")

    # ─── Step 4: Selection sweep ────
    print(f"\n[4/4] Selection sweep + comparison")
    sol_sorted = sol_viable.sort_values("proba", ascending=False).reset_index(drop=True)
    sol_sorted["R"] = sol_sorted[TARGET] * RR - (1 - sol_sorted[TARGET]) * 1.0

    print(f"\n── SOL selection sweep ──")
    print(f"{'N':>5} {'WR%':>6} {'E[R]':>7} {'Σ R':>7}")
    for N in [200, 400, 600, 800, 1000, 1100, 1300, 1500, 1800, 2000, 2500, 3000]:
        if N > len(sol_sorted): break
        top = sol_sorted.head(N)
        wr = top[TARGET].mean() * 100
        sum_r = top.R.sum()
        er = sum_r / N
        marker = " ⭐" if wr >= 70 else "  "
        print(f"{N:>5} {wr:>5.1f}% {er:>+6.3f}R {sum_r:>+6.0f}R{marker}")

    # Compare against BTC+ETH baseline
    print(f"\n" + "=" * 72)
    print("Master comparison: BTC vs ETH vs SOL transfer")
    print("=" * 72)
    print(f"{'Asset':<8} {'N_viable':>10} {'Years':>7} {'N_sel':>7} {'WR%':>6} {'E[R]':>7} {'Σ R':>7}")

    # BTC and ETH from v3.3 OOS
    oos = pd.read_parquet("/Users/vadim/Desktop/output4/oos_predictions.parquet")
    sub_oos = oos[(oos.target == TARGET) & (oos.model == "lgb")]
    sub_oos = sub_oos.groupby("event_idx").agg(
        proba=("proba", "mean"), y_true=("y_true", "first")).reset_index()
    sub_sorted = sub_oos.sort_values("proba", ascending=False).reset_index(drop=True)
    # Get top-N=1100 → split per asset
    top_oos = sub_sorted.head(1100)
    # Need to merge with features for asset labels
    train_meta = train.reset_index().rename(columns={"index": "event_idx"})[["event_idx", "asset"]]
    top_oos = top_oos.merge(train_meta, on="event_idx", how="left")

    for asset in ["BTC", "ETH", "SOL"]:
        if asset in ("BTC", "ETH"):
            sub_a = top_oos[top_oos.asset == asset]
            n_sel = len(sub_a)
            wr = sub_a.y_true.mean() * 100
            sum_r = sub_a.y_true.sum() * RR - (1 - sub_a.y_true).sum() * 1.0
            er = sum_r / n_sel if n_sel else 0
            n_viable = sum(train.asset == asset)
            yrs = 6.4
        else:
            # SOL — pick N matching same selectivity ratio
            # Same selectivity as BTC+ETH: 1100/6325 = 17.4%
            ratio = 1100 / len(train)
            n_sel = int(len(sol_sorted) * ratio)
            top_sol = sol_sorted.head(n_sel)
            wr = top_sol[TARGET].mean() * 100
            sum_r = top_sol.R.sum()
            er = sum_r / n_sel if n_sel else 0
            n_viable = len(sol_sorted)
            yrs = 5.8
        print(f"{asset:<8} {n_viable:>10,} {yrs:>7.1f} {n_sel:>7,} {wr:>5.1f}% {er:>+6.3f}R {sum_r:>+6.0f}R")

    # Save predictions
    sol_sorted.to_parquet(OUT_DIR / "sol_predictions_v33.parquet", index=False)
    print(f"\nSaved predictions: {OUT_DIR / 'sol_predictions_v33.parquet'}")


if __name__ == "__main__":
    main()
