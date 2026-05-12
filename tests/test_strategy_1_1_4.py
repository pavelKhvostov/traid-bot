"""Unit-тесты для Strategy 1.1.4 — top FVG-1d/12h + FVG-4h/6h -> OB-1h/2h + FVG-15m/20m.

Все тесты на искусственных свечах. Никакого I/O, никакой сети.
Покрытие: happy-path LONG/SHORT, SL=ob_htf.bottom/top, edge cases
(нет top-FVG, top-FVG без валидного macro, противоположное направление).
"""
from __future__ import annotations

import pandas as pd
import pytest

from strategies.strategy_1_1_4 import detect_strategy_1_1_4_signals


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


# ---------- Test 1: happy-path LONG через 1d FVG + 4h FVG + 1h OB + 15m FVG ----------

def test_happy_path_long_via_1d_4h_1h_15m():
    """Полная воронка LONG: top-FVG-1d → macro-FVG-4h → OB-1h → entry-FVG-15m."""
    df_1d = make_df([
        ("2026-01-01", 90, 95, 88, 90, 100),     # c0.high=95
        ("2026-01-02", 92, 110, 90, 105, 100),   # c1
        ("2026-01-03", 105, 110, 100, 108, 100), # c2.low=100
    ])
    # top-FVG-1d LONG: high(c0)=95 < low(c2)=100 → zone [95, 100], c2_time=2026-01-03

    df_4h = make_df([
        ("2026-01-03 04:00", 96, 96, 95.5, 95.7, 10),   # c0.high=96
        ("2026-01-03 08:00", 96, 97, 95.5, 96.5, 10),   # c1
        ("2026-01-03 12:00", 98, 98.5, 98, 98.2, 10),   # c2.low=98 (внутри top-FVG [95,100])
    ])
    # macro-FVG-4h LONG: 96 < 98 → zone [96, 98], c2_time=12:00 ≥ top.c2_time=2026-01-03 → invalidation не нужна

    df_1h = make_df([
        ("2026-01-04 02:00", 98, 98.5, 97.5, 97, 10),    # prev bearish
        ("2026-01-04 03:00", 97, 99, 97, 99, 10),         # cur bullish, close(99) > prev.open(98)
    ])
    # OB-1h LONG: prev.close(97) < prev.open(98), cur.close(99) > prev.open(98)
    # zone = [min(97.5, 97), 98] = [97, 98]. Overlap с top-FVG [95,100] ✓ и macro [96,98] ✓

    df_15m = make_df([
        ("2026-01-04 03:15", 97.5, 97.5, 97.3, 97.4, 1),  # c0.high=97.5
        ("2026-01-04 03:30", 97.5, 97.6, 97.3, 97.5, 1),  # c1
        ("2026-01-04 03:45", 97.7, 97.9, 97.7, 97.8, 1),  # c2.low=97.7
    ])
    # entry-FVG-15m LONG: 97.5 < 97.7 → zone [97.5, 97.7]. Overlap с OB-1h [97,98] ✓
    # Окно 15m в OB-1h: [prev_time=02:00, cur_time + (60-15)min = 03:45]

    sigs = detect_strategy_1_1_4_signals(
        df_1d, empty_df(), df_4h, empty_df(), df_1h, empty_df(),
        df_15m, empty_df(), verbose=False,
    )
    assert len(sigs) == 1
    s = sigs[0]
    assert s["direction"] == "LONG"
    assert s["top_tf"] == "1d"
    assert s["fvg_macro_tf"] == "4h"
    assert s["ob_htf_tf"] == "1h"
    assert s["fvg_tf"] == "15m"
    # entry = mid(15m FVG) = (97.5 + 97.7) / 2
    assert s["entry"] == pytest.approx((97.5 + 97.7) / 2)
    # SL = ob_htf.bottom = 97 (без буфера)
    assert s["sl"] == pytest.approx(97.0)
    assert s["top_fvg_zone"] == (95.0, 100.0)
    assert s["ob_htf_zone"] == (97.0, 98.0)


# ---------- Test 2: happy-path SHORT через 12h FVG + 6h FVG + 2h OB + 20m FVG ----------

