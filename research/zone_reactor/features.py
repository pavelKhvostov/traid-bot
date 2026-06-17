"""zone_reactor.features — модуль силы зоны реакции (multi-TF 8h/12h/D/3d + ICT + индикаторы).

Цель проекта: определять диапазоны (зоны), от которых ожидается реакция цены ≥5%.
Единица анализа = 12h confirmed fractal (swing low → ожидаем long-реакцию, swing high →
short). Это уже «точка интереса» — поэтому НЕ предсказываем «фрактал ли это» (это
тривиально из формы свечи и было утечкой в etap_170, AUC 0.93). Предсказываем УСЛОВНО:
даст ли фрактал реакцию ≥5% (зона сильная) или нет (слабая).

Сила зоны = что трейдер-ICT смотрит:
  • multi-TF confluence OB+FVG (8h/12h/1d/3d), same-direction, на ЭКСТРЕМУМЕ-фитиле,
    born ≤ подтверждения (без lookahead), вес по HTF + untouched (свежесть);
  • ICT: liquidity sweep (снял prior low/high и вернулся), premium/discount (где
    экстремум в dealing range), FVG поблизости;
  • индикаторы 12h: RSI, EMA200-dist, Hull dir, ATR%, vol-z, Bollinger %b;
  • HTF тренд 1d/3d.

Все фичи ≤ времени подтверждения фрактала (i+N). Лейбл считается ПОСЛЕ (i+N+1…).
"""
from __future__ import annotations
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd
from data_manager import load_df, compose_from_base
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg
from research.elements_study.etap_170_lopez_features import rsi_wilder, hull_ma, ema, atr as atr_series

START_DATE = pd.Timestamp("2020-01-01", tz="UTC")
END_DATE = pd.Timestamp("2026-06-03", tz="UTC")
FRACTAL_N = 2
TF_W = {'8h': 1.0, '12h': 1.5, '1d': 2.5, '3d': 3.0}
TF_MIN = {'8h': 480, '12h': 720, '1d': 1440, '3d': 4320}
REACT_PCT = 5.0
HORIZON = 20          # 20×12h = 10 дней на реакцию
SWEEP_W = 10          # окно ликвидности (5 дней на 12h)
RANGE_W = 60          # dealing range для premium/discount (30 дней)


def _load_tf(sym, tf):
    if tf == '12h':
        d = compose_from_base(load_df(sym, "1h"), "12h")
    else:
        d = load_df(sym, tf)
    return d[(d.index >= START_DATE) & (d.index <= END_DATE)].copy()


def detect_zones(df, tf):
    """OB+FVG зоны TF, birth=close cur-свечи (honest) + first_touch время."""
    zones = []
    idx = df.index
    for j in range(2, len(df)):
        z = detect_ob_pair(df, j)
        if z is not None:
            zones.append({'b': z.bottom, 't': z.top, 'dir': z.direction,
                          'birth': z.cur_time + pd.Timedelta(minutes=TF_MIN[tf])})
        f = detect_fvg(df, j)
        if f is not None:
            zones.append({'b': f.bottom, 't': f.top, 'dir': f.direction,
                          'birth': f.c2_time + pd.Timedelta(minutes=TF_MIN[tf])})
    lows = df['low']; highs = df['high']
    for z in zones:
        m = (idx > z['birth']) & (lows <= z['t']) & (highs >= z['b'])
        ft = idx[m]
        z['first_touch'] = ft[0] if len(ft) else pd.Timestamp.max.tz_localize('UTC')
    return zones


def zone_strength_at(extreme, want, ts, price, zones_by_tf):
    """Сила same-dir зон, содержащих экстремум, born ≤ ts. want='LONG'/'SHORT'."""
    tol = price * 0.004
    conf = 0; strength = 0.0; htf = 0; n_unt = 0; n_unt_htf = 0
    nearest = 25.0; matched = 0; tf_hits = set()
    for tf, zones in zones_by_tf.items():
        for z in zones:
            if z['dir'] != want or z['birth'] > ts:
                continue
            if z['b'] - tol <= extreme <= z['t'] + tol:
                d, hit = 0.0, True
            else:
                d = (z['b'] - extreme if extreme < z['b'] else extreme - z['t']) / price * 100
                hit = d < 0.6
            nearest = min(nearest, d)
            if hit:
                conf += 1; matched += 1; tf_hits.add(tf)
                unt = z['first_touch'] >= ts
                strength += TF_W[tf] * (1.6 if unt else 1.0)
                if tf in ('1d', '3d'):
                    htf = 1
                    n_unt_htf += int(unt)
                n_unt += int(unt)
    return {
        'zone_conf_count': conf, 'zone_strength': strength, 'in_htf_zone': htf,
        'nearest_zone_dist': min(nearest, 25.0), 'n_tf_aligned': len(tf_hits),
        'untouched_frac': n_unt / matched if matched else 0.0, 'n_untouched_htf': n_unt_htf,
    }


