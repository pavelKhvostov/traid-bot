"""ML walk-forward CV on Bulkowski features + B1 for 2h ob_vc Enter/Skip decision.

Features:
  - 8 Bulkowski binary (4h/1d × engulf/hammer/db/busted)
  - B1_aligned
  - direction (long → 0, short → 1)

Target: y = 1 if R == +1 (WIN at TP1R), else 0 (LOSS at SL).
Untouched and timeout setups DROPPED (not actionable).

Walk-forward:
  - Sort by born_ms
  - Initial train: 2 years
  - Test: rolling 6 months
  - Re-train at each step

Outputs:
  - AUC per fold
  - WR uplift at various thresholds (0.50, 0.55, 0.60, 0.65)
  - Comparison vs B1 baseline
  - Feature importance (coefficients)
"""
import pathlib, time
import numpy as np
import pandas as pd
from datetime import datetime, timezone

from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score

t0 = time.time()
data_path = pathlib.Path(__file__).parent.parent / "data/bulkowski_features.parquet"
df = pd.read_parquet(data_path).sort_values("born_ms").reset_index(drop=True)
print(f"Loaded: {len(df):,} setups")

# Filter to touched & decisive (R != 0)
df = df[(df.touched) & (df.R.isin([-1, 1]))].reset_index(drop=True)
print(f"Touched & decisive: {len(df):,}")

# ─── Features ───────────────────────────────────────────────
FEAT_COLS = [
    "4h_engulf","4h_hammer","4h_db","4h_busted",
    "1d_engulf","1d_hammer","1d_db","1d_busted",
    "B1_aligned",
]
df["dir_short"] = (df.direction == "short").astype(int)
FEAT_COLS_FULL = FEAT_COLS + ["dir_short"]

X_all = df[FEAT_COLS_FULL].astype(float).values
y_all = (df.R == 1).astype(int).values
born_all = df.born_ms.values

print(f"\nBaseline WR (all): {y_all.mean()*100:.1f}%  N={len(y_all)}")

# ─── Walk-forward setup ────────────────────────────────────
TRAIN_YEARS = 2
TEST_MONTHS = 6
ms_per_day = 24*3600*1000
train_ms = TRAIN_YEARS * 365 * ms_per_day
test_ms = TEST_MONTHS * 30 * ms_per_day

start_ms = int(born_all.min())
end_ms = int(born_all.max())

folds = []
cursor = start_ms + train_ms
while cursor + test_ms <= end_ms + ms_per_day:
    test_end = min(cursor + test_ms, end_ms + 1)
    folds.append((start_ms, cursor, cursor, test_end))  # train[start, cursor) test[cursor, test_end)
    cursor += test_ms

print(f"Folds: {len(folds)} (train expanding from {datetime.fromtimestamp(start_ms/1000, tz=timezone.utc).date()})")

# ─── Walk-forward loop ─────────────────────────────────────
all_test_idx = []
all_test_proba = []
all_test_y = []
all_test_born = []
fold_results = []
coefs_per_fold = []

for fi, (tr_lo, tr_hi, te_lo, te_hi) in enumerate(folds):
    tr_mask = (born_all >= tr_lo) & (born_all < tr_hi)
    te_mask = (born_all >= te_lo) & (born_all < te_hi)
    Xt = X_all[tr_mask]; yt = y_all[tr_mask]
    Xs = X_all[te_mask]; ys = y_all[te_mask]
    bs = born_all[te_mask]
    if len(yt) < 100 or len(ys) < 30 or len(np.unique(yt)) < 2:
        continue

    sc = StandardScaler().fit(Xt)
    Xt_s = sc.transform(Xt); Xs_s = sc.transform(Xs)

    model = LogisticRegression(C=1.0, max_iter=1000, class_weight="balanced", random_state=42)
    model.fit(Xt_s, yt)
    p = model.predict_proba(Xs_s)[:, 1]

    auc = roc_auc_score(ys, p) if len(np.unique(ys)) > 1 else float("nan")
    base_wr = ys.mean()
    test_date = datetime.fromtimestamp(te_lo/1000, tz=timezone.utc).date()
    fold_results.append({
        "fold": fi, "test_start": str(test_date),
        "n_train": int(tr_mask.sum()), "n_test": int(te_mask.sum()),
        "auc": auc, "base_wr": base_wr,
    })
    coefs_per_fold.append(model.coef_[0])

    all_test_proba.extend(p.tolist())
    all_test_y.extend(ys.tolist())
    all_test_born.extend(bs.tolist())

# ─── Fold summary ──────────────────────────────────────────
fold_df = pd.DataFrame(fold_results)
print(f"\n{'='*80}")
print(f"WALK-FORWARD FOLDS")
print(f"{'='*80}")
print(f"{'fold':>4} {'test_start':<12} {'n_tr':>5} {'n_te':>5} {'AUC':>6} {'base_WR':>8}")
for r in fold_results:
    print(f"{r['fold']:>4} {r['test_start']:<12} {r['n_train']:>5} {r['n_test']:>5} {r['auc']:>6.3f} {r['base_wr']*100:>7.1f}%")

