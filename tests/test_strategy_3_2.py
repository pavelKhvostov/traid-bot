"""Unit-тесты для Strategy 3.2 — FVG-4h → failed-touch → FVG-1h в 8h окне.

Покрытие:
  - happy LONG: FVG-4h LONG → 2 свечи rejection вверх → FVG-1h LONG
  - happy SHORT: FVG-4h SHORT → 2 свечи rejection вниз → FVG-1h SHORT
  - edge: touch-свеча пробивает зону насквозь → []
  - edge: первая свеча close НЕ выше FVG.top (для LONG) → []
  - edge: вторая свеча close НЕ выше FVG.top → []
  - edge: rejection OK, но FVG-1h не образовалась в 8h окне → []
  - edge: нет FVG-4h в данных → []
"""
from __future__ import annotations

import pandas as pd
import pytest

from strategies.strategy_3_2 import detect_strategy_3_2_signals


def make_df(candles: list[tuple]) -> pd.DataFrame:
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


# ---------- Test 1: happy LONG ----------

def test_happy_long_full_funnel():
    df_4h = make_df([
        ("2026-01-01 00:00", 99,    102, 98,    100,   100),  # filler — не FVG
        ("2026-01-01 04:00", 100,   102, 99,    101.5, 100),  # c0 FVG-4h
        ("2026-01-01 08:00", 101.5, 110, 101,   109,   100),  # c1
        ("2026-01-01 12:00", 109,   112, 104,   110,   100),  # c2 → LONG FVG zone [102, 104]
        ("2026-01-01 16:00", 110,   110, 103.5, 105,   100),  # touch (low=103.5≤104, close=105>104)
        ("2026-01-01 20:00", 105,   106, 104.5, 105.5, 100),  # touch+1 (close=105.5>104)
        ("2026-01-02 00:00", 105.5, 106, 104,   104.5, 100),  # filler
    ])
    # 1h свечи: filler перед окном + 8 свечей в окне [16:00, 24:00)
    df_1h = make_df([
        ("2026-01-01 12:00", 109,   110,   109,   110,   10),
        ("2026-01-01 13:00", 110,   110,   109,   109.5, 10),
        ("2026-01-01 14:00", 109.5, 110,   109,   109.5, 10),
        ("2026-01-01 15:00", 109.5, 110,   109,   110,   10),
        ("2026-01-01 16:00", 103.8, 104.0, 103.5, 103.9, 10),  # c0 FVG-1h: high=104.0
        ("2026-01-01 17:00", 103.9, 104.3, 103.7, 104.2, 10),  # c1
        ("2026-01-01 18:00", 104.5, 105.0, 104.5, 104.8, 10),  # c2: low=104.5 → LONG FVG [104.0, 104.5]
        ("2026-01-01 19:00", 104.8, 105.0, 104.0, 104.5, 10),
        ("2026-01-01 20:00", 104.5, 105.0, 104.0, 104.5, 10),
        ("2026-01-01 21:00", 104.5, 105.0, 104.0, 104.5, 10),
        ("2026-01-01 22:00", 104.5, 105.0, 104.0, 104.5, 10),
        ("2026-01-01 23:00", 104.5, 105.0, 104.0, 104.5, 10),
    ])

    sigs = detect_strategy_3_2_signals(df_4h, df_1h)
    assert len(sigs) == 1
    s = sigs[0]
    assert s["direction"] == "LONG"
    assert s["fvg_4h_zone"] == (102.0, 104.0)
    assert s["touch_time"] == pd.Timestamp("2026-01-01 16:00", tz="UTC")
    assert s["touch_close"] == 105.0
    assert s["touch_plus1_close"] == 105.5
    assert s["fvg_1h_zone"] == (104.0, 104.5)
    assert s["fvg_1h_c0_time"] == pd.Timestamp("2026-01-01 16:00", tz="UTC")
    assert s["fvg_1h_c2_time"] == pd.Timestamp("2026-01-01 18:00", tz="UTC")
    assert s["signal_time"] == pd.Timestamp("2026-01-01 18:00", tz="UTC")
    assert s["entry"] == pytest.approx(104.25)
    assert s["sl"] == pytest.approx(103.5)
    assert s["tp"] == pytest.approx(105.0)
    assert s["risk"] == pytest.approx(0.75)


# ---------- Test 2: happy SHORT ----------

