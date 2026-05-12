---
tags: [strategy, multi-tf, fvg, ob, strategy-1-1-6]
date: 2026-05-06
status: research-baseline-negative
related: [[strategy_1_1_1]], [[универсальные определения OB и FVG]]
---

# Strategy 1.1.6 — FVG-{1d,12h} + OB-{4h,6h} → FVG-{1h,2h}, entry на htf-FVG

## Концепт

**Параллельная ветка к 1.1.1/1.1.2/1.1.3 с инвертированной структурой**:
зеркалим типы паттернов на каждом уровне.

```
1.1.1:  OB-top  → FVG-macro → OB-htf → FVG-entry (младший ТФ)
1.1.6:  FVG-top → OB-macro  → FVG-htf (entry прямо на htf-FVG)
```

Используются [[универсальные определения OB и FVG]] (canon).

**Status:** в live НЕ добавлена. Raw baseline на 3y BTC показал
отрицательный edge (WR 33%, −5R на 15 closed), стабильно убыточно
по годам. Кандидат на оптимизацию (vary entry_pct, фильтры) — пока
не приоритет.

## Логика (3 уровня × 2 ТФ + earliest-wins)

### Шаг 1: top-FVG — 1d ИЛИ 12h

`collect_valid_top_fvgs(df_top, top_tf_hours)` — все FVG нужного ТФ,
оба направления. Wick-инвалидация проверяется ПОЗЖЕ, в окне
`[c2_close, ob_macro.cur_close)` на свечах df_macro.

### Шаг 2: macro-OB — 4h ИЛИ 6h, earliest-wins

`find_first_macro_ob_for_top_fvg`. Поиск стартует с `fvg_top.c2_time
+ top_tf_hours` (закрытие c2 свечи top-FVG). Возвращается **первый**
валидный OB-macro:

- Направление совпадает с top-FVG
- `zones_overlap(ob_macro, fvg_top)` — partial overlap, НЕ внутри
- Wick-инвалидация top-FVG в окне `[search_start, ob.cur_close)` на
  df_macro (single wick = invalid)

Earliest-wins между 4h и 6h: по `cur_close = cur_time + macro_hours`,
не по `cur_time` (чтобы при равных open-time побеждал раньше-закрывшийся).

**Один macro на одну top-FVG** — снижает raw count и исключает кейс
«разные macro на одной структуре» (см. 2026-02-06 в 1.1.1).

### Шаг 3: htf-FVG — 1h ИЛИ 2h, earliest-wins по c2_close

`find_first_fvg_htf_in_zone`. **Критичное:** старт поиска =
`ob_macro.cur_time + macro_hours` (4 или 6), не `+ htf_hours`. Иначе
htf-FVG может сформироваться ДО закрытия cur-свечи macro-OB —
lookahead. См. [[strategy-1-1-6-look-ahead-macro-htf]].

Validity:
- Направление совпадает
- `zones_overlap` с ob_macro **И** `zones_overlap` с fvg_top
  (двойной чек — overlap не транзитивен)

Earliest между 1h и 2h: по `c2_close = c2_time + htf_hours`. У нас
разница 1h vs 2h = 100%, учитываем явно (в 1.1.1 для 15m vs 20m
разница 5 мин и сравнение по c2_time достаточно).

**SWEPT-фильтра НЕТ.** Это сознательная редукция к чистой
zone-confluence стратегии без структурных фильтров.

### Entry / SL / TP

- `entry = (fvg_htf.bottom + fvg_htf.top) / 2` — mid htf-FVG
- LONG: `sl = ob_macro.bottom`, `tp = entry + risk × RR`
- SHORT: `sl = ob_macro.top`, `tp = entry - risk × RR`
- **RR = 1.0** фиксированный (`strategies.strategy_1_1_6.RR` —
  модульная константа, single source of truth)
- `risk = abs(entry - sl)`

## Backtest симуляция

`research/1_1_6/backtest/backtest_strategy_1_1_6.py`:
- `fill_scan_start = signal_time + tf_minutes`, где
  `tf_minutes = 60 if htf_tf=="1h" else 120` (выводится из метаданных
  сигнала, не хардкод — урок [[strategy-1-1-1-look-ahead-15min-vs-tf_duration]])
- 5 outcomes: `WIN / LOSS / NO_ENTRY / NOT_FILLED / OPEN`
- **NO_ENTRY**: до fill цена коснулась TP или SL (структура отработала без нас)
- pnl_r: +1 / -1 / 0 / 0 / 0

## Дедуп

Двухэтапный bucketing 0.5% (по образцу 1.1.1):
1. Primary: группы `(signal_time, direction)`, sort by entry, merge пока
   `|entry_i - entry_first| / entry_first < 0.005`
2. Sub-bucketing: внутри primary sort by sl, merge пока
   `|sl_i - sl_first| / entry < 0.005` AND `outcome` совпадает

`must_match` минимальный = `["outcome", "fill_time"]`. **НЕ включать
`htf_tf, htf_fvg_zone`** — они meta-агрегируются sorted-uniq join
(`"1h,2h"`). Иначе валидный кейс «два пути через top-1d→1h-FVG и
top-12h→2h-FVG к одной (entry, sl)» падает с AssertionError. Этот
урок в нашем коде уже зашит, не повторяем.

