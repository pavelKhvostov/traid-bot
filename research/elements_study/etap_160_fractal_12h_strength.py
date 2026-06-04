"""etap_160: Глубокая ML-аналитика силы 12h-фракталов BTC.

ЗАДАЧА: научиться предсказывать "силу" 12h фрактала — будет ли движение
        >=3% (или >=4%, >=5%) от цены фрактала в течение 7 дней (14 баров)
        после confirmation_time.

TRAIN: 2020-01-01 → 2024-12-31  (5 лет)
TEST:  2025-01-01 → 2026-05-30  (1.4 года, OOS)

ФИЧИ (все на момент confirmation_time = ts_fractal + 2 бара):

  ЗОНЫ (на 1d, 12h, 4h, 2h, 1h):
    - in_OB_<tf>:        bool — fractal price внутри LONG/SHORT OB на этом TF?
    - in_FVG_<tf>:       bool — то же для FVG
    - dist_OB_<tf>_pct:  расстояние до ближайшего OB того же направления
    - dist_FVG_<tf>_pct: то же для FVG
    - n_zones_at_level:  сколько зон "в области" (price ± 0.5%) суммарно

  ИНДИКАТОРЫ (на 12h):
    - rsi_14: RSI Wilder 14
    - hull_78_slope_pct: наклон Hull MA 78 за последние 3 бара (%)
    - ema_200_dist_pct: расстояние до EMA-200 (% от цены)
    - vol_zscore_20: z-score объёма последних 20 баров

  СТРУКТУРА (12h):
    - dist_from_30d_high_pct: % от 30d HH
    - dist_from_30d_low_pct:  % от 30d LL
    - bars_since_30d_high:    сколько 12h-баров назад был HH
    - bars_since_30d_low:     сколько 12h-баров назад был LL
    - dist_from_7d_mid_pct:   расстояние от mid 7d range

  СВОЙСТВА ФРАКТАЛА:
    - fractal_body_pct: |close-open| / range фрактал-свечи
    - fractal_range_vs_atr: range фрактал-свечи / ATR(14)
    - fractal_is_marubozu: body_pct >= 0.7
    - is_low_fractal: 1 если LOW (рост ожидается), 0 если HIGH

  ПРЕ-ФРАКТАЛ (импульс перед):
    - pre_3d_return_pct: % изменения цены за 3 дня (6 баров) до фрактала
    - pre_7d_return_pct: за 7 дней (14 баров)
    - pre_volatility_atr_pct: ATR-norm волатильность 14 баров до

  HTF КОНТЕКСТ:
    - htf_1d_hull_dir: знак Hull MA(20) на 1d (-1/+1)
    - htf_4h_hull_dir: на 4h (Hull 78 4h)
    - htf_aligned_with_fractal: 1 если HTF trend в нашу сторону

  USDT.D (если есть):
    - usdtd_3d_return_pct: движение USDT.D за 3 дня
    - usdtd_aligned_mirror: 1 если USDT.D mirror-aligned

TARGET:
    - hit_3pct, hit_4pct, hit_5pct (binary)
    - max_move_pct (continuous)

МОДЕЛЬ: GradientBoostingClassifier (sklearn) на hit_3pct.

МЕТРИКИ:
    - AUC, Brier score, AP на TEST
    - Precision/Recall@threshold (0.5, 0.6, 0.7)
    - Expected hit-rate vs baseline
    - Feature importance
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
from dataclasses import dataclass
from collections import defaultdict

from data_manager import load_df, compose_from_base
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg, OBZone, FVGZone

SYMBOL = "BTCUSDT"
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")
TEST_END = pd.Timestamp("2026-05-31", tz="UTC")
START_DATE = pd.Timestamp("2020-01-01", tz="UTC")

FRACTAL_N = 2          # Williams N=2
FUTURE_BARS = 14       # 7 дней 12h
PRE_3D_BARS = 6
PRE_7D_BARS = 14
RSI_LEN = 14
HULL_LEN = 78          # Hull 78 (наш стандартный)
EMA_LEN = 200
VOL_Z_LEN = 20
ATR_LEN = 14

# Targets
TARGETS = [3.0, 4.0, 5.0]


# ============================================================
# ФРАКТАЛЫ
# ============================================================

def find_williams_fractals(df: pd.DataFrame, n: int = 2) -> list[dict]:
    """Williams N=2 fractals на df.

    Returns: list of {'idx', 'time', 'type': 'HIGH'/'LOW', 'price', 'conf_idx', 'conf_time'}
    """
    highs = df['high'].values
    lows = df['low'].values
    times = df.index
    out = []
    for i in range(n, len(df) - n):
        h_win = highs[i-n:i+n+1]
        l_win = lows[i-n:i+n+1]
        if highs[i] == h_win.max() and (h_win == highs[i]).sum() == 1:
            out.append({
                'idx': i, 'time': times[i], 'type': 'HIGH', 'price': float(highs[i]),
                'conf_idx': i+n, 'conf_time': times[i+n],
            })
        if lows[i] == l_win.min() and (l_win == lows[i]).sum() == 1:
            out.append({
                'idx': i, 'time': times[i], 'type': 'LOW', 'price': float(lows[i]),
                'conf_idx': i+n, 'conf_time': times[i+n],
            })
    return out


# ============================================================
# ИНДИКАТОРЫ
# ============================================================

def rsi_wilder(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def wma(values: np.ndarray, length: int) -> np.ndarray:
    weights = np.arange(1, length + 1, dtype=float)
    out = np.full(len(values), np.nan)
    for i in range(length - 1, len(values)):
        out[i] = np.dot(values[i - length + 1:i + 1], weights) / weights.sum()
    return out


def hull_ma(series: pd.Series, length: int = 78) -> pd.Series:
    half = length // 2
    sqrtl = int(np.sqrt(length))
    raw = 2 * wma(series.values, half) - wma(series.values, length)
    hull = wma(pd.Series(raw).fillna(0).values, sqrtl)
    return pd.Series(hull, index=series.index)


def ema(series: pd.Series, length: int = 200) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    high = df['high']; low = df['low']; close = df['close']
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()


# ============================================================
# ЗОНЫ (OB/FVG) на момент confirmation
# ============================================================

def collect_active_zones(df: pd.DataFrame, conf_idx: int, lookback: int = 200) -> dict:
    """Соберём OB/FVG зоны, активные на момент conf_idx (родились до, не закрыты).

    Простое определение mitigation: зона закрыта когда любая будущая свеча
    проходит через неё полностью. Для скорости — просто берём недавние и проверяем
    что цена ещё в неё не зашла за весь lookback.

    Returns: {'OB': [OBZone, ...], 'FVG': [FVGZone, ...]} (без mitigation для скорости)
    """
    ob_list = []
    fvg_list = []
    start = max(2, conf_idx - lookback)
    for j in range(start, conf_idx + 1):
        ob = detect_ob_pair(df, j)
        if ob is not None:
            ob_list.append(ob)
        fvg = detect_fvg(df, j)
        if fvg is not None:
            fvg_list.append(fvg)
    return {'OB': ob_list, 'FVG': fvg_list}


def zone_features(price: float, zones: dict, tf_label: str, is_low_fractal: bool) -> dict:
    """Из списка OB/FVG зон собрать фичи: in_zone, dist_to_nearest_same_dir."""
    feats = {}
    target_dir = 'LONG' if is_low_fractal else 'SHORT'

    for typ in ['OB', 'FVG']:
        in_zone = 0
        dist_same_pct = 100.0  # большое число если нет
        n_same = 0
        for z in zones[typ]:
            if z.bottom <= price <= z.top:
                in_zone = 1
            if z.direction == target_dir:
                n_same += 1
                # ближайшая граница
                if price < z.bottom:
                    d = (z.bottom - price) / price * 100
                elif price > z.top:
                    d = (price - z.top) / price * 100
                else:
                    d = 0.0
                if d < dist_same_pct:
                    dist_same_pct = d
        feats[f'in_{typ}_{tf_label}'] = in_zone
        feats[f'dist_{typ}_{tf_label}_pct'] = min(dist_same_pct, 20.0)
        feats[f'n_{typ}_{tf_label}_same_dir'] = n_same
    return feats


# ============================================================
# СБОР ВСЕХ ФИЧЕЙ
# ============================================================

def build_features(
    df_12h: pd.DataFrame,
    df_1d: pd.DataFrame,
    df_4h: pd.DataFrame,
    df_2h: pd.DataFrame,
    df_1h: pd.DataFrame,
    df_usdtd_12h: pd.DataFrame | None,
    fractals: list[dict],
) -> pd.DataFrame:
    """Для каждого фрактала собрать вектор фичей + target."""

    # Pre-compute индикаторы на 12h
    rsi12 = rsi_wilder(df_12h['close'], RSI_LEN)
    hull12 = hull_ma(df_12h['close'], HULL_LEN)
    ema200 = ema(df_12h['close'], EMA_LEN)
    atr14 = atr(df_12h, ATR_LEN)
    vol_z = (df_12h['volume'] - df_12h['volume'].rolling(VOL_Z_LEN).mean()) / df_12h['volume'].rolling(VOL_Z_LEN).std()

    # 1d Hull
    hull_1d = hull_ma(df_1d['close'], 20)
    # 4h Hull
    hull_4h = hull_ma(df_4h['close'], 78)

    # USDT.D вспомогательно
    if df_usdtd_12h is not None and not df_usdtd_12h.empty:
        ud_close = df_usdtd_12h['close']
    else:
        ud_close = None

    rows = []
    skipped = 0

    for f in fractals:
        ts_f = f['time']
        ts_conf = f['conf_time']
        price = f['price']
        is_low = (f['type'] == 'LOW')
        conf_idx = f['conf_idx']

        # Target: max move в окне [conf_idx+1 .. conf_idx+FUTURE_BARS]
        future = df_12h.iloc[conf_idx+1 : conf_idx+1+FUTURE_BARS]
        if len(future) < 3:  # слишком мало будущего
            skipped += 1
            continue

        if is_low:
            max_move = (future['high'].max() - price) / price * 100
        else:
            max_move = (price - future['low'].min()) / price * 100

        feat = {
            'fractal_time': ts_f,
            'conf_time': ts_conf,
            'price': price,
            'is_low_fractal': int(is_low),
            'max_move_pct': max_move,
        }
        for t in TARGETS:
            feat[f'hit_{int(t)}pct'] = int(max_move >= t)

        # Индикаторы на момент conf_idx
        feat['rsi_14'] = float(rsi12.iloc[conf_idx]) if not pd.isna(rsi12.iloc[conf_idx]) else 50.0
        # Hull slope = (hull[i] - hull[i-3]) / hull[i-3] * 100
        h_now = hull12.iloc[conf_idx]
        h_prev = hull12.iloc[conf_idx-3] if conf_idx >= 3 else h_now
        feat['hull_78_slope_pct'] = float((h_now - h_prev) / h_prev * 100) if h_prev else 0.0
        feat['ema_200_dist_pct'] = float((price - ema200.iloc[conf_idx]) / price * 100) if not pd.isna(ema200.iloc[conf_idx]) else 0.0
        feat['vol_zscore_20'] = float(vol_z.iloc[conf_idx]) if not pd.isna(vol_z.iloc[conf_idx]) else 0.0

        # Структура: 30d HH/LL = 60 баров 12h
        win30 = df_12h.iloc[max(0, conf_idx-60):conf_idx+1]
        hh = win30['high'].max(); ll = win30['low'].min()
        feat['dist_from_30d_high_pct'] = float((hh - price) / price * 100)
        feat['dist_from_30d_low_pct'] = float((price - ll) / price * 100)
        idx_hh = win30['high'].idxmax(); idx_ll = win30['low'].idxmin()
        feat['bars_since_30d_high'] = int(conf_idx - df_12h.index.get_loc(idx_hh))
        feat['bars_since_30d_low'] = int(conf_idx - df_12h.index.get_loc(idx_ll))
        win7 = df_12h.iloc[max(0, conf_idx-14):conf_idx+1]
        mid7 = (win7['high'].max() + win7['low'].min()) / 2
        feat['dist_from_7d_mid_pct'] = float((price - mid7) / price * 100)

        # Свойства фрактал-свечи
        fc = df_12h.iloc[f['idx']]
        rng = fc['high'] - fc['low']
        body = abs(fc['close'] - fc['open'])
        feat['fractal_body_pct'] = float(body / rng) if rng else 0.0
        feat['fractal_range_vs_atr'] = float(rng / atr14.iloc[f['idx']]) if not pd.isna(atr14.iloc[f['idx']]) and atr14.iloc[f['idx']] else 1.0
        feat['fractal_is_marubozu'] = int(feat['fractal_body_pct'] >= 0.7)

        # Pre-fractal momentum
        if f['idx'] >= PRE_3D_BARS:
            p_start_3d = df_12h['close'].iloc[f['idx'] - PRE_3D_BARS]
            feat['pre_3d_return_pct'] = float((price - p_start_3d) / p_start_3d * 100)
        else:
            feat['pre_3d_return_pct'] = 0.0
        if f['idx'] >= PRE_7D_BARS:
            p_start_7d = df_12h['close'].iloc[f['idx'] - PRE_7D_BARS]
            feat['pre_7d_return_pct'] = float((price - p_start_7d) / p_start_7d * 100)
        else:
            feat['pre_7d_return_pct'] = 0.0
        pre_vol = df_12h.iloc[max(0, f['idx']-PRE_7D_BARS):f['idx']]
        if len(pre_vol):
            avg_range = (pre_vol['high'] - pre_vol['low']).mean()
            feat['pre_volatility_atr_pct'] = float(avg_range / price * 100)
        else:
            feat['pre_volatility_atr_pct'] = 0.0

        # HTF trend alignment
        try:
            h1d_at = hull_1d.asof(ts_conf)
            h1d_prev = hull_1d.asof(ts_conf - pd.Timedelta(days=3))
            htf1d_dir = 1 if h1d_at > h1d_prev else -1
        except Exception:
            htf1d_dir = 0
        try:
            h4h_at = hull_4h.asof(ts_conf)
            h4h_prev = hull_4h.asof(ts_conf - pd.Timedelta(hours=12))
            htf4h_dir = 1 if h4h_at > h4h_prev else -1
        except Exception:
            htf4h_dir = 0
        feat['htf_1d_hull_dir'] = htf1d_dir
        feat['htf_4h_hull_dir'] = htf4h_dir
        # aligned: LOW fractal в восходящем HTF = aligned
        expected_dir = 1 if is_low else -1
        feat['htf_1d_aligned'] = int(htf1d_dir == expected_dir)
        feat['htf_4h_aligned'] = int(htf4h_dir == expected_dir)

        # USDT.D (если есть)
        if ud_close is not None:
            try:
                ud_now = ud_close.asof(ts_conf)
                ud_prev = ud_close.asof(ts_conf - pd.Timedelta(days=3))
                if pd.notna(ud_now) and pd.notna(ud_prev) and ud_prev:
                    ud_ret = (ud_now - ud_prev) / ud_prev * 100
                    feat['usdtd_3d_return_pct'] = float(ud_ret)
                    # mirror align: LOW fractal (рост) ожидает USDT.D вниз
                    if is_low:
                        feat['usdtd_aligned_mirror'] = int(ud_ret < 0)
                    else:
                        feat['usdtd_aligned_mirror'] = int(ud_ret > 0)
                else:
                    feat['usdtd_3d_return_pct'] = 0.0
                    feat['usdtd_aligned_mirror'] = 0
            except Exception:
                feat['usdtd_3d_return_pct'] = 0.0
                feat['usdtd_aligned_mirror'] = 0
        else:
            feat['usdtd_3d_return_pct'] = 0.0
            feat['usdtd_aligned_mirror'] = 0

        # ЗОНЫ — на каждом TF собираем при conf_idx (используем asof для других TF)
        # 12h zones
        z12 = collect_active_zones(df_12h, conf_idx, lookback=150)
        feat.update(zone_features(price, z12, '12h', is_low))

        # 1d zones — найдём conf_idx на 1d
        try:
            idx_1d = df_1d.index.get_indexer([ts_conf], method='pad')[0]
            if idx_1d >= 2:
                z1d = collect_active_zones(df_1d, idx_1d, lookback=120)
                feat.update(zone_features(price, z1d, '1d', is_low))
        except Exception:
            pass

        # 4h zones
        try:
            idx_4h = df_4h.index.get_indexer([ts_conf], method='pad')[0]
            if idx_4h >= 2:
                z4h = collect_active_zones(df_4h, idx_4h, lookback=200)
                feat.update(zone_features(price, z4h, '4h', is_low))
        except Exception:
            pass

        # 2h zones
        try:
            idx_2h = df_2h.index.get_indexer([ts_conf], method='pad')[0]
            if idx_2h >= 2:
                z2h = collect_active_zones(df_2h, idx_2h, lookback=300)
                feat.update(zone_features(price, z2h, '2h', is_low))
        except Exception:
            pass

        # 1h zones
        try:
            idx_1h = df_1h.index.get_indexer([ts_conf], method='pad')[0]
            if idx_1h >= 2:
                z1h = collect_active_zones(df_1h, idx_1h, lookback=400)
                feat.update(zone_features(price, z1h, '1h', is_low))
        except Exception:
            pass

        rows.append(feat)

    print(f'  Skipped (no future): {skipped}')
    return pd.DataFrame(rows)


# ============================================================
# MAIN
# ============================================================

def main():
    print("="*70)
    print("etap_160: Fractal 12h strength ML — train 2020-2024, test 2025-2026")
    print("="*70)
    print()

    t0 = time.time()
    print("Loading data...")
    df_1h = load_df(SYMBOL, "1h")
    df_1d = load_df(SYMBOL, "1d")
    df_12h = compose_from_base(df_1h, "12h")
    df_4h = compose_from_base(df_1h, "4h")
    df_2h = compose_from_base(df_1h, "2h")

    cutoff_low = START_DATE
    cutoff_hi = TEST_END
    for name, df in [('1h', df_1h), ('1d', df_1d), ('12h', df_12h), ('4h', df_4h), ('2h', df_2h)]:
        # уже привязаны по index
        pass

    df_1h = df_1h[(df_1h.index >= cutoff_low) & (df_1h.index <= cutoff_hi)].copy()
    df_1d = df_1d[(df_1d.index >= cutoff_low) & (df_1d.index <= cutoff_hi)].copy()
    df_12h = df_12h[(df_12h.index >= cutoff_low) & (df_12h.index <= cutoff_hi)].copy()
    df_4h = df_4h[(df_4h.index >= cutoff_low) & (df_4h.index <= cutoff_hi)].copy()
    df_2h = df_2h[(df_2h.index >= cutoff_low) & (df_2h.index <= cutoff_hi)].copy()
    print(f"  12h bars: {len(df_12h)}  range: {df_12h.index[0]} -> {df_12h.index[-1]}")
    print(f"  data load: {time.time()-t0:.1f}s")

    # USDT.D — есть ли?
    usdtd_path = _ROOT / 'data' / 'USDT_D_12h.csv'
    df_ud_12h = None
    if usdtd_path.exists():
        df_ud_12h = pd.read_csv(usdtd_path, index_col=0, parse_dates=True)
        if df_ud_12h.index.tz is None:
            df_ud_12h.index = df_ud_12h.index.tz_localize('UTC')
        print(f"  USDT.D 12h: {len(df_ud_12h)} bars")
    else:
        print(f"  USDT.D 12h: NOT FOUND ({usdtd_path}) — feature will be 0")

    print()
    print("Detecting 12h fractals...")
    fractals = find_williams_fractals(df_12h, FRACTAL_N)
    print(f"  Total: {len(fractals)}  HIGH={sum(1 for f in fractals if f['type']=='HIGH')}  LOW={sum(1 for f in fractals if f['type']=='LOW')}")
    print()

    print("Building features (это займёт несколько минут)...")
    t1 = time.time()
    feat_df = build_features(df_12h, df_1d, df_4h, df_2h, df_1h, df_ud_12h, fractals)
    print(f"  Features built: {feat_df.shape[0]} rows × {feat_df.shape[1]} cols  ({time.time()-t1:.1f}s)")
    feat_df['fractal_time'] = pd.to_datetime(feat_df['fractal_time'], utc=True)
    feat_df = feat_df.sort_values('fractal_time').reset_index(drop=True)
    print()

    # Split train/test
    train_mask = feat_df['fractal_time'] < TRAIN_END
    test_mask = ~train_mask
    train_df = feat_df[train_mask].copy()
    test_df = feat_df[test_mask].copy()
    print(f"Train: {len(train_df)}  range {train_df['fractal_time'].min()} -> {train_df['fractal_time'].max()}")
    print(f"Test:  {len(test_df)}   range {test_df['fractal_time'].min()} -> {test_df['fractal_time'].max()}")
    print()

    # Baseline rates
    print("=== Baseline rates ===")
    for t in TARGETS:
        col = f'hit_{int(t)}pct'
        print(f"  hit_{int(t)}pct: TRAIN {train_df[col].mean()*100:.1f}%  TEST {test_df[col].mean()*100:.1f}%")
    print(f"  avg max_move: TRAIN {train_df['max_move_pct'].mean():.2f}%  TEST {test_df['max_move_pct'].mean():.2f}%")
    print()

    # Features
    drop_cols = ['fractal_time', 'conf_time', 'price', 'max_move_pct'] + [f'hit_{int(t)}pct' for t in TARGETS]
    feature_cols = [c for c in feat_df.columns if c not in drop_cols]
    print(f"Feature cols ({len(feature_cols)}):")
    for c in feature_cols: print(f'  {c}')
    print()

    X_train = train_df[feature_cols].fillna(0).values
    X_test = test_df[feature_cols].fillna(0).values

    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.metrics import roc_auc_score, brier_score_loss, average_precision_score, classification_report

    out_dir = _ROOT / 'research' / 'elements_study' / 'output'
    out_dir.mkdir(parents=True, exist_ok=True)

    print("="*70)
    print("TRAINING MODELS")
    print("="*70)
    print()

    summary = []
    all_predictions = []

    for t in TARGETS:
        target_col = f'hit_{int(t)}pct'
        y_train = train_df[target_col].values
        y_test = test_df[target_col].values

        print(f"--- Target: hit_{int(t)}pct ---")
        print(f"  train positives: {y_train.sum()}/{len(y_train)} ({y_train.mean()*100:.1f}%)")
        print(f"  test  positives: {y_test.sum()}/{len(y_test)} ({y_test.mean()*100:.1f}%)")

        clf = GradientBoostingClassifier(
            n_estimators=200, max_depth=4, learning_rate=0.05,
            min_samples_leaf=20, random_state=42,
        )
        t2 = time.time()
        clf.fit(X_train, y_train)
        p_test = clf.predict_proba(X_test)[:, 1]
        print(f"  fit time: {time.time()-t2:.1f}s")

        # OOS metrics
        try:
            auc = roc_auc_score(y_test, p_test)
        except Exception:
            auc = float('nan')
        brier = brier_score_loss(y_test, p_test)
        ap = average_precision_score(y_test, p_test)
        print(f"  OOS AUC = {auc:.3f}  Brier = {brier:.3f}  AP = {ap:.3f}")

        # Threshold sweep
        print(f"\n  Threshold sweep (OOS):")
        print(f"  {'thr':>5}  {'n_kept':>6}  {'kept%':>6}  {'hit%':>6}  {'lift':>5}  {'avg_move%':>9}")
        baseline = y_test.mean() * 100
        for thr in [0.0, 0.3, 0.4, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8]:
            keep = p_test >= thr
            n = keep.sum()
            if n == 0:
                continue
            hit_rate = y_test[keep].mean() * 100
            avg_move = test_df['max_move_pct'].values[keep].mean()
            lift = hit_rate / baseline if baseline else 0
            print(f"  {thr:>5.2f}  {n:>6d}  {n/len(y_test)*100:>5.1f}%  {hit_rate:>5.1f}%  {lift:>4.2f}x  {avg_move:>8.2f}%")

        # Feature importance
        fi = sorted(zip(feature_cols, clf.feature_importances_), key=lambda x: -x[1])
        print(f"\n  TOP-15 features:")
        for name, imp in fi[:15]:
            print(f"    {imp:.4f}  {name}")
        print()

        # Save predictions
        pred_df = test_df[['fractal_time', 'is_low_fractal', 'price', 'max_move_pct', target_col]].copy()
        pred_df['p_hit'] = p_test
        pred_df.to_csv(out_dir / f'etap_160_predictions_hit{int(t)}.csv', index=False)
        if int(t) == 3:
            all_predictions = pred_df.copy()

        summary.append({
            'target': f'hit_{int(t)}pct',
            'train_n': len(y_train), 'test_n': len(y_test),
            'train_pos_rate': y_train.mean(), 'test_pos_rate': y_test.mean(),
            'auc': auc, 'brier': brier, 'ap': ap,
        })

    # Save summary
    sdf = pd.DataFrame(summary)
    sdf.to_csv(out_dir / 'etap_160_summary.csv', index=False)
    print()
    print("="*70)
    print("SUMMARY")
    print("="*70)
    print(sdf.to_string(index=False))
    print()
    print(f"Total time: {time.time()-t0:.1f}s")
    print(f"Output: {out_dir}/etap_160_*.csv")


if __name__ == "__main__":
    main()
