"""Compare 3 HMA computation modes:
  1. LOOKAHEAD — closes[idx_containing_entry_ms]  (uses bar's FINAL close — future!)
  2. INTRADAY — closes[0..closed_idx] + current_1m_close at entry_ms  (live PineScript-style)
  3. HONEST   — closes[0..closed_idx], use HMA from last closed bar only

INTRADAY uses real-time info available at entry_fill_ms — no peek into future.
"""
from __future__ import annotations
import csv
import pathlib
import sys
import time
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import KFold

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


def compute_intraday_hma(rows_1m, bars, entry_ms_array, tf_name, L):
    """INTRADAY: use closes of all closed HTF bars + current 1m close as 'partial bar close'."""
    bar_arr = bars[tf_name]
    tf_ms = TF_SPECS[tf_name]
    ts_arr = bar_arr[:, 0].astype(np.int64)
    closes_htf = bar_arr[:, 4]

    ts_1m = rows_1m[:, 0].astype(np.int64)
    closes_1m = rows_1m[:, 4]

    n = len(entry_ms_array)
    out = np.full(n, np.nan)
    if L >= len(closes_htf): return out

    for i, entry_ms in enumerate(entry_ms_array):
        if entry_ms <= 0: continue

        # Last fully closed bar idx: open + tf_ms <= entry_ms ⟺ open <= entry_ms - tf_ms
        closed_idx = int(np.searchsorted(ts_arr, entry_ms - tf_ms, side="right") - 1)
        if closed_idx < L - 2: continue  # need enough history

        # Current 1m close at entry_ms
        i_1m = int(np.searchsorted(ts_1m, entry_ms, side="right") - 1)
        if i_1m < 0: continue
        current_price = closes_1m[i_1m]

        # Build series: all closed closes + current partial-bar close
        series = np.concatenate([closes_htf[:closed_idx+1], [current_price]])
        hma_arr = hma_np(series, L)
        hma_val = hma_arr[-1]
        if not np.isfinite(hma_val) or abs(hma_val) < 1e-9: continue

        out[i] = (current_price - hma_val) / hma_val * 100

    return out


def compute_honest_hma(rows_1m, bars, entry_ms_array, tf_name, L):
    """HONEST: HMA from LAST CLOSED bar only (no partial bar update)."""
    bar_arr = bars[tf_name]
    tf_ms = TF_SPECS[tf_name]
    ts_arr = bar_arr[:, 0].astype(np.int64)
    closes_htf = bar_arr[:, 4]

    ts_1m = rows_1m[:, 0].astype(np.int64)
    closes_1m = rows_1m[:, 4]

    n = len(entry_ms_array)
    out = np.full(n, np.nan)
    if L >= len(closes_htf): return out
    hma_arr = hma_np(closes_htf, L)

    valid_event = entry_ms_array > 0
    closed_idx = np.full(n, -1, dtype=np.int64)
    if valid_event.any():
        cutoff = entry_ms_array[valid_event] - tf_ms
        closed_idx[valid_event] = np.searchsorted(ts_arr, cutoff, side="right") - 1
    valid = (closed_idx >= 0) & valid_event

    hma_val = np.full(n, np.nan)
    hma_val[valid] = hma_arr[closed_idx[valid]]

    idx_1m = np.full(n, -1, dtype=np.int64)
    if valid_event.any():
        idx_1m[valid_event] = np.searchsorted(ts_1m, entry_ms_array[valid_event], side="right") - 1
    valid_1m = (idx_1m >= 0) & valid_event

    price_now = np.full(n, np.nan)
    price_now[valid_1m] = closes_1m[idx_1m[valid_1m]]

    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(
            np.abs(hma_val) > 1e-9,
            (price_now - hma_val) / hma_val * 100, np.nan)
    return out


