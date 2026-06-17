"""etap_189: МАКСИМАЛЬНАЯ попытка — предсказать «свеча даст +5% раньше снятия low/high».

Свободные руки (запрос пользователя): любые индикаторы, наши + классика TA. Две вещи,
не пробованные раньше: (1) ВЕСЬ универсум 12h-баров (а не только Bulkowski-сигналы) ×
BTC+ETH+SOL × оба направления → ~25-30k образцов (статистическая мощность; раньше
n_test=559 был мал); (2) широкий арсенал TA-индикаторов.

ЗАДАЧА (лейбл пользователя): для свечи i,
  long  good(1) = цена прошла +5% ВВЕРХ раньше, чем low(i) был снят (low <= low(i));
  short good(1) = цена прошла -5% ВНИЗ  раньше, чем high(i) был снят (high >= high(i));
  стоп первым при касании в одном баре (консерв.), таймаут 120×12h=60д → выброс.
Каждая свеча → 2 образца (long-гипотеза + short-гипотеза). Резолв на 12h.

ИНДИКАТОРЫ (всё ≤ i, без lookahead, вручную — без TA-Lib):
  тренд: EMA 20/50/100/200 dist, Hull(78) slope, MA-кроссы;
  моментум: RSI14, Stoch %K/%D, Williams %R, CCI, ROC 3/6/12, MACD line/sig/hist;
  волатильность: ATR%, Bollinger %b + bandwidth, Keltner pos, Parkinson, realized-vol;
  объём: vol-z, OBV slope, MFI;
  каналы: Donchian pos 20/55, dist 30d/90d hi/lo;
  сила тренда: ADX/DMI(+DI/-DI);
  свеча: body/wicks/close_pos/range-atr/gap;
  sweep: пробой recent hi/lo (24/72/168h) + failed;
  macro: USDT.D 1d ret; HTF: 1d Hull dir / RSI / EMA200 dist; время: hour/dow; side.

Валидация: TRAIN<2024 / TEST≥2024; time-based purged CV (h=60д, emb=3д); HGB.
При больших n: реальный edge если purgedCV И OOS AUC > 0.55. + per-asset + threshold.

Output: output/etap_189_dataset.csv, etap_189_importance.csv
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

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
START_DATE = pd.Timestamp("2020-01-01", tz="UTC")
END_DATE = pd.Timestamp("2026-05-01", tz="UTC")
TRAIN_END = pd.Timestamp("2024-01-01", tz="UTC")
OUT = _ROOT / 'research' / 'elements_study' / 'output'
TARGET = 5.0
TIMEOUT = 120
HORIZON_D = 60
EMBARGO_D = 3


def ema(s, n): return s.ewm(span=n, adjust=False).mean()
def sma(s, n): return s.rolling(n).mean()


def rsi(s, n=14):
    d = s.diff(); g = d.clip(lower=0); l = (-d).clip(lower=0)
    ag = g.ewm(alpha=1/n, adjust=False).mean(); al = l.ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + ag / al.replace(0, np.nan))


def true_range(df):
    pc = df['close'].shift()
    return pd.concat([df['high']-df['low'], (df['high']-pc).abs(), (df['low']-pc).abs()], axis=1).max(axis=1)


def atr(df, n=14): return true_range(df).ewm(alpha=1/n, adjust=False).mean()


def wma(s, n):
    w = np.arange(1, n+1)
    return s.rolling(n).apply(lambda x: np.dot(x, w)/w.sum(), raw=True)


def hull(s, n=78):
    return wma(2*wma(s, n//2) - wma(s, n), int(np.sqrt(n)))


def adx(df, n=14):
    up = df['high'].diff(); dn = -df['low'].diff()
    plus = ((up > dn) & (up > 0)) * up
    minus = ((dn > up) & (dn > 0)) * dn
    tr = true_range(df).ewm(alpha=1/n, adjust=False).mean()
    pdi = 100 * plus.ewm(alpha=1/n, adjust=False).mean() / tr.replace(0, np.nan)
    mdi = 100 * minus.ewm(alpha=1/n, adjust=False).mean() / tr.replace(0, np.nan)
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return pdi, mdi, dx.ewm(alpha=1/n, adjust=False).mean()


def mfi(df, n=14):
    tp = (df['high'] + df['low'] + df['close']) / 3
    mf = tp * df['volume']
    pos = mf.where(tp > tp.shift(), 0.0).rolling(n).sum()
    neg = mf.where(tp < tp.shift(), 0.0).rolling(n).sum()
    return 100 - 100 / (1 + pos / neg.replace(0, np.nan))


def build_indicators(df):
    """Все индикаторы как столбцы (≤ i). df 12h. Возвращает DataFrame фич."""
    o, h, l, c, v = df['open'], df['high'], df['low'], df['close'], df['volume']
    F = pd.DataFrame(index=df.index)
    rng = (h - l).replace(0, np.nan)
    a = atr(df, 14)
    # тренд
    for n in (20, 50, 100, 200):
        F[f'ema{n}_dist'] = (c - ema(c, n)) / c * 100
    hl = hull(c, 78)
    F['hull_slope'] = (hl - hl.shift(3)) / hl.shift(3) * 100
    F['ema20_50_cross'] = (ema(c, 20) - ema(c, 50)) / c * 100
    # моментум
    F['rsi14'] = rsi(c, 14)
    lo14 = l.rolling(14).min(); hi14 = h.rolling(14).max()
    F['stoch_k'] = 100 * (c - lo14) / (hi14 - lo14).replace(0, np.nan)
    F['stoch_d'] = F['stoch_k'].rolling(3).mean()
    F['williams_r'] = -100 * (hi14 - c) / (hi14 - lo14).replace(0, np.nan)
    tp = (h + l + c) / 3
    F['cci'] = (tp - sma(tp, 20)) / (0.015 * (tp - sma(tp, 20)).abs().rolling(20).mean())
    for n in (3, 6, 12):
        F[f'roc{n}'] = (c / c.shift(n) - 1) * 100
    macd = ema(c, 12) - ema(c, 26); sig = ema(macd, 9)
    F['macd'] = macd / c * 100; F['macd_sig'] = sig / c * 100; F['macd_hist'] = (macd - sig) / c * 100
    # волатильность
    F['atr_pct'] = a / c * 100
    bb_m = sma(c, 20); bb_s = c.rolling(20).std()
    F['bb_pctb'] = (c - (bb_m - 2*bb_s)) / (4*bb_s).replace(0, np.nan)
    F['bb_bw'] = (4*bb_s) / bb_m * 100
    F['keltner_pos'] = (c - ema(c, 20)) / (2 * a).replace(0, np.nan)
    F['parkinson'] = np.sqrt((np.log(h/l)**2).rolling(14).mean() / (4*np.log(2)))
    F['realized_vol'] = np.log(c/c.shift()).rolling(14).std() * 100
    # объём
    F['vol_z20'] = (v - sma(v, 20)) / v.rolling(20).std().replace(0, np.nan)
    obv = (np.sign(c.diff()).fillna(0) * v).cumsum()
    F['obv_slope'] = (obv - obv.shift(10)) / v.rolling(20).mean().replace(0, np.nan)
    F['mfi14'] = mfi(df, 14)
    # каналы
    for n in (20, 55):
        dlo = l.rolling(n).min(); dhi = h.rolling(n).max()
        F[f'donch_pos{n}'] = (c - dlo) / (dhi - dlo).replace(0, np.nan)
    F['dist_30d_hi'] = (h.rolling(60).max() - c) / c * 100
    F['dist_30d_lo'] = (c - l.rolling(60).min()) / c * 100
    F['dist_90d_hi'] = (h.rolling(180).max() - c) / c * 100
    F['dist_90d_lo'] = (c - l.rolling(180).min()) / c * 100
    # сила тренда
    pdi, mdi, adxv = adx(df, 14)
    F['adx'] = adxv; F['di_diff'] = pdi - mdi
    # свеча
    F['body_pct'] = (c - o).abs() / rng
    F['upper_wick'] = (h - np.maximum(o, c)) / rng
    F['lower_wick'] = (np.minimum(o, c) - l) / rng
    F['close_pos'] = (c - l) / rng
    F['range_atr'] = rng / a.replace(0, np.nan)
    F['gap'] = (o - c.shift()) / c.shift() * 100
    F['is_bull'] = (c > o).astype(float)
    # sweep history
    for wh, wb in [(24, 2), (72, 6), (168, 14)]:
        ph = h.shift().rolling(wb).max(); pl = l.shift().rolling(wb).min()
        F[f'swept_hi_{wh}'] = (h > ph).astype(float)
        F[f'swept_lo_{wh}'] = (l < pl).astype(float)
        F[f'failed_hi_{wh}'] = ((h > ph) & (c < ph)).astype(float)
        F[f'failed_lo_{wh}'] = ((l < pl) & (c > pl)).astype(float)
    return F


def label_dir(side, entry, stop_px, h, l, start, n):
    """good=1 если +TARGET% в сторону раньше снятия stop_px. None=timeout."""
    end = min(start + TIMEOUT, n)
    if side == 'long':
        tp = entry * (1 + TARGET/100)
    else:
        tp = entry * (1 - TARGET/100)
    for k in range(start, end):
        if side == 'long':
            if l[k] <= stop_px: return 0
            if h[k] >= tp: return 1
        else:
            if h[k] >= stop_px: return 0
            if l[k] <= tp: return 1
    return None


def build_symbol(sym, udby):
    d1h = load_df(sym, "1h")
    d1h = d1h[(d1h.index >= START_DATE) & (d1h.index <= END_DATE)].copy()
    df = compose_from_base(d1h, "12h")
    df = df[(df.index >= START_DATE) & (df.index <= END_DATE)].copy()
    F = build_indicators(df)
    # HTF 1d
    d1d = compose_from_base(d1h, "1d")
    hl1d = hull(d1d['close'], 78); hl1d_dir = (hl1d > hl1d.shift(3)).astype(int)*2-1
    rsi1d = rsi(d1d['close'], 14); ema1d = (d1d['close'] - ema(d1d['close'], 200)) / d1d['close'] * 100
    for s in (hl1d_dir, rsi1d, ema1d):
        s.index = s.index + pd.Timedelta(days=1)   # known at close
    h = df['high'].values; l = df['low'].values; c = df['close'].values
    n = len(df); times = df.index
    dates = times.normalize()

    rows = []
    for i in range(200, n):           # достаточно истории для индикаторов
        ts = times[i]
        f = F.iloc[i]
        if f.isna().any():
            continue
        base = f.to_dict()
        base['htf_hull1d'] = float(hl1d_dir.asof(ts)) if pd.notna(hl1d_dir.asof(ts)) else 0.0
        base['htf_rsi1d'] = float(rsi1d.asof(ts)) if pd.notna(rsi1d.asof(ts)) else 50.0
        base['htf_ema1d'] = float(ema1d.asof(ts)) if pd.notna(ema1d.asof(ts)) else 0.0
        base['usdtd_1d_ret'] = udby.get(dates[i], 0.0)
        base['hour'] = float(ts.hour); base['dow'] = float(ts.dayofweek)
        for side, stop_px in (('long', l[i]), ('short', h[i])):
            y = label_dir(side, c[i], stop_px, h, l, i + 1, n)
            if y is None:
                continue
            r = dict(base)
            r['side_long'] = 1 if side == 'long' else 0
            r['symbol'] = sym; r['time'] = ts; r['y'] = y
            rows.append(r)
    return rows


def purged_cv(X, y, t, n_splits=5):
    order = np.argsort(t); folds = np.array_split(order, n_splits); aucs = []
    for f in folds:
        lo, hi = t[f].min(), t[f].max()
        keep = np.ones(len(y), bool); keep[f] = False
        keep &= ~((t + HORIZON_D >= lo - EMBARGO_D) & (t <= hi + EMBARGO_D))
        if keep.sum() < 500 or y[f].sum() < 20 or len(np.unique(y[keep])) < 2:
            continue
        m = HistGradientBoostingClassifier(max_iter=500, learning_rate=0.03,
            max_leaf_nodes=31, min_samples_leaf=80, l2_regularization=1.0, random_state=0).fit(X[keep], y[keep])
        aucs.append(roc_auc_score(y[f], m.predict_proba(X[f])[:, 1]))
    return (np.mean(aucs), np.std(aucs), len(aucs)) if aucs else (np.nan, np.nan, 0)


def main():
    t0 = time.time()
    print("=" * 84)
    print("etap_189: предсказать +5%>снятие low/high · ВЕСЬ универсум 12h · ~50 TA-индикаторов")
    print("=" * 84)
    ud = pd.read_csv(_ROOT / 'data' / 'USDT_D_1d.csv', parse_dates=['datetime'])
    udr = ud['close'].pct_change().fillna(0) * 100
    udby = {pd.Timestamp(d).normalize(): r for d, r in zip(ud['datetime'], udr.values)}

    rows = []
    for sym in SYMBOLS:
        r = build_symbol(sym, udby)
        rows.extend(r); s = pd.DataFrame(r)
        print(f"  [{sym}] образцов: {len(r)}  good%={s['y'].mean()*100:.1f}")
    df = pd.DataFrame(rows).sort_values('time').reset_index(drop=True)
    df['t_days'] = (df['time'] - df['time'].min()).dt.total_seconds() / 86400.0
    df.to_csv(OUT / 'etap_189_dataset.csv', index=False)

    feat = [c for c in df.columns if c not in ('symbol', 'time', 'y', 't_days') and df[c].dtype != object]
    df[feat] = df[feat].fillna(0)
    is_tr = (df['time'] < TRAIN_END).values
    Xtr, ytr, ttr = df.loc[is_tr, feat].values, df.loc[is_tr, 'y'].values, df.loc[is_tr, 't_days'].values
    te = df.loc[~is_tr]; Xte, yte = te[feat].values, te['y'].values

    print(f"\nВСЕГО: {len(df)}  фич: {len(feat)}  good% TRAIN={ytr.mean()*100:.1f} TEST={yte.mean()*100:.1f}")
    cv_m, cv_s, k = purged_cv(Xtr, ytr, ttr)
    clf = HistGradientBoostingClassifier(max_iter=600, learning_rate=0.03, max_leaf_nodes=31,
        min_samples_leaf=80, l2_regularization=1.0, early_stopping=True,
        validation_fraction=0.15, random_state=42).fit(Xtr, ytr)
    resub = roc_auc_score(ytr, clf.predict_proba(Xtr)[:, 1])
    oos = roc_auc_score(yte, clf.predict_proba(Xte)[:, 1])
    print(f"\nHGB: resub AUC={resub:.3f}  purgedCV={cv_m:.3f}±{cv_s:.3f} (folds {k})  OOS={oos:.3f}")
    print(f"  (при n_test={len(yte)} AUC значим: ±{0.5/np.sqrt(min(yte.sum(),(1-yte).sum())):.3f} ~1σ)")

    # per-asset + per-side OOS
    print("\nOOS AUC per-asset / per-side:")
    tep = te.assign(p=clf.predict_proba(Xte)[:, 1])
    for sym in SYMBOLS:
        s = tep[tep.symbol == sym]
        if s['y'].nunique() == 2:
            print(f"  {sym}: AUC={roc_auc_score(s['y'], s['p']):.3f} (n={len(s)}, good%={s['y'].mean()*100:.0f})")
    for sd, nm in [(1, 'long'), (0, 'short')]:
        s = tep[tep.side_long == sd]
        if s['y'].nunique() == 2:
            print(f"  {nm}: AUC={roc_auc_score(s['y'], s['p']):.3f} (n={len(s)})")

    # threshold sweep
    print("\nОтсев по P (OOS): улучшает ли good%?")
    base = yte.mean()*100
    for tau in [0.5, 0.6, 0.7, 0.8]:
        sel = tep[tep.p >= tau]
        if len(sel) < 30: continue
        print(f"  P≥{tau:.2f}: n={len(sel):>5} ({len(sel)/len(tep)*100:>3.0f}%)  good%={sel['y'].mean()*100:>4.1f}  Δ={sel['y'].mean()*100-base:>+4.1f}pp")

    pi = permutation_importance(clf, Xte, yte, n_repeats=5, random_state=0, scoring='roc_auc')
    imp = sorted(zip(feat, pi.importances_mean, pi.importances_std), key=lambda x: -x[1])
    print("\nPermutation importance (OOS, top-15):")
    for nm, mn, st in imp[:15]:
        print(f"  {nm:>16}  {mn:+.4f} ± {st:.4f}")
    pd.DataFrame([{'feature': n, 'imp': m, 'std': s} for n, m, s in imp]).to_csv(OUT / 'etap_189_importance.csv', index=False)

    print("\n" + "=" * 84)
    if oos > 0.55 and cv_m > 0.55:
        print(f"ЕСТЬ СИГНАЛ: OOS AUC={oos:.3f}, purgedCV={cv_m:.3f} на n={len(df)}. Предсказуемо — строим фильтр.")
    elif oos > 0.53:
        print(f"СЛАБЫЙ СИГНАЛ: OOS AUC={oos:.3f} (>0.53 но <0.55). Есть намёк, маленький эффект.")
    else:
        print(f"НЕТ: OOS AUC={oos:.3f} даже на ~{len(df)} образцах и ~50 индикаторах. Задача непредсказуема")
        print("  из пред-входной TA-информации — это свойство рынка, не нехватка фич/данных.")
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
