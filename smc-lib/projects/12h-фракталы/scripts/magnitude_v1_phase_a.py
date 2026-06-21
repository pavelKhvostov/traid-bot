"""Phase A — Magnitude ML head v1.

Updated feature set (per empirical findings 2026-06-06):
    DROP: n_confluent, score_weighted (ρ ≈ 0 на Basket subset)
    KEEP: funding_signed, individual B-fires, on-chain proxies, time

Targets:
    move_pct       — continuous (max move in expected direction next 48h)
    move_ge_3      — binary (≥3% reached?)
    move_ge_5      — binary (≥5% reached?)

Models:
    HistGradientBoostingRegressor (quantile q=0.25, 0.50, 0.75)
    HistGradientBoostingClassifier для бинарных порогов

Cross-validation:
    Time-series 5-fold + embargo
    (Lopez de Prado canon, simplified — no Purged K-Fold)
"""
from __future__ import annotations
import pathlib
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from sklearn.ensemble import HistGradientBoostingRegressor, HistGradientBoostingClassifier
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import roc_auc_score, average_precision_score
from sklearn.inspection import permutation_importance
from _lib import load_12h, OUT_DIR, load_baseline, match_pivots

# ─── Constants ─────────────────────────────────────────────────
ALL_CODES = ["B1C1","B1C2","B1C3","B1C4","B1C5","B1C6",
             "B2C1","B2C2","B3C1","B4C1","B4C2","B5C1","B8C1","B9C1"]
EMBARGO_BARS = 14   # Lopez canon
N_SPLITS = 5

# ─── Load Basket-matched events ────────────────────────────────
print("Loading Basket events...")
bars = load_12h()
pmap = match_pivots(bars, load_baseline())
events = pd.read_parquet(OUT_DIR / "events_with_funding_confluent.parquet")
events["in_basket"] = events.apply(
    lambda r: (int(r["bar_idx"]), r["direction"]) in pmap, axis=1)
basket = events[events["in_basket"]].sort_values("ts_ms").reset_index(drop=True)
basket["confirmed"] = basket.apply(
    lambda r: pmap[(int(r["bar_idx"]), r["direction"])][0], axis=1)
print(f"  Basket events: {len(basket)}  confirmed: {basket['confirmed'].sum()}")

# ─── Build features ────────────────────────────────────────────
print("Building feature matrix...")

# 1. 14 binary B-fires
for c in ALL_CODES:
    basket[f"fire_{c}"] = basket["blocks"].apply(
        lambda s: int(c in (s.split(",") if s else [])))

# 2. funding (signed for direction)
basket["funding_bps"] = basket["funding"] * 10_000
basket["funding_signed"] = basket.apply(
    lambda r: r["funding_bps"] if r["direction"] == "short" else -r["funding_bps"],
    axis=1)

# 3. direction (binary)
basket["dir_short"] = (basket["direction"] == "short").astype(int)

# 4. Time features from ts_ms
basket["dt"] = pd.to_datetime(basket["ts_ms"], unit="ms", utc=True)
basket["hour"] = basket["dt"].dt.hour
basket["dow"] = basket["dt"].dt.dayofweek
basket["month"] = basket["dt"].dt.month

# 5. Realized volatility 24h (4 prior 12h bars) + ATR%
t12 = bars["t"]; h12 = bars["h"]; l12 = bars["l"]; c12 = bars["c"]
log_ret = np.diff(np.log(c12), prepend=np.log(c12[0]))
rv_24h = np.zeros(len(c12))
for i in range(4, len(c12)):
    rv_24h[i] = np.std(log_ret[i-4:i]) * np.sqrt(2 * 365)  # annualised
atr14 = np.zeros(len(c12))
tr = np.zeros(len(c12))
for i in range(1, len(c12)):
    tr[i] = max(h12[i]-l12[i], abs(h12[i]-c12[i-1]), abs(l12[i]-c12[i-1]))
for i in range(14, len(c12)):
    atr14[i] = tr[i-14:i].mean()
atr_pct = atr14 / c12

# Attach to events by bar_idx
basket["rv_24h"] = basket["bar_idx"].map(lambda i: rv_24h[int(i)])
basket["atr_pct"] = basket["bar_idx"].map(lambda i: atr_pct[int(i)])

