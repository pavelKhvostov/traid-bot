---
tags: [decision, phase-1, zones, lifecycle]
date: 2026-04-23
phase: 1
decision-id: D-09, D-10
status: locked
---

# Zone lifecycle — без TTL, параллельные зоны независимы

## Решение

### D-09: WAITING-зона без TTL

Зона `status=WAITING` живёт **до явного INVALID** (close 1h за границей). Никаких автоматических
`EXPIRED` через N баров.

### D-10: Параллельные зоны на разных HTF одного символа независимы

Если `detect_obx4` дал зону на 4h и зону на 12h с пересекающимися границами — **обе**
продолжают работать. Могут стрельнуть два сигнала. Коллизий нет: `zone_id =
make_zone_id(strategy_id, symbol, origin_tf, created_at)` включает `origin_tf`.

## Зачем

MVP-упрощение. Реальная проблема (память, рост `active_zones`) не наблюдается — вернёмся
к TTL когда будет что оптимизировать.

## Trade-off

| Риск | Митигация |
|---|---|
| Бесконечный рост `active_zones` на трендах (bullish ралли → bullish зоны копятся) | Принят; пересмотр если `state/active_zones.json` станет > нескольких MB |
| Двойной алерт от 4h+12h одновременно | Принят; это не баг, а фича — разный TF-контекст для трейдера |

## Принцип

**Не оптимизировать то, что ещё не стало проблемой.** TTL + `EXPIRED` статус — отдельная
гипотеза на будущее, а не преждевременная сложность в MVP.

## Где живёт

- `src/strategies/s1_obx4_ob1h/runner.py` — `check_active_zones` не фильтрует по возрасту (PLAN 04)
- `src/strategies/_shared/zone_first_ob.py` — алгоритм не знает про TTL (PLAN 02)
- `tests/test_strategies/test_s1.py::test_s1_no_return` — 200+ свечей без возврата, зона
  остаётся WAITING (D-01 fixture)

## Deferred

- TTL для WAITING-зон (реализуем по факту реальной проблемы памяти)
- `ZoneStatus.EXPIRED` (отложен вместе с TTL)
- Dedup по пересечению границ (отвергнут в D-10 в пользу независимости)

## Связано

- `src/core/entities.py::make_zone_id` — детерминированный ID через `origin_tf`
- strategy-invariants §1 (state machine — 4 перехода, никаких `FIRED → WAITING`)
- strategy-invariants §5 (детерминированность ID)