def main():
    t0 = time.time()
    print("=" * 72)
    print("INTRADAY HMA check — partial-bar update at entry_ms (PineScript-style)")
    print("=" * 72)

    df = pd.read_parquet(CURRENT_FEATS)
    df_v = df[df.fill_touched & df.r_pct_pass].reset_index(drop=True)
    print(f"viable events: {len(df_v):,}")

    intraday = {col: np.full(len(df_v), np.nan) for col in HMA_COLS}
    honest = {col: np.full(len(df_v), np.nan) for col in HMA_COLS}

    for asset, csv_path in [("BTC", BTC_CSV), ("ETH", ETH_CSV)]:
        print(f"\n[{asset}] loading 1m + aggregating...")
        rows_1m = load_1m(csv_path)
        bars = aggregate_all_tfs(rows_1m)
        mask = (df_v.asset == asset).to_numpy()
        entry_ms_arr = df_v.loc[mask, "entry_fill_ms"].to_numpy(dtype=np.int64)
        print(f"  events: {mask.sum():,}")

        for (tf, L) in PICKED_HMA:
            col = f"hma_{tf}_{L}_dist_pct"
            intraday[col][mask] = compute_intraday_hma(rows_1m, bars, entry_ms_arr, tf, L)
            honest[col][mask]  = compute_honest_hma(rows_1m, bars, entry_ms_arr, tf, L)

    df_intra = pd.DataFrame(intraday)
    df_honest = pd.DataFrame(honest)

    print(f"\n[Build done {time.time()-t0:.1f}s] Comparing correlations vs lookahead...")
    print(f"{'feature':<25} {'corr(lookahead,intraday)':>26} {'corr(lookahead,honest)':>24}")
    for col in HMA_COLS:
        lh = df_v[col].to_numpy()
        ir = df_intra[col].to_numpy()
        hn = df_honest[col].to_numpy()
        m_ir = ~(np.isnan(lh) | np.isnan(ir))
        m_hn = ~(np.isnan(lh) | np.isnan(hn))
        c_ir = np.corrcoef(lh[m_ir], ir[m_ir])[0,1] if m_ir.sum() > 100 else np.nan
        c_hn = np.corrcoef(lh[m_hn], hn[m_hn])[0,1] if m_hn.sum() > 100 else np.nan
        marker = " 🎯" if c_ir > 0.95 else ""
        print(f"  {col:<25} {c_ir:>+24.4f} {c_hn:>+22.4f}{marker}")

    # Train + compare 3 modes
    print("\nTraining 3 models and computing CV AUC...")
    y = df_v["hit_RR_20"].to_numpy()

    X_look = df_v[ALL_FEATS].to_numpy(dtype=np.float32)
    X_intra = pd.concat([df_v[WAIT_COLS].reset_index(drop=True),
                          df_intra.reset_index(drop=True)], axis=1)[ALL_FEATS].to_numpy(dtype=np.float32)
    X_hon = pd.concat([df_v[WAIT_COLS].reset_index(drop=True),
                        df_honest.reset_index(drop=True)], axis=1)[ALL_FEATS].to_numpy(dtype=np.float32)

    valid = (~np.isnan(X_look).any(axis=1)) & (~np.isnan(X_intra).any(axis=1)) & (~np.isnan(X_hon).any(axis=1))
    print(f"  consistent valid: {valid.sum():,}")
    X_look = X_look[valid]; X_intra = X_intra[valid]; X_hon = X_hon[valid]; y = y[valid]

    def hgb():
        return HistGradientBoostingClassifier(
            learning_rate=0.05, max_iter=300, max_leaf_nodes=31,
            min_samples_leaf=40, l2_regularization=0.1, random_state=42)

    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    auc_look, auc_intra, auc_hon = [], [], []
    for fold, (tr, te) in enumerate(kf.split(X_look)):
        m = hgb(); m.fit(X_look[tr], y[tr])
        auc_look.append(roc_auc_score(y[te], m.predict_proba(X_look[te])[:, 1]))
        m = hgb(); m.fit(X_intra[tr], y[tr])
        auc_intra.append(roc_auc_score(y[te], m.predict_proba(X_intra[te])[:, 1]))
        m = hgb(); m.fit(X_hon[tr], y[tr])
        auc_hon.append(roc_auc_score(y[te], m.predict_proba(X_hon[te])[:, 1]))
        print(f"  fold {fold}: look={auc_look[-1]:.4f}  intra={auc_intra[-1]:.4f}  hon={auc_hon[-1]:.4f}")

    print("\n" + "=" * 72)
    print("RESULTS — 5-fold CV AUC")
    print("=" * 72)
    print(f"  Lookahead (peeks future):   {np.mean(auc_look):.4f} ± {np.std(auc_look):.4f}  ← cheating")
    print(f"  INTRADAY (partial bar):     {np.mean(auc_intra):.4f} ± {np.std(auc_intra):.4f}  ← honest, real-time")
    print(f"  HONEST (last closed only):  {np.mean(auc_hon):.4f} ± {np.std(auc_hon):.4f}  ← honest, stale")
    print(f"\n  Δ(intraday − honest):   {np.mean(auc_intra) - np.mean(auc_hon):+.4f}  (uplift from partial-bar info)")
    print(f"  Δ(lookahead − intraday): {np.mean(auc_look) - np.mean(auc_intra):+.4f}  (residual cheating advantage)")

    print(f"\nTotal: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
