---
tags: [decision, phase-1, bootstrap, persistence]
date: 2026-04-23
phase: 1
decision-id: D-11
status: locked
---

# Bootstrap order — синхронный и блокирующий

## Решение

**Порядок старта бота (D-11):**

```
load state/*.json → delta-fetch candles → lookback rebuild (on_htf_close для всех стратегий)
→ start WebSocket → asyncio.gather(ws_loop, telegram_polling)
```

WebSocket стартует **только** после полного завершения rebuild. Если rebuild упал
(битый JSON, network timeout на delta-fetch, ошибка в `S1Runner.on_htf_close`) —
процесс делает `sys.exit(non-zero)`, **НЕ** стартует в partial state.

## Зачем

Без этого — **race condition**: live 1h-свеча может прилететь для ещё не восстановленной
зоны (например, OBx4 на 4h, который мы ещё не дочитали lookback'ом), и `S1Runner.check_active_zones`
не найдёт её → потерянный сигнал.

## Альтернативы и почему отвергнуты

| Альтернатива | Почему нет |
|---|---|
| Async rebuild + start WS параллельно | Race condition (см. выше) |
| Partial start при ошибке JSON | Тихая потеря зон — хуже, чем alert «бот не поднимается» |
| Retry rebuild до успеха | Скрывает реальную проблему (битый JSON → нужна диагностика, не цикл) |

## Принцип

**«Лучше alert `бот не поднимается` чем молча генерировать сигналы с потерянными зонами.»**
NFR-2.3 «никогда не теряем зону» — это в том числе про startup, не только про shutdown.

## Где живёт

- `src/main.py` — sync order (PLAN 07 task 07.1)
- `tests/test_main_bootstrap_order.py` — unit-тест на последовательность вызовов (PLAN 07 task 07.3)
- Manual verification: битый `state/active_zones.json` → запуск → `sys.exit(2)` (VALIDATION.md)

## Связано

- [[правило первого OB после возврата]] — shared модуль `_shared/zone_first_ob.py`
- NFR-2.3 в REQUIREMENTS.md
- RESEARCH §Q10 (bootstrap order в src/main.py)
- RESEARCH §Q12 (risk: live race window после WS reconnect — закрыт расширением
  `_delta_fetch_after_reconnect` вызовом `lookback_rebuild`)
