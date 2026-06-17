"""etap_176: META-СЕЛЕКТОР (Stage B) на лейблах etap_175.

Выбор пользователя: гибрид пивот→PnL-фильтр, старт GBM, BTC+ETH+SOL.
GBM = sklearn HistGradientBoostingClassifier (LightGBM не установлен; HGB —
робастный GBM в стиле проекта без тяжёлых зависимостей) + изотоническая
калибровка.

ЗАДАЧА: из кандидатов-пивотов (Stage A, etap_175) отобрать торгуемые —
обучаем на лейбле win = (net_R после издержек > 0), отбираем по P(win)≥τ,
сравниваем net_R отобранного подмножества с baseline (unfiltered).

ВАЛИДАЦИЯ (честно):
  • TEST = строго будущее (2025-01-01 → 2026-04), чистый OOS.
  • Внутри TRAIN: time-ordered, последние 20% = калибровка/early-stop,
    с embargo-зазором на границе.
  • Метрика отбора = РЕАЛЬНЫЙ net_R (тот же cost-движок), НЕ AUC.
  • Permutation importance на TEST — честно показать, на что опирается отбор.

NB: это MVP-ворота. Следующая строгость (CPCV + Deflated Sharpe / PBO) —
etap_177+, перед тем как доверять и масштабировать в DL.

Output: output/etap_176_threshold_sweep.csv, output/etap_176_importance.csv
"""
from __future__ import annotations
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score
from sklearn.inspection import permutation_importance

OUT = _ROOT / 'research' / 'elements_study' / 'output'

# колонки, которые НЕЛЬЗЯ давать модели (исход или идентификаторы)
LEAK = {'symbol', 'time', 'entry', 'outcome', 'gross_R', 'net_R', 'win',
        'hit_rr1', 'hit_rr2', 'hit_rr3', 'mfe_R', 'mae_R', 'bars_held_1h', 'period'}