# 6. Funding × top B-block fire interactions
TOP_B = ["B1C1", "B8C1", "B2C1", "B3C1"]  # top WR blocks
for c in TOP_B:
    basket[f"funding_x_{c}"] = basket["funding_signed"] * basket[f"fire_{c}"]

# ─── Targets ───────────────────────────────────────────────────
basket["move_ge_3"] = (basket["move_pct"] >= 3).astype(int)
basket["move_ge_5"] = (basket["move_pct"] >= 5).astype(int)

# Drop events with missing data
need_cols = ["move_pct", "funding_signed", "rv_24h", "atr_pct"]
basket = basket.dropna(subset=need_cols).reset_index(drop=True)
print(f"  Events after dropna: {len(basket)}")

# ─── Feature list ──────────────────────────────────────────────
FEATURES = (
    [f"fire_{c}" for c in ALL_CODES] +
    ["funding_signed", "funding_bps", "dir_short",
     "rv_24h", "atr_pct", "hour", "dow", "month"] +
    [f"funding_x_{c}" for c in TOP_B]
)
print(f"  Features ({len(FEATURES)}): {len(ALL_CODES)} fires + meta + interactions")

X = basket[FEATURES].values
y_reg = basket["move_pct"].values
y_3 = basket["move_ge_3"].values
y_5 = basket["move_ge_5"].values

# ─── Cross-validation: time-series with embargo ────────────────
def cv_with_embargo(X, n_splits, embargo):
    """TimeSeriesSplit + trim train tail by embargo."""
    tss = TimeSeriesSplit(n_splits=n_splits)
    for fold, (tr_idx, te_idx) in enumerate(tss.split(X)):
        # Embargo: drop last `embargo` train indices
        if embargo > 0 and len(tr_idx) > embargo:
            tr_idx = tr_idx[:-embargo]
        yield fold, tr_idx, te_idx


# ─── Train + evaluate ──────────────────────────────────────────
def evaluate_quantile(quantile):
    """Train HistGB quantile regressor across CV folds."""
    preds_oof = np.full(len(y_reg), np.nan)
    for fold, tr, te in cv_with_embargo(X, N_SPLITS, EMBARGO_BARS):
        m = HistGradientBoostingRegressor(
            loss="quantile", quantile=quantile,
            max_iter=200, max_depth=4, learning_rate=0.05,
            min_samples_leaf=10, random_state=42)
        m.fit(X[tr], y_reg[tr])
        preds_oof[te] = m.predict(X[te])
    return preds_oof


def evaluate_binary(y_bin, name):
    """Train HistGB classifier; return OOF preds + metrics."""
    preds_oof = np.full(len(y_bin), np.nan)
    aucs = []; aps = []
    for fold, tr, te in cv_with_embargo(X, N_SPLITS, EMBARGO_BARS):
        if y_bin[tr].sum() == 0 or y_bin[te].sum() == 0:
            continue
        m = HistGradientBoostingClassifier(
            max_iter=200, max_depth=4, learning_rate=0.05,
            min_samples_leaf=10, random_state=42)
        m.fit(X[tr], y_bin[tr])
        p = m.predict_proba(X[te])[:, 1]
        preds_oof[te] = p
        aucs.append(roc_auc_score(y_bin[te], p))
        aps.append(average_precision_score(y_bin[te], p))
    valid = ~np.isnan(preds_oof)
    auc_oof = roc_auc_score(y_bin[valid], preds_oof[valid])
    ap_oof = average_precision_score(y_bin[valid], preds_oof[valid])
    print(f"\n  {name}:")
    print(f"    AUC per-fold: mean={np.mean(aucs):.3f}  std={np.std(aucs):.3f}")
    print(f"    AP  per-fold: mean={np.mean(aps):.3f}  std={np.std(aps):.3f}")
    print(f"    AUC OOF (pooled): {auc_oof:.3f}")
    print(f"    AP  OOF (pooled): {ap_oof:.3f}")
    print(f"    Baseline pos rate: {y_bin.mean()*100:.1f}%")
    return preds_oof, auc_oof, ap_oof


