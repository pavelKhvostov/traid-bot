"""etap_172: Bulkowski reversal-pattern detectors + Bulkowski-style backtest.

12 паттернов с высоким edge по Bulkowski "Encyclopedia of Chart Patterns" 3rd ed.
Реализованы как чистые функции detect_<name>(df, i, lookback) -> dict|None.
None если паттерн на баре i не сформирован/не подтверждён.
dict с полями: pattern, side ('long'/'short'), breakout_idx,
                low_idx, low_price, high_idx, high_price, height_pct,
                duration_bars, neck_price (если есть).

Бар i = breakout-бар: цена ЗАКРЫЛАСЬ за пределы confirmation line.
Все компоненты паттерна (peaks/valleys) confirmed (n=2 right side) до бара i.
НЕТ lookahead'а — детектор использует только данные ≤ i.

Bulkowski metrics на каждый сработавший паттерн:
  - failure_rate: % случаев, где |move| < 5%
  - avg_move_pct: средний move от breakout до ultimate extreme
  - median_bars_to_extreme: медиана баров до ultimate (12h-бары)
  - busted_rate: % где move<10% и потом close за противоположную сторону
  - hit_target_rate: % где |move| >= height_pct (full measure rule)
  - half_target_rate: % где |move| >= height_pct/2 (half measure rule)

Ultimate high/low — определяется как у Bulkowski:
  - максимум/минимум до 20% контр-движения от пика, или конец данных.

Период: 2020-01-01 → 2024-12-31 (train), 2025-2026 (OOS отдельно).

Output:
  research/elements_study/output/etap_172_stats.csv  — таблица per-pattern
  research/elements_study/output/etap_172_signals.csv — все срабатывания
                                                        (time, pattern, side, ...)
                                                        для подключения как фичи в etap_173.
"""
from __future__ import annotations
import sys as _sys
import time
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd

from data_manager import load_df, compose_from_base

SYMBOL = "BTCUSDT"
START_DATE = pd.Timestamp("2020-01-01", tz="UTC")
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")
TEST_END = pd.Timestamp("2026-05-31", tz="UTC")

# Параметры детекторов
SWING_N = 2  # n right-side bars для confirm фрактала
LOOKBACK = 60  # макс. бар-окно паттерна (60 баров = 30 дней на 12h)
MIN_VALLEY_DEPTH_PCT = 3.0  # минимальная глубина впадины между peaks
MIN_PEAK_HEIGHT_PCT = 3.0
PEAK_TOLERANCE_PCT = 3.0  # двойной/тройной — пики в пределах ±3%

# Параметры стат-оценки (Bulkowski)
ULT_REVERSAL_PCT = 20.0  # контр-движение для определения ultimate extreme
FAILURE_PCT = 5.0  # break-even failure threshold
BUST_PCT = 10.0  # busted: move < 10% перед разворотом
MAX_WALK_BARS = 240  # макс. 120 дней (240 баров 12h) для поиска ultimate


# ============================================================
# Утилиты: фрактал / swing
# ============================================================

def confirmed_swings(highs: np.ndarray, lows: np.ndarray, start: int, end: int, n: int = 2):
    """Возвращает confirmed swing highs/lows в [start, end].

    Swing high в j: high[j] строго > high[j-n..j-1] и >= high[j+1..j+n].
    Подтверждение на j+n, значит j+n должен быть ≤ end.
    """
    sh, sl = [], []
    for j in range(max(start, n), min(end - n + 1, len(highs))):
        hh = highs[j]
        if all(hh > highs[j - k] for k in range(1, n + 1)) and \
           all(hh > highs[j + k] for k in range(1, n + 1)):
            sh.append((j, hh))
        ll = lows[j]
        if all(ll < lows[j - k] for k in range(1, n + 1)) and \
           all(ll < lows[j + k] for k in range(1, n + 1)):
            sl.append((j, ll))
    return sh, sl


def slope(x0, y0, x1, y1):
    if x1 == x0:
        return 0.0
    return (y1 - y0) / (x1 - x0)


# ============================================================
# 12 ДЕТЕКТОРОВ
# ============================================================

