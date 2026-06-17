"""zone_reactor.baseline — gating-валидация: предсказывает ли сила зоны реакцию ≥5%?

УСЛОВНАЯ задача (без фрактал-утечки etap_170): среди 12h-фракталов отделить сильные
зоны (реакция ≥5%) от слабых, по multi-TF силе зоны + ICT + индикаторам.
Train 2020-01→2024-01, test 2024-01→конец (2025-26 OOS).

Если AUC > 0.58 И реакция% монотонна по силе зоны → сигнал есть, строим GPU-сеть с
самообучением (model.py / train_gpu.py). Если ~0.5 → честный стоп.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from sklearn.inspection import permutation_importance

from research.zone_reactor.features import build_fractal_dataset, FEATURES

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TRAIN_END = pd.Timestamp("2024-01-01", tz="UTC")
HORIZON_D = 10; EMBARGO_D = 2
OUT = _ROOT / 'research' / 'zone_reactor'


def purged_cv(X, y, t):
    order = np.argsort(t); folds = np.array_split(order, 5); aucs = []
    for f in folds:
        lo, hi = t[f].min(), t[f].max()
        keep = np.ones(len(y), bool); keep[f] = False
        keep &= ~((t + HORIZON_D >= lo - EMBARGO_D) & (t <= hi + EMBARGO_D))
        if keep.sum() < 200 or y[f].sum() < 10 or len(np.unique(y[keep])) < 2:
            continue
        m = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.04, max_leaf_nodes=31,
            min_samples_leaf=30, l2_regularization=1.0, random_state=0).fit(X[keep], y[keep])
        aucs.append(roc_auc_score(y[f], m.predict_proba(X[f])[:, 1]))
    return (np.mean(aucs), np.std(aucs), len(aucs)) if aucs else (np.nan, np.nan, 0)


def main():
    t0 = time.time()
    print("=" * 80)
    print("zone_reactor BASELINE: предсказуема ли реакция ≥5% по силе зоны? (условно, OOS)")
    print("=" * 80)
    rows = []
    for sym in SYMBOLS:
        r = build_fractal_dataset(sym); rows.extend(r)
        s = pd.DataFrame(r)
        print(f"  [{sym}] фракталов: {len(r)}  реакция≥5%: {s['react5'].mean()*100:.1f}%")
    df = pd.DataFrame(rows).sort_values('time').reset_index(drop=True)
    df['t_days'] = (df['time'] - df['time'].min()).dt.total_seconds() / 86400.0
    df.to_csv(OUT / 'dataset.csv', index=False)

    is_tr = (df['time'] < TRAIN_END).values
    df[FEATURES] = df[FEATURES].fillna(0)
    Xtr, ytr, ttr = df.loc[is_tr, FEATURES].values, df.loc[is_tr, 'react5'].values, df.loc[is_tr, 't_days'].values
    te = df.loc[~is_tr].copy(); Xte, yte = te[FEATURES].values, te['react5'].values
    print(f"\nВСЕГО: {len(df)}  TRAIN {is_tr.sum()} (реакция {ytr.mean()*100:.0f}%) / "
          f"TEST {len(te)} (реакция {yte.mean()*100:.0f}%)")

    cv_m, cv_s, k = purged_cv(Xtr, ytr, ttr)
    clf = HistGradientBoostingClassifier(max_iter=500, learning_rate=0.04, max_leaf_nodes=31,
        min_samples_leaf=30, l2_regularization=1.0, early_stopping=True,
        validation_fraction=0.15, random_state=42).fit(Xtr, ytr)
    resub = roc_auc_score(ytr, clf.predict_proba(Xtr)[:, 1])
    oos = roc_auc_score(yte, clf.predict_proba(Xte)[:, 1])
    print(f"\nAUC: resub={resub:.3f}  purgedCV={cv_m:.3f}±{cv_s:.3f} (folds {k})  OOS={oos:.3f}")

    # МОНОТОННОСТЬ: реакция% по квартилям силы зоны (интерпретируемо)
    te = te.copy()
    print("\nреакция≥5% по квартилям zone_strength (TEST):")
    te['zb'] = pd.qcut(te['zone_strength'].rank(method='first'), 4, labels=['Q1-слаб', 'Q2', 'Q3', 'Q4-сильн'])
    for b, g in te.groupby('zb'):
        print(f"   {b:>9}: n={len(g):>4}  реакция%={g['react5'].mean()*100:>4.1f}  "
              f"strength∈[{g['zone_strength'].min():.1f},{g['zone_strength'].max():.1f}]")
    print("\nреакция≥5% по уверенности модели P (TEST):")
    te['p'] = clf.predict_proba(Xte)[:, 1]
    te['pb'] = pd.qcut(te['p'].rank(method='first'), 4, labels=['P-низк', 'Q2', 'Q3', 'P-выс'])
    for b, g in te.groupby('pb'):
        print(f"   {b:>7}: n={len(g):>4}  реакция%={g['react5'].mean()*100:>4.1f}")

    pi = permutation_importance(clf, Xte, yte, n_repeats=8, random_state=0, scoring='roc_auc')
    imp = sorted(zip(FEATURES, pi.importances_mean, pi.importances_std), key=lambda x: -x[1])
    print("\nPermutation importance (OOS, top-12):")
    for nm, mn, st in imp[:12]:
        print(f"   {nm:>18}  {mn:+.4f} ± {st:.4f}")
    pd.DataFrame([{'feature': n, 'imp': m} for n, m, _ in imp]).to_csv(OUT / 'importance.csv', index=False)

    print("\n" + "=" * 80)
    q = te.groupby('zb', observed=True)['react5'].mean()
    monotone = q.iloc[-1] - q.iloc[0]
    if oos > 0.58 and cv_m > 0.56:
        print(f"СИГНАЛ ЕСТЬ: OOS AUC={oos:.3f}, purgedCV={cv_m:.3f}, Δреакция(Q4-Q1)={monotone*100:+.0f}пп.")
        print("  → сила зоны предсказывает реакцию. СТРОИМ GPU-сеть с самообучением (model.py).")
    else:
        print(f"СЛАБО: OOS AUC={oos:.3f}, purgedCV={cv_m:.3f}, Δреакция(Q4-Q1)={monotone*100:+.0f}пп.")
        print("  Сила зоны не отделяет сильные зоны от слабых лучше монетки (условно).")
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
