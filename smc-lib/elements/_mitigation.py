"""SMC canon-aware mitigation tracker.

Per-element mitigation model from ~/smc-lib/elements/zone_of_interest.md:
- Wick-fill (gradual zone shrink): OB, block_orders, FVG, i-FVG, RDRB POI, i-RDRB POI,
  ob_vc, breaker_block, mitigation_block
- First-touch (one-shot consumption): RB, ob_liq (liq marker)
- Sweep (wick at level): fractal, marubozu (open level), VWAP, choch_bos

Critical distinction (user clarification 2026-06-14):
- **Mit-test** = bar's wick enters zone AND bar's close on "expected" side → counts for mitigation
- **Passage** = bar's close BEYOND zone (broken through) → NOT mitigation, but invalidation event

⚠ Legacy role-inversion (apply_wick_fill_mitigation `is_breaker` flag) — kept for
  backward compatibility, но в каноне 2026-06-14 структурный пробой OB.zone
  триггерит формирование **отдельных** элементов `breaker_block` (если pierced wick
  prev есть) и/или `mitigation_block` (если выполнилось Rule 1 закрепление).
  Detect those через standalone detectors:
    elements/breaker_block/code.py::detect_breaker
    elements/mitigation_block/code.py::detect_mitigation_block

Trigger: feedback-smc-canon-checklist.md (memory).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, Sequence

from candle import Candle

Direction = Literal["long", "short"]
Interval = tuple[float, float]


@dataclass
class ZoneState:
    """Mitigation state of a zonal SMC element after applying subsequent bars."""

    initial_zone: Interval
    direction: Direction  # original
    active_zone: Interval  # current (after wick-fill mit shrinkage)
    is_consumed: bool = False  # zone fully consumed
    is_invalidated_by_close: bool = False  # close past opposite boundary
    is_breaker: bool = False  # role inverted after structural break
    breaker_zone: Interval | None = None  # same geometry as initial, but inverted role
    n_real_mitigations: int = 0  # mit-test events (touched + reacted)
    n_passages: int = 0  # bars wicked through without test
    mit_history: list[tuple[int, Interval]] = field(default_factory=list)  # (bar_idx, zone_after_shrink)
    consumed_at_bar: int | None = None  # index where consumed
    invalidated_at_bar: int | None = None
    breaker_from_bar: int | None = None

    @property
    def effective_direction(self) -> Direction:
        """Direction after role inversion (breaker)."""
        if self.is_breaker:
            return "short" if self.direction == "long" else "long"
        return self.direction


def apply_wick_fill_mitigation(
    initial_zone: Interval,
    direction: Direction,
    subsequent_bars: Sequence[Candle],
    start_idx: int = 0,
) -> ZoneState:
    """Apply wick-fill mitigation model (OB, FVG, RDRB POI, etc.)

    LONG zone (support below): test from above, low ≤ zone_hi shrinks the zone.
    SHORT zone (resistance above): test from below, high ≥ zone_lo shrinks the zone.

    Critical: distinguish mit-test (close on expected side) vs passage (close beyond zone).
    """
    zlo, zhi = initial_zone
    state = ZoneState(
        initial_zone=initial_zone,
        direction=direction,
        active_zone=(zlo, zhi),
    )

    for i, bar in enumerate(subsequent_bars):
        idx = start_idx + i
        if state.is_consumed:
            break

        if direction == "long":
            # LONG zone (support): тестируется wick'ом сверху.
            # Canon Правила 2 Модели 1: смотрим ТОЛЬКО wick.
            # low > zone_hi → нет взаимодействия
            # low > zone_lo → fill_partial (zone shrinks)
            # low ≤ zone_lo → CONSUMED
            if bar.low > state.active_zone[1]:
                continue

            new_lo = bar.low
            if new_lo <= state.active_zone[0]:
                state.is_consumed = True
                state.consumed_at_bar = idx
                state.active_zone = (state.active_zone[0], state.active_zone[0])
            else:
                state.active_zone = (state.active_zone[0], new_lo)
                state.n_real_mitigations += 1
                state.mit_history.append((idx, state.active_zone))

        else:  # short
            # SHORT zone (resistance): тестируется wick'ом снизу.
            # high < zone_lo → нет взаимодействия
            # high < zone_hi → fill_partial (zone shrinks)
            # high ≥ zone_hi → CONSUMED
            if bar.high < state.active_zone[0]:
                continue

            new_hi = bar.high
            if new_hi >= state.active_zone[1]:
                state.is_consumed = True
                state.consumed_at_bar = idx
                state.active_zone = (state.active_zone[1], state.active_zone[1])
            else:
                state.active_zone = (new_hi, state.active_zone[1])
                state.n_real_mitigations += 1
                state.mit_history.append((idx, state.active_zone))

    return state


def apply_first_touch_mitigation(
    initial_zone: Interval,
    direction: Direction,
    subsequent_bars: Sequence[Candle],
    start_idx: int = 0,
    consume_at_fraction: float = 1.0,
) -> ZoneState:
    """First-touch model: wick reaches consume-level → zone consumed.

    Args:
        consume_at_fraction: где внутри зоны срабатывает consume.
            1.0 = внешний край wick'a (default, ob_liq канон).
            0.5 = середина wick'a = entry-level (RB канон 2026-06-15).
            Для LONG support: уровень = zlo + (zhi - zlo) × fraction.
            Для SHORT resist: уровень = zhi - (zhi - zlo) × fraction.
    """
    zlo, zhi = initial_zone
    state = ZoneState(initial_zone=initial_zone, direction=direction, active_zone=(zlo, zhi))

    if direction == "long":
        consume_level = zlo + (zhi - zlo) * consume_at_fraction
    else:
        consume_level = zhi - (zhi - zlo) * consume_at_fraction

    for i, bar in enumerate(subsequent_bars):
        idx = start_idx + i
        if state.is_consumed:
            break

        if direction == "long":
            if bar.low <= consume_level:  # wick reached consume-level (LONG support from above)
                state.is_consumed = True
                state.consumed_at_bar = idx
                state.n_real_mitigations = 1
                break
        else:  # short
            if bar.high >= consume_level:  # wick reached consume-level (SHORT resistance from below)
                state.is_consumed = True
                state.consumed_at_bar = idx
                state.n_real_mitigations = 1
                break

    return state


def apply_sweep_mitigation(
    level: float,
    direction: Literal["high", "low"],  # FH=high (top level), FL=low (bottom level)
    subsequent_bars: Sequence[Candle],
    start_idx: int = 0,
) -> dict:
    """Sweep model (fractal, marubozu open, VWAP).

    Returns dict (not ZoneState — single-level element):
    - swept: bool
    - swept_at_bar: int|None
    - magnitude_pct: float — how far past level (if swept)
    """
    result = {"swept": False, "swept_at_bar": None, "magnitude_pct": 0.0}
    for i, bar in enumerate(subsequent_bars):
        idx = start_idx + i
        if direction == "high":  # FH: swept when high > level
            if bar.high > level:
                result["swept"] = True
                result["swept_at_bar"] = idx
                result["magnitude_pct"] = (bar.high - level) / level * 100
                break
        else:  # low: FL: swept when low < level
            if bar.low < level:
                result["swept"] = True
                result["swept_at_bar"] = idx
                result["magnitude_pct"] = (level - bar.low) / level * 100
                break
    return result


# ─── Element-type registry (canon 2026-06-14) ──────────────────────────────
# Wick-fill: постепенное сжатие при касании wick'ом до противоположной границы
WICK_FILL_ELEMENTS = (
    "ob",                    # canonical OB drop/rally area
    "block_orders",          # composite N+M
    "fvg",                   # bullish/bearish FVG gap
    "i_fvg",                 # inverse FVG overlap zone
    "rdrb_poi",              # RDRB POI (block ∪ liq)
    "i_rdrb_poi",            # i-RDRB POI (with new inverted liq canon)
    "ob_vc",                 # HTF OB.zone (LTF FVG валидатор не trackается отдельно)
    "breaker_block",         # standalone flip-zone (pierced wick of prev)
    "mitigation_block",      # standalone flip-zone (бывшая OB drop/rally area после Rule 1)
)
# First-touch: одноразовый consumption на первом контакте wick'a
FIRST_TOUCH_ELEMENTS = ("rb", "ob_liq")
# Sweep: точечный level, wick касается → CONSUMED
SWEEP_ELEMENTS = (
    "fractal",               # Williams BW FH/FL
    "marubozu_open",         # marubozu open level (magnet)
    "vwap",                  # anchored VWAP (time-varying)
    "choch_bos",             # close-cross trigger (event, not zone, but tracked same way)
)


# Per-element overrides для first-touch fraction
FIRST_TOUCH_FRACTION: dict[str, float] = {
    "rb": 0.5,        # canon 2026-06-15: entry-level = mid wick
    "ob_liq": 1.0,    # canon: any wick touch (zone boundary)
}


def apply_mitigation(
    element_type: str,
    initial_zone: Interval | float,
    direction: Direction | Literal["high", "low"],
    subsequent_bars: Sequence[Candle],
    start_idx: int = 0,
) -> ZoneState | dict:
    """Dispatch by element type to correct mitigation model."""
    if element_type in WICK_FILL_ELEMENTS:
        return apply_wick_fill_mitigation(initial_zone, direction, subsequent_bars, start_idx)
    elif element_type in FIRST_TOUCH_ELEMENTS:
        fraction = FIRST_TOUCH_FRACTION.get(element_type, 1.0)
        return apply_first_touch_mitigation(initial_zone, direction, subsequent_bars,
                                             start_idx, consume_at_fraction=fraction)
    elif element_type in SWEEP_ELEMENTS:
        return apply_sweep_mitigation(initial_zone, direction, subsequent_bars, start_idx)
    else:
        raise ValueError(f"Unknown element_type: {element_type}")
