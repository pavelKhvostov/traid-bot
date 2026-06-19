"""VARIANT B — Transfer Learning с Andrey predictions.

Add Andrey's etap_173 p_hit predictions as features в наш ML head.
Retrain on OOS window 2025-01-01 → 2026-05-21 head-to-head.

Window:
    Andrey OOS: 2025-01-01 → 2026-05-21 (1029 days × 2 = 2058 12h bars? — check)
    Наш train scope: split this OOS window 70/30 → 70% train, 30% holdout

Features:
    All наши Stage 3 (38) +
    6 Andrey predictions (p_y_high_strong_{3,4,5}, p_y_low_strong_{3,4,5}) +
    3 derived (E_andrey, max_p_andrey, min_p_andrey)

Target:
    Same 6 binary: y_high_strong_3/4/5, y_low_strong_3/4/5

Comparison:
    Naked Andrey (just his p_hit) vs.
    Our v1 (no Andrey features) vs.
    Our v2 (with Andrey features)
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

ANDREY_DIR = pathlib.Path.home() / "Desktop"
N_SPLITS = 5
EMBARGO = 14

# ─── Load Andrey predictions ───────────────────────────────────
print("Loading Andrey's etap_173 predictions...")
andrey_dfs = {}
for tgt in ["y_high_strong_3", "y_high_strong_4", "y_high_strong_5",
             "y_low_strong_3", "y_low_strong_4", "y_low_strong_5"]:
    df = pd.read_csv(ANDREY_DIR / f"etap_173_pred_{tgt}.csv", parse_dates=["time"])
    df["ts_ms"] = df["time"].apply(lambda t: int(t.timestamp() * 1000))
    andrey_dfs[tgt] = df[["ts_ms", "p_hit"]].rename(columns={"p_hit": f"andrey_{tgt}"})
    print(f"  {tgt}: {len(df)} rows, ts range {df['time'].min()} → {df['time'].max()}")

# ─── Load наш Stage 3 dataset (built fresh, to ensure ALL features present) ─────
print("\nReconstructing Stage 3 feature matrix...")
bars = load_12h()
n = bars["n"]
c = bars["c"]; h = bars["h"]; l = bars["l"]; t = bars["t"]

# Load supporting data
regime = pd.read_parquet(OUT_DIR / "D_regime_states.parquet")
fires = pd.read_parquet(OUT_DIR / "D_stage1_fires.parquet")
lopez = pd.read_parquet(OUT_DIR / "D_stage2_lopez.parquet")
funding = pd.read_parquet(pathlib.Path.home() / "Desktop/btc_funding_binance.parquet")
funding["fundingTime"] = funding["fundingTime"].astype(np.int64)
funding["fundingRate"] = funding["fundingRate"].astype(float)
funding = funding.sort_values("fundingTime").reset_index(drop=True)

df = pd.DataFrame({"bar_idx": np.arange(n), "ts_ms": t})
df = df.merge(regime[["bar_idx", "p_bull", "p_bear", "p_range", "rv", "trend_pct"]],
              on="bar_idx", how="left")
df = df.merge(lopez[["bar_idx", "sadf", "amihud", "vpin", "roll",
                     "parkinson", "fd_close", "fd_volume"]],
              on="bar_idx", how="left")

# Patterns
PATTERN_WINDOW = 10
PATTERNS = sorted(fires["pattern"].unique())
pat_fired = {p: np.zeros(n, dtype=int) for p in PATTERNS}
for _, f in fires.iterrows():
    bi = int(f["breakout_idx"])
    p = f["pattern"]
    for k in range(bi, min(bi + PATTERN_WINDOW, n)):
        pat_fired[p][k] = 1
for p in PATTERNS:
    df[f"pat_{p}"] = pat_fired[p]
TIER1 = ["big_w", "db_eve_eve", "hs_bottom", "v_bottom", "barr_bottom"]
TIER2 = ["big_m", "hs_top", "v_top", "barr_top", "diamond_top"]
TIER4 = ["hs_top_busted", "triple_top_busted",
         "rect_bottom_busted", "sym_triangle_busted"]
df["tier1_count"] = sum(df[f"pat_{p}"] for p in TIER1 if f"pat_{p}" in df.columns)
df["tier2_count"] = sum(df[f"pat_{p}"] for p in TIER2 if f"pat_{p}" in df.columns)
df["tier4_count"] = sum(df[f"pat_{p}"] for p in TIER4 if f"pat_{p}" in df.columns)
df["any_long_fire"] = ((df["tier1_count"] > 0) | (df["tier4_count"] > 0)).astype(int)
df["any_short_fire"] = (df["tier2_count"] > 0).astype(int)

# Funding
fund_ts = funding["fundingTime"].values
fund_rate = funding["fundingRate"].values
TF12_MS = 12 * 60 * 60 * 1000
def fund_at(ts):
    close_ms = int(ts + TF12_MS)
    j = int(np.searchsorted(fund_ts, close_ms, side="right")) - 1
    if j < 0: return np.nan
    return fund_rate[j]
df["funding_rate"] = df["ts_ms"].map(fund_at)
df["funding_bps"] = df["funding_rate"] * 10_000

# Time
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

# ─── Merge Andrey predictions ──────────────────────────────────
print("\nMerging Andrey predictions...")
for tgt, andf in andrey_dfs.items():
    df = df.merge(andf, on="ts_ms", how="left")

# Derived Andrey features
df["andrey_E_high"] = (3 * df["andrey_y_high_strong_3"] +
                       df["andrey_y_high_strong_4"] +
                       df["andrey_y_high_strong_5"])
df["andrey_E_low"] = (3 * df["andrey_y_low_strong_3"] +
                      df["andrey_y_low_strong_4"] +
                      df["andrey_y_low_strong_5"])
df["andrey_max_p"] = df[[f"andrey_y_{s}_strong_{n}"
                          for s in ["high", "low"]
                          for n in [3, 4, 5]]].max(axis=1)

# ─── Build targets ─────────────────────────────────────────────
def fmh(i, N=4):
    if i + N >= n: return np.nan
    return (h[i+1:i+1+N].max() - c[i]) / c[i] * 100
def fml(i, N=4):
    if i + N >= n: return np.nan
    return (c[i] - l[i+1:i+1+N].min()) / c[i] * 100
df["future_high_pct"] = df["bar_idx"].map(fmh)
df["future_low_pct"] = df["bar_idx"].map(fml)
for thr in [3, 4, 5]:
    df[f"y_high_strong_{thr}"] = (df["future_high_pct"] >= thr).astype(int)
    df[f"y_low_strong_{thr}"] = (df["future_low_pct"] >= thr).astype(int)

log_ret = np.diff(np.log(c), prepend=np.log(c[0]))
df["sample_w"] = np.abs(log_ret) + 1e-3

# ─── Restrict to Andrey OOS window ─────────────────────────────
ANDREY_TS_MIN = min(andrey_dfs["y_low_strong_3"]["ts_ms"].min() for tgt in andrey_dfs)
ANDREY_TS_MAX = max(andrey_dfs["y_low_strong_3"]["ts_ms"].max() for tgt in andrey_dfs)
print(f"\nAndrey OOS window: {datetime.fromtimestamp(ANDREY_TS_MIN/1000, timezone.utc):%Y-%m-%d} → "
      f"{datetime.fromtimestamp(ANDREY_TS_MAX/1000, timezone.utc):%Y-%m-%d}")

df_oos = df[(df["ts_ms"] >= ANDREY_TS_MIN) & (df["ts_ms"] <= ANDREY_TS_MAX)].copy()
print(f"  Bars in Andrey OOS: {len(df_oos)}")

# ─── Feature lists ─────────────────────────────────────────────
FEAT_OURS = (
    ["p_bull", "p_bear", "p_range", "rv", "trend_pct"] +
    [f"pat_{p}" for p in PATTERNS] +
    ["tier1_count", "tier2_count", "tier4_count", "any_long_fire", "any_short_fire"] +
    ["sadf", "amihud", "vpin", "roll", "parkinson", "fd_close", "fd_volume"] +
    ["funding_bps", "funding_x_pbull", "funding_x_pbear"] +
    ["hour", "dow", "month"] +
    ["sadf_x_pbear", "vpin_x_short_fire", "parkinson_x_pbull", "fd_close_x_prange"]
)
FEAT_ANDREY = [f"andrey_y_{s}_strong_{n}" for s in ["high", "low"] for n in [3, 4, 5]] + \
              ["andrey_E_high", "andrey_E_low", "andrey_max_p"]

TARGETS = [f"y_high_strong_{t}" for t in [3, 4, 5]] + [f"y_low_strong_{t}" for t in [3, 4, 5]]

# Drop NaN
need = FEAT_OURS + FEAT_ANDREY + TARGETS + ["sample_w"]
clean = df_oos.dropna(subset=need).reset_index(drop=True)
print(f"  Bars after dropna: {len(clean)}")

# ─── Train 3 models per target ────────────────────────────────
def purged_kfold(n_samples, n_splits, embargo):
    fold_size = n_samples // n_splits
    for fold in range(n_splits):
        te_start = fold * fold_size
        te_end = (fold + 1) * fold_size if fold < n_splits - 1 else n_samples
        test_idx = np.arange(te_start, te_end)
        train_mask = np.ones(n_samples, dtype=bool)
        train_mask[max(0, te_start - embargo):min(n_samples, te_end + embargo)] = False
        yield fold, np.where(train_mask)[0], test_idx


def evaluate(features, label, y, W):
    X = clean[features].values
    preds = np.full(len(y), np.nan)
    aucs = []; aps = []
    for fold, tr, te in purged_kfold(len(X), N_SPLITS, EMBARGO):
        if y[tr].sum() == 0 or y[te].sum() == 0: continue
        m = HistGradientBoostingClassifier(
            max_iter=300, max_depth=4, learning_rate=0.05,
            min_samples_leaf=20, random_state=42)
        m.fit(X[tr], y[tr], sample_weight=W[tr])
        p = m.predict_proba(X[te])[:, 1]
        preds[te] = p
        aucs.append(roc_auc_score(y[te], p))
        aps.append(average_precision_score(y[te], p))
    valid = ~np.isnan(preds)
    return {
        "label": label,
        "auc_oof": roc_auc_score(y[valid], preds[valid]),
        "ap_oof": average_precision_score(y[valid], preds[valid]),
        "auc_mean": np.mean(aucs), "auc_std": np.std(aucs),
        "preds": preds,
    }


print("\n" + "=" * 95)
print("HEAD-TO-HEAD: Naked Andrey vs Our v1 vs Our v2 (with Andrey features)")
print("=" * 95)
W = clean["sample_w"].values
table_rows = []

# Andrey AUC reference (his pipeline self-reported, on FULL CV not just window)
ANDREY_REF = {
    "y_low_strong_3": 0.942, "y_low_strong_4": 0.937, "y_low_strong_5": 0.934,
    "y_high_strong_3": 0.929, "y_high_strong_4": 0.925, "y_high_strong_5": 0.916,
}

for tgt in TARGETS:
    y = clean[tgt].values
    print(f"\n=== {tgt} (pos rate {y.mean()*100:.1f}%) ===")
    # 1) Naked Andrey: только его prediction для этого target
    nake_features = [f"andrey_{tgt}"]
    r0 = evaluate(nake_features, "Andrey p_hit only", y, W)
    # 2) Our v1: только наши Stage 3 features
    r1 = evaluate(FEAT_OURS, "Ours v1 (no Andrey)", y, W)
    # 3) Our v2: наши + Andrey features
    r2 = evaluate(FEAT_OURS + FEAT_ANDREY, "Ours v2 (+ Andrey)", y, W)

    print(f"  {'Approach':<32} {'AUC OOF':>9} {'AP OOF':>8}")
    for r in [r0, r1, r2]:
        print(f"  {r['label']:<32} {r['auc_oof']:>9.3f} {r['ap_oof']:>8.3f}")
    print(f"  {'Andrey CV reference':<32} {ANDREY_REF[tgt]:>9.3f} {'—':>8}")

    table_rows.append({
        "target": tgt,
        "andrey_only": r0["auc_oof"],
        "ours_v1": r1["auc_oof"],
        "ours_v2": r2["auc_oof"],
        "andrey_ref": ANDREY_REF[tgt],
    })

# Summary
print("\n" + "=" * 95)
print("SUMMARY (AUC OOF on Andrey OOS window 2025-01 → 2026-05-21)")
print("=" * 95)
summ = pd.DataFrame(table_rows).set_index("target")
summ["delta_ref"] = (summ["ours_v2"] - summ["andrey_ref"]).round(3)
summ["delta_v1_v2"] = (summ["ours_v2"] - summ["ours_v1"]).round(3)
summ = summ.round(3)
print(summ.to_string())

mean_v1 = summ["ours_v1"].mean()
mean_v2 = summ["ours_v2"].mean()
mean_andrey = summ["andrey_only"].mean()
mean_ref = summ["andrey_ref"].mean()
print(f"\n  Mean AUC across 6 targets:")
print(f"    Andrey only (его p_hit):      {mean_andrey:.3f}")
print(f"    Ours v1 (без Andrey):         {mean_v1:.3f}")
print(f"    Ours v2 (+ Andrey features):  {mean_v2:.3f}  ← OUR FULL")
print(f"    Andrey CV reference (full):    {mean_ref:.3f}")
print(f"    Lift v2 vs v1:                 {mean_v2 - mean_v1:+.3f}")
print(f"    Gap to ref:                    {mean_v2 - mean_ref:+.3f}")

summ.to_csv(OUT_DIR / "D_variant_B_results.csv")
print(f"\nSaved: {OUT_DIR / 'D_variant_B_results.csv'}")
