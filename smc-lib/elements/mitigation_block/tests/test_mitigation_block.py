"""Tests for new Mitigation Block canon (broken OB + Rule 1 закрепление).

Canon 2026-06-14: MB = полностью пробитый OB + 4 свечи закрепления
(1 пробойная + 3 подтверждающих с open И close за пробитым уровнем).
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from candle import Candle
from elements.ob.code import detect_ob
from elements.mitigation_block.code import (
    detect_mitigation_block,
    scan_mitigation_blocks,
)


# ─────────────────────────────────────────────────────────────────────
# OB fixtures
# ─────────────────────────────────────────────────────────────────────

def _long_ob_pair():
    """LONG OB: prev bear, cur bull, cur.close > prev.open.

    prev O=100 H=102 L=95 C=96 (bear)
    cur  O=96  H=105 L=94 C=104 (bull, full break: cur.close > prev.high)

    OB.zone = drop area = [min(95, 94), 100] = [94, 100]
    """
    prev = Candle(open=100, high=102, low=95, close=96)
    cur = Candle(open=96, high=105, low=94, close=104)
    return prev, cur


def _short_ob_pair():
    """SHORT OB: prev bull, cur bear, cur.close < prev.open.

    prev O=100 H=105 L=98 C=104 (bull)
    cur  O=104 H=106 L=95 C=96  (bear, full break: cur.close < prev.low)

    OB.zone = rally area = [100, max(105, 106)] = [100, 106]
    """
    prev = Candle(open=100, high=105, low=98, close=104)
    cur = Candle(open=104, high=106, low=95, close=96)
    return prev, cur


# ─────────────────────────────────────────────────────────────────────
# Bearish MB tests (LONG OB → пробой вниз)
# ─────────────────────────────────────────────────────────────────────

def test_bearish_mb_armed_at_post_4():
    """LONG OB.zone = [94, 100]. Пробитый уровень = 94.

    post[0] (пробойная): close 89 < 94 ✓
    post[1] (подтв. 1): open 89, close 87 — оба < 94 ✓
    post[2] (подтв. 2): open 87, close 85 — оба < 94 ✓
    post[3] (подтв. 3): open 85, close 86 — оба < 94 ✓

    → MB armed.
    """
    prev, cur = _long_ob_pair()
    ob = detect_ob(prev, cur)
    assert ob is not None and ob.zone == (94, 100)

    post = [
        Candle(open=95, high=96, low=88, close=89),     # 0 пробойная
        Candle(open=89, high=91, low=85, close=87),     # 1 confirm
        Candle(open=87, high=89, low=83, close=85),     # 2 confirm
        Candle(open=85, high=87, low=82, close=86),     # 3 confirm
    ]
    mb = detect_mitigation_block(ob, post)
    assert mb is not None
    assert mb.direction == "bearish"
    assert mb.zone == (94, 100)
    assert mb.broken_level == 94
    assert mb.breakout_idx == 0
    assert mb.confirm_idxs == (1, 2, 3)
    assert mb.armed_at_idx == 3


def test_bearish_mb_breakout_at_post_2():
    """Пробой не сразу — на post[2] (после 2 не-пробойных)."""
    prev, cur = _long_ob_pair()
    ob = detect_ob(prev, cur)

    post = [
        Candle(open=96, high=98, low=95, close=97),     # 0 in zone, not below 94
        Candle(open=97, high=99, low=95, close=96),     # 1 in zone
        Candle(open=96, high=97, low=88, close=89),     # 2 пробойная (close 89 < 94)
        Candle(open=89, high=91, low=85, close=87),     # 3 confirm
        Candle(open=87, high=89, low=83, close=85),     # 4 confirm
        Candle(open=85, high=87, low=82, close=86),     # 5 confirm
    ]
    mb = detect_mitigation_block(ob, post)
    assert mb is not None
    assert mb.breakout_idx == 2
    assert mb.confirm_idxs == (3, 4, 5)


def test_bearish_mb_confirm_fail_open_inside_level():
    """Если хотя бы у одной из 3 confirming свечей open ≥ broken_level → fail."""
    prev, cur = _long_ob_pair()
    ob = detect_ob(prev, cur)

    post = [
        Candle(open=95, high=96, low=88, close=89),     # 0 пробойная (89 < 94)
        Candle(open=89, high=91, low=85, close=87),     # 1 confirm (87 < 94, 89 < 94 ✓)
        Candle(open=94.5, high=95, low=90, close=92),   # 2 ❌ open 94.5 ≥ 94 → fail
        Candle(open=85, high=87, low=82, close=86),     # 3 N/A
    ]
    assert detect_mitigation_block(ob, post) is None


def test_bearish_mb_confirm_fail_close_inside_level():
    """Если close хотя бы одной confirming ≥ broken_level → fail."""
    prev, cur = _long_ob_pair()
    ob = detect_ob(prev, cur)

    post = [
        Candle(open=95, high=96, low=88, close=89),     # 0 пробойная
        Candle(open=89, high=95, low=88, close=94.5),   # 1 ❌ close 94.5 ≥ 94 → fail
        Candle(open=85, high=87, low=82, close=86),     # 2 N/A
        Candle(open=85, high=87, low=82, close=86),     # 3 N/A
    ]
    assert detect_mitigation_block(ob, post) is None


def test_bearish_mb_no_breakout_in_window():
    """Если в окне max_bars_to_breakout пробой не произошёл → None."""
    prev, cur = _long_ob_pair()
    ob = detect_ob(prev, cur)

    post = [Candle(open=96, high=98, low=94.5, close=96) for _ in range(35)]
    assert detect_mitigation_block(ob, post, max_bars_to_breakout=30) is None


def test_bearish_mb_insufficient_bars_for_confirmation():
    """Пробойная есть, но < 3 баров после неё → None (not enough confirmation)."""
    prev, cur = _long_ob_pair()
    ob = detect_ob(prev, cur)

    post = [
        Candle(open=95, high=96, low=88, close=89),     # 0 пробойная
        Candle(open=89, high=91, low=85, close=87),     # 1 confirm
        Candle(open=87, high=89, low=83, close=85),     # 2 confirm
        # нет 3-й confirming → None
    ]
    assert detect_mitigation_block(ob, post) is None


# ─────────────────────────────────────────────────────────────────────
# Bullish MB tests (SHORT OB → пробой вверх) — зеркально
# ─────────────────────────────────────────────────────────────────────

def test_bullish_mb_armed():
    """SHORT OB.zone = [100, 106]. Пробитый уровень = 106.

    Все 4 свечи post должны иметь open И close > 106 (для confirm).
    """
    prev, cur = _short_ob_pair()
    ob = detect_ob(prev, cur)
    assert ob is not None and ob.zone == (100, 106)

    post = [
        Candle(open=97, high=112, low=96, close=111),   # 0 пробойная (111 > 106)
        Candle(open=111, high=115, low=109, close=113), # 1 confirm (111, 113 > 106 ✓)
        Candle(open=113, high=117, low=111, close=115), # 2 confirm
        Candle(open=115, high=118, low=113, close=114), # 3 confirm
    ]
    mb = detect_mitigation_block(ob, post)
    assert mb is not None
    assert mb.direction == "bullish"
    assert mb.zone == (100, 106)
    assert mb.broken_level == 106
    assert mb.breakout_idx == 0


def test_bullish_mb_confirm_fail():
    """Если у любой confirming open или close ≤ 106 → fail."""
    prev, cur = _short_ob_pair()
    ob = detect_ob(prev, cur)

    post = [
        Candle(open=97, high=112, low=96, close=111),   # 0 пробойная
        Candle(open=111, high=115, low=109, close=113), # 1 confirm ✓
        Candle(open=106, high=110, low=104, close=108), # 2 ❌ open 106, не > 106
        Candle(open=115, high=118, low=113, close=114), # 3 N/A
    ]
    assert detect_mitigation_block(ob, post) is None


# ─────────────────────────────────────────────────────────────────────
# scan_mitigation_blocks
# ─────────────────────────────────────────────────────────────────────

def test_scan_finds_mb_in_series():
    """scan находит MB в полной серии свечей."""
    bars = [
        # pre — заполнение чтобы OB-пара не была первой
        Candle(open=99, high=101, low=98, close=100),
        # OB-пара (idx 1, 2): LONG OB
        Candle(open=100, high=102, low=95, close=96),   # prev (bear)
        Candle(open=96, high=105, low=94, close=104),   # cur (bull)
        # post (OB-зона [94, 100]):
        Candle(open=95, high=96, low=88, close=89),     # пробойная
        Candle(open=89, high=91, low=85, close=87),     # confirm 1
        Candle(open=87, high=89, low=83, close=85),     # confirm 2
        Candle(open=85, high=87, low=82, close=86),     # confirm 3
    ]
    results = scan_mitigation_blocks(bars)
    assert len(results) >= 1
    i_cur, mb = results[0]
    assert i_cur == 2  # cur OB candle at idx 2
    assert mb.direction == "bearish"
    assert mb.zone == (94, 100)