## Результаты raw baseline (3y BTCUSDT, RR=1.0, после lookahead-fix)

| Метрика | Значение |
|---|---|
| Raw | 135 |
| Deduped | 111 |
| Closed (W+L) | 15 (W=5, L=10) |
| NO_ENTRY | 96 (86%) |
| NOT_FILLED | 0 |
| OPEN | 0 |
| **WR** | **33.3%** |
| **PnL** | **−5R** |
| R/trade | −0.333 |

### По годам

| Год | n closed | W | L | WR | PnL R |
|---|---|---|---|---|---|
| 2023 | 1 | 0 | 1 | 0%   | -1R |
| 2024 | 6 | 2 | 4 | 33%  | -2R |
| 2025 | 6 | 2 | 4 | 33%  | -2R |
| 2026 (4 мес) | 2 | 1 | 1 | 50% |  0R |

**Стабильно слабо-отрицательно во всех 4 годах.** Выборки крошечные
(1-6/год), но направление чёткое.

### LONG vs SHORT

| Dir | total | closed | WR | PnL |
|---|---|---|---|---|
| LONG | 58 | 7 | 28.6% | −3R |
| SHORT | 53 | 8 | 37.5% | −2R |

Симметричны по total. Обе убыточны. Разница ±1 на 7-8 сделках = шум.

### Распределение по геометрии (deduped)

```
top_tf  macro_tf  htf_tf   n      %
12h     4h        1h       43    39%
1d      4h        1h       20    18%
12h,1d  4h        1h       15    14%
12h     6h        1h       13    12%
12h,1d  6h        1h        6     5%
1d      6h        1h        5     5%
12h     4h        2h        3     3%
12h     6h        2h        2     2%
12h,1d  4h        1h,2h     1     1%
12h,1d  4h,6h     1h        1     1%
12h,1d  6h        2h        1     1%
1d      6h        2h        1     1%
```

70% сетапов через `*, 4h, 1h`. 2h-htf и 6h-macro дают мало добавки.

## Lookahead-bug история (2026-05-06)

Первый прогон: WR 27% / −10R на 22 closed. Пользователь сверил с TV
и заметил аномалию 2026-02-14: htf-FVG (1h) на 02-17 00:00 при том,
что cur 6h-macro закрывалась только в 02-17 03:00. То есть «реакция»
формировалась ДО формирования макро-структуры.

**Корень:** в `find_first_fvg_htf_in_zone` параметр `htf_hours`
использовался для смещения от ob_macro.cur_time, должен быть
`macro_hours`. Длительность бара выводилась из ТФ поиска, не из
ТФ candidate-структуры.

После fix'а: −5R вместо −10R, WR 33% вместо 27%, 15 closed вместо 22.
7 «магических» сигналов вычистились — все они оказались убыточными
(в основном). Это типичный паттерн: lookahead-fix не улучшает edge,
а делает его реальный показатель честнее.

Детально: [[strategy-1-1-6-look-ahead-macro-htf]].

## Известные ограничения

- **Только BTCUSDT, 3y in-sample.** Walk-forward / OOS / cross-symbol
  не делали — но edge всё равно отрицательный, оптимизировать пока нечего.
- **NO_ENTRY 86%** — mid-FVG entry слишком оптимистична. Цена идёт
  быстро, mid пропускается. Кандидат на улучшение: vary entry_pct
  (по аналогии с 1.1.1 Stage 1).
- **70% через одну геометрию** (`*, 4h, 1h`). Можно упростить
  детектор до htf=1h only — потеря небольшая.
- **Closed=15 на 3y = 5/год** — выборка маленькая, выводы шумные.
  Но направление (отрицательное) одинаковое во всех 4 годах.

## Live deployment

**Не интегрирована в live.** Сознательное решение пользователя
2026-05-06: зафиксировать в research, в бот не добавлять. Edge не
подтверждён, NO_ENTRY 86% делает live-исполнение проблематичным
(нужны настоящие limit-orders + симуляция отмены).

## Файлы

- [strategies/strategy_1_1_6.py](../../../strategies/strategy_1_1_6.py) — детектор
- [research/1_1_6/backtest/backtest_strategy_1_1_6.py](../../../research/1_1_6/backtest/backtest_strategy_1_1_6.py) — backtest
- [tests/test_strategy_1_1_6.py](../../../tests/test_strategy_1_1_6.py) — 6 unit-тестов
- `signals/backtest_strategy_1_1_6.csv` — 111 deduped (gitignored)

## Связи

- [[strategy_1_1_1]] — родительская стратегия с прямой структурой
- [[универсальные определения OB и FVG]] — canon формул
- [[strategy-1-1-6-look-ahead-macro-htf]] — найденная грабля
- [[strategy-1-1-1-look-ahead-15min-vs-tf_duration]] — родственный bug
- [[2026-05-06-strategy-1-1-6-первый-прогон]] — session note
