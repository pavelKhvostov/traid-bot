# Trading Signals Bot

## Что это

Telegram-бот, который параллельно прогоняет несколько алгоритмических
стратегий по BTC на Binance Spot и шлёт сигналы подписчикам в ЛС.
В live с 2026-05-06: `MultiStrategyScanner` запускает **6 версий 1.1.x**
параллельно (один WS, на каждом 1h close прогоняются все 6 детекторов).
Старые `Scanner` (7 классических) и `VicScanner` отключены в main.py,
код сохранён.

## Стратегии в live (6 версий 1.1.x)

`multi_strategy_scanner.py:STRATEGIES`:

- **S111_SWEPT**  — 1.1.1 со SWEPT-фильтром на OB-htf (отсекает 20% NOT-SWEPT мусора)
- **S112**        — 1.1.2 (macro=OB вместо FVG, без SWEPT)
- **S113_V1**     — 1.1.3 fvg_variant=v1, macro_mode=untouched (immediate FVG)
- **S113_V2**     — 1.1.3 fvg_variant=v2 (FVG охватывает OB-pair)
- **S114_V1**     — 1.1.4 fvg_variant=v1 (гибрид: macro=FVG + entry-FVG того же ТФ)
- **S114_V2**     — 1.1.4 fvg_variant=v2

Формат сигнала (без кружков confluence):

```text
BTC - LONG
POI: Daily OB + 4h FVG
Volume confirmation: 1h OB + 15m FVG
```

Защита от старых сигналов: `MAX_SIGNAL_AGE_HOURS=1` + `prefill_silent`
на startup. См. [[swept-фильтр-применим-только-к-1-1-1]] для решения
про SWEPT.

### Старые live-стратегии (отключены в main.py, код сохранён)

- **OBX4** ⚡, **FVG** 〰️, **OB_HTF** 📦, **RDRB** ↩️, **FRACTAL** ❄️,
  **HAMMER** 🔨, **MARUBOZU** 🟩 — `scanner.py`
- **VIC_EVOT** 🎯 — `vic_scanner.py`

### Backtest-only — в live не интегрированы

- **VIC_BOS**        — VIC-уровень + BOS на 3m (quadruple H-L-H-L). 3y BTC: WR 53.6%, +37R.
- **Strategy 1.1.1** — multi-TF nested OB+FVG: OB-{1d,12h} + FVG-{4h,6h} → OB-{1h,2h} + FVG-{15m,20m}.
                       3y BTC raw @ RR=1.0: 144 deduped, WR 61.7%, +33R.
                       После 3-stage SWEPT optimize @ RR=2.2: 115 closed, WR 54.8%, **+46.8R**, R/trade 0.755.
                       См. `research/1_1_1/`.
- **Strategy 1.1.2** — макро-OB вместо макро-FVG. Stage 3 @ RR=2.2: WR 44.4%, +101.4R на 241 closed.
                       См. `research/1_1_2/`.
- **Strategy 1.1.3** — entry FVG того же ТФ что OB-htf (без 15m/20m). Слабее 1.1.1: stage3 @ RR=2.2 +11.4R.
                       См. `research/1_1_3/`.
- **Strategy 1.1.4** — гибрид macro-FVG (1.1.1) + entry immediate (1.1.3). **WIP**, только raw backtest.
                       См. `research/1_1_4/`.
- **Strategy 1.2.0** — новая ветка: EMA-200 + sweep + FVG-15m. В стадии tuning, текущие показатели отрицательные.
                       См. `research/1_2_0/`.

## Символы

BTCUSDT, ETHUSDT, SOLUSDT

## Источник данных

Binance Spot REST + WebSocket (публичное API, ключи не нужны).

- `Scanner` подписан на `TIMEFRAMES_NATIVE = ["1h","2h","4h","6h","8h","12h","1d","3d"]`.
  Составные `3h` (из 1h) и `2d` (из 1d) пересобираются через
  `compose_from_base` с `origin='epoch'`.
