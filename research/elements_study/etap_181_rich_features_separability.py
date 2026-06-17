"""etap_181: разделимость good/bad Bulkowski-сигналов на ПОЛНОМ наборе фич проекта.

Задача (пользователь): на момент формирования сигнала научить модель отличать
удачные от неудачных и отсеять неудачные.

Прошлые попытки (175-180) кормили модель тонким контекстом (28 фич) или сырой
формой свечей → OOS AUC ~0.5. Честное слабое место: модель НЕ видела накопленный
alpha проекта. Здесь даём ей ВСЁ из etap_170 (~250 фич, lookahead уже исправлен):
  • зоны OB/FVG на 1h/2h/4h/12h/1d (кол-во / дистанция / in-zone / СИЛА: age/width/
    touch_count), раздельно LONG/SHORT;
  • multi-TF Hull(78) dir (1d/4h), EMA-200, RSI, vol-z, ATR%;
  • sweep-история BSL/SSL (24/72/168h) + failed-sweep;
  • Lopez-микроструктура: FFD, SADF, Amihud, VPIN, Roll, Parkinson, Garman-Klass;
  • USDT.D (return/EMA50/RSI), block-orders proximity (1d/4h/12h), confluence, time.

Кандидаты = Bulkowski-детекторы (etap_172) на BTC+ETH+SOL.
Лейбл = симметричный first-touch ±5% (good=пошёл в сторону сигнала раньше -5%);
base rate ~50%, geometry-neutral — чистый вопрос разделимости.

Валидация честная: TRAIN<2024 / TEST≥2024; time-based purged CV (horizon 30д,
embargo 3д) на train; строгий OOS. Модели: HGB (GBM) + MLP (NN). + per-pattern OOS.

ВЕРДИКТ: если и с 250 фичами purged-CV И OOS ≤ ~0.55 везде — сигнал good/bad на
этом пуле не извлекаем НИКАКИМ инструментарием → потолок в источнике, не в фичах.

Output: output/etap_181_separability.csv, etap_181_importance.csv
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
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import roc_auc_score
from sklearn.inspection import permutation_importance

from data_manager import load_df, compose_from_base
from etap_172_bulkowski_patterns import DETECTORS, LOOKBACK, SWING_N
from etap_170_lopez_features import build_dataset, TARGETS

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
START_DATE = pd.Timestamp("2020-01-01", tz="UTC")
END_DATE = pd.Timestamp("2026-05-01", tz="UTC")
TRAIN_END = pd.Timestamp("2024-01-01", tz="UTC")
OUT = _ROOT / 'research' / 'elements_study' / 'output'

TARGET_PCT = 5.0
TIMEOUT_12H = 60
HORIZON_D = 30            # горизонт лейбла для purge
EMBARGO_D = 3

# колонки из etap_170, которые НЕ фичи (лейблы/идентификаторы/цены)
DROP = (['time', 'close', 'high', 'low', 'is_low_fractal', 'is_high_fractal',
         'move_after_low_pct', 'move_after_high_pct']
        + [f'y_low_strong_{int(t)}' for t in TARGETS]
        + [f'y_high_strong_{int(t)}' for t in TARGETS])


def label_symmetric(side, entry, h1, l1, start, end):
    if side == 'long':
        tp = entry * (1 + TARGET_PCT / 100); sl = entry * (1 - TARGET_PCT / 100)
    else:
        tp = entry * (1 - TARGET_PCT / 100); sl = entry * (1 + TARGET_PCT / 100)
    for k in range(start, end):
        hi = h1[k]; lo = l1[k]
        if side == 'long':
            hit_tp = hi >= tp; hit_sl = lo <= sl
        else:
            hit_tp = lo <= tp; hit_sl = hi >= sl
        if hit_sl:
            return 0
        if hit_tp:
            return 1
    return None


def signals_for(df12, h1, l1, c1, t1_ns):
    """Bulkowski-сигналы + good/bad лейбл, ключ = time(open 12h) + side + pattern."""
    times = df12['time'] if 'time' in df12.columns else pd.Series(df12.index)
    n = len(df12)
    rows = []
    for i in range(LOOKBACK + SWING_N + 2, n - SWING_N):
        for det in DETECTORS:
            sig = det(df12, i)
            if sig is None:
                continue
            side = sig['side']; entry = sig['breakout_price']
            t_open = times.iloc[i]
            t_close_ns = (t_open + pd.Timedelta(hours=12)).value
            start = int(np.searchsorted(t1_ns, t_close_ns, side='left'))
            if start >= len(c1):
                continue
            end = min(start + TIMEOUT_12H * 12, len(c1))
            y = label_symmetric(side, entry, h1, l1, start, end)
            if y is None:
                continue
            rows.append({'time': t_open, 'side_long': 1 if side == 'long' else 0,
                         'pattern': sig['pattern'], 'y': y})
    return pd.DataFrame(rows)


def build_symbol(sym, df_usdtd):
    def _clip(d):
        return d[(d.index >= START_DATE) & (d.index <= END_DATE)].copy()
    df_1h = _clip(load_df(sym, "1h"))
    df_1d = _clip(load_df(sym, "1d"))
    df_12h = _clip(compose_from_base(df_1h, "12h"))
    df_4h = _clip(compose_from_base(df_1h, "4h"))
    df_2h = _clip(compose_from_base(df_1h, "2h"))

    # 250 фич на каждый 12h-бар (lookahead исправлен в etap_170)
    feat = build_dataset(df_12h, df_1d, df_4h, df_2h, df_1h, df_usdtd)
    feat['time'] = pd.to_datetime(feat['time'], utc=True)

    # Bulkowski-сигналы на том же df_12h (time = open 12h-бара = feat['time'])
    df12r = df_12h.reset_index()
    df12r = df12r.rename(columns={df12r.columns[0]: 'time'})
    h1 = df_1h['high'].values.astype(float); l1 = df_1h['low'].values.astype(float)
    c1 = df_1h['close'].values.astype(float)
    t1_ns = df_1h.index.values.astype('datetime64[ns]').astype(np.int64)
    sig = signals_for(df12r, h1, l1, c1, t1_ns)
    sig['time'] = pd.to_datetime(sig['time'], utc=True)

    m = sig.merge(feat.drop(columns=[c for c in DROP if c in feat.columns and c != 'time']),
                  on='time', how='inner')
    m['symbol'] = sym
    return m


PAT_ID = {p: i for i, p in enumerate(sorted(
    ['big_w', 'big_m', 'db_eve_eve', 'hs_top', 'hs_bottom', 'triple_top', 'v_bottom',
     'v_top', 'rounding_bottom', 'cup_handle', 'barr_top', 'barr_bottom', 'diamond_top']))}


def purged_cv_auc(model_fn, X, y, t_days, n_splits=5):
    order = np.argsort(t_days)
    folds = np.array_split(order, n_splits)
    aucs = []
    for f in folds:
        lo, hi = t_days[f].min(), t_days[f].max()
        keep = np.ones(len(y), bool); keep[f] = False
        overlap = (t_days + HORIZON_D >= lo - EMBARGO_D) & (t_days <= hi + EMBARGO_D)
        keep &= ~overlap
        if keep.sum() < 100 or y[f].sum() < 3 or (1 - y[f]).sum() < 3 \
           or len(np.unique(y[keep])) < 2:
            continue
        m = model_fn().fit(X[keep], y[keep])
        aucs.append(roc_auc_score(y[f], m.predict_proba(X[f])[:, 1]))
    return (np.mean(aucs), np.std(aucs), len(aucs)) if aucs else (np.nan, np.nan, 0)


def hgb():
    return HistGradientBoostingClassifier(max_iter=400, learning_rate=0.04,
        max_leaf_nodes=31, min_samples_leaf=30, l2_regularization=1.0, random_state=0)


def mlp():
    return make_pipeline(StandardScaler(),
        MLPClassifier(hidden_layer_sizes=(128, 64), alpha=3e-3, max_iter=400,
                      early_stopping=True, n_iter_no_change=15, random_state=0))


def main():
    t0 = time.time()
    print("=" * 82)
    print("etap_181: разделимость good/bad · ПОЛНЫЙ набор фич проекта (~250) · HGB+MLP")
    print("=" * 82)
    up = _ROOT / 'data' / 'USDT_D_1d.csv'
    df_usdtd = None
    if up.exists():
        df_usdtd = pd.read_csv(up, index_col=0, parse_dates=True)
        if df_usdtd.index.tz is None:
            df_usdtd.index = df_usdtd.index.tz_localize('UTC')
        df_usdtd = df_usdtd[(df_usdtd.index >= START_DATE) & (df_usdtd.index <= END_DATE)]

    parts = []
    for sym in SYMBOLS:
        print(f"\n[{sym}] build_dataset (~250 фич)...")
        m = build_symbol(sym, df_usdtd)
        print(f"  сигналов с фичами: {len(m)}  good%={m['y'].mean()*100:.1f}")
        parts.append(m)
    df = pd.concat(parts, ignore_index=True).sort_values('time').reset_index(drop=True)
    df['pattern_id'] = df['pattern'].map(PAT_ID)
    df['t_days'] = (df['time'] - df['time'].min()).dt.total_seconds() / 86400.0

    feat_cols = [c for c in df.columns
                 if c not in ('time', 'symbol', 'pattern', 'y', 't_days')
                 and df[c].dtype != object]
    df[feat_cols] = df[feat_cols].fillna(0)
    print(f"\nВСЕГО сигналов: {len(df)}  фич: {len(feat_cols)}  good%={df['y'].mean()*100:.1f}")

    is_tr = (df['time'] < TRAIN_END).values
    Xtr, ytr, ttr = df.loc[is_tr, feat_cols].values, df.loc[is_tr, 'y'].values, df.loc[is_tr, 't_days'].values
    Xte, yte = df.loc[~is_tr, feat_cols].values, df.loc[~is_tr, 'y'].values

    print("\nAUC: 0.5=монетка. Сигнал есть только если purgedCV И OOS > ~0.55.")
    print(f"{'model':>6}  {'resub':>6}{'purgedCV':>9}{'±':>6}{'fld':>4}  {'OOS':>6}")
    results = []
    fitted = {}
    for name, fn in [('HGB', hgb), ('MLP', mlp)]:
        cv_m, cv_s, k = purged_cv_auc(fn, Xtr, ytr, ttr)
        clf = fn().fit(Xtr, ytr)
        fitted[name] = clf
        resub = roc_auc_score(ytr, clf.predict_proba(Xtr)[:, 1])
        oos = roc_auc_score(yte, clf.predict_proba(Xte)[:, 1])
        print(f"{name:>6}  {resub:>6.3f}{cv_m:>9.3f}{cv_s:>6.3f}{k:>4}  {oos:>6.3f}")
        results.append({'model': name, 'n_train': int(is_tr.sum()), 'n_test': int((~is_tr).sum()),
                        'base_te': round(float(yte.mean()), 3), 'resub_AUC': round(resub, 3),
                        'purgedCV_AUC': round(cv_m, 3), 'cv_std': round(cv_s, 3),
                        'cv_folds': k, 'OOS_AUC': round(oos, 3)})
    pd.DataFrame(results).to_csv(OUT / 'etap_181_separability.csv', index=False)

    # per-pattern OOS AUC (HGB) — вдруг отдельные паттерны разделяются
    print("\nper-pattern OOS AUC (HGB), n_test>=25:")
    te = df.loc[~is_tr].copy()
    pte = fitted['HGB'].predict_proba(Xte)[:, 1]
    te = te.assign(p=pte)
    for pat in sorted(te['pattern'].unique()):
        s = te[te.pattern == pat]
        if len(s) < 25 or s['y'].nunique() < 2:
            continue
        print(f"  {pat:>14}: n={len(s):>3} good%={s['y'].mean()*100:>4.0f}  "
              f"OOS_AUC={roc_auc_score(s['y'], s['p']):.3f}")

    # threshold sweep OOS (HGB) — даёт ли отсев прирост good%
    print("\nОтсев по P (HGB, OOS): улучшает ли good%?")
    base = yte.mean() * 100
    print(f"  baseline good%={base:.1f}  n={len(yte)}")
    for tau in [0.5, 0.55, 0.6, 0.65]:
        sel = te[te.p >= tau]
        if len(sel) < 10:
            continue
        print(f"  P≥{tau:.2f}: n={len(sel):>3} ({len(sel)/len(te)*100:>3.0f}%)  "
              f"good%={sel['y'].mean()*100:>4.1f}  Δ={sel['y'].mean()*100-base:>+4.1f}pp")

    # importance (permutation на OOS, HGB)
    pi = permutation_importance(fitted['HGB'], Xte, yte, n_repeats=8, random_state=0, scoring='roc_auc')
    imp = sorted(zip(feat_cols, pi.importances_mean, pi.importances_std), key=lambda x: -x[1])
    print("\nPermutation importance (OOS, HGB, top-15):")
    for nm, mn, st in imp[:15]:
        print(f"  {nm:>34}  {mn:+.4f} ± {st:.4f}")
    pd.DataFrame([{'feature': n, 'imp': m, 'std': s} for n, m, s in imp]).to_csv(
        OUT / 'etap_181_importance.csv', index=False)

    best = max(results, key=lambda r: r['OOS_AUC'])
    print("\n" + "=" * 82)
    if best['OOS_AUC'] > 0.55 and best['purgedCV_AUC'] > 0.55:
        print(f"СИГНАЛ: {best['model']} purgedCV={best['purgedCV_AUC']} OOS={best['OOS_AUC']} "
              f"→ есть на чём строить отсев. Дальше: threshold→PnL, per-pattern, TCN.")
    else:
        print(f"ВЕРДИКТ: лучший OOS_AUC={best['OOS_AUC']} (purgedCV={best['purgedCV_AUC']}).")
        print("  Даже с ~250 фичами проекта классы good/bad НЕ разделяются на честном OOS.")
        print("  Потолок не в фичах/модели — сигнал не в источнике (Bulkowski-пул = бета).")
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
