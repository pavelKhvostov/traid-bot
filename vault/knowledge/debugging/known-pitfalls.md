---
tags: [debugging, pitfalls, index]
date: 2026-04-29
status: living-document
---

# Known pitfalls — грабли проекта с правилами избегания

Один экран. Каждый пункт — грабли, на которые проект уже наступал. Перед
работой в области пункта — явно сказать в чате одной строкой:
`вижу related pitfall: <название>, избегаю через <правило>`.

При обнаружении новой ошибки, которой здесь нет — добавить пункт сюда (тот
же формат) и завести детальную заметку в `vault/knowledge/debugging/<утверждение>.md`.

---

### Instant-fill simulator завышает PnL в 3-7×

Что было: etap_42 PDF использовал `simulate_fixed_rr` без ожидания касания
entry — trade фейерится мгновенно по signal_time + tf_min независимо от
текущей цены. Числа +168R BTC (etap_42 reference) → реально +42R (×4).
Симптом: PDF числа выглядят слишком хорошо vs другие симуляторы.
Reproduce: instant baseline 165R / limit baseline 41R → ×4 inflation.
Inflation factor: BTC ×4.0 / ETH ×3.3 / SOL ×4.6.
Правило избегания: backtest simulator ОБЯЗАН ждать касания entry
(limit-fill) или использовать market-at-close с пересчётом R. instant-fill
OK только для screening relative comparison, НИКОГДА для абсолютных
live-expectations. Любой WR > 60% — first candidate проверки exec model.
Источник: [[etap-42-instant-fill-3-7x-inflation]]

### Multi-shot detector добавляет 1.7-2.3× duplicate inflation

Что было: multi-shot framework (etap_98 для 1.1.1, etap_109 для 1.1.2)
собирает все (OB-htf, entry-FVG) пары в зоне. Без дедупа `(signal_time,
direction, entry)` число trades завышено ×1.7-2.3 от реальной торговли.
Симптом: 1.1.2 BTC 6.34y multi-shot baseline +726R на 2157 closed →
после дедупа 968 unique → +315R (×2.3 inflation).
Reproduce: один top-OB содержит 5-15 macro-OB кандидатов, многие
производят тот же (signal_time, entry) → дубли (max 14× на один entry).
Правило избегания: при сравнении multi-shot PnL с canonical numbers
из CLAUDE.md — учитывать factor. Multi-shot OK для relative
baseline-vs-floating comparison (oба используют ту же выборку). Для
абсолютных live-expectations — применить дедуп.
Источник: [[multi-shot-detector-2.3x-inflation]]

### Lookahead в backtest от open() текущей свечи

Что было: `signal_time = open(i+2)` — scan 1m начинался от open бара i+2.
Симптом: grid search показал WR 63.6%, +184R за 3y BTC на VIC_EVOT — нереалистично.
Причина: внутри 15m бара i+2 есть 1m свечи с `low = low(i+2)` → entry-fill
происходит мгновенно по данным, недоступным в реал-тайме.
Правило избегания: scan всегда стартует от **close** последнего известного
бара: `signal_time + tf_duration`. Любой grid search с WR > 60% на сотнях
сделок крипто-стратегии — первый кандидат на проверку lookahead.
Источник: [[lookahead-bug-в-vic-evot-backtest]]

### Удаление state/sent_signals.json вручную → лавина сигналов

Что было: пользователь удалил `state/sent_signals.json` для очистки.
Симптом: при следующем re-scan (close 1h) бот разослал 87 «свежих»
подтверждений за последние 7 дней — все подписчики получили лавину.
Причина: дедуп ключи стёрлись, prefill_silent на момент рестарта не был
включён или не покрывал full re-scan window.
Правило избегания: НЕ удалять `state/sent_signals.json` на работающем боте.
При необходимости очистить — сначала остановить бот, удалить файл,
рестартовать (тогда prefill_silent при старте отметит сегодняшнее как sent).
Для очистки старых записей — использовать ротацию по дате, не truncate.
Источник: [[prefill silent при старте]]

### trigger_time=open_time искал OB-1h внутри формирующейся свечи

