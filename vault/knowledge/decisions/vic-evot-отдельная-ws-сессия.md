---
tags: [decision, vic-evot, architecture, scanner]
date: 2026-04-27
status: locked
---

# VIC_EVOT — отдельная WS-сессия вместо расширения TIMEFRAMES_NATIVE

## Решение

Стратегия VIC_EVOT (8-я в проекте) живёт в собственном `VicScanner`
([vic_scanner.py](../../../vic_scanner.py)) с отдельной WS-подпиской на
`SYMBOLS × VIC_NATIVE_TFS = ["1m", "15m", "1d"]`. Существующий `Scanner`
[scanner.py](../../../scanner.py) и `TIMEFRAMES_NATIVE`
[config.py:11](../../../config.py#L11) **не изменены**.

## Где живёт в коде

- `config.py`: добавлены `VIC_TFS = ["1d"]`, `VIC_NATIVE_TFS = ["1m", "15m", "1d"]`,
  `VIC_1M_LOOKBACK_DAYS = 3`, `VIC_15M_LOOKBACK_DAYS = 7`. `TIMEFRAMES_NATIVE`
  без изменений.
- `vic_scanner.py`: класс `VicScanner` с методами `startup`, `_bootstrap_recent`,
  `_prefill_vic_levels`, `on_closed_1d`, `on_closed_15m`, `ws_loop`.
- `main.py`: `asyncio.gather(scanner.ws_loop(), vic_scanner.ws_loop(), polling_loop())`.
  `vic_scanner.startup()` вызывается ДО `scanner.startup()`.

## Что предписывала spec

[[vic_evot]] §7 одной строкой:

> `config.py` — `TIMEFRAMES_NATIVE += ["1m", "15m"]`, `VIC_TFS = ["1d"]`

Буквально интерпретируя: 1m и 15m добавляются в общий список, существующий
`Scanner` тоже подписывается на них через `_stream_names`
([scanner.py:255-260](../../../scanner.py#L255-L260)).

## Зачем отклонились

### 1. Bootstrap-trap для 1m

`Scanner.startup` итерирует `TIMEFRAMES_NATIVE` и зовёт `update_df_incrementally`
для каждой пары (symbol, tf). При **пустом CSV** функция падает в
`fetch_full_history`, который начинает фетч от `HISTORY_START_DATE = "2022-01-01"`
([data_manager.py:144-145](../../../data_manager.py#L144-L145)).

Для 1m это:
- 4+ года × 525 600 свечей/год × 3 символа ≈ 6.3 млн свечей
- Binance limit 1000 свечей/запрос → **~6300 REST-вызовов**
- При sleep 0.15s между батчами ([data_manager.py:114](../../../data_manager.py#L114))
  это **~16 минут** на одни только 1m-данные при первом запуске
- VIC нужны только последние 1-2 дня 1m для расчёта maxV(D-1) — остальные
  6.3 млн свечей бесполезны, занимают сотни МБ диска

### 2. Дубль REST-апдейтов на каждом close

Если 1m в `TIMEFRAMES_NATIVE`, существующий `Scanner.ws_loop` ловит каждый
close 1m-свечи и зовёт `update_df_incrementally` ([scanner.py:285-286](../../../scanner.py#L285-L286)),
ровно как и `VicScanner.ws_loop`. Это два REST-вызова к Binance на каждый
close 1m свечи:

- 1440 closes/сутки × 3 символа = 4320 closes
- × 2 (Scanner + VicScanner) = **+4320 дублирующих REST/сутки**
- + аналогично для 15m: +96×3×2 = 576 дублей
- Binance rate-limit (1200 запросов/мин) выдержит, но это пустая трата
  ресурса и зашумление логов

### 3. Семантическое разделение ответственности

Существующий `Scanner` = «1h-конфирмационный движок для 7 стратегий с зонами».
Логика prefill, full_rescan на 1h, dispatch через `STRATEGY_MAP` — заточена
под этот контракт. Подписка на 1m/15m не несёт для него никакой пользы:
после `tf in applicable_tfs` фильтра ([scanner.py:162](../../../scanner.py#L162))
закрытия 1m/15m игнорируются.

`VicScanner` = «15m-конфирмационный движок для одной стратегии VIC_EVOT с
уровнями». У него своя логика, свои dependency (1m свечи для maxV-расчёта,
15m для детекта, 1d как контекст направления). Изоляция упрощает
рассуждение.

## Альтернативы, которые отбросили

| Альтернатива | Почему отбросили |
|---|---|
| Буквально `TIMEFRAMES_NATIVE += ["1m", "15m"]` без правок в `Scanner` | Bootstrap-trap (1) и дубли REST (2). |
| `TIMEFRAMES_NATIVE += [...]` + правка `Scanner.startup` (новый `BOOTSTRAP_TFS = TIMEFRAMES_NATIVE - {"1m","15m"}`) | Решает только trap, дубли остаются. Плюс правка `scanner.py` ради VIC — нарушение принципа изоляции. |
| Один общий WS, `VicScanner` как callback в `Scanner` | Spec §7 явно сказала «два scanner-а в `gather`» — выбран именно distributed, не shared. |
| 1m данные через REST batch на каждом close 1d (без WS-подписки на 1m) | Концептуально проще, но spec упомянула 1m как `TIMEFRAMES_NATIVE` — это намёк на streaming. WS даёт «свежий» 1m моментально, REST batch добавил бы латенцию ~3 сек на close 1d. |

## Что осталось

- 1d входит в **обе** WS-подписки (`TIMEFRAMES_NATIVE` уже содержит "1d", и
  `VIC_NATIVE_TFS` — тоже). На каждом close 1d оба сканера дёргают
  `update_df_incrementally`. Это **раз в сутки**, дубль тривиален.
- Bootstrap-helper `_bootstrap_recent` в `VicScanner` дублирует логику
  `update_df_incrementally`, но с ограниченным горизонтом. Возможный
  рефактор: вынести в `data_manager.update_df_with_horizon(symbol, tf,
  lookback_days)` и переиспользовать. Не сделал — пока единственный
  потребитель.

## Связано

- [[vic_evot]] — spec, §7 описывает изначальное предписание
- [[2026-04-27-vic-evot-реализация]] — сессия с полным контекстом отклонения
- [[архитектура проекта flat layout]] — общий принцип flat-layout без `src/`
- [[главное правило ob только на последней закрытой 1h]] — аналог
  «live-правила» для 1h-стратегий; в VIC то же правило, но для 15m
