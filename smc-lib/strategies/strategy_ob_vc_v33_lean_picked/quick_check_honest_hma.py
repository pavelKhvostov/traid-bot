"""B Quick check — rebuild all 11 picked HMA features with HONEST logic.

Compare:
  Current (lookahead): closes[idx where ts[idx] <= entry_ms]  ← bar may be in progress
  Honest:              closes[idx where ts[idx] + tf_ms <= entry_ms]  ← last fully closed bar
                       price = 1m close at entry_ms minute  ← honest "now" price

Run quick CV AUC comparison: current vs honest.
"""
from __future__ import annotations
import csv
import pathlib
import sys
import time
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.ensemble import HistGradientBoostingClassifier

warnings.filterwarnings("ignore")
sys.path.insert(0, str(pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v3")))
from features._common import aggregate_all_tfs, hma_np, TF_SPECS


CURRENT_FEATS = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v3/features_v33_picked.parquet")
BTC_CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
ETH_CSV = pathlib.Path.home() / "traid-bot/data/ETHUSDT_1m_vic_vadim.csv"

PICKED_HMA = [
    ("15m", 7),  ("20m", 6),  ("1h", 4),   ("90m", 8),  ("2h", 4),
    ("4h", 4),   ("6h", 6),   ("12h", 8),  ("1d", 8),   ("2d", 8),  ("3d", 12),
]

WAIT_COLS = [
    "fill_delay_min", "wait_max_high_pct", "wait_min_low_pct",
    "wait_touched_sl_before_entry", "wait_volume_total", "wait_directional_efficiency",
    "wait_net_move_pct", "wait_bars_count_15m", "wait_bars_count_1h",
    "wait_bars_count_4h", "wait_volatility_change_pct",
]
HMA_COLS = [f"hma_{tf}_{L}_dist_pct" for tf, L in PICKED_HMA]
ALL_FEATS = WAIT_COLS + HMA_COLS


def load_1m(path):
    rows = []
    with path.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
            rows.append((t, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return np.array(rows, dtype=np.float64)


def compute_honest_hma(rows_1m, bars, entry_ms_array, tf_name, L):
    """Honest HMA dist_pct:
       - HMA computed at last CLOSED HTF bar (ts + tf_ms <= entry_ms)
       - Current price = 1m close at entry_ms
    """
    bar_arr = bars[tf_name]
    tf_ms = TF_SPECS[tf_name]
    ts_arr = bar_arr[:, 0].astype(np.int64)
    closes_htf = bar_arr[:, 4]

    if L >= len(closes_htf):
        return np.full(len(entry_ms_array), np.nan)

    hma_arr = hma_np(closes_htf, L)

    # Honest idx: last bar where (open + tf_ms) <= entry_ms ⟺ open <= entry_ms - tf_ms
    valid_event = entry_ms_array > 0
    honest_idx = np.full(len(entry_ms_array), -1, dtype=np.int64)
    if valid_event.any():
        cutoff = entry_ms_array[valid_event] - tf_ms
        honest_idx[valid_event] = np.searchsorted(ts_arr, cutoff, side="right") - 1
    valid_idx = (honest_idx >= 0) & valid_event

    # HMA value at honest idx
    hma_val = np.full(len(entry_ms_array), np.nan)
    hma_val[valid_idx] = hma_arr[honest_idx[valid_idx]]

    # Current price = 1m close at entry_ms
    ts_1m = rows_1m[:, 0].astype(np.int64)
    closes_1m = rows_1m[:, 4]
    idx_1m = np.full(len(entry_ms_array), -1, dtype=np.int64)
    if valid_event.any():
        idx_1m[valid_event] = np.searchsorted(ts_1m, entry_ms_array[valid_event], side="right") - 1
    valid_1m = (idx_1m >= 0) & valid_event

    price_now = np.full(len(entry_ms_array), np.nan)
    price_now[valid_1m] = closes_1m[idx_1m[valid_1m]]

    with np.errstate(divide="ignore", invalid="ignore"):
        dist_pct = np.where(
            np.abs(hma_val) > 1e-9,
            (price_now - hma_val) / hma_val * 100,
            np.nan
        )
    return dist_pct


def main():
    t0 = time.time()
    print("=" * 72)
    print("B Quick check — honest HMA features vs current (lookahead)")
    print("=" * 72)

    print("\n[1/4] Loading current features...")
    df = pd.read_parquet(CURRENT_FEATS)
    df_v = df[df.fill_touched & df.r_pct_pass].reset_index(drop=True)
    print(f"  viable events: {len(df_v):,}")

    print("\n[2/4] Building HONEST HMA features for BTC + ETH...")
    honest_features = {col: np.full(len(df_v), np.nan) for col in HMA_COLS}

    for asset, csv_path in [("BTC", BTC_CSV), ("ETH", ETH_CSV)]:
        print(f"\n  [{asset}] loading 1m + aggregating...")
        rows_1m = load_1m(csv_path)
        bars = aggregate_all_tfs(rows_1m)
        mask = (df_v.asset == asset).to_numpy()
        entry_ms_arr = df_v.loc[mask, "entry_fill_ms"].to_numpy(dtype=np.int64)
        print(f"    events: {mask.sum():,}")

        for (tf, L) in PICKED_HMA:
            col = f"hma_{tf}_{L}_dist_pct"
            honest_vals = compute_honest_hma(rows_1m, bars, entry_ms_arr, tf, L)
            honest_features[col][mask] = honest_vals

    df_honest = pd.DataFrame(honest_features)

    print("\n[3/4] Comparing current vs honest per HMA feature...")
    print(f"  {'feature':<25} {'corr':>8} {'mean_diff':>10} {'std_diff':>10}")
    for col in HMA_COLS:
        cur = df_v[col].to_numpy()
        hon = df_honest[col].to_numpy()
        m = ~(np.isnan(cur) | np.isnan(hon))
        if m.sum() < 100: continue
        corr = np.corrcoef(cur[m], hon[m])[0, 1]
        mean_diff = (hon[m] - cur[m]).mean()
        std_diff = (hon[m] - cur[m]).std()
        sig = " ⚠" if corr < 0.95 else ""
        print(f"  {col:<25} {corr:>+8.4f} {mean_diff:>+10.4f} {std_diff:>+10.4f}{sig}")

    print("\n[4/4] Training + comparing AUC (in-sample, full BTC+ETH)...")
    df_v["sample_weight"] = 1.0  # equal weights for speed
    y = df_v["hit_RR_20"].to_numpy()
    sw = df_v.sample_weight.to_numpy()

    # Current
    X_cur = df_v[ALL_FEATS].to_numpy(dtype=np.float32)
    # Honest = wait same + honest HMA
    X_hon = pd.concat([df_v[WAIT_COLS].reset_index(drop=True),
                        df_honest.reset_index(drop=True)], axis=1)[ALL_FEATS].to_numpy(dtype=np.float32)

    # Drop NaN rows (consistent)
    nan_mask = (~np.isnan(X_cur).any(axis=1)) & (~np.isnan(X_hon).any(axis=1))
    print(f"  consistent valid rows: {nan_mask.sum():,} / {len(df_v):,}")
    X_cur = X_cur[nan_mask]; X_hon = X_hon[nan_mask]
    y = y[nan_mask]; sw = sw[nan_mask]

    print("\n  Training current (with lookahead)...")
    m_cur = HistGradientBoostingClassifier(
        learning_rate=0.05, max_iter=300, max_leaf_nodes=31,
        min_samples_leaf=40, l2_regularization=0.1, random_state=42)
    m_cur.fit(X_cur, y, sample_weight=sw)
    auc_cur_in = roc_auc_score(y, m_cur.predict_proba(X_cur)[:, 1])

    print("  Training honest...")
    m_hon = HistGradientBoostingClassifier(
        learning_rate=0.05, max_iter=300, max_leaf_nodes=31,
        min_samples_leaf=40, l2_regularization=0.1, random_state=42)
    m_hon.fit(X_hon, y, sample_weight=sw)
    auc_hon_in = roc_auc_score(y, m_hon.predict_proba(X_hon)[:, 1])

    # Quick 5-fold CV (random split, not WF, just for comparison)
    from sklearn.model_selection import KFold
    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    auc_cur_cv = []
    auc_hon_cv = []
    for tr, te in kf.split(X_cur):
        m1 = HistGradientBoostingClassifier(
            learning_rate=0.05, max_iter=300, max_leaf_nodes=31,
            min_samples_leaf=40, l2_regularization=0.1, random_state=42)
        m1.fit(X_cur[tr], y[tr])
        auc_cur_cv.append(roc_auc_score(y[te], m1.predict_proba(X_cur[te])[:, 1]))

        m2 = HistGradientBoostingClassifier(
            learning_rate=0.05, max_iter=300, max_leaf_nodes=31,
            min_samples_leaf=40, l2_regularization=0.1, random_state=42)
        m2.fit(X_hon[tr], y[tr])
        auc_hon_cv.append(roc_auc_score(y[te], m2.predict_proba(X_hon[te])[:, 1]))

    print("\n" + "=" * 72)
    print("RESULTS — Current (lookahead) vs Honest")
    print("=" * 72)
    print(f"  In-sample AUC:")
    print(f"    Current: {auc_cur_in:.4f}")
    print(f"    Honest:  {auc_hon_in:.4f}")
    print(f"    Δ:       {auc_hon_in - auc_cur_in:+.4f}")
    print(f"\n  5-fold CV AUC (mean):")
    print(f"    Current: {np.mean(auc_cur_cv):.4f}  std={np.std(auc_cur_cv):.4f}")
    print(f"    Honest:  {np.mean(auc_hon_cv):.4f}  std={np.std(auc_hon_cv):.4f}")
    print(f"    Δ:       {np.mean(auc_hon_cv) - np.mean(auc_cur_cv):+.4f}")
    print(f"\n  Per-fold CV details:")
    for i, (a, b) in enumerate(zip(auc_cur_cv, auc_hon_cv)):
        print(f"    fold {i}: current={a:.4f}, honest={b:.4f}, Δ={b-a:+.4f}")

    print(f"\nElapsed: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
