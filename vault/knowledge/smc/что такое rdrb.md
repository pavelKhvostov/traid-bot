---
tags: [smc, primitive, rdrb]
date: 2026-04-27
related: [[s3 rdrb + ob1h]], [[три типа подтверждения 1h ob fvg rdrb]]
---

# Что такое RDRB

## Расшифровка

**Rally-Drop-Rally-Base** в классической формулировке. В коде проекта используется
сжатая версия из 3 свечей (anchor, mid, trigger) — фактически паттерн «ложного пробоя
с возвратом», который содержательно похож на классический RDRB.

## Формальное определение

[strategies/rdrb.py:38-47](../../../strategies/rdrb.py#L38-L47):

**LONG:**
- `mid.close > anchor.high` (средняя ушла выше high якоря)
- `trigger.low < anchor.high` (триггер пробил уровень низом)
- `trigger.close > anchor.high` (но закрылся обратно над уровнем)

**SHORT:** зеркально вокруг `anchor.low`.

## Зона — формула пересечения фитилей с ограничением телами

LONG:
- `zone_bottom = max(trigger.low, max(anchor.open, anchor.close))`
- `zone_top = min(anchor.high, min(trigger.open, trigger.close))`

SHORT:
- `zone_bottom = max(anchor.low, max(trigger.open, trigger.close))`
- `zone_top = min(trigger.high, min(anchor.open, anchor.close))`

Если `zone_top <= zone_bottom` — зона невалидна, отбрасывается.

## Где используется

| Место | Назначение |
|---|---|
| [strategies/rdrb.py](../../../strategies/rdrb.py) | Сама стратегия s3 — RDRB как зона старшего ТФ |
| [strategies/ob1h_core.py:187-216](../../../strategies/ob1h_core.py#L187-L216) | RDRB-1h как один из трёх типов подтверждения |

## Связи

- [[s3 rdrb + ob1h]]
- [[три типа подтверждения 1h ob fvg rdrb]]
