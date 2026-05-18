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

## Зона — три варианта определения (2026-05-18 update)

Зона задаёт область, где ожидается реакция при возврате цены. Есть **3 версии**
с разной шириной:

### V1 — Intersection (текущий код `strategies/strategy_rdrb.py`)

Узкая зона — пересечение фитилей anchor+trigger, ограниченное телами.

LONG:
- `zone_top = min(anchor.high, trigger.close)`
- `zone_bottom = max(trigger.low, anchor.close)`

SHORT:
- `zone_top = min(trigger.high, anchor.close)`
- `zone_bottom = max(anchor.low, trigger.close)`

Если `zone_top <= zone_bottom` — зона невалидна, отбрасывается.

### V2 — Intersection + anchor body extension

Зона расширяется до **тела anchor** (LONG — вниз до body_top, SHORT — вверх
до body_bottom).

LONG:
- `zone_top = min(anchor.high, trigger.close)` — как V1
- `zone_bottom = max(anchor.open, anchor.close)` — **тело TOP анкора**

SHORT:
- `zone_top = min(anchor.open, anchor.close)` — **тело BOTTOM анкора**
- `zone_bottom = max(anchor.low, trigger.close)`

Захватывает фитиль anchor над/под его телом, даже если trigger не дошёл туда.

### V3 — MAX (полный фитиль anchor)

Самая широкая зона — **весь противоположный фитиль anchor**. Trigger в
формуле не участвует.

LONG:
- `zone_top = anchor.high` — самый верхний пик
- `zone_bottom = max(anchor.open, anchor.close)` — тело TOP анкора

SHORT:
- `zone_top = min(anchor.open, anchor.close)` — тело BOTTOM анкора
- `zone_bottom = anchor.low`

Концептуально: «вся область, где anchor отыграл противоположное движение
фитилём». Trigger — только триггер паттерна, не геометрия зоны.

### Сравнение

```
LONG anchor пример: high=81000, open=80500, close=79800, low=79500
                    trigger.low=80100, trigger.close=80700

V1 zone = [max(80100, 79800)=80100,  min(81000, 80700)=80700]  width=600
V2 zone = [max(80500, 79800)=80500,  min(81000, 80700)=80700]  width=200  ← уже
V3 zone (MAX) = [80500, 81000]                                  width=500
```

V1/V2/V3 — это **trade-off ширина зоны vs качество сигнала**:
- V1 = узкая, но точная (там реально были оба свинга)
- V3 MAX = широкая, больше каскадов попадают внутрь, но entry может быть далеко
- V2 = баланс

## Где используется

| Место | Назначение |
|---|---|
| [strategies/rdrb.py](../../../strategies/rdrb.py) | Сама стратегия s3 — RDRB как зона старшего ТФ |
| [strategies/ob1h_core.py:187-216](../../../strategies/ob1h_core.py#L187-L216) | RDRB-1h как один из трёх типов подтверждения |

## Связи

- [[s3 rdrb + ob1h]]
- [[три типа подтверждения 1h ob fvg rdrb]]