def test_happy_path_short_via_12h_6h_2h_20m():
    """Полная воронка SHORT: top-FVG-12h → macro-FVG-6h → OB-2h → entry-FVG-20m."""
    df_12h = make_df([
        ("2026-02-01 00:00", 110, 112, 105, 108, 100),  # c0.low=105
        ("2026-02-01 12:00", 108, 109, 102, 102, 100),  # c1
        ("2026-02-02 00:00", 100,  98,  90, 92,  100),  # c2.high=98
    ])
    # top-FVG-12h SHORT: low(c0)=105 > high(c2)=98 → zone [98, 105], c2_time=2026-02-02 00:00

    df_6h = make_df([
        ("2026-02-02 00:00", 99, 100, 99,  99.5, 10),   # c0.low=99
        ("2026-02-02 06:00", 99,  99,  98.5, 98.5, 10), # c1
        ("2026-02-02 12:00", 98,  98,  97.5, 97.7, 10), # c2.high=98 → нужно low(c0) > high(c2): 99 > 98 ✓
    ])
    # macro-FVG-6h SHORT: 99 > 98 → zone [98, 99]. SHORT requires top∈top-FVG: 99 ∈ [98,105] ✓
    # c2_time=12:00, окно [c0_top=2026-02-01 00:00, c2_top+12h=2026-02-02 12:00) → 12:00 НЕ в окне (строго <).

    # Двинем macro раньше
    df_6h = make_df([
        ("2026-02-02 00:00", 99, 100, 99,  99.5, 10),   # c0
        ("2026-02-02 06:00", 99,  99,  98.5, 98.5, 10), # c1
        # делаем разрыв: c0=00:00 high=100, c2=12:00 low=88
        # SHORT: low(c0)=99 > high(c2)
    ])

    # Перестрою — давай SHORT macro раньше top-c2
    df_12h = make_df([
        ("2026-02-01 00:00", 110, 112, 105, 108, 100),  # c0 low=105
        ("2026-02-01 12:00", 108, 109, 100, 102, 100),  # c1
        ("2026-02-02 00:00", 100,  98,  90,  92,  100), # c2 high=98
    ])
    # top-FVG-12h SHORT: zone [98, 105], c2=2026-02-02 00:00, окно macro в [c0=2026-02-01 00:00, c2+12h=2026-02-02 12:00)

    df_6h = make_df([
        ("2026-02-01 00:00", 105, 110, 104, 109, 10),   # c0.low=104
        ("2026-02-01 06:00", 109, 110, 100, 102, 10),   # c1
        ("2026-02-01 12:00", 100, 102,  98,  99,  10),  # c2.high=102 → low(c0)=104 > high(c2)=102 ✓
        ("2026-02-01 18:00", 99, 100,  98, 98.5, 10),   # filler invalidation: high=100 < top=104? нет, проверка high > top для SHORT
    ])
    # macro-FVG-6h SHORT: 104 > 102 → zone [102, 104]. top∈top-FVG [98,105]: 104 ∈ ✓
    # c2_time=2026-02-01 12:00 < top.c2_time=2026-02-02 00:00 → invalidation: check high > f.top=104
    # invalidation окно [c2+6h = 18:00, top.c2+12h = 2026-02-02 12:00)
    # filler 18:00 high=100, не > 104 → ok

    df_2h = make_df([
        ("2026-02-02 14:00", 99,  99.5, 98.5, 99.2, 10),   # prev bullish (close > open)
        ("2026-02-02 16:00", 99.2, 100,  98,   98.5, 10),  # cur bearish, close(98.5) < prev.open(99)
    ])
    # OB-2h SHORT: prev close(99.2) > open(99), cur close(98.5) < prev.open(99)
    # zone = [99, max(99.5, 100)] = [99, 100]. overlap top [98,105] ✓ и macro [102,104]?
    # нет — [99,100] не пересекается с [102,104]! исправлю.
    df_2h = make_df([
        ("2026-02-02 14:00", 102, 102.5, 101.5, 102.2, 10),  # prev bullish (close > open) close=102.2 > open=102
        ("2026-02-02 16:00", 102.2, 103, 101, 101.5, 10),    # cur bearish close(101.5) < prev.open(102)
    ])
    # OB-2h SHORT: zone = [102, max(102.5, 103)] = [102, 103]. overlap [98,105] ✓ и [102,104] ✓
    # search_start htf = top.c2 + 12h = 2026-02-02 12:00. ob prev=14:00 > search_start ✓

    df_20m = make_df([
        ("2026-02-02 16:20", 102.5, 103, 102.4, 102.6, 1),   # c0.low=102.4
        ("2026-02-02 16:40", 102.5, 102.7, 102.3, 102.4, 1), # c1
        ("2026-02-02 17:00", 102.0, 102.2, 101.5, 101.7, 1), # c2.high=102.2 → 102.4 > 102.2 ✓
    ])
    # entry-FVG-20m SHORT: low(c0)=102.4 > high(c2)=102.2 → zone [102.2, 102.4]
    # окно 20m в OB-2h: [prev=14:00, cur+(120-20)min=17:40] → c2 17:00 ✓
    # overlap c OB-2h [102,103]: zone [102.2, 102.4] ✓

    sigs = detect_strategy_1_1_4_signals(
        empty_df(), df_12h, empty_df(), df_6h, empty_df(), df_2h,
        empty_df(), df_20m, verbose=False,
    )
    assert len(sigs) == 1
    s = sigs[0]
    assert s["direction"] == "SHORT"
    assert s["top_tf"] == "12h"
    assert s["fvg_macro_tf"] == "6h"
    assert s["ob_htf_tf"] == "2h"
    assert s["fvg_tf"] == "20m"
    # entry = mid 20m FVG = (102.2 + 102.4) / 2 = 102.3
    assert s["entry"] == pytest.approx(102.3)
    # SL = ob_htf.top = 103 (без буфера)
    assert s["sl"] == pytest.approx(103.0)
    assert s["top_fvg_zone"] == (98.0, 105.0)
    assert s["ob_htf_zone"] == (102.0, 103.0)