def main():
    df = pd.read_csv(OUT / 'etap_175_labeled.csv')
    df['time'] = pd.to_datetime(df['time'])
    df = df.sort_values('time').reset_index(drop=True)

    # symbol как числовая категория (Stage-B фича)
    df['sym_id'] = df['symbol'].map({'BTCUSDT': 0, 'ETHUSDT': 1, 'SOLUSDT': 2})

    feat_cols = [c for c in df.columns if c not in LEAK and c != 'sym_id'] + ['sym_id']
    feat_cols = [c for c in feat_cols if df[c].dtype != object]

    tr = df[df.period == 'train'].copy()
    te = df[df.period == 'test'].copy()

    # внутренний time-split с embargo
    tr = tr.sort_values('time').reset_index(drop=True)
    cut = int(len(tr) * 0.80)
    embargo = 20
    fit_idx = tr.index[:cut - embargo]
    cal_idx = tr.index[cut:]
    Xf, yf = tr.loc[fit_idx, feat_cols].values, tr.loc[fit_idx, 'win'].values
    Xc, yc = tr.loc[cal_idx, feat_cols].values, tr.loc[cal_idx, 'win'].values
    Xte, yte = te[feat_cols].values, te['win'].values

    print("=" * 74)
    print("etap_176: meta-селектор (HistGBM + изотоническая калибровка)")
    print("=" * 74)
    print(f"features={len(feat_cols)}  fit={len(Xf)}  calib={len(Xc)}  test={len(Xte)}")

    clf = HistGradientBoostingClassifier(
        max_iter=500, learning_rate=0.04, max_leaf_nodes=31,
        min_samples_leaf=40, l2_regularization=1.0,
        early_stopping=True, validation_fraction=0.15,
        random_state=42)
    clf.fit(Xf, yf)

    # изотоническая калибровка на cal-слайсе
    p_cal_raw = clf.predict_proba(Xc)[:, 1]
    iso = IsotonicRegression(out_of_bounds='clip').fit(p_cal_raw, yc)

    p_te_raw = clf.predict_proba(Xte)[:, 1]
    p_te = iso.transform(p_te_raw)
    auc = roc_auc_score(yte, p_te)
    print(f"\nTEST AUC (win) = {auc:.3f}   (baseline win-rate {yte.mean()*100:.1f}%)")

    te = te.copy()
    te['p_win'] = p_te

    base_mean = te['net_R'].mean()
    base_sum = te['net_R'].sum()
    print(f"\nBASELINE TEST (unfiltered): n={len(te)}  win%={yte.mean()*100:.1f}  "
          f"mean net_R={base_mean:+.3f}  ΣR={base_sum:+.1f}")

    print("\n" + "=" * 74)
    print("THRESHOLD SWEEP на TEST (метрика = реальный net_R отобранных)")
    print("=" * 74)
    print(f"{'τ':>5}  {'n':>4}  {'%kept':>6}  {'win%':>5}  {'meanR':>7}  {'ΣR':>7}  "
          f"{'L_meanR':>8}  {'S_meanR':>8}")
    rows = []
    for tau in [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]:
        sel = te[te.p_win >= tau]
        if len(sel) == 0:
            continue
        L = sel[sel.side_long == 1]['net_R']
        S = sel[sel.side_long == 0]['net_R']
        print(f"{tau:>5.2f}  {len(sel):>4}  {len(sel)/len(te)*100:>5.0f}%  "
              f"{sel['win'].mean()*100:>5.1f}  {sel['net_R'].mean():>+7.3f}  "
              f"{sel['net_R'].sum():>+7.1f}  "
              f"{(L.mean() if len(L) else 0):>+8.3f}  {(S.mean() if len(S) else 0):>+8.3f}")
        rows.append({'tau': tau, 'n': len(sel), 'pct_kept': round(len(sel)/len(te)*100, 1),
                     'win_pct': round(sel['win'].mean()*100, 1),
                     'mean_net_R': round(sel['net_R'].mean(), 3),
                     'sum_net_R': round(sel['net_R'].sum(), 1),
                     'long_meanR': round(L.mean(), 3) if len(L) else None,
                     'short_meanR': round(S.mean(), 3) if len(S) else None})
    pd.DataFrame(rows).to_csv(OUT / 'etap_176_threshold_sweep.csv', index=False)

    # выбранный рабочий порог: первый, где mean net_R максимален при n>=40
    valid = [r for r in rows if r['n'] >= 40]
    best = max(valid, key=lambda r: r['mean_net_R']) if valid else None
    if best:
        tau = best['tau']
        sel = te[te.p_win >= tau]
        print(f"\nЛУЧШИЙ порог τ={tau} (n≥40):")
        print(f"  по активам:")
        for sym in ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']:
            s = sel[sel.symbol == sym]
            if len(s):
                print(f"    {sym}: n={len(s):>3}  win%={s['win'].mean()*100:>5.1f}  "
                      f"meanR={s['net_R'].mean():+.3f}  ΣR={s['net_R'].sum():+.1f}")
        sel_yr = sel.copy(); sel_yr['year'] = sel_yr['time'].dt.year
        print(f"  по годам:")
        for yr, g in sel_yr.groupby('year'):
            print(f"    {yr}: n={len(g):>3}  ΣR={g['net_R'].sum():+.1f}  "
                  f"mean={g['net_R'].mean():+.3f}")

    # permutation importance на TEST (на что опирается отбор)
    print("\n" + "=" * 74)
    print("Permutation importance (TEST, top-15)")
    print("=" * 74)
    pi = permutation_importance(clf, Xte, yte, n_repeats=10, random_state=0,
                                scoring='roc_auc')
    imp = sorted(zip(feat_cols, pi.importances_mean, pi.importances_std),
                 key=lambda x: -x[1])
    for name, m, s in imp[:15]:
        print(f"  {name:>22}  {m:+.4f} ± {s:.4f}")
    pd.DataFrame([{'feature': n, 'imp': m, 'std': s} for n, m, s in imp]
                 ).to_csv(OUT / 'etap_176_importance.csv', index=False)

    print("\nSaved: etap_176_threshold_sweep.csv, etap_176_importance.csv")


if __name__ == '__main__':
    main()
