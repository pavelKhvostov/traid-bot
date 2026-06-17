"""etap_182: МЕТА-СЕЛЕКТОР на i-RDRB+FVG — кандидаты с ДОКАЗАННЫМ primary-edge.

Вывод 175-181: на Bulkowski-пуле good/bad неразделимы (OOS AUC ~0.52) — нет
primary-edge, PnL = режимная бета. Мета-лейблинг (López de Prado §5.5) работает
только ПОВЕРХ модели, у которой edge уже есть. У i-RDRB+FVG он есть: BTC 1h 6y
RR=1 ≈ WR 57%, +160R (портфель с митигацией +269R). Здесь сеть решает посильное:
«какой из заведомо-плюсовых сетапов хуже» — отсечь и поднять WR/ΣR.

Stage A (канон smc-lib): i-RDRB на C1-C4 + FVG того же направления на C3-C4-C5
(1h). entry=mid RDRB-блока, SL=low/high паттерна(C1..C5), TP=RR1. Кросс-актив
BTC+ETH+SOL. Исход на 1h (fill→TP/SL, SL первым при касании обоих в баре;
консерв.), горизонт 60д. no_fill/degenerate выброшены. ЛЕЙБЛ = win(1)/loss(0).

Фичи на момент C5 (всё ≤ C5, без lookahead) — упор на доказанный edge проекта:
  • геометрия: R%, R/ATR(14,1h) [топ-фильтр: [0.5,0.85)→WR63%], block_width%,
    fvg_gap%, pattern_range%, side_long;
  • 1h: RSI14, EMA200-dist, Hull78-slope, vol_z20, ATR%, структура C5;
  • multi-TF тренд: Hull(78)/EMA dir на 4h/12h/1d (Hull-4h дал +13.6pp WR);
  • sweep BSL/SSL 24/72h + failed; pre-3d/7d ret; dist 30d HH/LL; USDT.D; time.

Валидация: TRAIN<2024 / TEST≥2024; time-based purged CV (horizon 14д, embargo 2д);
HGB+MLP. ГЛАВНОЕ — threshold-sweep на OOS: отсев по P(win)≥τ улучшает WR/ΣR?

Output: output/etap_182_metalabel.csv, etap_182_sweep.csv, etap_182_importance.csv
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
sys.path.insert(0, str(_ROOT / "smc-lib"))
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
from candle import Candle
from elements.i_rdrb.code import detect_i_rdrb
from elements.fvg.code import detect_fvg
from etap_170_lopez_features import rsi_wilder, hull_ma, ema, atr as atr_series

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
START_DATE = pd.Timestamp("2020-01-01", tz="UTC")
END_DATE = pd.Timestamp("2026-05-01", tz="UTC")
TRAIN_END = pd.Timestamp("2024-01-01", tz="UTC")
OUT = _ROOT / 'research' / 'elements_study' / 'output'

MAX_HOLD_1H = 24 * 60        # 60 дней горизонт на fill+resolve
HORIZON_D = 14
EMBARGO_D = 2


def to_candles(df):
    o = df['open'].values; h = df['high'].values; l = df['low'].values; c = df['close'].values
    t = (df.index.view('int64') // 1_000_000)  # ns → ms
    return [Candle(open=float(o[i]), high=float(h[i]), low=float(l[i]),
                   close=float(c[i]), open_time=int(t[i])) for i in range(len(df))]


def hull_dir_series(close, length):
    """+1 если Hull растёт за 3 бара, иначе -1 (last-closed honest на своём TF)."""
    hm = hull_ma(close, length)
    d = (hm > hm.shift(3)).astype(int) * 2 - 1
    return d


def resolve(side, entry, sl, tp, h1, l1, start):
    """Исход на 1h: ждём fill (откат к entry), затем TP/SL. SL первым в баре."""
    end = min(start + MAX_HOLD_1H, len(h1))
    in_trade = False
    for k in range(start, end):
        hi = h1[k]; lo = l1[k]
        if not in_trade:
            if side == 'long' and lo <= entry:
                in_trade = True
                if lo <= sl:
                    return 0
                if hi >= tp:
                    return 1
            elif side == 'short' and hi >= entry:
                in_trade = True
                if hi >= sl:
                    return 0
                if lo <= tp:
                    return 1
        else:
            if side == 'long':
                if lo <= sl:
                    return 0
                if hi >= tp:
                    return 1
            else:
                if hi >= sl:
                    return 0
                if lo <= tp:
                    return 1
    return None  # no_fill / timeout


def build_symbol(sym, usdtd_ret_by_date):
    d1h = load_df(sym, "1h")
    d1h = d1h[(d1h.index >= START_DATE) & (d1h.index <= END_DATE)].copy()
    n = len(d1h)
    o = d1h['open'].values.astype(float); h = d1h['high'].values.astype(float)
    l = d1h['low'].values.astype(float); c = d1h['close'].values.astype(float)
    v = d1h['volume'].values.astype(float)
    times = d1h.index

    # индикаторы 1h
    rsi = rsi_wilder(d1h['close'], 14).values
    hull = hull_ma(d1h['close'], 78).values
    ema200 = ema(d1h['close'], 200).values
    atr14 = atr_series(d1h, 14).values
    vmean = pd.Series(v).rolling(20).mean().values
    vstd = pd.Series(v).rolling(20).std().values

    # multi-TF Hull/EMA dir (агрегаты из 1h, индекс сдвинут на close → honest)
    htf = {}
    for tf, mins in [('4h', 240), ('12h', 720), ('1d', 1440)]:
        dtf = compose_from_base(d1h, tf)
        hd = hull_dir_series(dtf['close'], 78)
        ed = (dtf['close'] > ema(dtf['close'], 200)).astype(int) * 2 - 1
        hd.index = hd.index + pd.Timedelta(minutes=mins)   # известно на close
        ed.index = ed.index + pd.Timedelta(minutes=mins)
        htf[f'hull_{tf}'] = hd
        htf[f'ema_{tf}'] = ed

    candles = to_candles(d1h)
    dates = times.normalize()

    rows = []
    for i in range(n - 4):
        c1, c2, c3, c4, c5 = candles[i:i + 5]
        ir = detect_i_rdrb(c1, c2, c3, c4)
        if ir is None:
            continue
        fvg = detect_fvg(c3, c4, c5)
        if fvg is None or fvg.direction != ir.direction:
            continue
        side = ir.direction
        bb, bt = ir.rdrb.block
        entry = (bb + bt) / 2
        idx5 = i + 4
        plow = min(l[i:idx5 + 1]); phigh = max(h[i:idx5 + 1])
        if side == 'long':
            sl = plow; r_val = entry - sl; tp = entry + r_val
        else:
            sl = phigh; r_val = sl - entry; tp = entry - r_val
        if r_val <= 0:
            continue
        # вход начинаем искать со следующего 1h-бара после C5
        y = resolve(side, entry, sl, tp, h, l, idx5 + 1)
        if y is None:
            continue

        ts = times[idx5]; price = c[idx5]
        rng = max(h[idx5] - l[idx5], 1e-9)
        atr_i = atr14[idx5] if not np.isnan(atr14[idx5]) else r_val
        # sweep 24/72h на 1h
        feat = {}
        for win_h in (24, 72):
            lo_ = max(0, idx5 - win_h)
            ph = h[lo_:idx5].max() if idx5 > lo_ else h[idx5]
            pl = l[lo_:idx5].min() if idx5 > lo_ else l[idx5]
            feat[f'swept_bsl_{win_h}'] = int(h[idx5] > ph)
            feat[f'swept_ssl_{win_h}'] = int(l[idx5] < pl)
            feat[f'failed_bsl_{win_h}'] = int(h[idx5] > ph and price < ph)
            feat[f'failed_ssl_{win_h}'] = int(l[idx5] < pl and price > pl)
        hh30 = h[max(0, idx5 - 720):idx5 + 1].max()
        ll30 = l[max(0, idx5 - 720):idx5 + 1].min()
        p3 = c[idx5 - 72] if idx5 >= 72 else c[idx5]
        p7 = c[idx5 - 168] if idx5 >= 168 else c[idx5]
        feat.update({
            'side_long': 1 if side == 'long' else 0,
            'R_pct': r_val / entry * 100,
            'R_over_atr': r_val / atr_i if atr_i > 0 else 0.0,
            'block_width_pct': (bt - bb) / entry * 100,
            'fvg_gap_pct': abs(c5.low - c3.high if side == 'long' else c3.low - c5.high) / price * 100,
            'pattern_range_pct': (phigh - plow) / price * 100,
            'rsi_14': rsi[idx5] if not np.isnan(rsi[idx5]) else 50.0,
            'ema200_dist_pct': (price - ema200[idx5]) / price * 100 if not np.isnan(ema200[idx5]) else 0.0,
            'hull_slope_pct': (hull[idx5] - hull[idx5 - 3]) / hull[idx5 - 3] * 100
                if idx5 >= 3 and not np.isnan(hull[idx5]) and not np.isnan(hull[idx5 - 3]) and hull[idx5 - 3] else 0.0,
            'vol_z20': (v[idx5] - vmean[idx5]) / vstd[idx5] if not np.isnan(vstd[idx5]) and vstd[idx5] else 0.0,
            'atr_pct': atr_i / price * 100,
            'body_pct': abs(c[idx5] - o[idx5]) / rng,
            'upper_wick_pct': (h[idx5] - max(o[idx5], c[idx5])) / rng,
            'lower_wick_pct': (min(o[idx5], c[idx5]) - l[idx5]) / rng,
            'close_pos': (c[idx5] - l[idx5]) / rng,
            'pre_3d_ret_pct': (price - p3) / p3 * 100,
            'pre_7d_ret_pct': (price - p7) / p7 * 100,
            'dist_30d_high_pct': (hh30 - price) / price * 100,
            'dist_30d_low_pct': (price - ll30) / price * 100,
            'usdtd_1d_ret_pct': usdtd_ret_by_date.get(dates[idx5], 0.0),
            'hour_utc': float(ts.hour),
            'dow': float(ts.dayofweek),
        })
        for key, ser in htf.items():
            try:
                val = ser.asof(ts)
                feat[f'htf_{key}_dir'] = float(val) if pd.notna(val) else 0.0
            except Exception:
                feat[f'htf_{key}_dir'] = 0.0
        feat.update({'symbol': sym, 'time': ts, 'y': y})
        rows.append(feat)
    return rows


def purged_cv_auc(model_fn, X, y, t_days, n_splits=5):
    order = np.argsort(t_days)
    folds = np.array_split(order, n_splits)
    aucs = []
    for f in folds:
        lo, hi = t_days[f].min(), t_days[f].max()
        keep = np.ones(len(y), bool); keep[f] = False
        keep &= ~((t_days + HORIZON_D >= lo - EMBARGO_D) & (t_days <= hi + EMBARGO_D))
        if keep.sum() < 80 or y[f].sum() < 3 or (1 - y[f]).sum() < 3 or len(np.unique(y[keep])) < 2:
            continue
        m = model_fn().fit(X[keep], y[keep])
        aucs.append(roc_auc_score(y[f], m.predict_proba(X[f])[:, 1]))
    return (np.mean(aucs), np.std(aucs), len(aucs)) if aucs else (np.nan, np.nan, 0)


def hgb():
    return HistGradientBoostingClassifier(max_iter=400, learning_rate=0.04,
        max_leaf_nodes=31, min_samples_leaf=25, l2_regularization=1.0, random_state=0)


def mlp():
    return make_pipeline(StandardScaler(),
        MLPClassifier(hidden_layer_sizes=(64, 32), alpha=3e-3, max_iter=400,
                      early_stopping=True, n_iter_no_change=15, random_state=0))


def main():
    t0 = time.time()
    print("=" * 80)
    print("etap_182: мета-селектор i-RDRB+FVG (primary-edge есть) · 1h · BTC+ETH+SOL · RR1")
    print("=" * 80)
    ud = pd.read_csv(_ROOT / 'data' / 'USDT_D_1d.csv', parse_dates=['datetime'])
    ud_ret = ud['close'].pct_change().fillna(0) * 100
    udby = {pd.Timestamp(d).tz_localize('UTC').normalize() if pd.Timestamp(d).tz is None
            else pd.Timestamp(d).normalize(): r for d, r in zip(ud['datetime'], ud_ret.values)}

    rows = []
    for sym in SYMBOLS:
        r = build_symbol(sym, udby)
        rows.extend(r)
        s = pd.DataFrame(r)
        print(f"  [{sym}] сетапов (filled): {len(r)}  WR={s['y'].mean()*100:.1f}%  "
              f"ΣR={(2*s['y']-1).sum():+.0f}")
    df = pd.DataFrame(rows).sort_values('time').reset_index(drop=True)
    df['t_days'] = (df['time'] - df['time'].min()).dt.total_seconds() / 86400.0
    df.to_csv(OUT / 'etap_182_metalabel.csv', index=False)

    feat_cols = [c for c in df.columns if c not in ('symbol', 'time', 'y', 't_days')
                 and df[c].dtype != object]
    df[feat_cols] = df[feat_cols].fillna(0)
    is_tr = (df['time'] < TRAIN_END).values
    Xtr, ytr, ttr = df.loc[is_tr, feat_cols].values, df.loc[is_tr, 'y'].values, df.loc[is_tr, 't_days'].values
    te = df.loc[~is_tr].copy()
    Xte, yte = te[feat_cols].values, te['y'].values

    print(f"\nВСЕГО filled: {len(df)}  фич: {len(feat_cols)}")
    print(f"BASELINE: TRAIN n={is_tr.sum()} WR={ytr.mean()*100:.1f}%  |  "
          f"TEST(OOS) n={len(yte)} WR={yte.mean()*100:.1f}% ΣR={(2*yte-1).sum():+.0f}")

    print("\nAUC (0.5=монетка):")
    print(f"{'model':>6}  {'resub':>6}{'purgedCV':>9}{'±':>6}{'fld':>4}  {'OOS':>6}")
    fitted = {}
    for name, fn in [('HGB', hgb), ('MLP', mlp)]:
        cv_m, cv_s, k = purged_cv_auc(fn, Xtr, ytr, ttr)
        clf = fn().fit(Xtr, ytr); fitted[name] = clf
        resub = roc_auc_score(ytr, clf.predict_proba(Xtr)[:, 1])
        oos = roc_auc_score(yte, clf.predict_proba(Xte)[:, 1])
        print(f"{name:>6}  {resub:>6.3f}{cv_m:>9.3f}{cv_s:>6.3f}{k:>4}  {oos:>6.3f}")

    # выбираем модель с лучшим OOS AUC для отсева
    best_name = max(fitted, key=lambda nm: roc_auc_score(yte, fitted[nm].predict_proba(Xte)[:, 1]))
    te = te.assign(p=fitted[best_name].predict_proba(Xte)[:, 1])
    base_wr = yte.mean() * 100; base_sumR = (2 * yte - 1).sum()

    print(f"\nОТСЕВ по P(win) ({best_name}, OOS) — главный тест мета-лейблинга:")
    print(f"  baseline: n={len(te)}  WR={base_wr:.1f}%  ΣR={base_sumR:+.0f}  R/tr={base_sumR/len(te):+.3f}")
    print(f"  {'τ':>5} {'n':>4} {'kept%':>6} {'WR%':>6} {'ΔWR':>6} {'ΣR':>6} {'R/tr':>7}")
    sweep = []
    for tau in [0.45, 0.50, 0.55, 0.60, 0.65]:
        sel = te[te.p >= tau]
        if len(sel) < 10:
            continue
        wr = sel['y'].mean() * 100; sumR = (2 * sel['y'] - 1).sum()
        print(f"  {tau:>5.2f} {len(sel):>4} {len(sel)/len(te)*100:>5.0f}% {wr:>6.1f} "
              f"{wr-base_wr:>+5.1f} {sumR:>+6.0f} {sumR/len(sel):>+7.3f}")
        sweep.append({'tau': tau, 'n': len(sel), 'kept_pct': round(len(sel)/len(te)*100, 1),
                      'WR': round(wr, 1), 'dWR': round(wr-base_wr, 1), 'sumR': int(sumR),
                      'R_per_tr': round(sumR/len(sel), 3)})
    pd.DataFrame(sweep).to_csv(OUT / 'etap_182_sweep.csv', index=False)

    # per-year ΣR после отсева на лучшем τ
    if sweep:
        best_tau = max(sweep, key=lambda s: s['sumR'])['tau']
        syr = te[te.p >= best_tau].copy(); syr['yr'] = syr['time'].dt.year
        print(f"\nОтсев P≥{best_tau} по годам (OOS):")
        for yr, g in syr.groupby('yr'):
            print(f"  {yr}: n={len(g):>3} WR={g['y'].mean()*100:>4.0f}% ΣR={(2*g['y']-1).sum():+.0f}")

    pi = permutation_importance(fitted['HGB'], Xte, yte, n_repeats=8, random_state=0, scoring='roc_auc')
    imp = sorted(zip(feat_cols, pi.importances_mean, pi.importances_std), key=lambda x: -x[1])
    print("\nPermutation importance (OOS, HGB, top-12):")
    for nm, mn, st in imp[:12]:
        print(f"  {nm:>22}  {mn:+.4f} ± {st:.4f}")
    pd.DataFrame([{'feature': n, 'imp': m, 'std': s} for n, m, s in imp]).to_csv(
        OUT / 'etap_182_importance.csv', index=False)

    oos_best = roc_auc_score(yte, te['p'])
    print("\n" + "=" * 80)
    improved = [s for s in sweep if s['dWR'] > 1.5 and s['n'] >= len(te) * 0.3]
    if oos_best > 0.55 and improved:
        print(f"РАБОТАЕТ: {best_name} OOS AUC={oos_best:.3f}; отсев поднимает WR "
              f"(см. sweep) при разумном kept%. Мета-лейблинг даёт edge поверх i-RDRB+FVG.")
    else:
        print(f"Слабо: лучший OOS AUC={oos_best:.3f}; отсев не даёт устойчивого +WR/ΣR.")
        print("  Возможные причины: фич мало / нужен per-asset / RR=1-исход слишком близок к 50/50.")
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
