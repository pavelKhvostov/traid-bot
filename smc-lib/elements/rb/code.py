"""RB (Rejection Block). Спецификация: definition.md.

Одиночная свеча. Доминирующий фитиль ≥ 2× второго фитиля И ≥ 3× тела.
"""
from __future__ import annotations

import sys
import pathlib
from dataclasses import dataclass
from typing import Literal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from candle import Candle


Direction = Literal["top", "bottom"]      # top = bearish rejection, bottom = bullish
Interval = tuple[float, float]

# Canon thresholds (зафиксированы 2026-05-24)
K1_DOM_OVER_OTHER = 2.0
K2_DOM_OVER_BODY = 3.0


@dataclass(frozen=True)
class RB:
    direction: Direction
    candle: Candle
    body: float
    upper_wick: float
    lower_wick: float
    zone: Interval               # зона доминирующего фитиля


def detect_rb(c: Candle) -> RB | None:
    """Возвращает RB или None.

    TOP RB: upper_wick ≥ 2× lower_wick AND upper_wick ≥ 3× body.
    BOTTOM RB: lower_wick ≥ 2× upper_wick AND lower_wick ≥ 3× body.
    Требуется body > 0 (не doji) и противоположный фитиль > 0.
    """
    body = abs(c.open - c.close)
    if body <= 0:
        return None

    body_top = max(c.open, c.close)
    body_bot = min(c.open, c.close)
    upper = c.high - body_top
    lower = body_bot - c.low

    # TOP RB
    if upper > 0 and lower > 0:
        if upper >= K1_DOM_OVER_OTHER * lower and upper >= K2_DOM_OVER_BODY * body:
            return RB(
                direction="top", candle=c,
                body=body, upper_wick=upper, lower_wick=lower,
                zone=(body_top, c.high),
            )
        # BOTTOM RB
        if lower >= K1_DOM_OVER_OTHER * upper and lower >= K2_DOM_OVER_BODY * body:
            return RB(
                direction="bottom", candle=c,
                body=body, upper_wick=upper, lower_wick=lower,
                zone=(c.low, body_bot),
            )
    return None
