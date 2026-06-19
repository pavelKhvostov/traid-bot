"""Tests for i_fvg (canon v2 — 2026-06-15).

v2 canon: A.zone шринкается через wick-fill по between bars. i-FVG ZoI =
overlap(shrunk_A, B.zone). Если A полностью consumed между — i-FVG не формируется.
"""
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
# A.zone = [c1.high=105, c3.low=115]
B_BEAR = (
    Candle(open=130, high=132, low=118, close=119),   # B.c1
    Candle(open=119, high=120, low=102, close=104),   # B.c2 (first touch A)
    Candle(open=104, high=108, low=100, close=105),   # B.c3
)
# B.zone = [c3.high=108, c1.low=118]

# Зеркальный bear→bull iFVG
A_BEAR = (
    Candle(open=100, high=101, low=95, close=96),     # A.c1
    Candle(open=96, high=97, low=80, close=81),       # A.c2 (displacement down)
    Candle(open=81, high=85, low=76, close=78),       # A.c3
)
# A.zone = [c3.high=85, c1.low=95]
B_BULL = (
    Candle(open=70, high=82, low=68, close=81),       # B.c1
    Candle(open=81, high=98, low=80, close=96),       # B.c2 (first touch A)
    Candle(open=96, high=100, low=92, close=95),      # B.c3
)
# B.zone = [c1.high=82, c3.low=92]


def test_reference_bull_to_bear_ifvg():
    """Эталон bull→bear (between empty): shrunk_A = a.zone, overlap=(108,115)."""
    r = detect_i_fvg(*A_BULL, [], *B_BEAR)
    assert r is not None
    assert r.direction == "short"
    assert r.a.zone == (105, 115)
    assert r.b.zone == (108, 118)
    assert r.a_shrunk == (105, 115)   # без between — без шринка
    assert r.overlap == (108, 115)


def test_reference_bear_to_bull_ifvg():
    """Зеркальный bear→bull: shrunk_A == a.zone, overlap=(85,92)."""
    r = detect_i_fvg(*A_BEAR, [], *B_BULL)
    assert r is not None
    assert r.direction == "long"
    assert r.a.zone == (85, 95)
    assert r.b.zone == (82, 92)
    assert r.a_shrunk == (85, 95)
    assert r.overlap == (85, 92)


# ─────────────────────────────────────────────────────────────────
# Canon v2 — between bars shrink A.zone
# ─────────────────────────────────────────────────────────────────

def test_between_no_touch_no_shrink():
    """Свечи между не касаются A.zone — shrunk_A = a.zone."""
    between = (
        Candle(open=122, high=128, low=120, close=126),
        Candle(open=126, high=130, low=119, close=128),
    )
    r = detect_i_fvg(*A_BULL, between, *B_BEAR)
    assert r is not None
    assert r.a_shrunk == (105, 115)
    assert r.overlap == (108, 115)


def test_between_partial_shrink_canon_v2():
    """Между свеча с wick в A.zone — A.zone шринкается, i-FVG остаётся валидной.
    A bull zone=[105,115]. between bar low=110 → shrunk_A=[105,110].
    overlap с B=[108,118] = [108,110]."""
    between = (
        Candle(open=120, high=125, low=110, close=120),   # low=110 в A.zone → shrink
    )
    r = detect_i_fvg(*A_BULL, between, *B_BEAR)
    assert r is not None
    assert r.a_shrunk == (105, 110)
    assert r.overlap == (108, 110)


def test_between_full_consume_returns_none():
    """Между свеча low <= A.bottom → A consumed → None."""
    between = (
        Candle(open=120, high=121, low=104, close=109),   # low=104 ≤ A.bottom=105 → CONSUMED
    )
    assert detect_i_fvg(*A_BULL, between, *B_BEAR) is None


def test_between_multi_step_shrink():
    """Последовательные wicks шринкают A постепенно.
    A=[105,115]. between: low=113 → [105,113]; low=111 → [105,111]; low=110 → [105,110]."""
    between = (
        Candle(open=120, high=125, low=113, close=121),
        Candle(open=121, high=124, low=111, close=120),
        Candle(open=120, high=123, low=110, close=119),
    )
    r = detect_i_fvg(*A_BULL, between, *B_BEAR)
    assert r is not None
    assert r.a_shrunk == (105, 110)
    assert r.overlap == (108, 110)


