import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from candle import Candle
from elements.ob.code import detect_ob


def test_long_ob_reference():
    """LONG OB: prev bear, cur bull, cur.close > prev.open. Zone = [pattern.low, cur.close]."""
    prev = Candle(open=100, high=102, low=95, close=96)
    cur = Candle(open=96, high=105, low=94, close=104)
    r = detect_ob(prev, cur)
    assert r is not None
    assert r.direction == "long"
    assert r.zone == (94, 104)
    assert r.breaker_block == (100, 104)


def test_short_ob_reference():
    """SHORT OB: prev bull, cur bear, cur.close < prev.open. Zone = [cur.close, pattern.high]."""
    prev = Candle(open=100, high=105, low=98, close=104)
    cur = Candle(open=104, high=106, low=95, close=96)
    r = detect_ob(prev, cur)
    assert r is not None
    assert r.direction == "short"
    assert r.zone == (96, 106)
    assert r.breaker_block == (96, 100)


def test_long_ob_zone_uses_prev_low_when_lower():
    """Если prev.low ниже cur.low → используется prev.low."""
    prev = Candle(open=100, high=102, low=90, close=96)  # bear
    cur = Candle(open=96, high=105, low=94, close=104)   # bull
    r = detect_ob(prev, cur)
    assert r is not None
    assert r.zone == (90, 104)
    assert r.breaker_block == (100, 104)


def test_short_ob_zone_uses_prev_high_when_higher():
    """Если prev.high выше cur.high → используется prev.high."""
    prev = Candle(open=100, high=110, low=98, close=104)  # bull
    cur = Candle(open=104, high=106, low=95, close=96)    # bear
    r = detect_ob(prev, cur)
    assert r is not None
    assert r.zone == (96, 110)
    assert r.breaker_block == (96, 100)


def test_ob_geometry_matches_block_orders_1_1():
    """OB ≡ (N₁=1, N₂=1) случай block_orders. Зона = [block.low, block.close] LONG."""
    prev = Candle(open=100, high=102, low=95, close=96)  # bear (initial)
    cur = Candle(open=96, high=105, low=94, close=104)   # bull (counter, cross 104 > 100)
    r = detect_ob(prev, cur)
    assert r is not None
    # block.open = prev.open = 100, block.close = cur.close = 104
    # block.low = min(prev.low, cur.low) = 94, block.high = max(prev.high, cur.high) = 105
    # zone = [block.low, block.close] = [94, 104]
    # breaker_block = [block.open, block.close] = [100, 104]
    assert r.zone == (94, 104)
    assert r.breaker_block == (100, 104)


def test_fails_when_cur_does_not_close_beyond_prev_open():
    """LONG: cur.close == prev.open — недостаточно (нужно строго больше)."""
    prev = Candle(open=100, high=102, low=95, close=96)
    cur = Candle(open=96, high=101, low=94, close=100)
    assert detect_ob(prev, cur) is None


def test_fails_when_prev_is_doji():
    """prev doji — не OB (нет направления)."""
    prev = Candle(open=100, high=102, low=95, close=100)  # doji
    cur = Candle(open=100, high=105, low=99, close=104)
    assert detect_ob(prev, cur) is None


def test_fails_when_cur_is_doji():
    """cur doji — не OB."""
    prev = Candle(open=100, high=102, low=95, close=96)
    cur = Candle(open=96, high=101, low=95, close=96)  # doji
    assert detect_ob(prev, cur) is None


def test_fails_same_direction():
    """prev bear, cur bear — не OB."""
    prev = Candle(open=100, high=102, low=95, close=96)
    cur = Candle(open=96, high=97, low=92, close=93)
    assert detect_ob(prev, cur) is None


def test_long_ob_boundary_cur_close_just_above_prev_open():
    """cur.close = prev.open + epsilon — валидный LONG."""
    prev = Candle(open=100, high=102, low=95, close=96)
    cur = Candle(open=96, high=101, low=94, close=100.01)
    r = detect_ob(prev, cur)
    assert r is not None
    assert r.direction == "long"


def test_short_ob_boundary():
    """cur.close = prev.open - epsilon — валидный SHORT."""
    prev = Candle(open=100, high=105, low=98, close=104)
    cur = Candle(open=104, high=106, low=99, close=99.99)
    r = detect_ob(prev, cur)
    assert r is not None
    assert r.direction == "short"
