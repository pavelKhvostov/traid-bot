---
tags: [strategy, s1, obx4]
date: 2026-04-27
related: [[что такое обx4 цепочка]], [[три типа подтверждения 1h ob fvg rdrb]], [[главное правило ob только на последней закрытой 1h]]
---

# s1 OBx4 + OB1h

## Триггер старшего ТФ

OBx4-цепочка ([[что такое обx4 цепочка]]) на ТФ из `STRATEGY_TFS = ["12h", "1d", "2d", "3d"]`
([scanner.py:29](../../../scanner.py#L29)).

Изначально планировалось `[1h, 2h, 3h, 4h, 6h, 8h, 12h, 1d, 2d, 3d]`, но в реальном коде
все 7 стратегий используют общий список `STRATEGY_TFS` — четыре «крупных» ТФ.

Bullish и bearish детекторы — [strategies/obx4.py:78-185](../../../strategies/obx4.py#L78).

## Зона

Общее пересечение тел c1-c4:
- `ob_top = min(body_top(c1..c4))`
- `ob_bottom = max(body_bottom(c1..c4))`

`trigger_time = c5.open_time + tf` ([[trigger_time равен open_time плюс tf]]).

## Триггер младшего ТФ

1h, через [[три типа подтверждения 1h ob fvg rdrb]] — единая функция
`ob1h_core.find_first_confirmation_in_zone`
([strategies/ob1h_core.py:219](../../../strategies/ob1h_core.py#L219)).

**Главное правило:** подтверждение засчитывается только если
`confirm_time == последняя_закрытая_1h_свеча`
([[главное правило ob только на последней закрытой 1h]]).

## Stop-условие

Закрытие 1h за границей зоны (LONG: `close < zone_bottom`, SHORT: `close > zone_top`)
→ зона мертва, поиск подтверждения прекращается
([ob1h_core.py:248-252](../../../strategies/ob1h_core.py#L248-L252)).

## Формат сигнала в Telegram

Формирование — `telegram_bot.broadcast_signal`. Детали меты сигнала: `zone_bottom`,
`zone_top`, `confirm_zone_bottom/top` (1h-зона подтверждения), `confirm_type`
(`OB-1h | FVG-1h | RDRB-1h`).

## Источник в коде

- Детектор зоны: [strategies/obx4.py](../../../strategies/obx4.py)
- Подтверждение: `ob1h_core.find_first_confirmation_in_zone`
  ([strategies/ob1h_core.py](../../../strategies/ob1h_core.py))
- Диспатч: [scanner.py::_dispatch_strategy](../../../scanner.py)

## Связи

- [[что такое обx4 цепочка]]
- [[что такое order block]]
- [[три типа подтверждения 1h ob fvg rdrb]]
- [[главное правило ob только на последней закрытой 1h]]
- [[правило первого OB после возврата]]
