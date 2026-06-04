---
tags: [debugging, requests, proxy, binance]
date: 2026-06-03
---

# SOCKS-прокси блокирует Binance REST в python-requests

## Симптом

```
requests.exceptions.InvalidSchema: Missing dependencies for SOCKS support.
```

Возникает мгновенно при вызове `requests.get(BINANCE_KLINES_URL, ...)` в
`data_manager.fetch_klines_range()`. НЕ network error — ошибка ДО отправки.

## Причина

В системных env vars лежат прокси-настройки SOCKS5 (от VPN/другого приложения):
- `HTTP_PROXY=socks5://...`
- `HTTPS_PROXY=socks5://...`
- `ALL_PROXY=socks5://...`

Библиотека `requests` автоматически их подхватывает. SOCKS-прокси требует
дополнительной зависимости `pysocks` (через `requests[socks]`), которая
**не установлена в venv проекта**.

## Минимальное воспроизведение

```bash
$ python -c "
import os
os.environ['HTTPS_PROXY'] = 'socks5://127.0.0.1:1080'
import requests
requests.get('https://api.binance.com/api/v3/ping')
"
# requests.exceptions.InvalidSchema: Missing dependencies for SOCKS support.
```

## Правило избегания

Перед запуском любого скрипта, дёргающего Binance/REST:

```bash
NO_PROXY="*" HTTP_PROXY="" HTTPS_PROXY="" ALL_PROXY="" venv/Scripts/python.exe script.py
```

Или внутри скрипта (более надёжно):

```python
import os
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy']:
    os.environ.pop(k, None)
```

## Что НЕ делать

- ❌ Не ставить `pysocks` как фикс. Бот работает напрямую с `api.binance.com` —
  proxy не нужен. Установка `pysocks` решит ошибку, но запустит трафик через
  чужой SOCKS-сервер.
- ❌ Не править глобальные env vars Windows — другие программы (или сам пользователь)
  могут их использовать намеренно. Локальный override в subprocess безопаснее.

## Где встречается в проекте

- `data_manager.fetch_klines_range()` — bootstrap истории
- `data_manager.update_df_incrementally()` — догрузка свечей
- `data_manager.fetch_full_history()`
- `vic_levels.fetch_vic_d` (через session)

## История

- **2026-06-03** — впервые поймано при попытке докачать BTC 12h до текущего
  момента в сессии [[2026-06-03-bulkowski-12-reversal-detectors-etap-172]].
- Возможно, проявлялось и раньше при apt/pip install через subprocess
  (косвенный сигнал — install падал, пока не делали NO_PROXY=*).
