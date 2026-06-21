"""run_3candles_sweep — 3-свечный liquidity grab continuation pattern.

Спецификация: definition.md.
"""
from __future__ import annotations

import sys
import pathlib
from dataclasses import dataclass
from typing import Literal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from candle import Candle


Direction = Literal["long", "short"]
Interval = tuple[float, float]

WICK_BODY_RATIO_MIN = 2.5
ENTRY_WICK_FRACTION = 0.3


@dataclass(frozen=True)
class Run3CandlesSweep:
    direction: Direction
    c1: Candle
    c2: Candle
    c3: Candle
    sweep_zone: Interval   # полоса wick c2 = зона интереса
    entry: float
    sl: float
    tp: float


def detect_run_3candles_sweep(c1: Candle, c2: Candle, c3: Candle) -> Run3CandlesSweep | None:
    """Возвращает Run3CandlesSweep или None.

    SHORT: 3 bear подряд, c2.high > c1.high, c2.upper_wick ≥ 2.5 × c2.body.
    LONG — зеркально.
    """
    # SHORT
    if c1.is_bear and c2.is_bear and c3.is_bear:
        if c2.high <= c1.high:
            return None
        upper_wick = c2.high - max(c2.open, c2.close)
        body = abs(c2.open - c2.close)
        if body == 0: return None
        if upper_wick < WICK_BODY_RATIO_MIN * body:
            return None
        sweep_zone = (max(c2.open, c2.close), c2.high)
        entry = max(c2.open, c2.close) + ENTRY_WICK_FRACTION * upper_wick
        sl = c2.high
        tp = c3.low
        return Run3CandlesSweep("short", c1, c2, c3, sweep_zone, entry, sl, tp)

    # LONG
    if c1.is_bull and c2.is_bull and c3.is_bull:
        if c2.low >= c1.low:
            return None
        lower_wick = min(c2.open, c2.close) - c2.low
        body = abs(c2.open - c2.close)
        if body == 0: return None
        if lower_wick < WICK_BODY_RATIO_MIN * body:
            return None
        sweep_zone = (c2.low, min(c2.open, c2.close))
        entry = min(c2.open, c2.close) - ENTRY_WICK_FRACTION * lower_wick
        sl = c2.low
        tp = c3.high
        return Run3CandlesSweep("long", c1, c2, c3, sweep_zone, entry, sl, tp)

    return None
