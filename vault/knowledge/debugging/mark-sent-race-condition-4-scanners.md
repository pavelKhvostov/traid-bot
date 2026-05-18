---
tags: [debugging, live-bot, race-condition, concurrency]
date: 2026-05-13
---

# mark_sent race condition при 4 concurrent scanners

## Что было

`state.mark_sent(key, payload)` без thread lock:

```python
def mark_sent(key: str, payload: dict) -> None:
    d = load_sent_signals()  # read
    d[key] = payload          # modify
    save_sent_signals(d)      # write
```

## Симптом

4 параллельных live-сканера (1.1.1 + 1.1.2 + 1.1.3 + 1.1.6) запускают `on_closed_1h(symbol)` через `asyncio.to_thread`. На 1h boundary часто все 4 одновременно вызывают `mark_sent`. Без lock:

1. Scanner A: load → d_A
2. Scanner B: load → d_B (same содержимое)
3. Scanner A: d_A[key_A] = payload_A, save
4. Scanner B: d_B[key_B] = payload_B, save → **затирает key_A**

Риск: потеря записей в `state/sent_signals.json`, повторные рассылки.

## Причина

`asyncio.to_thread` запускает в отдельных threads из ThreadPool. Multiple threads могут одновременно вызывать `mark_sent`. JSON-файл не atomic.

При single 1.1.1 scanner (старая архитектура) race window был малым (1 thread на 3 symbol BTC/ETH/SOL → 3 потенциальных concurrent). С 4 scanners это **12 потенциальных concurrent calls** на 1h boundary.

## Правило избегания

Любая функция в `state.py` которая делает read-modify-write на JSON файле — обязательно через `threading.Lock`:

```python
import threading as _threading
_SENT_LOCK = _threading.Lock()

def mark_sent(key, payload):
    with _SENT_LOCK:
        d = load_sent_signals()
        d[key] = payload
        save_sent_signals(d)
```

Альтернатива (более масштабируемая): `state/sent_signals.db` через SQLite с WAL mode. Текущий проект решил остаться на JSON ([[почему csv а не postgres]]).

## Fix (2026-05-13)

Добавлен `threading.Lock` в `state.py` вокруг `mark_sent`.

## Возможные продолжения проблем

- `save_last_signal` — также read-modify-write, может race. Менее критично (один файл, последний выигрывает).
- `save_users` — то же. Modify редок, но возможен race с команды /start.

Если появятся аналогичные симптомы — extend pattern с _LOCK на эти функции.

## Источник

[[2026-05-13-live-bot-vic-ifvg-strategies-117-118]] — session note

## Связи

- [[multi-scanner-current-hour-filter]] — другой live-bug этой же сессии
