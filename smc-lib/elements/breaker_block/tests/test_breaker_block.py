"""Tests for breaker_block detection (Canon v4 — 2026-06-15).

v4 semantics:
- Activation: close > prev.high (LONG OB) / close < prev.low (SHORT OB)
  в окне bar 3-6 = post_bars[0..3]
- Wick-fill mitigation от bar после activator
- Bullish breaker (SHORT resist): тестируется bar.low (LONG semantic)
- Bearish breaker (LONG support): тестируется bar.high (SHORT semantic)
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from candle import Candle
from elements.ob.code import detect_ob
from elements.breaker_block.code import detect_breaker, scan_breakers


def _ob_pair_bullish():
    """LONG OB: prev bear, cur bull, close > prev.open. Breaker zone = [prev.open=100, prev.high=120]."""
    prev = Candle(open=110, high=120, low=99, close=100)
    cur = Candle(open=100, high=112, low=99, close=111)
    return prev, cur


def _ob_pair_bearish():
    """SHORT OB: prev bull, cur bear, close < prev.open. Breaker zone = [prev.low=80, prev.open=100]."""
    prev = Candle(open=100, high=101, low=80, close=110)  # noqa: bull (close 110 > open 100? no — fix)
    prev = Candle(open=90, high=101, low=80, close=100)
    cur = Candle(open=100, high=101, low=88, close=89)
    return prev, cur


# ───────────────────────────────────────────────────────────────────────
# Activation in window (Canon v4)
# ───────────────────────────────────────────────────────────────────────

def test_bullish_activated_at_bar_5_diagnostic():
    """Diagnostic example из definition.md: ARM at bar 5 (post[2]) close > prev.high."""
    prev, cur = _ob_pair_bullish()
    ob = detect_ob(prev, cur)
    assert ob is not None
    # OB zone = [99, 110] (drop area); breaker zone = [100, 120] (prev wick)
    post = [
        Candle(open=111, high=113, low=109, close=110),   # bar 3: close 110 ≤ 120, no act
        Candle(open=110, high=115, low=108, close=113),   # bar 4: close 113 ≤ 120, no act
        Candle(open=113, high=122, low=112, close=121),   # bar 5: close 121 > 120 ★ ARMED
        Candle(open=121, high=125, low=117, close=118),   # bar 6: low=117 в зоне → shrink to (110,117)
        Candle(open=118, high=119, low=110, close=112),   # bar 7: low=110 ≤ zone_lo → CONSUMED
    ]
    br = detect_breaker(ob, post)
    assert br is not None
    assert br.direction == "bullish"
    assert br.activated_at_idx == 2   # bar 5 = post[2]
    assert br.initial_zone == (110, 120)   # [prev.open=110, prev.high=120]
    # After bar 6 shrink: (110, 117); after bar 7 CONSUMED
    assert br.shrink_count == 1
    assert br.consumed_at_idx == 4   # bar 7 = post[4]
    assert br.is_active is False


def test_bullish_not_activated_in_window_returns_none():
    """Если в окне 4 свечей нет close > prev.high → return None."""
    prev, cur = _ob_pair_bullish()
    ob = detect_ob(prev, cur)
    # Все 4 post-bar close ≤ 120 → no activation
    post = [
        Candle(open=111, high=119, low=110, close=115),   # close 115 ≤ 120
        Candle(open=115, high=119, low=110, close=118),
        Candle(open=118, high=119, low=110, close=119),
        Candle(open=119, high=120, low=110, close=119),
    ]
    assert detect_breaker(ob, post) is None


def test_bullish_armed_without_consume_stays_active():
    """Armed → дальнейшие bars не возвращаются в zone — breaker остаётся active."""
    prev, cur = _ob_pair_bullish()
    ob = detect_ob(prev, cur)
    post = [
        Candle(open=111, high=113, low=110, close=112),    # bar 3: no act
        Candle(open=112, high=122, low=111, close=121),    # bar 4: close 121 > 120 ★ ARMED at post[1]
        Candle(open=121, high=130, low=125, close=128),    # bar 5: low=125 > zone_hi=120 → no interact
        Candle(open=128, high=135, low=126, close=132),    # bar 6: low=126 > 120 → no interact
        Candle(open=132, high=140, low=130, close=138),    # bar 7: low=130 > 120 → no interact
    ]
    br = detect_breaker(ob, post)
    assert br is not None
    assert br.activated_at_idx == 1
    assert br.consumed_at_idx is None
    assert br.is_active is True
    assert br.shrink_count == 0
    assert br.current_zone == (110, 120)   # без изменений


def test_bullish_partial_shrink_no_consume():
    """Activated, потом частично сжимается, но не consumed."""
    prev, cur = _ob_pair_bullish()
    ob = detect_ob(prev, cur)
    post = [
        Candle(open=111, high=125, low=121, close=122),    # bar 3: close 122 > 120 ★ ARMED at post[0]; low=121 > zone_hi=120 → no interact
        Candle(open=122, high=128, low=115, close=121),    # bar 4: low=115 в зоне → shrink to (110,115)
        Candle(open=121, high=125, low=118, close=120),    # bar 5: low=118 > zone_hi=115 → no interact
        Candle(open=120, high=128, low=112, close=120),    # bar 6: low=112 в зоне (110,115) → shrink (110,112)
    ]
    br = detect_breaker(ob, post)
    assert br is not None
    assert br.activated_at_idx == 0
    assert br.consumed_at_idx is None
    assert br.shrink_count == 2
    assert br.current_zone == (110, 112)


# ───────────────────────────────────────────────────────────────────────
# Bearish (mirror)
# ───────────────────────────────────────────────────────────────────────

def test_bearish_activated_at_bar_3_immediate():
    """Bearish: bar 3 close < prev.low ARMS immediately."""
    prev, cur = _ob_pair_bearish()   # prev bull O=90 H=101 L=80 C=100; cur bear O=100 H=101 L=88 C=89
    ob = detect_ob(prev, cur)
    assert ob is not None
    assert ob.direction == "short"
    # Breaker zone = [prev.low=80, prev.open=90]
    post = [
        Candle(open=89, high=92, low=78, close=79),       # bar 3: close 79 < 80 ★ ARMED at post[0]
        Candle(open=79, high=85, low=72, close=78),       # bar 4: high=85 в зоне (80,90) → shrink (85,90)
        Candle(open=78, high=90, low=70, close=85),       # bar 5: high=90 ≥ zone_hi=90 → CONSUMED
    ]
    br = detect_breaker(ob, post)
    assert br is not None
    assert br.direction == "bearish"
    assert br.activated_at_idx == 0
    assert br.initial_zone == (80, 90)
    assert br.shrink_count == 1
    assert br.consumed_at_idx == 2


def test_bearish_not_activated_returns_none():
    """Bearish: ни один из bar 3-6 не close < prev.low → return None."""
    prev, cur = _ob_pair_bearish()
    ob = detect_ob(prev, cur)
    post = [
        Candle(open=89, high=90, low=81, close=82),       # close 82 ≥ 80, no act
        Candle(open=82, high=88, low=81, close=85),
        Candle(open=85, high=90, low=82, close=83),
        Candle(open=83, high=89, low=81, close=82),
    ]
    assert detect_breaker(ob, post) is None


# ───────────────────────────────────────────────────────────────────────
# Edge cases
# ───────────────────────────────────────────────────────────────────────

def test_degenerate_prev_no_wick_returns_none():
    """prev без верхнего фитиля (open == high) → нет breaker zone."""
    # Bullish OB attempt с дегенератным prev: prev.open == prev.high
    prev = Candle(open=120, high=120, low=100, close=100)   # bear, no upper wick
    cur = Candle(open=100, high=125, low=99, close=124)
    ob = detect_ob(prev, cur)
    assert ob is not None
    # br_low = prev.open = 120, br_high = prev.high = 120 → degenerate
    post = [Candle(open=124, high=130, low=123, close=128)]
    assert detect_breaker(ob, post) is None


def test_short_post_bars_dont_crash():
    """post_bars короче окна активации — функция не падает."""
    prev, cur = _ob_pair_bullish()
    ob = detect_ob(prev, cur)
    post = [Candle(open=111, high=113, low=110, close=112)]   # 1 свеча, нет activation
    assert detect_breaker(ob, post) is None


def test_scan_breakers_absolute_indices():
    """scan_breakers возвращает абсолютные индексы в шкале candles."""
    candles = [
        Candle(open=98, high=99, low=97, close=98),
        Candle(open=110, high=120, low=99, close=100),     # 1: prev bear (для OB)
        Candle(open=100, high=112, low=99, close=111),     # 2: cur bull → OB
        Candle(open=111, high=113, low=110, close=112),    # 3 bar 3 (bull, не cur для OB)
        Candle(open=112, high=115, low=110, close=114),    # 4 bar 4 (bull, не cur для OB)
        Candle(open=114, high=122, low=113, close=121),    # 5 bar 5 ★ ARMED at abs=5
        Candle(open=121, high=125, low=117, close=118),    # 6
        Candle(open=118, high=119, low=110, close=112),    # 7 CONSUMED at abs=7
    ]
    results = scan_breakers(candles)
    assert len(results) == 1
    br = results[0]
    assert br.activated_at_idx == 5
    assert br.consumed_at_idx == 7
    assert br.direction == "bullish"


# ───────────────────────────────────────────────────────────────────────
# Legacy aliases (for downstream compat)
# ───────────────────────────────────────────────────────────────────────

def test_legacy_zone_and_return_idx_aliases():
    """Старый код использует br.zone и br.return_idx — должны работать через property."""
    prev, cur = _ob_pair_bullish()
    ob = detect_ob(prev, cur)
    post = [
        Candle(open=111, high=125, low=121, close=122),   # ★ ARMED at post[0], low > zone_hi → no interact
    ]
    br = detect_breaker(ob, post)
    assert br is not None
    assert br.zone == br.initial_zone == (110, 120)
    assert br.return_idx == br.activated_at_idx == 0
    assert br.bos_idx == 0
    assert br.is_active is True