def detect_big_w(df, i, lookback=LOOKBACK):
    """Big W (Bulkowski Ch.7): twin bottom с tall left side.

    - 2 confirmed swing lows ~same price (±3%)
    - Left rise into pattern минимум = height (tall left)
    - Peak между ними - 12% median
    - Breakout = close above the hill between bottoms
    """
    lo = max(0, i - lookback)
    hi = i + 1
    highs = df['high'].values; lows = df['low'].values; closes = df['close'].values
    sh, sl = confirmed_swings(highs, lows, lo, hi, SWING_N)
    if len(sl) < 2:
        return None
    # Берём 2 последних confirmed lows
    j2, p2 = sl[-1]; j1, p1 = sl[-2]
    if j1 >= j2: return None
    if abs(p1 - p2) / p1 * 100 > PEAK_TOLERANCE_PCT: return None
    # Пик между bottoms
    mid_slice = highs[j1:j2 + 1]
    peak_idx = int(np.argmax(mid_slice)) + j1
    peak_price = highs[peak_idx]
    valley_min = min(p1, p2)
    height = peak_price - valley_min
    height_pct = height / valley_min * 100
    if height_pct < MIN_VALLEY_DEPTH_PCT: return None
    # Tall left side: высота лево-tail до начала паттерна
    # Берём максимум highs в [lo, j1-1] и проверяем что drop into p1 >= height
    if j1 > lo:
        left_max = highs[lo:j1].max()
        left_drop = (left_max - p1) / p1 * 100
        if left_drop < height_pct: return None  # not "tall left"
    # Breakout: close[i] > peak_price
    if closes[i] <= peak_price: return None
    # Проверяем что breakout именно сейчас (не подтверждался ранее)
    if closes[i - 1] > peak_price: return None
    return {
        'pattern': 'big_w', 'side': 'long',
        'breakout_idx': i, 'breakout_price': closes[i],
        'low_idx': j2, 'low_price': p2,
        'high_idx': peak_idx, 'high_price': peak_price,
        'height_pct': height_pct,
        'duration_bars': j2 - j1,
        'neck_price': peak_price,
    }


def detect_big_m(df, i, lookback=LOOKBACK):
    """Big M (Ch.6): twin top, mirror of Big W."""
    lo = max(0, i - lookback)
    hi = i + 1
    highs = df['high'].values; lows = df['low'].values; closes = df['close'].values
    sh, sl = confirmed_swings(highs, lows, lo, hi, SWING_N)
    if len(sh) < 2: return None
    j2, p2 = sh[-1]; j1, p1 = sh[-2]
    if j1 >= j2: return None
    if abs(p1 - p2) / p1 * 100 > PEAK_TOLERANCE_PCT: return None
    mid_slice = lows[j1:j2 + 1]
    valley_idx = int(np.argmin(mid_slice)) + j1
    valley_price = lows[valley_idx]
    peak_max = max(p1, p2)
    height = peak_max - valley_price
    height_pct = height / valley_price * 100
    if height_pct < MIN_VALLEY_DEPTH_PCT: return None
    if j1 > lo:
        left_min = lows[lo:j1].min()
        left_rise = (p1 - left_min) / left_min * 100
        if left_rise < height_pct: return None
    if closes[i] >= valley_price: return None
    if closes[i - 1] < valley_price: return None
    return {
        'pattern': 'big_m', 'side': 'short',
        'breakout_idx': i, 'breakout_price': closes[i],
        'low_idx': valley_idx, 'low_price': valley_price,
        'high_idx': j2, 'high_price': p2,
        'height_pct': height_pct,
        'duration_bars': j2 - j1,
        'neck_price': valley_price,
    }


def detect_db_eve_eve(df, i, lookback=LOOKBACK):
    """Double Bottom Eve&Eve (Ch.29): два округлых дна.

    Отличие от Big W: НЕ требуется tall left side.
    Bulkowski rank 5/39, fail 12%, +50% avg rise.
    Округлость = не V-spike: low_bar и его соседи имеют small body relative to range.
    """
    lo = max(0, i - lookback)
    hi = i + 1
    highs = df['high'].values; lows = df['low'].values
    closes = df['close'].values; opens = df['open'].values
    sh, sl = confirmed_swings(highs, lows, lo, hi, SWING_N)
    if len(sl) < 2: return None
    j2, p2 = sl[-1]; j1, p1 = sl[-2]
    if j2 - j1 < 5: return None  # ≥ several bars apart
    if abs(p1 - p2) / p1 * 100 > PEAK_TOLERANCE_PCT: return None
    peak_idx = int(np.argmax(highs[j1:j2 + 1])) + j1
    peak_price = highs[peak_idx]
    height_pct = (peak_price - min(p1, p2)) / min(p1, p2) * 100
    if height_pct < MIN_VALLEY_DEPTH_PCT: return None
    # "Eve" = wide rounded: широкие маленькие тельца возле дна
    def is_rounded(j):
        win = slice(max(j - 1, 0), min(j + 2, len(closes)))
        rng = highs[win] - lows[win]
        body = np.abs(closes[win] - opens[win])
        if rng.mean() == 0: return False
        return (body / rng).mean() < 0.6
    if not (is_rounded(j1) and is_rounded(j2)): return None
    if closes[i] <= peak_price: return None
    if closes[i - 1] > peak_price: return None
    return {
        'pattern': 'db_eve_eve', 'side': 'long',
        'breakout_idx': i, 'breakout_price': closes[i],
        'low_idx': j2, 'low_price': p2,
        'high_idx': peak_idx, 'high_price': peak_price,
        'height_pct': height_pct,
        'duration_bars': j2 - j1,
        'neck_price': peak_price,
    }


