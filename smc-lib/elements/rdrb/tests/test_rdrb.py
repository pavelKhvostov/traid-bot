import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from candle import Candle
from elements.rdrb.code import detect_rdrb


FIXTURES = json.loads((pathlib.Path(__file__).parent / "fixtures.json").read_text())


def _candles(name):
    raw = FIXTURES[name]["candles"]
    return [Candle(open=c["open"], high=c["high"], low=c["low"], close=c["close"]) for c in raw]


def _is_subset(inner, outer):
    return outer[0] <= inner[0] <= inner[1] <= outer[1]


def _assert_expected(name, result):
    expected = FIXTURES[name]["expected"]
    assert result is not None
    assert result.direction == expected["direction"]
    assert result.variant == expected["variant"]
    assert result.poi == tuple(expected["poi"])
    assert result.block == tuple(expected["block"])
    if expected["liq"] is None:
        assert result.liq is None
    else:
        assert result.liq == tuple(expected["liq"])
    assert _is_subset(result.block, result.poi)


def test_reference_short_v1_2026_05_22():
    _assert_expected("reference_short_v1_2026_05_22", detect_rdrb(*_candles("reference_short_v1_2026_05_22")))


def test_reference_short_v1_2026_05_23_15m():
    """Кейс с C1.low > C3.body_top: нижняя граница POI = C1.low, а не C3.body_top."""
    _assert_expected("reference_short_v1_2026_05_23_15m", detect_rdrb(*_candles("reference_short_v1_2026_05_23_15m")))


def test_long_mirror_v1():
    """Зеркальное отражение SHORT даёт LONG с такой же V1-структурой."""
    c1, c2, c3 = _candles("reference_short_v1_2026_05_22")
    AXIS = 200000.0
    def flip(c):
        return Candle(open=AXIS - c.open, high=AXIS - c.low, low=AXIS - c.high, close=AXIS - c.close)
    result = detect_rdrb(flip(c1), flip(c2), flip(c3))
    assert result is not None
    assert result.direction == "long"
    assert result.variant == "V1"
    assert result.liq is not None
    assert _is_subset(result.block, result.poi)


def test_v2_short_block_equals_poi():
    """SHORT V2: вик C3 (вверх) достаёт до тела C1 → block == poi, liq = ∅."""
    c1 = Candle(open=100, high=105, low=70, close=95)
    c2 = Candle(open=95, high=98, low=65, close=68)
    c3 = Candle(open=70, high=110, low=65, close=80)
    result = detect_rdrb(c1, c2, c3)
    assert result is not None
    assert result.direction == "short"
    assert result.variant == "V2"
    assert result.poi == (80, 95)
    assert result.block == (80, 95)
    assert result.liq is None


def test_v1_short_wick_not_reaching_body():
    """SHORT V1, C1.low > C3.body_top: POI.bottom = C1.low."""
    c1 = Candle(open=100, high=110, low=80, close=95)
    c2 = Candle(open=95, high=98, low=68, close=70)
    c3 = Candle(open=70, high=85, low=65, close=75)
    result = detect_rdrb(c1, c2, c3)
    assert result is not None
    assert result.direction == "short"
    assert result.variant == "V1"
    assert result.poi == (80, 95)
    assert result.block == (80, 85)
    assert result.liq == (85, 95)


def test_c2_doji_not_rdrb():
    c1 = Candle(open=105, high=115, low=95, close=102)
    c2 = Candle(open=100, high=110, low=90, close=100)
    c3 = Candle(open=85, high=98, low=80, close=92)
    assert detect_rdrb(c1, c2, c3) is None


def test_c2_close_not_below_c1_low():
    """SHORT-кандидат отвергается, если C2.close не строго ниже C1.low."""
    c1 = Candle(open=110, high=115, low=100, close=108)
    c2 = Candle(open=108, high=112, low=101, close=102)
    c3 = Candle(open=99, high=104, low=95, close=103)
    assert detect_rdrb(c1, c2, c3) is None


def test_wicks_dont_overlap():
    c1 = Candle(open=110, high=115, low=109, close=112)
    c2 = Candle(open=112, high=115, low=98, close=99)
    c3 = Candle(open=99, high=101, low=97, close=100)
    assert detect_rdrb(c1, c2, c3) is None


def test_bodies_overlap_no_zone():
    c1 = Candle(open=110, high=115, low=95, close=100)
    c2 = Candle(open=100, high=105, low=90, close=92)
    c3 = Candle(open=92, high=108, low=91, close=105)
    assert detect_rdrb(c1, c2, c3) is None
