"""ob_sweep_liq_4candles — снятие ликвидности Williams-фрактала.

Спецификация: definition.md.

Reference (anchor) = любой Williams 5-bar FH/FL. Sweep candle Y приходит позже,
снимает ликвидность фрактала и закрывается за его close.

⚠️ Имя элемента (с "_4candles") историческое — после рефакторинга 2026-05-27
канон не привязан к строго 4-свечному окну. Reference = FH/FL анкер любой давности.
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
class OBSweepLiq4:
    direction: Direction
    anchor: Candle         # FH bar (SHORT) / FL bar (LONG) — Williams 5-bar фрактал
    sweep: Candle          # свеча Y, выполнившая sweep
    liq_zone: Interval     # область снятой ликвидности


def detect_ob_sweep_liq_4candles(anchor: Candle, y: Candle, direction: Direction) -> OBSweepLiq4 | None:
    """Возвращает OBSweepLiq4 или None.

    Caller отвечает за валидацию что `anchor` — Williams 5-bar FH (SHORT) или FL (LONG).
    Здесь проверяются только геометрические условия sweep.

    SHORT (anchor = FH, обычно bull):
      - y.open  < anchor.high   (открытие ниже FH = приход снизу)
      - y.high  > anchor.high   (sweep FH сверху)
      - y.close < anchor.open   (close ниже нижней границы тела OB-bar)

    LONG (anchor = FL, обычно bear) — зеркально:
      - y.open  > anchor.low
      - y.low   < anchor.low    (sweep FL снизу)
      - y.close > anchor.open   (close выше верхней границы тела OB-bar)
    """
    if direction == "short":
        if y.open  >= anchor.high:  return None
        if y.high  <= anchor.high:  return None
        if y.close >= anchor.open:  return None
        liq_zone = (anchor.high, y.high)
        return OBSweepLiq4("short", anchor, y, liq_zone)

    if direction == "long":
        if y.open  <= anchor.low:   return None
        if y.low   >= anchor.low:   return None
        if y.close <= anchor.open:  return None
        liq_zone = (y.low, anchor.low)
        return OBSweepLiq4("long", anchor, y, liq_zone)

    return None
