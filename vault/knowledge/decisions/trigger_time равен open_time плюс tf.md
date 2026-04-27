---
tags: [decision, time, zones]
date: 2026-04-27
status: locked
---

# `trigger_time = open_time + tf` (правка 2026-04-27)

## Решение

Во всех детекторах зон время «открытия зоны» (с которого мы начинаем искать подтверждение
на 1h) считается как **`open_time` последней свечи паттерна + длительность ТФ**, то есть
**момент закрытия** этой свечи.

`pd.Timedelta(tf)` — например `Timedelta("12h")`, `Timedelta("3d")`.

## Где живёт

| Стратегия | Файл | Формула `trigger_time` |
|---|---|---|
| OBX4 | [strategies/obx4.py:268](../../../strategies/obx4.py#L268) | `c5.open_time + tf` |
| OB_HTF | [strategies/ob_htf.py:86,104](../../../strategies/ob_htf.py#L86) | `cur.open_time + tf` |
| RDRB | [strategies/rdrb.py:61](../../../strategies/rdrb.py#L61) | `trigger.open_time + tf` |
| FVG | [strategies/fvg.py:26](../../../strategies/fvg.py#L26) | `c2.open_time + tf` |
| HAMMER | [strategies/hammer.py:91,124](../../../strategies/hammer.py#L91) | `nxt.open_time + tf` |
| MARUBOZU | [strategies/marubozu.py:52](../../../strategies/marubozu.py#L52) | `candle.open_time + tf` |
| FRACTAL | [strategies/fractal.py:62](../../../strategies/fractal.py#L62) | `(close_time - 1h).floor("h")` — спец-случай |

## Зачем

- **Согласованность.** Все стратегии говорят на одном языке времени.
- **Совместимо с фильтром `> trigger_time`** в `find_first_confirmation_in_zone`
  ([ob1h_core.py:232](../../../strategies/ob1h_core.py#L232)) — ищем 1h-подтверждение
  строго после закрытия HTF-свечи паттерна, не во время её формирования.
- **Совместимо с UTC-границей дня** в `_prefill_today_signals`
  ([scanner.py:106](../../../scanner.py#L106)) — `trigger_time >= today_start`
  отбирает зоны, чьё закрытие пришлось на сегодня.

## Особый случай — FRACTAL

У s4 паттерн «снятие» в принципе занимает несколько свечей старшего ТФ, поэтому время
«открытия зоны» округляется по часу: `(close_time - 1h).floor("h")`. Это сознательное
исключение, см. [[s4 снятие фрактала]].

## Связано

- [[s1 obx4 + ob1h]], [[s2 ob htf + ob1h]], [[s3 rdrb + ob1h]], [[s4 снятие фрактала]],
  [[s5 fvg + ob1h]], [[hammer молот плюс фрактал плюс ob]], [[marubozu тело 95 процентов]]
- [[главное правило ob только на последней закрытой 1h]]
