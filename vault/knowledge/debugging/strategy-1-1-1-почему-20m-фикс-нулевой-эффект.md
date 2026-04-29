---
tags: [debugging, look-ahead, strategy_1_1_1, defensive-fix]
date: 2026-04-29
status: resolved
related: [[strategy-1-1-1-look-ahead-15min-vs-tf_duration]]
---

# Strategy 1.1.1: почему фикс 20m look-ahead дал нулевой эффект на 3y

## Smoke-test результат

После фикса хардкода `+15min` → `+tf_minutes` прогон 3y BTC показал:
30 20m сигналов, 0 outcome'ов изменилось.

## Математика — fill внутри c2 невозможен

Entry в Strategy 1.1.1 = **середина FVG** (`(bottom+top)/2`).

Для **LONG FVG**: `high(c0) < low(c2)` (определение FVG). Тогда:

```
entry = (high(c0) + low(c2)) / 2  <  low(c2)
```

Fill срабатывает на 1m свече `bar` если `bar.low ≤ entry`. Внутри 20m
c2 свечи живут 20 1m баров; их минимальный low по построению равен
`low(c2)`. То есть **все** 1m баров внутри c2 имеют low ≥ low(c2) > entry.
**Fill физически невозможен внутри c2.**

Симметрично для SHORT FVG: `entry > high(c2)`, ни один 1m бар внутри c2
не имеет high ≥ entry.

## Вывод — фикс защитный

Look-ahead был **теоретическим, не практическим** в текущей геометрии
mid-of-FVG entry. Фикс остаётся правильным:

- Защищает от регрессий, если entry сменится (80% FVG, 100% FVG-bottom,
  и т.п. — для них fill внутри c2 становится возможным).
- Снимает yellow flag из backtest-auditor чек-листа.
- Делает код самодокументируемым (`tf_minutes` явно выводится из сигнала).

## Что это НЕ объясняет

«Магический» WR 64.2% из первичного 3y прогона — НЕ был артефактом 20m
look-ahead'а. Реальная причина WR где-то ещё: 6h macro path (44% сигналов),
2026-год эффект, или дубли путей через одну entry FVG (адресуется в Фазе 2
дедупом).

## Связано

- [[strategy-1-1-1-look-ahead-15min-vs-tf_duration]] — родительская заметка
  про сам look-ahead
- [[known-pitfalls]] — пункт 8 (фикс остаётся защитным правилом)