def test_happy_short_full_funnel():
    df_4h = make_df([
        ("2026-02-01 00:00", 100, 102, 98,  100, 100),  # filler
        ("2026-02-01 04:00", 100, 101, 96,  98,  100),  # c0 FVG-4h: low=96
        ("2026-02-01 08:00", 98,  99,  88,  90,  100),  # c1
        ("2026-02-01 12:00", 90,  93,  85,  86,  100),  # c2: high=93 → SHORT FVG zone [93, 96]
        ("2026-02-01 16:00", 86,  95,  85,  88,  100),  # touch (high=95≥93, close=88<93)
        ("2026-02-01 20:00", 88,  92,  87,  89,  100),  # touch+1 (close=89<93)
        ("2026-02-02 00:00", 89,  90,  88,  89,  100),  # filler
    ])
    df_1h = make_df([
        ("2026-02-01 12:00", 90, 91, 86, 86, 10),
        ("2026-02-01 13:00", 86, 87, 85, 86, 10),
        ("2026-02-01 14:00", 86, 87, 85, 86, 10),
        ("2026-02-01 15:00", 86, 87, 85, 86, 10),
        ("2026-02-01 16:00", 86, 90.0, 85.5, 89, 10),  # c0 FVG-1h: low=85.5, high=90.0
        ("2026-02-01 17:00", 89, 89.5, 88.0, 88.5, 10),  # c1
        ("2026-02-01 18:00", 88.5, 89.0, 87.5, 87.8, 10),  # c2: high=89.0 → SHORT FVG: low(c0)=85.5? нет
    ])
    # пересчёт: SHORT FVG требует low(c0) > high(c2). low(c0)=85.5, high(c2)=89.0 → 85.5>89? нет.
    # Перестрою:
    df_1h = make_df([
        ("2026-02-01 12:00", 90, 91, 86, 86, 10),
        ("2026-02-01 13:00", 86, 87, 85, 86, 10),
        ("2026-02-01 14:00", 86, 87, 85, 86, 10),
        ("2026-02-01 15:00", 86, 87, 85, 86, 10),
        ("2026-02-01 16:00", 90,   91.0, 89.5, 89.5, 10),  # c0: low=89.5
        ("2026-02-01 17:00", 89.5, 89.7, 88.0, 88.3, 10),  # c1
        ("2026-02-01 18:00", 88.3, 88.5, 87.5, 87.8, 10),  # c2: high=88.5 → SHORT FVG: low(c0)=89.5 > high(c2)=88.5 ✓ zone [88.5, 89.5]
        ("2026-02-01 19:00", 87.8, 88.0, 87.0, 87.5, 10),
        ("2026-02-01 20:00", 87.5, 88.0, 87.0, 87.5, 10),
        ("2026-02-01 21:00", 87.5, 88.0, 87.0, 87.5, 10),
        ("2026-02-01 22:00", 87.5, 88.0, 87.0, 87.5, 10),
        ("2026-02-01 23:00", 87.5, 88.0, 87.0, 87.5, 10),
    ])

    sigs = detect_strategy_3_2_signals(df_4h, df_1h)
    assert len(sigs) == 1
    s = sigs[0]
    assert s["direction"] == "SHORT"
    assert s["fvg_4h_zone"] == (93.0, 96.0)
    assert s["touch_time"] == pd.Timestamp("2026-02-01 16:00", tz="UTC")
    assert s["fvg_1h_zone"] == (88.5, 89.5)
    assert s["entry"] == pytest.approx(89.0)
    assert s["sl"] == pytest.approx(91.0)  # high(c0_1h=16:00)=91.0
    assert s["risk"] == pytest.approx(2.0)
    assert s["tp"] == pytest.approx(87.0)  # entry - risk = 89 - 2


# ---------- Test 3: edge — touch свеча пробивает зону насквозь ----------

def test_touch_candle_breaks_through_zone_yields_no_signal():
    """LONG FVG-4h, но touch-свеча close ≤ FVG.bottom → пробила насквозь, скип."""
    df_4h = make_df([
        ("2026-01-01 00:00", 99,    102, 98,    100,   100),
        ("2026-01-01 04:00", 100,   102, 99,    101.5, 100),  # c0
        ("2026-01-01 08:00", 101.5, 110, 101,   109,   100),  # c1
        ("2026-01-01 12:00", 109,   112, 104,   110,   100),  # c2 → LONG [102, 104]
        ("2026-01-01 16:00", 110,   110, 100,   101,   100),  # touch (low=100≤104, close=101 ≤ 102 = FVG.bottom)
        ("2026-01-01 20:00", 101,   102, 100,   101,   100),
    ])
    df_1h = empty_df()

    sigs = detect_strategy_3_2_signals(df_4h, df_1h)
    assert sigs == []