def detect_hs_top(df, i, lookback=LOOKBACK):
    """Head-and-Shoulders Top (Ch.41): 3 peaks, middle highest.

    Bulkowski 9/36 bull, 4/19 bear (5% fail), best busted +67%.
    """
    lo = max(0, i - lookback)
    hi = i + 1
    highs = df['high'].values; lows = df['low'].values; closes = df['close'].values
    sh, sl = confirmed_swings(highs, lows, lo, hi, SWING_N)
    if len(sh) < 3 or len(sl) < 2: return None
    # 3 последних peaks
    j3, p3 = sh[-1]; j2, p2 = sh[-2]; j1, p1 = sh[-3]
    if not (j1 < j2 < j3): return None
    # Middle (head) highest, shoulders ≈ same height
    if not (p2 > p1 and p2 > p3): return None
    if abs(p1 - p3) / p1 * 100 > PEAK_TOLERANCE_PCT * 2: return None  # shoulders within 6%
    # Two valleys между ними
    valleys = [(k, v) for k, v in sl if j1 < k < j3]
    if len(valleys) < 2: return None
    valleys.sort()
    v_left = valleys[0]; v_right = valleys[-1]
    # Neckline через 2 valleys; breakout на close[i] < neckline at x=i
    neckline_at_i = v_left[1] + slope(v_left[0], v_left[1], v_right[0], v_right[1]) * (i - v_left[0])
    height_pct = (p2 - min(v_left[1], v_right[1])) / p2 * 100
    if height_pct < MIN_VALLEY_DEPTH_PCT: return None
    if closes[i] >= neckline_at_i: return None
    prev_neck = v_left[1] + slope(v_left[0], v_left[1], v_right[0], v_right[1]) * (i - 1 - v_left[0])
    if closes[i - 1] < prev_neck: return None
    return {
        'pattern': 'hs_top', 'side': 'short',
        'breakout_idx': i, 'breakout_price': closes[i],
        'low_idx': v_right[0], 'low_price': v_right[1],
        'high_idx': j2, 'high_price': p2,
        'height_pct': height_pct,
        'duration_bars': j3 - j1,
        'neck_price': neckline_at_i,
    }


def detect_hs_bottom(df, i, lookback=LOOKBACK):
    """Inverse Head-and-Shoulders (Ch.39): 3 valleys, middle deepest."""
    lo = max(0, i - lookback)
    hi = i + 1
    highs = df['high'].values; lows = df['low'].values; closes = df['close'].values
    sh, sl = confirmed_swings(highs, lows, lo, hi, SWING_N)
    if len(sl) < 3 or len(sh) < 2: return None
    j3, p3 = sl[-1]; j2, p2 = sl[-2]; j1, p1 = sl[-3]
    if not (j1 < j2 < j3): return None
    if not (p2 < p1 and p2 < p3): return None
    if abs(p1 - p3) / p1 * 100 > PEAK_TOLERANCE_PCT * 2: return None
    peaks = [(k, v) for k, v in sh if j1 < k < j3]
    if len(peaks) < 2: return None
    peaks.sort()
    p_left = peaks[0]; p_right = peaks[-1]
    neckline_at_i = p_left[1] + slope(p_left[0], p_left[1], p_right[0], p_right[1]) * (i - p_left[0])
    height_pct = (max(p_left[1], p_right[1]) - p2) / p2 * 100
    if height_pct < MIN_VALLEY_DEPTH_PCT: return None
    if closes[i] <= neckline_at_i: return None
    prev_neck = p_left[1] + slope(p_left[0], p_left[1], p_right[0], p_right[1]) * (i - 1 - p_left[0])
    if closes[i - 1] > prev_neck: return None
    return {
        'pattern': 'hs_bottom', 'side': 'long',
        'breakout_idx': i, 'breakout_price': closes[i],
        'low_idx': j2, 'low_price': p2,
        'high_idx': p_right[0], 'high_price': p_right[1],
        'height_pct': height_pct,
        'duration_bars': j3 - j1,
        'neck_price': neckline_at_i,
    }


def detect_triple_top(df, i, lookback=LOOKBACK):
    """Triple Top (Ch.68): 3 peaks ~same price.

    Bulkowski-busted edge +60% (single-bust ratio 67%).
    """
    lo = max(0, i - lookback)
    hi = i + 1
    highs = df['high'].values; lows = df['low'].values; closes = df['close'].values
    sh, sl = confirmed_swings(highs, lows, lo, hi, SWING_N)
    if len(sh) < 3: return None
    j3, p3 = sh[-1]; j2, p2 = sh[-2]; j1, p1 = sh[-3]
    if not (j1 < j2 < j3): return None
    peaks = [p1, p2, p3]
    mx, mn = max(peaks), min(peaks)
    if (mx - mn) / mn * 100 > PEAK_TOLERANCE_PCT: return None
    valleys = [(k, v) for k, v in sl if j1 < k < j3]
    if len(valleys) < 2: return None
    valley_min = min(v for _, v in valleys)
    height_pct = (max(peaks) - valley_min) / valley_min * 100
    if height_pct < MIN_VALLEY_DEPTH_PCT: return None
    if closes[i] >= valley_min: return None
    if closes[i - 1] < valley_min: return None
    return {
        'pattern': 'triple_top', 'side': 'short',
        'breakout_idx': i, 'breakout_price': closes[i],
        'low_idx': i, 'low_price': valley_min,
        'high_idx': j2, 'high_price': p2,
        'height_pct': height_pct,
        'duration_bars': j3 - j1,
        'neck_price': valley_min,
    }


