---
tags: [decision, bootstrap, archive, revised]
date: 2026-04-27
phase: 1
decision-id: D-11
status: revised
---

# Bootstrap order — пересмотрено: async без hard-exit

## Решение D-11 (исходное) было пересмотрено

Изначально (Phase 1, 2026-04-23) D-11 фиксировало строгий синхронный порядок:

```
load state/*.json → delta-fetch candles → lookback rebuild
→ start WebSocket → asyncio.gather(ws_loop, telegram_polling)
```

С `sys.exit(non-zero)` при любой ошибке rebuild и блокировкой WS до полного
восстановления зон через `S1Runner.on_htf_close`.

В реальной кодовой базе (flat layout, см. [[архитектура проекта flat layout]])
**ничего из этого не реализовано**: нет ни классов `S1Runner`, ни функции
`lookback_rebuild`, ни `sys.exit` на провал старта. Решение D-11 закрыто как
архивное.

## Что реально делает старт сегодня

[main.py:12-52](../../../main.py#L12-L52):

1. `load_dotenv()` через `config.py`, проверка `TELEGRAM_BOT_TOKEN`.
2. Разовая миграция: удаление `state/signals_today.json` (today-store отменён).
3. `Scanner().startup()` — см. ниже.
4. Уведомление админов (`send_message` через `requests`).
5. `asyncio.gather(scanner.ws_loop(), polling_loop())` — два корутина.

[scanner.py:52-67](../../../scanner.py#L52-L67) (`Scanner.startup`):

1. `update_df_incrementally(symbol, tf)` для всех native TF — догрузка свежих свечей.
2. `compose_from_base` для composed (3h, 2d).
3. `_prefill_today_signals` — маркирует сегодняшние подтверждения как sent
   (см. [[prefill silent при старте]]). **Никакого full lookback rebuild.**

В `ws_loop` ([scanner.py:267-291](../../../scanner.py#L267-L291)) — `try/except` с
реконнектом через `await asyncio.sleep(5)`. **Нет** `sys.exit` при дисконнекте.

## Почему async вместо sync — и почему hard-exit убран

- **Полностью асинхронный WebSocket.** `websockets.connect` живёт в event-loop;
  блокировать его синхронным rebuild означает либо переписывать всё в sync (потеря
  параллельной работы Telegram polling), либо тащить thread-pool вокруг каждого
  блокирующего вызова.
- **Hard-exit мешает реконнекту.** Бот должен переживать сетевые провалы и кратковременные
  ошибки Binance. `sys.exit` при первой проблеме = нерабочий бот в проде.
- **Reduced surface для race condition.** Без полного rebuild активных зон при старте
  риск «пропустить зону» решается иначе: `_prefill_today_signals` помечает уже отстрелившие
  сегодняшние сигналы, а на каждом закрытии 1h `full_rescan = (tf == "1h")`
  ([scanner.py:150](../../../scanner.py#L150)) пересканивает все source_tf за UTC-день.
  Свежие зоны переоткрываются естественным путём из CSV.

## Что осталось от исходного D-11 как принцип

- «Никогда не теряем зону» — реализовано через `mark_sent` с дедупом по ключу и
  `was_sent` проверку перед broadcast ([scanner.py:223](../../../scanner.py#L223)).
- Telegram polling и WS работают параллельно (`asyncio.gather`) — это сохранилось.

## Если когда-либо вернёмся к sync rebuild

Триггером пересмотра будет: подтверждённый case потери сигнала на старте, который
prefill-silent + full_rescan не покрывают. Пока такого не зафиксировано.

## Связано

- [[архитектура проекта flat layout]]
- [[prefill silent при старте]]
- [[главное правило ob только на последней закрытой 1h]]
- [[zone-lifecycle-no-ttl]] — D-09/D-10 актуальны
