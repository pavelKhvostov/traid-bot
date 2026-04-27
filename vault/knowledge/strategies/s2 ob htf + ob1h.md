---
tags: [strategy, s2, ob_htf]
date: 2026-04-27
related: [[что такое order block]], [[три типа подтверждения 1h ob fvg rdrb]], [[главное правило ob только на последней закрытой 1h]]
---

# s2 OB_HTF + OB1h

## Триггер старшего ТФ

OB-паттерн из **двух свечей** на ТФ из `STRATEGY_TFS = ["12h", "1d", "2d", "3d"]`
([scanner.py:29](../../../scanner.py#L29)).

**LONG:** `prev.close < prev.open` (красная) **и** `cur.close > prev.open` (закрылась выше открытия prev).
**SHORT:** зеркально (зелёная prev + закрытие cur ниже открытия prev).

## Зона

Новая формула (полутело + cur low/high), [strategies/ob_htf.py:71-81](../../../strategies/ob_htf.py#L71-L81):

- LONG: `zone_bottom = min(prev.low, cur.low)`, `zone_top = prev.open`
- SHORT: `zone_bottom = prev.open`, `zone_top = max(prev.high, cur.high)`

`trigger_time = cur.open_time + tf` ([[trigger_time равен open_time плюс tf]]).

## Обязательный фильтр FVG 4h

Зона валидна только если в окне `[cur.open_time, cur.open_time + tf)` на 4h нашлась
свеча `c0`, образующая FVG того же направления, чья область пересекается с зоной
([ob_htf.py:11-49](../../../strategies/ob_htf.py#L11-L49)).

Без подтверждающей FVG 4h зона **отбрасывается** — это главное отличие s2 от чистого OB.

## Триггер младшего ТФ

1h, через [[три типа подтверждения 1h ob fvg rdrb]] (`find_first_confirmation_in_zone`
в [strategies/ob1h_core.py:219](../../../strategies/ob1h_core.py#L219)). Подтверждение
засчитывается только если `confirm_time == последняя_закрытая_1h_свеча`
([[главное правило ob только на последней закрытой 1h]]).

## Источник в коде

- Детектор: [strategies/ob_htf.py](../../../strategies/ob_htf.py)
- FVG-фильтр 4h: `_has_confirming_fvg_4h` там же
- Подтверждение: `ob1h_core.find_first_confirmation_in_zone`

## Связи

- [[что такое order block]]
- [[что такое fvg]]
- [[три типа подтверждения 1h ob fvg rdrb]]
- [[главное правило ob только на последней закрытой 1h]]