def detect_v_bottom(df, i, lookback=20):
    """V-Bottom (Ch.68 V-bottoms): sharp drop then sharp reversal.

    Меньше lookback т.к. V — короткий резкий паттерн (Bulkowski median 3-5 weeks).
    На 12h: окно 20 баров = 10 дней.
    """
    lo = max(0, i - lookback)
    closes = df['close'].values; lows = df['low'].values
    # Lowest low в окне
    seg = lows[lo:i + 1]
    j_low = int(np.argmin(seg)) + lo
    if j_low == i or j_low == lo: return None  # нужно min внутри окна
    p_low = lows[j_low]
    # Drop: max high слева от j_low → p_low ≥ 8%
    left_max = df['high'].values[lo:j_low + 1].max()
    drop_pct = (left_max - p_low) / left_max * 100
    if drop_pct < 8.0: return None
    # Rebound: close[i] vs p_low
    rise_pct = (closes[i] - p_low) / p_low * 100
    if rise_pct < drop_pct * 0.5: return None  # хотя бы половина drop отыграна
    # Symmetry: количество баров drop ≈ rebound
    bars_down = j_low - lo
    bars_up = i - j_low
    if bars_up > bars_down * 2.5 or bars_down > bars_up * 2.5: return None
    # Breakout: close[i] > midpoint
    midpoint = (left_max + p_low) / 2
    if closes[i] <= midpoint: return None
    if closes[i - 1] > midpoint: return None
    return {
        'pattern': 'v_bottom', 'side': 'long',
        'breakout_idx': i, 'breakout_price': closes[i],
        'low_idx': j_low, 'low_price': p_low,
        'high_idx': lo, 'high_price': left_max,
        'height_pct': drop_pct,
        'duration_bars': i - lo,
        'neck_price': midpoint,
    }


def detect_v_top(df, i, lookback=20):
    """V-Top (Ch.70): sharp rise then sharp drop."""
    lo = max(0, i - lookback)
    closes = df['close'].values; highs = df['high'].values
    seg = highs[lo:i + 1]
    j_high = int(np.argmax(seg)) + lo
    if j_high == i or j_high == lo: return None
    p_high = highs[j_high]
    left_min = df['low'].values[lo:j_high + 1].min()
    rise_pct = (p_high - left_min) / left_min * 100
    if rise_pct < 8.0: return None
    drop_pct = (p_high - closes[i]) / p_high * 100
    if drop_pct < rise_pct * 0.5: return None
    bars_up = j_high - lo
    bars_dn = i - j_high
    if bars_dn > bars_up * 2.5 or bars_up > bars_dn * 2.5: return None
    midpoint = (left_min + p_high) / 2
    if closes[i] >= midpoint: return None
    if closes[i - 1] < midpoint: return None
    return {
        'pattern': 'v_top', 'side': 'short',
        'breakout_idx': i, 'breakout_price': closes[i],
        'low_idx': lo, 'low_price': left_min,
        'high_idx': j_high, 'high_price': p_high,
        'height_pct': rise_pct,
        'duration_bars': i - lo,
        'neck_price': midpoint,
    }


