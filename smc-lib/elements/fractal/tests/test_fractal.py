import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from candle import Candle
from elements.fractal.code import detect_fractal


def _c(h, l):
    """Минимальная свеча с заданными high/low (open/close внутри для валидности)."""
    return Candle(open=l + 1, high=h, low=l, close=h - 1)


def test_fh_n2_canonical():
    """FH с N=2: центр (idx 2) имеет строго максимальный high."""
    candles = [_c(102, 95), _c(104, 97), _c(110, 99), _c(108, 100), _c(105, 98)]
    r = detect_fractal(candles, n=2)
    assert r is not None
    assert r.direction == "high"
    assert r.n == 2
    assert r.level == 110
    assert r.center is candles[2]


def test_fl_n2_canonical():
    """FL с N=2: центр имеет строго минимальный low."""
    candles = [_c(105, 98), _c(103, 96), _c(100, 88), _c(101, 91), _c(104, 95)]
    r = detect_fractal(candles, n=2)
    assert r is not None
    assert r.direction == "low"
    assert r.level == 88


def test_fh_n1_3bar():
    """FH с N=1 (3-bar fractal, Pine WICK.ED режим '3')."""
    candles = [_c(100, 95), _c(105, 98), _c(102, 96)]
    r = detect_fractal(candles, n=1)
    assert r is not None
    assert r.direction == "high"
    assert r.n == 1
    assert r.level == 105


def test_fl_n1_3bar():
    """FL с N=1."""
    candles = [_c(105, 98), _c(100, 90), _c(103, 95)]
    r = detect_fractal(candles, n=1)
    assert r is not None
    assert r.direction == "low"
    assert r.level == 90


def test_fh_n3_7bar():
    """FH с N=3 (7-bar окно)."""
    candles = [
        _c(100, 90), _c(101, 91), _c(102, 92),
        _c(110, 95),                            # center, max
        _c(103, 93), _c(104, 92), _c(105, 91),
    ]
    r = detect_fractal(candles, n=3)
    assert r is not None
    assert r.direction == "high"
    assert r.level == 110


def test_fails_tied_high():
    """Один из соседей имеет такой же high → не FH (strict ineq)."""
    candles = [_c(102, 95), _c(110, 97), _c(110, 99), _c(108, 100), _c(105, 98)]
    #                              ^^^ tied с центром
    assert detect_fractal(candles, n=2) is None


def test_fails_tied_low():
    """Tied low → не FL."""
    candles = [_c(105, 98), _c(103, 88), _c(100, 88), _c(101, 91), _c(104, 95)]
    #                              ^^^ tied
    assert detect_fractal(candles, n=2) is None


def test_fails_center_not_extremum():
    """Центр не максимум и не минимум — None."""
    candles = [_c(110, 90), _c(104, 95), _c(105, 98), _c(108, 96), _c(112, 92)]
    assert detect_fractal(candles, n=2) is None


def test_fails_wrong_length_too_few():
    """4 свечи при N=2 (нужно 5) → None."""
    candles = [_c(102, 95), _c(104, 97), _c(110, 99), _c(108, 100)]
    assert detect_fractal(candles, n=2) is None


def test_fails_wrong_length_too_many():
    """6 свечей при N=2 → None."""
    candles = [_c(102, 95), _c(104, 97), _c(110, 99), _c(108, 100), _c(105, 98), _c(103, 94)]
    assert detect_fractal(candles, n=2) is None


def test_fails_both_fh_and_fl_simultaneously():
    """Центр одновременно строго max по high И строго min по low (inside-neighbors candle) → None."""
    # Соседи: 100-95, 102-96 | center: 110-80 | 101-97, 99-94 — center съел всех
    candles = [_c(100, 95), _c(102, 96), _c(110, 80), _c(101, 97), _c(99, 94)]
    r = detect_fractal(candles, n=2)
    assert r is None  # ambiguous


def test_fails_n_zero():
    """N=0 невалидно (нет соседей)."""
    candles = [_c(110, 90)]
    assert detect_fractal(candles, n=0) is None


def test_fh_independent_of_lows():
    """FH проверяет только high; для FL чтобы НЕ сработал, center.low не должен быть min."""
    # center.low=95, у соседа [3] low=88 < 95 → FL fail. center.high=110 строго > все highs → FH ok.
    candles = [_c(102, 90), _c(104, 92), _c(110, 95), _c(108, 88), _c(105, 89)]
    r = detect_fractal(candles, n=2)
    assert r is not None
    assert r.direction == "high"
    assert r.level == 110


def test_left_neighbor_just_one_higher_fails():
    """Достаточно ОДНОГО соседа с >= high чтобы FH провалилось."""
    candles = [_c(111, 95), _c(104, 97), _c(110, 99), _c(108, 100), _c(105, 98)]
    #            ^^^ выше центра → FH fails
    r = detect_fractal(candles, n=2)
    assert r is None