Что было: trigger_time зоны был равен open_time свечи-формирующей.
Симптом: подтверждение OB-1h находилось ВНУТРИ ещё-не-закрытой свечи;
сигнал отправлялся с временем будущего close.
Причина: open_time != close-time. Поиск подтверждения на свече, которая
ещё не закрылась, — псевдо-lookahead.
Правило избегания: соглашение `trigger_time = open_time + tf_duration`
(момент закрытия зоны = старт окна поиска подтверждения). В live:
`confirm_time == last_1h_open` — подтверждение только на ПОСЛЕДНЕЙ
ЗАКРЫТОЙ 1h свече.
Источник: [[trigger_time равен open_time плюс tf]], [[главное правило ob только на последней закрытой 1h]]

### Bootstrap 15 минут на каждом старте при добавлении 1m в TIMEFRAMES_NATIVE

Что было: предложение добавить `TIMEFRAMES_NATIVE += ["1m","15m"]` для VIC_EVOT.
Симптом: первый запуск тянул бы ~6.3M свечей 1m с 2022-01-01 для 3 символов
= ~6300 REST-вызовов × 0.15s sleep ≈ 16 минут на каждом холодном старте.
Причина: `Scanner.startup` идёт в `fetch_full_history` от `HISTORY_START_DATE`
для пустого CSV.
Правило избегания: для high-frequency ТФ (1m, 15m) — отдельный bootstrap
с ограниченным горизонтом (`VIC_1M_LOOKBACK_DAYS=3`, `VIC_15M_LOOKBACK_DAYS=7`).
НЕ добавлять short-TF в `TIMEFRAMES_NATIVE` без отдельного bootstrap-пути.
Источник: [[vic-evot-отдельная-ws-сессия]]

### maxV считался на 1m, а Pine ASVK ViC использует 15m LTF

Что было: `calculate_vic_d` принимал сырые 1m свечи без ресемпла.
Симптом: maxV для BTC 2026-04-26 = 78400.0, TV-индикатор показывал ≈78416 (Δ −16).
Причина: Pine `auto=true, mlt=100` на 1D-чарте → LTF = 1440/100 = 14.4m
→ `timeframe.from_seconds(864)` возвращает closest valid TF из стандартного
набора = 15m. Не «rounds down», а «closest valid».
Правило избегания: при репликации Pine-индикатора — ВСЕГДА просить у юзера
скрин конкретного значения с TV перед коммитом. Запросить у юзера ID
индикатора (TV → информация → автор/название) и проверить публичный код,
если open-source. Прогонять comparison-таблицу maxV на 5+ LTF-вариантах.
Если 5m/10m/15m/30m/60m дают одинаковый ответ — Pine использует один из
них. **При смене `VIC_LTF_MINUTES` — удалить `state/vic_levels.json`**,
иначе кэш содержит старые (неверные) значения; либо дождаться
`on_closed_1d`, который перезапишет.
Источник: [[vic-maxv-расходился-с-pine-индикатором-из-за-1m-вместо-15m]]

### prefill_silent пропускал сегодняшние сигналы из-за раннего was_sent

Что было: prefill маркировал сигналы, но в некоторых сценариях ключ уже
существовал из предыдущей сессии → запись пропускалась, при следующем
close 1h тот же сигнал улетал как «новый».
Симптом: разовая повторная рассылка сегодняшних сигналов при перезапуске
бота в течение дня.
Причина: `was_sent(key)` возвращал True для сигналов из предыдущей сессии;
prefill пропускал их через `continue`, не обновляя метаданные. Дальнейший
re-scan (от свежего close 1h) перепутывал prefill_silent vs broadcast_sent
ключи.
Правило избегания: prefill_silent проверяет `was_sent` ДО `mark_sent` и
пропускает уже отмеченные — это by design. При изменении формата дедуп-ключа
`_sig_key_str` (`strategy|symbol|tf|direction|confirm_iso`) — обязательно
мигрировать `state/sent_signals.json`, иначе старые записи становятся
невидимыми и лавина повторяется.
Источник: [[prefill silent при старте]]