def detect_rounding_bottom(df, i, lookback=40):
    """Rounding Bottom (Ch.55): smooth concave curve.

    Bulkowski lowest fail (4.3%), #1 в bear market.
    Используем R² фита параболы y = a*x^2 + b*x + c, a > 0.
    """
    lo = max(0, i - lookback)
    if i - lo < 12: return None
    closes = df['close'].values
    x = np.arange(lo, i + 1, dtype=float)
    y = closes[lo:i + 1]
    # Fit парабола
    try:
        a, b, c = np.polyfit(x - lo, y, 2)
    except Exception:
        return None
    if a <= 0: return None  # not concave-up
    y_pred = a * (x - lo) ** 2 + b * (x - lo) + c
    ss_res = ((y - y_pred) ** 2).sum()
    ss_tot = ((y - y.mean()) ** 2).sum()
    r2 = 1 - ss_res / max(ss_tot, 1e-9)
    if r2 < 0.55: return None
    # Vertex (минимум) должен быть в средней трети окна
    vert_x = -b / (2 * a)
    if vert_x < (i - lo) * 0.25 or vert_x > (i - lo) * 0.75: return None
    vert_idx = int(round(vert_x)) + lo
    p_low = y[int(round(vert_x))]
    p_left = y[0]; p_right = y[-1]
    # Rim ≈ same price
    if abs(p_left - p_right) / p_left * 100 > PEAK_TOLERANCE_PCT * 2: return None
    height_pct = (max(p_left, p_right) - p_low) / p_low * 100
    if height_pct < MIN_VALLEY_DEPTH_PCT: return None
    # Breakout = close[i] > rim_max
    rim_max = max(p_left, p_right)
    if closes[i] <= rim_max: return None
    if closes[i - 1] > rim_max: return None
    return {
        'pattern': 'rounding_bottom', 'side': 'long',
        'breakout_idx': i, 'breakout_price': closes[i],
        'low_idx': vert_idx, 'low_price': p_low,
        'high_idx': i, 'high_price': rim_max,
        'height_pct': height_pct,
        'duration_bars': i - lo,
        'neck_price': rim_max,
    }


def detect_cup_with_handle(df, i, lookback=60):
    """Cup with Handle (Ch.20): rounded U + handle.

    Bulkowski fail 5.3%, +54% avg.
    """
    lo = max(0, i - lookback)
    if i - lo < 20: return None
    # Handle: последние H_BARS = 3..10 баров — узкая консолидация
    closes = df['close'].values; highs = df['high'].values; lows = df['low'].values
    # Подбираем handle_start как место максимума в окне [i-15, i-3]
    handle_window_start = max(lo + 10, i - 15)
    if handle_window_start >= i: return None
    handle_max_idx = int(np.argmax(highs[handle_window_start:i + 1])) + handle_window_start
    if i - handle_max_idx < 3 or i - handle_max_idx > 15: return None
    handle_start = handle_max_idx
    # Right rim = high[handle_start]
    right_rim = highs[handle_start]
    # Handle: цены [handle_start..i] — retracement макс 40% высоты cup
    handle_low = lows[handle_start:i].min()
    # Cup: [lo, handle_start]
    cup_low_idx = int(np.argmin(closes[lo:handle_start + 1])) + lo
    cup_low = closes[cup_low_idx]
    if cup_low_idx < lo + 3 or cup_low_idx > handle_start - 3: return None
    # Left rim — high слева от cup_low в окне cup
    left_rim = highs[lo:cup_low_idx + 1].max()
    # Rims ≈ same
    if abs(left_rim - right_rim) / left_rim * 100 > PEAK_TOLERANCE_PCT * 2: return None
    height = max(left_rim, right_rim) - cup_low
    height_pct = height / cup_low * 100
    if height_pct < MIN_VALLEY_DEPTH_PCT: return None
    handle_retrace = (right_rim - handle_low) / height
    if handle_retrace > 0.5: return None  # handle не больше 50% cup
    # Rounded cup test: R² параболы на closes[lo..handle_start]
    x = np.arange(handle_start - lo + 1, dtype=float)
    y = closes[lo:handle_start + 1]
    try:
        a, b, c = np.polyfit(x, y, 2)
    except Exception:
        return None
    if a <= 0: return None
    y_pred = a * x ** 2 + b * x + c
    r2 = 1 - ((y - y_pred) ** 2).sum() / max(((y - y.mean()) ** 2).sum(), 1e-9)
    if r2 < 0.45: return None
    # Breakout = close[i] > right_rim
    if closes[i] <= right_rim: return None
    if closes[i - 1] > right_rim: return None
    return {
        'pattern': 'cup_handle', 'side': 'long',
        'breakout_idx': i, 'breakout_price': closes[i],
        'low_idx': cup_low_idx, 'low_price': cup_low,
        'high_idx': handle_start, 'high_price': right_rim,
        'height_pct': height_pct,
        'duration_bars': i - lo,
        'neck_price': right_rim,
    }


