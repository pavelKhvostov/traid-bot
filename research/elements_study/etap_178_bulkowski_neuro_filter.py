"""etap_178: нейро-фильтр busted-сигналов Bulkowski по условиям пользователя.

Контекст: паттерны Bulkowski ловят разворот в ~80% (move≥5%, etap_172), НО
busted 50-60% — путь рваный, реальный стоп выбивает. Задача селектора:
по контексту сигнала отделить ХОРОШИЕ (дойдёт +5% раньше снятия структурного
low/high паттерна) от ПЛОХИХ (busted) и отсеять плохие.

Условия пользователя (2026-06-09):
  • Stage A = ТОЛЬКО детекторы Bulkowski (etap_172), кросс-актив BTC+ETH+SOL.
  • Лейбл success: +5% в сторону сигнала РАНЬШЕ снятия структурного уровня
        LONG  → стоп = low_price паттерна (низ фигуры);
        SHORT → стоп = high_price паттерна (верх фигуры).
    Резолв на 1h, оба в свече → стоп первым (консерв.), таймаут 30д → 0.
  • TRAIN 4 года (2020-01→2024-01), TEST 2 года (2024-01→конец).
  • Модель = HistGBM + изотония (старт; NN позже, если есть сигнал).
  • Фичи = контекст (как etap_175/177) + ИДЕНТИЧНОСТЬ паттерна + height/duration
    + rr_at_target (reward/risk геометрия, известна на входе).

Output: output/etap_178_labeled.csv, etap_178_sweep.csv, etap_178_importance.csv
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score
from sklearn.inspection import permutation_importance
from sklearn.model_selection import KFold

from data_manager import load_df, compose_from_base
from etap_172_bulkowski_patterns import DETECTORS, LOOKBACK, SWING_N
from etap_175_metalabel_dataset import build_features, detect_failed_sweep, confirmed_swings_last
from etap_177_label5pct_select import simulate_5pct  # success +5% раньше снятия sl_level

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
START_DATE = pd.Timestamp("2020-01-01", tz="UTC")
END_DATE = pd.Timestamp("2026-05-01", tz="UTC")
TRAIN_END = pd.Timestamp("2024-01-01", tz="UTC")
OUT = _ROOT / 'research' / 'elements_study' / 'output'

PATTERN_ID = {p: i for i, p in enumerate(sorted(
    ['big_w', 'big_m', 'db_eve_eve', 'hs_top', 'hs_bottom', 'triple_top',
     'v_bottom', 'v_top', 'rounding_bottom', 'cup_handle', 'barr_top',
     'barr_bottom', 'diamond_top']))}


def process_symbol(sym, usdtd_ret_by_date):
    df1 = load_df(sym, "1h")
    df1 = df1[(df1.index >= START_DATE) & (df1.index <= END_DATE)].copy()
    df12 = compose_from_base(df1, "12h")
    df12 = df12[(df12.index >= START_DATE) & (df12.index <= END_DATE)].copy().reset_index()
    if 'time' not in df12.columns:
        df12 = df12.rename(columns={df12.columns[0]: 'time'})
    o, h, l, c, atr, F, n = build_features(df12, usdtd_ret_by_date)
    times = df12['time']
    h1 = df1['high'].values.astype(float); l1 = df1['low'].values.astype(float)
    c1 = df1['close'].values.astype(float)
    t1_ns = df1.index.values.astype('datetime64[ns]').astype(np.int64)

    rows = []
    for i in range(LOOKBACK + SWING_N + 2, n - SWING_N):
        fired = [det(df12, i) for det in DETECTORS]
        fired = [s for s in fired if s is not None]
        if not fired:
            continue
        fs_long, fs_short, fs_feats = detect_failed_sweep(h, l, c, i)
        sh, sl_sw = confirmed_swings_last(h, l, i, LOOKBACK, SWING_N)
        dist_hi = (sh[1] - c[i]) / c[i] * 100 if sh else 0.0
        dist_lo = (c[i] - sl_sw[1]) / c[i] * 100 if sl_sw else 0.0
        ctx = {
            'close_pos_in_range': F['close_pos_in_range'][i], 'body_pct': F['body_pct'][i],
            'upper_wick_pct': F['upper_wick_pct'][i], 'lower_wick_pct': F['lower_wick_pct'][i],
            'range_vs_atr': F['range_vs_atr'][i], 'atr_pct': F['atr_pct'][i],
            'vol_z20': F['vol_z20'][i], 'ema200_dist_pct': F['ema200_dist_pct'][i],
            'ema50_slope_pct': F['ema50_slope_pct'][i], 'pre_3d_ret_pct': F['pre_3d_ret_pct'][i],
            'pre_7d_ret_pct': F['pre_7d_ret_pct'][i], 'usdtd_1d_ret_pct': F['usdtd_1d_ret_pct'][i],
            'hour_utc': F['hour_utc'][i], 'dow': F['dow'][i],
            'dist_swing_hi_pct': dist_hi, 'dist_swing_lo_pct': dist_lo, **fs_feats,
        }
        t_close_ns = (times.iloc[i] + pd.Timedelta(hours=12)).value
        for sig in fired:
            side = sig['side']
            entry = sig['breakout_price']
            stop = sig['low_price'] if side == 'long' else sig['high_price']
            lab = simulate_5pct(side, entry, stop, h1, l1, c1, t1_ns, t_close_ns)
            if lab is None:
                continue
            rec = dict(ctx)
            rec.update({
                'symbol': sym, 'time': times.iloc[i], 'entry': entry,
                'pattern': sig['pattern'], 'pattern_id': PATTERN_ID[sig['pattern']],
                'side_long': 1 if side == 'long' else 0,
                'height_pct': sig['height_pct'], 'duration_bars': sig['duration_bars'],
                'sym_id': {'BTCUSDT': 0, 'ETHUSDT': 1, 'SOLUSDT': 2}[sym],
                'period': 'test' if times.iloc[i] >= TRAIN_END else 'train',
            })
            rec.update(lab)
            rows.append(rec)
    return rows


LEAK = {'symbol', 'time', 'entry', 'pattern', 'outcome', 'success', 'gross_R',
        'net_R', 'risk_pct', 'bars_held_1h', 'period'}


def main():
    t0 = time.time()
    print("=" * 74)
    print("etap_178: нейро-фильтр busted Bulkowski · лейбл +5%>стоп · 4y/2y · BTC+ETH+SOL")
    print("=" * 74)
    ud = pd.read_csv(_ROOT / 'data' / 'USDT_D_1d.csv', parse_dates=['datetime'])
    ud_ret = ud['close'].pct_change().fillna(0) * 100
    ud_by_date = {pd.Timestamp(d).normalize(): r for d, r in zip(ud['datetime'], ud_ret.values)}

    rows = []
    for sym in SYMBOLS:
        r = process_symbol(sym, ud_by_date)
        print(f"  [{sym}] Bulkowski-сигналов: {len(r)}")
        rows.extend(r)
    df = pd.DataFrame(rows).sort_values('time').reset_index(drop=True)
    df.to_csv(OUT / 'etap_178_labeled.csv', index=False)

    print("\nBASELINE success-rate (дошёл +5% раньше снятия структурного low/high):")
    for split in ['train', 'test']:
        sub = df[df.period == split]
        for grp, gd in [('ALL', sub), ('LONG', sub[sub.side_long == 1]), ('SHORT', sub[sub.side_long == 0])]:
            print(f"  {split:>5} {grp:>6}: n={len(gd):>4}  success%={gd['success'].mean()*100:>5.1f}  "
                  f"net_ΣR={gd['net_R'].sum():>+7.1f}  RR_med={gd['rr_at_target'].median():.2f}")

    feat = [c for c in df.columns if c not in LEAK and df[c].dtype != object]
    tr = df[df.period == 'train'].reset_index(drop=True)
    te = df[df.period == 'test'].reset_index(drop=True)
    X, y = tr[feat].values, tr['success'].values
    Xte, yte = te[feat].values, te['success'].values

    kf = KFold(5, shuffle=False); aucs = []
    for a, b in kf.split(X):
        m = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.04,
            min_samples_leaf=30, l2_regularization=1.0, random_state=0).fit(X[a], y[a])
        aucs.append(roc_auc_score(y[b], m.predict_proba(X[b])[:, 1]))
    print(f"\nTRAIN 5-fold CV AUC: {np.mean(aucs):.3f} ± {np.std(aucs):.3f}")

    clf = HistGradientBoostingClassifier(max_iter=500, learning_rate=0.04,
        max_leaf_nodes=31, min_samples_leaf=30, l2_regularization=1.0,
        early_stopping=True, validation_fraction=0.15, random_state=42).fit(X, y)
    print(f"TRAIN resub AUC:     {roc_auc_score(y, clf.predict_proba(X)[:,1]):.3f}")
    cut = int(len(tr) * 0.8)
    iso = IsotonicRegression(out_of_bounds='clip').fit(clf.predict_proba(X[cut:])[:, 1], y[cut:])
    te = te.copy()
    te['p'] = iso.transform(clf.predict_proba(Xte)[:, 1])
    te['EV'] = te['p'] * te['rr_at_target'] - (1 - te['p'])
    print(f"TEST AUC:            {roc_auc_score(yte, te['p']):.3f}  (baseline success {yte.mean()*100:.1f}%)")

    print(f"\nBASELINE TEST: n={len(te)}  success%={yte.mean()*100:.1f}  "
          f"net_ΣR={te['net_R'].sum():+.1f}  meanR={te['net_R'].mean():+.3f}")
    print("\nОТСЕВ по P(хороший сигнал) — TEST:")
    print(f"{'τ':>5}  {'n':>4}  {'kept%':>5}  {'succ%':>6}  {'busted↓':>7}  {'meanR':>7}  {'ΣR':>7}")
    base_succ = yte.mean() * 100
    rows_sw = []
    for tau in [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]:
        sel = te[te.p >= tau]
        if len(sel) < 5:
            continue
        succ = sel['success'].mean() * 100
        print(f"{tau:>5.2f}  {len(sel):>4}  {len(sel)/len(te)*100:>4.0f}%  {succ:>6.1f}  "
              f"{succ-base_succ:>+6.1f}pp  {sel['net_R'].mean():>+7.3f}  {sel['net_R'].sum():>+7.1f}")
        rows_sw.append({'kind': 'P', 'tau': tau, 'n': len(sel), 'succ_pct': round(succ, 1),
                        'mean_net_R': round(sel['net_R'].mean(), 3), 'sum_net_R': round(sel['net_R'].sum(), 1)})
    print("\nОТСЕВ по EV = P×RR − (1−P) — TEST:")
    print(f"{'EV≥':>5}  {'n':>4}  {'succ%':>6}  {'meanR':>7}  {'ΣR':>7}  {'L_ΣR':>7}  {'S_ΣR':>7}")
    for ev in [0.0, 0.3, 0.6, 0.9, 1.2]:
        sel = te[te.EV >= ev]
        if len(sel) < 5:
            continue
        L = sel[sel.side_long == 1]['net_R']; S = sel[sel.side_long == 0]['net_R']
        print(f"{ev:>5.1f}  {len(sel):>4}  {sel['success'].mean()*100:>6.1f}  "
              f"{sel['net_R'].mean():>+7.3f}  {sel['net_R'].sum():>+7.1f}  "
              f"{L.sum():>+7.1f}  {S.sum():>+7.1f}")
        rows_sw.append({'kind': 'EV', 'tau': ev, 'n': len(sel), 'succ_pct': round(sel['success'].mean()*100, 1),
                        'mean_net_R': round(sel['net_R'].mean(), 3), 'sum_net_R': round(sel['net_R'].sum(), 1)})
    pd.DataFrame(rows_sw).to_csv(OUT / 'etap_178_sweep.csv', index=False)

    # по паттернам: baseline vs после отсева EV>=0.6
    print("\nПо паттернам (TEST): baseline → после отсева EV≥0.6")
    sel = te[te.EV >= 0.6]
    for pat in sorted(te['pattern'].unique()):
        b = te[te.pattern == pat]; s = sel[sel.pattern == pat]
        print(f"  {pat:>14}: base n={len(b):>3} succ={b['success'].mean()*100:>4.0f}% ΣR={b['net_R'].sum():>+6.1f}"
              f"   →  kept n={len(s):>3} succ={(s['success'].mean()*100 if len(s) else 0):>4.0f}% ΣR={s['net_R'].sum():>+6.1f}")

    # по годам для EV>=0.6
    sy = te[te.EV >= 0.6].copy(); sy['yr'] = sy['time'].dt.year
    print("\nEV≥0.6 по годам:")
    for yr, g in sy.groupby('yr'):
        print(f"  {yr}: n={len(g):>3}  ΣR={g['net_R'].sum():+6.1f}  succ={g['success'].mean()*100:.0f}%")

    pi = permutation_importance(clf, Xte, yte, n_repeats=10, random_state=0, scoring='roc_auc')
    imp = sorted(zip(feat, pi.importances_mean, pi.importances_std), key=lambda x: -x[1])
    print("\nPermutation importance (TEST, top-12):")
    for nm, mn, st in imp[:12]:
        print(f"  {nm:>22}  {mn:+.4f} ± {st:.4f}")
    pd.DataFrame([{'feature': n, 'imp': m, 'std': s} for n, m, s in imp]).to_csv(
        OUT / 'etap_178_importance.csv', index=False)
    print(f"\nDone in {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