### Strategy 1.1.1: hardcoded +15min для fill-scan ломает 20m FVG

Что было: в `backtest_strategy_1_1_1.py:simulate_outcome` хардкод
`fill_scan_start = signal_time + 15min`, применяется ко всем entry FVG
независимо от их TF.
Симптом: 3y BTC прогон показал WR 64.2% на 123 closed сделках (RR=1,
+35R) — попадает в красную зону pitfall #1.
Причина: `signal_time = fvg_entry.c2_time` (open_time c2 свечи). Для 20m
FVG c2 закрывается через 20 минут, не через 15. Scan стартует за 5 мин
до фактического закрытия c2 → захватывает 1m свечи, которые в реал-тайме
ещё являются частью незакрытой 20m c2.
Правило избегания: длительность бара entry-FVG должна выводиться из
метаданных сигнала, не из контекста скрипта. Шаблон:
`fill_scan_start = sig["signal_time"] + pd.Timedelta(minutes=TF_MINUTES[sig["entry_tf"]])`.
Любой `signal_time + Timedelta(minutes=15|20|...)` хардкод = RED FLAG.
- Smoke-test 3y показал 0 изменений outcome'ов: look-ahead был
  теоретическим, не практическим (entry=mid-FVG лежит вне c2). Фикс
  остаётся защитным — для будущих entry-стратегий look-ahead станет
  практическим. См. [[strategy-1-1-1-почему-20m-фикс-нулевой-эффект]].
Источник: [[strategy-1-1-1-look-ahead-15min-vs-tf_duration]]

### Дубли сигналов при перекрывающихся зонах одной стратегии

Что было: одна 1h confirm-свеча попадала в несколько зон одной стратегии
(например, OB-D и OB-3d перекрывались по диапазону).
Симптом: подписчики получали 2-3 сообщения с одинаковой ценой/временем,
разный `source_tf`.
Причина: дедуп-ключ включает `source_tf`
(`{strategy}|{symbol}|{source_tf}|{direction}|{confirm_iso}`), поэтому одна
и та же confirm-свеча с разных source_tf — это разные ключи.
Правило избегания: на одно (symbol, strategy, direction, confirm_time) не
более одного сообщения — это by design разных source_tf. Если хочется
дедуп per-confirm-time — отдельный second-level дедуп через
`{strategy}|{symbol}|{direction}|{confirm_iso}` без source_tf, проверяемый
ПОСЛЕ дедупа per-zone. **Не реализовано**, считаем «допустимый шум».
Триггер пересмотра: **если ≥3 жалобы от подписчиков** на дубли — реализовать
second-level дедуп.
Источник: [[три типа подтверждения 1h ob fvg rdrb]]

### bounce_1x в zone-units ≠ realistic WR при RR-стратегии

Что было: считал `bounce_1x` (% случаев когда цена дошла до `entry + 1×zone_size`
хоть когда-то в окне 50 баров) как прокси WR. На RDRB-1h было 99%, а на
realistic backtest с фьючерсным SL и RR=2 — WR 33%.
Симптом: edge ушёл с обещанных 99% до математического break-even.
Причина: `bounce_1x` не учитывает порядок (если SL выбит до bounce —
True всё равно). При фьючерсном SL (1% от entry ≈ 10×zone_size для RDRB)
TP при RR=2 уезжает на 20×zone_size — намного дальше чем 1×zone, и цена
обычно успевает выбить SL раньше.
Правило избегания: `bounce_X%` в zone-units нельзя использовать как прокси
WR. Перед оптимизацией формулы — обязательный realistic backtest с
RR-симуляцией на 1m. Если bounce_X = 99% а realistic_WR = 33% — значит
zone_size << RR×SL_distance. Использовать ATR-units или absolute-%
для сопоставимых метрик.
Источник: [[bounce-1x-не-равно-wr-при-rr]]

### Anchor zone использовался до cur_close → масштабный lookahead в HTF×LTF setup'ах

