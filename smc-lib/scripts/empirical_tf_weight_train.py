"""Train ML на force_all_bars_per_tf.parquet и извлечь empirical TF_WEIGHT.

Models:
  - Multinomial Logistic Regression (linear, для прямых coefficients)
  - HistGradientBoostingClassifier (tree, для performance benchmark + importance)

Walk-forward 1y train / 1mo retrain.

Output:
  - Per-TF / per-feature coefficients
  - Comparison vs current naive TF_WEIGHT (linear hours)
  - Performance metrics
"""
from __future__ import annotations
import time
from pathlib import Path
import pandas as pd
import numpy as np
import warnings; warnings.filterwarnings('ignore')

df = pd.read_parquet(Path.home()/'Desktop/force_all_bars_per_tf.parquet')
print(f"Loaded: {df.shape}")
print(f"Label distribution: {df['label'].value_counts().sort_index().to_dict()}")

df['close_ts'] = pd.to_datetime(df['close_ts_ms'], unit='ms', utc=True)
df = df.sort_values('close_ts').reset_index(drop=True)
print(f"Period: {df['close_ts'].min()} → {df['close_ts'].max()}")

TFS = ['1h','2h','4h','6h','8h','12h','1d','2d','3d']
FEATURE_TYPES = ['buyer','seller','top_long','top_short','wage_long','wage_short']
all_feats = [f'{ft}_{tf}' for tf in TFS for ft in FEATURE_TYPES]
print(f"\nFeatures: {len(all_feats)}")

X_full = df[all_feats].fillna(0).values
y_full = df['label'].astype(int).values

# Walk-forward
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import HistGradientBoostingClassifier

cur = pd.Timestamp('2021-05-01', tz='UTC')
t_end = df['close_ts'].max()

print("\n=== Walk-forward training ===")
preds_lr = []; preds_tree = []
coef_history = []
t0 = time.time(); ri = 0
while cur < t_end:
    train_lo = cur - pd.Timedelta(days=365)
    test_hi = cur + pd.Timedelta(days=30)
    train_mask = (df['close_ts'] >= train_lo) & (df['close_ts'] < cur)
    test_mask = (df['close_ts'] >= cur) & (df['close_ts'] < test_hi)
    n_tr = train_mask.sum(); n_te = test_mask.sum()
    if n_tr < 100 or n_te == 0:
        cur += pd.Timedelta(days=30); continue
    Xtr = X_full[train_mask.values]; ytr = y_full[train_mask.values]
    Xte = X_full[test_mask.values]; yte = y_full[test_mask.values]

    # Standardize
    sc = StandardScaler()
    Xtr_s = sc.fit_transform(Xtr); Xte_s = sc.transform(Xte)
    # Logistic (multinomial: -1, 0, +1)
    lr = LogisticRegression(max_iter=500, C=1.0,
                            class_weight='balanced', solver='lbfgs')
    lr.fit(Xtr_s, ytr)
    # Coefficients per class
    coef = lr.coef_  # shape (3, n_features)
    # Store coefs for FH and FL classes
    classes = lr.classes_
    coef_history.append({
        'cur_date': cur, 'n_tr': int(n_tr),
        'classes': classes.tolist(),
        'coef': coef.tolist(),
        'std': sc.scale_.tolist(),
    })
    ypp_lr = lr.predict(Xte_s)
    preds_lr.append(pd.DataFrame({
        'close_ts': df.loc[test_mask, 'close_ts'].values,
        'label': yte, 'pred_lr': ypp_lr,
    }))

    # HGBR
    hg = HistGradientBoostingClassifier(max_iter=200, max_depth=5, learning_rate=0.05,
                                         class_weight='balanced')
    hg.fit(Xtr, ytr)
    ypp_tree = hg.predict(Xte)
    preds_tree.append(pd.DataFrame({
        'close_ts': df.loc[test_mask, 'close_ts'].values,
        'label': yte, 'pred_tree': ypp_tree,
    }))

    ri += 1
    if ri % 10 == 0:
        print(f"  retrain {ri}: cur={cur.date()}, n_tr={n_tr}, n_te={n_te}, {(time.time()-t0)/60:.1f}m")
    cur += pd.Timedelta(days=30)

preds_lr = pd.concat(preds_lr).reset_index(drop=True)
preds_tree = pd.concat(preds_tree).reset_index(drop=True)
print(f"\nTotal predictions: {len(preds_lr)}, time {(time.time()-t0)/60:.1f}m")

# Performance
print("\n=== Performance ===")
print(f"Baseline (predict majority class 0): accuracy = {(preds_lr['label']==0).mean()*100:.1f}%")
print(f"\nLogistic accuracy: {(preds_lr['pred_lr']==preds_lr['label']).mean()*100:.1f}%")
print(f"HGBR accuracy:     {(preds_tree['pred_tree']==preds_tree['label']).mean()*100:.1f}%")

