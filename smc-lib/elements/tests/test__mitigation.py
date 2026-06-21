"""Tests for shared _mitigation.py utility.

Validates canon dispatch (wick-fill / first-touch / sweep) per element type.
Canon 2026-06-14: registry includes ob, fvg, block_orders, rdrb_poi, i_rdrb_poi,
i_fvg, ob_liq, ob_vc, rb, fractal, marubozu_open, vwap, breaker_block,
mitigation_block, choch_bos.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from candle import Candle
from elements._mitigation import (
    apply_mitigation,
    apply_wick_fill_mitigation,
    apply_first_touch_mitigation,
    apply_sweep_mitigation,
    WICK_FILL_ELEMENTS,
    FIRST_TOUCH_ELEMENTS,
    SWEEP_ELEMENTS,
    ZoneState,
)


def _c(o, h, l, c) -> Candle:
    return Candle(open=o, high=h, low=l, close=c)


# ─────────────────────────────────────────────────────────────────────
# Registry coverage (canon 2026-06-14)
# ─────────────────────────────────────────────────────────────────────

def test_wick_fill_registry_complete():
    """All zone elements that should use wick-fill are registered."""
    required = {
        "ob", "block_orders", "fvg", "i_fvg", "rdrb_poi", "i_rdrb_poi",
        "ob_vc", "breaker_block", "mitigation_block",
    }
    assert required.issubset(set(WICK_FILL_ELEMENTS))


def test_first_touch_registry_complete():
    required = {"rb", "ob_liq"}
    assert required.issubset(set(FIRST_TOUCH_ELEMENTS))


def test_sweep_registry_complete():
    required = {"fractal", "marubozu_open", "vwap", "choch_bos"}
    assert required.issubset(set(SWEEP_ELEMENTS))


def test_no_element_in_multiple_groups():
    """Sanity: один элемент не должен быть в нескольких группах."""
    wf = set(WICK_FILL_ELEMENTS)
    ft = set(FIRST_TOUCH_ELEMENTS)
    sw = set(SWEEP_ELEMENTS)
    assert not (wf & ft)
    assert not (wf & sw)
    assert not (ft & sw)


# ─────────────────────────────────────────────────────────────────────
# Dispatch via apply_mitigation()
# ─────────────────────────────────────────────────────────────────────

def test_dispatch_ob_to_wick_fill():
    """apply_mitigation('ob', ...) → ZoneState (wick-fill model)."""
    result = apply_mitigation(
        element_type="ob",
        initial_zone=(94, 100),
        direction="long",
        subsequent_bars=[_c(98, 99, 96, 97)],  # wick into zone
    )
    assert isinstance(result, ZoneState)


def test_dispatch_breaker_block_to_wick_fill():
    """breaker_block — wick-fill (new canon 2026-06-14)."""
    result = apply_mitigation(
        element_type="breaker_block",
        initial_zone=(100, 102),
        direction="short",
        subsequent_bars=[_c(99, 101, 98, 100)],
    )
    assert isinstance(result, ZoneState)


def test_dispatch_mitigation_block_to_wick_fill():
    """mitigation_block — wick-fill on flipped OB.zone."""
    result = apply_mitigation(
        element_type="mitigation_block",
        initial_zone=(94, 100),
        direction="short",  # bearish MB = short setup
        subsequent_bars=[_c(91, 96, 90, 92)],
    )
    assert isinstance(result, ZoneState)


def test_dispatch_ob_vc_to_wick_fill():
    """ob_vc — wick-fill (HTF OB.zone)."""
    result = apply_mitigation(
        element_type="ob_vc",
        initial_zone=(98, 104),
        direction="long",
        subsequent_bars=[_c(102, 103, 99, 100)],
    )
    assert isinstance(result, ZoneState)


def test_dispatch_rb_to_first_touch():
    """rb → first-touch по entry-level 0.5 (canon 2026-06-15)."""
    # zone=(95, 100) SHORT → midpoint=97.5. bar.high=98 ≥ 97.5 → consumed.
    result = apply_mitigation(
        element_type="rb",
        initial_zone=(95, 100),
        direction="short",
        subsequent_bars=[_c(94, 98, 93, 96)],
    )
    assert isinstance(result, ZoneState)
    assert result.is_consumed


def test_rb_0_5_canon_wick_just_to_boundary_not_consumed():
    """RB canon 2026-06-15: касание края зоны без выхода до 0.5 — НЕ consumed."""
    # zone=(95, 100) SHORT → midpoint=97.5. bar.high=96 < 97.5 → NOT consumed.
    result = apply_mitigation(
        element_type="rb",
        initial_zone=(95, 100),
        direction="short",
        subsequent_bars=[_c(92, 96, 91, 94)],
    )
    assert isinstance(result, ZoneState)
    assert not result.is_consumed


def test_dispatch_fractal_to_sweep():
    """fractal → dict via sweep model."""
    result = apply_mitigation(
        element_type="fractal",
        initial_zone=100.0,
        direction="high",  # FH
        subsequent_bars=[_c(99, 101, 98, 100)],  # high 101 > 100
    )
    assert isinstance(result, dict)
    assert result["swept"] is True


def test_dispatch_unknown_raises():
    """Unknown element_type → ValueError."""
    import pytest
    with pytest.raises(ValueError, match="Unknown element_type"):
        apply_mitigation(
            element_type="unknown_element",
            initial_zone=(0, 1),
            direction="long",
            subsequent_bars=[],
        )


# ─────────────────────────────────────────────────────────────────────
# Wick-fill semantics (canon zone shrinkage)
# ─────────────────────────────────────────────────────────────────────

def test_wick_fill_long_shrinks_zone():
    """LONG zone [94, 100]. Bar wick low=98 (above zone_lo=94) → shrinks to [94, 98]."""
    state = apply_wick_fill_mitigation(
        initial_zone=(94, 100),
        direction="long",
        subsequent_bars=[_c(99, 99.5, 98, 99)],
    )
    assert state.active_zone == (94, 98)
    assert state.is_consumed is False
    assert state.n_real_mitigations == 1


def test_wick_fill_long_consumes_zone():
    """LONG zone [94, 100]. Bar wick low=94 → CONSUMED."""
    state = apply_wick_fill_mitigation(
        initial_zone=(94, 100),
        direction="long",
        subsequent_bars=[_c(96, 97, 94, 95)],
    )
    assert state.is_consumed is True
    assert state.consumed_at_bar == 0


def test_wick_fill_short_shrinks_zone():
    """SHORT zone [100, 106]. Bar wick high=103 → shrinks to [103, 106]."""
    state = apply_wick_fill_mitigation(
        initial_zone=(100, 106),
        direction="short",
        subsequent_bars=[_c(101, 103, 100.5, 101)],
    )
    assert state.active_zone == (103, 106)
    assert state.n_real_mitigations == 1


# ─────────────────────────────────────────────────────────────────────
# REGRESSION (2026-06-15): canon wick-fill = ONLY wick check.
# Bug: старый код добавлял close-check, отправляя кейсы "wick reached
# opposite border + close beyond" в is_invalidated_by_close вместо
# is_consumed. Нашли через OB SHORT $63,520 на BTC 12h.
# ─────────────────────────────────────────────────────────────────────

def test_wick_fill_long_consumed_with_close_below():
    """LONG zone [94, 100]. Bar wick=94, close=92 (под zone_lo).
    Canon Правила 2 Модели 1: wick reached zone_lo → CONSUMED. Close НЕ важен."""
    state = apply_wick_fill_mitigation(
        initial_zone=(94, 100),
        direction="long",
        subsequent_bars=[_c(96, 97, 94, 92)],  # close=92 < zone_lo=94
    )
    assert state.is_consumed is True, "wick reached zone_lo → должно быть CONSUMED"
    assert state.is_invalidated_by_close is False, \
        "Правило 2 Модель 1 НЕ имеет invalidated-by-close branch"


def test_wick_fill_short_consumed_with_close_above():
    """SHORT zone [100, 106]. Bar wick=106, close=108 (над zone_hi).
    Canon: wick reached zone_hi → CONSUMED. Close НЕ важен."""
    state = apply_wick_fill_mitigation(
        initial_zone=(100, 106),
        direction="short",
        subsequent_bars=[_c(102, 106, 101, 108)],  # close=108 > zone_hi=106
    )
    assert state.is_consumed is True, "wick reached zone_hi → должно быть CONSUMED"
    assert state.is_invalidated_by_close is False, \
        "Правило 2 Модель 1 НЕ имеет invalidated-by-close branch"


def test_wick_fill_short_real_case_btc_ob_63520():
    """REGRESSION case: реальный OB SHORT $63,520 на BTC 12h, 2026-06-05.
    После 3 partial mitigations zone сжимается до (64394, 64495).
    Bar 06-13 12:00 UTC: high=64763 ≥ zone_hi=64495 → CONSUMED.
    Bug фиксил: эту консьюмацию.
    """
    initial_zone = (62546.0, 64494.92)
    # Bars from real BTC data
    subs = [
        _c(63886, 62458, 59131, 61056),  # 06-05 12: no interaction (h < zone_lo)
        _c(61056, 61530, 59500, 60803),
        _c(60803, 61185, 60394, 60885),
        _c(60885, 62960, 60746, 62622),  # partial 1
        _c(62622, 64235, 61184, 63332),  # partial 2
        _c(63332, 63873, 62408, 63480),
        _c(63480, 64200, 62718, 63086),
        _c(63086, 63526, 62423, 62711),
        _c(62711, 62895, 60780, 61730),
        _c(61730, 61975, 60755, 61034),
        _c(61034, 62858, 60960, 61511),
        _c(61511, 63257, 61511, 63108),
        _c(63108, 63933, 62348, 63626),
        _c(63626, 63954, 62830, 63766),
        _c(63766, 64394, 63045, 63580),  # partial 3
        _c(63580, 63985, 63419, 63971),
        _c(63971, 64763, 63920, 64458),  # CONSUMED: h=64763 ≥ zone_hi 64495
    ]
    state = apply_wick_fill_mitigation(
        initial_zone=initial_zone,
        direction="short",
        subsequent_bars=subs,
    )
    assert state.is_consumed is True
    assert state.consumed_at_bar == 16  # последний бар где h=64763
    assert state.n_real_mitigations == 3


# ─────────────────────────────────────────────────────────────────────
# First-touch semantics
# ─────────────────────────────────────────────────────────────────────

def test_first_touch_long_consumed_immediately():
    """LONG zone, любое касание wick'ом → CONSUMED."""
    state = apply_first_touch_mitigation(
        initial_zone=(94, 100),
        direction="long",
        subsequent_bars=[_c(101, 102, 99, 100.5)],
    )
    assert state.is_consumed is True
    assert state.n_real_mitigations == 1