def detect_barr_top(df, i, lookback=40):
    """Bump-and-Run Reversal Top (Ch.15): lead-in trendline + bump ≥ 2× lead-in.

    Bulkowski #1 of 36, -17% / 14% fail.
    Алгоритм:
      1. Найти lead-in: первая половина окна, fit линии тренда
         slope_in (положительный) на closes.
      2. Bump: вторая половина — slope_bump > 2× slope_in.
      3. Breakout = close[i] < lead-in trendline value at x=i.
    """
    lo = max(0, i - lookback)
    if i - lo < 16: return None
    closes = df['close'].values
    half = (i - lo) // 2
    # Lead-in: lo..lo+half
    x_in = np.arange(half + 1, dtype=float)
    y_in = closes[lo:lo + half + 1]
    if len(y_in) < 4: return None
    slope_in, intercept_in = np.polyfit(x_in, y_in, 1)
    if slope_in <= 0: return None  # требуется uptrend lead-in
    # Bump: lo+half..i
    x_bp = np.arange(i - (lo + half) + 1, dtype=float)
    y_bp = closes[lo + half:i + 1]
    if len(y_bp) < 4: return None
    slope_bp, intercept_bp = np.polyfit(x_bp, y_bp, 1)
    if slope_bp < slope_in * 1.5: return None  # bump steeper
    # Peak of bump
    peak_idx = int(np.argmax(closes[lo + half:i + 1])) + lo + half
    p_high = closes[peak_idx]
    lead_start_price = closes[lo]
    height_pct = (p_high - lead_start_price) / lead_start_price * 100
    if height_pct < 8.0: return None
    # Lead-in trendline at x=i: intercept_in + slope_in * (i - lo)
    trendline_at_i = intercept_in + slope_in * (i - lo)
    if closes[i] >= trendline_at_i: return None
    prev_trend = intercept_in + slope_in * (i - 1 - lo)
    if closes[i - 1] < prev_trend: return None
    return {
        'pattern': 'barr_top', 'side': 'short',
        'breakout_idx': i, 'breakout_price': closes[i],
        'low_idx': lo, 'low_price': lead_start_price,
        'high_idx': peak_idx, 'high_price': p_high,
        'height_pct': height_pct,
        'duration_bars': i - lo,
        'neck_price': trendline_at_i,
    }


def detect_barr_bottom(df, i, lookback=40):
    """Bump-and-Run Reversal Bottom (Ch.14): mirror BARR top.

    Bulkowski #1 of 39, +55% / 9% fail — лучший reversal в книге.
    """
    lo = max(0, i - lookback)
    if i - lo < 16: return None
    closes = df['close'].values
    half = (i - lo) // 2
    x_in = np.arange(half + 1, dtype=float)
    y_in = closes[lo:lo + half + 1]
    if len(y_in) < 4: return None
    slope_in, intercept_in = np.polyfit(x_in, y_in, 1)
    if slope_in >= 0: return None  # требуется downtrend lead-in
    x_bp = np.arange(i - (lo + half) + 1, dtype=float)
    y_bp = closes[lo + half:i + 1]
    if len(y_bp) < 4: return None
    slope_bp, intercept_bp = np.polyfit(x_bp, y_bp, 1)
    if slope_bp > slope_in * 1.5: return None  # bump steeper (more negative)
    valley_idx = int(np.argmin(closes[lo + half:i + 1])) + lo + half
    p_low = closes[valley_idx]
    lead_start_price = closes[lo]
    height_pct = (lead_start_price - p_low) / lead_start_price * 100
    if height_pct < 8.0: return None
    trendline_at_i = intercept_in + slope_in * (i - lo)
    if closes[i] <= trendline_at_i: return None
    prev_trend = intercept_in + slope_in * (i - 1 - lo)
    if closes[i - 1] > prev_trend: return None
    return {
        'pattern': 'barr_bottom', 'side': 'long',
        'breakout_idx': i, 'breakout_price': closes[i],
        'low_idx': valley_idx, 'low_price': p_low,
        'high_idx': lo, 'high_price': lead_start_price,
        'height_pct': height_pct,
        'duration_bars': i - lo,
        'neck_price': trendline_at_i,
    }


def detect_diamond_top(df, i, lookback=40):
    """Diamond Top (Ch.24): broadening then narrowing.

    Bulkowski 3/36, -17% / 15% fail.
    Геометрия: первая половина — расходящиеся trendlines (ширина растёт),
    вторая — сходящиеся (ширина падает). Breakout — close ниже последнего low.
    """
    lo = max(0, i - lookback)
    if i - lo < 12: return None
    highs = df['high'].values; lows = df['low'].values; closes = df['close'].values
    half = lo + (i - lo) // 2
    # Ширина: high - low в окне
    rng_left = (highs[lo:half + 1] - lows[lo:half + 1])
    rng_right = (highs[half:i + 1] - lows[half:i + 1])
    if len(rng_left) < 4 or len(rng_right) < 4: return None
    x_l = np.arange(len(rng_left), dtype=float)
    x_r = np.arange(len(rng_right), dtype=float)
    slope_l, _ = np.polyfit(x_l, rng_left, 1)
    slope_r, _ = np.polyfit(x_r, rng_right, 1)
    if slope_l <= 0 or slope_r >= 0: return None  # broadening then narrowing
    # Pattern должен быть на uptrend (top)
    if closes[half] <= closes[lo]: return None
    peak_idx = int(np.argmax(highs[lo:i + 1])) + lo
    p_high = highs[peak_idx]
    p_low = lows[half:i + 1].min()
    height_pct = (p_high - p_low) / p_low * 100
    if height_pct < MIN_VALLEY_DEPTH_PCT: return None
    # Breakout: close[i] < last low в правой половине
    last_low = lows[half:i].min() if i > half else lows[half]
    if closes[i] >= last_low: return None
    if closes[i - 1] < last_low: return None
    return {
        'pattern': 'diamond_top', 'side': 'short',
        'breakout_idx': i, 'breakout_price': closes[i],
        'low_idx': i, 'low_price': p_low,
        'high_idx': peak_idx, 'high_price': p_high,
        'height_pct': height_pct,
        'duration_bars': i - lo,
        'neck_price': last_low,
    }


