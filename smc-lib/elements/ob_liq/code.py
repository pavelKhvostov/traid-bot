"""OB с явно выраженным уровнем ликвидности. Спецификация: definition.md.

Composite: canon-OB (пара prev/cur) + 2-условный маркер ликвидности на prev.
Williams-фрактальность УБРАНА (2026-05-27).
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
class OBLiq:
    direction: Direction
    prev: Candle           # OB candle (с выраженным фитилём)
    cur: Candle            # reaction
    zone: Interval         # canon-OB зона входа
    liq_zone: Interval     # маркер ликвидности


def detect_ob_liq(prev: Candle, cur: Candle) -> OBLiq | None:
    """Возвращает OBLiq или None.

    Условия:
      LONG: prev bear, cur bull, cur.close > prev.open
            + нижний wick(prev) > 3×нижний wick(cur)
            + нижний wick(prev) > body(prev)
      SHORT — зеркально.
    """
    # LONG OB
    if prev.is_bear and cur.is_bull and cur.close > prev.open:
        prev_lower = min(prev.open, prev.close) - prev.low
        cur_lower = min(cur.open, cur.close) - cur.low
        prev_body = abs(prev.open - prev.close)
        if prev_lower <= 3 * cur_lower:
            return None
        if prev_lower <= prev_body:
            return None
        zone = (min(prev.low, cur.low), prev.open)
        liq_zone = (prev.low, cur.low)
        return OBLiq("long", prev, cur, zone, liq_zone)

    # SHORT OB
    if prev.is_bull and cur.is_bear and cur.close < prev.open:
        prev_upper = prev.high - max(prev.open, prev.close)
        cur_upper = cur.high - max(cur.open, cur.close)
        prev_body = abs(prev.open - prev.close)
        if prev_upper <= 3 * cur_upper:
            return None
        if prev_upper <= prev_body:
            return None
        zone = (prev.open, max(prev.high, cur.high))
        liq_zone = (cur.high, prev.high)
        return OBLiq("short", prev, cur, zone, liq_zone)

    return None