print(f"\nMean AUC: {fold_df.auc.mean():.3f}  Median: {fold_df.auc.median():.3f}")
print(f"Mean base WR: {fold_df.base_wr.mean()*100:.1f}%")

# ─── Aggregate OOS predictions ────────────────────────────
proba = np.array(all_test_proba)
y = np.array(all_test_y)
print(f"\nOOS combined: N={len(y)}  WR={y.mean()*100:.1f}%  AUC={roc_auc_score(y, proba):.3f}")

# ─── Threshold analysis ────────────────────────────────────
print(f"\n{'='*80}")
print(f"THRESHOLD ANALYSIS (OOS): if P(win) ≥ τ → enter, else skip")
print(f"{'='*80}")
print(f"{'τ':>6} {'N_enter':>9} {'%basket':>9} {'WR':>7} {'EV':>9} {'Σ R':>8}")
print("-"*60)
for tau in [0.40, 0.45, 0.50, 0.52, 0.55, 0.58, 0.60, 0.65, 0.70]:
    enter = proba >= tau
    n = enter.sum()
    if n < 20:
        print(f"{tau:>6.2f} {n:>9} {n/len(y)*100:>8.1f}%   {'-':>6}   {'-':>8}   {'-':>7}")
        continue
    ye = y[enter]
    wr = ye.mean()*100
    w = (ye == 1).sum(); l = (ye == 0).sum()
    print(f"{tau:>6.2f} {n:>9} {n/len(y)*100:>8.1f}% {wr:>6.1f}% {(2*wr/100)-1:>+8.3f}R {w-l:>+7}R")

# ─── Compare vs B1 baseline OOS ───────────────────────────
# Get B1 baseline on same OOS window
oos_mask = born_all >= folds[0][2] if folds else np.zeros(len(born_all), dtype=bool)
b1_oos = df[oos_mask & (df.B1_aligned)]
b1_oos = b1_oos[(b1_oos.touched) & (b1_oos.R.isin([-1, 1]))]
b1_wr = (b1_oos.R == 1).mean()*100
b1_w = (b1_oos.R == 1).sum(); b1_l = (b1_oos.R == -1).sum()
print(f"\n{'='*80}")
print(f"B1 BASELINE (same OOS window): N={len(b1_oos)}  WR={b1_wr:.1f}%  Σ={b1_w-b1_l:+}R")
print(f"{'='*80}")

# ─── Feature importance (mean coefficients) ───────────────
coefs = np.array(coefs_per_fold)
print(f"\n{'='*80}")
print(f"FEATURE IMPORTANCE (mean ± std logistic coefficient across folds)")
print(f"{'='*80}")
print(f"{'feature':<16} {'mean':>8} {'std':>7} {'stable?':>10}")
for i, f in enumerate(FEAT_COLS_FULL):
    m = coefs[:, i].mean(); s = coefs[:, i].std()
    stable = "✓" if abs(m) > s else "noisy"
    print(f"{f:<16} {m:>+8.3f} {s:>7.3f} {stable:>10}")

# ─── Build OOS DataFrame ──────────────────────────────────
oos = pd.DataFrame({
    "born_ms": all_test_born,
    "proba": all_test_proba,
    "y": all_test_y,
})
df_lookup = df[["born_ms","B1_aligned"]].drop_duplicates("born_ms").set_index("born_ms")
oos["B1"] = oos.born_ms.map(df_lookup["B1_aligned"].to_dict())

# ─── ML × B1 combination ──────────────────────────────────
print(f"\n{'='*80}")
print(f"ML × B1 COMBINATION (layered filter)")
print(f"{'='*80}")
print(f"{'τ':>6} {'mode':<14} {'N':>5} {'WR':>7} {'EV':>9} {'Σ R':>8}")
print("-"*60)
for tau in [0.50, 0.55, 0.58, 0.60]:
    for mode, mask in [
        ("ML only",   oos.proba >= tau),
        ("ML + B1",   (oos.proba >= tau) & oos.B1),
        ("ML AND/OR B1", (oos.proba >= tau) | oos.B1),
    ]:
        n = mask.sum()
        if n < 20:
            print(f"{tau:>6.2f} {mode:<14} {n:>5} {'-':>6} {'-':>8} {'-':>7}")
            continue
        ye = oos.y[mask]
        wr = ye.mean()*100
        w = (ye == 1).sum(); l = (ye == 0).sum()
        print(f"{tau:>6.2f} {mode:<14} {n:>5} {wr:>6.1f}% {(2*wr/100)-1:>+8.3f}R {w-l:>+7}R")
    print("-"*60)

# ─── Save OOS predictions ───────────────────────────────────
out_path = pathlib.Path(__file__).parent.parent / "data/ml_oos_predictions.parquet"
oos.to_parquet(out_path)
print(f"\nSaved OOS predictions: {out_path}")
print(f"Elapsed: {time.time()-t0:.1f}s")
