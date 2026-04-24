# 📊 Trading Signals Bot

Telegram-бот, который ловит торговые сетапы на Binance Spot по 5 стратегиям
и отправляет сигналы подписчикам **в реальном времени** — только когда OB-1h
сформировался на свече, которая только что закрылась.

---

## 🎯 Что делает

- Слушает закрытие свечей Binance через WebSocket для **BTC, ETH, SOL** на ТФ
  `1h, 2h, 3h, 4h, 6h, 8h, 12h, 1d, 2d, 3d`.
- На каждой закрывшейся свече старшего ТФ ищет паттерны 5 стратегий и
  определяет торговую зону.
- На каждой закрывшейся 1h-свече проверяет, не сформировался ли в активной
  зоне `OB-1h` (Order Block).
- Отправляет сигнал в Telegram, если **OB-1h образовался именно на той 1h-свече,
  которая только что закрылась** (никаких "догоняющих" сигналов).
- Хранит дедуп в `state/sent_signals.json` — повторно тот же сигнал не уйдёт.

---

## 🧠 5 стратегий

| # | Стратегия | Иконка | ТФ зон | Описание |
|---|-----------|--------|--------|----------|
| 1 | **OBX4**    | ⚡ | 1h..3d | 4 свечи с чередованием цветов, FVG на 5-й |
| 2 | **FVG**     | 〰️ | 2h..3d | Fair Value Gap (3-свечный разрыв) |
| 3 | **OB_HTF**  | 📦 | 2h..3d | 2-свечный реверс на старшем ТФ |
| 4 | **RDRB**    | ↩️ | 2h..3d | 3-свечный пробой с возвратом |
| 5 | **FRACTAL** | ❄️ | 2h..3d | Снятие фрактала i±2 |

Подтверждение для всех — **OB-1h** на 1h-свече:
- LONG: `close[i-1] < open[i-1]` AND `close[i] > open[i-1]`
- SHORT: зеркально

---

## 🚀 Быстрый запуск

### 1. Клонировать и поставить зависимости

```bash
git clone https://github.com/pavelKhvostov/traid-bot.git trading-signals-bot
cd trading-signals-bot
python3 -m venv venv
source venv/bin/activate         # Linux/Mac
# venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

### 2. Создать Telegram-бота

1. Открой [@BotFather](https://t.me/BotFather), отправь `/newbot`, дай имя.
2. Получи токен вида `7891234567:AAH...`.
3. Узнай свой `chat_id` через [@userinfobot](https://t.me/userinfobot).

### 3. Настроить `.env`

В корне проекта создай файл `.env`:

```
TELEGRAM_BOT_TOKEN=сюда_токен_от_BotFather
```

### 4. Добавить себя в админы

```bash
mkdir -p state
echo '[ТВОЙ_CHAT_ID]' > state/admins.json
```

Например: `echo '[886807304]' > state/admins.json`

### 5. Подписаться на бота в Telegram

Открой своего бота в Telegram и нажми **/start**. Без этого бот не сможет
тебе писать.

### 6. Запустить

```bash
python main.py
```

Старт за 30-60 секунд: догрузка свежих свечей с Binance + `prefill_silent`
(маркирует сегодняшние сигналы в дедуп без отправки, чтобы при первом
re-scan не было пакета).

После строки `[INFO] ws connected` бот в работе.

### 7. Не дать Mac уснуть (если запускаешь на ноуте)

В отдельной вкладке терминала:

```bash
caffeinate -i
```

Эта команда висит и держит Mac бодрым, пока работает. Закрой её через
`Ctrl+C`, когда нужно остановить.

---

## 🤖 Команды бота в Telegram

| Кнопка / Команда | Действие |
|------------------|----------|
| **/start** или `▶️ Подписаться` | Подписаться на сигналы |
| **/stop** или `🛑 Отписаться` | Отписаться |
| **/status** или `📊 Статус` | Проверить подписку |
| **/whoami** | Узнать свой chat_id |

**Админские** (только для chat_id из `admins.json`):

| Команда | Действие |
|---------|----------|
| `/users` | Сколько подписчиков |
| `/broadcast <текст>` | Разослать всем подписчикам |
| `/admin_add <id>` | Сделать кого-то админом |
| `/admin_remove <id>` | Убрать админа |

---

## 📨 Формат сигнала

```
Ξ ETHUSDT · 📦 OB_HTF
📈 LONG · зона 4h

Вход:  2319.91
Зона:  2312.87 – 2338.79
OB 1h: 2026-04-24 02:00 UTC

