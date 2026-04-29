---
tags: [debugging, dedup, strategy_1_1_1, tolerance]
date: 2026-04-29
status: resolved
---

# Strategy 1.1.1: dedup tolerance через bucketing 0.5%, не через round()

## Что было

После Ф1 (SL=15%) на 3y BTC dedup давал 158 строк. Но 15 из них (9.5%)
были «почти-дубли» с дребезгом SL = 0.025-0.5% от entry. Семантически
это один трейд (≈один уровень входа), но dedup-ключ
`(signal_time, direction, entry, round(sl, 8))` требовал точного равенства SL.

## Первая попытка (НЕ работает)

```python
key = (signal_time, direction, round(entry, 8), round(sl/entry, 4))
```

Идея: округлить relative SL до 4 знаков (=0.01%). Думали — два значения
с diff 0.025% попадут в один bin.

**Результат:** 0 эффекта, deduped осталось 158.

**Почему не работает:** `round(x, N)` определяет **ширину bin** (0.0001 = 0.01%),
не **толерантность**. Два значения с diff 0.025% МОГУТ оказаться в РАЗНЫХ bins
если они на границе:
- `1.014959 → round → 1.0150`
- `1.015214 → round → 1.0152`
Diff 0.025% (= 0.00025), но попали в разные ячейки.

## Правильное решение — bucketing

Двухэтапный алгоритм:

**Этап 1.** Primary group по `(signal_time, direction, round(entry, 8))`.

**Этап 2.** Внутри primary-группы:
1. Сортируем по `sl` возрастающе.
2. Идём последовательно. Объединяем в текущий bucket пока:
   - `|sl_i - sl_first_in_bucket| / entry < SL_TOLERANCE` (0.005)
   - И `outcome совпадает с outcome первого в bucket'е`
3. Если хоть одно условие нарушено → начинаем новый bucket.

Условие на outcome — следствие правила «outcome разные = легитимные
разные трейды» (могут быть SL близкие но один win, другой loss).

## Реализация

[backtest_strategy_1_1_1.py:dedupe_signals](../../../backtest_strategy_1_1_1.py)
с константой `SL_TOLERANCE = 0.005`.

## Результаты на 3y BTC

| | round-based key | bucketing |
|---|---|---|
| deduped n | 158 | **144** |
| схлопнуто из 158 | 0 | 14 |
| WR (RR=1) | 63.9% | 61.7% |
| PnL (RR=1) | +43R | +33R |
| Кейс 2026-02-06 (diff 4.86%) | 2 строки ✓ | 2 строки ✓ |

После bucketing преимущественно схлопнулись winners (12W + 2L) —
объясняется, что почти-дубли «фарм» одной entry'е чаще выигрывали.

## Урок (правило избегания)

**`round(x, N)` = ширина bin, НЕ tolerance.** Для семантического
схлопывания близких значений нужен sort+merge с явным threshold:

```python
# Плохо: округление как «толерантность»
key = (..., round(value, N))

# Правильно: bucketing
sorted_items = sorted(items, key=lambda x: x['value'])
buckets = []
cur, first = [], None
for item in sorted_items:
    if first is None or abs(item['value'] - first) < THRESHOLD:
        cur.append(item)
        if first is None: first = item['value']
    else:
        buckets.append(cur)
        cur, first = [item], item['value']
if cur: buckets.append(cur)
```

Также: при объединении группы — обязательно проверять что критичные
для интерпретации поля совпадают (тут `outcome`); если нет → split,
это легитимно разные трейды.

## Связано

- [[strategy_1_1_1]] — spec
- [[strategy-1-1-1-разные-sl-на-одном-entry]] — кейс с реально разными SL
- [[strategy-1-1-1-sl-15-percent]] — почему дребезг возник
- [[known-pitfalls]] — кандидат на 9-й pitfall
