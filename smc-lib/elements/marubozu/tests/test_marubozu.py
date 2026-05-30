import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from candle import Candle
from elements.marubozu.code import detect_marubozu


def test_long_marubozu_with_upper_wick():
    """LONG: open == low, есть верхний фитиль. Pine catches, old 95%-canon would NOT."""
    c = Candle(open=100, high=110, low=100, close=109)
    r = detect_marubozu(c)
    assert r is not None
    assert r.direction == "long"
    assert r.zone == (100, 109)


def test_long_marubozu_full_body_no_wicks():
    """LONG: open == low AND high == close → нет ни одного фитиля. Эталонная marubozu."""
    c = Candle(open=100, high=109, low=100, close=109)
    r = detect_marubozu(c)
    assert r is not None
    assert r.direction == "long"
    assert r.zone == (100, 109)


def test_short_marubozu_with_lower_wick():
    """SHORT: open == high, есть нижний фитиль."""
    c = Candle(open=110, high=110, low=100, close=101)
    r = detect_marubozu(c)
    assert r is not None
    assert r.direction == "short"
    assert r.zone == (101, 110)


def test_short_marubozu_full_body_no_wicks():
    """SHORT: open == high AND close == low → нет фитилей."""
    c = Candle(open=110, high=110, low=101, close=101)
    r = detect_marubozu(c)
    assert r is not None
    assert r.direction == "short"
    assert r.zone == (101, 110)


def test_fails_long_with_small_lower_wick():
    """LONG: open > low даже на 0.01 → нет marubozu (есть нижний фитиль)."""
    c = Candle(open=100.01, high=110, low=100, close=109)
    assert detect_marubozu(c) is None


def test_fails_short_with_small_upper_wick():
    """SHORT: open < high даже на 0.01 → нет marubozu (есть верхний фитиль)."""
    c = Candle(open=109.99, high=110, low=100, close=101)
    assert detect_marubozu(c) is None


def test_fails_doji_open_eq_close_at_low():
    """Doji при open == low: close == open → не bull (close > open ложно)."""
    c = Candle(open=100, high=105, low=100, close=100)
    assert detect_marubozu(c) is None


def test_fails_doji_open_eq_close_at_high():
    """Doji при open == high: close == open → не bear."""
    c = Candle(open=110, high=110, low=105, close=110)
    assert detect_marubozu(c) is None


def test_fails_bull_with_open_at_high():
    """Bull но open == high (close > open невозможно при open == high и close <= high) → None.
    Конструкция: open == high == close, но это doji. Bull marubozu только при open == low."""
    c = Candle(open=100, high=100, low=95, close=100)   # close == open: doji
    assert detect_marubozu(c) is None


def test_fails_bear_with_open_at_low():
    """Bear но open == low → невозможно (close < open ⇒ close < low, нарушение OHLC)."""
    # Конструируем bear с open == low: open=100, low=100, close<100 — но тогда low должен быть min, нарушение
    # Просто проверим что bear с open != high не проходит:
    c = Candle(open=109, high=110, low=100, close=101)
    assert detect_marubozu(c) is None


def test_fails_zero_range_doji():
    """Нулевой диапазон (high == low == open == close) — doji, None."""
    c = Candle(open=100, high=100, low=100, close=100)
    assert detect_marubozu(c) is None


def test_long_with_very_long_upper_wick():
    """LONG: open == low, маленькое тело, огромный верхний фитиль. По Pine — marubozu, по old-canon — нет."""
    c = Candle(open=100, high=200, low=100, close=101)
    r = detect_marubozu(c)
    assert r is not None
    assert r.direction == "long"
    assert r.zone == (100, 101)
    # body=1, range=100, body/range=0.01 — далеко от 95% старого канона


def test_zone_uses_body_not_range():
    """Зона строго равна телу, не диапазону. Верхний фитиль НЕ включён."""
    c = Candle(open=100, high=120, low=100, close=110)
    r = detect_marubozu(c)
    assert r is not None
    assert r.zone == (100, 110)   # тело, без верхнего фитиля [110, 120]
