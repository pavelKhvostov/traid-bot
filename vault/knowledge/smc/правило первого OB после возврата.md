---
tags: [smc, rule, strategy-core]
date: 2026-04-22
related: [[s1 obx4 + ob1h]], [[s2 ob htf + ob1h]], [[s3 rdrb + ob1h]], [[s5 fvg + ob1h]]
---

# Правило первого OB после возврата

## Суть

Для четырёх стратегий с возвратом в зону (s1, s2, s3, s5) действует единое правило:
**засчитывается только ПЕРВЫЙ OB1h, сформировавшийся после того, как цена вернулась в зону старшего ТФ.**
Любой последующий OB в той же зоне — игнорируется.

## Алгоритм (псевдокод)

```
zone = создана из паттерна старшего ТФ (OBx4 / OB / RDRB / FVG)
на каждой закрытой 1h свече после c5_time (или время создания зоны):
    if zone.status != WAITING and zone.status != RETURNED:
        skip
    
    # 1. Проверка пробоя зоны закрытием
    if zone.direction == BULLISH and candle.close < zone.bottom:
        zone.status = INVALID
        return
    if zone.direction == BEARISH and candle.close > zone.top:
        zone.status = INVALID
        return
    
    # 2. Возврат в зону (касание)
    if zone.status == WAITING and candle crosses [zone.bottom, zone.top]:
        zone.status = RETURNED
    
    # 3. Попытка собрать OB на паре (prev_candle, current_candle)
    if zone.status == RETURNED and есть prev_candle, который пересекает зону:
        if zone.direction == BULLISH:
            if prev.close < prev.open and current.close > prev.open:
                FIRE SIGNAL
                zone.status = FIRED
                return    # ← критично: выход после первого OB
        elif zone.direction == BEARISH:
            if prev.close > prev.open and current.close < prev.open:
                FIRE SIGNAL
                zone.status = FIRED
                return
```

## Почему именно первый

- **Снижает ложные срабатывания.** В зоне цена часто качается туда-обратно: второй, третий OB
  часто срабатывает уже после того, как trend-следящие участники вышли — RR деградирует.
- **Совпадает с методологией школы "Smart Money Concepts".** Институциональный ордер обычно исполняется
  при первом тесте зоны; последующие тесты — retail-шум.
- **Упрощает учёт дублей.** `zone_id` → `FIRED` → зона удалена. Нет вопроса "это новый сигнал или повтор?".

## Источник истины в коде

`obxxx.py:find_ob1h_in_obx4_zone` — эталонная реализация. В новом проекте переезжает в
`src/strategies/_shared/zone_first_ob.py` и переиспользуется всеми четырьмя стратегиями.

## Что НЕ попадает под это правило

- **s4 (снятие фрактала)** — там нет зоны и возврата, событие атомарное (одна свеча, снявшая фрактал).

## Типичные ошибки, которых избегаем

1. ❌ Искать OB не "первый после возврата", а "любой в зоне" — сломается логика, сигналов будет в 3-5 раз больше.
2. ❌ Начинать поиск ДО возврата в зону — детектор будет срабатывать на OB вдали от зоны.
3. ❌ Не проверять, что `prev_candle` тоже пересекает зону — OB-свеча (прев) должна быть в зоне, иначе это OB где-то в стороне.
4. ❌ Не проверять пробой закрытием — цена может уйти далеко за зону и долго там находиться, а зона "висит" активной.

## Связи

- Применяется в [[s1 obx4 + ob1h]]
- Применяется в [[s2 ob htf + ob1h]]
- Применяется в [[s3 rdrb + ob1h]]
- Применяется в [[s5 fvg + ob1h]]
- Основа для детектора [[что такое order block]]