def test_first_touch_short_consumed_immediately():
    state = apply_first_touch_mitigation(
        initial_zone=(100, 106),
        direction="short",
        subsequent_bars=[_c(95, 100.5, 94, 99)],
    )
    assert state.is_consumed is True


# ─────────────────────────────────────────────────────────────────────
# Sweep semantics
# ─────────────────────────────────────────────────────────────────────

def test_sweep_fh_swept_when_high_above_level():
    """FH level=100, bar high=101 → swept."""
    result = apply_sweep_mitigation(
        level=100.0,
        direction="high",
        subsequent_bars=[_c(98, 101, 97, 99)],
    )
    assert result["swept"] is True
    assert result["magnitude_pct"] == 1.0


def test_sweep_fl_swept_when_low_below_level():
    """FL level=100, bar low=99 → swept."""
    result = apply_sweep_mitigation(
        level=100.0,
        direction="low",
        subsequent_bars=[_c(101, 102, 99, 100.5)],
    )
    assert result["swept"] is True
    assert result["magnitude_pct"] == 1.0


def test_sweep_not_swept_when_level_untouched():
    result = apply_sweep_mitigation(
        level=100.0,
        direction="high",
        subsequent_bars=[_c(95, 98, 94, 96)],
    )
    assert result["swept"] is False
