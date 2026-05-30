"""RDRB — 3-свечный паттерн. Спецификация: definition.md."""
from __future__ import annotations

import sys
import pathlib
from dataclasses import dataclass, field
from typing import Literal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from candle import Candle, intervals_overlap


Direction = Literal["long", "short"]
Variant = Literal["V1", "V2"]
Interval = tuple[float, float]  # (bottom, top)


@dataclass(frozen=True)
class RDRB:
    direction: Direction
    variant: Variant                   # V1 = liq непустой; V2 = block == poi
    c1: Candle
    c2: Candle
    c3: Candle
    poi: Interval                      # зона интереса; block примыкает к одной границе POI
    block: Interval                    # пересечение виков; block ⊆ poi
    liq: Interval | None               # POI \ block; один интервал или None


def detect_rdrb(c1: Candle, c2: Candle, c3: Candle) -> RDRB | None:
    """Возвращает RDRB или None, если C1-C2-C3 не образуют паттерн."""
    if c2.is_bear:
        if c2.close >= c1.low:
            return None
        if not intervals_overlap((c3.body_top, c3.high), (c1.low, c1.body_bottom)):
            return None
        if c1.body_bottom <= c3.body_top:
            return None
        block_bottom = max(c1.low, c3.body_top)
        block_top = min(c1.body_bottom, c3.high)
        block = (block_bottom, block_top)
        poi = (block_bottom, c1.body_bottom)
        liq: Interval | None = (block_top, c1.body_bottom) if block_top < c1.body_bottom else None
        variant: Variant = "V2" if liq is None else "V1"
        return RDRB("short", variant, c1, c2, c3, poi, block, liq)

    if c2.is_bull:
        if c2.close <= c1.high:
            return None
        if not intervals_overlap((c3.low, c3.body_bottom), (c1.body_top, c1.high)):
            return None
        if c3.body_bottom <= c1.body_top:
            return None
        block_bottom = max(c1.body_top, c3.low)
        block_top = min(c1.high, c3.body_bottom)
        block = (block_bottom, block_top)
        poi = (c1.body_top, block_top)
        liq: Interval | None = (c1.body_top, block_bottom) if block_bottom > c1.body_top else None
        variant: Variant = "V2" if liq is None else "V1"
        return RDRB("long", variant, c1, c2, c3, poi, block, liq)

    return None
