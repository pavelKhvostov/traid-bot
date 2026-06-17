"""etap_177: новая разметка «удачный сигнал = +5% раньше снятия low/high» + 4y/2y.

Постановка пользователя (2026-06-09):
  • TRAIN = 4 года (2020-01 → 2024-01), TEST = 2 года (2024-01 → конец).
  • Лейбл success(1/0): от входа (close сигнальной 12h-свечи) цена прошла
        LONG : +5% ВВЕРХ раньше, чем сняла low сигнальной свечи (l[i]);
        SHORT: -5% ВНИЗ  раньше, чем сняла high сигнальной свечи (h[i]).
    Первое касание решает (оба в одной 1h-свече → считаем стоп первым).
    Не достигла +5% за таймаут (30 дней) → 0.
  • Модель (HistGBM + изотония) учится разделять success на TRAIN, проверяем OOS.

Кандидаты (Stage A) и фичи — те же, что в etap_175 (failed-sweep + Bulkowski,
27 фич: sweep / структура свечи / ATR / EMA-тренд / pre-returns / swing-дист /
USDT.D / time-of-day). Кросс-актив BTC+ETH+SOL.

Доп.: для отобранных считаем реальный net_R, если торговать TP=+5% / SL=low,
с издержками (taker+slip+funding) — честная связь отбора с PnL.

Output: output/etap_177_labeled.csv, etap_177_sweep.csv, etap_177_importance.csv
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
from etap_175_metalabel_dataset import (
    build_features, detect_failed_sweep, confirmed_swings_last,
    SIDE_COST, FUNDING_PER_8H)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
START_DATE = pd.Timestamp("2020-01-01", tz="UTC")
END_DATE = pd.Timestamp("2026-05-01", tz="UTC")
TRAIN_END = pd.Timestamp("2024-01-01", tz="UTC")   # 4 года train, ~2.3 года test
OUT = _ROOT / 'research' / 'elements_study' / 'output'

TARGET_PCT = 5.0           # цель +5%
TIMEOUT_12H = 60           # 30 дней на достижение цели


def simulate_5pct(side, entry, sl_level, h1, l1, c1, t1_ns, t_close_ns):
    """success=1 если +TARGET% раньше снятия low/high. + реальный net_R."""
    if side == 'long':
        if sl_level >= entry:
            return None
        tp = entry * (1 + TARGET_PCT / 100)
    else:
        if sl_level <= entry:
            return None
        tp = entry * (1 - TARGET_PCT / 100)
    risk_pct = abs(entry - sl_level) / entry
    rr_at_target = (TARGET_PCT / 100) / risk_pct      # reward/risk до цели

    start = int(np.searchsorted(t1_ns, t_close_ns, side='left'))
    if start >= len(c1):
        return None
    end = min(start + TIMEOUT_12H * 12, len(c1))

    success = 0; outcome = 'timeout'; exit_i = end - 1
    for k in range(start, end):
        hi = h1[k]; lo = l1[k]
        if side == 'long':
            hit_sl = lo <= sl_level
            hit_tp = hi >= tp
        else:
            hit_sl = hi >= sl_level
            hit_tp = lo <= tp
        if hit_sl and hit_tp:
            success = 0; outcome = 'sl'; exit_i = k; break   # стоп первым (консерв.)
        if hit_sl:
            success = 0; outcome = 'sl'; exit_i = k; break
        if hit_tp:
            success = 1; outcome = 'tp'; exit_i = k; break

    # реальный net_R при торговле TP=+5% / SL=low
    if outcome == 'tp':
        gross_R = rr_at_target
    elif outcome == 'sl':
        gross_R = -1.0
    else:
        px = c1[exit_i]
        gross_R = ((px - entry) if side == 'long' else (entry - px)) / abs(entry - sl_level)
    hours = max(1, exit_i - start + 12)
    cost_R = (2 * SIDE_COST + FUNDING_PER_8H * hours / 8.0) / risk_pct
    net_R = gross_R - cost_R
    return {'success': success, 'outcome': outcome, 'risk_pct': risk_pct * 100,
            'rr_at_target': rr_at_target, 'gross_R': gross_R, 'net_R': net_R,
            'bars_held_1h': exit_i - start}


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
        bull = []; bear = []
        for det in DETECTORS:
            sig = det(df12, i)
            if sig is not None:
                (bull if sig['side'] == 'long' else bear).append(sig['pattern'])
        fs_long, fs_short, fs_feats = detect_failed_sweep(h, l, c, i)
        cand_long = fs_long or len(bull) > 0
        cand_short = fs_short or len(bear) > 0
        if not (cand_long or cand_short):
            continue
        sh, sl_sw = confirmed_swings_last(h, l, i, LOOKBACK, SWING_N)
        dist_hi = (sh[1] - c[i]) / c[i] * 100 if sh else 0.0
        dist_lo = (c[i] - sl_sw[1]) / c[i] * 100 if sl_sw else 0.0
        base = {
            'symbol': sym, 'time': times.iloc[i], 'entry': c[i],
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
        for side, is_cand, n_bulk, from_fs, sl_level in (
            ('long', cand_long, len(bull), fs_long, l[i]),
            ('short', cand_short, len(bear), fs_short, h[i])):
            if not is_cand:
                continue
            lab = simulate_5pct(side, c[i], sl_level, h1, l1, c1, t1_ns, t_close_ns)
            if lab is None:
                continue
            rec = dict(base)
            rec['side_long'] = 1 if side == 'long' else 0
            rec['n_bulkowski'] = n_bulk
            rec['from_failed_sweep'] = int(bool(from_fs))
            rec['period'] = 'test' if times.iloc[i] >= TRAIN_END else 'train'
            rec.update(lab)
            rows.append(rec)
    return rows


LEAK = {'symbol', 'time', 'entry', 'outcome', 'success', 'gross_R', 'net_R',
        'risk_pct', 'rr_at_target', 'bars_held_1h', 'period'}


def main():
    t0 = time.time()
    print("=" * 74)
    print(f"etap_177: лейбл «+{TARGET_PCT:.0f}% раньше снятия low/high» · 4y train / 2y test")
    print("=" * 74)

    ud = pd.read_csv(_ROOT / 'data' / 'USDT_D_1d.csv', parse_dates=['datetime'])
    ud_ret = ud['close'].pct_change().fillna(0) * 100
    usdtd_ret_by_date = {pd.Timestamp(d).normalize(): r for d, r in zip(ud['datetime'], ud_ret.values)}

    all_rows = []
    for sym in SYMBOLS:
        rows = process_symbol(sym, usdtd_ret_by_date)
        print(f"  [{sym}] кандидатов: {len(rows)}")
        all_rows.extend(rows)
    df = pd.DataFrame(all_rows).sort_values('time').reset_index(drop=True)
    df['sym_id'] = df['symbol'].map({'BTCUSDT': 0, 'ETHUSDT': 1, 'SOLUSDT': 2})
    df.to_csv(OUT / 'etap_177_labeled.csv', index=False)

    # baseline success-rate
    print("\nBASELINE success-rate (доля сигналов, дошедших +5% раньше стопа):")
    for split in ['train', 'test']:
        sub = df[df.period == split]
        for grp, gd in [('ALL', sub), ('LONG', sub[sub.side_long == 1]), ('SHORT', sub[sub.side_long == 0])]:
            print(f"  {split:>5} {grp:>6}: n={len(gd):>4}  success%={gd['success'].mean()*100:>5.1f}  "
                  f"net_ΣR={gd['net_R'].sum():>+7.1f}  meanR={gd['net_R'].mean():>+.3f}")

    feat = [c for c in df.columns if c not in LEAK and c != 'sym_id' and df[c].dtype != object] + ['sym_id']
    tr = df[df.period == 'train'].reset_index(drop=True)
    te = df[df.period == 'test'].reset_index(drop=True)
    X, y = tr[feat].values, tr['success'].values
    Xte, yte = te[feat].values, te['success'].values

    # in-sample обучаемость: 5-fold time-contiguous CV + resub
    kf = KFold(5, shuffle=False); aucs = []
    for a, b in kf.split(X):
        m = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.04,
            min_samples_leaf=40, l2_regularization=1.0, random_state=0).fit(X[a], y[a])
        aucs.append(roc_auc_score(y[b], m.predict_proba(X[b])[:, 1]))
    print(f"\nTRAIN 5-fold CV AUC: {np.mean(aucs):.3f} ± {np.std(aucs):.3f}")

    clf = HistGradientBoostingClassifier(max_iter=500, learning_rate=0.04,
        max_leaf_nodes=31, min_samples_leaf=40, l2_regularization=1.0,
        early_stopping=True, validation_fraction=0.15, random_state=42).fit(X, y)
    print(f"TRAIN resub AUC:     {roc_auc_score(y, clf.predict_proba(X)[:,1]):.3f}")

    # калибровка на последних 20% train
    cut = int(len(tr) * 0.8)
    iso = IsotonicRegression(out_of_bounds='clip').fit(
        clf.predict_proba(X[cut:])[:, 1], y[cut:])
    p_te = iso.transform(clf.predict_proba(Xte)[:, 1])
    print(f"TEST AUC:            {roc_auc_score(yte, p_te):.3f}  "
          f"(baseline success {yte.mean()*100:.1f}%)")

    te = te.copy(); te['p'] = p_te
    print(f"\nBASELINE TEST: n={len(te)}  success%={yte.mean()*100:.1f}  "
          f"net_ΣR={te['net_R'].sum():+.1f}  meanR={te['net_R'].mean():+.3f}")
    print("\nTHRESHOLD SWEEP (TEST):")
    print(f"{'τ':>5}  {'n':>4}  {'%':>4}  {'succ%':>5}  {'meanR':>7}  {'ΣR':>7}  {'L_R':>7}  {'S_R':>7}")
    rows = []
    for tau in [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]:
        sel = te[te.p >= tau]
        if len(sel) == 0:
            continue
        L = sel[sel.side_long == 1]['net_R']; S = sel[sel.side_long == 0]['net_R']
        print(f"{tau:>5.2f}  {len(sel):>4}  {len(sel)/len(te)*100:>3.0f}%  "
              f"{sel['success'].mean()*100:>5.1f}  {sel['net_R'].mean():>+7.3f}  "
              f"{sel['net_R'].sum():>+7.1f}  {(L.mean() if len(L) else 0):>+7.3f}  "
              f"{(S.mean() if len(S) else 0):>+7.3f}")
        rows.append({'tau': tau, 'n': len(sel), 'succ_pct': round(sel['success'].mean()*100, 1),
                     'mean_net_R': round(sel['net_R'].mean(), 3), 'sum_net_R': round(sel['net_R'].sum(), 1)})
    pd.DataFrame(rows).to_csv(OUT / 'etap_177_sweep.csv', index=False)

    pi = permutation_importance(clf, Xte, yte, n_repeats=10, random_state=0, scoring='roc_auc')
    imp = sorted(zip(feat, pi.importances_mean, pi.importances_std), key=lambda x: -x[1])
    print("\nPermutation importance (TEST, top-12):")
    for nm, mn, st in imp[:12]:
        print(f"  {nm:>22}  {mn:+.4f} ± {st:.4f}")
    pd.DataFrame([{'feature': n, 'imp': m, 'std': s} for n, m, s in imp]).to_csv(
        OUT / 'etap_177_importance.csv', index=False)
    print(f"\nDone in {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
