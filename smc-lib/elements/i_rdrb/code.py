"""i-RDRB — 4-свечный reversal-паттерн. Спецификация: definition.md."""
from __future__ import annotations

import sys
import pathlib
from dataclasses import dataclass
from typing import Literal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from candle import Candle
from elements.rdrb.code import RDRB, detect_rdrb


Direction = Literal["long", "short"]


@dataclass(frozen=True)
class IRDRB:
    direction: Direction  # всегда противоположен rdrb.direction
    rdrb: RDRB
    c4: Candle


def detect_i_rdrb(c1: Candle, c2: Candle, c3: Candle, c4: Candle) -> IRDRB | None:
    """Возвращает IRDRB или None.

    i-RDRB — reversal-паттерн: C4 разворачивает движение C2 за границу RDRB block.
    SHORT RDRB (C2 bear) → LONG i-RDRB: C4 bull AND C4.close > rdrb.block.top
    LONG  RDRB (C2 bull) → SHORT i-RDRB: C4 bear AND C4.close < rdrb.block.bottom
    Continuation-кейсы (C4 в ту же сторону, что C2) i-RDRB не образуют.
    """
    rdrb = detect_rdrb(c1, c2, c3)
    if rdrb is None:
        return None

    block_bottom, block_top = rdrb.block

    if rdrb.direction == "short":
        if c4.is_bull and c4.close > block_top:
            return IRDRB("long", rdrb, c4)
        return None

    # rdrb.direction == "long"
    if c4.is_bear and c4.close < block_bottom:
        return IRDRB("short", rdrb, c4)
    return None
