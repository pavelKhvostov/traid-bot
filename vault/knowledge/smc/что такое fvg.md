---
tags: [smc, primitive, fvg]
date: 2026-04-27
related: [[s5 fvg + ob1h]], [[s2 ob htf + ob1h]], [[три типа подтверждения 1h ob fvg rdrb]]
---

# Что такое FVG (Fair Value Gap)

## Идея

Импульс настолько резкий, что между свечами `i-2` и `i` остался ценовой разрыв,
который свеча `i-1` своими тенями не закрыла.

## Формальное определение

LONG (bullish FVG): `c0.high < c2.low` — между ними пустота `[c0.high, c2.low]`.
SHORT (bearish FVG): `c0.low > c2.high` — пустота `[c2.high, c0.low]`.

Где `c0 = i-2`, `c2 = i`. Свеча `c1` (середина) в условии не участвует — её роль
только «хвостами не дотянуть».

## Где используется в проекте

| Место | Назначение |
|---|---|
| [strategies/fvg.py](../../../strategies/fvg.py) | Сама стратегия s5 — FVG как зона старшего ТФ |
| [strategies/ob_htf.py:11-49](../../../strategies/ob_htf.py#L11-L49) | FVG 4h как фильтр для зоны s2 |
| [strategies/ob1h_core.py:171-184](../../../strategies/ob1h_core.py#L171-L184) | FVG-1h как один из трёх типов подтверждения |
| [strategies/obx4.py](../../../strategies/obx4.py) (внутри OBx4) | FVG между c3 и c5 как обязательный элемент паттерна |

## Связи

- [[s5 fvg + ob1h]]
- [[s2 ob htf + ob1h]]
- [[три типа подтверждения 1h ob fvg rdrb]]
- [[что такое обx4 цепочка]]
