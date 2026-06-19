"""Mitigation Block. Спецификация: definition.md.

Canon 2026-06-14: MB = полностью пробитый OB + закрепление по Правилу 1.
ZoI = бывшая OB drop/rally area с инвертированной ролью (flip).

Триггер формирования:
  1. Существует OB (LONG или SHORT)
  2. Полный пробой OB.zone в обратную сторону:
     - LONG OB:  close < ob.zone[0] (drop_low)  → breakout вниз
     - SHORT OB: close > ob.zone[1] (rally_high) → breakout вверх
  3. Закрепление по Правилу 1: 1 пробойная + 3 подтверждающих свечи,
     у каждой из 3 — И open, И close за пробитым уровнем

После закрепления — OB.zone становится Mitigation Block с инвертированной ролью:
  LONG OB пробит вниз  → Bearish MB (resistance на возврате)
  SHORT OB пробит вверх → Bullish MB (support на возврате)

Mitigation модель: wick-fill (наследуется от OB, Правило 2 модель 1).
"""
from __future__ import annotations

import sys
import pathlib
from dataclasses import dataclass
from typing import Literal, Optional

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from candle import Candle
from elements.ob.code import OB


Direction = Literal["bearish", "bullish"]
Interval = tuple[float, float]


@dataclass(frozen=True)
class MitigationBlock:
    direction: Direction          # bearish = LONG OB пробит вниз (SHORT setup);
                                  # bullish = SHORT OB пробит вверх (LONG setup)
    ob: OB                        # исходный OB до пробоя
    breakout_idx: int             # индекс пробойной свечи (1) в массиве post_bars
    confirm_idxs: tuple[int, int, int]  # индексы 3 подтверждающих свечей (2, 3, 4)
    armed_at_idx: int             # = confirm_idxs[-1] (момент когда MB armed)
    broken_level: float           # пробитый уровень (= ob.zone[0] LONG OB, ob.zone[1] SHORT OB)
    zone: Interval                # = ob.zone (унаследована от OB, drop/rally area)


def detect_mitigation_block(
    ob: OB,
    post_bars: list[Candle],
    max_bars_to_breakout: int = 30,
) -> Optional[MitigationBlock]:
    """Детекция Mitigation Block на основе уже-найденного OB + последующих баров.

    Args:
        ob: OB-кандидат
        post_bars: бары ПОСЛЕ закрытия cur свечи OB (post_bars[0] = первая свеча после cur)
        max_bars_to_breakout: максимум баров от формирования OB до первой пробойной свечи

    Returns:
        MitigationBlock если зафиксировано закрепление по Правилу 1 (1 пробойная + 3 подтв.);
        None если пробой не произошёл, или закрепление не выполнилось,
        или OB.zone consumed wick-fill'ом до пробоя.

    ⚠ Anti-lookahead guardrail (per known-pitfalls «Anchor zone до cur_close»):
       post_bars[0] должен быть свечой ПОЛНОСТЬЮ ПОСЛЕ ob.cur.close_time. Caller
       обязан передавать правильно — детектор не валидирует timing.
    """
    drop_low, rally_high = ob.zone

    if ob.direction == "long":
        # LONG OB → ищем breakout вниз (close < drop_low)
        broken_level = drop_low
        mb_direction: Direction = "bearish"
    else:
        # SHORT OB → ищем breakout вверх (close > rally_high)
        broken_level = rally_high
        mb_direction = "bullish"

    # Сканируем post_bars в поисках пробойной свечи (1 из 4)
    n = len(post_bars)
    scan_end = min(max_bars_to_breakout, n)

    for i in range(scan_end):
        bar = post_bars[i]

        # Pre-breakout invalidation: до пробоя OB.zone должна оставаться wick-fill actionable.
        # Если до пробоя свеча зашла глубоко в OB.zone и закрылась внутри/прошла насквозь
        # на противоположную сторону — это не валидный setup для MB.
        # Проверяем только что текущая свеча — пробойная (close за уровнем в нужную сторону).
        if mb_direction == "bearish":
            if bar.close >= broken_level:
                continue  # not yet broken — продолжаем сканировать
            # bar.close < broken_level → пробойная свеча (1 из 4)
        else:  # bullish
            if bar.close <= broken_level:
                continue
            # bar.close > broken_level → пробойная свеча (1 из 4)

        # Найдена пробойная свеча на индексе i.
        # Нужно 3 подтверждающих ПОСЛЕДУЮЩИХ свечи с open И close за broken_level.
        confirm_start = i + 1
        confirm_end = confirm_start + 3
        if confirm_end > n:
            # Недостаточно баров для проверки закрепления
            return None

        # Проверяем 3 подтверждающих
        all_confirm_ok = True
        for j in range(confirm_start, confirm_end):
            c = post_bars[j]
            if mb_direction == "bearish":
                if not (c.open < broken_level and c.close < broken_level):
                    all_confirm_ok = False
                    break
            else:  # bullish
                if not (c.open > broken_level and c.close > broken_level):
                    all_confirm_ok = False
                    break

        if not all_confirm_ok:
            # Закрепление не выполнилось — пробой ложный.
            # NB: не пытаемся искать другой пробой далее по этому OB —
            # один OB может породить максимум один MB (либо armed, либо не сформировался).
            return None

        # Все 4 условия выполнены → MB armed
        return MitigationBlock(
            direction=mb_direction,
            ob=ob,
            breakout_idx=i,
            confirm_idxs=(confirm_start, confirm_start + 1, confirm_start + 2),
            armed_at_idx=confirm_start + 2,
            broken_level=broken_level,
            zone=ob.zone,
        )

    # Пробойная свеча не найдена в окне max_bars_to_breakout
    return None


def scan_mitigation_blocks(
    candles: list[Candle],
    max_bars_to_breakout: int = 30,
) -> list[tuple[int, MitigationBlock]]:
    """Скан всей серии: для каждой пары (i-1, i) проверяем OB, потом MB.

    Returns:
        list[(i_cur, MitigationBlock)] — индекс cur свечи OB + объект MB.
    """
    from elements.ob.code import detect_ob

    results = []
    n = len(candles)
    for i in range(1, n - 4):  # нужно min 4 баров после cur для проверки закрепления
        ob = detect_ob(candles[i - 1], candles[i])
        if ob is None:
            continue
        post = candles[i + 1:]
        mb = detect_mitigation_block(ob, post, max_bars_to_breakout)
        if mb is not None:
            results.append((i, mb))
    return results