- `VicScanner` дополнительно подписан на `["1m","15m","1d"]` (1d дублируется —
  тривиально). Bootstrap 1m/15m с ограниченным горизонтом
  (`VIC_1M_LOOKBACK_DAYS=3`, `VIC_15M_LOOKBACK_DAYS=7`) — НЕ от
  `HISTORY_START_DATE`, чтобы не фетчить 6.3M свечей при старте.

## Архитектура (минимальная, без оверинжиниринга)

```
traid-bot/
├── .env                  # TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID
├── config.py             # SYMBOLS, TIMEFRAMES_NATIVE, VIC_NATIVE_TFS, пути
├── data_manager.py       # скачивание+хранение свечей (REST+WS), CSV
├── state.py              # users.json, sent_signals.json, vic_levels.json, bot.log (5MB rotate)
├── telegram_bot.py       # отправка сообщений, команды /start /stop /status
├── multi_strategy_scanner.py  # Live-сканер 6 стратегий 1.1.x (с 2026-05-06)
├── scanner.py            # Старый Scanner с 7 классическими (отключён в main.py)
├── vic_scanner.py        # VicScanner для VIC_EVOT (отключён в main.py)
├── vic_levels.py         # calculate_vic_d (чистая функция, maxV(D-1))
├── strategies/
│   ├── __init__.py
│   ├── base.py
│   ├── ob1h_core.py, obx4.py, fvg.py, ob_htf.py, rdrb.py, fractal.py
│   ├── hammer.py, marubozu.py, vic_evot.py
│   ├── strategy_1_1_1.py / 1_1_2.py / 1_1_3.py / 1_1_4.py  # все 4 в live (multi_scanner)
│   ├── strategy_1_1_6.py / 1_2_0.py    # research-only
├── research/             # research-стенд (см. research/README.md)
│   ├── 1_1_1/{backtest,optimize,analyze}/   # эталон 1.1.1
│   ├── 1_1_2/{backtest,optimize,analyze,export}/
│   ├── 1_1_3/{backtest,optimize,analyze,compare}/
│   ├── 1_1_4/{backtest,analyze}/   # SWEPT-split добавлен 2026-05-06
│   ├── 1_1_6/{backtest,optimize,analyze}/   # параллельная ветка FVG-OB-FVG
│   ├── 1_2_0/{backtest,tune}/
│   ├── rdrb/{backtest,optimize,analyze}/
│   ├── vic/{backtest,optimize}/
│   └── preview_strategies_monthly.py   # diagnostic preview live-сигналов
├── tests/                # pytest (73 tests)
└── main.py               # точка входа: asyncio.gather(scanner, polling)
```

## Ключевые решения

- Все времена в UTC (как отдаёт Binance).
- Обрабатываем ТОЛЬКО закрытые свечи (`k["x"] == True` в WebSocket).
- Составные ТФ (3h, 2d) пересобираются из базовых (1h, 1d) через
  `pandas.resample` с `origin='epoch'`, выравнивание по UTC 00:00.
- Дедуп сигналов через `state/sent_signals.json` — ключ
  `{strategy}|{symbol}|{source_tf}|{direction}|{confirm_time_iso}`.
- Подписчики — список объектов в `state/users.json`.
- На старте бота: bootstrap истории с 2022-01-01 для `Scanner`, ограниченный
  горизонт для `VicScanner`. `prefill_silent` отмечает сегодняшние сигналы
  как sent без рассылки. См. [[prefill silent при старте]].
- Главное правило live для 7 стратегий: `confirm_time == last_1h_open` —
  подтверждение только на ПОСЛЕДНЕЙ ЗАКРЫТОЙ 1h свече. Для VIC_EVOT —
  `i+2 == last_closed_15m_open_time`.
- Универсальные определения OB и FVG зафиксированы как canon. См.
  [[универсальные определения OB и FVG]].