def pinball_loss(y_true, y_pred, quantile):
    e = y_true - y_pred
    return np.mean(np.maximum(quantile * e, (quantile - 1) * e))


# ─── Run quantile regression ───────────────────────────────────
print("\n" + "=" * 80)
print("QUANTILE REGRESSION — predict move_pct distribution")
print("=" * 80)
for q in [0.25, 0.50, 0.75]:
    preds = evaluate_quantile(q)
    valid = ~np.isnan(preds)
    pb = pinball_loss(y_reg[valid], preds[valid], q)
    cov = np.mean(y_reg[valid] >= preds[valid])
    print(f"  q={q}: pinball_loss={pb:.3f}  coverage_actual={cov*100:.1f}% "
          f"(target {(1-q)*100:.0f}%)")

# ─── Binary classifiers ────────────────────────────────────────
print("\n" + "=" * 80)
print("BINARY CLASSIFICATION — P(move ≥ threshold)")
print("=" * 80)
p3_oof, auc3, ap3 = evaluate_binary(y_3, "move ≥ 3% (P_3)")
p5_oof, auc5, ap5 = evaluate_binary(y_5, "move ≥ 5% (P_5)")

# ─── Precision @ K (top events) ────────────────────────────────
print("\n" + "=" * 80)
print("PRECISION @ K — top events by predicted probability")
print("=" * 80)
for label, p, y in [("P_3", p3_oof, y_3), ("P_5", p5_oof, y_5)]:
    valid = ~np.isnan(p)
    pv = p[valid]; yv = y[valid]
    n = len(pv)
    for k_pct in [10, 20, 30]:
        k = max(1, int(n * k_pct / 100))
        top_idx = np.argsort(pv)[::-1][:k]
        prec = yv[top_idx].mean() * 100
        print(f"  {label} top {k_pct}% (n={k}): precision = {prec:.1f}% "
              f"(baseline {yv.mean()*100:.1f}%, lift {prec/(yv.mean()*100):.2f}×)")

# ─── Feature importance (permutation, на one fold) ────────────
print("\n" + "=" * 80)
print("FEATURE IMPORTANCE (permutation on classifier P_3)")
print("=" * 80)
m_final = HistGradientBoostingClassifier(
    max_iter=200, max_depth=4, learning_rate=0.05,
    min_samples_leaf=10, random_state=42)
# Train on first 80% for perm importance on last 20%
n80 = int(len(X) * 0.8)
m_final.fit(X[:n80], y_3[:n80])
imp = permutation_importance(m_final, X[n80:], y_3[n80:],
                              n_repeats=10, random_state=42, n_jobs=-1)

imp_df = pd.DataFrame({
    "feature": FEATURES,
    "importance_mean": imp.importances_mean,
    "importance_std": imp.importances_std,
}).sort_values("importance_mean", ascending=False)
print(imp_df.head(15).to_string(index=False))

# ─── Save outputs ──────────────────────────────────────────────
basket["p_3"] = p3_oof
basket["p_5"] = p5_oof
basket["E_pct_proxy"] = 3 * basket["p_3"].fillna(0) + basket["p_5"].fillna(0) * 2
out = OUT_DIR / "magnitude_v1_predictions.parquet"
basket.to_parquet(out, index=False)
print(f"\nSaved: {out}")

# Feature importance file
imp_df.to_csv(OUT_DIR / "magnitude_v1_feature_importance.csv", index=False)
print(f"Saved: {OUT_DIR / 'magnitude_v1_feature_importance.csv'}")

# ─── Top-15 by E_pct_proxy ─────────────────────────────────────
print("\n" + "=" * 80)
print("TOP-15 events by E_pct (predicted expected magnitude)")
print("=" * 80)
top = basket.dropna(subset=["E_pct_proxy"]).nlargest(15, "E_pct_proxy")
for _, r in top.iterrows():
    dt = r["dt"].strftime("%Y-%m-%d %H:%M")
    conf = "✓" if r["confirmed"] else "✗"
    print(f"  {dt}  {r['direction']:>5}  p_3={r['p_3']:.2f}  p_5={r['p_5']:.2f}  "
          f"E={r['E_pct_proxy']:.2f}  move_actual={r['move_pct']:.2f}%  {conf}")
