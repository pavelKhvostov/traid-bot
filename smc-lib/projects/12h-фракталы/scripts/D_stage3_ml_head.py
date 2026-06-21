"""STAGE 3 — Feature Engineering + ML Head Training.

Train на ALL 4 698 bars (decoupled от Basket). Predict 6 magnitude targets
(Andrey-style): y_high/low_strong_{3,4,5} — будет ли N% move в ожидаемом
направлении за 48h после close.

Features (per-bar):
    Stage 0 — 5  : p_bull, p_bear, p_range, rv, trend_pct
    Stage 1 — 14 : per-pattern fired in window [i-9, i] (binary)
    Stage 1 — 3  : count Tier 1 fires, Tier 2 fires, Tier 4 (busted) fires
    Stage 2 — 7  : sadf, amihud, vpin, roll, parkinson, fd_close, fd_volume
    Funding — 3  : funding_bps, funding_x_pbull, funding_x_pbear
    Time   — 3  : hour, dow, month
    Inter. — 5  : sadf × p_bear, vpin × any_short_fire, gk-like × p_bull,
                  fd_close × p_range, parkinson × p_bull
Total: ~40 features.

CV: Purged K-Fold (5 splits) + embargo=14 (Lopez Ch.7)
Sample weights: |log_return| (Ch.4)
Model: HistGradientBoostingClassifier per target × 6
"""
from __future__ import annotations
import pathlib
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score, average_precision_score
from sklearn.inspection import permutation_importance
from _lib import load_12h, OUT_DIR

# ─── Constants ─────────────────────────────────────────────────
PATTERN_WINDOW = 10        # ловим pattern если стрельнул в [i-9, i]
N_SPLITS = 5
EMBARGO = 14
FUTURE_HORIZON = 4         # 4×12h = 48h

# ─── Load data ─────────────────────────────────────────────────
print("Loading all stages...")
bars = load_12h()
n = bars["n"]
c = bars["c"]; h = bars["h"]; l = bars["l"]; t = bars["t"]

regime = pd.read_parquet(OUT_DIR / "D_regime_states.parquet")
fires = pd.read_parquet(OUT_DIR / "D_stage1_fires.parquet")
lopez = pd.read_parquet(OUT_DIR / "D_stage2_lopez.parquet")
funding = pd.read_parquet(pathlib.Path.home() / "Desktop/btc_funding_binance.parquet")
funding["fundingTime"] = funding["fundingTime"].astype(np.int64)
funding["fundingRate"] = funding["fundingRate"].astype(float)
funding = funding.sort_values("fundingTime").reset_index(drop=True)

print(f"  bars: {n}, regime: {len(regime)}, fires: {len(fires)}, "
      f"lopez: {len(lopez)}, funding: {len(funding)}")

# ─── Build per-bar feature matrix ──────────────────────────────
print("\nBuilding feature matrix (per-bar)...")

# Start with all bars indexed
df = pd.DataFrame({"bar_idx": np.arange(n), "ts_ms": t})

# Stage 0 features
df = df.merge(regime[["bar_idx", "p_bull", "p_bear", "p_range", "rv", "trend_pct"]],
              on="bar_idx", how="left")

# Stage 2 features
df = df.merge(lopez[["bar_idx", "sadf", "amihud", "vpin", "roll",
                     "parkinson", "fd_close", "fd_volume"]],
              on="bar_idx", how="left")

# Stage 1 pattern fires: per-pattern binary "fired в окне [i-9, i]"
PATTERNS = sorted(fires["pattern"].unique())
print(f"  Patterns: {len(PATTERNS)}: {PATTERNS}")
pat_fired = {p: np.zeros(n, dtype=int) for p in PATTERNS}
for _, f in fires.iterrows():
    bi = int(f["breakout_idx"])
    p = f["pattern"]
    for k in range(bi, min(bi + PATTERN_WINDOW, n)):
        pat_fired[p][k] = 1
for p in PATTERNS:
    df[f"pat_{p}"] = pat_fired[p]

# Tier aggregates
TIER1_LONG = ["big_w", "db_eve_eve", "hs_bottom", "v_bottom", "barr_bottom"]
TIER2_SHORT = ["big_m", "hs_top", "v_top", "barr_top", "diamond_top"]
TIER4_BUSTED = ["hs_top_busted", "triple_top_busted",
                "rect_bottom_busted", "sym_triangle_busted"]

df["tier1_count"] = sum(df[f"pat_{p}"] for p in TIER1_LONG if f"pat_{p}" in df.columns)
df["tier2_count"] = sum(df[f"pat_{p}"] for p in TIER2_SHORT if f"pat_{p}" in df.columns)
df["tier4_count"] = sum(df[f"pat_{p}"] for p in TIER4_BUSTED if f"pat_{p}" in df.columns)
df["any_long_fire"] = ((df["tier1_count"] > 0) | (df["tier4_count"] > 0)).astype(int)
df["any_short_fire"] = (df["tier2_count"] > 0).astype(int)

