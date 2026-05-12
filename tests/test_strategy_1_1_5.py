"""Unit-тесты для Strategy 1.1.5 — полная воронка
1d-фрактал → 4h/6h sweep+OB → 1h/2h OB + 15m/20m FVG.

Покрытие:
  - happy SHORT через HH-1d → 4h sweep+OB → 1h OB + 15m FVG
  - happy LONG  через LL-1d → 6h sweep+OB → 2h OB + 20m FVG
  - edge: первая касающаяся 4h-свеча пробивает уровень → 0 сигналов
  - edge: «особый случай» macro_ob_cur_is_sweep + полная воронка под ним
  - edge: после snipe не нашлось macro OB в окне k_after → 0 сигналов
  - edge: macro OB найден, но нет 1h/2h OB+FVG entry → 0 сигналов
  - edge: 1d без фрактала i±2 → 0 сигналов
"""
from __future__ import annotations

import pandas as pd

from strategies.strategy_1_1_5 import detect_strategy_1_1_5_signals


def make_df(candles: list[tuple]) -> pd.DataFrame:
    """[(ts_str, open, high, low, close, volume), ...] -> DataFrame с UTC index."""
    idx = pd.DatetimeIndex(
        [pd.Timestamp(c[0], tz="UTC") for c in candles],
        tz="UTC", name="open_time",
    )
    return pd.DataFrame({
        "open":   [c[1] for c in candles],
        "high":   [c[2] for c in candles],
        "low":    [c[3] for c in candles],
        "close":  [c[4] for c in candles],
        "volume": [c[5] for c in candles],
    }, index=idx)


def empty_df() -> pd.DataFrame:
    return pd.DataFrame(
        {"open": [], "high": [], "low": [], "close": [], "volume": []},
        index=pd.DatetimeIndex([], tz="UTC", name="open_time"),
    )


# Стандартный 1d с HH=110 на 2026-01-03 (для SHORT-кейсов).
def _df_1d_hh() -> pd.DataFrame:
    return make_df([
        ("2026-01-01", 95,  100, 95, 98,  100),
        ("2026-01-02", 98,  105, 92, 100, 100),
        ("2026-01-03", 100, 110, 96, 105, 100),  # HH high=110, low=96 не LL
        ("2026-01-04", 105, 108, 91, 95,  100),
        ("2026-01-05", 95,  104, 90, 100, 100),
    ])


# Стандартный 1d с LL=80 на 2026-02-03 (для LONG-кейсов).
def _df_1d_ll() -> pd.DataFrame:
    return make_df([
        ("2026-02-01", 100, 105, 90, 95, 100),
        ("2026-02-02", 95,  100, 88, 92, 100),
        ("2026-02-03", 92,  95,  80, 85, 100),  # LL low=80, high=95 не HH
        ("2026-02-04", 85,  90,  82, 88, 100),
        ("2026-02-05", 88,  95,  84, 90, 100),
    ])


# ---------- Test 1: happy SHORT — HH 1d → 4h sweep+OB → 1h OB + 15m FVG ----------

