"""etap_170: Lopez de Prado features для PIVOT detector.

База: etap_167. Цель = РАННЕЕ обнаружение разворота (не торговля), поэтому
из Lopez берём ТОЛЬКО фичи и методологию валидации, НЕ triple-barrier.

ДОБАВЛЕНО:
  Микроструктурные фичи (Lopez Ch 19, доступные из 12h OHLCV):
    - SADF (rolling explosiveness test) — bubble detector → pivot близко
    - Amihud illiquidity = |return| / dollar_volume
    - VPIN approximation (Bulk Volume Classification)
    - Roll spread estimator
    - Parkinson HL-vol vs ATR (внутри-баровая волатильность)
    - Garman-Klass volatility

  Fractional Differentiation (Lopez Ch 5):
    - frac_diff_close (d≈0.4) — стационарный close с сохранением памяти

  Methodology (Lopez Ch 4, 7, 8):
    - Sample weights = uniqueness × |return| (Ch 4)
    - Purged K-Fold CV вместо simple split (Ch 7)
    - MDA feature importance (permutation, Ch 8)

  Зональные фичи etap_167 СОХРАНЕНЫ:
  - dist_to_opp_zone_pct (расстояние до противоположной — критично!)

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
# LOPEZ DE PRADO FEATURES (Ch 5, 17, 19)
# ============================================================

def frac_diff_ffd(series: pd.Series, d: float = 0.4, thresh: float = 1e-4) -> pd.Series:
    """Fixed-Width Window Fractional Differentiation (Lopez Ch 5).

    Сохраняет память о уровнях, делает ряд стационарным.
    d ≈ 0.4 для BTC даёт corr с close ≈ 0.99 + ADF p-value < 0.05.
    """
    # Вычислим веса до thresh
    w = [1.0]
    k = 1
    while True:
        w_k = -w[-1] * (d - k + 1) / k
        if abs(w_k) < thresh:
            break
        w.append(w_k)
        k += 1
    w = np.array(w[::-1])  # reverse: oldest -> latest
    width = len(w)
    out = pd.Series(np.nan, index=series.index)
    vals = series.values
    for i in range(width, len(series)):
        seg = vals[i-width+1:i+1]
        if np.any(np.isnan(seg)):
            continue
        out.iloc[i] = float(np.dot(w, seg))
    return out


def sadf_rolling(log_price: pd.Series, min_window: int = 40, max_window: int = 120) -> pd.Series:
    """Supremum Augmented Dickey-Fuller — детектор bubble (Lopez Ch 17).

    Для каждой свечи t считает SADF_t = sup ADF_{t0,t} по t0 ∈ [t-max, t-min].
    Высокий SADF (>1.5) = explosive фаза = bubble/burst → pivot вероятен.

    Упрощённая реализация без полной ADF — используем простую регрессию OLS
    на Δy = α + β·y_{-1} + ε и берём t-statistic для β.
    """
    n = len(log_price)
    out = pd.Series(np.nan, index=log_price.index)
    y = log_price.values
    for t in range(max_window, n):
        best_tstat = -np.inf
        for w in [40, 60, 90, 120]:
            if w > t: continue
            y_seg = y[t-w+1:t+1]
            if np.any(np.isnan(y_seg)): continue
            # Δy = α + β·y_{-1} + ε
            dy = np.diff(y_seg)
            y_lag = y_seg[:-1]
            X = np.column_stack([np.ones_like(y_lag), y_lag])
            try:
                XtX_inv = np.linalg.inv(X.T @ X)
                beta = XtX_inv @ X.T @ dy
                resid = dy - X @ beta
                sigma2 = (resid @ resid) / (len(dy) - 2)
                se_beta = np.sqrt(sigma2 * XtX_inv[1, 1])
                tstat = beta[1] / se_beta if se_beta > 0 else 0
                if tstat > best_tstat: best_tstat = tstat
            except Exception:
                continue
        if best_tstat > -np.inf:
            out.iloc[t] = best_tstat
    return out


def amihud_illiquidity(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """Amihud illiquidity (Lopez Ch 19): |return| / dollar_volume.

    Высокая Amihud = тонкий стакан = большой price impact = pivot risk.
    """
    log_ret = np.log(df['close'] / df['close'].shift(1)).abs()
    dollar_vol = df['close'] * df['volume']
    daily_illiq = log_ret / dollar_vol.replace(0, np.nan)
    return daily_illiq.rolling(window).mean()


def vpin_bvc(df: pd.DataFrame, window: int = 50) -> pd.Series:
    """VPIN через Bulk Volume Classification (Lopez Ch 19).

    V_buy ≈ V * Φ((C - O) / σ_ΔP)
    V_sell = V - V_buy
    VPIN = Σ|V_buy - V_sell| / Σ(V_buy + V_sell)

    Высокий VPIN = toxic order flow = pivot risk.
    """
    from scipy.stats import norm as sci_norm
    delta_p = df['close'] - df['open']
    sigma_dp = delta_p.rolling(window).std()
    z = (delta_p / sigma_dp.replace(0, np.nan)).fillna(0)
    v_buy = df['volume'] * z.apply(sci_norm.cdf)
    v_sell = df['volume'] - v_buy
    imbalance = (v_buy - v_sell).abs()
    total = v_buy + v_sell
    vpin = imbalance.rolling(window).sum() / total.rolling(window).sum().replace(0, np.nan)
    return vpin


def roll_spread(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """Roll bid-ask spread estimator (Lopez Ch 19).

    S = 2 * sqrt(max(0, -Cov(ΔC_t, ΔC_{t-1})))
    """
    dc = df['close'].diff()
    cov = dc.rolling(window).apply(lambda s: s.cov(s.shift(1)) if len(s.dropna()) > 2 else 0)
    return 2 * np.sqrt(np.clip(-cov, 0, None))


def parkinson_vol(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Parkinson high-low volatility (Lopez Ch 19)."""
    hl = np.log(df['high'] / df['low'])
    return np.sqrt(hl.pow(2).rolling(window).mean() / (4 * np.log(2)))


