"""zone_reactor.zone_touch — ПРАВИЛЬНАЯ постановка идеи пользователя.

НЕ «какой фрактал даст реакцию» (это был прокси, etap_192/baseline — контраста мало),
А: определи ICT-зоны заранее → на КАСАНИИ предскажи, УДЕРЖИТСЯ зона (реакция ≥5%,
сильная) или ПРОБЬЁТСЯ (слабая). Held vs broke — ровно strong/weak пользователя.

Зоны (8h/12h/1d/3d): OB (demand/supply) + FVG (bull/bear). Событие = ПЕРВОЕ касание
ценой зоны после её рождения. Лейбл на касании:
  held(1) = цена прошла ≥5% в сторону зоны (demand→вверх, supply→вниз) РАНЬШЕ, чем
            закрылась за дальний край зоны (пробой);  broke(0) = пробила первой.
  таймаут 20×12h → выброс.
Резолв на 12h. Train 2020→2024 / test 2024→2026.

Фичи силы зоны (≤ касания): TF-вес, тип (OB/FVG), возраст, displacement рождения
(body%/range), MULTI-TF confluence на цене касания (сколько зон др. ТФ накрывают, вес
HTF), premium/discount позиция, HTF тренд 1d/3d, индикаторы, atr_pct (контроль).

Контроль волатильности: печатаем zone-only AUC (без atr/vol) и per-asset.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from sklearn.inspection import permutation_importance

from data_manager import load_df, compose_from_base
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg
from research.elements_study.etap_170_lopez_features import rsi_wilder, hull_ma, ema, atr as atr_series

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
START = pd.Timestamp("2020-01-01", tz="UTC"); END = pd.Timestamp("2026-06-11", tz="UTC")
TRAIN_END = pd.Timestamp("2024-01-01", tz="UTC")
TF_MIN = {'8h': 480, '12h': 720, '1d': 1440, '3d': 4320}
TF_W = {'8h': 1.0, '12h': 1.5, '1d': 2.5, '3d': 3.0}
REACT = 5.0; HORIZON = 20; RANGE_W = 60
HORIZON_D = 10; EMBARGO_D = 2
OUT = _ROOT / 'research' / 'zone_reactor'


def _load_tf(sym, tf):
    d = compose_from_base(load_df(sym, "1h"), "12h") if tf == '12h' else load_df(sym, tf)
    return d[(d.index >= START) & (d.index <= END)].copy()


def detect_zones(df, tf):
    zones = []
    for j in range(2, len(df)):
        z = detect_ob_pair(df, j)
        if z is not None:
            r = df.iloc[j]; rng = max(r['high'] - r['low'], 1e-9)
            zones.append({'b': z.bottom, 't': z.top, 'dir': z.direction, 'type': 'OB',
                          'birth': z.cur_time + pd.Timedelta(minutes=TF_MIN[tf]), 'tf': tf,
                          'disp_body': abs(r['close'] - r['open']) / rng})
        f = detect_fvg(df, j)
        if f is not None:
            r = df.iloc[j]; rng = max(r['high'] - r['low'], 1e-9)
            zones.append({'b': f.bottom, 't': f.top, 'dir': f.direction, 'type': 'FVG',
                          'birth': f.c2_time + pd.Timedelta(minutes=TF_MIN[tf]), 'tf': tf,
                          'disp_body': abs(r['close'] - r['open']) / rng})
    # первое касание на барах ЭТОГО TF
    lows = df['low']; highs = df['high']; idx = df.index
    for z in zones:
        m = (idx > z['birth']) & (lows <= z['t']) & (highs >= z['b'])
        ft = idx[m]
        z['touch'] = ft[0] if len(ft) else None
    return [z for z in zones if z['touch'] is not None]


def confluence_at(price, want, ts, zones_all):
    tol = price * 0.004
    cnt = 0; strength = 0.0; htf = 0; tfs = set()
    for z in zones_all:
        if z['dir'] != want or z['birth'] > ts:
            continue
        if z['b'] - tol <= price <= z['t'] + tol:
            cnt += 1; strength += TF_W[z['tf']]; tfs.add(z['tf'])
            if z['tf'] in ('1d', '3d'):
                htf = 1
    return cnt, strength, htf, len(tfs)


def build_symbol(sym):
    frames = {tf: _load_tf(sym, tf) for tf in TF_MIN}
    zones_by_tf = {tf: detect_zones(frames[tf], tf) for tf in TF_MIN}
    zones_all = [z for zs in zones_by_tf.values() for z in zs]
    d12 = frames['12h']
    h = d12['high'].values; l = d12['low'].values; c = d12['close'].values; v = d12['volume'].values
    t12 = d12.index; n = len(c)
    atr = atr_series(d12, 14).values; rsi = rsi_wilder(d12['close'], 14).values
    hull = hull_ma(d12['close'], 78).values; ema200 = ema(d12['close'], 200).values
    vmean = pd.Series(v).rolling(20).mean().values; vstd = pd.Series(v).rolling(20).std().values
    htf_dir = {}
    for tf in ('1d', '3d'):
        hm = hull_ma(frames[tf]['close'], 50); dd = (hm > hm.shift(3)).astype(int)*2-1
        dd.index = dd.index + pd.Timedelta(minutes=TF_MIN[tf]); htf_dir[tf] = dd

    rows = []
    for z in zones_all:
        # 12h-бар на/после касания
        j = int(np.searchsorted(t12.values, np.datetime64(z['touch']), side='left'))
        if j < max(200, RANGE_W) or j >= n - HORIZON - 1 or atr[j] <= 0:
            continue
        long = z['dir'] == 'LONG'
        ref = z['t'] if long else z['b']          # проксимальный край (куда пришла цена)
        far = z['b'] if long else z['t']           # дальний край (пробой)
        # ЛЕЙБЛ held/broke — intrabar SL-first (реалистичный стоп по фитилю дальнего края)
        held = 0
        for k in range(j, min(j + HORIZON, n)):
            if long:
                if l[k] <= far:        # фитиль пробил дальний край = стоп (первым, консерв.)
                    break
                if h[k] >= ref * (1 + REACT/100):
                    held = 1; break
            else:
                if h[k] >= far:
                    break
                if l[k] <= ref * (1 - REACT/100):
                    held = 1; break
        ts = z['touch']
        fi = j - 1                          # фичи — на ПОСЛЕДНЕМ ЗАКРЫТОМ 12h-баре до касания (анти-lookahead)
        price = c[fi]
        cnt, strength, htf, ntf = confluence_at(ref, z['dir'], ts, zones_all)
        rlo = l[fi-RANGE_W:fi+1].min(); rhi = h[fi-RANGE_W:fi+1].max()
        pos = (ref - rlo) / (rhi - rlo) if rhi > rlo else 0.5
        age_h = (ts - z['birth']).total_seconds() / 3600
        rows.append({
            'symbol': sym, 'time': ts, 'tf_w': TF_W[z['tf']], 'is_ob': int(z['type'] == 'OB'),
            'side_long': int(long), 'held': held,
            'conf_count': cnt, 'conf_strength': strength, 'in_htf': htf, 'n_tf_aligned': ntf,
            'disp_body': z['disp_body'], 'age_h': min(age_h, 9999), 'pos_in_range': pos,
            'zone_width_pct': (z['t'] - z['b']) / price * 100,
            'rsi14': rsi[fi] if not np.isnan(rsi[fi]) else 50.0,
            'ema200_dist': (price - ema200[fi]) / price * 100 if not np.isnan(ema200[fi]) else 0.0,
            'hull_dir': 1.0 if (not np.isnan(hull[fi]) and not np.isnan(hull[fi-3]) and hull[fi] > hull[fi-3]) else -1.0,
            'atr_pct': atr[fi] / price * 100,
            'vol_z': (v[fi] - vmean[fi]) / vstd[fi] if not np.isnan(vstd[fi]) and vstd[fi] else 0.0,
            'htf_1d_dir': float(htf_dir['1d'].asof(ts)) if pd.notna(htf_dir['1d'].asof(ts)) else 0.0,
            'htf_3d_dir': float(htf_dir['3d'].asof(ts)) if pd.notna(htf_dir['3d'].asof(ts)) else 0.0,
        })
    return rows


ZONE_F = ['tf_w', 'is_ob', 'conf_count', 'conf_strength', 'in_htf', 'n_tf_aligned',
          'disp_body', 'age_h', 'pos_in_range', 'zone_width_pct', 'side_long']
VOL_F = ['atr_pct', 'vol_z']
TREND_F = ['rsi14', 'ema200_dist', 'hull_dir', 'htf_1d_dir', 'htf_3d_dir']
ALL_F = ZONE_F + VOL_F + TREND_F


def fit_auc(df, cols, is_tr):
    Xtr = df.loc[is_tr, cols].fillna(0).values; ytr = df.loc[is_tr, 'held'].values
    te = df.loc[~is_tr]; Xte = te[cols].fillna(0).values; yte = te['held'].values
    if len(np.unique(ytr)) < 2 or len(np.unique(yte)) < 2:
        return np.nan, None
    m = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.04, max_leaf_nodes=31,
        min_samples_leaf=40, l2_regularization=1.0, random_state=0).fit(Xtr, ytr)
    return roc_auc_score(yte, m.predict_proba(Xte)[:, 1]), m


def main():
    t0 = time.time()
    print("=" * 80)
    print("zone_reactor ZONE-TOUCH: зона УДЕРЖИТСЯ (реакция ≥5%) или ПРОБЬЁТСЯ? (held/broke)")
    print("=" * 80)
    rows = []
    for sym in SYMBOLS:
        r = build_symbol(sym); rows.extend(r)
        s = pd.DataFrame(r)
        print(f"  [{sym}] касаний зон: {len(r)}  held(реакция≥5%): {s['held'].mean()*100:.1f}%")
    df = pd.DataFrame(rows).sort_values('time').reset_index(drop=True)
    df.to_csv(OUT / 'zone_touch_dataset.csv', index=False)
    is_tr = (df['time'] < TRAIN_END).values
    print(f"\nВСЕГО касаний: {len(df)}  TRAIN {is_tr.sum()} / TEST {len(df)-is_tr.sum()}  "
          f"held база test={df.loc[~is_tr,'held'].mean()*100:.0f}%")

    print("\nOOS AUC по группам фич:")
    a_all, clf = fit_auc(df, ALL_F, is_tr)
    a_zone, _ = fit_auc(df, ZONE_F, is_tr)
    a_zt, _ = fit_auc(df, ZONE_F + TREND_F, is_tr)
    a_vol, _ = fit_auc(df, VOL_F, is_tr)
    print(f"   ВСЕ ({len(ALL_F)}):                {a_all:.3f}")
    print(f"   ЗОНЫ-только ({len(ZONE_F)}):        {a_zone:.3f}   ← твоя идея в чистом виде")
    print(f"   зоны+тренд (без vol):       {a_zt:.3f}")
    print(f"   только волатильность (2):   {a_vol:.3f}")

    te = df.loc[~is_tr].copy()
    print("\nheld% по силе зоны (conf_strength, TEST) — монотонно?:")
    te['zb'] = pd.qcut(te['conf_strength'].rank(method='first'), 4, labels=['Q1-слаб', 'Q2', 'Q3', 'Q4-сильн'])
    for b, g in te.groupby('zb'):
        print(f"   {b:>9}: n={len(g):>4} held%={g['held'].mean()*100:>4.1f} "
              f"strength∈[{g['conf_strength'].min():.1f},{g['conf_strength'].max():.1f}]")

    print("\nPER-ASSET зоны-только OOS AUC:")
    for sym in SYMBOLS:
        d = df[df.symbol == sym].reset_index(drop=True); itr = (d['time'] < TRAIN_END).values
        az, _ = fit_auc(d, ZONE_F, itr)
        print(f"   {sym}: зоны={az:.3f} (held база {d.loc[~itr,'held'].mean()*100:.0f}%, n_te={int((~itr).sum())})")

    if clf is not None:
        pi = permutation_importance(clf, df.loc[~is_tr, ALL_F].fillna(0).values, te['held'].values,
                                    n_repeats=6, random_state=0, scoring='roc_auc')
        imp = sorted(zip(ALL_F, pi.importances_mean), key=lambda x: -x[1])
        print("\nimportance (OOS) top-10:")
        for nm, mn in imp[:10]:
            print(f"   {nm:>16} {mn:+.4f}")

    print("\n" + "=" * 80)
    if a_zone > 0.57 and a_zt > 0.58:
        print(f"СИЛА ЗОНЫ РАБОТАЕТ: зоны-только AUC={a_zone:.3f} (без волатильности). Held/broke")
        print("  разделяется по ICT-силе зоны. → строим GPU-сеть с самообучением.")
    else:
        print(f"Зоны-только AUC={a_zone:.3f}: ICT-сила зоны held/broke не разделяет лучше монетки.")
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