DETECTORS = [
    detect_big_w,
    detect_big_m,
    detect_db_eve_eve,
    detect_hs_top,
    detect_hs_bottom,
    detect_triple_top,
    detect_v_bottom,
    detect_v_top,
    detect_rounding_bottom,
    detect_cup_with_handle,
    detect_barr_top,
    detect_barr_bottom,
    detect_diamond_top,
]


# ============================================================
# WALK-FORWARD: Bulkowski-style outcome
# ============================================================

def walk_outcome(df, signal, max_bars=MAX_WALK_BARS, reversal_pct=ULT_REVERSAL_PCT):
    """От breakout до ultimate extreme (20% counter-move) или конца данных.

    Возвращает dict:
      bars_to_extreme, max_favor_pct (best move в нужную сторону, ABS),
      max_adverse_pct (worst в противоположную, ABS),
      ult_move_pct (sign-aware),
      crossed_opposite_after_small (для busted: move<10% then cross),
      reached_target (heights), reached_half_target.
    """
    i = signal['breakout_idx']
    side = signal['side']
    entry = signal['breakout_price']
    height_pct = signal['height_pct']
    end = min(i + max_bars + 1, len(df))
    if end <= i + 1:
        return None
    closes = df['close'].values[i + 1:end]
    highs = df['high'].values[i + 1:end]
    lows = df['low'].values[i + 1:end]
    # Сторона entry
    if side == 'long':
        favor = (highs - entry) / entry * 100
        adverse = (entry - lows) / entry * 100
        cum_max = np.maximum.accumulate(favor)
        # Ultimate high: highest high до 20% pullback от него
        ult_idx = 0
        for k in range(len(cum_max)):
            if cum_max[k] > 0:
                drop_from_peak = (cum_max[k] - favor[k])
                if drop_from_peak >= reversal_pct:
                    break
                if cum_max[k] > favor[ult_idx] if ult_idx < len(favor) else 0:
                    ult_idx = int(np.argmax(cum_max[:k + 1]))
            ult_idx = int(np.argmax(cum_max[:k + 1]))
        ult_move = favor[ult_idx]
        max_adverse = float(adverse.max())
        # Busted: move<10% favor, then close back below low_price (entry side)
        crossed_opp = False
        opposite_threshold = signal['low_price']
        peak_pre = 0.0
        for k in range(len(closes)):
            peak_pre = max(peak_pre, favor[k])
            if peak_pre < BUST_PCT and closes[k] < opposite_threshold:
                crossed_opp = True
                break
            if peak_pre >= BUST_PCT:
                break
        reached_target = ult_move >= height_pct
        reached_half = ult_move >= height_pct / 2
    else:  # short
        favor = (entry - lows) / entry * 100
        adverse = (highs - entry) / entry * 100
        cum_max = np.maximum.accumulate(favor)
        ult_idx = 0
        for k in range(len(cum_max)):
            if cum_max[k] > 0:
                pullback_from_low = cum_max[k] - favor[k]
                if pullback_from_low >= reversal_pct:
                    break
            ult_idx = int(np.argmax(cum_max[:k + 1]))
        ult_move = favor[ult_idx]
        max_adverse = float(adverse.max())
        crossed_opp = False
        opposite_threshold = signal['high_price']
        peak_pre = 0.0
        for k in range(len(closes)):
            peak_pre = max(peak_pre, favor[k])
            if peak_pre < BUST_PCT and closes[k] > opposite_threshold:
                crossed_opp = True
                break
            if peak_pre >= BUST_PCT:
                break
        reached_target = ult_move >= height_pct
        reached_half = ult_move >= height_pct / 2

    return {
        'bars_to_extreme': ult_idx + 1,
        'ult_move_pct': float(ult_move),
        'max_adverse_pct': float(max_adverse),
        'busted': bool(crossed_opp),
        'reached_target': bool(reached_target),
        'reached_half_target': bool(reached_half),
    }


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("etap_172: Bulkowski reversal-pattern detectors")
    print("12 patterns на BTC 12h, 2020-01-01 -> 2024-12-31 (train) + OOS")
    print("=" * 70)
    print()

    t0 = time.time()
    print("Loading BTC 1h, composing 12h...")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_12h = df_12h[(df_12h.index >= START_DATE) & (df_12h.index <= TEST_END)].copy()
    df_12h = df_12h.reset_index()
    # Имя колонки времени после reset_index зависит от имени индекса. Унифицируем.
    if 'time' not in df_12h.columns:
        df_12h = df_12h.rename(columns={df_12h.columns[0]: 'time'})
    print(f"  12h bars: {len(df_12h)}  range {df_12h['time'].iloc[0]} -> {df_12h['time'].iloc[-1]}")
    print(f"  ({time.time() - t0:.1f}s)")
    print()

    # Run all detectors on every bar
    print("Running 13 detectors over every 12h bar...")
    t1 = time.time()
    signals = []
    for i in range(LOOKBACK + SWING_N + 2, len(df_12h)):
        for det in DETECTORS:
            sig = det(df_12h, i)
            if sig is not None:
                sig['time'] = df_12h['time'].iloc[i]
                signals.append(sig)
    print(f"  total signals: {len(signals)}  ({time.time() - t1:.1f}s)")
    print()

    # Walk forward
    print("Walking forward to determine ultimate extreme per signal...")
    t2 = time.time()
    rows = []
    for sig in signals:
        out = walk_outcome(df_12h, sig)
        if out is None:
            continue
        rec = {**sig, **out}
        rows.append(rec)
    out_df = pd.DataFrame(rows)
    print(f"  outcomes for: {len(out_df)} signals  ({time.time() - t2:.1f}s)")
    print()

    # Split by regime
    out_df['period'] = np.where(out_df['time'] < TRAIN_END, 'train', 'oos')

    # Aggregate stats per pattern × period
    print("=" * 70)
    print("Bulkowski-style stats: TRAIN (2020-2024)")
    print("=" * 70)
    print(f"{'pattern':>18}  {'n':>5}  {'fail%':>6}  {'avg_mov%':>9}  "
          f"{'med_bars':>9}  {'bust%':>6}  {'tgt%':>5}  {'half%':>6}")
    print("-" * 70)
    stats_rows = []
    for pat in sorted(out_df['pattern'].unique()):
        for period in ['train', 'oos']:
            sub = out_df[(out_df['pattern'] == pat) & (out_df['period'] == period)]
            if len(sub) == 0:
                continue
            n = len(sub)
            fail_rate = (sub['ult_move_pct'].abs() < FAILURE_PCT).mean() * 100
            avg_move = sub['ult_move_pct'].mean()
            med_bars = sub['bars_to_extreme'].median()
            bust_rate = sub['busted'].mean() * 100
            tgt_rate = sub['reached_target'].mean() * 100
            half_rate = sub['reached_half_target'].mean() * 100
            stats_rows.append({
                'pattern': pat, 'period': period, 'n': n,
                'failure_rate_pct': round(fail_rate, 1),
                'avg_move_pct': round(avg_move, 2),
                'median_bars_to_extreme': int(med_bars),
                'busted_rate_pct': round(bust_rate, 1),
                'hit_target_rate_pct': round(tgt_rate, 1),
                'half_target_rate_pct': round(half_rate, 1),
            })
            if period == 'train':
                print(f"{pat:>18}  {n:>5d}  {fail_rate:>5.1f}%  {avg_move:>+8.2f}%  "
                      f"{int(med_bars):>9d}  {bust_rate:>5.1f}%  {tgt_rate:>4.1f}%  {half_rate:>5.1f}%")
    print()
    print("=" * 70)
    print("OOS (2025-2026.05)")
    print("=" * 70)
    print(f"{'pattern':>18}  {'n':>5}  {'fail%':>6}  {'avg_mov%':>9}  "
          f"{'med_bars':>9}  {'bust%':>6}  {'tgt%':>5}  {'half%':>6}")
    print("-" * 70)
    for r in stats_rows:
        if r['period'] != 'oos':
            continue
        print(f"{r['pattern']:>18}  {r['n']:>5d}  {r['failure_rate_pct']:>5.1f}%  "
              f"{r['avg_move_pct']:>+8.2f}%  {r['median_bars_to_extreme']:>9d}  "
              f"{r['busted_rate_pct']:>5.1f}%  {r['hit_target_rate_pct']:>4.1f}%  "
              f"{r['half_target_rate_pct']:>5.1f}%")
    print()

    # Сохраняем результаты
    out_dir = _ROOT / 'research' / 'elements_study' / 'output'
    out_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(stats_rows).to_csv(out_dir / 'etap_172_stats.csv', index=False)
    print(f"Saved: {out_dir / 'etap_172_stats.csv'}")

    # Сигналы (для подключения как фичи в etap_173)
    sig_out = out_df[['time', 'pattern', 'side', 'breakout_price',
                      'height_pct', 'duration_bars',
                      'ult_move_pct', 'bars_to_extreme', 'busted', 'period']].copy()
    sig_out.to_csv(out_dir / 'etap_172_signals.csv', index=False)
    print(f"Saved: {out_dir / 'etap_172_signals.csv'}")
    print()
    print("=" * 70)
    print(f"Done in {time.time() - t0:.1f}s")
    print("=" * 70)


if __name__ == '__main__':
    main()
