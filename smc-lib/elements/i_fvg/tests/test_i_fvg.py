import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from candle import Candle
from elements.i_fvg.code import detect_i_fvg


# Эталонный bull→bear iFVG из definition.md
A_BULL = (
    Candle(open=100, high=105, low=99, close=104),    # A.c1
    Candle(open=104, high=120, low=103, close=119),   # A.c2 (displacement up)
    Candle(open=119, high=124, low=115, close=122),   # A.c3
)
B_BEAR = (
    Candle(open=130, high=132, low=118, close=119),   # B.c1
    Candle(open=119, high=120, low=102, close=104),   # B.c2 (first touch A)
    Candle(open=104, high=108, low=100, close=105),   # B.c3
)

# Зеркальный bear→bull iFVG
A_BEAR = (
    Candle(open=100, high=101, low=95, close=96),     # A.c1
    Candle(open=96, high=97, low=80, close=81),       # A.c2 (displacement down)
    Candle(open=81, high=85, low=76, close=78),       # A.c3
)
B_BULL = (
    Candle(open=70, high=82, low=68, close=81),       # B.c1
    Candle(open=81, high=98, low=80, close=96),       # B.c2 (first touch A)
    Candle(open=96, high=100, low=92, close=95),      # B.c3
)


def test_reference_bull_to_bear_ifvg():
    """Эталон bull→bear: A.zone=[105,115], B.zone=[108,118], overlap=[108,115]."""
    r = detect_i_fvg(*A_BULL, [], *B_BEAR)
    assert r is not None
    assert r.direction == "short"
    assert r.a.direction == "long"
    assert r.b.direction == "short"
    assert r.a.zone == (105, 115)
    assert r.b.zone == (108, 118)
    assert r.overlap == (108, 115)
    assert r.between == ()


def test_reference_bear_to_bull_ifvg():
    """Зеркальный bear→bull: A.zone=[85,95], B.zone=[82,92], overlap=[85,92]."""
    r = detect_i_fvg(*A_BEAR, [], *B_BULL)
    assert r is not None
    assert r.direction == "long"
    assert r.a.direction == "short"
    assert r.b.direction == "long"
    assert r.a.zone == (85, 95)
    assert r.b.zone == (82, 92)
    assert r.overlap == (85, 92)


def test_between_untouched_ok():
    """Свечи между A и B, не касающиеся A.zone=[105,115], — разрешены."""
    between = (
        Candle(open=122, high=128, low=120, close=126),   # выше зоны A
        Candle(open=126, high=130, low=119, close=128),   # low=119 > A.top=115
    )
    r = detect_i_fvg(*A_BULL, between, *B_BEAR)
    assert r is not None
    assert len(r.between) == 2


def test_fails_when_between_touches_a():
    """Свеча в between касается A.zone → A уже не untouched → None."""
    between = (
        Candle(open=122, high=125, low=110, close=120),   # low=110 ∈ A.zone=[105,115]
    )
    assert detect_i_fvg(*A_BULL, between, *B_BEAR) is None


def test_fails_when_b_same_direction_as_a():
    """B того же направления (bull→bull) — не iFVG."""
    b_bull_same = (
        Candle(open=120, high=125, low=118, close=124),
        Candle(open=124, high=130, low=110, close=128),   # bull displacement, touches A
        Candle(open=128, high=132, low=126, close=130),
    )
    # FVG-B на этих свечах bullish (c1.high=125 < c3.low=126)
    assert detect_i_fvg(*A_BULL, [], *b_bull_same) is None


def test_fails_when_a_invalid():
    """Если A.c1.high >= A.c3.low — FVG-A не валидна → None."""
    not_fvg = (
        Candle(open=100, high=120, low=99, close=119),
        Candle(open=119, high=121, low=110, close=115),
        Candle(open=115, high=118, low=105, close=110),   # c3.low=105 < c1.high=120
    )
    assert detect_i_fvg(*not_fvg, [], *B_BEAR) is None


def test_fails_when_b_invalid():
    """Если B не FVG — None."""
    not_fvg = (
        Candle(open=120, high=125, low=110, close=115),   # bear, low=110 ∈ A.zone
        Candle(open=115, high=118, low=108, close=112),   # bear, c1.low=110 vs c3.high — посмотрим
        Candle(open=112, high=113, low=108, close=110),
    )
    # c1.low=110, c3.high=113 → 110 < 113 → не SHORT FVG. c1.high=125, c3.low=108 → не LONG.
    assert detect_i_fvg(*A_BULL, [], *not_fvg) is None


def test_fails_when_no_touch_from_b():
    """Ни одна свеча из B не касается A.zone → first touch произошёл бы вне B → None."""
    # Создаём B-bear полностью выше A.zone=[105,115] (low всех B-свечей > 115)
    b_high = (
        Candle(open=130, high=132, low=128, close=129),
        Candle(open=129, high=130, low=120, close=121),   # low=120 > A.top=115 → не касается
        Candle(open=121, high=122, low=116, close=118),   # low=116 > 115 → не касается
    )
    # FVG-B SHORT: c1.low=128 > c3.high=122 ✓
    assert detect_i_fvg(*A_BULL, [], *b_high) is None


def test_fails_when_zones_dont_overlap():
    """A.zone и B.zone не пересекаются → None.

    A=[105,115] bull. B-bear полностью НИЖЕ A: B.zone должен быть < 105.
    Но при этом хотя бы одна свеча B касается A (wick проходит через A).
    """
    b_below = (
        Candle(open=120, high=121, low=100, close=102),   # bear, wick low=100 < A.bottom=105 → touches
        Candle(open=102, high=103, low=85, close=87),     # bear displacement down
        Candle(open=87, high=90, low=80, close=82),       # bear
    )
    # FVG-B SHORT: c1.low=100 > c3.high=90 ✓, zone=[90, 100], НЕ пересекается с [105, 115]
    assert detect_i_fvg(*A_BULL, [], *b_below) is None


def test_overlap_geometry_when_b_inside_a():
    """B.zone полностью внутри A.zone → overlap == B.zone."""
    # Сузим B чтобы B.zone ⊂ A.zone=[105,115]
    b_inside = (
        Candle(open=130, high=132, low=113, close=114),   # B.c1 bear, low=113
        Candle(open=114, high=115, low=102, close=104),   # B.c2 bear displacement, touches A
        Candle(open=104, high=108, low=100, close=105),   # B.c3 bear, high=108
    )
    # B SHORT: c1.low=113 > c3.high=108 → zone=[108, 113]. A=[105, 115]. Overlap=[108, 113] = B.zone.
    r = detect_i_fvg(*A_BULL, [], *b_inside)
    assert r is not None
    assert r.b.zone == (108, 113)
    assert r.overlap == (108, 113)
