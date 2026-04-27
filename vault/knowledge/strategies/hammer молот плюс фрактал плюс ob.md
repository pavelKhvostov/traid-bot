---
tags: [strategy, hammer]
date: 2026-04-27
related: [[фракталы билла уильямса]], [[что такое order block]], [[три типа подтверждения 1h ob fvg rdrb]]
---

# HAMMER — молот + LL/HH-фрактал + OB-связка

## Идея

Стратегия работает только когда **три условия совпали в одной свече**:

1. Свеча — **молот** (классический или перевёрнутый) по геометрии.
2. Эта же свеча — фрактал (LL для LONG, HH для SHORT).
3. **Следующая свеча** образует с молотом OB-связку.

## Геометрия молота

[strategies/hammer.py:11-14](../../../strategies/hammer.py#L11-L14):

- `body_ratio = body / range` ≤ **0.30** (тело ≤ 30% диапазона)
- длинный фитиль ≥ **2.0 ×** body
- короткий фитиль ≤ **0.30 ×** body

Доджи (body == 0) и пустые свечи (range == 0) игнорируются.

## Фрактал

LL/HH по i±2 (см. [[фракталы билла уильямса]]). Без фрактала молот не считается.

## OB-связка со следующей свечой

LONG: `nxt.close > cur.open` (зелёная закрылась выше открытия молота).
SHORT: `nxt.close < cur.open`.

## Зона

[hammer.py:79-81](../../../strategies/hammer.py#L79-L81):

- LONG: `zone_bottom = min(cur.low, nxt.low)`, `zone_top = cur.open`
- SHORT: `zone_bottom = cur.open`, `zone_top = max(cur.high, nxt.high)`

`trigger_time = nxt.open_time + tf` ([[trigger_time равен open_time плюс tf]]) — то есть
закрытие следующей свечи.

## Триггер младшего ТФ

1h, через [[три типа подтверждения 1h ob fvg rdrb]]. Подтверждение засчитывается только
если `confirm_time == последняя_закрытая_1h_свеча`.

## Источник в коде

- [strategies/hammer.py](../../../strategies/hammer.py)
- Подтверждение: `ob1h_core.find_first_confirmation_in_zone`

## Связи

- [[фракталы билла уильямса]]
- [[что такое order block]]
- [[три типа подтверждения 1h ob fvg rdrb]]
