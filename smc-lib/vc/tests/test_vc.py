import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from candle import Candle
from elements.ob.code import detect_ob
from elements.fvg.code import detect_fvg
from vc.code import has_vc, find_vc_confirmations


# ---- LONG: LONG FVG-15m внутри LONG OB-1h ----
OB_LONG_PREV = Candle(open=110, high=112, low=100, close=102)   # bear
OB_LONG_CUR  = Candle(open=102, high=115, low=101, close=113)   # bull, close > prev.open
FVG_LONG_INSIDE = (
    Candle(open=104, high=105, low=103, close=104),
    Candle(open=104, high=110, low=104, close=109),
    Candle(open=109, high=111, low=107, close=110),
)  # FVG.zone = [105, 107] ⊆ OB.zone [100, 113]


def test_long_vc_predicate_true():
    ob = detect_ob(OB_LONG_PREV, OB_LONG_CUR)
    fvg = detect_fvg(*FVG_LONG_INSIDE)
    assert ob.zone == (100, 113) and fvg.zone == (105, 107)
    assert has_vc(ob, fvg) is True


# ---- SHORT: SHORT FVG-15m внутри SHORT OB-1h ----
OB_SHORT_PREV = Candle(open=100, high=110, low=98, close=108)   # bull
OB_SHORT_CUR  = Candle(open=108, high=109, low=95, close=97)    # bear
FVG_SHORT_INSIDE = (
    Candle(open=106, high=107, low=105, close=106),
    Candle(open=106, high=106, low=100, close=101),
    Candle(open=101, high=103, low=100, close=102),
)  # FVG.zone = [103, 105]


def test_short_vc_predicate_true():
    ob = detect_ob(OB_SHORT_PREV, OB_SHORT_CUR)  # zone [97, 110]
    fvg = detect_fvg(*FVG_SHORT_INSIDE)
    assert ob.direction == "short" and fvg.zone == (103, 105)
    assert has_vc(ob, fvg) is True


# ---- Negative: разные направления ----
def test_direction_mismatch_returns_false():
    ob = detect_ob(OB_LONG_PREV, OB_LONG_CUR)  # LONG
    fvg = detect_fvg(*FVG_SHORT_INSIDE)  # SHORT
    assert has_vc(ob, fvg) is False


# ---- Negative: FVG целиком вне OB ----
def test_fvg_outside_returns_false():
    ob = detect_ob(OB_LONG_PREV, OB_LONG_CUR)  # zone [100, 113]
    fvg_outside = (
        Candle(open=80, high=80, low=78, close=79),
        Candle(open=79, high=92, low=79, close=91),
        Candle(open=91, high=92, low=90, close=91),
    )  # FVG.zone = [80, 90] < OB.lo
    fvg = detect_fvg(*fvg_outside)
    assert fvg.zone == (80, 90)
    assert has_vc(ob, fvg) is False


# ---- Negative: FVG частично выходит за OB ----
def test_fvg_partial_overlap_returns_false():
    ob = detect_ob(OB_LONG_PREV, OB_LONG_CUR)
    fvg_partial = (
        Candle(open=110, high=112, low=109, close=111),
        Candle(open=111, high=120, low=110, close=119),
        Candle(open=119, high=121, low=115, close=120),
    )
    fvg = detect_fvg(*fvg_partial)  # zone = [112, 115], 115 > 113
    assert has_vc(ob, fvg) is False


# ---- Edge: FVG ровно на границе OB ----
def test_edge_touching_zones_returns_true():
    ob = detect_ob(OB_LONG_PREV, OB_LONG_CUR)  # zone [100, 113]
    edge_fvg = (
        Candle(open=99, high=100, low=98, close=99),
        Candle(open=99, high=114, low=99, close=113),
        Candle(open=113, high=115, low=113, close=114),
    )
    fvg = detect_fvg(*edge_fvg)
    assert fvg.zone == (100, 113)
    assert has_vc(ob, fvg) is True  # ≤ включительно


# ---- find_vc_confirmations ----
def test_find_vc_confirmations_filters_list():
    ob = detect_ob(OB_LONG_PREV, OB_LONG_CUR)  # LONG, zone [100, 113]
    inside = detect_fvg(*FVG_LONG_INSIDE)        # подтверждает
    outside = detect_fvg(
        Candle(open=80, high=80, low=78, close=79),
        Candle(open=79, high=92, low=79, close=91),
        Candle(open=91, high=92, low=90, close=91),
    )                                            # не подтверждает
    wrong_dir = detect_fvg(*FVG_SHORT_INSIDE)    # SHORT — не подтверждает
    confs = find_vc_confirmations(ob, [inside, outside, wrong_dir])
    assert confs == [inside]
