import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from candle import Candle
from elements.i_rdrb.code import detect_i_rdrb


FIXTURES = json.loads((pathlib.Path(__file__).parent / "fixtures.json").read_text())


def _candles(name):
    raw = FIXTURES[name]["candles"]
    return [Candle(open=c["open"], high=c["high"], low=c["low"], close=c["close"]) for c in raw]


def _expected_liq(value):
    return None if value is None else tuple(value)


def test_reference_long_i_rdrb_2026_05_18_4h():
    c1, c2, c3, c4 = _candles("reference_long_i_rdrb_2026_05_18_4h")
    expected = FIXTURES["reference_long_i_rdrb_2026_05_18_4h"]["expected"]
    result = detect_i_rdrb(c1, c2, c3, c4)
    assert result is not None
    assert result.direction == expected["direction"]
    # inherited RDRB
    assert result.rdrb.direction == expected["rdrb_direction"]
    assert result.rdrb.variant == expected["rdrb_variant"]
    assert result.rdrb.poi == tuple(expected["rdrb_poi"])
    assert result.rdrb.block == tuple(expected["rdrb_block"])
    assert result.rdrb.liq == tuple(expected["rdrb_liq"])
    # i-RDRB-specific (canon 2026-06-14)
    assert result.variant == expected["i_rdrb_variant"]
    assert result.poi == tuple(expected["i_rdrb_poi"])
    assert result.block == tuple(expected["i_rdrb_block"])
    assert result.liq == _expected_liq(expected["i_rdrb_liq"])


def test_long_i_rdrb_on_short_rdrb_v1():
    """Reversal: SHORT RDRB + C4 bull, close > block.top → LONG i-RDRB.
    Здесь C3.body_top=95 < C1.low=100 → i-RDRB liq = [95, 100], V1."""
    c1 = Candle(open=110, high=115, low=100, close=105)   # bull, body=[105,110], low=100
    c2 = Candle(open=105, high=108, low=88,  close=90)    # bear displacement, close 90 < c1.low=100
    c3 = Candle(open=90,  high=104, low=85,  close=95)    # bull, body=[90,95], high=104
    # rdrb SHORT: block = [max(100, 95), min(105, 104)] = [100, 104]
    c4 = Candle(open=95,  high=110, low=94,  close=108)   # bull, close 108 > block.top=104
    result = detect_i_rdrb(c1, c2, c3, c4)
    assert result is not None
    assert result.direction == "long"
    assert result.rdrb.direction == "short"
    # i-RDRB canon: liq = [c3.body_top=95, c1.low=100] = [95, 100]
    assert result.liq == (95.0, 100.0)
    # block = rdrb.block = [100, 104]
    assert result.block == (100.0, 104.0)
    # POI = block ∪ liq = [95, 104]
    assert result.poi == (95.0, 104.0)
    assert result.variant == "V1"


def test_short_i_rdrb_on_long_rdrb_v1():
    """LONG RDRB + C4 bear → SHORT i-RDRB.
    C1.high=100 < C3.body_bottom=105 → i-RDRB liq = [100, 105], V1."""
    c1 = Candle(open=90,  high=100, low=85,  close=95)    # bull, body=[90,95], high=100
    c2 = Candle(open=95,  high=112, low=92,  close=110)   # bull displacement, close 110 > c1.high=100
    c3 = Candle(open=110, high=115, low=96,  close=105)   # bull, body=[105,110], low=96
    # rdrb LONG: block = [max(95, 96), min(100, 105)] = [96, 100]
    c4 = Candle(open=105, high=106, low=92,  close=94)    # bear, close 94 < block.bottom=96
    result = detect_i_rdrb(c1, c2, c3, c4)
    assert result is not None
    assert result.direction == "short"
    assert result.rdrb.direction == "long"
    # i-RDRB canon: liq = [c1.high=100, c3.body_bottom=105] = [100, 105]
    assert result.liq == (100.0, 105.0)
    assert result.block == (96.0, 100.0)
    # POI = block ∪ liq = [96, 105]
    assert result.poi == (96.0, 105.0)
    assert result.variant == "V1"


def test_continuation_not_i_rdrb_short():
    """SHORT RDRB + C4 bear (continuation вниз) — НЕ i-RDRB."""
    c1 = Candle(open=110, high=115, low=100, close=105)
    c2 = Candle(open=105, high=108, low=88, close=90)
    c3 = Candle(open=90, high=104, low=85, close=95)
    c4 = Candle(open=95, high=98, low=70, close=72)
    assert detect_i_rdrb(c1, c2, c3, c4) is None


def test_continuation_not_i_rdrb_long():
    """LONG RDRB + C4 bull (continuation вверх) — НЕ i-RDRB."""
    c1 = Candle(open=90, high=100, low=85, close=95)
    c2 = Candle(open=95, high=112, low=92, close=110)
    c3 = Candle(open=110, high=115, low=96, close=105)
    c4 = Candle(open=105, high=125, low=104, close=122)
    assert detect_i_rdrb(c1, c2, c3, c4) is None


def test_c4_close_inside_block_not_i_rdrb():
    c1, c2, c3, _ = _candles("reference_long_i_rdrb_2026_05_18_4h")
    c4 = Candle(open=76928.00, high=76990.00, low=76900.00, close=76980.00)
    assert detect_i_rdrb(c1, c2, c3, c4) is None


def test_c4_doji_not_i_rdrb():
    c1, c2, c3, _ = _candles("reference_long_i_rdrb_2026_05_18_4h")
    c4 = Candle(open=76928.00, high=77000.00, low=76900.00, close=76928.00)
    assert detect_i_rdrb(c1, c2, c3, c4) is None


def test_c4_bull_at_block_top_boundary():
    """C4 close == block.top — НЕ i-RDRB (нужно строго >)."""
    c1, c2, c3, _ = _candles("reference_long_i_rdrb_2026_05_18_4h")
    c4 = Candle(open=76928.00, high=77000.00, low=76900.00, close=76995.00)
    assert detect_i_rdrb(c1, c2, c3, c4) is None


def test_no_rdrb_no_i_rdrb():
    c1 = Candle(open=100, high=110, low=90, close=100)
    c2 = Candle(open=100, high=110, low=90, close=100)
    c3 = Candle(open=100, high=110, low=90, close=100)
    c4 = Candle(open=100, high=200, low=90, close=180)
    assert detect_i_rdrb(c1, c2, c3, c4) is None
