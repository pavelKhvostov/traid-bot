"""STAGE 0 — Regime Classifier (D-layer foundation).

3-state HMM: BULL / BEAR / RANGE.

Trained on ALL 4 698 12h bars (NO basket dependency — это invariant к нашему Basket).
Output: per-bar P(bull, bear, range) + most-likely state.

Features:
    log_return     — log(close[i] / close[i-1])
    rv_24h         — std of log_return over last 4 bars
    trend          — close vs 200-bar EMA percentage

Train: 2020-01-01 → 2024-12-31
OOS:   2025-01-01 → 2026-06-06

Output:
    ~/Desktop/12h-fractal-new-out/D_regime_states.parquet
        bar_idx · ts_ms · regime_state · p_bull · p_bear · p_range
"""
from __future__ import annotations
import pathlib
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from hmmlearn.hmm import GaussianHMM
from _lib import load_12h, OUT_DIR

# ─── Constants ─────────────────────────────────────────────────
TRAIN_END_MS = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
EMA_PERIOD = 200       # 12h bars ≈ 100 days
RV_WINDOW = 4          # 4×12h = 2 days
RANDOM_SEED = 42

# ─── Load 12h bars ─────────────────────────────────────────────
print("Loading 12h bars (raw chart, no basket dependency)...")
bars = load_12h()
n = bars["n"]
c = bars["c"]; h = bars["h"]; l = bars["l"]; t = bars["t"]
print(f"  Total bars: {n}")

# ─── Build features ────────────────────────────────────────────
print("Building regime features...")

# 1. Log returns
log_ret = np.diff(np.log(c), prepend=np.log(c[0]))

# 2. Realized vol (rolling RV_WINDOW bars)
rv = np.zeros(n)
for i in range(RV_WINDOW, n):
    rv[i] = np.std(log_ret[i-RV_WINDOW:i])

# 3. Trend: (close - EMA200) / close
ema = np.zeros(n)
ema[0] = c[0]
alpha = 2 / (EMA_PERIOD + 1)
for i in range(1, n):
    ema[i] = alpha * c[i] + (1 - alpha) * ema[i-1]
trend = (c - ema) / c

# Stack features (X shape: n × 3)
X = np.column_stack([log_ret, rv, trend])

# Mask: drop first EMA_PERIOD bars (EMA warm-up)
valid_start = EMA_PERIOD
X_valid = X[valid_start:]
print(f"  Valid bars after EMA warm-up: {len(X_valid)}")

# Train/test split
train_mask = t[valid_start:] < TRAIN_END_MS
X_train = X_valid[train_mask]
print(f"  Train bars: {train_mask.sum()}  OOS bars: {(~train_mask).sum()}")

# ─── Standardise features ─────────────────────────────────────
mean = X_train.mean(axis=0)
std = X_train.std(axis=0)
X_train_norm = (X_train - mean) / std
X_full_norm = (X_valid - mean) / std

# ─── Train HMM ─────────────────────────────────────────────────
print("\nTraining HMM (3 states, Gaussian emissions)...")
hmm = GaussianHMM(
    n_components=3,
    covariance_type="full",
    n_iter=200,
    random_state=RANDOM_SEED,
)
hmm.fit(X_train_norm)
print(f"  Log-likelihood (train): {hmm.score(X_train_norm):.2f}")
print(f"  Converged: {hmm.monitor_.converged}")

# ─── Identify states (bull / bear / range) ────────────────────
# Каждый state — distribution. Bull = positive trend mean, low RV.
# Bear = negative trend mean. Range = high RV или near-zero trend.
means = hmm.means_  # (3, 3) — mean per state per feature
print("\nState means (in standardised space):")
for s in range(3):
    print(f"  State {s}: log_ret={means[s,0]:+.3f}  rv={means[s,1]:+.3f}  trend={means[s,2]:+.3f}")

# Sort states by trend feature (column 2)
trend_means = means[:, 2]
rv_means = means[:, 1]

# Bull = highest trend; Bear = lowest trend; Range = remaining (often high rv)
bull_state = int(np.argmax(trend_means))
bear_state = int(np.argmin(trend_means))
range_state = int([s for s in range(3) if s not in (bull_state, bear_state)][0])

print(f"\nState mapping: bull={bull_state}, bear={bear_state}, range={range_state}")

# ─── Predict on FULL valid range (train + OOS) ─────────────────
log_prob, posteriors = hmm.score_samples(X_full_norm)
states = hmm.predict(X_full_norm)

# Re-map probabilities to bull/bear/range
p_bull = posteriors[:, bull_state]
p_bear = posteriors[:, bear_state]
p_range = posteriors[:, range_state]

# Map states to labels
label_map = {bull_state: "bull", bear_state: "bear", range_state: "range"}
state_labels = np.array([label_map[s] for s in states])

# ─── Build output DataFrame ────────────────────────────────────
out_df = pd.DataFrame({
    "bar_idx": np.arange(valid_start, n),
    "ts_ms": t[valid_start:],
    "regime_state": state_labels,
    "p_bull": p_bull,
    "p_bear": p_bear,
    "p_range": p_range,
    "trend_pct": trend[valid_start:] * 100,
    "rv": rv[valid_start:],
    "is_train": train_mask,
})

# ─── Stats ─────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("REGIME DISTRIBUTION")
print("=" * 70)
print("\nTrain period (2020-2024):")
train_df = out_df[out_df["is_train"]]
print(train_df["regime_state"].value_counts(normalize=True).round(3).to_string())
print("\nOOS period (2025-2026):")
oos_df = out_df[~out_df["is_train"]]
print(oos_df["regime_state"].value_counts(normalize=True).round(3).to_string())

# ─── Regime transitions per year ──────────────────────────────
out_df["year"] = pd.to_datetime(out_df["ts_ms"], unit="ms").dt.year
print("\nRegime dominance per year:")
year_regime = out_df.groupby("year")["regime_state"].value_counts(normalize=True).unstack(fill_value=0)
print(year_regime.round(2).to_string())

# ─── Move per regime — sanity check ────────────────────────────
print("\n" + "=" * 70)
print("Sanity check: realised move % by regime (next 48h max favor)")
print("=" * 70)

# Compute realised move for both sides
def max_move_long(i):
    if i + 4 >= n: return np.nan
    return (h[i+1:i+5].max() - c[i]) / c[i] * 100
def max_move_short(i):
    if i + 4 >= n: return np.nan
    return (c[i] - l[i+1:i+5].min()) / c[i] * 100

out_df["move_long"] = out_df["bar_idx"].map(lambda i: max_move_long(int(i)))
out_df["move_short"] = out_df["bar_idx"].map(lambda i: max_move_short(int(i)))

print("\nMean move %, per regime:")
print(out_df.groupby("regime_state")[["move_long", "move_short"]].mean().round(2).to_string())
print("\nMedian move %, per regime:")
print(out_df.groupby("regime_state")[["move_long", "move_short"]].median().round(2).to_string())

# ─── Save ──────────────────────────────────────────────────────
save_path = OUT_DIR / "D_regime_states.parquet"
out_df.drop(columns=["year"]).to_parquet(save_path, index=False)
print(f"\nSaved: {save_path}")
print(f"  Columns: bar_idx, ts_ms, regime_state, p_bull, p_bear, p_range, "
      f"trend_pct, rv, is_train, move_long, move_short")
