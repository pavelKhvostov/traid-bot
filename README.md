# 📊 Trading Signals Bot

Telegram-бот и бэктест-движок для 5 алгоритмических стратегий на спот-рынке Binance.
Детектит паттерны на старших таймфреймах, ждёт подтверждения через OB на 1h и
присылает сигналы в Telegram.

## 🎯 Что делает проект

Параллельно прогоняет 5 торговых стратегий по криптовалютам (BTC, ETH, SOL)
на таймфреймах от 1h до 3d. Все стратегии работают по единой логике:

1. **На старшем ТФ** (2h..3d; OBX4 также 1h) детектируется специфичный паттерн,
   который формирует торговую зону `[zone_bottom, zone_top]` с направлением
   LONG или SHORT.
2. **На 1h** ждём возврата цены в эту зону.
3. В зоне ищется **первый OB 1h** (2-свечный реверс-паттерн) — это и есть
   торговый сигнал.
4. Если цена закрывается за пределы зоны — зона закрывается, сигнал не выдаётся.

## 🧠 Стратегии

| # | Стратегия | ТФ зон | Описание зоны |
|---|-----------|--------|---------------|
| 1 | **OBX4** ⚡ | 1h..3d | Общее пересечение тел 4 свечей OBX4-паттерна |
| 2 | **OB_HTF** 🟣 | 2h..3d | Диапазон `[Low, High]` prev-свечи 2-свечного реверса |
| 3 | **RDRB** ⚪ | 2h..3d | Диапазон якорной свечи (i-2) 3-свечного паттерна |
| 4 | **FRACTAL** 🔱 | 2h..3d | Фитиль свечи-снятия фрактала (i±2) |
| 5 | **FVG** 🎯 | 2h..3d | Границы Fair Value Gap (3-свечная конструкция) |

**OB 1h** — единый для всех стратегий паттерн подтверждения:
- **LONG:** `close[i-1] < open[i-1]` AND `close[i] > open[i-1]`
- **SHORT:** зеркально
- prev-свеча должна пересекать зону

## 📈 Результаты бэктеста (2022-01-01 → сегодня)

Прогон по 3 символам × 9-10 таймфреймам × 5 стратегий:

| Стратегия | Всего сигналов | BTC | ETH | SOL |
|-----------|----------------|-----|-----|-----|
| OBX4      | 547   | 187 | 185 | 175 |
| FVG       | 15687 | 5031 | 5315 | 5341 |
| OB_HTF    | 29194 | 9987 | 9746 | 9461 |
| RDRB      | 14372 | 4680 | 4757 | 4935 |
| FRACTAL   | 17089 | 5807 | 5765 | 5517 |

Дедупликация внутри одного `(symbol, source_tf, direction, ob1h_time)` —
при перекрывающихся зонах оставляется самая узкая.

## 🛠 Как запустить самому

### 1. Окружение

