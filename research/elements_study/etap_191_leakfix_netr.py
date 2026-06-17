"""etap_191: фикс lookahead (USDT.D) + честный net_R payoff для задачи +5%>снятие low/high.

etap_189 дал OOS AUC 0.758; etap_190 показал: НЕ чистая тавтология (market-only AUC
0.614, net_R конвертируется в плюс R/tr +0.28). НО usdtd_1d_ret (importance #2) — это
дневной возврат USDT.D за ДАТУ бара, а 12h-бар в 00:00/12:00 закрывается раньше дневной
свечи → LOOKAHEAD. Чиним: usdtd берём за ПРОШЛЫЙ день (известно на момент бара).

Затем — решающий тест на ЧЕСТНЫХ данных:
  • OOS AUC (все фичи / market-only), purged-CV.
  • net_R payoff (точный risk_pct = (close-low)/close для long и т.д., rr=5%/risk,
    стоп=−1, издержки taker+slip+funding): фильтр по P улучшает ΣnetR / R/tr?
  • PER-YEAR и PER-ASSET стабильность отфильтрованного.
Если после фикса net_R остаётся плюсовым, стабильным по годам/активам — это РЕАЛЬНО.

Output: output/etap_191_dataset.csv, etap_191_sweep.csv
"""
from __future__ import annotations
import sys
import time
import warnings
from pathlib import Path

_ROOT = Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

from data_manager import load_df, compose_from_base
from etap_189_universe_5pct_predict import (
    build_indicators, hull, rsi, ema, SYMBOLS, START_DATE, END_DATE, TRAIN_END,
    TARGET, TIMEOUT)

OUT = _ROOT / 'research' / 'elements_study' / 'output'
HORIZON_D = 60; EMBARGO_D = 3
SIDE_COST = 0.0008; FUNDING_8H = 0.0001
GEOM = {'close_pos', 'range_atr', 'side_long', 'upper_wick', 'lower_wick', 'body_pct',
        'gap', 'is_bull', 'atr_pct', 'bb_bw', 'parkinson', 'realized_vol'}


def label_dir(side, entry, stop_px, h, l, start, n):
    end = min(start + TIMEOUT, n)
    tp = entry * (1 + TARGET/100) if side == 'long' else entry * (1 - TARGET/100)
    for k in range(start, end):
        if side == 'long':
            if l[k] <= stop_px: return 0, k - start
            if h[k] >= tp: return 1, k - start
        else:
            if h[k] >= stop_px: return 0, k - start
            if l[k] <= tp: return 1, k - start
    return None, 0


def build_symbol(sym, udby_prev):
    d1h = load_df(sym, "1h"); d1h = d1h[(d1h.index >= START_DATE) & (d1h.index <= END_DATE)].copy()
    df = compose_from_base(d1h, "12h"); df = df[(df.index >= START_DATE) & (df.index <= END_DATE)].copy()
    F = build_indicators(df)
    d1d = compose_from_base(d1h, "1d")
    hl1d = hull(d1d['close'], 78); hl1d_dir = (hl1d > hl1d.shift(3)).astype(int)*2-1
    rsi1d = rsi(d1d['close'], 14); ema1d = (d1d['close'] - ema(d1d['close'], 200))/d1d['close']*100
    for s in (hl1d_dir, rsi1d, ema1d):
        s.index = s.index + pd.Timedelta(days=1)
    h = df['high'].values; l = df['low'].values; c = df['close'].values
    n = len(df); times = df.index; dates = times.normalize()
    rows = []
    for i in range(200, n):
        ts = times[i]; f = F.iloc[i]
        if f.isna().any():
            continue
        base = f.to_dict()
        base['htf_hull1d'] = float(hl1d_dir.asof(ts)) if pd.notna(hl1d_dir.asof(ts)) else 0.0
        base['htf_rsi1d'] = float(rsi1d.asof(ts)) if pd.notna(rsi1d.asof(ts)) else 50.0
        base['htf_ema1d'] = float(ema1d.asof(ts)) if pd.notna(ema1d.asof(ts)) else 0.0
        base['usdtd_prev_ret'] = udby_prev.get(dates[i], 0.0)   # FIX: прошлый день
        base['hour'] = float(ts.hour); base['dow'] = float(ts.dayofweek)
        for side, stop_px in (('long', l[i]), ('short', h[i])):
            y, bars = label_dir(side, c[i], stop_px, h, l, i + 1, n)
            if y is None:
                continue
            risk_pct = (c[i] - stop_px) / c[i] if side == 'long' else (stop_px - c[i]) / c[i]
            if risk_pct < 0.003:   # отсекаем вырожденные микро-стопы (<0.3%) — неторгуемы
                continue
            rr = (TARGET/100.0) / risk_pct
            hours = max(1, (bars + 1) * 12)
            cost_R = (2*SIDE_COST + FUNDING_8H*hours/8.0) / risk_pct
            net_R = (rr if y == 1 else -1.0) - cost_R
            r = dict(base)
            r.update({'side_long': 1 if side == 'long' else 0, 'symbol': sym, 'time': ts,
                      'y': y, 'risk_pct': risk_pct*100, 'rr': rr, 'net_R': net_R})
            rows.append(r)
    return rows


