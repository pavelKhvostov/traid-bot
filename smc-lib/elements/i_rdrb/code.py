"""i-RDRB — 4-свечный reversal-паттерн. Спецификация: definition.md.

Канон 2026-06-14: liq i-RDRB переопределяется относительно подлежащего RDRB,
сдвигается в сторону разворота (зона «обманутой ликвидности»).
"""
from __future__ import annotations

import sys
import pathlib
from dataclasses import dataclass
from typing import Literal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from candle import Candle
from elements.rdrb.code import RDRB, detect_rdrb


Direction = Literal["long", "short"]
Variant = Literal["V1", "V2"]
Interval = tuple[float, float]  # (bottom, top)


@dataclass(frozen=True)
class IRDRB:
    direction: Direction               # всегда противоположен rdrb.direction
    variant: Variant                   # V1 = liq i-RDRB непустой; V2 = liq пустой → poi ≡ block
    rdrb: RDRB                         # подлежащий RDRB (его poi/block/liq остаются доступны как inherited)
    c4: Candle
    poi: Interval                      # i-RDRB POI = block ∪ liq (canon)
    block: Interval                    # = rdrb.block (inherited)
    liq: Interval | None               # i-RDRB liq (переопределён vs RDRB); None при V2


def detect_i_rdrb(c1: Candle, c2: Candle, c3: Candle, c4: Candle) -> IRDRB | None:
    """Возвращает IRDRB или None.

    i-RDRB — reversal-паттерн: C4 разворачивает движение C2 за границу RDRB block.
    SHORT RDRB (C2 bear) → LONG  i-RDRB: C4 bull AND C4.close > rdrb.block.top
    LONG  RDRB (C2 bull) → SHORT i-RDRB: C4 bear AND C4.close < rdrb.block.bottom
    Continuation-кейсы (C4 в ту же сторону, что C2) i-RDRB не образуют.

    Зоны (canon 2026-06-14):
      block — наследуется из rdrb.block
      LONG  i-RDRB: liq = [c3.body_top, c1.low]   если c3.body_top < c1.low (V1), иначе None (V2)
      SHORT i-RDRB: liq = [c1.high, c3.body_bottom] если c1.high < c3.body_bottom (V1), иначе None (V2)
      POI = block ∪ liq.
    """
    rdrb = detect_rdrb(c1, c2, c3)
    if rdrb is None:
        return None

    block_bottom, block_top = rdrb.block

    if rdrb.direction == "short":
        if not (c4.is_bull and c4.close > block_top):
            return None
        # LONG i-RDRB: liq ниже block
        c3_body_top = c3.body_top
        c1_low = c1.low
        if c3_body_top < c1_low:
            liq: Interval | None = (c3_body_top, c1_low)
            poi: Interval = (c3_body_top, block_top)
            variant: Variant = "V1"
        else:
            liq = None
            poi = rdrb.block
            variant = "V2"
        return IRDRB("long", variant, rdrb, c4, poi, rdrb.block, liq)

    # rdrb.direction == "long"
    if not (c4.is_bear and c4.close < block_bottom):
        return None
    # SHORT i-RDRB: liq выше block
    c1_high = c1.high
    c3_body_bottom = c3.body_bottom
    if c1_high < c3_body_bottom:
        liq = (c1_high, c3_body_bottom)
        poi = (block_bottom, c3_body_bottom)
        variant = "V1"
    else:
        liq = None
        poi = rdrb.block
        variant = "V2"
    return IRDRB("short", variant, rdrb, c4, poi, rdrb.block, liq)
