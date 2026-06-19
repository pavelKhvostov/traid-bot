import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from candle import Candle
from elements.block_orders.code import detect_block_orders


def test_reference_long_block_2026_05_05_1h():
    """Эталон: BTC 1h 2026-05-05 00:00 (preceding) + 01:00-04:00 MSK (block).
    open=80259.18, close=80352.00, N₁=2, N₂=2."""
    preceding = Candle(open=79936.70, high=80383.15, low=79936.70, close=80259.17)  # bull
    c1 = Candle(open=80259.18, high=80397.19, low=80042.84, close=80067.23)         # bear
    c2 = Candle(open=80067.22, high=80067.22, low=79744.91, close=79861.01)         # bear
    c3 = Candle(open=79861.01, high=80183.33, low=79808.72, close=80170.66)         # bull, no cross
    c4 = Candle(open=80170.66, high=80385.06, low=80080.76, close=80352.00)         # bull, cross

    r = detect_block_orders([preceding, c1, c2, c3, c4])
    assert r is not None
    assert r.direction == "long"
    assert r.n_initial == 2
    assert r.n_counter == 2
    assert r.open == 80259.18
    assert r.close == 80352.00
    assert r.high == 80397.19
    assert r.low == 79744.91
    # Canon 2026-06-15: LONG zone = [block.low, block.open] (drop area only)
    assert r.zone == (79744.91, 80259.18)
    assert r.preceding == preceding
    assert len(r.candles) == 4


def test_short_block_synthetic():
    """SHORT: preceding bear + 2 bull initial + 1 bear counter (cross)."""
    preceding = Candle(open=110, high=112, low=99, close=100)  # bear
    c1 = Candle(open=100, high=108, low=99, close=105)         # bull
    c2 = Candle(open=105, high=112, low=104, close=110)        # bull
    c3 = Candle(open=110, high=111, low=95, close=98)          # bear, 98 < 100 cross

    r = detect_block_orders([preceding, c1, c2, c3])
    assert r is not None
    assert r.direction == "short"
    assert r.n_initial == 2
    assert r.n_counter == 1
    assert r.open == 100
    assert r.close == 98
    # Canon 2026-06-15: SHORT zone = [block.open, block.high] (rally area only)
    assert r.zone == (100, 112)


def test_long_n1_1_n2_2_valid():
    """N₁=1, N₂=2 — допустимо (не (1,1))."""
    preceding = Candle(open=80, high=92, low=78, close=90)  # bull
    c1 = Candle(open=90, high=91, low=85, close=86)         # bear (initial #1)
    c2 = Candle(open=86, high=92, low=85, close=88)         # bull, 88 < 90 no cross
    c3 = Candle(open=88, high=95, low=87, close=94)         # bull, 94 > 90 cross

    r = detect_block_orders([preceding, c1, c2, c3])
    assert r is not None
    assert r.direction == "long"
    assert r.n_initial == 1
    assert r.n_counter == 2
    # Canon 2026-06-15: LONG zone = [block.low, block.open]
    # pattern.low = min(85, 85, 87) = 85, block.open = 90 → zone=[85, 90]
    assert r.zone == (85, 90)


def test_long_n1_3_n2_1_valid():
    """N₁=3, N₂=1 — допустимо."""
    preceding = Candle(open=80, high=110, low=78, close=100)  # bull
    c1 = Candle(open=100, high=101, low=95, close=96)         # bear
    c2 = Candle(open=96, high=97, low=92, close=93)           # bear
    c3 = Candle(open=93, high=94, low=89, close=90)           # bear
    c4 = Candle(open=90, high=110, low=89, close=108)         # bull, 108 > 100 cross

    r = detect_block_orders([preceding, c1, c2, c3, c4])
    assert r is not None
    assert r.n_initial == 3
    assert r.n_counter == 1
    # Canon 2026-06-15: LONG zone = [block.low, block.open]
    # pattern.low = min(95, 92, 89, 89) = 89, block.open = 100 → zone=[89, 100]
    assert r.zone == (89, 100)


def test_fails_n1_1_n2_1_canon_ob():
    """(1,1) — это canon-OB, не блок ордеров."""
    preceding = Candle(open=80, high=92, low=78, close=90)
    c1 = Candle(open=90, high=91, low=85, close=86)   # bear
    c2 = Candle(open=86, high=95, low=85, close=94)   # bull, cross 94 > 90

    assert detect_block_orders([preceding, c1, c2]) is None


