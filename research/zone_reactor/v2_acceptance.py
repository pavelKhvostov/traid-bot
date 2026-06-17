"""zone_reactor v2 Блок 1: добавляют ли ACCEPTANCE + multi-TF-type фичи сигнал?

Идея пользователя: сила зоны = сколько торговалось в ней ранее (acceptance/volume-at-
price) + конкретные multi-TF стеки (D-FVG + 6/8h-OB + 12h-FVG). Этих фич не было в v1.
Чистая модель (вход = close 12h-свечи касания). Сравниваем OOS AUC: BASE (старые фичи)
vs +ACCEPTANCE vs +ACCEPTANCE+TYPESTACK. Если прирост над BASE — фичи реальны.
train 2020-2024 / test 2025-2026. CatBoost-GPU.
"""
from __future__ import annotations
import sys, time
from pathlib import Path
_ROOT = Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
sys.path.insert(0, str(_ROOT))
import numpy as np, pandas as pd, warnings
warnings.filterwarnings('ignore')
from sklearn.metrics import roc_auc_score
from catboost import CatBoostClassifier
from data_manager import load_df, compose_from_base
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg
from research.elements_study.etap_170_lopez_features import rsi_wilder, hull_ma, ema, atr as atr_series

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
START = pd.Timestamp("2020-01-01", tz="UTC"); END = pd.Timestamp("2026-06-11", tz="UTC")
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")
TFS = {'6h': 360, '8h': 480, '12h': 720, '1d': 1440, '3d': 4320}
TF_W = {'6h': 0.8, '8h': 1.0, '12h': 1.5, '1d': 2.5, '3d': 3.0}
WMAX = 5.0; REACT = 5.0; HOLD12 = 20; RANGE_W = 60; ACC_W = 80; RISK_FLOOR = 0.003
SIDE_COST = 0.0008; FUNDING_8H = 0.0001


def _load(sym, tf):
    d = compose_from_base(load_df(sym, "1h"), "12h") if tf == '12h' else load_df(sym, tf)
    return d[(d.index >= START) & (d.index <= END)].copy()


def zones(df, tf):
    out = []
    for j in range(2, len(df)):
        z = detect_ob_pair(df, j)
        if z is not None:
            out.append({'b': z.bottom, 't': z.top, 'dir': z.direction, 'type': 'OB', 'tf': tf,
                        'birth': z.cur_time + pd.Timedelta(minutes=TFS[tf])})
        f = detect_fvg(df, j)
        if f is not None:
            out.append({'b': f.bottom, 't': f.top, 'dir': f.direction, 'type': 'FVG', 'tf': tf,
                        'birth': f.c2_time + pd.Timedelta(minutes=TFS[tf])})
    return out


def resolve12(long, entry, far, tp, h, l, start, n):
    risk = max(abs(entry - far) / entry, RISK_FLOOR)
    end = min(start + HOLD12, len(h))
    for k in range(start, end):
        if long:
            if l[k] <= far: out, ex = 0, k; break
            if h[k] >= tp: out, ex = 1, k; break
        else:
            if h[k] >= far: out, ex = 0, k; break
            if l[k] <= tp: out, ex = 1, k; break
    else:
        return None
    return out


TYPES = ['6h_OB', '6h_FVG', '8h_OB', '8h_FVG', '12h_OB', '12h_FVG', '1d_OB', '1d_FVG', '3d_OB', '3d_FVG']