# ---------- Test 3: edge — нет top-FVG → 0 сигналов ----------

def test_no_top_fvg_yields_no_signals():
    """Если top-1d нет валидной FVG (нет gap между c0 и c2) → 0 сигналов."""
    df_1d = make_df([
        ("2026-01-01", 100, 105, 95, 100, 100),
        ("2026-01-02", 100, 106, 96, 102, 100),
        ("2026-01-03", 102, 107, 97, 103, 100),
    ])
    # high(c0)=105, low(c2)=97 → 105 > 97, нет LONG FVG
    # low(c0)=95,  high(c2)=107 → 95 < 107, нет SHORT FVG

    sigs = detect_strategy_1_1_4_signals(
        df_1d, empty_df(), empty_df(), empty_df(),
        empty_df(), empty_df(), empty_df(), empty_df(),
        verbose=False,
    )
    assert sigs == []


# ---------- Test 4: edge — top-FVG есть, но macro противоположного направления ----------

def test_top_fvg_with_wrong_direction_macro_yields_no_signals():
    """top-FVG LONG, но FVG-4h SHORT → пропускается (direction mismatch)."""
    df_1d = make_df([
        ("2026-01-01", 90, 95, 88, 90, 100),
        ("2026-01-02", 92, 110, 90, 105, 100),
        ("2026-01-03", 105, 110, 100, 108, 100),
    ])
    # top-FVG-1d LONG zone [95, 100]

    df_4h = make_df([
        ("2026-01-03 04:00", 99, 100, 98, 99.5, 10),    # c0.low=98, high=100
        ("2026-01-03 08:00", 99, 99, 97, 97.5, 10),
        ("2026-01-03 12:00", 96, 96, 95, 95.5, 10),     # c2.high=96
    ])
    # FVG-4h SHORT: low(c0)=98 > high(c2)=96 → SHORT zone [96, 98], но top — LONG → пропускается

    sigs = detect_strategy_1_1_4_signals(
        df_1d, empty_df(), df_4h, empty_df(),
        empty_df(), empty_df(), empty_df(), empty_df(),
        verbose=False,
    )
    assert sigs == []


# ---------- Test 5: edge — top-FVG + macro есть, но нет OB-htf → 0 сигналов ----------

def test_no_htf_ob_yields_no_signals():
    """top-FVG + macro валидны, но 1h без OB-pair → 0 сигналов."""
    df_1d = make_df([
        ("2026-01-01", 90, 95, 88, 90, 100),
        ("2026-01-02", 92, 110, 90, 105, 100),
        ("2026-01-03", 105, 110, 100, 108, 100),
    ])
    df_4h = make_df([
        ("2026-01-03 04:00", 96, 96, 95.5, 95.7, 10),
        ("2026-01-03 08:00", 96, 97, 95.5, 96.5, 10),
        ("2026-01-03 12:00", 98, 98.5, 98, 98.2, 10),
    ])
    # 1h без OB-pair: монотонные свечи
    df_1h = make_df([
        ("2026-01-04 00:00", 100, 101, 99, 100.5, 10),
        ("2026-01-04 01:00", 100.5, 101.5, 100, 101, 10),
        ("2026-01-04 02:00", 101, 102, 100.5, 101.5, 10),
    ])

    sigs = detect_strategy_1_1_4_signals(
        df_1d, empty_df(), df_4h, empty_df(),
        df_1h, empty_df(), empty_df(), empty_df(),
        verbose=False,
    )
    assert sigs == []
