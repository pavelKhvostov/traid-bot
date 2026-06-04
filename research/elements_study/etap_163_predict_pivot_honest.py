"""etap_163: HONEST predict pivot AT close — без lookahead в HTF.

ОТЛИЧИЕ от etap_161:
  etap_161 имел lookahead через HTF asof:
    - hull_1d.asof(ts_i) на ts_i = 06.02 00:00 (open 12h-свечи) брал
      значение HullMA рассчитанное на close 1d-свечи 06.02 00:00,
      которая закрывается в 07.02 00:00 — это БУДУЩЕЕ.
    - hull_4h.asof(ts_i) аналогично.
    - bisect_right(times, ts_i) для зон включал HTF-OB с cur_time=ts_i
      (не закрытый HTF-бар).

  В этой версии (etap_163):
    - HTF Hull серии сдвинуты на close_time HTF-свечи
      (index += tf_duration) — значение становится известно В МОМЕНТ
      close HTF-свечи, не на её open.
    - asof(ts_close - 1ns) — берёт строго ПОСЛЕДНЮЮ закрытую HTF свечу.
    - Зоны HTF аналогично — каждая зона "рождается" в close cur-свечи.
    - ts_close = ts_i + 12h (close 12h свечи).

Это сложнее: baseline для "low_fractal AND rise>=4%" ~6-8%, AUC>=0.6 = хороший.

ЛЕЙБЛЫ (lookahead для target, как и положено для supervised):
  - is_low_fractal: low(i) < low(i-2,i-1,i+1,i+2)
  - is_high_fractal: high(i) > high(i-2,i-1,i+1,i+2)
  - move_after_low_pct: (max(high) в [i+3..i+3+14]) / low(i) - 1, в %
  - move_after_high_pct: (low(i) - min(low) в [i+3..i+3+14]) / low(i), в %
  - y_low_strong_<X>:   is_low_fractal AND move_after_low_pct >= X
  - y_high_strong_<X>:  is_high_fractal AND move_after_high_pct >= X

ФИЧИ — на момент close свечи i (ТОЛЬКО данные ≤ i, никакого lookahead):
  - индикаторы 12h: rsi/hull/ema/atr/vol_z на close(i)
  - структура 12h: 30d HH/LL, days since, 7d mid distance
  - свеча: body%, range/ATR, is_marubozu, close_in_range_pct,
           wick_upper%, wick_lower%
  - momentum: pre_3d/7d return до close(i)
  - HTF trend: 1d Hull dir, 4h Hull dir на close(i)
  - зоны на 1d/12h/4h/2h/1h: для LONG и SHORT ОТДЕЛЬНО (т.к. направление неизвестно):
      n_LONG_OB_<tf>, dist_LONG_OB_<tf>_pct, in_LONG_OB_<tf>
      n_SHORT_OB_<tf>, dist_SHORT_OB_<tf>_pct, in_SHORT_OB_<tf>
      (то же для FVG)
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists(): _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path: _sys.path.insert(0, str(_ROOT))

import time
import numpy as np
import pandas as pd

from data_manager import load_df, compose_from_base
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg

SYMBOL = "BTCUSDT"
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")
TEST_END = pd.Timestamp("2026-05-31", tz="UTC")
START_DATE = pd.Timestamp("2020-01-01", tz="UTC")

FRACTAL_N = 2
FUTURE_BARS = 14   # 7 дней после confirmation
RSI_LEN = 14
HULL_LEN = 78
EMA_LEN = 200
VOL_Z_LEN = 20
ATR_LEN = 14
TARGETS = [3.0, 4.0, 5.0]


# ============================================================
# ИНДИКАТОРЫ
# ============================================================

def rsi_wilder(series, length=14):
    delta = series.diff()
    gain = delta.clip(lower=0); loss = (-delta).clip(lower=0)
    ag = gain.ewm(alpha=1/length, adjust=False).mean()
    al = loss.ewm(alpha=1/length, adjust=False).mean()
    rs = ag / al.replace(0, np.nan)
    return 100 - 100 / (1 + rs)

def _wma(values, length):
    weights = np.arange(1, length+1, dtype=float)
    out = np.full(len(values), np.nan)
    for i in range(length-1, len(values)):
        out[i] = np.dot(values[i-length+1:i+1], weights) / weights.sum()
    return out

def hull_ma(series, length=78):
    half = length//2; sqrtl = int(np.sqrt(length))
    raw = 2*_wma(series.values, half) - _wma(series.values, length)
    return pd.Series(_wma(pd.Series(raw).fillna(0).values, sqrtl), index=series.index)

def ema(series, length=200): return series.ewm(span=length, adjust=False).mean()

def atr(df, length=14):
    high, low, close = df['high'], df['low'], df['close']
    tr = pd.concat([high-low, (high-close.shift()).abs(), (low-close.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()


# ============================================================
# Зоны на момент close i
# ============================================================

def zones_at_idx(df, idx, lookback):
    obs = []; fvgs = []
    start = max(2, idx - lookback)
    for j in range(start, idx + 1):
        z = detect_ob_pair(df, j)
        if z is not None: obs.append(z)
        f = detect_fvg(df, j)
        if f is not None: fvgs.append(f)
    return obs, fvgs


def zone_feats_dir_split(price, obs, fvgs, tf_label):
    """Фичи разделены LONG/SHORT т.к. направление будущего фрактала неизвестно."""
    out = {}
    for dir_label in ['LONG', 'SHORT']:
        for typ, items in [('OB', obs), ('FVG', fvgs)]:
            in_zone = 0; dist = 20.0; n = 0
            for z in items:
                if z.direction != dir_label: continue
                n += 1
                if z.bottom <= price <= z.top:
                    in_zone = 1; d = 0.0
                elif price < z.bottom:
                    d = (z.bottom - price) / price * 100
                else:
                    d = (price - z.top) / price * 100
                if d < dist: dist = d
            out[f'n_{dir_label}_{typ}_{tf_label}'] = n
            out[f'in_{dir_label}_{typ}_{tf_label}'] = in_zone
            out[f'dist_{dir_label}_{typ}_{tf_label}_pct'] = min(dist, 20.0)
    return out


# ============================================================
# Сбор датасета
# ============================================================

def build_dataset(df_12h, df_1d, df_4h, df_2h, df_1h):
    print(f'  bars 12h: {len(df_12h)}')

    # precompute индикаторы 12h
    rsi12 = rsi_wilder(df_12h['close'], RSI_LEN)
    hull12 = hull_ma(df_12h['close'], HULL_LEN)
    ema200 = ema(df_12h['close'], EMA_LEN)
    atr14 = atr(df_12h, ATR_LEN)
    vol_z = (df_12h['volume'] - df_12h['volume'].rolling(VOL_Z_LEN).mean()) \
            / df_12h['volume'].rolling(VOL_Z_LEN).std()
    # === HONEST HTF Hull ===
    # Сдвигаем индекс на close HTF-свечи: index был open_time, делаем close_time.
    # Тогда asof(ts_close - 1ns) даст значение Hull чьей HTF-свечи close ≤ ts_close.
    hull_1d_open = hull_ma(df_1d['close'], 20)
    hull_1d = hull_1d_open.copy()
    hull_1d.index = hull_1d.index + pd.Timedelta(days=1)
    hull_4h_open = hull_ma(df_4h['close'], 78)
    hull_4h = hull_4h_open.copy()
    hull_4h.index = hull_4h.index + pd.Timedelta(hours=4)

    highs = df_12h['high'].values
    lows = df_12h['low'].values

    # Зоны — кэшируем для скорости (на каждом i заново было бы 4684 × O(lookback))
    # Делаем инкрементально: каждый бар добавляет 1 новый OB и 1 новый FVG (если есть),
    # держим списки активных. Зоны бессмертные (без mitigation) — упрощение, как в etap_160.
    obs_12h = []; fvgs_12h = []
    # 1d/4h/2h/1h будут пересчитываться через asof + slicing — для простоты построим заранее списки до каждого индекса
    # Чтобы не делать O(N²), пересоберём активные зоны на КАЖДОМ HTF на дату close 12h-свечи асимптотически.
    # Простой вариант: для каждого HTF предкомпьютим списки [(time, OB/FVG)] и используем bisect.
    def precompute_zones(df):
        ob_list = []  # (time, OBZone)
        fvg_list = []
        for j in range(2, len(df)):
            z = detect_ob_pair(df, j)
            if z is not None: ob_list.append((df.index[j], z))
            f = detect_fvg(df, j)
            if f is not None: fvg_list.append((df.index[j], f))
        return ob_list, fvg_list

    print('  precompute zones for HTF...')
    t0 = time.time()
    ob_1d, fvg_1d = precompute_zones(df_1d)
    ob_4h, fvg_4h = precompute_zones(df_4h)
    ob_2h, fvg_2h = precompute_zones(df_2h)
    ob_1h, fvg_1h = precompute_zones(df_1h)
    print(f'  zones precomputed in {time.time()-t0:.1f}s')

    # Конвертируем в массивы времён для bisect
    import bisect
    def split_times(items):
        times = [t for t, _ in items]
        objs = [o for _, o in items]
        return times, objs

    # === HONEST zones ===
    # Зона детектится по 2-3 свечам, она "рождается" в close cur-свечи.
    # Сдвигаем сохранённое время каждой зоны (= cur_time, т.е. open cur-свечи)
    # на +tf_duration, чтобы получить close cur-свечи. Тогда bisect_right(times, ts_close-1ns)
    # включит только зоны рождённые ДО ts_close.
    def shift_times(items, td: pd.Timedelta):
        return [(t + td, o) for t, o in items]

    ob_1d = shift_times(ob_1d, pd.Timedelta(days=1));  fvg_1d = shift_times(fvg_1d, pd.Timedelta(days=1))
    ob_4h = shift_times(ob_4h, pd.Timedelta(hours=4)); fvg_4h = shift_times(fvg_4h, pd.Timedelta(hours=4))
    ob_2h = shift_times(ob_2h, pd.Timedelta(hours=2)); fvg_2h = shift_times(fvg_2h, pd.Timedelta(hours=2))
    ob_1h = shift_times(ob_1h, pd.Timedelta(hours=1)); fvg_1h = shift_times(fvg_1h, pd.Timedelta(hours=1))

    t_ob1d, o_ob1d = split_times(ob_1d); t_fvg1d, o_fvg1d = split_times(fvg_1d)
    t_ob4h, o_ob4h = split_times(ob_4h); t_fvg4h, o_fvg4h = split_times(fvg_4h)
    t_ob2h, o_ob2h = split_times(ob_2h); t_fvg2h, o_fvg2h = split_times(fvg_2h)
    t_ob1h, o_ob1h = split_times(ob_1h); t_fvg1h, o_fvg1h = split_times(fvg_1h)

    LB_BARS_HTF = {'1d': 120, '4h': 200, '2h': 300, '1h': 400}

    def zones_up_to_lookback(times, objs, ts, lookback_bars, bar_minutes):
        cut = bisect.bisect_right(times, ts)
        lookback_td = pd.Timedelta(minutes=bar_minutes * lookback_bars)
        cut_lo = bisect.bisect_left(times, ts - lookback_td)
        return objs[cut_lo:cut]

    rows = []
    skip_target = 0

    for i in range(2, len(df_12h)):
        # нужно знание i+2 для лейбла фрактала, i+3..i+3+FUTURE_BARS для движения
        if i + 2 >= len(df_12h):
            break
        future_start = i + 3
        future_end = i + 3 + FUTURE_BARS
        if future_end > len(df_12h):
            skip_target += 1
            continue

        ts_i = df_12h.index[i]
        # Close time текущей 12h-свечи. Для HTF-индикаторов используем lookup в момент close.
        # Так как индексы HTF Hull/zones были сдвинуты на их собственный close_time,
        # asof(ts_close) даст значение HTF-свечи закрывшейся не позже ts_close.
        ts_close = ts_i + pd.Timedelta(hours=12)
        ts_lookup = ts_close

        # === LABELS (используют будущие свечи — это OK для target) ===
        h_win = highs[i-2:i+3]; l_win = lows[i-2:i+3]
        is_high_fr = (highs[i] == h_win.max()) and ((h_win == highs[i]).sum() == 1)
        is_low_fr  = (lows[i]  == l_win.min())  and ((l_win == lows[i]).sum() == 1)

        future_slice = df_12h.iloc[future_start:future_end]
        move_after_low = (future_slice['high'].max() - lows[i]) / lows[i] * 100
        move_after_high = (highs[i] - future_slice['low'].min()) / highs[i] * 100

        # === FEATURES (только ≤ i) ===
        # Inкрементально обновим OB/FVG на 12h
        z = detect_ob_pair(df_12h, i)
        if z is not None: obs_12h.append(z)
        zf = detect_fvg(df_12h, i)
        if zf is not None: fvgs_12h.append(zf)
        # ограничим окно для 12h до 150 баров
        ob_window_12h = [o for o in obs_12h[-150:]]
        fvg_window_12h = [f for f in fvgs_12h[-150:]]

        close_i = float(df_12h['close'].iloc[i])
        feat = {
            'time': ts_i,
            'close': close_i,
            'high': float(highs[i]),
            'low': float(lows[i]),
            'is_low_fractal': int(is_low_fr),
            'is_high_fractal': int(is_high_fr),
            'move_after_low_pct': float(move_after_low),
            'move_after_high_pct': float(move_after_high),
        }
        for t in TARGETS:
            feat[f'y_low_strong_{int(t)}'] = int(is_low_fr and move_after_low >= t)
            feat[f'y_high_strong_{int(t)}'] = int(is_high_fr and move_after_high >= t)

        # Индикаторы 12h на close i
        feat['rsi_14'] = float(rsi12.iloc[i]) if not pd.isna(rsi12.iloc[i]) else 50.0
        if i >= 3 and not pd.isna(hull12.iloc[i]) and not pd.isna(hull12.iloc[i-3]) and hull12.iloc[i-3]:
            feat['hull_78_slope_pct'] = float((hull12.iloc[i] - hull12.iloc[i-3]) / hull12.iloc[i-3] * 100)
        else:
            feat['hull_78_slope_pct'] = 0.0
        feat['ema_200_dist_pct'] = float((close_i - ema200.iloc[i]) / close_i * 100) if not pd.isna(ema200.iloc[i]) else 0.0
        feat['vol_zscore_20'] = float(vol_z.iloc[i]) if not pd.isna(vol_z.iloc[i]) else 0.0
        feat['atr_pct'] = float(atr14.iloc[i] / close_i * 100) if not pd.isna(atr14.iloc[i]) else 0.0

        # Структура 12h
        win30 = df_12h.iloc[max(0, i-60):i+1]
        hh = win30['high'].max(); ll = win30['low'].min()
        feat['dist_from_30d_high_pct'] = float((hh - close_i) / close_i * 100)
        feat['dist_from_30d_low_pct'] = float((close_i - ll) / close_i * 100)
        idx_hh = win30['high'].idxmax(); idx_ll = win30['low'].idxmin()
        feat['bars_since_30d_high'] = int(i - df_12h.index.get_loc(idx_hh))
        feat['bars_since_30d_low'] = int(i - df_12h.index.get_loc(idx_ll))
        win7 = df_12h.iloc[max(0, i-14):i+1]
        mid7 = (win7['high'].max() + win7['low'].min()) / 2
        feat['dist_from_7d_mid_pct'] = float((close_i - mid7) / close_i * 100)

        # Свойства свечи i (без знания i+1, i+2)
        op = float(df_12h['open'].iloc[i]); cl = close_i
        hi = float(highs[i]); lo = float(lows[i])
        rng = hi - lo
        body = abs(cl - op)
        upper_wick = hi - max(op, cl)
        lower_wick = min(op, cl) - lo
        feat['candle_body_pct'] = float(body/rng) if rng else 0.0
        feat['candle_range_vs_atr'] = float(rng / atr14.iloc[i]) if not pd.isna(atr14.iloc[i]) and atr14.iloc[i] else 1.0
        feat['candle_is_marubozu'] = int(feat['candle_body_pct'] >= 0.7)
        feat['candle_upper_wick_pct'] = float(upper_wick / rng) if rng else 0.0
        feat['candle_lower_wick_pct'] = float(lower_wick / rng) if rng else 0.0
        feat['candle_is_bull'] = int(cl > op)
        feat['candle_close_pos_in_range'] = float((cl - lo) / rng) if rng else 0.5

        # Pre-momentum
        if i >= 6:
            p3 = df_12h['close'].iloc[i-6]
            feat['pre_3d_return_pct'] = float((close_i - p3) / p3 * 100)
        else:
            feat['pre_3d_return_pct'] = 0.0
        if i >= 14:
            p7 = df_12h['close'].iloc[i-14]
            feat['pre_7d_return_pct'] = float((close_i - p7) / p7 * 100)
        else:
            feat['pre_7d_return_pct'] = 0.0
        pre = df_12h.iloc[max(0, i-14):i]
        if len(pre):
            avg_rng = (pre['high'] - pre['low']).mean()
            feat['pre_volatility_atr_pct'] = float(avg_rng / close_i * 100)
        else:
            feat['pre_volatility_atr_pct'] = 0.0

        # HTF trend (1d/4h Hull direction) — индексы Hull сдвинуты на close, см. выше
        try:
            h1d_at = hull_1d.asof(ts_lookup); h1d_prev = hull_1d.asof(ts_lookup - pd.Timedelta(days=3))
            feat['htf_1d_hull_dir'] = 1 if pd.notna(h1d_at) and pd.notna(h1d_prev) and h1d_at > h1d_prev else -1
        except Exception:
            feat['htf_1d_hull_dir'] = 0
        try:
            h4h_at = hull_4h.asof(ts_lookup); h4h_prev = hull_4h.asof(ts_lookup - pd.Timedelta(hours=12))
            feat['htf_4h_hull_dir'] = 1 if pd.notna(h4h_at) and pd.notna(h4h_prev) and h4h_at > h4h_prev else -1
        except Exception:
            feat['htf_4h_hull_dir'] = 0

        # ЗОНЫ 12h
        feat.update(zone_feats_dir_split(close_i, ob_window_12h, fvg_window_12h, '12h'))

        # ЗОНЫ 1d/4h/2h/1h через bisect — times уже сдвинуты на close cur-свечи
        # bisect_right(times, ts_lookup) включит зону у которой close ≤ ts_close
        def _zones_for(times, objs, lb_bars, bar_min):
            cut = bisect.bisect_right(times, ts_lookup)
            cut_lo = bisect.bisect_left(times, ts_lookup - pd.Timedelta(minutes=bar_min*lb_bars))
            return objs[cut_lo:cut]

        feat.update(zone_feats_dir_split(close_i, _zones_for(t_ob1d, o_ob1d, 120, 1440), _zones_for(t_fvg1d, o_fvg1d, 120, 1440), '1d'))
        feat.update(zone_feats_dir_split(close_i, _zones_for(t_ob4h, o_ob4h, 200, 240), _zones_for(t_fvg4h, o_fvg4h, 200, 240), '4h'))
        feat.update(zone_feats_dir_split(close_i, _zones_for(t_ob2h, o_ob2h, 300, 120), _zones_for(t_fvg2h, o_fvg2h, 300, 120), '2h'))
        feat.update(zone_feats_dir_split(close_i, _zones_for(t_ob1h, o_ob1h, 400, 60), _zones_for(t_fvg1h, o_fvg1h, 400, 60), '1h'))

        rows.append(feat)

    print(f'  skipped (no future): {skip_target}')
    return pd.DataFrame(rows)


def main():
    print("="*70)
    print("etap_163: HONEST pivot AT CLOSE — HTF lookahead fixed")
    print("="*70)
    print()

    t0 = time.time()
    print("Loading data...")
    df_1h = load_df(SYMBOL, "1h")
    df_1d = load_df(SYMBOL, "1d")
    df_12h = compose_from_base(df_1h, "12h")
    df_4h = compose_from_base(df_1h, "4h")
    df_2h = compose_from_base(df_1h, "2h")
    cl, ch = START_DATE, TEST_END
    df_1h = df_1h[(df_1h.index >= cl) & (df_1h.index <= ch)].copy()
    df_1d = df_1d[(df_1d.index >= cl) & (df_1d.index <= ch)].copy()
    df_12h = df_12h[(df_12h.index >= cl) & (df_12h.index <= ch)].copy()
    df_4h = df_4h[(df_4h.index >= cl) & (df_4h.index <= ch)].copy()
    df_2h = df_2h[(df_2h.index >= cl) & (df_2h.index <= ch)].copy()
    print(f'  range: {df_12h.index[0]} -> {df_12h.index[-1]}  ({time.time()-t0:.1f}s)')
    print()

    print("Building dataset (12h candidate per bar)...")
    t1 = time.time()
    ds = build_dataset(df_12h, df_1d, df_4h, df_2h, df_1h)
    print(f'  built {len(ds)} samples × {ds.shape[1]} cols in {time.time()-t1:.1f}s')
    ds['time'] = pd.to_datetime(ds['time'], utc=True)
    print()

    # Split
    train_df = ds[ds['time'] < TRAIN_END].copy()
    test_df = ds[ds['time'] >= TRAIN_END].copy()
    print(f'TRAIN: {len(train_df)}  range {train_df["time"].min()} -> {train_df["time"].max()}')
    print(f'TEST:  {len(test_df)}   range {test_df["time"].min()} -> {test_df["time"].max()}')
    print()

    print("=== Baseline rates (доля свечей которые \"станут\" фракталом + ≥X%) ===")
    for t in TARGETS:
        lc = f'y_low_strong_{int(t)}'; hc = f'y_high_strong_{int(t)}'
        print(f'  LOW  strong{int(t)}%: TRAIN {train_df[lc].mean()*100:>5.2f}%  TEST {test_df[lc].mean()*100:>5.2f}%')
        print(f'  HIGH strong{int(t)}%: TRAIN {train_df[hc].mean()*100:>5.2f}%  TEST {test_df[hc].mean()*100:>5.2f}%')
    print()

    # Features = всё кроме лейблов и id
    drop = ['time','close','high','low','is_low_fractal','is_high_fractal',
            'move_after_low_pct','move_after_high_pct'] + \
           [f'y_low_strong_{int(t)}' for t in TARGETS] + \
           [f'y_high_strong_{int(t)}' for t in TARGETS]
    feat_cols = [c for c in ds.columns if c not in drop]
    print(f'features: {len(feat_cols)}')
    print()

    X_train = train_df[feat_cols].fillna(0).values
    X_test = test_df[feat_cols].fillna(0).values

    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.metrics import roc_auc_score, brier_score_loss, average_precision_score

    out_dir = _ROOT / 'research' / 'elements_study' / 'output'
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = []

    for direction in ['low', 'high']:
        for t in TARGETS:
            col = f'y_{direction}_strong_{int(t)}'
            y_train = train_df[col].values; y_test = test_df[col].values

            print(f'--- Target: {col}  (LOW=рост, HIGH=падение) ---')
            print(f'  train pos: {y_train.sum()}/{len(y_train)} ({y_train.mean()*100:.2f}%)')
            print(f'  test  pos: {y_test.sum()}/{len(y_test)} ({y_test.mean()*100:.2f}%)')
            if y_train.sum() < 30 or y_test.sum() < 5:
                print('  too few positives — skip\n')
                continue

            clf = GradientBoostingClassifier(
                n_estimators=300, max_depth=4, learning_rate=0.05,
                min_samples_leaf=20, random_state=42,
            )
            t2 = time.time()
            clf.fit(X_train, y_train)
            p_test = clf.predict_proba(X_test)[:, 1]
            print(f'  fit time: {time.time()-t2:.1f}s')

            try:
                auc = roc_auc_score(y_test, p_test)
            except Exception:
                auc = float('nan')
            brier = brier_score_loss(y_test, p_test)
            ap = average_precision_score(y_test, p_test)
            base = y_test.mean()*100
            print(f'  OOS AUC = {auc:.3f}  Brier = {brier:.3f}  AP = {ap:.3f}  (baseline = {base:.2f}%)')

            # Threshold sweep
            print(f'  Threshold sweep (OOS):')
            print(f'  {"thr":>5}  {"n_kept":>6}  {"kept%":>6}  {"hit%":>6}  {"lift":>5}')
            for thr in [0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
                keep = p_test >= thr
                n = keep.sum()
                if n == 0: continue
                hit_rate = y_test[keep].mean()*100
                lift = hit_rate / base if base else 0
                print(f'  {thr:>5.2f}  {n:>6d}  {n/len(y_test)*100:>5.1f}%  {hit_rate:>5.1f}%  {lift:>4.2f}x')

            # Top features
            fi = sorted(zip(feat_cols, clf.feature_importances_), key=lambda x: -x[1])
            print(f'  TOP-10 features:')
            for name, imp in fi[:10]: print(f'    {imp:.4f}  {name}')
            print()

            # Save
            pdf = test_df[['time','close','high','low', col]].copy()
            pdf['p_hit'] = p_test
            pdf.to_csv(out_dir / f'etap_163_pred_{col}.csv', index=False)

            summary.append({
                'target': col,
                'train_n': len(y_train), 'test_n': len(y_test),
                'baseline_pos_pct': base, 'auc': auc, 'brier': brier, 'ap': ap,
                'best_lift_thr': max([0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]),
            })

    sdf = pd.DataFrame(summary)
    sdf.to_csv(out_dir / 'etap_163_summary.csv', index=False)
    print("="*70)
    print("SUMMARY")
    print("="*70)
    print(sdf.to_string(index=False))
    print()
    print(f'Total: {time.time()-t0:.1f}s')


if __name__ == '__main__':
    main()
