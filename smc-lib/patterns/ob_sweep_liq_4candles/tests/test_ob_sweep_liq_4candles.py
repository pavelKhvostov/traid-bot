import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from candle import Candle
from patterns.ob_sweep_liq_4candles.code import detect_ob_sweep_liq_4candles


def test_short_happy_path_btc_6h_2026_05_26():
    """Эталон BTC 6h SHORT. anchor=2026-05-25 15:00 (Williams FH at 77906), y=2026-05-26 15:00."""
    anchor = Candle(open=77358, high=77906, low=77286, close=77564)
    y      = Candle(open=77184, high=78080, low=75850, close=75935)
    r = detect_ob_sweep_liq_4candles(anchor, y, "short")
    assert r is not None
    assert r.direction == "short"
    assert r.liq_zone == (77906, 78080)


def test_long_happy_path_mirror():
    """LONG mirror: anchor = Williams FL (bear), y приходит с верху, делает sweep FL, close выше anchor.open."""
    anchor = Candle(open=110, high=112, low=90, close=100)    # bear, FL at 90, open=110 = top of body
    y      = Candle(open=105, high=115, low=85, close=112)    # opens above FL.low, low sweeps, close above anchor.open(110)
    r = detect_ob_sweep_liq_4candles(anchor, y, "long")
    assert r is not None
    assert r.direction == "long"
    assert r.liq_zone == (85, 90)


def test_fails_when_open_above_fh_short():
    """SHORT: если y.open >= anchor.high → не sweep (опен уже выше FH)."""
    anchor = Candle(open=100, high=110, low=98, close=105)
    y      = Candle(open=112, high=120, low=109, close=104)  # open 112 > anchor.high 110
    assert detect_ob_sweep_liq_4candles(anchor, y, "short") is None


def test_fails_when_no_sweep_short():
    """SHORT: y.high не превышает anchor.high → нет sweep."""
    anchor = Candle(open=100, high=110, low=98, close=105)
    y      = Candle(open=104, high=109, low=95, close=100)   # y.high=109 < anchor.high=110
    assert detect_ob_sweep_liq_4candles(anchor, y, "short") is None


def test_fails_when_close_above_fh_close_short():
    """SHORT: y.close >= anchor.close → close НЕ ниже close FH-бара."""
    anchor = Candle(open=100, high=110, low=98, close=105)
    y      = Candle(open=104, high=115, low=100, close=108)  # y.close=108 > anchor.close=105
    assert detect_ob_sweep_liq_4candles(anchor, y, "short") is None


def test_fails_when_open_below_fl_long():
    """LONG: если y.open <= anchor.low → не sweep."""
    anchor = Candle(open=100, high=110, low=90, close=98)
    y      = Candle(open=88, high=100, low=85, close=95)   # open 88 < anchor.low 90
    assert detect_ob_sweep_liq_4candles(anchor, y, "long") is None


def test_fails_when_no_sweep_long():
    """LONG: y.low не ниже anchor.low → нет sweep."""
    anchor = Candle(open=100, high=110, low=90, close=98)
    y      = Candle(open=95, high=105, low=92, close=100)  # y.low=92 > anchor.low=90
    assert detect_ob_sweep_liq_4candles(anchor, y, "long") is None


def test_fails_when_close_below_fl_close_long():
    """LONG: y.close <= anchor.close → close не выше close FL-бара."""
    anchor = Candle(open=100, high=110, low=90, close=98)
    y      = Candle(open=95, high=105, low=85, close=97)  # y.close=97 < anchor.close=98
    assert detect_ob_sweep_liq_4candles(anchor, y, "long") is None
