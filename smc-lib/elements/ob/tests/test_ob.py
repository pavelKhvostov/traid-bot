import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from candle import Candle
from elements.ob.code import detect_ob


def test_long_ob_reference():
    """LONG OB ZoI = drop area = [min(prev.low, cur.low), prev.open]. Всегда, регардлесс от full break."""
    prev = Candle(open=100, high=102, low=95, close=96)
    cur = Candle(open=96, high=105, low=94, close=104)
    r = detect_ob(prev, cur)
    assert r is not None
    assert r.direction == "long"
    assert r.zone == (94, 100)


def test_short_ob_reference():
    """SHORT OB ZoI = rally area = [prev.open, max(prev.high, cur.high)]."""
    prev = Candle(open=100, high=105, low=98, close=104)
    cur = Candle(open=104, high=106, low=95, close=96)
    r = detect_ob(prev, cur)
    assert r is not None
    assert r.direction == "short"
    assert r.zone == (100, 106)


def test_long_ob_zone_uses_prev_low_when_lower():
    prev = Candle(open=100, high=102, low=90, close=96)
    cur = Candle(open=96, high=105, low=94, close=104)
    r = detect_ob(prev, cur)
    assert r is not None
    assert r.zone == (90, 100)


def test_short_ob_zone_uses_prev_high_when_higher():
    prev = Candle(open=100, high=110, low=98, close=104)
    cur = Candle(open=104, high=106, low=95, close=96)
    r = detect_ob(prev, cur)
    assert r is not None
    assert r.zone == (100, 110)


def test_long_ob_zone_does_not_change_without_full_break():
    """cur.close ≤ prev.high → OB.zone identical (drop area), но is_full_break() = False."""
    from elements.ob.code import is_full_break
    prev = Candle(open=100, high=102, low=95, close=96)
    cur = Candle(open=96, high=101.5, low=94, close=101)
    r = detect_ob(prev, cur)
    assert r is not None
    assert r.zone == (94, 100)
    assert is_full_break(r) is False


def test_long_ob_full_break_flag():
    from elements.ob.code import is_full_break
    prev = Candle(open=100, high=102, low=95, close=96)
    cur = Candle(open=96, high=105, low=94, close=104)
    r = detect_ob(prev, cur)
    assert is_full_break(r) is True


def test_short_ob_full_break_flag():
    from elements.ob.code import is_full_break
    prev = Candle(open=100, high=105, low=98, close=104)
    cur = Candle(open=104, high=106, low=95, close=96)
    r = detect_ob(prev, cur)
    assert is_full_break(r) is True


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