Что было: в `etap_14_full_grid.py` окно поиска LTF-триггера в зоне анкора
стартовало с `a["time"]` = ob.cur_time = open свечи cur. Но OB подтверждается
только ПОСЛЕ закрытия cur, в `cur_time + tf_anchor`.
Симптом: grid search на BTCUSDT 6 лет показал «топ-3» с WR 67-77% и +285…+559R.
После фикса: WR 26-49%, total −6 … −119R. Edge испарился полностью.
Причина: триггеры в окне (cur_open, cur_close) использовали ещё-не-сформированный
анкор. На FVG-15m триггере с OB-12h окно было 12h × 48 баров — массовое
включение «нелегальных» setups. Внутри окна формирования OB цена систематически
идёт В сторону зоны → искусственно завышенный WR.
Правило избегания: **RED FLAG в любом backtest-коде** — `a_start = ...["time"]`
без добавления `+ tf_anchor`. Эталон — `etap_13_ob_size_sweep.py:99-100`:
`ob_start = ob["ob_time"] + pd.Timedelta(hours=4)`. То же самое для всех
HTF×LTF setup'ов в research/. После любого нового pipeline — обязательная
sanity-проверка: WR > 60% на сотнях сделок крипто-стратегии = lookahead suspect.
Источник: [[lookahead-anchor-confirm-окно-cur_open-cur_close]]

### Год отсутствует в year-by-year breakdown — это data gap, не «нет setups»

Что было: в `data/BTCUSDT_1m.csv` отсутствовали 480 дней (2022-01-01 .. 2023-04-26).
Симптом: year-by-year breakdown показывал 2020, 2021, 2023, 2024, 2025 — без 2022.
Все backtests интерпретировали это как «не было setups в bear market».
Причина: bootstrap CSV прервался; pd.read_csv не fail'ит, groupby не выдаёт
строки для пустых годов. Одновременно 2022 — самый тяжёлый bear (LUNA + FTX),
которого больше всего нужно тестировать.
Правило избегания: при backtest на 2+ года — обязательная sanity-проверка
полноты данных (`set(years_in_data) == set(expected_years)` + gap detection
через `df.index.diff().max()`). **Если год отсутствует в year-by-year — это
RED FLAG**, не «strategy doesn't fire there». После fix C2 получил +22R
благодаря 2022 (стал 0 минусовых лет за 7), D2 потерял корону (2022 был −6.25R).
Источник: [[2022-1m-data-gap-symptom-year-missing]]

### HTF lookup в backtest читает FORMING bar — lookahead

Что было: в etap_36 фильтр на Hull MA(78) на 1d поверх C2 (LTF strategy
на FVG-2h trigger). `hull_trend_label(close_1d, hull_1d, ts)` использовал
`close_1d.iloc[idx]` где idx — бар содержащий ts. Этот бар на момент ts
ЕЩЁ ФОРМИРУЕТСЯ.
Симптом: BTC C2v2 RR=1.5 показывал WR 49.0% / **+101R** / 0 минусовых
лет — выглядело как breakthrough; OOS на ETH провалился (-30R / 4/4 bad
years), что раскрыло аномалию. После audit fix (использовать last closed
1d bar `idx-1`): WR 46.6% / +66R / 1 bad year на BTC. Inflation +35R / 53%.
Причина: в pandas df.index содержит OPEN times. `searchsorted(ts, "right") - 1`
возвращает индекс бара ВНУТРИ которого ts (он формируется). Его close
известен только в момент next bar's open — это будущая информация
относительно ts. Pine `request.security(_, "1d", close)` non-repaint
возвращает close last CLOSED 1d bar, что соответствует `close[idx - 1]`
в backtest.
Правило избегания: для любого HTF lookup в backtest LTF-стратегии:
**стартовать с `last_closed = idx - 1`**. Все Pine `[N]` shifts применять
от last_closed (`hull[last_closed - shift]`). Любой `htf_series.asof(ts)`
без поправки на закрытость бара — RED FLAG. Helper `htf_safe_value(series, ts)`
для централизованного использования.
Источник: [[htf-lookup-must-use-last-closed-bar-not-forming]]

