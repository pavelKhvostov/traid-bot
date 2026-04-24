# Code Review — Trading Signals Bot (snapshot)

Дата: 2026-04-24. Цель документа — зафиксировать текущее состояние live-стэка
и известные риски, чтобы следующая сессия не начиналась с нуля.

---

## Архитектура (как работает сейчас)

```
WS (24 stream: 3 symbols × 8 native tfs)
  └─ k["x"] == True  →  update_df_incrementally(symbol, tf)
                    →  on_closed_native_candle(symbol, tf)
                         ├─ если tf == "1h" → recompose 3h; full_rescan по всем стратегиям × source_tf, cutoff = today_start
                         ├─ если tf == "1d" → recompose 2d
                         └─ иначе → _dispatch_strategy(tf), cutoff = None (берётся последняя зона)

_dispatch_strategy(cutoff):
  detect_zones(df_htf, symbol, tf)
  if cutoff: фильтр zones[trigger_time >= cutoff]
  if not cutoff: берём только последнюю зону
  scan_zones_to_signals(zones, df_1h)  # ядро + дедуп по (sym, tf, dir, ob_time)
  last_1h_open = df_1h.iloc[-1]["Open time"]
  for s in signals:
      if ob_time != last_1h_open: skip              # ГЛАВНОЕ ПРАВИЛО
      if was_sent(key): skip
      broadcast_signal(sig_data); mark_sent; save_last_signal

startup():
  update_df_incrementally для всех symbol × NATIVE_TFS
  compose 3h, 2d
  _prefill_today_signals(): «тихий маркер» — проходит сегодняшние зоны за 48h,
    mark_sent без broadcast. Защита от повтора утренних сигналов.
```

Дедуп-ключ:
```
{strategy}|{symbol}|{source_tf}|{direction}|{ob1h_cur_time_iso}
```

---

## Состояние файлов

| Файл | Назначение | Статус |
|---|---|---|
| config.py | env, пути, admins.json | OK |
| data_manager.py | Binance REST, CSV, compose_from_base | OK, не трогался давно |
| state.py | users, sent_signals, last_signal, bot.log | OK, today-store удалён |
| telegram_bot.py | API, polling, reply/inline KB, команды | OK |
| scanner.py | live WS + dispatch + prefill | OK, самое активное место правок |
| main.py | bootstrap + asyncio.gather | OK |
| strategies/base.py | Signal/Zone, format, TV url | OK |
| strategies/ob1h_core.py | ядро find_first_ob1h_in_zone + dedup | OK |
| strategies/obx4.py | детектор + to_ref_format (общий адаптер) | OK |
| strategies/{fvg,ob_htf,rdrb,fractal}.py | детекторы зон | OK |
| full_backtest_new.py | offline прогон всех 5 стратегий → CSV | OK |
| generate_report.py | HTML-отчёт по CSV | OK |
| generate_dashboard.py | dashboard из state (users, sent, logs) | OK |

---

## Findings

### 🔴 Critical
_нет_

### 🟠 High

**H-1. `_prefill_today_signals` не вызывается повторно при пересечении UTC-полуночи.**
`startup()` зовёт его один раз. Если бот работает непрерывно через 00:00 UTC, «тихий маркер» за новый день не выполнится, и при рестарте позже в этот день все сегодняшние OB могут прийти повторно (они не в `sent_signals`, но главное правило `ob_time == last_1h_open` ограничит их одним — всё же риск ненужных рассылок при рестарте в середине дня).

**Митигация**: либо вызывать `_prefill_today_signals` раз в сутки, либо при рестарте после суток пустой `sent_signals` за сегодня — prefill сработает как нужно. Сейчас приемлемо, но стоит запланировать таймер «пересечение UTC-полуночи → re-prefill».

**H-2. `state.*` читает JSON на каждом вызове.**
`load_users`, `load_sent_signals`, `was_sent`, `mark_sent`, `save_users` — каждый раз читают файл целиком. При рассылке N подписчикам × K сигналов это O(N·K·|sent|) дисковых чтений. Пока подписчиков единицы, норм. При росте до сотен — заметит.

