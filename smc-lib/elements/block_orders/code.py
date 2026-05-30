"""Блок ордеров. Спецификация: definition.md.

Слайс: candles[0] = preceding, candles[1] = initial #1, ...
Counter stop на ПЕРВОЙ свече с close-crossing block.open.
(N₁, N₂) ≠ (1, 1) — это canon-OB.
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
class BlockOrders:
    direction: Direction
    n_initial: int
    n_counter: int
    open: float                    # = candles[0].open (initial #1)
    close: float                   # = candles[-1].close (counter, first-crossed)
    high: float
    low: float
    zone: Interval                 # (min(open, close), max(open, close))
    preceding: Candle
    candles: tuple[Candle, ...]    # initial + counter (length n_initial + n_counter)


def detect_block_orders(candles: list[Candle] | tuple[Candle, ...]) -> BlockOrders | None:
    """Детектирует блок ордеров в слайсе candles.

    Соглашение: candles[0] — preceding, candles[1] — initial #1, далее initial run + counter run.
    Если в слайсе свечи ПОСЛЕ first cross — игнорируются (блок заканчивается на first cross).
    """
    if len(candles) < 3:  # preceding + ≥2 block candles (так как (1,1) запрещено)
        return None

    preceding = candles[0]
    if preceding.is_doji:
        return None
    first = candles[1]
    if first.is_doji:
        return None

    initial_bear = first.is_bear
    # Preceding противоположна initial
    if initial_bear and not preceding.is_bull:
        return None
    if (not initial_bear) and not preceding.is_bear:
        return None

    # Initial run
    j = 1
    while j < len(candles) and (
        (initial_bear and candles[j].is_bear)
        or ((not initial_bear) and candles[j].is_bull)
    ):
        j += 1
    n_initial = j - 1
    if n_initial < 1 or j >= len(candles):
        return None

    block_open = first.open

    # Counter run, stop at first close-cross
    counter_bull = initial_bear
    m = 0
    crossed = False
    while j + m < len(candles):
        c = candles[j + m]
        ok = (counter_bull and c.is_bull) or ((not counter_bull) and c.is_bear)
        if not ok:
            break  # counter broken before crossing
        m += 1
        if (initial_bear and c.close > block_open) or ((not initial_bear) and c.close < block_open):
            crossed = True
            break
    if not crossed:
        return None

    n_counter = m
    # (N₁, N₂) ≠ (1, 1)
    if n_initial == 1 and n_counter == 1:
        return None

    block_candles = tuple(candles[1 : 1 + n_initial + n_counter])
    direction: Direction = "long" if initial_bear else "short"
    op = block_open
    cl = block_candles[-1].close
    hi = max(c.high for c in block_candles)
    lo = min(c.low for c in block_candles)
    # Зона интереса: от pattern.low/high до block.close (включает breaker-block + drop/rally area)
    if direction == "long":
        zone: Interval = (lo, cl)
    else:
        zone: Interval = (cl, hi)

    return BlockOrders(
        direction=direction,
        n_initial=n_initial,
        n_counter=n_counter,
        open=op,
        close=cl,
        high=hi,
        low=lo,
        zone=zone,
        preceding=preceding,
        candles=block_candles,
    )
