---
tags: [strategy, s5, fvg]
date: 2026-04-27
related: [[что такое fvg]], [[три типа подтверждения 1h ob fvg rdrb]], [[главное правило ob только на последней закрытой 1h]]
---

# s5 FVG + OB1h

## Триггер старшего ТФ

Сырая FVG из 3 свечей на ТФ из `STRATEGY_TFS = ["12h", "1d", "2d", "3d"]`
([strategies/fvg.py](../../../strategies/fvg.py)):

- LONG: `c0.high < c2.low` (`high[i-2] < low[i]`)
- SHORT: `c0.low > c2.high` (`low[i-2] > high[i]`)

## Зона

Сам gap (без полутел и фильтров):

- LONG: `zone_bottom = c0.high`, `zone_top = c2.low`
- SHORT: `zone_bottom = c2.high`, `zone_top = c0.low`

`trigger_time = c2.open_time + tf` ([[trigger_time равен open_time плюс tf]]).

## Триггер младшего ТФ

1h, через [[три типа подтверждения 1h ob fvg rdrb]]. Подтверждение засчитывается только
если `confirm_time == последняя_закрытая_1h_свеча`.

## Замечание

В отличие от s2 (OB_HTF) у s5 **нет** дополнительного FVG-4h-фильтра — паттерн сам себе
достаточный. Это сознательное расхождение: s2 ловит OB и ему нужен FVG как подтверждение
импульса, а s5 уже и есть FVG.

## Источник в коде

- Детектор зоны: [strategies/fvg.py](../../../strategies/fvg.py)
- Подтверждение: `ob1h_core.find_first_confirmation_in_zone`

## Связи

- [[что такое fvg]]
- [[три типа подтверждения 1h ob fvg rdrb]]
- [[главное правило ob только на последней закрытой 1h]]
