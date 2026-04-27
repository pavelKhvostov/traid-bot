---
tags: [architecture, csv, data]
date: 2026-04-27
---

# Структура CSV

## Файлы

`data/<SYMBOL>_<TF>.csv` — например `data/BTCUSDT_1h.csv`, `data/ETHUSDT_3d.csv`.

`SYMBOL ∈ {BTCUSDT, ETHUSDT, SOLUSDT}` (см. [[почему только btc eth sol]]).

`TF ∈ TIMEFRAMES_NATIVE ∪ TIMEFRAMES_COMPOSED.keys()`:

```python
TIMEFRAMES_NATIVE   = ["1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d"]
TIMEFRAMES_COMPOSED = {"3h": "1h", "2d": "1d"}
```

## Колонки (после `to_ref_format`)

`Open time | Open | High | Low | Close | Volume | Close time?`

- `Open time` — timezone-aware UTC datetime, **первичный ключ строки**.
- `Open/High/Low/Close/Volume` — float, NaN-строки отбрасываются.
- Сортировка по `Open time` ↑, дубликаты удаляются (`keep="last"`).

В файлах на диске встречается lowercase-формат с `DatetimeIndex` (`open_time` в индексе);
адаптер `strategies.obx4.to_ref_format` приводит к Capitalized + колонке.

## Native vs Composed

- **Native** ТФ (`1h, 2h, 4h, ...`) скачиваются с Binance напрямую через
  `update_df_incrementally`.
- **Composed** ТФ (`3h, 2d`) собираются из базовых через `compose_from_base`
  ([data_manager.py](../../../data_manager.py)) с `pandas.resample(rule, origin="epoch")`.
  Lowercase-частоты (`"3h"`, `"2d"`) — обязательны (см. [[pandas-frequency-lowercase]]).

## Точки записи

- `data_manager.update_df_incrementally(symbol, tf)` — натив, инкремент после WS-закрытия.
- `data_manager.save_df(df, symbol, tf)` — composed после пересборки в
  `scanner._recompose` и в `Scanner.startup`.

## Лимиты

- Объём: 3 символа × 10 ТФ × ~100k свечей ≈ 300 МБ. Загружается в RAM целиком
  через `pd.read_csv` за 1-2 сек.
- Ротации/архивации нет — файл растёт линейно по времени.

## Источник истины

`.planning/codebase/STRUCTURE.md` — расположение файлов, naming.

## Связано

- [[архитектура проекта flat layout]]
- [[стек и зависимости]]
- [[почему csv а не postgres]]
- [[pandas-frequency-lowercase]]