- `bot.log` ротируется при > 5 MB (`LOG_ROTATE_BYTES` в `state.py`). Ровно
  один backup: `bot.log.1`.
- Двойной WS: `Scanner` и `VicScanner` запускаются параллельно через
  `asyncio.gather`. См. [[vic-evot-отдельная-ws-сессия]].

## Формат сигнала в Telegram

Зональный (7 стратегий):
```
₿ BTCUSDT · ⚡ OBX4
📈 LONG · зона 1d
Подтверждение: OB-1h

Вход:    65432.10
Зона:    65000.00 – 65500.00
Время:   2026-04-29 14:00 UTC
```

Уровневый (VIC_EVOT):
```
₿ BTCUSDT · 🎯 VIC_EVOT
📈 LONG · уровень maxV(2026-04-28)
Подтверждение: FVG-15m + LL-фрактал + OB-15m

Вход:    65432.10
Уровень: 65250.00
Время:   2026-04-29 14:30 UTC
```

Иконки стратегий: OBX4 ⚡, FVG 〰️, OB_HTF 📦, RDRB ↩️, FRACTAL ❄️,
HAMMER 🔨, MARUBOZU 🟩, VIC_EVOT 🎯.

## Стиль кода

- Python 3.13, pandas 2.2.3, requests, websockets, python-dotenv.
- Никаких ORM, базы данных, Docker — всё в CSV и JSON.
- Простые функции и dataclass-ы, никаких классов-фабрик и DI-контейнеров.
- Логи через `state.log_event(level, msg)` (пишет в `state/bot.log` + stdout).
- Русские комментарии допустимы.

## Команды Telegram-бота

- `/start` — подписаться на сигналы.
- `/stop` — отписаться.
- `/status` — подписан/не подписан.
- `/lastsignal` — последний сигнал.

## Чего НЕ делать

- Не делать веб-интерфейс, дашборды.
- Не добавлять async-ORM, Redis, Celery.
- Бэктест-скрипты — одноразовые, не превращать в фреймворк/CLI/конфиги.
- Не покрывать тестами не-стратегический код (UI, форматирование, утилиты,
  бэктест-скрипты). Стратегии и формулы — обязательно тесты, см. секцию
  «Тестирование (для стратегий)».
- Не использовать TA-Lib или сторонние индикаторы — вся логика уже в
  существующем коде пользователя.

## Источники логики стратегий

Reference-имплементации стратегий — в истории git (commit `b950d43` и ранее).
При расхождении детектора с reference — записать в [[known-pitfalls]] и
решить осознанно.

## При написании стратегии или её формулы

- Каждая чистая функция-детектор (`detect_*` в `strategies/`) и каждая формула
  (`calculate_*` в `vic_levels.py` и аналогах) обязана иметь тест в
  `tests/test_<имя>.py` с фикстурами на счастливый путь + минимум 3 edge case.
- Reference-формулы (OB, FVG, RDRB, фрактал) фиксируются один раз в
  `vault/knowledge/smc/` и переиспользуются. При расхождении детектора с canon —
  обновлять оба места одновременно.
- `Signal` всегда возвращается с заполненным `meta` (минимум `confirm_type`).
  Это влияет на Telegram-формат через `format_signal_telegram`.
- При смене `confirm_time` логики или ТФ-схемы — проверить дедуп-ключ в
  `_sig_key_str`/`mark_sent`. Изменение формата ключа без миграции сломает
  дедуп старых записей.

## Тестирование (для стратегий)

При создании или изменении логики любой стратегии (`strategies/*.py`)
или её формул (`vic_levels.py` и аналоги) — обязательно создать или
обновить тест в `tests/test_<имя_стратегии>.py`.

- Минимум: фикстура на счастливый путь + 3 edge case (пустой df, граничный
  случай, противоположное направление).
- Тесты — чистые: фикстуры строят искусственные свечи, никакого I/O,
  никакой сети.
