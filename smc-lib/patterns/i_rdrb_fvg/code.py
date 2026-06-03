"""i-RDRB с последующим FVG. Спецификация: definition.md.

Composite: i-RDRB на (C1-C4) + FVG на (C3-C4-C5) того же направления.
"""
from __future__ import annotations

import sys
import pathlib
from dataclasses import dataclass
from typing import Literal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from candle import Candle
from elements.i_rdrb.code import IRDRB, detect_i_rdrb
from elements.fvg.code import FVG, detect_fvg


Direction = Literal["long", "short"]


@dataclass(frozen=True)
class IRDRBFVG:
    direction: Direction
    irdrb: IRDRB
    fvg: FVG
    c5: Candle


def detect_i_rdrb_fvg(
    c1: Candle, c2: Candle, c3: Candle, c4: Candle, c5: Candle,
) -> IRDRBFVG | None:
    """Возвращает IRDRBFVG или None.

    Требует:
    - i-RDRB на (c1, c2, c3, c4)
    - FVG на (c3, c4, c5)
    - FVG.direction == i-RDRB.direction
    """
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None:
        return None
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != ir.direction:
        return None
    return IRDRBFVG(ir.direction, ir, fvg, c5)