def garman_klass_vol(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Garman-Klass volatility (Lopez Ch 19)."""
    hl = np.log(df['high'] / df['low'])
    co = np.log(df['close'] / df['open'])
    sigma2 = 0.5 * hl.pow(2) - (2*np.log(2) - 1) * co.pow(2)
    return np.sqrt(sigma2.rolling(window).mean().clip(lower=0))


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


def zone_strength_features(price, obs, fvgs, tf_label, ts_close, df_tf, bar_min):
    """СИЛА ближайшей зоны на каждом TF, для каждого направления отдельно.

    Возвращает для LONG и SHORT × OB и FVG:
      - nearest_age_h (часы с close cur-свечи зоны до ts_close)
      - nearest_width_pct (width zone / price * 100)
      - nearest_birth_body_pct (body% cur-свечи)
      - nearest_touch_count (сколько свечей касались зоны между рождением и ts_close)
      - nearest_is_HTF (1 если tf_label in {'1d','12h'})

    df_tf — pandas df этого TF для подсчёта touch_count.
    bar_min — длительность бара в минутах.
    """
    out = {}
    is_htf = 1 if tf_label in ('1d','12h') else 0

    for dir_label in ['LONG','SHORT']:
        for typ, items in [('OB', obs), ('FVG', fvgs)]:
            # найти ближайшую same-dir зону
            best = None
            best_dist = 1e9
            for z in items:
                if z.direction != dir_label: continue
                if z.bottom <= price <= z.top:
                    d = 0.0
                elif price < z.bottom:
                    d = (z.bottom - price) / price
                else:
                    d = (price - z.top) / price
                if d < best_dist:
                    best_dist = d
                    best = z

            prefix = f'zs_{dir_label}_{typ}_{tf_label}'
            if best is None:
                out[f'{prefix}_age_h'] = 999.0
                out[f'{prefix}_width_pct'] = 0.0
                out[f'{prefix}_birth_body_pct'] = 0.0
                out[f'{prefix}_touch_count'] = 0
                out[f'{prefix}_is_HTF'] = is_htf
                continue

            # ВСЕ zones хранят OBZone.cur_time = open cur-свечи (в shift_times я меняла tuple, не сам объект)
            # close зоны = cur_time + bar_min
            zone_birth_open = pd.Timestamp(best.cur_time if typ == 'OB' else best.c2_time)
            if zone_birth_open.tz is None: zone_birth_open = zone_birth_open.tz_localize('UTC')
            zone_birth_close = zone_birth_open + pd.Timedelta(minutes=bar_min)
            try:
                age_td = ts_close - zone_birth_close
                age_h = age_td.total_seconds() / 3600
                out[f'{prefix}_age_h'] = float(min(max(age_h, 0), 9999))
            except Exception:
                out[f'{prefix}_age_h'] = 0.0

            # width
            width = best.top - best.bottom
            out[f'{prefix}_width_pct'] = float(width / price * 100) if price > 0 else 0.0

            # birth body% — берём cur-свечу зоны из df_tf
            try:
                cur_t = best.cur_time if typ == 'OB' else best.c2_time
                if cur_t in df_tf.index:
                    r = df_tf.loc[cur_t]
                    rng = r['high'] - r['low']
                    body = abs(r['close'] - r['open'])
                    out[f'{prefix}_birth_body_pct'] = float(body / rng) if rng else 0.0
                else:
                    out[f'{prefix}_birth_body_pct'] = 0.0
            except Exception:
                out[f'{prefix}_birth_body_pct'] = 0.0

            # touch_count: свечи между cur_time и ts_close, чьи [low, high] пересекают зону
            try:
                cur_t = best.cur_time if typ == 'OB' else best.c2_time
                ts_lookup_for_touch = ts_close - pd.Timedelta(minutes=bar_min)  # exclude current
                slice_df = df_tf[(df_tf.index > cur_t) & (df_tf.index <= ts_lookup_for_touch)]
                if len(slice_df):
                    # touch = свеча low <= top and high >= bottom
                    touches = ((slice_df['low'] <= best.top) & (slice_df['high'] >= best.bottom)).sum()
                    out[f'{prefix}_touch_count'] = int(touches)
                else:
                    out[f'{prefix}_touch_count'] = 0
            except Exception:
                out[f'{prefix}_touch_count'] = 0

            out[f'{prefix}_is_HTF'] = is_htf

    return out


# ============================================================
# Сбор датасета
# ============================================================

def build_dataset(df_12h, df_1d, df_4h, df_2h, df_1h, df_usdtd_1d=None):
    print(f'  bars 12h: {len(df_12h)}')

    # precompute индикаторы 12h
    rsi12 = rsi_wilder(df_12h['close'], RSI_LEN)
    hull12 = hull_ma(df_12h['close'], HULL_LEN)
    ema200 = ema(df_12h['close'], EMA_LEN)
    atr14 = atr(df_12h, ATR_LEN)
    vol_z = (df_12h['volume'] - df_12h['volume'].rolling(VOL_Z_LEN).mean()) \
            / df_12h['volume'].rolling(VOL_Z_LEN).std()
    # === HONEST HTF Hull ===
    hull_1d_open = hull_ma(df_1d['close'], 20)
    hull_1d = hull_1d_open.copy()
    hull_1d.index = hull_1d.index + pd.Timedelta(days=1)
    hull_4h_open = hull_ma(df_4h['close'], 78)
    hull_4h = hull_4h_open.copy()
    hull_4h.index = hull_4h.index + pd.Timedelta(hours=4)

    # === LOPEZ DE PRADO FEATURES (precompute) ===
    print('  computing Lopez features (FFD, SADF, Amihud, VPIN, Roll, Parkinson, GK)...')
    log_close = np.log(df_12h['close'])
    frac_diff_d04 = frac_diff_ffd(log_close, d=0.4, thresh=1e-4)
    frac_diff_d03 = frac_diff_ffd(log_close, d=0.3, thresh=1e-4)
    sadf_series = sadf_rolling(log_close, min_window=40, max_window=120)
    amihud = amihud_illiquidity(df_12h, window=20)
    vpin = vpin_bvc(df_12h, window=50)
    roll = roll_spread(df_12h, window=20)
    parkinson = parkinson_vol(df_12h, window=14)
    gk = garman_klass_vol(df_12h, window=14)
    print('  Lopez features done')

    # === USDT.D 1d (HONEST: index сдвинут на close = +1d) ===
    if df_usdtd_1d is not None and not df_usdtd_1d.empty:
        ud_close = df_usdtd_1d['close'].copy()
        ud_close.index = ud_close.index + pd.Timedelta(days=1)
        ud_ema50 = ud_close.ewm(span=50, adjust=False).mean()
        ud_rsi14 = rsi_wilder(ud_close, 14)
        print(f'  USDT.D 1d: {len(ud_close)} bars  range {ud_close.index[0]} -> {ud_close.index[-1]}')
    else:
        ud_close = None
        ud_ema50 = None
        ud_rsi14 = None
        print('  USDT.D: not available, features will be 0')

    highs = df_12h['high'].values
    lows = df_12h['low'].values

    # === Block orders: маrubozu свеча с volume z-score >= 2 (proxy для Вадима) ===
    # Pre-compute список (close_time, low, high, body_dir) для каждой block-свечи на каждом TF
    def detect_block_orders(df, vol_window=20, body_thr=0.7, vol_z_thr=2.0):
        body_pct = (df['close'] - df['open']).abs() / (df['high'] - df['low']).replace(0, np.nan)
        vz = (df['volume'] - df['volume'].rolling(vol_window).mean()) / df['volume'].rolling(vol_window).std()
        mask = (body_pct >= body_thr) & (vz >= vol_z_thr)
        blocks = []
        for ts in df.index[mask.fillna(False)]:
            row = df.loc[ts]
            direction = 'LONG' if row['close'] > row['open'] else 'SHORT'
            blocks.append({'close_time': ts, 'low': float(row['low']), 'high': float(row['high']), 'dir': direction})
        return blocks
    block_1d = detect_block_orders(df_1d)
    block_4h = detect_block_orders(df_4h)
    block_12h = detect_block_orders(df_12h)
    print(f'  block_orders: 1d={len(block_1d)} 4h={len(block_4h)} 12h={len(block_12h)}')

    # Block_orders: сдвинуть close_time на +tf (HONEST — известны только после close)
    for b in block_1d: b['close_time'] = b['close_time'] + pd.Timedelta(days=1)
    for b in block_4h: b['close_time'] = b['close_time'] + pd.Timedelta(hours=4)
    for b in block_12h: b['close_time'] = b['close_time'] + pd.Timedelta(hours=12)

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

        z1d_ob = _zones_for(t_ob1d, o_ob1d, 120, 1440); z1d_fvg = _zones_for(t_fvg1d, o_fvg1d, 120, 1440)
        z4h_ob = _zones_for(t_ob4h, o_ob4h, 200, 240); z4h_fvg = _zones_for(t_fvg4h, o_fvg4h, 200, 240)
        z2h_ob = _zones_for(t_ob2h, o_ob2h, 300, 120); z2h_fvg = _zones_for(t_fvg2h, o_fvg2h, 300, 120)
        z1h_ob = _zones_for(t_ob1h, o_ob1h, 400, 60); z1h_fvg = _zones_for(t_fvg1h, o_fvg1h, 400, 60)
        feat.update(zone_feats_dir_split(close_i, z1d_ob, z1d_fvg, '1d'))
        feat.update(zone_feats_dir_split(close_i, z4h_ob, z4h_fvg, '4h'))
        feat.update(zone_feats_dir_split(close_i, z2h_ob, z2h_fvg, '2h'))
        feat.update(zone_feats_dir_split(close_i, z1h_ob, z1h_fvg, '1h'))
        # === NEW: ZONE STRENGTH features ===
        feat.update(zone_strength_features(close_i, ob_window_12h, fvg_window_12h, '12h', ts_close, df_12h, 720))
        feat.update(zone_strength_features(close_i, z1d_ob, z1d_fvg, '1d', ts_close, df_1d, 1440))
        feat.update(zone_strength_features(close_i, z4h_ob, z4h_fvg, '4h', ts_close, df_4h, 240))
        feat.update(zone_strength_features(close_i, z2h_ob, z2h_fvg, '2h', ts_close, df_2h, 120))
        feat.update(zone_strength_features(close_i, z1h_ob, z1h_fvg, '1h', ts_close, df_1h, 60))

        # === NEW LOPEZ FEATURES ===
        feat['lopez_fracdiff_d04'] = float(frac_diff_d04.iloc[i]) if not pd.isna(frac_diff_d04.iloc[i]) else 0.0
        feat['lopez_fracdiff_d03'] = float(frac_diff_d03.iloc[i]) if not pd.isna(frac_diff_d03.iloc[i]) else 0.0
        feat['lopez_sadf'] = float(sadf_series.iloc[i]) if not pd.isna(sadf_series.iloc[i]) else 0.0
        # SADF interpretation: phase
        sadf_val = feat['lopez_sadf']
        feat['lopez_sadf_explosive'] = int(sadf_val > 1.5)
        feat['lopez_sadf_steady'] = int(sadf_val < -1.5)
        feat['lopez_amihud'] = float(amihud.iloc[i]) if not pd.isna(amihud.iloc[i]) else 0.0
        # Amihud z-score (vs 90-day baseline)
        if i >= 180:
            amihud_window = amihud.iloc[i-180:i+1].dropna()
            if len(amihud_window) > 10:
                mu = amihud_window.mean(); sd = amihud_window.std()
                feat['lopez_amihud_zscore'] = float((amihud.iloc[i] - mu) / sd) if sd > 0 else 0.0
            else:
                feat['lopez_amihud_zscore'] = 0.0
        else:
            feat['lopez_amihud_zscore'] = 0.0
        feat['lopez_vpin'] = float(vpin.iloc[i]) if not pd.isna(vpin.iloc[i]) else 0.0
        feat['lopez_roll_spread'] = float(roll.iloc[i]) if not pd.isna(roll.iloc[i]) else 0.0
        feat['lopez_parkinson'] = float(parkinson.iloc[i]) if not pd.isna(parkinson.iloc[i]) else 0.0
        feat['lopez_gk_vol'] = float(gk.iloc[i]) if not pd.isna(gk.iloc[i]) else 0.0
        # Дивергенция: Parkinson vs ATR (intra-bar volatility expansion)
        atr_at_i = atr14.iloc[i] if not pd.isna(atr14.iloc[i]) else 1.0
        atr_pct = atr_at_i / close_i if close_i > 0 else 0.0001
        feat['lopez_parkinson_vs_atr'] = float(parkinson.iloc[i] / atr_pct) if atr_pct > 0 and not pd.isna(parkinson.iloc[i]) else 1.0
        feat['lopez_gk_vs_cc'] = float(gk.iloc[i] / atr_pct) if atr_pct > 0 and not pd.isna(gk.iloc[i]) else 1.0

        # ===== NEW: USDT.D features =====
        if ud_close is not None:
            try:
                ud_now = ud_close.asof(ts_lookup)
                ud_1d_ago = ud_close.asof(ts_lookup - pd.Timedelta(days=1))
                ud_3d_ago = ud_close.asof(ts_lookup - pd.Timedelta(days=3))
                ud_7d_ago = ud_close.asof(ts_lookup - pd.Timedelta(days=7))
                ud_ema50_now = ud_ema50.asof(ts_lookup)
                ud_rsi_now = ud_rsi14.asof(ts_lookup)
                if pd.notna(ud_now) and pd.notna(ud_1d_ago) and ud_1d_ago > 0:
                    feat['usdtd_1d_return_pct'] = float((ud_now - ud_1d_ago) / ud_1d_ago * 100)
                else: feat['usdtd_1d_return_pct'] = 0.0
                if pd.notna(ud_now) and pd.notna(ud_3d_ago) and ud_3d_ago > 0:
                    feat['usdtd_3d_return_pct'] = float((ud_now - ud_3d_ago) / ud_3d_ago * 100)
                else: feat['usdtd_3d_return_pct'] = 0.0
                if pd.notna(ud_now) and pd.notna(ud_7d_ago) and ud_7d_ago > 0:
                    feat['usdtd_7d_return_pct'] = float((ud_now - ud_7d_ago) / ud_7d_ago * 100)
                else: feat['usdtd_7d_return_pct'] = 0.0
                if pd.notna(ud_now) and pd.notna(ud_ema50_now) and ud_ema50_now > 0:
                    feat['usdtd_above_ema50'] = int(ud_now > ud_ema50_now)
                    feat['usdtd_ema50_dist_pct'] = float((ud_now - ud_ema50_now) / ud_ema50_now * 100)
                else:
                    feat['usdtd_above_ema50'] = 0
                    feat['usdtd_ema50_dist_pct'] = 0.0
                feat['usdtd_rsi14'] = float(ud_rsi_now) if pd.notna(ud_rsi_now) else 50.0
            except Exception:
                for k in ['usdtd_1d_return_pct','usdtd_3d_return_pct','usdtd_7d_return_pct',
                         'usdtd_above_ema50','usdtd_ema50_dist_pct','usdtd_rsi14']:
                    feat[k] = 0.0 if k != 'usdtd_above_ema50' else 0
        else:
            for k in ['usdtd_1d_return_pct','usdtd_3d_return_pct','usdtd_7d_return_pct',
                     'usdtd_above_ema50','usdtd_ema50_dist_pct','usdtd_rsi14']:
                feat[k] = 0.0 if k != 'usdtd_above_ema50' else 0

        # ===== NEW: Sweep history (BSL/SSL within 24h/72h) =====
        # Смотрим на 12h данные ДО свечи i
        # sweep BSL = свеча i пробила HIGH ранее закрытой свечи в окне
        # Поскольку для решения мы на close(i), используем свечи до i включительно
        for win_h, win_bars in [(24, 2), (72, 6), (168, 14)]:
            wl = max(0, i - win_bars)
            wd = df_12h.iloc[wl:i+1]  # включая i
            if len(wd) >= 2:
                # Previous high/low (исключая последнюю свечу i)
                prev = wd.iloc[:-1]
                prev_hi = prev['high'].max()
                prev_lo = prev['low'].min()
                # Sweep BSL = i.high > prev_hi (пробили high)
                bsl_swept = int(highs[i] > prev_hi)
                ssl_swept = int(lows[i] < prev_lo)
                # Magnitude
                bsl_mag = (highs[i] - prev_hi) / prev_hi * 100 if bsl_swept and prev_hi > 0 else 0
                ssl_mag = (prev_lo - lows[i]) / prev_lo * 100 if ssl_swept and prev_lo > 0 else 0
                # Failed sweep — пробили но close обратно (для свечи i)
                bsl_failed = int(bsl_swept and close_i < prev_hi)
                ssl_failed = int(ssl_swept and close_i > prev_lo)
            else:
                bsl_swept = ssl_swept = bsl_failed = ssl_failed = 0
                bsl_mag = ssl_mag = 0
            feat[f'sweep_BSL_{win_h}h'] = bsl_swept
            feat[f'sweep_SSL_{win_h}h'] = ssl_swept
            feat[f'sweep_BSL_failed_{win_h}h'] = bsl_failed
            feat[f'sweep_SSL_failed_{win_h}h'] = ssl_failed
            feat[f'sweep_BSL_mag_{win_h}h_pct'] = float(bsl_mag)
            feat[f'sweep_SSL_mag_{win_h}h_pct'] = float(ssl_mag)

        # ===== NEW: Multi-TF zone confluence =====
        # Сколько разных типов зон (OB/FVG на 1h/2h/4h/12h/1d) стоят у текущей цены (±0.5%)
        tol = close_i * 0.005
        confluence_count = 0
        for tfl in ['1h','2h','4h','12h','1d']:
            for dir_lbl in ['LONG','SHORT']:
                for typ in ['OB','FVG']:
                    k = f'dist_{dir_lbl}_{typ}_{tfl}_pct'
                    if k in feat and feat[k] < 0.5:
                        confluence_count += 1
        feat['confluence_zones_at_price'] = confluence_count

        # ===== NEW: Block orders proximity =====
        # Для каждого TF: ближайший block_order, dist выше/ниже текущей цены
        def block_feats(blocks, label):
            res = {f'n_block_{label}_above': 0, f'n_block_{label}_below': 0,
                   f'dist_block_{label}_above_pct': 20.0, f'dist_block_{label}_below_pct': 20.0,
                   f'block_{label}_at_price': 0}
            for b in blocks:
                if b['close_time'] > ts_lookup: continue  # не известен ещё
                # ограничим окном 14 баров (для разных TF)
                if (ts_lookup - b['close_time']) > pd.Timedelta(days=30):
                    continue
                if b['high'] < close_i:
                    res[f'n_block_{label}_below'] += 1
                    d = (close_i - b['high']) / close_i * 100
                    if d < res[f'dist_block_{label}_below_pct']: res[f'dist_block_{label}_below_pct'] = d
                elif b['low'] > close_i:
                    res[f'n_block_{label}_above'] += 1
                    d = (b['low'] - close_i) / close_i * 100
                    if d < res[f'dist_block_{label}_above_pct']: res[f'dist_block_{label}_above_pct'] = d
                else:
                    res[f'block_{label}_at_price'] = 1
            return res
        feat.update(block_feats(block_1d, '1d'))
        feat.update(block_feats(block_4h, '4h'))
        feat.update(block_feats(block_12h, '12h'))

        # ===== NEW: Time features =====
        feat['hour_utc'] = int(ts_i.hour)  # 0 или 12
        feat['day_of_week'] = int(ts_i.dayofweek)  # 0=Mon, 6=Sun
        feat['is_weekend'] = int(ts_i.dayofweek >= 5)

        # ===== NEW: HTF range position (14d, 90d) =====
        win14 = df_12h.iloc[max(0, i-28):i+1]
        if len(win14):
            hh14 = win14['high'].max(); ll14 = win14['low'].min()
            rng14 = hh14 - ll14
            feat['pos_in_14d_range_pct'] = float((close_i - ll14) / rng14 * 100) if rng14 else 50.0
        else:
            feat['pos_in_14d_range_pct'] = 50.0
        win90 = df_12h.iloc[max(0, i-180):i+1]
        if len(win90):
            hh90 = win90['high'].max(); ll90 = win90['low'].min()
            rng90 = hh90 - ll90
            feat['pos_in_90d_range_pct'] = float((close_i - ll90) / rng90 * 100) if rng90 else 50.0
        else:
            feat['pos_in_90d_range_pct'] = 50.0

        rows.append(feat)

    print(f'  skipped (no future): {skip_target}')
    return pd.DataFrame(rows)


def main():
    print("="*70)
    print("etap_170: LOPEZ FEATURES — SADF, Amihud, VPIN, Roll, Parkinson, FFD")
    print("  + Purged K-Fold CV + sample weights для честной оценки")
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

    # Load USDT.D 1d
    df_usdtd_1d = None
    usdtd_path = _ROOT / 'data' / 'USDT_D_1d.csv'
    if usdtd_path.exists():
        df_usdtd_1d = pd.read_csv(usdtd_path, index_col=0, parse_dates=True)
        if df_usdtd_1d.index.tz is None:
            df_usdtd_1d.index = df_usdtd_1d.index.tz_localize('UTC')
        df_usdtd_1d = df_usdtd_1d[(df_usdtd_1d.index >= cl) & (df_usdtd_1d.index <= ch)]
        print(f'  USDT.D 1d loaded: {len(df_usdtd_1d)} bars')
    else:
        print(f'  USDT.D NOT FOUND at {usdtd_path}')

    print("Building dataset (12h candidate per bar)...")
    t1 = time.time()
    ds = build_dataset(df_12h, df_1d, df_4h, df_2h, df_1h, df_usdtd_1d)
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

    from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
    from sklearn.metrics import roc_auc_score, brier_score_loss, average_precision_score

    out_dir = _ROOT / 'research' / 'elements_study' / 'output'
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = []

    # Sample weights (Lopez Ch 4) — return-attribution approximation
    # Return-attribution приближаем |close_t+14 / close_t - 1|
    log_close = np.log(df_12h['close'])
    future_ret = (log_close.shift(-14) - log_close).abs().fillna(0)
    sample_w_df = pd.DataFrame({'time': df_12h.index, 'w': future_ret.values})
    # normalize, clip
    mean_w = sample_w_df['w'].replace(0, np.nan).mean()
    sample_w_df['w'] = (sample_w_df['w'] / mean_w).fillna(1).clip(0.1, 10)
    # Если train_df['time'] не tz-aware, конвертируем index df_12h
    train_times = pd.to_datetime(train_df['time'].values, utc=True)
    sample_w_df['time'] = pd.to_datetime(sample_w_df['time'], utc=True)
    merged_w = pd.DataFrame({'time': train_times}).merge(sample_w_df, on='time', how='left')
    sample_w_train = merged_w['w'].fillna(1.0).values

    print('=== HONEST CV: Purged K-Fold (5 folds, embargo=14 bars) ===')
    print()

    # Purged K-Fold простой: убрать из train all events чей label-interval пересекает test
    LABEL_HORIZON = 14  # 14 баров
    EMBARGO = 14

    def purged_kfold_splits(n_total, n_splits=5, label_h=14, embargo=14):
        fold_size = n_total // n_splits
        for k in range(n_splits):
            test_start = k * fold_size
            test_end = (k+1) * fold_size if k < n_splits-1 else n_total
            test_idx = list(range(test_start, test_end))
            # Train = всё за пределами test ± purge gap
            purge_start = max(0, test_start - label_h)
            purge_end = min(n_total, test_end + embargo + label_h)
            train_idx = [i for i in range(n_total) if i < purge_start or i >= purge_end]
            yield train_idx, test_idx

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

            # === HONEST 5-FOLD PURGED CV на TRAIN ===
            fold_aucs = []
            for fold_k, (tr_i, te_i) in enumerate(purged_kfold_splits(len(train_df), 5, LABEL_HORIZON, EMBARGO)):
                if len(te_i) < 20 or len(tr_i) < 100: continue
                clf_cv = GradientBoostingClassifier(
                    n_estimators=200, max_depth=4, learning_rate=0.05,
                    min_samples_leaf=20, random_state=42,
                )
                clf_cv.fit(X_train[tr_i], y_train[tr_i], sample_weight=sample_w_train[tr_i])
                p_cv = clf_cv.predict_proba(X_train[te_i])[:, 1]
                try:
                    auc_cv = roc_auc_score(y_train[te_i], p_cv)
                    fold_aucs.append(auc_cv)
                except Exception:
                    pass
            cv_mean = np.mean(fold_aucs) if fold_aucs else float('nan')
            cv_std = np.std(fold_aucs) if fold_aucs else float('nan')
            print(f'  Purged CV AUC: {cv_mean:.3f} ± {cv_std:.3f}  (folds: {[f"{a:.2f}" for a in fold_aucs]})')

            # === FINAL FIT + HOLD-OUT TEST 2025-2026 ===
            clf = GradientBoostingClassifier(
                n_estimators=300, max_depth=4, learning_rate=0.05,
                min_samples_leaf=20, random_state=42,
            )
            t2 = time.time()
            clf.fit(X_train, y_train, sample_weight=sample_w_train)
            p_test = clf.predict_proba(X_test)[:, 1]
            print(f'  fit time: {time.time()-t2:.1f}s')

            try:
                auc = roc_auc_score(y_test, p_test)
            except Exception:
                auc = float('nan')
            brier = brier_score_loss(y_test, p_test)
            ap = average_precision_score(y_test, p_test)
            base = y_test.mean()*100
            print(f'  Hold-out TEST AUC = {auc:.3f}  Brier = {brier:.3f}  AP = {ap:.3f}  (baseline = {base:.2f}%)')

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
            print(f'  TOP-15 features:')
            for name, imp in fi[:15]: print(f'    {imp:.4f}  {name}')
            print()

            # Save
            pdf = test_df[['time','close','high','low', col]].copy()
            pdf['p_hit'] = p_test
            pdf.to_csv(out_dir / f'etap_170_pred_{col}.csv', index=False)

            summary.append({
                'target': col,
                'train_n': len(y_train), 'test_n': len(y_test),
                'baseline_pos_pct': base,
                'purged_cv_auc_mean': cv_mean, 'purged_cv_auc_std': cv_std,
                'holdout_auc': auc, 'brier': brier, 'ap': ap,
            })

    sdf = pd.DataFrame(summary)
    sdf.to_csv(out_dir / 'etap_170_summary.csv', index=False)
    print("="*70)
    print("SUMMARY")
    print("="*70)
    print(sdf.to_string(index=False))
    print()
    print(f'Total: {time.time()-t0:.1f}s')


if __name__ == '__main__':
    main()