def build_fractal_dataset(sym):
    """Все 12h-фракталы sym → строки с фичами силы зоны + ICT + индикаторы + лейбл реакции."""
    frames = {tf: _load_tf(sym, tf) for tf in TF_MIN}
    zones_by_tf = {tf: detect_zones(frames[tf], tf) for tf in TF_MIN}
    d12 = frames['12h']
    o = d12['open'].values; h = d12['high'].values; l = d12['low'].values; c = d12['close'].values
    v = d12['volume'].values; times = d12.index; n = len(c)

    atr = atr_series(d12, 14).values
    rsi = rsi_wilder(d12['close'], 14).values
    hull = hull_ma(d12['close'], 78).values
    ema200 = ema(d12['close'], 200).values
    vmean = pd.Series(v).rolling(20).mean().values; vstd = pd.Series(v).rolling(20).std().values
    bb_m = pd.Series(c).rolling(20).mean().values; bb_s = pd.Series(c).rolling(20).std().values
    # HTF тренд: 1d/3d Hull dir (shift на close → honest)
    htf_dir = {}
    for tf in ('1d', '3d'):
        hm = hull_ma(frames[tf]['close'], 50)
        dd = (hm > hm.shift(3)).astype(int) * 2 - 1
        dd.index = dd.index + pd.Timedelta(minutes=TF_MIN[tf])
        htf_dir[tf] = dd

    rows = []
    for i in range(max(200, RANGE_W, SWEEP_W + 1), n - HORIZON - 3):
        if atr[i] <= 0:
            continue
        is_low = l[i] < l[i-1] and l[i] < l[i-2] and l[i] < l[i+1] and l[i] < l[i+2]
        is_high = h[i] > h[i-1] and h[i] > h[i-2] and h[i] > h[i+1] and h[i] > h[i+2]
        if not (is_low or is_high):
            continue
        side = 'long' if is_low else 'short'   # если оба — берём оба? фрактал обычно один
        for is_it, sd in [(is_low, 'long'), (is_high, 'short')]:
            if not is_it:
                continue
            extreme = l[i] if sd == 'long' else h[i]
            want = 'LONG' if sd == 'long' else 'SHORT'
            ts_conf = times[i + 2]      # фрактал подтверждён на i+2
            price = c[i]
            # ЛЕЙБЛ: реакция ≥5% от экстремума ПОСЛЕ подтверждения, до пробоя экстремума
            react = 0
            for k in range(i + 3, min(i + 3 + HORIZON, n)):
                if sd == 'long':
                    if h[k] >= extreme * (1 + REACT_PCT/100):
                        react = 1; break
                    if l[k] < extreme:        # пробил low — зона не удержала
                        break
                else:
                    if l[k] <= extreme * (1 - REACT_PCT/100):
                        react = 1; break
                    if h[k] > extreme:
                        break
            # ФИЧИ силы зоны (на экстремуме, ≤ ts_conf)
            zs = zone_strength_at(extreme, want, ts_conf, price, zones_by_tf)
            # ICT: sweep ликвидности
            prior_lo = l[i-SWEEP_W:i].min(); prior_hi = h[i-SWEEP_W:i].max()
            if sd == 'long':
                swept = int(l[i] < prior_lo); reclaim = int(l[i] < prior_lo and c[i] > prior_lo)
                sweep_mag = (prior_lo - l[i]) / price * 100 if l[i] < prior_lo else 0.0
            else:
                swept = int(h[i] > prior_hi); reclaim = int(h[i] > prior_hi and c[i] < prior_hi)
                sweep_mag = (h[i] - prior_hi) / price * 100 if h[i] > prior_hi else 0.0
            # premium/discount: позиция экстремума в dealing range
            rlo = l[i-RANGE_W:i+1].min(); rhi = h[i-RANGE_W:i+1].max()
            pos_in_range = (extreme - rlo) / (rhi - rlo) if rhi > rlo else 0.5
            rec = {
                'symbol': sym, 'time': times[i], 'side_long': 1 if sd == 'long' else 0,
                'react5': react, **zs,
                'liq_swept': swept, 'liq_reclaim': reclaim, 'sweep_mag_pct': sweep_mag,
                'pos_in_range': pos_in_range,
                'rsi14': rsi[i] if not np.isnan(rsi[i]) else 50.0,
                'ema200_dist': (price - ema200[i]) / price * 100 if not np.isnan(ema200[i]) else 0.0,
                'hull_dir': 1.0 if (not np.isnan(hull[i]) and not np.isnan(hull[i-3]) and hull[i] > hull[i-3]) else -1.0,
                'atr_pct': atr[i] / price * 100,
                'vol_z': (v[i] - vmean[i]) / vstd[i] if not np.isnan(vstd[i]) and vstd[i] else 0.0,
                'bb_pctb': (c[i] - (bb_m[i] - 2*bb_s[i])) / (4*bb_s[i]) if not np.isnan(bb_s[i]) and bb_s[i] else 0.5,
                'htf_1d_dir': float(htf_dir['1d'].asof(ts_conf)) if pd.notna(htf_dir['1d'].asof(ts_conf)) else 0.0,
                'htf_3d_dir': float(htf_dir['3d'].asof(ts_conf)) if pd.notna(htf_dir['3d'].asof(ts_conf)) else 0.0,
            }
            rows.append(rec)
    return rows


FEATURES = [
    'zone_conf_count', 'zone_strength', 'in_htf_zone', 'nearest_zone_dist', 'n_tf_aligned',
    'untouched_frac', 'n_untouched_htf', 'liq_swept', 'liq_reclaim', 'sweep_mag_pct',
    'pos_in_range', 'rsi14', 'ema200_dist', 'hull_dir', 'atr_pct', 'vol_z', 'bb_pctb',
    'htf_1d_dir', 'htf_3d_dir', 'side_long',
]
