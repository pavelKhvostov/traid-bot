"""CHoCH/BOS tests — LuxAlgo canon."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from candle import Candle
from elements.choch_bos.code import (
    scan_market_structure,
    detect_choch,
    detect_bos,
    _is_fractal_high,
    _is_fractal_low,
)


# ────────────────────────────────────────────────────────────
# Fractal detection
# ────────────────────────────────────────────────────────────

def test_fractal_high_strict_5bar():
    """Williams BW 5-bar (length=5, p=2): high[2] строго выше окрестностей."""
    bars = [
        Candle(open=100, high=101, low=99, close=100),
        Candle(open=100, high=102, low=99, close=101),
        Candle(open=101, high=105, low=100, close=104),   # center, FH
        Candle(open=104, high=103, low=101, close=102),
        Candle(open=102, high=102, low=100, close=101),
    ]
    assert _is_fractal_high(bars, center=2, p=2)


def test_fractal_low_strict_5bar():
    bars = [
        Candle(open=100, high=101, low=99, close=100),
        Candle(open=100, high=100, low=98, close=99),
        Candle(open=99, high=99, low=95, close=96),       # center, FL
        Candle(open=96, high=98, low=97, close=97),
        Candle(open=97, high=99, low=98, close=98),
    ]
    assert _is_fractal_low(bars, center=2, p=2)


def test_fractal_high_rejected_when_equal():
    """Strict: равенство НЕ фрактал."""
    bars = [
        Candle(open=100, high=105, low=99, close=100),    # high == pivot
        Candle(open=100, high=102, low=99, close=101),
        Candle(open=101, high=105, low=100, close=104),   # center
        Candle(open=104, high=103, low=101, close=102),
        Candle(open=102, high=102, low=100, close=101),
    ]
    assert not _is_fractal_high(bars, center=2, p=2)


# ────────────────────────────────────────────────────────────
# Scan: first bullish break = BOS (os was 0)
# ────────────────────────────────────────────────────────────

def test_first_bullish_break_is_bos():
    """Изначально os=0. Первый bullish break → BOS (не CHoCH)."""
    bars = [
        Candle(open=99,  high=100, low=98,  close=99),    # 0
        Candle(open=99,  high=102, low=98,  close=101),   # 1
        Candle(open=101, high=105, low=100, close=104),   # 2 — FH confirmed at n=4
        Candle(open=104, high=104, low=102, close=103),   # 3
        Candle(open=103, high=104, low=101, close=102),   # 4 — confirms FH at idx 2
        Candle(open=102, high=104, low=101, close=103),   # 5
        Candle(open=103, high=107, low=102, close=106),   # 6 — close 106 > 105 (upper) → bullish break
    ]
    events = scan_market_structure(bars, length=5)
    assert len(events) == 1
    e = events[0]
    assert e.type == "BOS"
    assert e.side == "bullish"
    assert e.fractal_idx == 2
    assert e.fractal_level == 105
    assert e.break_idx == 6


# ────────────────────────────────────────────────────────────
# Reversal: bullish BOS then bearish CHoCH
# ────────────────────────────────────────────────────────────

def test_bullish_bos_then_bearish_choch():
    """Сначала bullish break (BOS, os→+1), потом bearish break → CHoCH (os was +1)."""
    bars = [
        # FH @ 2 (high=105)
        Candle(open=99,  high=100, low=98,  close=99),
        Candle(open=99,  high=102, low=98,  close=101),
        Candle(open=101, high=105, low=100, close=104),
        Candle(open=104, high=104, low=102, close=103),
        Candle(open=103, high=104, low=101, close=102),
        # FL @ 5 (low=98) — strict fractal: окрестность 3..7 ВСЕ > 98
        Candle(open=102, high=103, low=99, close=100),    # 5
        Candle(open=100, high=101, low=98, close=99),     # 6 — FL center? нет, low=98
        Candle(open=99,  high=100, low=99, close=99.5),   # 7
        # bullish break: close > 105 (upper from FH @2)
        Candle(open=99.5, high=107, low=99, close=106),   # 8 → BOS bullish (os: 0 → +1)
        # then bearish — нужен новый lower fractal после break
        Candle(open=106, high=108, low=104, close=107),   # 9
        Candle(open=107, high=110, low=105, close=109),   # 10 — FH new (но не пробьём)
        Candle(open=109, high=110, low=106, close=108),   # 11
        Candle(open=108, high=109, low=104, close=105),   # 12 — FL center (low=104)?
        Candle(open=105, high=107, low=104.5, close=106), # 13
        Candle(open=106, high=108, low=105, close=107),   # 14 — confirms FL @12
        # bearish break: close < 104 (lower from FL @12)
        Candle(open=107, high=108, low=100, close=103),   # 15 → bearish break, os: +1 → CHoCH
    ]
    events = scan_market_structure(bars, length=5)
    # Должно быть как минимум: BOS bullish (на ~8), потом CHoCH bearish
    bullish_events = [e for e in events if e.side == "bullish"]
    bearish_events = [e for e in events if e.side == "bearish"]
    assert any(e.type == "BOS" for e in bullish_events)
    assert any(e.type == "CHoCH" for e in bearish_events)


# ────────────────────────────────────────────────────────────
# Filters
# ────────────────────────────────────────────────────────────

def test_detect_choch_filters_only_choch():
    bars = [
        Candle(open=99,  high=100, low=98,  close=99),
        Candle(open=99,  high=102, low=98,  close=101),
        Candle(open=101, high=105, low=100, close=104),
        Candle(open=104, high=104, low=102, close=103),
        Candle(open=103, high=104, low=101, close=102),
        Candle(open=102, high=104, low=101, close=103),
        Candle(open=103, high=107, low=102, close=106),
    ]
    all_events = scan_market_structure(bars, length=5)
    chochs = detect_choch(bars, length=5)
    bos = detect_bos(bars, length=5)
    assert len(chochs) + len(bos) == len(all_events)
    assert all(e.type == "CHoCH" for e in chochs)
    assert all(e.type == "BOS" for e in bos)


def test_no_break_no_events():
    """Цена не пробивает ни одного фрактала."""
    bars = [
        Candle(open=99,  high=100, low=98,  close=99),
        Candle(open=99,  high=102, low=98,  close=101),
        Candle(open=101, high=105, low=100, close=104),   # FH @ 2
        Candle(open=104, high=104, low=102, close=103),
        Candle(open=103, high=104, low=101, close=102),
        Candle(open=102, high=104, low=101, close=103),
        Candle(open=103, high=104.5, low=102, close=104), # close 104 < upper 105
    ]
    assert scan_market_structure(bars, length=5) == []


def test_min_break_depth_pct():
    """С min_break_depth_pct=1.0 close должен быть > upper × 1.01."""
    bars = [
        Candle(open=99,  high=100, low=98,  close=99),
        Candle(open=99,  high=102, low=98,  close=101),
        Candle(open=101, high=105, low=100, close=104),   # FH @ 2 (upper=105)
        Candle(open=104, high=104, low=102, close=103),
        Candle(open=103, high=104, low=101, close=102),
        Candle(open=102, high=104, low=101, close=103),
        Candle(open=103, high=106, low=102, close=105.5), # close 105.5 > 105 но < 105×1.01=106.05
    ]
    events = scan_market_structure(bars, length=5, min_break_depth_pct=1.0)
    assert events == []


def test_length_validation():
    import pytest
    with pytest.raises(ValueError):
        scan_market_structure([], length=2)