**Митигация**: кэш в памяти + write-through на изменение. Не срочно.

**H-3. Live-отправка блокирующая.**
`broadcast_signal` в `_dispatch_strategy` вызывается синхронно из `asyncio.to_thread(self.on_closed_native_candle, ...)`. Рассылка 100 подписчикам × 200 мс = 20 секунд. В это время scanner не обрабатывает новые WS-события (они копятся в очереди, не теряются — websockets буферизует).

**Митигация**: при росте аудитории вынести рассылку в отдельный воркер с очередью, или батчить в `aiohttp` с параллельными POST.

### 🟡 Medium

**M-1. `was_sent` race: два закрытия 1h+2h одновременно.**
Свечи 1h и 2h могут закрыться в одну секунду (на границе 02:00 UTC). `on_closed_native_candle(…, "1h")` и `… "2h"` будут крутиться параллельно в двух `to_thread`. Оба ядра могут найти один и тот же сигнал и до `mark_sent` пройти проверку `was_sent`. Результат — дубль.

**Митигация**: `threading.Lock` вокруг блока `was_sent → broadcast → mark_sent` в `_dispatch_strategy`. Оценка вероятности: низкая (1h полный rescan ловит только 1h-close, 2h-close идёт по одной стратегии × 2h), но не нулевая.

**M-2. `last_1h_open` из `df_1h.iloc[-1]`.**
Предполагает, что данные 1h уже догружены до этой свечи. `on_closed_native_candle` вызывается после `update_df_incrementally(symbol, tf)` — это обновляет только `tf`, НЕ обязательно `1h`. При закрытии 4h-свечи в 16:00 UTC в то же мгновение только что закрылась 1h (15:00–16:00), но её `update_df_incrementally` может прийти позже в другом WS-событии.

Последствие: `last_1h_open` = 15:00 (вчерашняя догрузка), а OB найден на 15:00 — совпадение. Но если 1h отстаёт на несколько часов (рестарт после простоя), `last_1h_open` устарел, и свежий OB может быть пропущен.

**Митигация**: в `on_closed_native_candle` добавить `update_df_incrementally(symbol, "1h")` перед чтением `df_1h`, если `tf != "1h"`. Не делать каждую свечу, только при 2h/4h и т.д.

**M-3. Reference-формат vs lowercase-формат.**
`to_ref_format` — адаптер lowercase+DatetimeIndex → Capitalized+"Open time". Используется почти везде, но легко забыть при добавлении нового пути. Полный переход на один формат снял бы класс багов.

**Митигация**: либо `load_df` всегда возвращает ref-формат, либо `data_manager` остаётся lowercase и все стратегии принимают lowercase (нужно будет переписать reference-код).

**M-4. `_prefill_today_signals` не re-scan-ит больше 48h назад.**
Если бот выключен >48h, часть зон из прошлого не попадёт в prefill, а её OB случится сегодня → сработает правило `ob_time == last_1h_open` → сигнал всё равно уйдёт корректно. Но prefill пометит меньше ключей — это OK, потому что «тихий маркер» и так не защищает от новых OB. Вывод: 48h хватает.

**M-5. `broadcast_signal` логирует warning про каждого заблокировавшего пользователя.**
При росте базы логи будут забиваться `send_message chat=… failed: Forbidden: bot was blocked`. Не критично, но стоит удалять таких из `users.json`.

**Митигация**: если `description` содержит "blocked" или "chat not found" — `remove_user(uid)` и `log_event("INFO", ...)`.

### 🟢 Low

**L-1. `_signal_payload` и `_sig_to_dict` дублируют поля.**
Разные форматы для `mark_sent` и для отправки — ок, но можно объединить.

**L-2. `to_ref_format` объявлена внутри `strategies/obx4.py`.**
Логично её вынести в `strategies/base.py` или `data_manager.py` — используется всеми детекторами и scanner-ом.

**L-3. Hardcoded `ping_interval=30, ping_timeout=15`.**
Binance WS работает стабильно при дефолтах. Норм.