def purged_cv(X, y, t, cols_idx, n_splits=5):
    order = np.argsort(t); folds = np.array_split(order, n_splits); aucs = []
    for f in folds:
        lo, hi = t[f].min(), t[f].max()
        keep = np.ones(len(y), bool); keep[f] = False
        keep &= ~((t + HORIZON_D >= lo - EMBARGO_D) & (t <= hi + EMBARGO_D))
        if keep.sum() < 500 or y[f].sum() < 20 or len(np.unique(y[keep])) < 2:
            continue
        m = HistGradientBoostingClassifier(max_iter=500, learning_rate=0.03, max_leaf_nodes=31,
            min_samples_leaf=80, l2_regularization=1.0, random_state=0).fit(X[np.ix_(keep, cols_idx)], y[keep])
        aucs.append(roc_auc_score(y[f], m.predict_proba(X[np.ix_(f, cols_idx)])[:, 1]))
    return (np.mean(aucs), len(aucs)) if aucs else (np.nan, 0)


def main():
    t0 = time.time()
    print("=" * 80)
    print("etap_191: ФИКС lookahead USDT.D + честный net_R payoff")
    print("=" * 80)
    ud = pd.read_csv(_ROOT / 'data' / 'USDT_D_1d.csv', parse_dates=['datetime'])
    udr = ud['close'].pct_change().fillna(0) * 100
    # FIX: возврат дня D приписываем дню D+1 (известен только после закрытия D)
    udby_prev = {pd.Timestamp(d).normalize() + pd.Timedelta(days=1): r
                 for d, r in zip(ud['datetime'], udr.values)}

    rows = []
    for sym in SYMBOLS:
        r = build_symbol(sym, udby_prev); rows.extend(r)
        s = pd.DataFrame(r)
        print(f"  [{sym}] {len(r)}  good%={s['y'].mean()*100:.1f}  baseline ΣnetR={s['net_R'].sum():+.0f}")
    df = pd.DataFrame(rows).sort_values('time').reset_index(drop=True)
    df['t_days'] = (df['time'] - df['time'].min()).dt.total_seconds()/86400.0
    df.to_csv(OUT / 'etap_191_dataset.csv', index=False)

    NONF = {'symbol', 'time', 'y', 't_days', 'risk_pct', 'rr', 'net_R'}
    feat = [c for c in df.columns if c not in NONF and df[c].dtype != object]
    df[feat] = df[feat].fillna(0)
    is_tr = (df['time'] < TRAIN_END).values
    X = df[feat].values; y = df['y'].values; t = df['t_days'].values
    Xtr, ytr, ttr = X[is_tr], y[is_tr], t[is_tr]
    te = df.loc[~is_tr].copy(); yte = te['y'].values
    Xte = te[feat].values

    market_idx = [i for i, c in enumerate(feat) if c not in GEOM]
    all_idx = list(range(len(feat)))
    cvA, kA = purged_cv(Xtr, ytr, ttr, all_idx)
    cvM, kM = purged_cv(Xtr, ytr, ttr, market_idx)
    clf = HistGradientBoostingClassifier(max_iter=600, learning_rate=0.03, max_leaf_nodes=31,
        min_samples_leaf=80, l2_regularization=1.0, early_stopping=True,
        validation_fraction=0.15, random_state=42).fit(Xtr, ytr)
    oos = roc_auc_score(yte, clf.predict_proba(Xte)[:, 1])
    print(f"\nПОСЛЕ ФИКСА: OOS AUC(all)={oos:.3f}  purgedCV(all)={cvA:.3f}  "
          f"purgedCV(market-only)={cvM:.3f}")

    te['p'] = clf.predict_proba(Xte)[:, 1]
    base = te['net_R'].sum()
    print(f"\nnet_R payoff (OOS): baseline n={len(te)} good%={yte.mean()*100:.1f} "
          f"ΣnetR={base:+.0f} R/tr={te['net_R'].mean():+.3f}")
    print(f"  {'τ':>5} {'n':>6} {'kept%':>6} {'good%':>6} {'rr_med':>7} {'ΣnetR':>7} {'R/tr':>7}")
    sweep = []
    for tau in [0.40, 0.50, 0.60, 0.70]:
        sel = te[te.p >= tau]
        if len(sel) < 20:
            continue
        print(f"  {tau:>5.2f} {len(sel):>6} {len(sel)/len(te)*100:>5.0f} {sel['y'].mean()*100:>5.1f} "
              f"{sel['rr'].median():>7.2f} {sel['net_R'].sum():>+7.0f} {sel['net_R'].mean():>+7.3f}")
        sweep.append({'tau': tau, 'n': len(sel), 'good_pct': round(sel['y'].mean()*100, 1),
                      'sumR': round(sel['net_R'].sum(), 0), 'R_tr': round(sel['net_R'].mean(), 3)})
    pd.DataFrame(sweep).to_csv(OUT / 'etap_191_sweep.csv', index=False)

    # per-year + per-asset на τ=0.5
    sel = te[te.p >= 0.5].copy()
    print(f"\nτ=0.5 PER-YEAR:  ", end='')
    sel['yr'] = sel['time'].dt.year
    print("  ".join(f"{yr}:n{len(g)}/ΣR{g['net_R'].sum():+.0f}/R/tr{g['net_R'].mean():+.2f}"
                    for yr, g in sel.groupby('yr')))
    print(f"τ=0.5 PER-ASSET: ", end='')
    print("  ".join(f"{s}:n{len(g)}/ΣR{g['net_R'].sum():+.0f}/R/tr{g['net_R'].mean():+.2f}"
                    for s, g in sel.groupby('symbol')))

    print("\n" + "=" * 80)
    bad_y = sum(1 for _, g in sel.groupby(sel['time'].dt.year) if g['net_R'].mean() < 0)
    if oos > 0.55 and cvM > 0.53 and len(sel) > 100 and sel['net_R'].mean() > 0.1 and bad_y == 0:
        print(f"ВЫДЕРЖАЛО ФИКС: OOS AUC {oos:.3f}, market-only CV {cvM:.3f}, фильтр R/tr "
              f"{sel['net_R'].mean():+.3f}, 0 плохих лет. РЕАЛЬНЫЙ сигнал — стоит развивать.")
    else:
        print(f"После фикса: OOS AUC {oos:.3f}, market CV {cvM:.3f}, фильтр R/tr {sel['net_R'].mean():+.3f}, "
              f"bad years {bad_y}. См. таблицу — оценить, сколько edge'а было утечкой.")
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