### Multi-bar pattern: detect at trigger, но entry должен быть на confirm_idx

Что было: RDRB+ MMXM фильтр (etap_31-32) — entry на FVG c2.close, фильтрация
по «есть ли RDRB+ потом в окне 10 баров».
Симптом: WR +10-15pp на всех ТФ (1h, 4h, 12h, 1d) vs baseline. «Идеальный
фильтр». На LTF особенно силный: 1h +14pp, R/tr с −0.05 на +0.21.
Причина: на момент c2.close мы ЕЩЁ НЕ ЗНАЕМ сформируется ли RDRB+ в
следующие 10 баров. Это будущая информация. Условие «не вернулась в FVG»
автоматически удаляет «плохие» trades, которые быстро вернулись в FVG в
первые 5-10 баров → искусственная inflation.
Правило избегания: для стратегий с структурным confirmation из N баров —
backtest entry **обязательно** на close confirm_idx (после waiting period),
SL/TP отсчитываются от него. Сравнение `lookahead vs honest` обязательно
для multi-bar patterns. На LTF (1h-4h) edge таких фильтров обычно
полностью пропадает; real edge остаётся только на HTF (12h-1d).
Источник: [[multi-bar-pattern-confirm-vs-trigger-lookahead]]

### Live-сканер пропускал сигналы из предыдущих часов (MAX_SIGNAL_AGE_HOURS=2)

Что было: live-сканеры использовали `age = now - signal_time` против `MAX_SIGNAL_AGE_HOURS=2`,
но `signal_time = fvg_entry.c2_time` это OPEN бара, не CLOSE. Для 2h FVG свежий сигнал
имеет age=2h на момент 1h close. WS delay 100ms → age=2h+ε → silenced.
Симптом: 2h FVG сетапы систематически блокировались. 15m FVG из ПРЕДЫДУЩЕГО часа
(c2_close=12:30 при 1h close 14:00, age=1.75h) проходили — слали "stale" сигналы.
Причина: age по c2_OPEN не соответствует фактической freshness; диапазон 2h слишком широк.
Правило избегания: для "current hour only" фильтра использовать `c2_CLOSE = signal_time
+ tf_duration` и проверять `(now.floor('h') - 1h, now.floor('h')]`. Не использовать
`MAX_SIGNAL_AGE_HOURS` как окно — оно охватывает несколько часов.
Источник: [[multi-scanner-current-hour-filter]]

### mark_sent race condition при concurrent live-сканерах

Что было: `state.mark_sent()` делал read-modify-write на `state/sent_signals.json`
без thread lock. При 4 live-сканерах (1.1.1 + 1.1.2 + 1.1.3 + 1.1.6) запускаемых через
`asyncio.to_thread`, на 1h boundary возможны 12+ concurrent calls.
Симптом: потенциальная потеря записей в JSON, повторные рассылки одного сигнала.
Причина: ThreadPool в asyncio.to_thread позволяет parallel execution, JSON-файл не atomic.
Правило избегания: любая функция в `state.py` с read-modify-write на shared JSON —
обязательно через `threading.Lock`. Для масштабирования рассмотреть SQLite с WAL.
Источник: [[mark-sent-race-condition-4-scanners]]

### Каскад продолжается на мёртвой родительской зоне — invalidation проверяется только на L2

Что было: в `detect_with_funnel` (etap_69) и `detect_4stage` (etap_66)
стратегии 1.1.4 проверка `l2_close > L1_active_end` стояла только на L2
(OB-4h). L3 (OB-1h/2h) и L4 (FVG-15m/20m) могли формироваться **уже после
инвалидации макрозоны L1** (FVG-d/12h).
Симптом: 24 из 186 raw-сетапов (~13%) портфеля B+F+J+K имели L3.close
после смерти L1. Эти сетапы показывали WR 21.1%, total -7R, avg -0.37R/trade —
системно проигрывали, но скрывались в общей статистике. До фикса портфель
показывал WR 59.9% / +133R, после фикса WR 64.3% / +107R / +0.93R/trade.
Причина: `l3_search_end = l2_close + l3_life` без clamp по `L1_active_end`.
Если l3_life > (L1_dead - L2_close), окно поиска L3 простирается за пределы
жизни макрозоны. При `allow_multi=5` это особенно опасно — квота
«5 сетапов на одну L1» добивается мёртвыми кандидатами.
Правило избегания: при многоуровневом каскаде с TTL/инвалидацией родительской
зоны проверка валидности должна быть на **КАЖДОМ уровне**, не только на L2.
Шаблон:
```python
if l2_close > L1_active_end: continue   # level 2
if l3_close > L1_active_end: continue   # level 3 — НЕ забыть
if l4_c2_close > L1_active_end: continue   # level 4
```
Дополнительно: clamp поискового окна сверху — `min(search_end, L1_active_end)`.
Источник: [[l3-не-фильтровался-против-l1-invalidation]]