def test_happy_short_full_funnel_4h_1h_15m():
    df_1d = _df_1d_hh()
    df_4h = make_df([
        ("2026-01-06 00:00", 100, 105,   99,    102, 10),
        ("2026-01-06 04:00", 102, 112,   107,   109, 10),  # SWEEP (high=112>110, close=109<110)
        ("2026-01-06 08:00", 109, 110,   109,   110, 10),  # OB-macro prev — bullish
        ("2026-01-06 12:00", 110, 110.5, 107.5, 108, 10),  # OB-macro cur  — bearish, close<prev.open
        ("2026-01-06 16:00", 108, 109,   107,   108, 10),  # filler
    ])
    # OB-macro SHORT zone = [109, 110.5], cur=12:00, search_start_htf=16:00
    df_1h = make_df([
        ("2026-01-06 16:00", 109.5, 110.2, 109.3, 110.0, 10),  # OB-htf prev — bullish
        ("2026-01-06 17:00", 110.0, 110.4, 108.8, 109.4, 10),  # OB-htf cur  — bearish, close=109.4<prev.open=109.5
    ])
    # OB-1h SHORT zone = [109.5, max(110.2, 110.4)] = [109.5, 110.4], overlap с [109, 110.5] ✓
    # FVG-15m окно: [16:00, 17:00 + 45min = 17:45]
    df_15m = make_df([
        ("2026-01-06 16:00", 110.5, 110.5, 110.0, 110.2, 1),  # c0: low=110.0
        ("2026-01-06 16:15", 110.2, 110.2, 109.7, 109.8, 1),  # c1
        ("2026-01-06 16:30", 109.8, 109.8, 109.4, 109.5, 1),  # c2: high=109.8
    ])
    # FVG-15m SHORT: low(c0)=110.0 > high(c2)=109.8 → zone [109.8, 110.0], overlap с [109.5, 110.4] ✓

    sigs = detect_strategy_1_1_5_signals(
        df_1d, df_4h, empty_df(), df_1h, empty_df(), df_15m, empty_df(),
        k_after=3,
    )
    assert len(sigs) == 1
    s = sigs[0]
    assert s["direction"] == "SHORT"
    assert s["fractal_type"] == "HH"
    assert s["sweep_tf"] == "4h"
    assert s["macro_ob_tf"] == "4h"
    assert s["macro_ob_zone"] == (109.0, 110.5)
    assert s["macro_ob_cur_is_sweep"] is False
    assert s["ob_htf_tf"] == "1h"
    assert s["ob_htf_prev_time"] == pd.Timestamp("2026-01-06 16:00", tz="UTC")
    assert s["ob_htf_cur_time"] == pd.Timestamp("2026-01-06 17:00", tz="UTC")
    assert s["ob_htf_zone"] == (109.5, 110.4)
    assert s["fvg_entry_tf"] == "15m"
    assert s["fvg_entry_zone"] == (109.8, 110.0)
    assert s["signal_time"] == pd.Timestamp("2026-01-06 16:30", tz="UTC")


# ---------- Test 2: happy LONG — LL 1d → 6h sweep+OB → 2h OB + 20m FVG ----------

def test_happy_long_full_funnel_6h_2h_20m():
    df_1d = _df_1d_ll()
    df_6h = make_df([
        ("2026-02-06 00:00", 90,   92, 85, 88,   10),
        ("2026-02-06 06:00", 88,   90, 78, 82,   10),  # SWEEP (low=78<80, close=82>80)
        ("2026-02-06 12:00", 82,   84, 81, 80.5, 10),  # OB-macro prev — bearish
        ("2026-02-06 18:00", 80.5, 84, 79, 83,   10),  # OB-macro cur  — bullish, close>prev.open
    ])
    # OB-macro LONG zone = [79, 82], cur=18:00, search_start_htf=2026-02-07 00:00
    df_2h = make_df([
        ("2026-02-07 00:00", 81, 81.2, 79.5, 80, 10),  # OB-htf prev — bearish
        ("2026-02-07 02:00", 80, 82.5, 79.8, 82, 10),  # OB-htf cur  — bullish, close>prev.open
    ])
    # OB-2h LONG zone = [min(79.5, 79.8), 81] = [79.5, 81], overlap с [79, 82] ✓
    # FVG-20m окно: [00:00, 02:00 + 100min = 03:40]
    df_20m = make_df([
        ("2026-02-07 02:00", 79.8, 80.0, 79.5, 80.0, 1),   # c0: high=80.0
        ("2026-02-07 02:20", 80.0, 80.3, 79.7, 79.9, 1),   # c1
        ("2026-02-07 02:40", 80.6, 81.0, 80.5, 80.8, 1),   # c2: low=80.5
    ])
    # FVG-20m LONG: high(c0)=80.0 < low(c2)=80.5 → zone [80.0, 80.5], overlap с [79.5, 81] ✓

    sigs = detect_strategy_1_1_5_signals(
        df_1d, empty_df(), df_6h, empty_df(), df_2h, empty_df(), df_20m,
        k_after=3,
    )
    assert len(sigs) == 1
    s = sigs[0]
    assert s["direction"] == "LONG"
    assert s["sweep_tf"] == "6h"
    assert s["macro_ob_tf"] == "6h"
    assert s["macro_ob_zone"] == (79.0, 82.0)
    assert s["ob_htf_tf"] == "2h"
    assert s["ob_htf_zone"] == (79.5, 81.0)
    assert s["fvg_entry_tf"] == "20m"
    assert s["fvg_entry_zone"] == (80.0, 80.5)


