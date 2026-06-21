"""Empirical TF_WEIGHT calibration на per-TF force snapshots.

Анализ:
1. Per-TF effect size: P(confirmed | buyer_tf > seller_tf) для каждого TF
2. Logistic regression: confirmed ~ Σ w_tf × net_tf
3. Coefficients → empirical TF weights (normalized to 1h=1)
4. Сравнение с current linear-hours weights

Run после force_per_tf_batch завершит работу.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
import numpy as np

P = Path.home()/'Desktop/force_per_tf_6y.parquet'
if not P.exists():
    print(f"Not found: {P}. Run force_per_tf_batch first."); raise SystemExit

df = pd.read_parquet(P)
print(f"Loaded {len(df)} pivots × {df.shape[1]} cols")
print(f"  Confirmed: {df['confirmed'].sum()}/{len(df)} = {df['confirmed'].mean()*100:.1f}%")
TFS = ['1h','2h','4h','6h','8h','12h','1d','2d','3d']

# Per-TF net (direction-aware: для FH ждём seller>buyer, для FL buyer>seller)
print("\n=== Per-TF effect size ===")
print(f"{'TF':>4s} {'force_match_n':>14s} {'P(W)|match':>12s} {'mismatch_n':>11s} {'P(W)|mismatch':>14s} {'lift':>6s}")
print("-"*70)
for tf in TFS:
    net = df[f'buyer_{tf}'] - df[f'seller_{tf}']
    # direction-match: FH → net < 0 (seller dominant); FL → net > 0
    fh_match = (df['direction']=='high') & (net < 0)
    fl_match = (df['direction']=='low') & (net > 0)
    match = fh_match | fl_match
    not_match = (~match) & (net.abs() > 0)  # exclude no-zone cases
    nm = match.sum(); nn = not_match.sum()
    pwm = df.loc[match, 'confirmed'].mean() if nm else 0
    pwn = df.loc[not_match, 'confirmed'].mean() if nn else 0
    lift = pwm - pwn
    print(f"  {tf:>4s} {nm:>14d} {pwm*100:>10.1f}% {nn:>11d} {pwn*100:>12.1f}% {lift*100:>+5.1f}")

# Stratified by per-TF net magnitude (sign-corrected)
print("\n=== P(confirmed) by net_tf magnitude (sign-corrected: FH→−net, FL→+net) ===")
print(f"{'TF':>4s} {'q1<X':>10s} {'q1 P(W)':>9s} {'q3>X':>10s} {'q3 P(W)':>9s} {'top 10%':>10s} {'top P(W)':>9s}")
for tf in TFS:
    net = df[f'buyer_{tf}'] - df[f'seller_{tf}']
    sign_corr = np.where(df['direction']=='high', -net, net)
    # higher sign_corr = more aligned with expected direction
    q1 = np.quantile(sign_corr, 0.10)
    q3 = np.quantile(sign_corr, 0.90)
    q_top = np.quantile(sign_corr, 0.90)
    bot = sign_corr <= q1
    top = sign_corr >= q3
    pw_bot = df.loc[bot, 'confirmed'].mean() if bot.sum() else 0
    pw_top = df.loc[top, 'confirmed'].mean() if top.sum() else 0
    print(f"  {tf:>4s} {q1:>10.1f} {pw_bot*100:>7.1f}% {q3:>10.1f} {pw_top*100:>7.1f}% n={top.sum()}")

# Logistic regression: confirmed ~ Σ net_tf, all TFs together
print("\n=== Logistic regression: confirmed ~ Σ w × net_tf ===")
try:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    # Build feature matrix: sign-corrected net per TF
    X = np.column_stack([
        np.where(df['direction']=='high',
                 -(df[f'buyer_{tf}']-df[f'seller_{tf}']),
                  (df[f'buyer_{tf}']-df[f'seller_{tf}']))
        for tf in TFS
    ])
    y = df['confirmed'].astype(int).values
    # Standardize (so coefficients comparable)
    sc = StandardScaler(); Xs = sc.fit_transform(X)
    lr = LogisticRegression(max_iter=2000, C=1.0, class_weight='balanced')
    lr.fit(Xs, y)
    coefs = lr.coef_[0]
    print(f"  Coefficients (standardized features; positive = predicts confirmed):")
    for tf, c, std in zip(TFS, coefs, sc.scale_):
        # convert standardized coef back to raw scale
        raw = c / std if std > 0 else 0
        print(f"    {tf:>4s}  std_coef={c:+.4f}  raw_coef={raw:+.6f}  feature_std={std:.1f}")

    # Empirical TF weights: normalize so 1h coef → weight 1
    print("\n=== Empirical TF_WEIGHTs (normalized to 1h=1, vs current linear-hours) ===")
    print(f"{'TF':>4s} {'current weight':>14s} {'empir.coef':>11s} {'empir.weight':>13s} {'ratio':>7s}")
    h1_coef = abs(coefs[0]) if abs(coefs[0]) > 1e-9 else 1.0
    cur = {'1h':1,'2h':2,'4h':4,'6h':6,'8h':8,'12h':12,'1d':24,'2d':48,'3d':72}
    for tf, c in zip(TFS, coefs):
        emp_w = abs(c)/h1_coef
        ratio = emp_w / cur[tf] if cur[tf] else 0
        print(f"  {tf:>4s} {cur[tf]:>14d} {c:>+11.4f} {emp_w:>13.3f} {ratio:>6.2f}×")

    # AUC-ROC
    from sklearn.metrics import roc_auc_score
    pred_p = lr.predict_proba(Xs)[:,1]
    auc = roc_auc_score(y, pred_p)
    print(f"\n  Overall AUC: {auc:.4f}")
except ImportError:
    print("  sklearn not available")