# Confusion matrices
from sklearn.metrics import confusion_matrix, classification_report
print("\n--- Logistic confusion matrix ---")
print(confusion_matrix(preds_lr['label'], preds_lr['pred_lr'], labels=[-1,0,1]))
print(classification_report(preds_lr['label'], preds_lr['pred_lr'], digits=3))

print("\n--- HGBR confusion matrix ---")
print(confusion_matrix(preds_tree['label'], preds_tree['pred_tree'], labels=[-1,0,1]))
print(classification_report(preds_tree['label'], preds_tree['pred_tree'], digits=3))

# Average coefficients across walk-forward iterations
print("\n=== Average ML coefficients (standardized) ===")
n_iter = len(coef_history)
avg_coef_fh = np.zeros(len(all_feats))
avg_coef_fl = np.zeros(len(all_feats))
n_fh = 0; n_fl = 0
for h in coef_history:
    classes = h['classes']
    coef = np.array(h['coef'])  # (n_classes, n_features)
    if 1 in classes:
        avg_coef_fh += coef[classes.index(1)]
        n_fh += 1
    if -1 in classes:
        avg_coef_fl += coef[classes.index(-1)]
        n_fl += 1
avg_coef_fh /= n_fh if n_fh else 1
avg_coef_fl /= n_fl if n_fl else 1

# Show per-feature
print("\nTop FH-predictive features (coef > 0 = predicts FH):")
fh_imp = pd.DataFrame({'feat': all_feats, 'coef': avg_coef_fh})
fh_imp = fh_imp.reindex(fh_imp['coef'].abs().sort_values(ascending=False).index).head(15)
for _, r in fh_imp.iterrows():
    print(f"  {r['feat']:25s} {r['coef']:+.4f}")

print("\nTop FL-predictive features (coef > 0 = predicts FL):")
fl_imp = pd.DataFrame({'feat': all_feats, 'coef': avg_coef_fl})
fl_imp = fl_imp.reindex(fl_imp['coef'].abs().sort_values(ascending=False).index).head(15)
for _, r in fl_imp.iterrows():
    print(f"  {r['feat']:25s} {r['coef']:+.4f}")

# Aggregate per-TF (sum across feature types)
print("\n=== Empirical TF importance (sum |coef| across all 6 feature types) ===")
print(f"{'TF':>4s} {'current':>10s} {'FH_emp':>10s} {'FL_emp':>10s} {'avg_emp':>10s} {'ratio_to_naive':>15s}")
print("-"*65)
current_weights = {'1h':1,'2h':2,'4h':4,'6h':6,'8h':8,'12h':12,'1d':24,'2d':48,'3d':72}
for tf in TFS:
    fh_sum = sum(abs(avg_coef_fh[i]) for i, f in enumerate(all_feats) if f.endswith(f'_{tf}'))
    fl_sum = sum(abs(avg_coef_fl[i]) for i, f in enumerate(all_feats) if f.endswith(f'_{tf}'))
    avg_sum = (fh_sum + fl_sum) / 2
    cur_w = current_weights[tf]
    print(f"  {tf:>4s} {cur_w:>10d} {fh_sum:>10.4f} {fl_sum:>10.4f} {avg_sum:>10.4f}")

# Normalize empirical to 1h=1
norms_fh = np.array([sum(abs(avg_coef_fh[i]) for i, f in enumerate(all_feats) if f.endswith(f'_{tf}')) for tf in TFS])
norms_fl = np.array([sum(abs(avg_coef_fl[i]) for i, f in enumerate(all_feats) if f.endswith(f'_{tf}')) for tf in TFS])
norms_avg = (norms_fh + norms_fl) / 2
norm_avg_to_1h = norms_avg / norms_avg[0] if norms_avg[0] > 0 else norms_avg

print("\n=== EMPIRICAL TF_WEIGHT (normalized to 1h=1) vs naive (hours) ===")
print(f"{'TF':>4s} {'naive':>8s} {'empirical':>12s} {'lift_×':>10s}")
print("-"*40)
for tf, w_e, w_n in zip(TFS, norm_avg_to_1h, [1, 2, 4, 6, 8, 12, 24, 48, 72]):
    ratio = w_e / w_n if w_n > 0 else 0
    print(f"  {tf:>4s} {w_n:>8.1f} {w_e:>12.3f} {ratio:>9.2f}×")

# Save coefficients
out = Path.home()/'Desktop/empirical_tf_weight_coefs.parquet'
pd.DataFrame({
    'TF': TFS,
    'naive_weight': [1, 2, 4, 6, 8, 12, 24, 48, 72],
    'empirical_normalized': norm_avg_to_1h,
}).to_parquet(out)
print(f"\nSaved → {out}")