# ---------- Test 3: edge — первая касающаяся 4h-свеча пробивает фрактал ----------

def test_first_touching_candle_breaks_level_yields_no_signal():
    df_1d = _df_1d_hh()
    df_4h = make_df([
        ("2026-01-06 00:00", 100, 105, 99,  102, 10),
        ("2026-01-06 04:00", 102, 112, 107, 111, 10),  # close=111 ≥ 110 → broken
        ("2026-01-06 08:00", 111, 113, 110, 112, 10),
    ])

    sigs = detect_strategy_1_1_5_signals(
        df_1d, df_4h, empty_df(), empty_df(), empty_df(), empty_df(), empty_df(),
        k_after=3,
    )
    assert sigs == []


# ---------- Test 4: «особый случай» macro_ob_cur_is_sweep + полная воронка ----------

def test_special_case_macro_ob_cur_is_sweep_with_full_funnel():
    df_1d = _df_1d_hh()
    df_4h = make_df([
        # idx 0: prev OB-macro. Bullish (close=108>open=105). High=109 ≤ 110, не касается уровня.
        ("2026-01-06 00:00", 105, 109, 104, 108, 10),
        # idx 1: SWEEP + cur OB-macro одновременно. high=112>110, close=104<110, close<prev.open=105.
        ("2026-01-06 04:00", 108, 112, 104, 104, 10),
        ("2026-01-06 08:00", 104, 105, 103, 104, 10),  # filler
    ])
    # OB-macro SHORT zone = [105, max(109, 112)] = [105, 112]. cur=04:00, search_start_htf=08:00
    df_1h = make_df([
        ("2026-01-06 08:00", 106, 109,   105, 108,   10),  # OB-htf prev — bullish
        ("2026-01-06 09:00", 108, 109.5, 104, 105,   10),  # OB-htf cur  — bearish, close<prev.open=106
    ])
    # OB-1h SHORT zone = [106, max(109, 109.5)] = [106, 109.5], overlap с [105, 112] ✓
    df_15m = make_df([
        ("2026-01-06 08:00", 108.5, 108.8, 109.0 - 0.0, 108.7, 1),  # c0: low=109.0 (через high поле — but compute manually)
    ])
    # упрощу: построю валидный SHORT FVG-15m в окне [08:00, 09:00 + 45min = 09:45]
    df_15m = make_df([
        ("2026-01-06 08:00", 108.7, 109.0, 108.5, 108.8, 1),  # c0: low=108.5
        ("2026-01-06 08:15", 108.8, 108.9, 108.0, 108.2, 1),  # c1
        ("2026-01-06 08:30", 108.0, 108.2, 107.5, 107.8, 1),  # c2: high=108.2
    ])
    # SHORT FVG-15m: low(c0)=108.5 > high(c2)=108.2 → zone [108.2, 108.5]. overlap с OB-1h [106, 109.5] ✓

    sigs = detect_strategy_1_1_5_signals(
        df_1d, df_4h, empty_df(), df_1h, empty_df(), df_15m, empty_df(),
        k_after=3,
    )
    assert len(sigs) == 1
    s = sigs[0]
    assert s["direction"] == "SHORT"
    assert s["sweep_time"] == pd.Timestamp("2026-01-06 04:00", tz="UTC")
    assert s["macro_ob_prev_time"] == pd.Timestamp("2026-01-06 00:00", tz="UTC")
    assert s["macro_ob_cur_time"] == pd.Timestamp("2026-01-06 04:00", tz="UTC")
    assert s["macro_ob_zone"] == (105.0, 112.0)
    assert s["macro_ob_cur_is_sweep"] is True
    assert s["ob_htf_tf"] == "1h"
    assert s["ob_htf_zone"] == (106.0, 109.5)
    assert s["fvg_entry_tf"] == "15m"
    assert s["fvg_entry_zone"] == (108.2, 108.5)


