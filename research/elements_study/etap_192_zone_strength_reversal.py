"""etap_192: предсказание разворота через СИЛУ ЗОНЫ, в которую ПРИШЛА свеча.

Идея пользователя: развороты бьют от сильных multi-TF зон. Ключ — мерить зону у
ЭКСТРЕМУМА-фитиля свечи (low для long-разворота, high для short), а не у close
(этого не было в etap_181). Сила зоны = multi-TF confluence (OB+FVG на 4h/12h/1d,
same-direction support/resistance) + HTF-вес + untouched (свежесть). + индикаторы.

Кандидаты = Bulkowski reversal-сигналы (etap_172), BTC+ETH+SOL, 12h.
Лейбл = busted-условие пользователя (etap_177): success(1) = +5% в сторону сигнала
РАНЬШЕ снятия структурного low/high; резолв на 1h, таймаут.

Фичи СИЛЫ ЗОНЫ (на экстремуме, same-dir, born ≤ сигнала — без lookahead):
  zone_conf_count   — сколько HTF same-dir зон (OB/FVG × 4h/12h/1d) содержат экстремум;
  zone_strength     — Σ вес (4h=1,12h=2,1d=3) × (1.5 если untouched);
  in_htf_zone       — есть зона на 12h или 1d;
  nearest_zone_dist — % до ближайшей same-dir зоны;
  untouched_frac    — доля попавших зон, нетронутых до сигнала (магнит-эффект);
  n_untouched_htf   — untouched на 12h/1d.
+ индикаторы: rsi14, ema200_dist, hull_dir, atr_pct, vol_z, failed_sweep (оставим
  только дающие эффект — смотрим importance).

Валидация: TRAIN<2024/TEST≥2024, purged-CV + OOS, МОНОТОННОСТЬ success% по силе зоны
(интерпретируемо), net_R с издержками. Honest zone-birth shift (+tf) против lookahead.

Output: output/etap_192_zones.csv
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
from sklearn.inspection import permutation_importance

from data_manager import load_df, compose_from_base
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg
from etap_172_bulkowski_patterns import DETECTORS, LOOKBACK, SWING_N
from etap_175_metalabel_dataset import wilder_atr, detect_failed_sweep
from etap_177_label5pct_select import simulate_5pct
from etap_170_lopez_features import rsi_wilder, hull_ma, ema

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
START_DATE = pd.Timestamp("2020-01-01", tz="UTC")
END_DATE = pd.Timestamp("2026-05-01", tz="UTC")
TRAIN_END = pd.Timestamp("2024-01-01", tz="UTC")
OUT = _ROOT / 'research' / 'elements_study' / 'output'
HORIZON_D = 30; EMBARGO_D = 3
SIDE_COST = 0.0008
TF_W = {'4h': 1.0, '12h': 2.0, '1d': 3.0}     # HTF-вес
TF_MIN = {'4h': 240, '12h': 720, '1d': 1440}


def detect_zones(df_tf, tf):
    """OB+FVG зоны TF с birth=close cur-свечи (honest) + first_touch время."""
    zones = []
    idx = df_tf.index
    for j in range(2, len(df_tf)):
        z = detect_ob_pair(df_tf, j)
        if z is not None:
            zones.append({'b': z.bottom, 't': z.top, 'dir': z.direction,
                          'birth': z.cur_time + pd.Timedelta(minutes=TF_MIN[tf])})
        f = detect_fvg(df_tf, j)
        if f is not None:
            zones.append({'b': f.bottom, 't': f.top, 'dir': f.direction,
                          'birth': f.c2_time + pd.Timedelta(minutes=TF_MIN[tf])})
    # first_touch: первый бар после birth, чей [low,high] пересекает зону
    lows = df_tf['low']; highs = df_tf['high']
    for z in zones:
        sub_mask = (idx > z['birth']) & (lows <= z['t']) & (highs >= z['b'])
        ft = idx[sub_mask]
        z['first_touch'] = ft[0] if len(ft) else pd.Timestamp.max.tz_localize('UTC')
    return zones


def zone_features(extreme, sig_dir, ts, price, zones_by_tf):
    """Сила same-dir зон, содержащих экстремум, born ≤ ts."""
    want = 'LONG' if sig_dir == 'long' else 'SHORT'
    tol = price * 0.003
    conf = 0; strength = 0.0; in_htf = 0; n_unt = 0; n_unt_htf = 0
    nearest = 20.0; matched = 0
    for tf, zones in zones_by_tf.items():
        for z in zones:
            if z['dir'] != want or z['birth'] > ts:
                continue
            # дистанция экстремума до зоны
            if z['b'] - tol <= extreme <= z['t'] + tol:
                d = 0.0; hit = True
            else:
                d = (z['b'] - extreme if extreme < z['b'] else extreme - z['t']) / price * 100
                hit = d < 0.5
            if d < nearest:
                nearest = d
            if hit:
                conf += 1; matched += 1
                untouched = z['first_touch'] >= ts
                strength += TF_W[tf] * (1.5 if untouched else 1.0)
                if tf in ('12h', '1d'):
                    in_htf = 1
                    if untouched:
                        n_unt_htf += 1
                if untouched:
                    n_unt += 1
    return {
        'zone_conf_count': conf, 'zone_strength': strength, 'in_htf_zone': in_htf,
        'nearest_zone_dist': min(nearest, 20.0),
        'untouched_frac': n_unt / matched if matched else 0.0,
        'n_untouched_htf': n_unt_htf,
    }


def build_symbol(sym, udby):
    d1h = load_df(sym, "1h"); d1h = d1h[(d1h.index >= START_DATE) & (d1h.index <= END_DATE)].copy()
    d1d = load_df(sym, "1d"); d1d = d1d[(d1d.index >= START_DATE) & (d1d.index <= END_DATE)].copy()
    d4h = compose_from_base(d1h, "4h"); d4h = d4h[(d4h.index >= START_DATE) & (d4h.index <= END_DATE)].copy()
    d12 = compose_from_base(d1h, "12h"); d12 = d12[(d12.index >= START_DATE) & (d12.index <= END_DATE)].copy()

    zones_by_tf = {'4h': detect_zones(d4h, '4h'), '12h': detect_zones(d12, '12h'), '1d': detect_zones(d1d, '1d')}

    df12 = d12.reset_index()
    if 'time' not in df12.columns:
        df12 = df12.rename(columns={df12.columns[0]: 'time'})
    o = df12['open'].values; h = df12['high'].values; l = df12['low'].values; c = df12['close'].values
    v = df12['volume'].values; times = df12['time']; n = len(c)
    atr = wilder_atr(h, l, c)
    rsi = rsi_wilder(d12['close'], 14).values
    hull = hull_ma(d12['close'], 78).values
    ema200 = ema(d12['close'], 200).values
    vmean = pd.Series(v).rolling(20).mean().values; vstd = pd.Series(v).rolling(20).std().values
    h1 = d1h['high'].values.astype(float); l1 = d1h['low'].values.astype(float)
    c1 = d1h['close'].values.astype(float)
    t1_ns = d1h.index.values.astype('datetime64[ns]').astype(np.int64)
    dates = times.dt.normalize()

    rows = []
    for i in range(max(LOOKBACK + SWING_N + 2, 200), n - SWING_N):
        if atr[i] <= 0:
            continue
        fired = [s for s in (det(df12, i) for det in DETECTORS) if s is not None]
        if not fired:
            continue
        fs_l, fs_s, _ = detect_failed_sweep(h, l, c, i)
        ts = times.iloc[i]; price = c[i]
        ind = {
            'rsi14': rsi[i] if not np.isnan(rsi[i]) else 50.0,
            'ema200_dist': (price - ema200[i]) / price * 100 if not np.isnan(ema200[i]) else 0.0,
            'hull_dir': 1.0 if (i >= 3 and not np.isnan(hull[i]) and not np.isnan(hull[i-3]) and hull[i] > hull[i-3]) else -1.0,
            'atr_pct': atr[i] / price * 100,
            'vol_z': (v[i] - vmean[i]) / vstd[i] if not np.isnan(vstd[i]) and vstd[i] else 0.0,
        }
        t_close_ns = (ts + pd.Timedelta(hours=12)).value
        for sig in fired:
            side = sig['side']
            extreme = l[i] if side == 'long' else h[i]
            entry = sig['breakout_price']
            stop = sig['low_price'] if side == 'long' else sig['high_price']
            lab = simulate_5pct(side, entry, stop, h1, l1, c1, t1_ns, t_close_ns)
            if lab is None:
                continue
            zf = zone_features(extreme, side, ts, price, zones_by_tf)
            r = dict(ind); r.update(zf)
            r.update({'side_long': 1 if side == 'long' else 0,
                      'failed_sweep': int(fs_l if side == 'long' else fs_s),
                      'pattern': sig['pattern'], 'symbol': sym, 'time': ts,
                      'success': lab['success'], 'net_R': lab['net_R'], 'rr_at_target': lab['rr_at_target']})
            rows.append(r)
    return rows


def purged_cv(X, y, t):
    order = np.argsort(t); folds = np.array_split(order, 5); aucs = []
    for f in folds:
        lo, hi = t[f].min(), t[f].max()
        keep = np.ones(len(y), bool); keep[f] = False
        keep &= ~((t + HORIZON_D >= lo - EMBARGO_D) & (t <= hi + EMBARGO_D))
        if keep.sum() < 100 or y[f].sum() < 5 or len(np.unique(y[keep])) < 2:
            continue
        m = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
            min_samples_leaf=25, l2_regularization=1.0, random_state=0).fit(X[keep], y[keep])
        aucs.append(roc_auc_score(y[f], m.predict_proba(X[f])[:, 1]))
    return (np.mean(aucs), len(aucs)) if aucs else (np.nan, 0)


def main():
    t0 = time.time()
    print("=" * 80)
    print("etap_192: сила зоны прихода (multi-TF OB+FVG на экстремуме) → разворот +5%")
    print("=" * 80)
    ud = pd.read_csv(_ROOT / 'data' / 'USDT_D_1d.csv', parse_dates=['datetime'])
    udr = ud['close'].pct_change().fillna(0) * 100
    udby = {pd.Timestamp(d).normalize(): r for d, r in zip(ud['datetime'], udr.values)}

    rows = []
    for sym in SYMBOLS:
        r = build_symbol(sym, udby); rows.extend(r)
        print(f"  [{sym}] сигналов: {len(r)}")
    df = pd.DataFrame(rows).sort_values('time').reset_index(drop=True)
    df['t_days'] = (df['time'] - df['time'].min()).dt.total_seconds() / 86400.0
    df.to_csv(OUT / 'etap_192_zones.csv', index=False)

    ZONE_F = ['zone_conf_count', 'zone_strength', 'in_htf_zone', 'nearest_zone_dist',
              'untouched_frac', 'n_untouched_htf']
    IND_F = ['rsi14', 'ema200_dist', 'hull_dir', 'atr_pct', 'vol_z', 'failed_sweep', 'side_long']
    feat = ZONE_F + IND_F
    df[feat] = df[feat].fillna(0)
    is_tr = (df['time'] < TRAIN_END).values
    te = df.loc[~is_tr].copy()
    print(f"\nВСЕГО: {len(df)}  TRAIN {is_tr.sum()} / TEST {len(te)}  "
          f"baseline success% tr={df.loc[is_tr,'success'].mean()*100:.1f} te={te['success'].mean()*100:.1f}")

    # 1) МОНОТОННОСТЬ: success% по бакетам силы зоны (интерпретируемо, главное)
    print("\n1) success% по силе зоны (TEST) — растёт ли разворот с силой зоны:")
    te['zbucket'] = pd.qcut(te['zone_strength'].rank(method='first'), 4, labels=['Q1-слаб', 'Q2', 'Q3', 'Q4-сильн'])
    for b, g in te.groupby('zbucket'):
        print(f"   {b:>9}: n={len(g):>3}  success%={g['success'].mean()*100:>4.1f}  "
              f"strength∈[{g['zone_strength'].min():.0f},{g['zone_strength'].max():.0f}]  ΣnetR={g['net_R'].sum():+.1f}")
    print(f"   in_htf_zone=1: success%={te[te.in_htf_zone==1]['success'].mean()*100:.1f} (n={int((te.in_htf_zone==1).sum())})  "
          f"vs =0: {te[te.in_htf_zone==0]['success'].mean()*100:.1f}")
    # univariate AUC zone_strength
    a = roc_auc_score(te['success'], te['zone_strength']); a = max(a, 1-a)
    print(f"   univariate AUC(zone_strength) на TEST = {a:.3f}")

    # 2) модели: zone-only / ind-only / both
    Xtr_all = {nm: df.loc[is_tr, cols].values for nm, cols in
               [('zone', ZONE_F), ('ind', IND_F), ('both', feat)]}
    ytr = df.loc[is_tr, 'success'].values; yte = te['success'].values
    print("\n2) OOS AUC (purged-CV):")
    for nm, cols in [('zone-only', ZONE_F), ('ind-only', IND_F), ('zone+ind', feat)]:
        cv, k = purged_cv(df.loc[is_tr, cols].values, ytr, df.loc[is_tr, 't_days'].values)
        clf = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.04, max_leaf_nodes=15,
            min_samples_leaf=25, l2_regularization=1.0, random_state=42).fit(df.loc[is_tr, cols].values, ytr)
        oos = roc_auc_score(yte, clf.predict_proba(te[cols].values)[:, 1])
        print(f"   {nm:>10}: purgedCV={cv:.3f} (folds {k})  OOS={oos:.3f}")
        if nm == 'zone+ind':
            best = clf

    # 3) net_R: отсев по P + по силе зоны
    te['p'] = best.predict_proba(te[feat].values)[:, 1]
    base_r = te['net_R'].sum(); base_s = te['success'].mean()*100
    print(f"\n3) net_R: baseline n={len(te)} succ%={base_s:.1f} ΣnetR={base_r:+.1f} R/tr={te['net_R'].mean():+.3f}")
    for tau in [0.55, 0.6, 0.65]:
        sel = te[te.p >= tau]
        if len(sel) < 15:
            continue
        print(f"   P≥{tau}: n={len(sel):>3} succ%={sel['success'].mean()*100:>4.1f} "
              f"ΣnetR={sel['net_R'].sum():+.1f} R/tr={sel['net_R'].mean():+.3f}")
    # отсев просто по силе зоны (без ML)
    thr = df.loc[is_tr, 'zone_strength'].quantile(0.6)
    selz = te[te.zone_strength >= thr]
    print(f"   zone_strength≥{thr:.0f} (train-q60): n={len(selz)} succ%={selz['success'].mean()*100:.1f} "
          f"ΣnetR={selz['net_R'].sum():+.1f} R/tr={selz['net_R'].mean():+.3f}")

    pi = permutation_importance(best, te[feat].values, yte, n_repeats=8, random_state=0, scoring='roc_auc')
    imp = sorted(zip(feat, pi.importances_mean), key=lambda x: -x[1])
    print("\nPermutation importance (OOS):")
    for nm, mn in imp:
        print(f"   {nm:>18}  {mn:+.4f}")

    print("\n" + "=" * 80)
    oos_both = roc_auc_score(yte, best.predict_proba(te[feat].values)[:, 1])
    if a > 0.55 or oos_both > 0.56:
        print(f"ЭФФЕКТ ЕСТЬ: сила зоны несёт сигнал (uni AUC {a:.2f}, модель OOS {oos_both:.2f}). "
              f"Смотреть монотонность+net_R выше — конвертируется ли в торгуемое.")
    else:
        print(f"СЛАБО: uni AUC(zone_strength) {a:.2f}, модель OOS {oos_both:.2f} — сила зоны на этом")
        print("  пуле не отделяет удачный разворот от busted (или эффект в пределах шума).")
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
