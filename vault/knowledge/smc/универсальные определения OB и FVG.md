---
tags: [smc, primitive, ob, fvg, definitions, canon]
date: 2026-04-28
status: locked
related: [[что такое order block]], [[что такое fvg]]
---

# Универсальные определения зон OB и FVG

> **CANON.** Эти определения зафиксированы пользователем как универсальные
> и применяются ко **всем** ТФ и стратегиям проекта. Не менять без явного
> запроса пользователя.

## Зона Order Block (OB)

OB — пара (prev, cur) из двух последовательных свечей.

### LONG OB

```
zone = [min(prev.low, cur.low), prev.open]
```

От минимального low из двух свечей до open первой (более старой) свечи.

Условие формирования: `prev` медвежья (`close < open`), `cur` бычья реакция
(`close > prev.open`).

### SHORT OB

```
zone = [prev.open, max(prev.high, cur.high)]
```

От open первой свечи до максимального high из двух свечей.

Условие формирования: `prev` бычья (`close > open`), `cur` медвежья реакция
(`close < prev.open`).

## Зона FVG (Fair Value Gap)

FVG — 3-свечной паттерн `(i-2, i-1, i)`. Свеча `i-1` (середина) в формулах
зоны не участвует — её роль только «не дотянуть тенями».

### LONG FVG (bullish)

Условие: `high(i-2) < low(i)`

```
zone = [high(i-2), low(i)]
```

От high(i-2) (нижняя граница) до low(i) (верхняя граница).

### SHORT FVG (bearish)

Условие: `low(i-2) > high(i)`

```
zone = [high(i), low(i-2)]
```

От high(i) (нижняя граница) до low(i-2) (верхняя граница).
В словах: «от low i-2 до high i», что эквивалентно [high(i), low(i-2)].

## Где применяется

Эти определения используются на ВСЕХ ТФ:

| ТФ | OB модуль | FVG модуль |
|---|---|---|
| 1d/12h/2d/3d | [strategies/ob_htf.py](../../../strategies/ob_htf.py) | внутри ob_htf.py |
| 1h | [strategies/ob1h_core.py](../../../strategies/ob1h_core.py) | внутри ob1h_core.py |
| 15m | [strategies/vic_evot.py](../../../strategies/vic_evot.py) | внутри vic_evot.py |
| 4h, 3m | при необходимости — те же формулы |

## Связи

- [[что такое order block]] — детальное описание OB
- [[что такое fvg]] — детальное описание FVG
