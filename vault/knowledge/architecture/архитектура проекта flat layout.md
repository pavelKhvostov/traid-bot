---
tags: [architecture, layout]
date: 2026-04-27
---

# Архитектура проекта — flat layout

## Что это

Все модули лежат **в корне репозитория**, без `src/`-обёртки. Импорты — относительно
рабочей директории, точка входа `python -m main` (или `python main.py`).

## Структура

```
trading-signals-bot/
├── main.py                # точка входа: startup → ws_loop + polling_loop
├── scanner.py             # WS-цикл, диспатч стратегий, prefill_silent, full_rescan на 1h
├── data_manager.py        # fetch_klines, update_df_incrementally, compose_from_base, CSV I/O
├── state.py               # sent_signals, users, last_signal, log_event
├── telegram_bot.py        # send_message, broadcast_signal, polling_loop
├── config.py              # SYMBOLS, TIMEFRAMES_NATIVE, TIMEFRAMES_COMPOSED, TELEGRAM_BOT_TOKEN
├── strategies/
│   ├── base.py            # dataclass Zone, Signal
│   ├── obx4.py            # OBx4 паттерн + to_ref_format адаптер
│   ├── fvg.py             # FVG зоны
│   ├── ob_htf.py          # OB на старшем ТФ + FVG-4h фильтр
│   ├── rdrb.py            # RDRB зоны
│   ├── fractal.py         # снятие фрактала
│   ├── hammer.py          # молот + фрактал + OB-связка
│   ├── marubozu.py        # тело ≥ 95% диапазона
│   └── ob1h_core.py       # find_first_confirmation_in_zone (3 типа), scan_zones_to_signals
├── data/<SYMBOL>_<TF>.csv # OHLCV кэш
├── state/                 # sent_signals.json, users.json, admins.json, last_signal.json
└── signals/               # backtest-выгрузки
```

## Что **не сложилось** vs первоначальный план

Первоначально планировалась `src/`-архитектура с:
- `src/detectors/`, `src/strategies/_shared/zone_first_ob.py`, `src/main.py`
- классы `S1Runner`, `Orchestrator` с `on_htf_close` / `check_active_zones`
- sync bootstrap order с `sys.exit` при сбое (см. [[bootstrap-sync-hard-exit]])

В реальности проект пошёл прагматичнее: функции вместо классов-runner, общее ядро
`ob1h_core.py` вместо `_shared/zone_first_ob.py`, async-первый main без hard-exit.

## Поток исполнения

1. `main.main()` → `Scanner().startup()` догружает свежие свечи и делает prefill_silent
   ([[prefill silent при старте]]).
2. `asyncio.gather(scanner.ws_loop(), polling_loop())` — два корутина параллельно.
3. На каждой закрытой WS-свече `update_df_incrementally` сохраняет CSV, потом
   `on_closed_native_candle` пересобирает составные ТФ (3h, 2d) и диспатчит стратегии.
4. На закрытии 1h — `full_rescan` по всем source_tf в `STRATEGY_TFS = ["12h", "1d", "2d", "3d"]`.
5. Подтверждение проходит через [[главное правило ob только на последней закрытой 1h]] и
   [[три типа подтверждения 1h ob fvg rdrb]].

## Источник истины

Подробная карта — в `.planning/codebase/ARCHITECTURE.md` и `.planning/codebase/STRUCTURE.md`.
Эта заметка фиксирует только то, что **не выводится** из чтения файлов: причины именно
такой формы и связь с заброшенным планом `src/`.

## Связано

- [[стек и зависимости]]
- [[структура CSV]]
- [[bootstrap-sync-hard-exit]]
- [[почему csv а не postgres]]