### round(x, N) ≠ толерантность — для tolerance нужен bucketing

Что было: для схлопывания «почти-дубликатов» с дребезгом 0.025-0.5%
попробовали ключ дедупа `(..., round(sl/entry, 4))`. Логика «4 знака =
0.01% bin → diff < 0.01% попадёт в один ключ».
Симптом: 0 эффекта, deduped n не изменилось (Strategy 1.1.1, 158 строк
до и после).
Причина: `round(x, N)` определяет **ширину bin**, а не **толерантность**.
Два значения с diff 0.025% МОГУТ оказаться в разных bins если они на
границе: `1.014959 → 1.0150` и `1.015214 → 1.0152` (diff 0.025% → разные ключи).
Правило избегания: для семантического схлопывания близких значений
**нельзя использовать round() как threshold**. Правильный паттерн —
bucketing: сортировка по значению + последовательное объединение пока
`abs(value_i - value_first) < THRESHOLD`. См.
[[strategy-1-1-1-dedup-bucketing-tolerance]] для готового шаблона.
Также: при объединении группы — assert на критичных полях (тут `outcome`);
если они расходятся → split, легитимные разные данные.
Источник: [[strategy-1-1-1-dedup-bucketing-tolerance]]

### Нативный 3d Binance не выровнен по UTC-эпохе

Что было: `3d` лежал в `TIMEFRAMES_NATIVE` → `get_df("3d")` тянул свечи
нативно через Binance klines `interval=3d`. При этом `2d`/`3h` собираются
из базового ТФ через `compose_from_base` с `origin='epoch'`.
Симптом: 3d-свечи смещены на 1 день относительно epoch-сетки. На 2026-05-19
крайняя закрытая 3d по нативным данным имела `open=2026-05-14` вместо
`open=2026-05-16` / `close=2026-05-19`. Расхождение с TradingView и с
собственным composed `2d`.
Причина: нативный 3d Binance анкорится не по Unix-эпохе. `2026-05-14` —
день №133 от `2026-01-01` (133 mod 3 = 1), не на epoch-3d-сетке.
`compose_from_base(origin='epoch')` применялся только к ТФ из
`TIMEFRAMES_COMPOSED`, `3d` туда не входил.
Правило избегания: любой ТФ длиннее `1d`, который Binance отдаёт не
выровненным по UTC-эпохе, держать в `TIMEFRAMES_COMPOSED` и собирать из
`1d`, не в `TIMEFRAMES_NATIVE`. Бэктест-скрипты с локальным хардкодом
`NATIVE = [..., "3d"]` (`full_backtest_new.py`,
`research/_shared/backtest_year.py`) имеют ту же грабли — их 3d-результаты
смещены, чинить при следующем прогоне.
Источник: [[нативный-3d-binance-не-выровнен-по-epoch]]

### Pine LTF на 12h-chart — ceil round-up до integer-minute, не closest valid