def test_fails_preceding_wrong_direction():
    """preceding той же направленности что initial — fail."""
    preceding = Candle(open=92, high=95, low=85, close=86)  # bear (но initial bear)
    c1 = Candle(open=86, high=87, low=80, close=82)         # bear
    c2 = Candle(open=82, high=83, low=78, close=79)         # bear
    c3 = Candle(open=79, high=90, low=78, close=88)         # bull, would cross
    assert detect_block_orders([preceding, c1, c2, c3]) is None


def test_fails_counter_broken_before_cross():
    """Counter прерван bear-свечой до crossing → fail."""
    preceding = Candle(open=80, high=92, low=78, close=90)
    c1 = Candle(open=90, high=91, low=85, close=86)   # bear
    c2 = Candle(open=86, high=87, low=82, close=83)   # bear
    c3 = Candle(open=83, high=88, low=82, close=87)   # bull, 87 < 90 no cross
    c4 = Candle(open=87, high=88, low=83, close=84)   # bear → counter broken

    assert detect_block_orders([preceding, c1, c2, c3, c4]) is None


def test_fails_counter_never_crosses():
    """Counter run кончился (нет больше свечей) без crossing → fail."""
    preceding = Candle(open=80, high=92, low=78, close=90)
    c1 = Candle(open=90, high=91, low=85, close=86)   # bear
    c2 = Candle(open=86, high=87, low=82, close=83)   # bear
    c3 = Candle(open=83, high=88, low=82, close=87)   # bull, no cross — and slice ends

    assert detect_block_orders([preceding, c1, c2, c3]) is None


def test_fails_doji_in_counter():
    """Doji в counter → counter broken."""
    preceding = Candle(open=80, high=92, low=78, close=90)
    c1 = Candle(open=90, high=91, low=85, close=86)
    c2 = Candle(open=86, high=87, low=82, close=83)
    c3 = Candle(open=83, high=88, low=82, close=87)   # bull no cross
    c4 = Candle(open=87, high=88, low=86, close=87)   # doji

    assert detect_block_orders([preceding, c1, c2, c3, c4]) is None


def test_extra_candles_after_cross_ignored():
    """Свечи после first cross в слайсе игнорируются."""
    preceding = Candle(open=80, high=92, low=78, close=90)
    c1 = Candle(open=90, high=91, low=85, close=86)
    c2 = Candle(open=86, high=92, low=85, close=88)   # no cross
    c3 = Candle(open=88, high=95, low=87, close=94)   # cross at counter #2
    c4 = Candle(open=94, high=100, low=93, close=99)  # extra — should be ignored

    r = detect_block_orders([preceding, c1, c2, c3, c4])
    assert r is not None
    assert r.n_counter == 2
    assert r.close == 94
    assert len(r.candles) == 3   # 1 initial + 2 counter
    # Canon 2026-06-15: LONG zone = [block.low, block.open]
    # pattern.low = 85, block.open = 90 → zone=[85, 90]
    assert r.zone == (85, 90)


def test_too_few_candles():
    """< 3 свечей — None."""
    c1 = Candle(open=100, high=101, low=95, close=96)
    c2 = Candle(open=96, high=97, low=92, close=93)
    assert detect_block_orders([c1, c2]) is None
    assert detect_block_orders([c1]) is None
    assert detect_block_orders([]) is None


def test_fails_initial_doji():
    """Initial #1 = doji — fail (не определена направленность)."""
    preceding = Candle(open=80, high=92, low=78, close=90)
    c1 = Candle(open=86, high=88, low=84, close=86)   # doji
    c2 = Candle(open=86, high=95, low=85, close=94)
    assert detect_block_orders([preceding, c1, c2]) is None


def test_fails_preceding_doji():
    """Preceding = doji — fail."""
    preceding = Candle(open=90, high=91, low=89, close=90)  # doji
    c1 = Candle(open=90, high=91, low=85, close=86)
    c2 = Candle(open=86, high=95, low=85, close=94)
    assert detect_block_orders([preceding, c1, c2]) is None
