import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from candle import Candle
from elements.fvg.code import detect_fvg


FIXTURES = json.loads((pathlib.Path(__file__).parent / "fixtures.json").read_text())


def _candles(name):
    return [Candle(open=c["open"], high=c["high"], low=c["low"], close=c["close"]) for c in FIXTURES[name]["candles"]]


def test_reference_short_fvg_2026_05_21_4h():
    c1, c2, c3 = _candles("reference_short_fvg_2026_05_21_4h")
    expected = FIXTURES["reference_short_fvg_2026_05_21_4h"]["expected"]
    result = detect_fvg(c1, c2, c3)
    assert result is not None
    assert result.direction == expected["direction"]
    assert result.zone == tuple(expected["zone"])


def test_long_fvg():
    c1 = Candle(open=95, high=100, low=90, close=98)
    c2 = Candle(open=98, high=120, low=97, close=118)  # bull displacement
    c3 = Candle(open=118, high=125, low=105, close=120)
    # c1.high (100) < c3.low (105) → long FVG = [100, 105]
    result = detect_fvg(c1, c2, c3)
    assert result is not None
    assert result.direction == "long"
    assert result.zone == (100, 105)


def test_short_fvg():
    c1 = Candle(open=100, high=110, low=105, close=108)
    c2 = Candle(open=108, high=109, low=85, close=88)
    c3 = Candle(open=88, high=100, low=80, close=85)
    # c1.low (105) > c3.high (100) → short FVG = [100, 105]
    result = detect_fvg(c1, c2, c3)
    assert result is not None
    assert result.direction == "short"
    assert result.zone == (100, 105)


def test_no_fvg_overlap():
    """Если c1 и c3 перекрываются по диапазону — нет FVG."""
    c1 = Candle(open=100, high=110, low=90, close=105)
    c2 = Candle(open=105, high=115, low=95, close=110)
    c3 = Candle(open=110, high=120, low=100, close=115)
    # c1.high (110) >= c3.low (100), c1.low (90) <= c3.high (120) → нет гэпа
    assert detect_fvg(c1, c2, c3) is None


def test_no_fvg_touching():
    """Граничный случай: c1.high == c3.low — гэпа нет (нужно строгое <)."""
    c1 = Candle(open=95, high=100, low=90, close=98)
    c2 = Candle(open=98, high=110, low=97, close=108)
    c3 = Candle(open=108, high=115, low=100, close=110)  # c3.low == c1.high
    assert detect_fvg(c1, c2, c3) is None