[📊 TradingView]
```

Иконки активов: ₿ BTC, Ξ ETH, ◎ SOL.
Блок с ценой/зоной/временем — тап копирует одним куском.
Кнопка под сообщением открывает график в TradingView.

---

## 🔧 Полезные скрипты

### Проверить, какие сигналы есть за сегодня (read-only)

```bash
python today_signals.py
```

Не отправляет ничего в Telegram, просто печатает таблицу всех сигналов с
00:00 UTC. Для дебага и сверки.

### Полный бэктест по истории (для анализа стратегий)

```bash
python full_backtest_new.py
```

Прогоняет 5 стратегий по 4 годам данных. Создаёт CSV-файлы в `signals/`.
Долго (5-10 минут на первом запуске), потом инкрементально.

### HTML-отчёт по бэктесту с фильтрами и TradingView-ссылками

```bash
python generate_report.py
```

Открывает в браузере страницу со всеми сигналами из CSV, фильтрами по
символу/ТФ/направлению.

### Дашборд (live-данные бота)

```bash
python generate_dashboard.py
```

Открывает страницу с подписчиками, отправленными сигналами и логами.

---

## 📂 Структура проекта

```
trading-signals-bot/
├── .env                       # секреты (НЕ в гите)
├── README.md                  # этот файл
├── CLAUDE.md                  # контекст для AI-кодинга
├── requirements.txt
├── config.py                  # SYMBOLS, TIMEFRAMES, ADMINS
├── data_manager.py            # загрузка/хранение свечей с Binance
├── state.py                   # users, sent_signals, last_signal, log
├── telegram_bot.py            # отправка сообщений, кнопки, polling команд
├── scanner.py                 # WebSocket Binance + диспетчер закрытых свечей
├── main.py                    # точка входа
├── today_signals.py           # просмотр сегодняшних сигналов
├── full_backtest_new.py       # бэктест по истории
├── generate_report.py         # HTML-отчёт по бэктесту
├── generate_dashboard.py      # HTML-дашборд live-данных
├── strategies/
│   ├── base.py                # Signal, Zone, иконки, рендер
│   ├── ob1h_core.py           # ОБЩЕЕ ЯДРО: find_first_ob1h_in_zone
│   ├── obx4.py                # OBX4
│   ├── fvg.py                 # FVG
│   ├── ob_htf.py              # OB_HTF
│   ├── rdrb.py                # RDRB
│   └── fractal.py             # FRACTAL
├── data/                      # CSV со свечами (автогенерация, НЕ в гите)
├── state/                     # users.json, sent_signals.json, bot.log
└── signals/                   # CSV бэктеста (НЕ в гите)
```

---

## ⚙️ Архитектура

```
┌──────────────────────┐
│ Binance WebSocket    │  ← подписка на 24 стрима (3 символа × 8 ТФ)
└──────────┬───────────┘
           │ закрытие свечи (k.x == True)
           ▼
┌──────────────────────┐
│ scanner.py           │  ← on_closed_native_candle
│                      │  • dispatch в стратегии
│                      │  • dedup через sent_signals.json
│                      │  • фильтр: OB только на последней 1h-свече
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ strategies/          │  ← detect_zones() → list[Zone]
│ + ob1h_core          │  ← find_first_ob1h_in_zone()
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ telegram_bot.py      │  ← broadcast_signal() всем подписчикам
└──────────────────────┘
```

---

## 🛡️ Главные правила

- **Не удалять `state/sent_signals.json` руками.** Это файл дедупа.
  Если удалить — бот при первом re-scan может прислать пакет старых
  сигналов в Telegram.
- **Не закрывать терминал с `python main.py`** — бот остановится.
- **Ноут на зарядке + caffeinate** — иначе Mac уснёт и WebSocket порвётся.

Если что-то пошло не так — смотри `state/bot.log`:

```bash
tail -100 state/bot.log
```

---

## 🛠 Технологии

- Python 3.13
- pandas 2.2.3 (OHLC обработка)
- requests (Binance REST)
- websockets (Binance WebSocket)
- python-dotenv (конфиг)

Никаких БД, ORM, Docker. Всё в CSV и JSON. Запуск одной командой.

---

## 📜 Источник данных

Binance Spot публичный API — **API-ключи не нужны**. Все свечи в UTC.
Обрабатываются только полностью закрытые бары.

---

**Автор:** Pavel Khvostov ([github.com/pavelKhvostov](https://github.com/pavelKhvostov))
