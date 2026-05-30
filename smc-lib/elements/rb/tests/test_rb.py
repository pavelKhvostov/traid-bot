import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from candle import Candle
from elements.rb.code import detect_rb


def test_reference_top_rb_2026_04_14_12h():
    """Эталон: BTC 12h 2026-04-14 15:00 MSK = TOP RB.
    upper/lower=4.94, upper/body=6.78."""
    c = Candle(open=74376.52, high=76038.00, low=73795.47, close=74131.55)
    r = detect_rb(c)
    assert r is not None
    assert r.direction == "top"
    assert r.zone == (74376.52, 76038.00)
    assert abs(r.body - 244.97) < 0.01
    assert abs(r.upper_wick - 1661.48) < 0.01
    assert abs(r.lower_wick - 336.08) < 0.01


def test_bottom_rb_synthetic():
    """BOTTOM RB: bull свеча с длинным нижним фитилём."""
    # body=2 (98→100), upper=1 (100→101), lower=8 (90→98)
    # lower/upper = 8 ≥ 2 ✓, lower/body = 4 ≥ 3 ✓
    c = Candle(open=98, high=101, low=90, close=100)
    r = detect_rb(c)
    assert r is not None
    assert r.direction == "bottom"
    assert r.zone == (90, 98)
    assert r.body == 2
    assert r.upper_wick == 1
    assert r.lower_wick == 8


def test_top_rb_bear_body():
    """TOP RB на bear свече."""
    # body=2 (102→100), upper=10 (102→112), lower=1 (100→99)
    # upper/lower = 10 ≥ 2 ✓, upper/body = 5 ≥ 3 ✓
    c = Candle(open=102, high=112, low=99, close=100)
    r = detect_rb(c)
    assert r is not None
    assert r.direction == "top"
    assert r.zone == (102, 112)


def test_top_rb_bull_body():
    """TOP RB на bull свече (тоже допустимо)."""
    # body=2 (98→100), upper=10 (100→110), lower=1 (98→97)
    # upper/lower = 10 ≥ 2, upper/body = 5 ≥ 3
    c = Candle(open=98, high=110, low=97, close=100)
    r = detect_rb(c)
    assert r is not None
    assert r.direction == "top"


def test_fails_doji():
    """body=0 — не RB."""
    c = Candle(open=100, high=110, low=99, close=100)
    assert detect_rb(c) is None


def test_fails_no_other_wick():
    """Один фитиль = 0 (марузу-с-фитилём) — не RB."""
    # body=2, upper=10, lower=0
    c = Candle(open=100, high=112, low=100, close=102)
    assert detect_rb(c) is None


def test_fails_k1_not_met():
    """Доминирующий фитиль < 2× второй — не RB."""
    # body=2, upper=5, lower=3, upper/lower=1.67 < 2
    c = Candle(open=102, high=107, low=99, close=100)
    assert detect_rb(c) is None


def test_fails_k2_not_met():
    """Доминирующий фитиль < 3× body — не RB."""
    # body=4 (104→100), upper=5 (104→109), lower=0.5 (100→99.5)
    # upper/lower=10 ≥ 2 ✓, upper/body=5/4=1.25 < 3 ✗
    c = Candle(open=104, high=109, low=99.5, close=100)
    assert detect_rb(c) is None


def test_boundary_k1_exactly_2():
    """K1 = 2.0 ровно — RB."""
    # body=2, upper=6, lower=3, upper/lower=2 ✓, upper/body=3 ✓
    c = Candle(open=102, high=108, low=99, close=100)
    r = detect_rb(c)
    assert r is not None
    assert r.direction == "top"


def test_boundary_k2_exactly_3():
    """K2 = 3.0 ровно — RB."""
    # body=2, upper=6, lower=2, upper/lower=3 ≥ 2 ✓, upper/body=3 ✓
    c = Candle(open=102, high=108, low=99, close=100)
    r = detect_rb(c)
    assert r is not None


def test_neither_top_nor_bottom():
    """Оба фитиля сравнимы — не RB."""
    # body=2, upper=4, lower=5
    c = Candle(open=102, high=106, low=95, close=100)
    assert detect_rb(c) is None
