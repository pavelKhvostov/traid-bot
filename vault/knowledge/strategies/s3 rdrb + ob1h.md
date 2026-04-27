---
tags: [strategy, s3, rdrb]
date: 2026-04-27
related: [[что такое rdrb]], [[три типа подтверждения 1h ob fvg rdrb]], [[главное правило ob только на последней закрытой 1h]]
---

# s3 RDRB + OB1h

## Триггер старшего ТФ

3-свечной RDRB-паттерн на ТФ из `STRATEGY_TFS = ["12h", "1d", "2d", "3d"]`. Якорная — `i-2`,
средняя — `i-1`, триггер — `i` ([strategies/rdrb.py](../../../strategies/rdrb.py)).

**LONG:** `mid.close > anchor.high` И `cur.low < anchor.high` И `cur.close > anchor.high`.
Средняя ушла выше high якоря, текущая свечой пробила его low-ом и закрылась обратно вверх.

**SHORT:** зеркально вокруг `anchor.low`.

## Зона — новая формула (пересечение фитилей с ограничением телами)

[rdrb.py:38-47](../../../strategies/rdrb.py#L38-L47):

- LONG: `zone_bottom = max(cur.low, max(anchor.open, anchor.close))`,
  `zone_top = min(anchor.high, min(cur.open, cur.close))`
- SHORT: `zone_bottom = max(anchor.low, max(cur.open, cur.close))`,
  `zone_top = min(cur.high, min(anchor.open, anchor.close))`

Если `zone_top <= zone_bottom` — зона отбрасывается.

`trigger_time = cur.open_time + tf` ([[trigger_time равен open_time плюс tf]]).

## Триггер младшего ТФ

1h, через [[три типа подтверждения 1h ob fvg rdrb]]. Подтверждение засчитывается только
если `confirm_time == последняя_закрытая_1h_свеча`.

## Источник в коде

- Детектор зоны: [strategies/rdrb.py](../../../strategies/rdrb.py)
- Подтверждение: `ob1h_core.find_first_confirmation_in_zone`

## Связи

- [[что такое rdrb]]
- [[три типа подтверждения 1h ob fvg rdrb]]
- [[главное правило ob только на последней закрытой 1h]]
