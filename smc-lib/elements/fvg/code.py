"""FVG (Fair Value Gap) — 3-свечный гэп. Спецификация: definition.md."""
from __future__ import annotations

import sys
import pathlib
from dataclasses import dataclass
from typing import Literal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from candle import Candle


Direction = Literal["long", "short"]
Interval = tuple[float, float]


@dataclass(frozen=True)
class FVG:
    direction: Direction
    c1: Candle
    c2: Candle      # displacement
    c3: Candle
    zone: Interval  # (bottom, top)


def detect_fvg(c1: Candle, c2: Candle, c3: Candle) -> FVG | None:
    """Возвращает FVG или None. Условия long/short взаимоисключающие."""
    if c1.high < c3.low:
        return FVG("long", c1, c2, c3, (c1.high, c3.low))
    if c1.low > c3.high:
        return FVG("short", c1, c2, c3, (c3.high, c1.low))
    return None
