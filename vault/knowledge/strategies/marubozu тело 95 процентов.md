---
tags: [strategy, marubozu]
date: 2026-04-27
related: [[три типа подтверждения 1h ob fvg rdrb]], [[главное правило ob только на последней закрытой 1h]]
---

# MARUBOZU — тело ≥ 95% диапазона

## Идея

Одна свеча без значимых фитилей. Импульс ровно в направлении тела.

## Условие

[strategies/marubozu.py:12](../../../strategies/marubozu.py#L12):

`body / range >= 0.95`

Доджи (`c == o`) и пустые свечи (`range == 0`) пропускаем.

## Зона

Сам корпус свечи:

- LONG (`c > o`): `zone_bottom = o`, `zone_top = c`
- SHORT (`c < o`): `zone_bottom = c`, `zone_top = o`

`trigger_time = candle.open_time + tf` ([[trigger_time равен open_time плюс tf]]).

## Триггер младшего ТФ

1h, через [[три типа подтверждения 1h ob fvg rdrb]]. Подтверждение засчитывается только
если `confirm_time == последняя_закрытая_1h_свеча`.

## Заметки

- Marubozu — чистая геометрия одной свечи, без фрактала и без зависимости от соседей
  (в отличие от HAMMER).
- ТФ из `STRATEGY_TFS = ["12h", "1d", "2d", "3d"]`.

## Источник в коде

- [strategies/marubozu.py](../../../strategies/marubozu.py)
- Подтверждение: `ob1h_core.find_first_confirmation_in_zone`

## Связи

- [[три типа подтверждения 1h ob fvg rdrb]]
- [[главное правило ob только на последней закрытой 1h]]
