"""OB (Order Block). Спецификация: definition.md.

Канонический 2-свечный паттерн. Зона интереса по vault canon.
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


@dataclass(frozen=True)
class OB:
    direction: Direction
    prev: Candle
    cur: Candle
    zone: Interval            # полная зона интереса: [pattern.low, cur.close] LONG / [cur.close, pattern.high] SHORT
    breaker_block: Interval   # подзона тела синтетической свечи: [prev.open, cur.close] LONG / [cur.close, prev.open] SHORT


def detect_ob(prev: Candle, cur: Candle) -> OB | None:
    """Возвращает OB или None.

    LONG: prev bear, cur bull, cur.close > prev.open
    SHORT: prev bull, cur bear, cur.close < prev.open

    Геометрия совпадает с (N₁, N₂) = (1, 1) случаем block_orders:
    block.open = prev.open, block.close = cur.close, block.low/high = min/max(prev, cur).
    Зона интереса = breaker_block + drop/rally area (см. definition.md).
    """
    if prev.is_bear and cur.is_bull and cur.close > prev.open:
        pattern_low = min(prev.low, cur.low)
        return OB("long", prev, cur, (pattern_low, cur.close), (prev.open, cur.close))
    if prev.is_bull and cur.is_bear and cur.close < prev.open:
        pattern_high = max(prev.high, cur.high)
        return OB("short", prev, cur, (cur.close, pattern_high), (cur.close, prev.open))
    return None
