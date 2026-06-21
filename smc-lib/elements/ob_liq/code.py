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
    zone: Interval         # ZoI ob_liq = LIQ marker (canon 2026-06-16, narrow)
    entry_zone: Interval   # trade entry zone = canon-OB drop/rally area (wide, для размещения ордера)


def detect_ob_liq(prev: Candle, cur: Candle) -> OBLiq | None:
    """Возвращает OBLiq или None.

    ZoI ob_liq (canon 2026-06-16) = LIQ marker (narrow):
      LONG: [prev.low, cur.low]
      SHORT: [cur.high, prev.high]

    Trade entry zone (информационное поле) = canon-OB drop/rally area.

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
        liq_marker = (prev.low, cur.low)                        # narrow ZoI (canon 2026-06-16)
        entry_zone = (min(prev.low, cur.low), prev.open)        # wide trade entry
        return OBLiq("long", prev, cur, liq_marker, entry_zone)

    # SHORT OB
    if prev.is_bull and cur.is_bear and cur.close < prev.open:
        prev_upper = prev.high - max(prev.open, prev.close)
        cur_upper = cur.high - max(cur.open, cur.close)
        prev_body = abs(prev.open - prev.close)
        if prev_upper <= 3 * cur_upper:
            return None
        if prev_upper <= prev_body:
            return None
        liq_marker = (cur.high, prev.high)                       # narrow ZoI (canon 2026-06-16)
        entry_zone = (prev.open, max(prev.high, cur.high))       # wide trade entry
        return OBLiq("short", prev, cur, liq_marker, entry_zone)

    return None
