"""STAGE 2 — Lopez de Prado microstructure features.

Per-bar features (independent of basket/patterns):
    sadf            — Supremum ADF (structural break, Ch.17)
    amihud          — |return| / volume illiquidity (Ch.19)
    vpin_proxy      — volume-synchronized informed trading proxy (Ch.19)
    roll            — Roll's implied bid-ask spread (Ch.19)
    parkinson       — Parkinson volatility estimator (high-low based, Ch.19)
    gk              — Garman-Klass volatility (OHLC-based, Ch.19)
    fd_close        — Fractional differentiation d=0.4 (Ch.5)
    fd_volume       — Fractional differentiation на volume

Trained on RAW 12h bars (4 698). Decoupled from Basket.

Output: ~/Desktop/12h-fractal-new-out/D_stage2_lopez.parquet
"""
from __future__ import annotations
import pathlib
import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller
from _lib import load_12h, OUT_DIR

# ─── Load 12h bars ─────────────────────────────────────────────
print("Loading 12h bars (raw)...")
bars = load_12h()
n = bars["n"]
o, h, l, c, v, t = bars["o"], bars["h"], bars["l"], bars["c"], bars["v"], bars["t"]
print(f"  Bars: {n}")

# ─── Feature 1: SADF (Lopez Ch.17, simplified) ────────────────
# Rolling ADF statistic как proxy для structural break / explosive trend
# Real SADF is supremum across multiple windows; simplified = rolling ADF
print("Computing SADF (rolling ADF, window=60)...")
def rolling_adf_stat(arr, window=60):
    out = np.full(len(arr), np.nan)
    for i in range(window, len(arr)):
        try:
            result = adfuller(arr[i-window:i], autolag=None, maxlag=5)
            out[i] = result[0]  # ADF test statistic
        except Exception:
            pass
    return out

log_close = np.log(c)
sadf = rolling_adf_stat(log_close, window=60)

# ─── Feature 2: Amihud illiquidity (Ch.19) ────────────────────
print("Computing Amihud illiquidity...")
log_ret = np.diff(log_close, prepend=log_close[0])
amihud_raw = np.abs(log_ret) / np.where(v > 0, v, 1)
# Rolling smoothing
amihud = pd.Series(amihud_raw).rolling(14, min_periods=5).mean().bfill().values

# ─── Feature 3: VPIN proxy (Ch.19, volume-bucketed) ───────────
# Real VPIN requires tick data; proxy = imbalance of bull/bear volume
# в rolling окне, normalised by total volume
print("Computing VPIN proxy...")
bull_v = np.where(c > o, v, 0)
bear_v = np.where(c < o, v, 0)
WIN_V = 50
vpin = np.full(n, np.nan)
for i in range(WIN_V, n):
    bv = bull_v[i-WIN_V:i].sum()
    sv = bear_v[i-WIN_V:i].sum()
    total = bv + sv
    if total > 0:
        vpin[i] = abs(bv - sv) / total

# ─── Feature 4: Roll spread (Ch.19) ────────────────────────────
# Roll's estimator: spread² = -4 × cov(Δp_t, Δp_t-1)
# negative cov → meaningful, else 0
print("Computing Roll spread...")
dp = np.diff(c, prepend=c[0])
roll = np.full(n, np.nan)
WIN_R = 30
for i in range(WIN_R, n):
    dp_window = dp[i-WIN_R:i]
    cov = np.cov(dp_window[1:], dp_window[:-1])[0, 1]
    if cov < 0:
        roll[i] = 2 * np.sqrt(-cov) / c[i]  # relative spread
    else:
        roll[i] = 0.0

# ─── Feature 5: Parkinson volatility (Ch.19) ──────────────────
# σ²_P = (1 / (4 ln 2)) × Σ (ln H/L)²
print("Computing Parkinson volatility...")
hl_log_sq = np.log(h / np.where(l > 0, l, 1)) ** 2
parkinson = pd.Series(hl_log_sq).rolling(20, min_periods=5).mean().bfill().values
parkinson = np.sqrt(parkinson / (4 * np.log(2)))

# ─── Feature 6: Garman-Klass volatility (Ch.19) ───────────────
# σ²_GK = 0.5 × (ln H/L)² − (2 ln 2 − 1) × (ln C/O)²
print("Computing Garman-Klass volatility...")
hl_sq = np.log(h / np.where(l > 0, l, 1)) ** 2
co_sq = np.log(c / np.where(o > 0, o, 1)) ** 2
gk_per_bar = 0.5 * hl_sq - (2 * np.log(2) - 1) * co_sq
gk_per_bar = np.maximum(gk_per_bar, 0)  # numerical floor
gk = pd.Series(gk_per_bar).rolling(20, min_periods=5).mean().bfill().values
gk = np.sqrt(gk)

# ─── Feature 7: Fractional differentiation d=0.4 (Ch.5) ───────
print("Computing fractional differentiation (d=0.4)...")
def frac_diff_weights(d, size):
    """Lopez Ch.5: weights for fractional differentiation."""
    w = [1.0]
    for k in range(1, size):
        w_k = -w[-1] * (d - k + 1) / k
        w.append(w_k)
    return np.array(w[::-1])

D_FRAC = 0.4
THRESH = 1e-5
# Determine truncation
test_w = frac_diff_weights(D_FRAC, 1000)
# Keep weights where |w| > THRESH
cumsum_abs = np.cumsum(np.abs(test_w[::-1]))[::-1]
trunc = int(np.argmax(np.abs(test_w) < THRESH))
if trunc == 0: trunc = 100
weights = frac_diff_weights(D_FRAC, trunc)
print(f"  Truncation: {trunc} weights")

def frac_diff(series, weights):
    out = np.full(len(series), np.nan)
    L = len(weights)
    for i in range(L, len(series)):
        out[i] = np.dot(weights, series[i-L+1:i+1])
    return out

fd_close = frac_diff(np.log(c), weights)
fd_volume = frac_diff(np.log(np.where(v > 0, v, 1)), weights)

# ─── Build output DataFrame ────────────────────────────────────
features_df = pd.DataFrame({
    "bar_idx": np.arange(n),
    "ts_ms": t,
    "sadf": sadf,
    "amihud": amihud,
    "vpin": vpin,
    "roll": roll,
    "parkinson": parkinson,
    "gk": gk,
    "fd_close": fd_close,
    "fd_volume": fd_volume,
})

# ─── Stats ─────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("FEATURE STATISTICS")
print("=" * 70)
print(features_df.describe().round(4).to_string())

# Correlation check
print("\n" + "=" * 70)
print("FEATURE CORRELATIONS")
print("=" * 70)
feat_cols = ["sadf", "amihud", "vpin", "roll", "parkinson", "gk", "fd_close", "fd_volume"]
corr = features_df[feat_cols].corr()
print(corr.round(3).to_string())

# ─── Save ──────────────────────────────────────────────────────
out = OUT_DIR / "D_stage2_lopez.parquet"
features_df.to_parquet(out, index=False)
print(f"\nSaved: {out}")

# Diagnostic: how many bars have valid data per feature
print("\n" + "=" * 70)
print("VALID BAR COUNTS")
print("=" * 70)
for col in feat_cols:
    valid = features_df[col].notna().sum()
    print(f"  {col:<12}: {valid:>4}/{n} = {100*valid/n:.1f}%")