**L-4. `update_df_incrementally` дергает Binance REST внутри `asyncio.to_thread`.**
Это sync-код с `time.sleep(0.15)` в цикле. Блокирует worker thread, а не event loop — OK.

**L-5. `generate_dashboard.py` читает `bot.log` целиком tail -1000.**
При ротации (5MB) норм. Можно оптимизировать через seek, но некритично.

**L-6. Нет graceful shutdown.**
При `Ctrl+C` WS закроется некорректно (без `ws.close()`), часть пакетов потеряется. Последствия: при рестарте `_prefill_today_signals` наверстает.

---

## Известные архитектурные инварианты

1. **Все времена UTC.** И в Binance, и в `data_manager`, и в state. Никаких локальных таймзон.
2. **Только закрытые свечи.** `k["x"] == True` — единственный триггер.
3. **Дедуп на уровне ключа**, не содержания. Один и тот же OB с разной `trigger_time` (широкая vs узкая зона) уже схлопнут в `scan_zones_to_signals` → `best` по минимальной ширине.
4. **Главное правило отправки**: `ob_time == df_1h.iloc[-1]["Open time"]`. Любой OB на старой 1h-свече — не отправляется.
5. **`prefill_silent` vs `live`**: prefill только пишет в `sent_signals`, live пишет `sent_signals + last_signal + broadcast`.
6. **Составные ТФ** (3h, 2d) пересобираются из 1h/1d через `compose_from_base` на каждом закрытии базового.
7. **`sent_signals.json` не чистится автоматически.** Растёт с временем. Нужен retention (например, удалять >30 дней) — TODO.

---

## Что НЕ надо менять без причины

- Математику стратегий в `strategies/*.py` (верифицирована против reference).
- `to_ref_format`, `_normalize_df` внутри obx4 — контракт детекторов зависит от этого.
- `ob1h_core.scan_zones_to_signals` — ядро дедупа.
- Формат ключа `was_sent`/`mark_sent` — сломает все предыдущие пометки.
- `signal_key` vs `_sig_key` в `scanner.py` — у `scanner._sig_key` другой формат, использует `meta["source_tf"]` вместо `timeframe`. Переименовать, чтобы не путать.

---

## TODO (приоритеты по следующей сессии)

1. **M-2**: перед `df_1h = load_df(symbol, "1h")` в `on_closed_native_candle` — `update_df_incrementally(symbol, "1h")` при `tf != "1h"`.
2. **H-1**: автоматический `_prefill_today_signals` на пересечении UTC-полуночи (asyncio-таймер).
3. **M-1**: `threading.Lock` вокруг критической секции в `_dispatch_strategy`.
4. **M-5**: авто-удаление заблокированных пользователей из `users.json`.
5. **Retention** для `sent_signals.json` (>30 дней убирать).
6. **Вынести `to_ref_format`** в `base.py` или `data_manager.py`.
7. **Graceful shutdown**: обработчик SIGTERM, `ws.close()`, финальный `log_event`.

---

## Verified behaviors (проверено)

- ✅ WS подключение к 24 стримам Binance Spot.
- ✅ `_prefill_today_signals` за 48h ≤ нескольких секунд.
- ✅ Главное правило `ob_time == last_1h_open` отсекает старые OB.
- ✅ Dedup по ключу в `scan_zones_to_signals`.
- ✅ HTML-формат сигнала: шапка + `<code>` блок с выравниванием.
- ✅ Inline-кнопка TradingView под каждым сигналом.
- ✅ Reply-клавиатура для подписчиков и неподписчиков.
- ✅ Admin-команды: `/users`, `/admin_add`, `/admin_remove`, `/broadcast`.
- ✅ Ротация `bot.log` > 5 MB.

## Not verified / не проверено

- ❓ Поведение при обрыве WS на 10+ минут (авто-reconnect работает, но сколько свечей пропускается?).
- ❓ Rate limit Telegram при >50 подписчиков.
- ❓ Поведение при заполнении диска (CSV + state + log).
- ❓ Корректность при рестарте ровно на границе UTC-дня.
