---
name: btc-data-1m-csv
description: Локальные 1m OHLCV CSV для BTC/ETH/SOL за ~6 лет в ~/traid-bot/data/
metadata: 
  node_type: memory
  type: reference
  originSessionId: 3cacc97d-b7e5-4c77-9746-69e316174b22
---

# BTC 1m данные

Локальные CSV с 1m OHLCV свечами для основных пар, ~6 лет истории. Использовать вместо Binance API для бэктестов / поиска паттернов — независимо от API-лимитов и быстрее на больших окнах.

## Расположение

```
~/traid-bot/data/
  BTCUSDT_1m_vic_vadim.csv    224MB   3 181 965 строк
  ETHUSDT_1m_vic_vadim.csv    210MB
  SOLUSDT_1m_vic_vadim.csv    182MB
  BTCUSDT_15m_vic_vadim.csv    15MB   (уже агрегировано)
```

## Формат

CSV с заголовком: `open_time,open,high,low,close,volume`

- `open_time` — ISO UTC с tz-суффиксом, e.g. `2020-05-01 00:00:00+00:00`
- Цены float, volume float
- Шаг 1 минута

## Покрытие

BTC: 2020-05-01 00:00 UTC → актуальная свежесть зависит от того, когда последний раз запускался `update_btc_1m_csv.py`. По состоянию на 2026-05-23 18:25 UTC — ≈ 6 лет 23 дня.

## Обновление

`~/smc-lib/scripts/update_btc_1m_csv.py` — догоняет недостающие 1m свечи с Binance API.
- Без флагов = dry-run (показывает что будет добавлено).
- С флагом `--apply` = дозаписывает в конец CSV.
- Проверяет отсутствие gap'ов и дубликатов перед записью.

## Использование

Для агрегации в HTF (1h, 4h и т.д.) — группировать по `open_time` с шагом N минут:
- 1h = 60 минут, open = первая, close = последняя, high = max, low = min

Для совместимости с `~/smc-lib`: построить список `Candle(open, high, low, close, open_time_ms)`.

Свежесть данных может отставать на несколько дней — для самых свежих свечей использовать Binance API (см. примеры в `~/smc-lib/scripts/find_*.py`).

Связано: [[smc-lib-location]], [[i-rdrb-v1-pattern]].
