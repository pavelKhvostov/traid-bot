---
tags: [debugging, requests, proxy, binance, environment]
date: 2026-06-11
---

# Binance REST: настройка прокси ЗАВИСИТ ОТ МАШИНЫ (VPS ≠ локальная Windows)

Дополняет/уточняет [[socks-proxy-блокирует-binance-rest]]. Оказалось, правило
«сбросить прокси перед Binance-фетчем» **верно только на VPS** и **активно ломает
локальную машину пользователя**.

## Две противоположные среды

### VPS (старый pitfall, 2026-06-03)
- В env лежат `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY=socks5://...` от другого софта.
- `pysocks` не стоит → `requests.get` падает **мгновенно**:
  `requests.exceptions.InvalidSchema: Missing dependencies for SOCKS support`.
- **Фикс:** снять proxy env (`os.environ.pop(...)`) / `NO_PROXY=*`. Прямой доступ к
  Binance работает.

### Локальная Windows-машина пользователя (этот pitfall, 2026-06-11)
- Binance (`api.binance.com`, `data-api.binance.vision`) доступен **ТОЛЬКО через
  системный прокси** (VPN, прописан в **реестре Windows**). `requests` подхватывает
  его автоматически через `urllib.request.getproxies()` — **хотя env-переменные
  HTTP_PROXY/etc ПУСТЫЕ** (`{k: os.environ.get(k)}` показывает `{}`).
- Если в скрипте стоит `os.environ["NO_PROXY"]="*"` → requests идёт **напрямую** →
  соединение/SSL-хэндшейк проходит, но **тело ответа не приходит** →
  `ReadTimeoutError`/`ConnectionError` после всех ретраев.

## Симптом-отличие
- VPS: мгновенный `InvalidSchema` (до отправки).
- Local: `ConnectionError: ... Read timed out` ПОСЛЕ серии ретраев (хэндшейк прошёл).

## Решающая диагностика
- Инлайн `venv/Scripts/python.exe -c "import requests; requests.get('https://data-api.binance.vision/api/v3/klines', params=...)"` — **РАБОТАЕТ** (берёт системный прокси).
- Тот же запрос из скрипта-файла, где наверху `os.environ['NO_PROXY']='*'` — **ПАДАЕТ**.
- Вывод: виноват не сеть/параметры, а отключение системного прокси.

## Две сопутствующие грабли (всплыли тут же)
1. **Фоновые Bash-задачи (sandbox) режут сеть.** `run_in_background: true` для
   Binance-фетча давал ConnectionError на первом же батче, а foreground — работал.
   Binance-фетч запускать в **foreground**.
2. **stdout Windows = cp1251.** `print` с `→`/кириллицей падает
   `UnicodeEncodeError: 'charmap' codec can't encode '→'`. Фикс:
   `sys.stdout.reconfigure(encoding="utf-8")` в начале скрипта.

## Правило избегания
**Сначала определи, на какой машине запускаешь.**
- На локальной Windows юзера: **НЕ трогать прокси** — дать requests взять системный.
  Не ставить `NO_PROXY`. Запускать в foreground. Ставить utf-8 на stdout.
- На VPS: сбрасывать proxy env как в старом pitfall.
- Универсальный быстрый тест перед фетчем: инлайн `requests.get(ping)` — если
  работает инлайн, но скрипт падает, ищи разницу в proxy-env/NO_PROXY скрипта.

## Где встретилось
- `research/elements_study/etap_196_fetch_taker_flow.py` — фетч taker-buy flow
  (BTC/ETH/SOL 1h+12h) для trend-continuation pullback study. После фикса —
  6 файлов скачаны успешно (`*_flow.csv`).