def test_btc_real_user_a_case_2026_04_06():
    """Воспроизводит реальный кейс BTC 12h 2026-04-06: A→shrink→shrink→shrink→user-A.

    A.zone = [67307.28, 68776.61]  (LONG FVG 2026-04-05/06)
    Between bars shrink:
      bar.low=68300 → A=[67307, 68300]
      bar.low=68072 → A=[67307, 68072]
      bar.low=67732 → A=[67307, 67732]
    B.zone = [67516, 69324.65]  (SHORT FVG 2026-06-02/03)
    overlap = [67516, 67732] = user-A rectangle ($216 width)
    """
    a_c1 = Candle(open=67300.42, high=67307.28, low=66611.66, close=66999.00)
    a_c2 = Candle(open=66998.99, high=69136.20, low=66680.57, close=69034.18)
    a_c3 = Candle(open=69034.18, high=70283.32, low=68776.61, close=69614.91)
    between = [
        Candle(open=69614.91, high=70351, low=68300, close=68800),   # shrink to 68300
        Candle(open=68800, high=69200, low=68072, close=68500),       # shrink to 68072
        Candle(open=68500, high=68900, low=67732, close=68000),       # shrink to 67732
    ]
    b_c1 = Candle(open=71408.90, high=71408.90, low=69324.65, close=69461.72)
    b_c2 = Candle(open=69461.73, high=69548.13, low=66193.00, close=66760.83)
    b_c3 = Candle(open=66760.84, high=67516.00, low=65426.34, close=67067.37)

    r = detect_i_fvg(a_c1, a_c2, a_c3, between, b_c1, b_c2, b_c3)
    assert r is not None
    assert r.a.zone == (67307.28, 68776.61)
    assert r.a_shrunk == (67307.28, 67732)
    assert r.b.zone == (67516.0, 69324.65)
    assert r.overlap == (67516.0, 67732)
    assert r.direction == "short"


# ─────────────────────────────────────────────────────────────────
# Negative cases
# ─────────────────────────────────────────────────────────────────

def test_fails_when_b_same_direction_as_a():
    b_bull_same = (
        Candle(open=120, high=125, low=118, close=124),
        Candle(open=124, high=130, low=110, close=128),
        Candle(open=128, high=132, low=126, close=130),
    )
    assert detect_i_fvg(*A_BULL, [], *b_bull_same) is None


def test_fails_when_a_invalid():
    not_fvg = (
        Candle(open=100, high=120, low=99, close=119),
        Candle(open=119, high=121, low=110, close=115),
        Candle(open=115, high=118, low=105, close=110),
    )
    assert detect_i_fvg(*not_fvg, [], *B_BEAR) is None


def test_fails_when_b_invalid():
    not_fvg = (
        Candle(open=120, high=125, low=110, close=115),
        Candle(open=115, high=118, low=108, close=112),
        Candle(open=112, high=113, low=108, close=110),
    )
    assert detect_i_fvg(*A_BULL, [], *not_fvg) is None


def test_fails_when_no_touch_from_b_to_shrunk_a():
    """Ни одна свеча из B не касается shrunk A → None."""
    b_high = (
        Candle(open=130, high=132, low=128, close=129),
        Candle(open=129, high=130, low=120, close=121),
        Candle(open=121, high=122, low=116, close=118),
    )
    assert detect_i_fvg(*A_BULL, [], *b_high) is None


def test_fails_when_zones_dont_overlap():
    """A.zone и B.zone не пересекаются → None."""
    b_below = (
        Candle(open=120, high=121, low=100, close=102),
        Candle(open=102, high=103, low=85, close=87),
        Candle(open=87, high=90, low=80, close=82),
    )
    assert detect_i_fvg(*A_BULL, [], *b_below) is None


def test_overlap_geometry_when_b_inside_a():
    b_inside = (
        Candle(open=130, high=132, low=113, close=114),
        Candle(open=114, high=115, low=102, close=104),
        Candle(open=104, high=108, low=100, close=105),
    )
    r = detect_i_fvg(*A_BULL, [], *b_inside)
    assert r is not None
    assert r.b.zone == (108, 113)
    assert r.overlap == (108, 113)