# Funding (last record ≤ bar close)
fund_ts = funding["fundingTime"].values
fund_rate = funding["fundingRate"].values
TF12_MS = 12 * 60 * 60 * 1000
def fund_at(ts_open):
    close_ms = int(ts_open + TF12_MS)
    j = int(np.searchsorted(fund_ts, close_ms, side="right")) - 1
    if j < 0: return np.nan
    return fund_rate[j]
df["funding_rate"] = df["ts_ms"].map(fund_at)
df["funding_bps"] = df["funding_rate"] * 10_000

# Time features
df["dt"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
df["hour"] = df["dt"].dt.hour
df["dow"] = df["dt"].dt.dayofweek
df["month"] = df["dt"].dt.month

# Interactions
df["sadf_x_pbear"] = df["sadf"] * df["p_bear"]
df["vpin_x_short_fire"] = df["vpin"] * df["any_short_fire"]
df["parkinson_x_pbull"] = df["parkinson"] * df["p_bull"]
df["fd_close_x_prange"] = df["fd_close"] * df["p_range"]
df["funding_x_pbull"] = df["funding_bps"] * df["p_bull"]
df["funding_x_pbear"] = df["funding_bps"] * df["p_bear"]

# ─── Build targets (6 binary) ──────────────────────────────────
print("Building targets (6 binary thresholds)...")
log_ret = np.diff(np.log(c), prepend=np.log(c[0]))

def future_max_high(i, N=FUTURE_HORIZON):
    if i + N >= n: return np.nan
    return (h[i+1:i+1+N].max() - c[i]) / c[i] * 100
def future_max_low(i, N=FUTURE_HORIZON):
    if i + N >= n: return np.nan
    return (c[i] - l[i+1:i+1+N].min()) / c[i] * 100

df["future_high_pct"] = df["bar_idx"].map(future_max_high)
df["future_low_pct"] = df["bar_idx"].map(future_max_low)
for thr in [3, 4, 5]:
    df[f"y_high_strong_{thr}"] = (df["future_high_pct"] >= thr).astype(int)
    df[f"y_low_strong_{thr}"] = (df["future_low_pct"] >= thr).astype(int)

# Sample weights: |log_return| (Lopez Ch.4 simplified)
df["sample_w"] = np.abs(log_ret) + 1e-3

# Drop NaN
FEATURES = (
    ["p_bull", "p_bear", "p_range", "rv", "trend_pct"] +
    [f"pat_{p}" for p in PATTERNS] +
    ["tier1_count", "tier2_count", "tier4_count", "any_long_fire", "any_short_fire"] +
    ["sadf", "amihud", "vpin", "roll", "parkinson", "fd_close", "fd_volume"] +
    ["funding_bps", "funding_x_pbull", "funding_x_pbear"] +
    ["hour", "dow", "month"] +
    ["sadf_x_pbear", "vpin_x_short_fire", "parkinson_x_pbull", "fd_close_x_prange"]
)
TARGETS = [f"y_high_strong_{t}" for t in [3, 4, 5]] + [f"y_low_strong_{t}" for t in [3, 4, 5]]

need = FEATURES + TARGETS + ["sample_w"]
clean = df.dropna(subset=need).reset_index(drop=True)
print(f"  Bars with valid features+targets: {len(clean)}/{n}")
print(f"  Feature count: {len(FEATURES)}")

# ─── Purged K-Fold with embargo (Lopez Ch.7) ───────────────────
def purged_kfold(n_samples, n_splits, embargo):
    """TimeSeriesSplit-like with embargo around test set."""
    fold_size = n_samples // n_splits
    for fold in range(n_splits):
        te_start = fold * fold_size
        te_end = (fold + 1) * fold_size if fold < n_splits - 1 else n_samples
        test_idx = np.arange(te_start, te_end)
        # Train = everything except test AND embargo around test
        train_mask = np.ones(n_samples, dtype=bool)
        train_mask[max(0, te_start - embargo):min(n_samples, te_end + embargo)] = False
        train_idx = np.where(train_mask)[0]
        yield fold, train_idx, test_idx


X = clean[FEATURES].values
W = clean["sample_w"].values
results = {}

print("\n" + "=" * 90)
print("TRAINING ML HEAD (6 targets × HistGradientBoosting × Purged K-Fold)")
print("=" * 90)

for tgt in TARGETS:
    y = clean[tgt].values
    preds_oof = np.full(len(y), np.nan)
    aucs = []; aps = []
    for fold, tr, te in purged_kfold(len(X), N_SPLITS, EMBARGO):
        if y[tr].sum() == 0 or y[te].sum() == 0: continue
        m = HistGradientBoostingClassifier(
            max_iter=300, max_depth=4, learning_rate=0.05,
            min_samples_leaf=20, random_state=42)
        m.fit(X[tr], y[tr], sample_weight=W[tr])
        p = m.predict_proba(X[te])[:, 1]
        preds_oof[te] = p
        aucs.append(roc_auc_score(y[te], p))
        aps.append(average_precision_score(y[te], p))
    valid = ~np.isnan(preds_oof)
    auc_pool = roc_auc_score(y[valid], preds_oof[valid])
    ap_pool = average_precision_score(y[valid], preds_oof[valid])
    pos_rate = y.mean()
    results[tgt] = {
        "preds": preds_oof,
        "auc_oof": auc_pool, "ap_oof": ap_pool,
        "auc_mean": np.mean(aucs), "auc_std": np.std(aucs),
        "ap_mean": np.mean(aps), "ap_std": np.std(aps),
        "pos_rate": pos_rate,
    }
    print(f"\n  {tgt}:")
    print(f"    Pos rate: {pos_rate*100:.1f}%   AUC OOF: {auc_pool:.3f}   AP OOF: {ap_pool:.3f}")
    print(f"    Per-fold AUC: {np.mean(aucs):.3f} ± {np.std(aucs):.3f}")

# ─── Comparison vs Andrey ─────────────────────────────────────
print("\n" + "=" * 90)
print("COMPARISON vs Andrey etap_173")
print("=" * 90)
ANDREY = {
    "y_low_strong_3": 0.942, "y_low_strong_4": 0.937, "y_low_strong_5": 0.934,
    "y_high_strong_3": 0.929, "y_high_strong_4": 0.925, "y_high_strong_5": 0.916,
}
print(f"  {'Target':<22} {'Andrey':>8} {'Наш':>8} {'Δ':>8}")
for tgt in TARGETS:
    andrey = ANDREY.get(tgt, np.nan)
    naш = results[tgt]["auc_oof"]
    diff = naш - andrey
    sign = "🟢" if diff > 0 else "🔴" if diff < -0.02 else "🟡"
    print(f"  {tgt:<22} {andrey:>8.3f} {naш:>8.3f} {diff:>+8.3f}  {sign}")

# ─── Precision @ K (trading metric) ──────────────────────────
print("\n" + "=" * 90)
print("PRECISION @ K — top-N events by predicted probability")
print("=" * 90)
for tgt in TARGETS:
    p = results[tgt]["preds"]
    y = clean[tgt].values
    valid = ~np.isnan(p)
    pv = p[valid]; yv = y[valid]
    n_v = len(pv)
    base = yv.mean() * 100
    print(f"\n  {tgt} (baseline {base:.1f}%):")
    for k_pct in [5, 10, 20]:
        k = max(1, int(n_v * k_pct / 100))
        top_idx = np.argsort(pv)[::-1][:k]
        prec = yv[top_idx].mean() * 100
        lift = prec / base if base > 0 else 0
        print(f"    top {k_pct}% (n={k}): precision = {prec:.1f}%   lift = {lift:.2f}×")

# ─── Feature importance (one target) ──────────────────────────
print("\n" + "=" * 90)
print("FEATURE IMPORTANCE (top-20 на y_low_strong_5)")
print("=" * 90)
y_imp = clean["y_low_strong_5"].values
n80 = int(len(X) * 0.8)
m_imp = HistGradientBoostingClassifier(
    max_iter=300, max_depth=4, learning_rate=0.05,
    min_samples_leaf=20, random_state=42)
m_imp.fit(X[:n80], y_imp[:n80], sample_weight=W[:n80])
imp = permutation_importance(m_imp, X[n80:], y_imp[n80:],
                              n_repeats=8, random_state=42, n_jobs=-1)
imp_df = pd.DataFrame({
    "feature": FEATURES,
    "importance": imp.importances_mean,
    "std": imp.importances_std,
}).sort_values("importance", ascending=False)
print(imp_df.head(20).to_string(index=False))

# ─── Save ─────────────────────────────────────────────────────
for tgt, r in results.items():
    clean[f"pred_{tgt}"] = r["preds"]
out = OUT_DIR / "D_stage3_predictions.parquet"
keep_cols = ["bar_idx", "ts_ms"] + TARGETS + [f"pred_{t}" for t in TARGETS]
clean[keep_cols].to_parquet(out, index=False)
print(f"\nSaved predictions: {out}")

imp_df.to_csv(OUT_DIR / "D_stage3_feature_importance.csv", index=False)
print(f"Saved feature importance: {OUT_DIR / 'D_stage3_feature_importance.csv'}")
