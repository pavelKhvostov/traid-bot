"""ViC Volume Heatmap — тепловая карта объёма по price levels.

Для каждой 12h свечи (full 6y BTC):
1. Берём её LTF (7m) sub-bars
2. Distribute volume by close price → price bins (0.1% log-scale step)
3. Накопить per-candle vector → 2D matrix (time × price)
4. Plot heatmap with log y-scale

Single combined volume (без bull/bear split — level это "fuzzy block",
поддержка или сопротивление зависит от текущей price relative to level).

Output: PNG в ~/Desktop/vic-heatmap-6y.png + top hot bands.
"""
from __future__ import annotations
import math, os, sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm

sys.path.insert(0, str(Path.home() / "smc-lib" / "prediction-algo"))
from data import load_btc_1m
from resample import resample_one


def main():
    print("[1/5] Loading BTC 1m (6y)...")
    df_1m = load_btc_1m(start="2020-05-01", end="2026-06-01")
    print(f"  rows: {len(df_1m):,}")

    # 12h candles (Monday-anchored except 3D)
    print("[2/5] Resampling to 12h + 7m (LTF for ViC)...")
    df_12h = resample_one(df_1m, "12h", df_1m.index[-1] + pd.Timedelta(minutes=1))
    print(f"  12h candles: {len(df_12h):,}")

    # Pre-bin price space (log scale)
    # Range from observed min to max
    p_min = float(df_1m["low"].min())
    p_max = float(df_1m["high"].max())
    print(f"  price range: ${p_min:.0f} → ${p_max:.0f}")

    PCT_STEP = 0.001  # 0.1% per bin
    log_min = math.log(p_min * 0.99)
    log_max = math.log(p_max * 1.01)
    log_step = math.log(1 + PCT_STEP)
    n_bins = int(math.ceil((log_max - log_min) / log_step))
    print(f"  price bins (0.1% step, log): {n_bins:,}")

    bin_edges_log = log_min + np.arange(n_bins + 1) * log_step
    bin_edges = np.exp(bin_edges_log)

    print("[3/5] Distribute 7m volume into price bins per 12h candle...")
    # For each 12h candle: find 7m bars within its range, distribute by close price
    matrix = np.zeros((len(df_12h), n_bins), dtype=np.float32)
    # Group 1m → 7m
    df_7m = resample_one(df_1m, "12h" if False else None, None) if False else None  # skip
    # Use 1m direct grouping for simplicity (1m → bin)
    # Faster: vectorize
    arr_ts = df_1m.index.astype("int64").values  # nanoseconds
    arr_close = df_1m["close"].values
    arr_vol = df_1m["volume"].values
    candle_ts = df_12h.index.astype("int64").values
    TF12_NS = 12 * 3600 * 10**9

    # Compute bin indices for all 1m closes
    log_close = np.log(arr_close)
    bin_idx = np.floor((log_close - log_min) / log_step).astype(np.int32)
    bin_idx = np.clip(bin_idx, 0, n_bins - 1)

    # Assign 1m → 12h candle index (assumes 12h ts sorted)
    candle_idx_for_1m = np.searchsorted(candle_ts, arr_ts, side='right') - 1
    valid = (candle_idx_for_1m >= 0) & (candle_idx_for_1m < len(df_12h))

    # Aggregate
    print(f"  aggregating {valid.sum():,} 1m bars into {len(df_12h):,} × {n_bins:,} matrix...")
    np.add.at(matrix, (candle_idx_for_1m[valid], bin_idx[valid]), arr_vol[valid])
    print(f"  total volume placed: {matrix.sum():.2e}")

    print("[4/5] Visualize heatmap...")
    fig, ax = plt.subplots(figsize=(20, 10))

    # Transpose: rows = price (top→bottom = high→low), cols = time
    mat = matrix.T  # shape (n_bins, n_candles)
    # Mask zeros for log colormap
    mat_masked = np.ma.masked_where(mat == 0, mat)

    # Time axis: 12h candle timestamps
    time_axis = df_12h.index
    # Y axis ticks: log-spaced price labels
    extent = [0, len(df_12h), 0, n_bins]

    im = ax.imshow(mat_masked, aspect="auto", origin="lower",
                    norm=LogNorm(vmin=max(1, mat[mat>0].min()), vmax=mat.max()),
                    cmap="inferno",
                    extent=extent)
    cbar = plt.colorbar(im, ax=ax, label="Volume (log)")

    # Y-axis labels — price values (every 10% of bins)
    y_ticks = np.arange(0, n_bins, n_bins // 15)
    y_labels = [f"${bin_edges[i]:.0f}" for i in y_ticks]
    ax.set_yticks(y_ticks); ax.set_yticklabels(y_labels)

    # X-axis labels — dates (every 100 bars ≈ 50 days)
    x_ticks = np.arange(0, len(df_12h), 250)
    x_labels = [time_axis[i].strftime("%Y-%m") for i in x_ticks]
    ax.set_xticks(x_ticks); ax.set_xticklabels(x_labels, rotation=45)

    ax.set_title(f"ViC Volume Heatmap — BTC 12h, full 6y, 0.1% price bins (log)\n"
                 f"{len(df_12h):,} candles × {n_bins:,} bins, total vol={mat.sum():.2e}")
    ax.set_xlabel("Time"); ax.set_ylabel("Price")
    plt.tight_layout()

    out = Path.home() / "Desktop" / "vic-heatmap-6y.png"
    plt.savefig(out, dpi=120, bbox_inches="tight")
    print(f"  → {out}")

    print("[5/5] Top hot bands (price levels with highest cumulative volume)...")
    bin_vol = mat.sum(axis=1)
    top_idx = np.argsort(-bin_vol)[:20]
    print(f"\n  {'Rank':<5}{'Price':<12}{'Volume (Σ)':<15}{'% of total':<10}")
    for r, i in enumerate(top_idx, 1):
        center = (bin_edges[i] + bin_edges[i+1]) / 2
        pct = bin_vol[i] / mat.sum() * 100
        print(f"  {r:<5}${center:<11.0f}{bin_vol[i]:<15.2e}{pct:<10.3f}%")

    # Save bin-volume profile
    bp = pd.DataFrame({
        "bin_idx": np.arange(n_bins),
        "price_lo": bin_edges[:-1],
        "price_hi": bin_edges[1:],
        "volume_sum": bin_vol,
    })
    bp.to_csv(Path.home() / "Desktop" / "vic-heatmap-volume-profile.csv", index=False)
    print(f"\nBin profile → ~/Desktop/vic-heatmap-volume-profile.csv")


if __name__ == "__main__":
    main()
