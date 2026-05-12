---
tags: [session, strategy_1_1_7, fractal, sweep, research]
date: 2026-05-12
related: [[strategy_1_1_7]], [[фракталы билла уильямса]], [[s4 снятие фрактала]]
---

# 2026-05-12 — Strategy 1.1.7: Fractal sweep + 1h confirmation + OB + FVG

Новая ветка к 1.1.x family. Top-структура — **снятие 4h-фрактала**
(вместо OB или FVG).

## Каскад

```
4h фрактал LL/HH (Bill Williams i±2)
  └── свеча-снятие 4h (sweep):
        - low < FL.low AND close > FL.low  (LONG; зеркально для HH)
        - первая такая после i+2
        └── POI = [sweep.low, min(sweep.open, sweep.close)]  (для FL)
              └── 8h окно от sweep_close: проверка что sweep сам стал фракталом
                    └── На 1h ищем (logical flow):
                          1. confirmation = первая 1h с close > POI.top (LONG)
                          2. invalidation = первая 1h с close < POI.bottom
                             — если случилась РАНЬШЕ confirmation → цепочка мертва
                          3. После confirmation ищем OB-1h/2h внутри POI до invalidation
                          4. Внутри OB ищем FVG-15m/20m
                                entry = mid FVG
                                SL    = OB.bottom (LONG) / OB.top (SHORT)
                                TP    = entry ± risk × 1.0
```

Все 4 (ob_tf × fvg_tf) комбинации earliest-wins по close-time.

## Эволюция спеки (с долгим discovery process)

Понимание правильной логики **confirmation vs invalidation** заняло несколько
итераций. Я последовательно ошибался:

1. **v1**: Окно поиска OB = 8h после sweep_close (включая всё подряд внутри).
   Не нашли цепочку 15-апр-26 потому что OB образовался через 14h после
   sweep_close (вне 8h).

2. **v2**: «8h окно = только проверка stayed_fractal, дальше всё без верхней
   границы». Получили склейки старых фракталов с FVG из других лет (баг
   2026-03-05 = FVG 2026 + OB 2024).

3. **v3**: Добавил окно FVG = ob.cur_close + 24h. Меньше склеек, но edge
   слабый.

4. **v4**: Пользователь сказал «зона невалидна как только 1h close выше
   зоны». Реализовал — но это убило 99% цепочек, потому что после sweep
   цена ВСЕГДА сначала уходит выше POI (это нормальное поведение реверса).

5. **v5 (правильная)**: Пользователь объяснил что **закреп и инвалидация —
   на противоположных границах POI**.
   - LONG: confirmation = close > POI.top (мы ЖДЁМ этого, это реверс).
   - LONG: invalidation = close < POI.bottom (ниже sweep.low — реверс
     провален, цена пошла НИЖЕ ловушки).
   - После confirmation ждём возврат в POI → OB внутри POI до invalidation.

Урок — у меня было подозрение что «закреп» и «инвалидация» — это одно
событие. Стоило задать вопрос явно на этапе спеки, до кодирования.

## Backtest 3y BTC raw RR=1.0 (финальная логика)

| Метрика | Значение |
|---|---|
| Raw | 286 |
| Deduped | 220 |
| Closed | 76 (W=40, L=36) |
| NO_ENTRY | 144 (65%) |
| NOT_FILLED | 0 |
| **WR** | **52.6%** |
| **PnL** | **+4R** |
| **R/trade** | **+0.053** |

**Воронка:**
- 1878 фракталов 4h на 3y
- 917 sweep candles (50%)
- 554 stayed_fractal (60% sweep'ов)
- 520 confirmed (94% stayed → закреп выше POI)
- 34 poi_eaten (закрепились ниже POI = реверс провален)
- 286 raw signals (есть OB + FVG до invalidation)

**LONG vs SHORT:** LONG лучше — 116 deduped, WR 55.8%, +5R.
SHORT — 104 deduped, WR 48.5%, −1R.

**По годам:**
- 2023: WR 55%, +2R
- 2024: WR 46%, −2R
- 2025: WR 62.5%, **+6R**
- 2026: WR 33%, −2R (только 6 closed)

**Распределение TF:** OB-1h+FVG-15m доминирует (132/220 = 60%).

## Решение

**Research-only.** Edge есть, но слабый (R/tr +0.053). Не в live до:
- RR-кривой (RR=2 может вытащить из 65% NO_ENTRY)
- Анализа почему SHORT слабее LONG
- Возможно entry на ближний край FVG (как 1.1.5) для уменьшения NO_ENTRY

## Файлы

**Созданы:**
- `strategies/strategy_1_1_7.py` (~370 строк)
- `tests/test_strategy_1_1_7.py` (7 smoke-тестов)
- `research/1_1_7/backtest/backtest_strategy_1_1_7.py`
- `research/1_1_7/preview/preview_1_1_7.py`
- этот session note

Все 92 теста зелёные (85 + 7 новых). Коммит в ветке `strategy-1-1-7-fractal-sweep`.

## Pitfall — `confirmation` vs `invalidation` на разных границах POI

Записан как [[fractal-sweep-confirmation-vs-invalidation-borders]]:
- LONG **закреп** = close > POI.**top** (ждём, это хорошо)
- LONG **инвалидация** = close < POI.**bottom** (плохо, реверс провален)
- Если перепутать — детектор отсекает почти все валидные цепочки.

## Связи

- [[strategy_1_1_7]] — спецификация
- [[фракталы билла уильямса]] — canon определения
- [[s4 снятие фрактала]] — старая live-стратегия с тем же примитивом
- [[strategy_1_1_5]] — параллельная research-ветка (RDRB-4 htf)