def build(sym):
    frames = {tf: _load(sym, tf) for tf in TFS}
    zall = [z for tf in TFS for z in zones(frames[tf], tf)]
    # first touch на 12h для каждой зоны
    d12 = frames['12h']
    h = d12['high'].values; l = d12['low'].values; c = d12['close'].values; v = d12['volume'].values
    t12 = d12.index; n = len(c)
    atr = atr_series(d12, 14).values; rsi = rsi_wilder(d12['close'], 14).values
    hull = hull_ma(d12['close'], 78).values; ema200 = ema(d12['close'], 200).values
    vmean = pd.Series(v).rolling(20).mean().values; vstd = pd.Series(v).rolling(20).std().values
    htf = {}
    for tf in ('1d', '3d'):
        hm = hull_ma(frames[tf]['close'], 50); dd = (hm > hm.shift(3)).astype(int)*2-1
        dd.index = dd.index + pd.Timedelta(minutes=TFS[tf]); htf[tf] = dd
    rows = []
    for z in zall:
        wpct = (z['t'] - z['b']) / z['t'] * 100
        if wpct > WMAX or wpct < 0.5:
            continue
        long = z['dir'] == 'LONG'
        b0 = int(np.searchsorted(t12.values, np.datetime64(z['birth'].tz_localize(None)), side='right'))
        tj = None
        for k in range(b0, n):
            if l[k] <= z['t'] and h[k] >= z['b']:
                tj = k; break
        if tj is None or tj < max(200, RANGE_W) or tj >= n - 1:
            continue
        entry = c[tj]; far = z['b'] if long else z['t']
        if (long and entry <= far) or (not long and entry >= far):
            continue
        tp = entry * (1 + REACT/100) if long else entry * (1 - REACT/100)
        r = resolve12(long, entry, far, tp, h, l, tj + 1, n)
        if r is None:
            continue
        held = r
        price = c[tj]; ts = t12[tj]; fi = tj
        # --- ACCEPTANCE: проторговка в зоне ранее (12h, окно до касания) ---
        w0 = max(0, tj - ACC_W)
        seg_lo = l[w0:tj]; seg_hi = h[w0:tj]; seg_c = c[w0:tj]; seg_v = v[w0:tj]
        overlap = (seg_lo <= z['t']) & (seg_hi >= z['b'])          # бар касался зоны
        closed_in = (seg_c >= z['b']) & (seg_c <= z['t'])           # закрылся в зоне (acceptance)
        acc_candles = int(closed_in.sum())
        acc_touch_bars = int(overlap.sum())
        vtot = seg_v.sum() + 1e-9
        acc_vol_frac = float(seg_v[overlap].sum() / vtot)           # доля объёма в зоне
        # --- MULTI-TF TYPE STACK на цене касания ---
        tol = price * 0.004
        stack = {f't_{k}': 0 for k in TYPES}
        for zz in zall:
            if zz['birth'] > ts:
                continue
            if zz['b'] - tol <= entry <= zz['t'] + tol:
                key = f"t_{zz['tf']}_{zz['type']}"
                if key in stack:
                    stack[key] = 1
        n_tf = len({k.split('_')[1] for k, vv in stack.items() if vv})
        rlo = l[fi-RANGE_W:fi+1].min(); rhi = h[fi-RANGE_W:fi+1].max()
        rec = {
            'symbol': sym, 'time': ts, 'held': held, 'side_long': int(long),
            'tf_w': TF_W[z['tf']], 'is_ob': int(z['type'] == 'OB'),
            'zone_width_pct': wpct, 'pos_in_range': (entry - rlo)/(rhi - rlo) if rhi > rlo else 0.5,
            'age_h': min((ts - z['birth']).total_seconds()/3600, 9999),
            'rsi14': rsi[fi] if not np.isnan(rsi[fi]) else 50.0,
            'ema200_dist': (price - ema200[fi])/price*100 if not np.isnan(ema200[fi]) else 0.0,
            'hull_dir': 1.0 if (not np.isnan(hull[fi]) and not np.isnan(hull[fi-3]) and hull[fi] > hull[fi-3]) else -1.0,
            'atr_pct': atr[fi]/price*100,
            'vol_z': (v[fi]-vmean[fi])/vstd[fi] if not np.isnan(vstd[fi]) and vstd[fi] else 0.0,
            'htf_1d_dir': float(htf['1d'].asof(ts)) if pd.notna(htf['1d'].asof(ts)) else 0.0,
            'htf_3d_dir': float(htf['3d'].asof(ts)) if pd.notna(htf['3d'].asof(ts)) else 0.0,
            # NEW acceptance
            'acc_candles': acc_candles, 'acc_touch_bars': acc_touch_bars, 'acc_vol_frac': acc_vol_frac,
            'n_tf_stack': n_tf,
        }
        rec.update(stack)
        rows.append(rec)
    return rows