```bash
git clone https://github.com/<твой-username>/trading-signals-bot.git
cd trading-signals-bot
python3 -m venv venv
source venv/bin/activate         # Linux/Mac
# venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

### 2. Переменные окружения

Создай файл `.env` в корне проекта:

```
TELEGRAM_BOT_TOKEN=токен_от_@BotFather
ADMIN_CHAT_ID=твой_chat_id_от_@userinfobot
```

### 3. Бэктест по истории

Прогон всех 5 стратегий по 3 символам и 9-10 ТФ с 2022-01-01.
Первый запуск качает историю с Binance (5-10 минут), последующие — быстро:

```bash
python full_backtest_new.py
```

Результат: 5 CSV-файлов в `signals/`:
- `backtest_obx4.csv`
- `backtest_fvg.csv`
- `backtest_ob_htf.csv`
- `backtest_rdrb.csv`
- `backtest_fractal.csv`

### 4. HTML-отчёт

Интерактивная страница с фильтрами и ссылками в TradingView:

```bash
python generate_report.py
```

Откроет `signals_report.html` в браузере. 5 вкладок, сортировка, пагинация,
кнопка "TV" для каждой строки.

### 5. Smoke-тесты отдельных стратегий

```bash
python smoke_test_obx4.py    # проверка OBX4 на BTCUSDT 4h
python smoke_test_fvg.py     # проверка FVG на BTCUSDT 4h
```

## 📂 Структура проекта

```
trading-signals-bot/
├── CLAUDE.md                  # контекст для AI-кодинга
├── README.md                  # этот файл
├── requirements.txt
├── .env                       # секреты (НЕ коммитится)
├── config.py                  # символы, ТФ, пути
├── data_manager.py            # загрузка+хранение свечей с Binance
├── state.py                   # users.json, sent_signals.json
├── telegram_bot.py            # отправка сообщений, /start /stop /status
├── strategies/
│   ├── base.py                # Signal, Zone, signal_key, format_telegram
│   ├── ob1h_core.py           # ОБЩЕЕ ЯДРО: find_first_ob1h_in_zone, dedup
│   ├── obx4.py                # детектор зон OBX4
│   ├── fvg.py                 # детектор зон FVG
│   ├── ob_htf.py              # детектор зон OB_HTF
│   ├── rdrb.py                # детектор зон RDRB
│   └── fractal.py             # детектор зон FRACTAL
├── full_backtest_new.py       # прогон всех 5 стратегий по истории
├── generate_report.py         # HTML-отчёт из CSV
├── smoke_test.py              # проверка базовой инфраструктуры
├── smoke_test_obx4.py         # smoke для OBX4
├── smoke_test_fvg.py          # smoke для FVG
└── reference/                 # оригинальные скрипты стратегий (для справки)
    ├── obx4_original.py
    ├── fvg_original.py
    ├── fractal_vasya_original.py
    └── rdrb_original.py
```

## 🏗 Архитектура

```
┌─────────────────────┐
│  data_manager.py    │  ← Binance REST + WebSocket, CSV-кэш
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  strategies/*.py    │  ← каждая стратегия: detect_zones(df, symbol, tf)
│  (5 детекторов зон) │     → list[Zone]
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│   ob1h_core.py      │  ← общее ядро:
│  (scan зон → OB-1h) │     scan_zones_to_signals(zones, df_1h)
└──────────┬──────────┘     → list[Signal] (с дедупом)
           │
           ▼
┌─────────────────────┐
│  telegram_bot.py    │  ← рассылка подписчикам
└─────────────────────┘
```

## 📊 Просмотр сигналов

HTML-отчёт (`signals_report.html`) открывается двойным кликом в любом браузере —
Python для просмотра не нужен. Внутри:

- 5 вкладок по стратегиям
- Фильтры: символ, таймфрейм, направление
- Сортировка по любой колонке
- Пагинация (100 строк/страница)
- Кнопка **TV** — открывает TradingView на нужном символе и ТФ
- Кнопка **📋** — копирует время сигнала в буфер (для `Alt+G` в TradingView)

## 🔧 Что ещё не готово

- [ ] `scanner.py` — главный live-цикл (WebSocket Binance → на закрытии свечи →
  прогон всех стратегий → дедуп → отправка в Telegram)
- [ ] `main.py` — точка входа для лайв-режима
- [ ] Фильтры шума на live (сейчас ~50 сигналов в день — много)

## 🛡 Технологии

- Python 3.13
- pandas 2.2.3 (обработка OHLC)
- requests (Binance REST)
- websockets (Binance WebSocket, для live)
- python-dotenv (конфиг)

Никаких БД, ORM, Docker — всё хранится в CSV и JSON, запускается одной командой.

## 📜 Источник данных

Binance Spot публичный API — **ключи не нужны**. Все свечи в UTC.
Обрабатываются только полностью закрытые бары.

---

**Автор:** Павел Хвостов
**Цель:** алгоритмическая торговля криптовалютами на спот-рынке Binance
