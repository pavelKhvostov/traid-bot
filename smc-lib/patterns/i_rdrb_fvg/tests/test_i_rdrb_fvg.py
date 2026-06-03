import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from candle import Candle
from patterns.i_rdrb_fvg.code import detect_i_rdrb_fvg


def test_reference_short_i_rdrb_fvg_2026_05_21_4h():
    """Эталон из definition.md: BTC 4h, 2026-05-20 23:00 → 2026-05-21 15:00 MSK."""
    c1 = Candle(open=77667.49, high=77766.60, low=77226.61, close=77552.23)
    c2 = Candle(open=77552.24, high=78173.15, low=77525.00, close=78078.72)
    c3 = Candle(open=78078.72, high=78180.01, low=77521.00, close=77889.01)
    c4 = Candle(open=77889.01, high=78200.00, low=77147.15, close=77189.10)
    c5 = Candle(open=77189.10, high=77402.12, low=76719.47, close=77259.46)

    r = detect_i_rdrb_fvg(c1, c2, c3, c4, c5)
    assert r is not None
    assert r.direction == "short"
    assert r.irdrb.direction == "short"
    assert r.irdrb.rdrb.direction == "long"   # подлежащий RDRB противоположный
    assert r.fvg.direction == "short"
    assert r.fvg.zone == (77402.12, 77521.00)


def test_long_i_rdrb_fvg_synthetic():
    """LONG i-RDRB (на SHORT RDRB) + LONG FVG."""
    c1 = Candle(open=110, high=115, low=100, close=105)        # bear
    c2 = Candle(open=105, high=108, low=88, close=90)          # bear (SHORT displacement)
    c3 = Candle(open=90, high=104, low=85, close=95)           # bull
    # RDRB SHORT, block = [max(100, 95), min(105, 104)] = [100, 104]
    c4 = Candle(open=95, high=115, low=94, close=112)          # bull, close 112 > block.top 104 → LONG i-RDRB
    # для FVG LONG нужен c3.high < c5.low → c3.high=104, c5.low должен быть > 104
    c5 = Candle(open=112, high=120, low=105, close=118)        # low=105 > c3.high=104 ✓

    r = detect_i_rdrb_fvg(c1, c2, c3, c4, c5)
    assert r is not None
    assert r.direction == "long"
    assert r.fvg.zone == (104, 105)


def test_fails_when_fvg_direction_differs():
    """i-RDRB SHORT но FVG LONG → None."""
    # Сконструируем SHORT i-RDRB
    c1 = Candle(open=90, high=100, low=85, close=95)           # bull
    c2 = Candle(open=95, high=112, low=92, close=110)          # bull (LONG displacement)
    c3 = Candle(open=110, high=115, low=96, close=105)         # bear
    # RDRB LONG, block = [max(95, 96), min(100, 105)] = [96, 100]
    c4 = Candle(open=105, high=106, low=92, close=94)          # bear, close 94 < block.bottom 96 → SHORT i-RDRB
    # Намеренно делаем LONG FVG (c3.high < c5.low): c3.high=115 уже выше любого разумного c5.low → нарушим
    c5 = Candle(open=94, high=120, low=116, close=118)         # low=116 > c3.high=115 → LONG FVG

    r = detect_i_rdrb_fvg(c1, c2, c3, c4, c5)
    assert r is None


def test_fails_when_no_fvg():
    """Нет gap между c3 и c5 → None."""
    c1 = Candle(open=110, high=115, low=100, close=105)
    c2 = Candle(open=105, high=108, low=88, close=90)
    c3 = Candle(open=90, high=104, low=85, close=95)
    c4 = Candle(open=95, high=115, low=94, close=112)          # LONG i-RDRB ok
    c5 = Candle(open=112, high=120, low=100, close=118)        # low=100 < c3.high=104 → no FVG

    r = detect_i_rdrb_fvg(c1, c2, c3, c4, c5)
    assert r is None


def test_fails_when_no_i_rdrb():
    """C4 не разворачивает движение → no i-RDRB → None."""
    c1 = Candle(open=110, high=115, low=100, close=105)
    c2 = Candle(open=105, high=108, low=88, close=90)
    c3 = Candle(open=90, high=104, low=85, close=95)
    c4 = Candle(open=95, high=98, low=88, close=92)            # bear, не разворот → continuation
    c5 = Candle(open=92, high=95, low=85, close=88)

    r = detect_i_rdrb_fvg(c1, c2, c3, c4, c5)
    assert r is None
