"""etap_183: МЕТА-SIZING на i-RDRB+FVG — предсказывать магнитуду (MFE), не win/loss.

Вывод etap_182: бинарный RR1-исход не разделяется (OOS AUC 0.54). Новая постановка
(López de Prado §5.5 meta-labeling в роли sizing): возможно, БИНАРНЫЙ исход
непредсказуем, а МАГНИТУДА хода — частично да. Если сеть угадывает сетапы, которые
убегают далеко (MFE≥2-3R до стопа), селективное расширение TP на них даёт +R.

Prior (наша находка [[floating-tp-only-helps-low-wr-strategies]]): blanket-floating
не помогает high-WR (i-RDRB+FVG WR~63%). Но СЕЛЕКТИВНЫЙ per-setup RR — отдельный
вопрос. Проверяем честно.

Stage A = i-RDRB+FVG (канон smc-lib, 1h, BTC+ETH+SOL) — как etap_182, но для каждого
filled-сетапа считаем ПРОФИЛЬ исхода (MFE в R, hit_rr1/2/3 до стопа), не только win.
Цель классификатора: y_big = MFE≥2R до стопа. Фичи — те же ~36 (etap_182).

ГЛАВНЫЙ ТЕСТ (payoff на OOS): сравнить net_R политик —
  • baseline: fixed RR1 на всех (= +1 если hit_rr1 иначе -1);
  • selective: на предсказанных runner'ах (p_big≥τ) цель RR_target∈{2,3}
    (+RR_target если hit_rr{target} иначе -1), на остальных RR1.
Бьёт ли selective baseline по ΣR, и стабильно ли по годам?

Output: output/etap_183_metasizing.csv, etap_183_payoff.csv
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
from sklearn.metrics import roc_auc_score
from sklearn.inspection import permutation_importance

from data_manager import load_df, compose_from_base
from candle import Candle
from elements.i_rdrb.code import detect_i_rdrb
from elements.fvg.code import detect_fvg
from etap_170_lopez_features import rsi_wilder, hull_ma, ema, atr as atr_series
# переиспользуем готовые helpers из etap_182 (без повторного main)
from etap_182_irdrb_fvg_metalabel import (
    to_candles, hull_dir_series, purged_cv_auc, hgb, mlp,
    SYMBOLS, START_DATE, END_DATE, TRAIN_END, MAX_HOLD_1H)

OUT = _ROOT / 'research' / 'elements_study' / 'output'
BIG_RR = 2.0   # y_big = MFE >= 2R до стопа


def resolve_profile(side, entry, sl, r_val, h1, l1, start):
    """Профиль: filled? MFE в R, hit_rr1/2/3 (достигнуто ДО стопа). SL-first консерв."""
    end = min(start + MAX_HOLD_1H, len(h1))
    in_trade = False
    mfe = 0.0
    hr = {1.0: 0, 2.0: 0, 3.0: 0}
    for k in range(start, end):
        hi = h1[k]; lo = l1[k]
        if not in_trade:
            if (side == 'long' and lo <= entry) or (side == 'short' and hi >= entry):
                in_trade = True
            else:
                continue
        # in_trade (включая бар fill); сначала стоп (консерв.)
        sl_now = (lo <= sl) if side == 'long' else (hi >= sl)
        if sl_now:
            break
        fav = ((hi - entry) if side == 'long' else (entry - lo)) / r_val
        if fav > mfe:
            mfe = fav
        for rr in (1.0, 2.0, 3.0):
            if mfe >= rr:
                hr[rr] = 1
    if not in_trade:
        return None
    return {'mfe_R': float(mfe), 'hit_rr1': hr[1.0], 'hit_rr2': hr[2.0], 'hit_rr3': hr[3.0]}


def build_symbol(sym, usdtd_ret_by_date):
    d1h = load_df(sym, "1h")
    d1h = d1h[(d1h.index >= START_DATE) & (d1h.index <= END_DATE)].copy()
    n = len(d1h)
    o = d1h['open'].values.astype(float); h = d1h['high'].values.astype(float)
    l = d1h['low'].values.astype(float); c = d1h['close'].values.astype(float)
    v = d1h['volume'].values.astype(float)
    times = d1h.index

    rsi = rsi_wilder(d1h['close'], 14).values
    hull = hull_ma(d1h['close'], 78).values
    ema200 = ema(d1h['close'], 200).values
    atr14 = atr_series(d1h, 14).values
    vmean = pd.Series(v).rolling(20).mean().values
    vstd = pd.Series(v).rolling(20).std().values

    htf = {}
    for tf, mins in [('4h', 240), ('12h', 720), ('1d', 1440)]:
        dtf = compose_from_base(d1h, tf)
        hd = hull_dir_series(dtf['close'], 78); ed = (dtf['close'] > ema(dtf['close'], 200)).astype(int) * 2 - 1
        hd.index = hd.index + pd.Timedelta(minutes=mins); ed.index = ed.index + pd.Timedelta(minutes=mins)
        htf[f'hull_{tf}'] = hd; htf[f'ema_{tf}'] = ed

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
            sl = plow; r_val = entry - sl
        else:
            sl = phigh; r_val = sl - entry
        if r_val <= 0:
            continue
        prof = resolve_profile(side, entry, sl, r_val, h, l, idx5 + 1)
        if prof is None:
            continue

        ts = times[idx5]; price = c[idx5]; rng = max(h[idx5] - l[idx5], 1e-9)
        atr_i = atr14[idx5] if not np.isnan(atr14[idx5]) else r_val
        feat = {}
        for win_h in (24, 72):
            lo_ = max(0, idx5 - win_h)
            ph = h[lo_:idx5].max() if idx5 > lo_ else h[idx5]
            pl = l[lo_:idx5].min() if idx5 > lo_ else l[idx5]
            feat[f'swept_bsl_{win_h}'] = int(h[idx5] > ph); feat[f'swept_ssl_{win_h}'] = int(l[idx5] < pl)
            feat[f'failed_bsl_{win_h}'] = int(h[idx5] > ph and price < ph)
            feat[f'failed_ssl_{win_h}'] = int(l[idx5] < pl and price > pl)
        hh30 = h[max(0, idx5 - 720):idx5 + 1].max(); ll30 = l[max(0, idx5 - 720):idx5 + 1].min()
        p3 = c[idx5 - 72] if idx5 >= 72 else c[idx5]; p7 = c[idx5 - 168] if idx5 >= 168 else c[idx5]
        feat.update({
            'side_long': 1 if side == 'long' else 0,
            'R_pct': r_val / entry * 100, 'R_over_atr': r_val / atr_i if atr_i > 0 else 0.0,
            'block_width_pct': (bt - bb) / entry * 100,
            'fvg_gap_pct': abs(c5.low - c3.high if side == 'long' else c3.low - c5.high) / price * 100,
            'pattern_range_pct': (phigh - plow) / price * 100,
            'rsi_14': rsi[idx5] if not np.isnan(rsi[idx5]) else 50.0,
            'ema200_dist_pct': (price - ema200[idx5]) / price * 100 if not np.isnan(ema200[idx5]) else 0.0,
            'hull_slope_pct': (hull[idx5] - hull[idx5 - 3]) / hull[idx5 - 3] * 100
                if idx5 >= 3 and not np.isnan(hull[idx5]) and not np.isnan(hull[idx5 - 3]) and hull[idx5 - 3] else 0.0,
            'vol_z20': (v[idx5] - vmean[idx5]) / vstd[idx5] if not np.isnan(vstd[idx5]) and vstd[idx5] else 0.0,
            'atr_pct': atr_i / price * 100, 'body_pct': abs(c[idx5] - o[idx5]) / rng,
            'upper_wick_pct': (h[idx5] - max(o[idx5], c[idx5])) / rng,
            'lower_wick_pct': (min(o[idx5], c[idx5]) - l[idx5]) / rng,
            'close_pos': (c[idx5] - l[idx5]) / rng,
            'pre_3d_ret_pct': (price - p3) / p3 * 100, 'pre_7d_ret_pct': (price - p7) / p7 * 100,
            'dist_30d_high_pct': (hh30 - price) / price * 100, 'dist_30d_low_pct': (price - ll30) / price * 100,
            'usdtd_1d_ret_pct': usdtd_ret_by_date.get(dates[idx5], 0.0),
            'hour_utc': float(ts.hour), 'dow': float(ts.dayofweek),
        })
        for key, ser in htf.items():
            try:
                val = ser.asof(ts); feat[f'htf_{key}_dir'] = float(val) if pd.notna(val) else 0.0
            except Exception:
                feat[f'htf_{key}_dir'] = 0.0
        feat.update({'symbol': sym, 'time': ts, **prof,
                     'y_big': int(prof['mfe_R'] >= BIG_RR)})
        rows.append(feat)
    return rows


def main():
    t0 = time.time()
    print("=" * 80)
    print(f"etap_183: мета-SIZING i-RDRB+FVG · цель MFE≥{BIG_RR:.0f}R · 1h · BTC+ETH+SOL")
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
        print(f"  [{sym}] filled: {len(r)}  MFE≥2R: {s['y_big'].mean()*100:.1f}%  "
              f"hit_rr1: {s['hit_rr1'].mean()*100:.0f}%  hit_rr3: {s['hit_rr3'].mean()*100:.0f}%")
    df = pd.DataFrame(rows).sort_values('time').reset_index(drop=True)
    df['t_days'] = (df['time'] - df['time'].min()).dt.total_seconds() / 86400.0
    df.to_csv(OUT / 'etap_183_metasizing.csv', index=False)

    LEAK = {'symbol', 'time', 't_days', 'mfe_R', 'hit_rr1', 'hit_rr2', 'hit_rr3', 'y_big'}
    feat_cols = [c for c in df.columns if c not in LEAK and df[c].dtype != object]
    df[feat_cols] = df[feat_cols].fillna(0)
    is_tr = (df['time'] < TRAIN_END).values
    Xtr, ytr, ttr = df.loc[is_tr, feat_cols].values, df.loc[is_tr, 'y_big'].values, df.loc[is_tr, 't_days'].values
    te = df.loc[~is_tr].copy(); Xte, yte = te[feat_cols].values, te['y_big'].values

    print(f"\nВСЕГО filled: {len(df)}  фич: {len(feat_cols)}")
    print(f"y_big (MFE≥{BIG_RR:.0f}R): TRAIN {ytr.mean()*100:.1f}%  TEST {yte.mean()*100:.1f}%")

    print("\nРазделимость 'runner' (MFE≥2R), AUC 0.5=монетка:")
    print(f"{'model':>6}  {'resub':>6}{'purgedCV':>9}{'±':>6}{'fld':>4}  {'OOS':>6}")
    fitted = {}
    for name, fn in [('HGB', hgb), ('MLP', mlp)]:
        cv_m, cv_s, k = purged_cv_auc(fn, Xtr, ytr, ttr)
        clf = fn().fit(Xtr, ytr); fitted[name] = clf
        resub = roc_auc_score(ytr, clf.predict_proba(Xtr)[:, 1])
        oos = roc_auc_score(yte, clf.predict_proba(Xte)[:, 1])
        print(f"{name:>6}  {resub:>6.3f}{cv_m:>9.3f}{cv_s:>6.3f}{k:>4}  {oos:>6.3f}")
    best = max(fitted, key=lambda nm: roc_auc_score(yte, fitted[nm].predict_proba(Xte)[:, 1]))
    te = te.assign(p=fitted[best].predict_proba(Xte)[:, 1])

    # net_R по политике RR (на профиле hit_rr*): +RR если hit_rr{RR} иначе -1
    def net_rr(sub, rr):
        col = {1.0: 'hit_rr1', 2.0: 'hit_rr2', 3.0: 'hit_rr3'}[rr]
        return (sub[col] * (rr + 1) - 1).sum()   # +rr при hit, -1 иначе

    base_R = net_rr(te, 1.0)
    print(f"\nBASELINE OOS fixed-RR1: n={len(te)}  ΣR={base_R:+.0f}  R/tr={base_R/len(te):+.3f}")
    print(f"  (для справки: blanket RR2 ΣR={net_rr(te,2.0):+.0f}, RR3 ΣR={net_rr(te,3.0):+.0f})")

    print(f"\nPAYOFF: selective RR на runner'ах (p≥τ) + RR1 на остальных ({best}, OOS):")
    print(f"{'RRtgt':>5} {'τ':>5} {'n_big':>6} {'big%':>5} {'big_WR%':>7} {'ΣR':>6} {'Δvs base':>9}")
    payoff = []
    for rr_t in (2.0, 3.0):
        for tau in [0.30, 0.40, 0.50, 0.60]:
            big = te['p'] >= tau
            if big.sum() < 10:
                continue
            sub_big = te[big]; sub_rest = te[~big]
            r_big = net_rr(sub_big, rr_t); r_rest = net_rr(sub_rest, 1.0)
            tot = r_big + r_rest
            big_wr = {2.0: 'hit_rr2', 3.0: 'hit_rr3'}[rr_t]
            print(f"{rr_t:>5.0f} {tau:>5.2f} {big.sum():>6} {big.mean()*100:>4.0f}% "
                  f"{sub_big[big_wr].mean()*100:>6.0f}% {tot:>+6.0f} {tot-base_R:>+9.0f}")
            payoff.append({'rr_target': rr_t, 'tau': tau, 'n_big': int(big.sum()),
                           'sumR': int(tot), 'delta_vs_base': int(tot - base_R)})
    pd.DataFrame(payoff).to_csv(OUT / 'etap_183_payoff.csv', index=False)

    # лучшая политика по годам
    if payoff:
        bestp = max(payoff, key=lambda x: x['sumR'])
        rr_t, tau = bestp['rr_target'], bestp['tau']
        print(f"\nЛучшая политика RR{rr_t:.0f}@τ{tau} по годам (OOS) vs baseline RR1:")
        te2 = te.copy(); te2['yr'] = te2['time'].dt.year
        col_t = {2.0: 'hit_rr2', 3.0: 'hit_rr3'}[rr_t]
        for yr, g in te2.groupby('yr'):
            big = g['p'] >= tau
            sel = (g[big][col_t] * (rr_t + 1) - 1).sum() + (g[~big]['hit_rr1'] * 2 - 1).sum()
            base = (g['hit_rr1'] * 2 - 1).sum()
            print(f"  {yr}: n={len(g):>3}  selective ΣR={sel:+.0f}  baseline ΣR={base:+.0f}  Δ={sel-base:+.0f}")

    pi = permutation_importance(fitted['HGB'], Xte, yte, n_repeats=8, random_state=0, scoring='roc_auc')
    imp = sorted(zip(feat_cols, pi.importances_mean, pi.importances_std), key=lambda x: -x[1])
    print("\nPermutation importance для runner-предсказания (OOS, HGB, top-10):")
    for nm, mn, st in imp[:10]:
        print(f"  {nm:>22}  {mn:+.4f} ± {st:.4f}")

    oos_auc = roc_auc_score(yte, te['p'])
    bestp = max(payoff, key=lambda x: x['sumR']) if payoff else None
    print("\n" + "=" * 80)
    if oos_auc > 0.55 and bestp and bestp['delta_vs_base'] > 0.1 * abs(base_R):
        print(f"РАБОТАЕТ: runner OOS AUC={oos_auc:.3f}; selective RR{bestp['rr_target']:.0f}@τ{bestp['tau']} "
              f"даёт ΣR Δ={bestp['delta_vs_base']:+} над baseline. Мета-sizing имеет смысл.")
    else:
        d = bestp['delta_vs_base'] if bestp else 0
        print(f"Слабо: runner OOS AUC={oos_auc:.3f}; лучшая selective-политика Δ={d:+} над baseline "
              f"(не >10% от |{base_R:.0f}|). Магнитуда тоже не предсказуема — мета-sizing не бьёт fixed RR1.")
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