# ---------- Test 4: edge — первая свеча close НЕ выше FVG.top ----------

def test_first_candle_close_not_above_top_yields_no_signal():
    """LONG FVG-4h, touch close внутри зоны (выше bottom, но ≤ top) → нарушен rejection."""
    df_4h = make_df([
        ("2026-01-01 00:00", 99,    102, 98,    100,   100),
        ("2026-01-01 04:00", 100,   102, 99,    101.5, 100),
        ("2026-01-01 08:00", 101.5, 110, 101,   109,   100),
        ("2026-01-01 12:00", 109,   112, 104,   110,   100),  # LONG [102, 104]
        ("2026-01-01 16:00", 110,   110, 102.5, 103,   100),  # touch close=103, не выше 104
        ("2026-01-01 20:00", 103,   105, 102.5, 105,   100),
    ])
    df_1h = empty_df()

    sigs = detect_strategy_3_2_signals(df_4h, df_1h)
    assert sigs == []


# ---------- Test 5: edge — вторая свеча close НЕ выше FVG.top ----------

def test_second_candle_close_not_above_top_yields_no_signal():
    df_4h = make_df([
        ("2026-01-01 00:00", 99,    102, 98,    100,   100),
        ("2026-01-01 04:00", 100,   102, 99,    101.5, 100),
        ("2026-01-01 08:00", 101.5, 110, 101,   109,   100),
        ("2026-01-01 12:00", 109,   112, 104,   110,   100),  # LONG [102, 104]
        ("2026-01-01 16:00", 110,   110, 103.5, 105,   100),  # touch close=105 > 104 ✓
        ("2026-01-01 20:00", 105,   105, 102.5, 103,   100),  # close=103 ≤ 104 ✗
    ])
    df_1h = empty_df()

    sigs = detect_strategy_3_2_signals(df_4h, df_1h)
    assert sigs == []


# ---------- Test 6: edge — rejection OK, но FVG-1h не образовалась ----------

def test_no_fvg_1h_in_window_yields_no_signal():
    df_4h = make_df([
        ("2026-01-01 00:00", 99,    102, 98,    100,   100),
        ("2026-01-01 04:00", 100,   102, 99,    101.5, 100),
        ("2026-01-01 08:00", 101.5, 110, 101,   109,   100),
        ("2026-01-01 12:00", 109,   112, 104,   110,   100),  # LONG [102, 104]
        ("2026-01-01 16:00", 110,   110, 103.5, 105,   100),
        ("2026-01-01 20:00", 105,   106, 104.5, 105.5, 100),
        ("2026-01-02 00:00", 105.5, 106, 104,   104.5, 100),
    ])
    # 1h свечи в окне без gap между c0 и c2 → нет FVG-1h
    df_1h = make_df([
        ("2026-01-01 16:00", 104, 104.5, 103.5, 104, 10),
        ("2026-01-01 17:00", 104, 104.5, 103.5, 104, 10),
        ("2026-01-01 18:00", 104, 104.5, 103.5, 104, 10),  # high(c0)=104.5 ≥ low(c2)=103.5 → нет LONG FVG
        ("2026-01-01 19:00", 104, 104.5, 103.5, 104, 10),
        ("2026-01-01 20:00", 104, 104.5, 103.5, 104, 10),
        ("2026-01-01 21:00", 104, 104.5, 103.5, 104, 10),
        ("2026-01-01 22:00", 104, 104.5, 103.5, 104, 10),
        ("2026-01-01 23:00", 104, 104.5, 103.5, 104, 10),
    ])

    sigs = detect_strategy_3_2_signals(df_4h, df_1h)
    assert sigs == []


# ---------- Test 7: edge — нет FVG-4h в данных ----------

def test_no_fvg_4h_yields_no_signal():
    df_4h = make_df([
        ("2026-01-01 00:00", 100, 105, 95,  102, 100),
        ("2026-01-01 04:00", 102, 106, 96,  103, 100),
        ("2026-01-01 08:00", 103, 107, 97,  104, 100),  # high(c0)=105, low(c2)=97 → 105>97 нет LONG; 95>107 нет SHORT
    ])
    df_1h = empty_df()

    sigs = detect_strategy_3_2_signals(df_4h, df_1h)
    assert sigs == []