- Запуск: `python -m pytest tests/ -v`. Без зелёных тестов **не коммитить**.

Для не-стратегического кода (telegram-формат, утилиты, скрипты-однодневки)
тесты по желанию. Бэктест-скрипты тестами не покрываются — их «тест» =
визуальная сверка с предыдущим прогоном CSV + ручная сверка с TV.

Если коммит меняет формулу детектора и тест НЕ был обновлён — в commit
message указать причину явно (например `(formula change, test update
follows in next commit)`); без этого — отказ от коммита.

## Самообучение: known-pitfalls.md

Проект ведёт живой список граблей в
`vault/knowledge/debugging/known-pitfalls.md`. Каждый пункт — короткая
запись (что было / симптом / причина / правило избегания / ссылка на
детальную заметку).

### Правила

1. **При старте каждой сессии** — прочитать `known-pitfalls.md` целиком
   (вместе с `index.md` и `текущие приоритеты.md`). Файл умещается на
   один экран; занимает 30 секунд.

2. **При обнаружении новой ошибки**, которая не входит в список:
   - Добавить пункт в `known-pitfalls.md` в том же формате (что было /
     симптом / причина / правило избегания / источник).
   - Создать детальную заметку в `vault/knowledge/debugging/<утверждение-
     описывающее-проблему>.md` с frontmatter `tags: [debugging, ...]`
     и `date: YYYY-MM-DD`.
   - Имя детальной заметки = утверждение (`lookahead-bug-в-vic-evot-
     backtest.md`), не категория (`bugs.md`).

3. **Перед написанием кода в области, связанной с известной ловушкой** —
   явно сказать в чате одной строкой:
   `вижу related pitfall: <название>, избегаю через <правило>`.

   Это форсит проверку «а не повторяю ли я ту же ошибку?» на этапе
   планирования, а не на этапе ревью CSV.

4. **Если новая грабля повторяет уже задокументированную** — это сигнал
   что правило избегания нечётко сформулировано. Обновить правило, не
   дублировать пункт.

---

## Obsidian Knowledge Vault

Хранилище знаний проекта: `vault/` (внутри проекта, относительный путь).

### При старте сессии

1. Прочитай `vault/00-home/index.md` — карта vault, что где лежит.
2. Прочитай `vault/00-home/текущие приоритеты.md` — что сейчас в работе.
3. Прочитай `vault/knowledge/debugging/known-pitfalls.md` — список
   уже-известных граблей с правилами избегания.
4. Если задача касается стратегии — прочитай заметку из `vault/knowledge/strategies/`.
5. Если задача про баг — посмотри `vault/knowledge/debugging/`.

### При завершении сессии (пользователь говорит "сохрани сессию")

1. Создай заметку в `vault/sessions/` с именем `YYYY-MM-DD-короткое-описание.md`.
2. Если было архитектурное решение — создай заметку в `vault/knowledge/decisions/`.
3. Если был баг и решение — создай заметку в `vault/knowledge/debugging/`
   И добавь пункт в `known-pitfalls.md`.
4. Если меняли стратегию — обнови `vault/knowledge/strategies/<название>.md`.
5. Обнови `vault/00-home/текущие приоритеты.md` (что сделано, что осталось).
6. Обнови `vault/00-home/index.md` если есть новые заметки.

### Правила оформления заметок

- Названия файлов = утверждения, не категории.
  Плохо: `auth.md`, `bugs.md`
  Хорошо: `утренняя пачка 87 сигналов из-за удаления sent_signals.md`
- Wiki-ссылки `[[имя заметки]]` обязательно — они создают граф связей.
- Frontmatter в начале каждой заметки.
- Язык: русский.

### Связь с GSD и `.planning/`

`.planning/codebase/` (карта от GSD) — описывает **что** в коде есть.
`vault/` (твой Obsidian) — описывает **почему** именно так и **историю изменений**.
Они дополняют друг друга, не конкурируют. При планировании задач сверяйся с обоими.