BASE = ['tf_w', 'is_ob', 'zone_width_pct', 'pos_in_range', 'age_h', 'rsi14', 'ema200_dist',
        'hull_dir', 'atr_pct', 'vol_z', 'htf_1d_dir', 'htf_3d_dir', 'side_long']
ACC = ['acc_candles', 'acc_touch_bars', 'acc_vol_frac']
STACK = ['n_tf_stack'] + [f't_{k}' for k in TYPES]


def auc(df, cols, is_tr):
    Xtr = df.loc[is_tr, cols].fillna(0).values; ytr = df.loc[is_tr, 'held'].values
    te = df.loc[~is_tr]; Xte = te[cols].fillna(0).values; yte = te['held'].values
    cb = CatBoostClassifier(iterations=700, learning_rate=0.04, depth=6, l2_leaf_reg=3,
                            task_type='GPU', devices='0', verbose=0, random_seed=0).fit(Xtr, ytr)
    return roc_auc_score(yte, cb.predict_proba(Xte)[:, 1]), cb


def main():
    t0 = time.time()
    print("=" * 76)
    print("zone_reactor v2 Блок1: ACCEPTANCE + multi-TF-стек добавляют сигнал? (CatBoost-GPU)")
    print("=" * 76)
    rows = []
    for sym in SYMBOLS:
        r = build(sym); rows.extend(r); print(f"  [{sym}] зон: {len(r)}")
    df = pd.DataFrame(rows).sort_values('time').reset_index(drop=True)
    df.to_csv(_ROOT / 'research/zone_reactor/v2_dataset.csv', index=False)
    is_tr = (df['time'] < TRAIN_END).values
    print(f"\nTRAIN {is_tr.sum()} / TEST {(~is_tr).sum()}  held база test={df.loc[~is_tr,'held'].mean()*100:.0f}%")
    print(f"acceptance: acc_candles медиана={df['acc_candles'].median():.0f}  "
          f"acc_vol_frac медиана={df['acc_vol_frac'].median():.3f}")
    print("\nOOS AUC (чистая модель: вход=close 12h-свечи касания):")
    a_base, _ = auc(df, BASE, is_tr)
    a_acc, _ = auc(df, BASE + ACC, is_tr)
    a_full, cb = auc(df, BASE + ACC + STACK, is_tr)
    print(f"   BASE (старые фичи):            {a_base:.4f}")
    print(f"   BASE + ACCEPTANCE:             {a_acc:.4f}   (Δ {a_acc-a_base:+.4f})")
    print(f"   BASE + ACCEPTANCE + TF-стек:   {a_full:.4f}   (Δ {a_full-a_base:+.4f})")
    imp = sorted(zip(BASE+ACC+STACK, cb.get_feature_importance()), key=lambda x: -x[1])[:10]
    print("\nimportance (full):", ', '.join(f'{n}={v:.1f}' for n, v in imp))
    acc_imp = sum(v for n, v in zip(BASE+ACC+STACK, cb.get_feature_importance()) if n in ACC+STACK)
    print(f"суммарная importance НОВЫХ фич (acceptance+стек): {acc_imp:.1f}%")
    print("\n" + "=" * 76)
    if a_full - a_base > 0.02:
        print(f"НОВЫЕ ФИЧИ ДАЮТ ПРИРОСТ (+{a_full-a_base:.3f}) → строим v2 (самообучение+GPU+TG).")
    else:
        print(f"Прирост {a_full-a_base:+.3f} мал — acceptance/стек не добавляют сигнала над base.")
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