Что было: ViC ASVK 12h-chart с mlt=100 даёт `rs=432s=7.2min`. Ожидалось,
что Pine возьмёт closest valid из {5m, 10m} — теоретически 5m.
Симптом: maxV не совпадал с индикатором (расхождение десятки/сотни USD)
на любом LTF из {1m, 5m, 7m, 10m, 15m}. На D-chart (Pine LTF=15m через
closest valid) совпадало точно — отсюда ожидание тоже closest valid.
Причина: Pine `timeframe.from_seconds(seconds)` на не-D chart **round-up
до ближайшей целой минуты** = `ceil(seconds/60)`. Для 432s → "8" (8m).
Правило избегания: при репликации Pine indicator на любом не-D chart
использовать `LTF_minutes = math.ceil(rs/60)`. На D-chart правило другое
(closest valid). При первой реплике — попросить 2-3 контрольных значения
из TV для сверки. Brute-force LTF от 1 до 30 минут показывает оптимум
точечно (для 12h@mlt=100 → 8m, Σ|Δ| на 6 свечах = 12 USD vs 600+ на других).
Источник: [[pine-ltf-12h-chart-ceil-round-up-to-integer-minutes]]

### Zone-overlap фильтр без mitigation покрывает почти все бары

Что было: в HH-предикторе (сессия 2026-05-19) использовалось «свеча `i`
пересекает зону SHORT FVG / OB-liq на D/2D/3D/W» без проверки, тронута
ли зона ранее. Старые зоны накапливаются годами.
Симптом: cond_fvg N = 2722 из 3194 валидных D-свечей (**85% покрытия**),
OR трёх sub-conditions N = 3009 (**94%**). Lift над базой P(HH-фрактал)
= ×1.04 (+0.6 pp) — фильтр выродился в тавтологию.
Причина: за 8.7 лет накопилось ~553 SHORT FVG через 4 ТФ. Любая текущая
свеча геометрически пересекает какую-нибудь старую зону.
Правило избегания: zone-overlap фильтры (FVG, OB, RDRB, любые ценовые
зоны) **обязаны** учитывать митигацию. Минимум — «первый touch»: считать
свечу `i`, только если она первая D-свеча после формирования зоны, чей
range её пересекает. Vectorized: `first_touch_indices` через
`np.argmax(~((h[start:] < zb) | (l[start:] > zt)))`. После фикса:
N(FVG-ft) = 354 (11%) → lift ×2.20 (+16.2 pp), топ-стэк ss+lh+(fvg-ft|ob-ft)
= 84.6% (11/13) lift ×6.3.
Источник: [[zone-mitigation-filter-required]]

### SOCKS-прокси блокирует Binance REST в python-requests

Что было: 2026-06-03 при `update_df_incrementally('BTCUSDT', '1h')` падал
с `requests.exceptions.InvalidSchema: Missing dependencies for SOCKS support`.
В env лежали `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` с `socks5://...` от другой
программы, а `pysocks` не установлен в venv проекта.
Симптом: любой `requests.get(BINANCE_KLINES_URL)` падает мгновенно с
InvalidSchema, причём это НЕ network error — это до отправки.
Правило избегания: перед запуском скриптов, дёргающих Binance/любой REST,
явно сбросить proxy env vars в subprocess:
`NO_PROXY=* HTTP_PROXY= HTTPS_PROXY= ALL_PROXY= python ...`
или внутри скрипта `for k in [...]: os.environ.pop(k, None)`. Не ставить
pysocks как фикс — корректнее работать напрямую с api.binance.com.
Источник: сессия [[2026-06-03-bulkowski-12-reversal-detectors-etap-172]]

### `reset_index` после `compose_from_base` теряет имя колонки

Что было: 2026-06-03 в etap_172 после `compose_from_base(df_1h, '12h')`
вызвал `df.reset_index()` ожидая колонку `'time'`, но индекс был безымянным
→ KeyError при `df['time']`. `compose_from_base` использует `resample`
который не назначает имя индексу при отсутствии входного name.
Симптом: KeyError: 'time' на первом же обращении к составленному ТФ-df.
Правило избегания: после `compose_from_base(...).reset_index()` всегда
ренеймить первую колонку: `df = df.rename(columns={df.columns[0]: 'time'})`.
Или сразу работать через индекс без reset_index. Не полагаться на имя
индекса от resample.
Источник: сессия [[2026-06-03-bulkowski-12-reversal-detectors-etap-172]]