# ---------- Test 5: edge — sweep валиден, но в [sweep, sweep+k_after] нет macro OB ----------

def test_no_macro_ob_in_window_yields_no_signal():
    df_1d = _df_1d_hh()
    df_4h = make_df([
        ("2026-01-06 00:00", 100, 105, 99,  102, 10),  # filler
        ("2026-01-06 04:00", 102, 112, 107, 109, 10),  # SWEEP (bullish)
        ("2026-01-06 08:00", 110, 110, 105, 105, 10),  # bearish, но close>prev.open=102 → не SHORT
        ("2026-01-06 12:00", 104, 104, 100, 100, 10),  # bearish, prev bearish → не SHORT
        ("2026-01-06 16:00", 99,  100, 95,  95,  10),  # bearish, prev bearish → не SHORT
    ])

    sigs = detect_strategy_1_1_5_signals(
        df_1d, df_4h, empty_df(), empty_df(), empty_df(), empty_df(), empty_df(),
        k_after=3,
    )
    assert sigs == []


# ---------- Test 6: edge — macro OB найден, но нет 1h/2h OB+FVG entry → [] ----------

def test_macro_ob_without_htf_fvg_yields_no_signal():
    """4h sweep+OB валидны, но 1h/2h не дают OB+FVG в зоне → скип."""
    df_1d = _df_1d_hh()
    df_4h = make_df([
        ("2026-01-06 00:00", 100, 105,   99,    102, 10),
        ("2026-01-06 04:00", 102, 112,   107,   109, 10),
        ("2026-01-06 08:00", 109, 110,   109,   110, 10),
        ("2026-01-06 12:00", 110, 110.5, 107.5, 108, 10),
    ])
    # 1h без OB-pair: монотонные свечи (все bearish, нет prev bullish для SHORT OB)
    df_1h = make_df([
        ("2026-01-06 16:00", 110, 110.5, 109, 109.2, 10),
        ("2026-01-06 17:00", 109, 109.5, 108, 108.2, 10),
        ("2026-01-06 18:00", 108, 108.5, 107, 107.2, 10),
    ])

    sigs = detect_strategy_1_1_5_signals(
        df_1d, df_4h, empty_df(), df_1h, empty_df(), empty_df(), empty_df(),
        k_after=3,
    )
    assert sigs == []


# ---------- Test 7: edge — 1d без фрактала i±2 ----------

def test_no_fractal_yields_no_signal():
    df_1d = make_df([
        ("2026-01-01", 100, 110, 90,  105, 100),
        ("2026-01-02", 105, 115, 95,  110, 100),
        ("2026-01-03", 110, 120, 100, 115, 100),
        ("2026-01-04", 115, 125, 105, 120, 100),
        ("2026-01-05", 120, 130, 110, 125, 100),
    ])

    sigs = detect_strategy_1_1_5_signals(
        df_1d, empty_df(), empty_df(), empty_df(), empty_df(), empty_df(), empty_df(),
        k_after=3,
    )
    assert sigs == []
