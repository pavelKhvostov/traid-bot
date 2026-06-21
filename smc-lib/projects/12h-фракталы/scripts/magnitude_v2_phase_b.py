"""Phase B — Magnitude ML v2.

Расширение Phase A (26 features) → новые 8 фич из локальных 1m + funding history:

NEW features (calculated locally, без API):
    cvd_window         — Cumulative Volume Delta в окне [i-2.open, i.close]
    cvd_divergence     — корреляция price-vs-CVD в окне (есть ли divergence)
    vol_z_score        — z-score 12h volume vs rolling 50
    rv_3d              — realized vol 3 дня (~6 12h bars)
    rv_7d              — realized vol 7 дней (~14 12h bars)
    rv_ratio           — rv_24h / rv_7d (expansion vs trend)
    funding_std_24h    — стандартное отклонение funding за 24h (3 records)
    bars_since_basket  — расстояние до предыдущего basket fire (regime continuity)

Models / CV same as Phase A:
    HistGradientBoosting + TimeSeriesSplit + embargo=14
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
from _lib import load_12h, load_1m, OUT_DIR, load_baseline, match_pivots, TF12, MS_M

ALL_CODES = ["B1C1","B1C2","B1C3","B1C4","B1C5","B1C6",
             "B2C1","B2C2","B3C1","B4C1","B4C2","B5C1","B8C1","B9C1"]
EMBARGO_BARS = 14
N_SPLITS = 5

# ─── Load data ─────────────────────────────────────────────────
print("Loading 12h bars + Basket events...")
bars = load_12h()
pmap = match_pivots(bars, load_baseline())
events = pd.read_parquet(OUT_DIR / "events_with_funding_confluent.parquet")
events["in_basket"] = events.apply(
    lambda r: (int(r["bar_idx"]), r["direction"]) in pmap, axis=1)
basket = events[events["in_basket"]].sort_values("ts_ms").reset_index(drop=True)
basket["confirmed"] = basket.apply(
    lambda r: pmap[(int(r["bar_idx"]), r["direction"])][0], axis=1)
print(f"  Basket events: {len(basket)}")

# ─── Compute CVD on 1m → 12h ───────────────────────────────────
print("Computing CVD on 1m data...")
rows = load_1m()
ts1m = np.array([r[0] for r in rows], dtype=np.int64)
o1m = np.array([r[1] for r in rows])
c1m = np.array([r[4] for r in rows])
v1m = np.array([r[5] for r in rows])
delta_1m = np.where(c1m > o1m, v1m, np.where(c1m < o1m, -v1m, 0))
cvd_1m = np.cumsum(delta_1m)

# CVD at boundaries of each 12h bar
t12 = bars["t"]; n12 = bars["n"]
cvd_at_close = np.zeros(n12)
for i in range(n12):
    close_ms = int(t12[i] + TF12)
    j = int(np.searchsorted(ts1m, close_ms, side="right")) - 1
    if j >= 0:
        cvd_at_close[i] = cvd_1m[j]

# CVD change per 12h bar
cvd_delta_12h = np.diff(cvd_at_close, prepend=cvd_at_close[0])

# CVD divergence: correlation of price change vs CVD change over last 4 bars
def cvd_divergence(i, window=4):
    if i < window: return 0.0
    p = bars["c"][i-window:i]
    cvd = cvd_at_close[i-window:i]
    if len(p) < 2: return 0.0
    if np.std(p) == 0 or np.std(cvd) == 0: return 0.0
    return np.corrcoef(p, cvd)[0, 1]

# ─── Volume z-score (rolling 50) ──────────────────────────────
v12 = bars["v"]
v_mean = pd.Series(v12).rolling(50, min_periods=20).mean().bfill().values
v_std = pd.Series(v12).rolling(50, min_periods=20).std().bfill().values
vol_z = (v12 - v_mean) / np.where(v_std > 0, v_std, 1.0)

# ─── Realized vol multi-window ────────────────────────────────
log_ret = np.diff(np.log(bars["c"]), prepend=np.log(bars["c"][0]))
def rolling_std(arr, window):
    out = np.zeros(len(arr))
    for i in range(window, len(arr)):
        out[i] = np.std(arr[i-window:i])
    return out

rv_24h = rolling_std(log_ret, 2) * np.sqrt(2 * 365)
rv_3d = rolling_std(log_ret, 6) * np.sqrt(2 * 365)
rv_7d = rolling_std(log_ret, 14) * np.sqrt(2 * 365)
rv_ratio = rv_24h / np.where(rv_7d > 0, rv_7d, 1)

# ─── ATR ──────────────────────────────────────────────────────
h12, l12, c12 = bars["h"], bars["l"], bars["c"]
tr = np.zeros(n12)
for i in range(1, n12):
    tr[i] = max(h12[i]-l12[i], abs(h12[i]-c12[i-1]), abs(l12[i]-c12[i-1]))
atr14 = np.zeros(n12)
for i in range(14, n12):
    atr14[i] = tr[i-14:i].mean()
atr_pct = atr14 / c12

# ─── Funding stability (rolling std of funding over 3 records ≈ 24h) ──
funding_cache = pathlib.Path.home() / "Desktop/btc_funding_binance.parquet"
fdf = pd.read_parquet(funding_cache)
fdf = fdf.sort_values("fundingTime").reset_index(drop=True)
funding_ts = fdf["fundingTime"].values
funding_rate = fdf["fundingRate"].values

def funding_std_at(close_ms, window=3):
    """Std of funding over last `window` records before close_ms."""
    j = int(np.searchsorted(funding_ts, close_ms, side="right"))
    if j < window: return 0.0
    return np.std(funding_rate[j-window:j])

# ─── Bars since last basket fire ──────────────────────────────
basket_bars = set(int(r) for r in basket["bar_idx"])
def bars_since_last(i):
    for d in range(1, 30):
        if (i - d) in basket_bars: return d
    return 30

# ─── Build features ────────────────────────────────────────────
print("Building feature matrix...")

# Existing Phase A features
for c in ALL_CODES:
    basket[f"fire_{c}"] = basket["blocks"].apply(
        lambda s: int(c in (s.split(",") if s else [])))

basket["funding_bps"] = basket["funding"] * 10_000
basket["funding_signed"] = basket.apply(
    lambda r: r["funding_bps"] if r["direction"] == "short" else -r["funding_bps"],
    axis=1)
basket["dir_short"] = (basket["direction"] == "short").astype(int)
basket["dt"] = pd.to_datetime(basket["ts_ms"], unit="ms", utc=True)
basket["hour"] = basket["dt"].dt.hour
basket["dow"] = basket["dt"].dt.dayofweek
basket["month"] = basket["dt"].dt.month

# Map bar_idx to derived features
basket["rv_24h"] = basket["bar_idx"].map(lambda i: rv_24h[int(i)])
basket["rv_3d"] = basket["bar_idx"].map(lambda i: rv_3d[int(i)])
basket["rv_7d"] = basket["bar_idx"].map(lambda i: rv_7d[int(i)])
basket["rv_ratio"] = basket["bar_idx"].map(lambda i: rv_ratio[int(i)])
basket["atr_pct"] = basket["bar_idx"].map(lambda i: atr_pct[int(i)])
basket["vol_z"] = basket["bar_idx"].map(lambda i: vol_z[int(i)])

# NEW Phase B features
basket["cvd_delta_12h"] = basket["bar_idx"].map(lambda i: cvd_delta_12h[int(i)])
# Normalise CVD by typical volume to avoid scale issues
basket["cvd_norm"] = basket["cvd_delta_12h"] / np.where(v12.mean() > 0, v12.mean(), 1)
basket["cvd_div"] = basket["bar_idx"].map(lambda i: cvd_divergence(int(i)))
basket["funding_std"] = basket["ts_ms"].map(
    lambda ts: funding_std_at(int(ts + TF12))) * 10_000  # to bps
basket["bars_since_basket"] = basket["bar_idx"].map(bars_since_last)

# Interactions
TOP_B = ["B1C1", "B8C1", "B2C1", "B3C1"]
for c in TOP_B:
    basket[f"funding_x_{c}"] = basket["funding_signed"] * basket[f"fire_{c}"]
basket["funding_x_cvd"] = basket["funding_signed"] * basket["cvd_norm"]
basket["rv_x_funding"] = basket["rv_24h"] * basket["funding_signed"].abs()

basket["move_ge_3"] = (basket["move_pct"] >= 3).astype(int)
basket["move_ge_5"] = (basket["move_pct"] >= 5).astype(int)
need = ["move_pct", "funding_signed", "rv_24h", "atr_pct", "cvd_norm", "rv_ratio"]
basket = basket.dropna(subset=need).reset_index(drop=True)
print(f"  Events after dropna: {len(basket)}")

FEATURES = (
    [f"fire_{c}" for c in ALL_CODES] +
    ["funding_signed", "funding_bps", "dir_short",
     "rv_24h", "rv_3d", "rv_7d", "rv_ratio",
     "atr_pct", "vol_z",
     "cvd_norm", "cvd_div", "funding_std", "bars_since_basket",
     "hour", "dow", "month"] +
    [f"funding_x_{c}" for c in TOP_B] +
    ["funding_x_cvd", "rv_x_funding"]
)
print(f"  Phase B feature count: {len(FEATURES)} (vs Phase A: 26)")

X = basket[FEATURES].values
y_reg = basket["move_pct"].values
y_3 = basket["move_ge_3"].values
y_5 = basket["move_ge_5"].values


def cv_with_embargo(X, n_splits, embargo):
    tss = TimeSeriesSplit(n_splits=n_splits)
    for fold, (tr_idx, te_idx) in enumerate(tss.split(X)):
        if embargo > 0 and len(tr_idx) > embargo:
            tr_idx = tr_idx[:-embargo]
        yield fold, tr_idx, te_idx


def evaluate_binary(y_bin, name):
    preds_oof = np.full(len(y_bin), np.nan)
    aucs = []; aps = []
    for fold, tr, te in cv_with_embargo(X, N_SPLITS, EMBARGO_BARS):
        if y_bin[tr].sum() == 0 or y_bin[te].sum() == 0: continue
        m = HistGradientBoostingClassifier(
            max_iter=300, max_depth=4, learning_rate=0.05,
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


print("\n" + "=" * 80)
print("PHASE B — BINARY CLASSIFIERS")
print("=" * 80)
p3_oof, auc3, ap3 = evaluate_binary(y_3, "move ≥ 3% (P_3)")
p5_oof, auc5, ap5 = evaluate_binary(y_5, "move ≥ 5% (P_5)")

# Comparison vs Phase A
print("\n" + "=" * 80)
print("PHASE A → PHASE B comparison")
print("=" * 80)
print(f"  P_3 AUC:    Phase A 0.633   →   Phase B {auc3:.3f}   "
      f"(Δ {auc3-0.633:+.3f})")
print(f"  P_5 AUC:    Phase A 0.602   →   Phase B {auc5:.3f}   "
      f"(Δ {auc5-0.602:+.3f})")
print(f"  P_3 AP:     Phase A 0.515   →   Phase B {ap3:.3f}   (Δ {ap3-0.515:+.3f})")
print(f"  P_5 AP:     Phase A 0.273   →   Phase B {ap5:.3f}   (Δ {ap5-0.273:+.3f})")

# Precision @ K
print("\n" + "=" * 80)
print("PRECISION @ K (Phase B)")
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

# Feature importance
print("\n" + "=" * 80)
print("FEATURE IMPORTANCE (top-15, permutation на P_3 hold-out)")
print("=" * 80)
n80 = int(len(X) * 0.8)
m_final = HistGradientBoostingClassifier(
    max_iter=300, max_depth=4, learning_rate=0.05,
    min_samples_leaf=10, random_state=42)
m_final.fit(X[:n80], y_3[:n80])
imp = permutation_importance(m_final, X[n80:], y_3[n80:],
                              n_repeats=10, random_state=42, n_jobs=-1)
imp_df = pd.DataFrame({
    "feature": FEATURES,
    "importance_mean": imp.importances_mean,
    "importance_std": imp.importances_std,
}).sort_values("importance_mean", ascending=False)
print(imp_df.head(15).to_string(index=False))

basket["p_3_v2"] = p3_oof
basket["p_5_v2"] = p5_oof
basket["E_pct_v2"] = 3 * basket["p_3_v2"].fillna(0) + basket["p_5_v2"].fillna(0) * 2
out = OUT_DIR / "magnitude_v2_predictions.parquet"
basket.to_parquet(out, index=False)
print(f"\nSaved: {out}")
imp_df.to_csv(OUT_DIR / "magnitude_v2_feature_importance.csv", index=False)
print(f"Saved: {OUT_DIR / 'magnitude_v2_feature_importance.csv'}")
