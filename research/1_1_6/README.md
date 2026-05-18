# Strategy 1.1.6 — FVG-top + OB-macro + FVG-htf (entry на htf-FVG)

Status: **raw baseline отрицательный, в live НЕ добавлен.** Параллельная
ветка к 1.1.1/1.1.2/1.1.3 с инвертированной структурой каскада.

## Идея

```
1.1.1:  OB-top   → FVG-macro → OB-htf  → FVG-entry (младший ТФ)
1.1.6:  FVG-top  → OB-macro  → FVG-htf (entry прямо на htf-FVG)
```

Воронка из 3 уровней × 2 ТФ:
```
FVG-{1d, 12h}   ← top-FVG (обе ветки параллельно, wick-инвалидация)
+ OB-{4h, 6h}   ← macro-OB (earliest-wins), zones_overlap с top (partial)
→ FVG-{1h, 2h}  ← htf-FVG (earliest-wins по c2_close), entry = mid
```

## Параметры

- **entry** = mid htf-FVG = `(htf_fvg.bottom + htf_fvg.top) / 2`
- **SL**:
  - LONG: `ob_macro.bottom`
  - SHORT: `ob_macro.top`
- **TP** = `entry ± risk × RR`, **RR = 1.0** (фиксированный, см.
  `strategies.strategy_1_1_6.RR`)
- **fill-scan** на 1m, начиная с `signal_time + tf_minutes_of_htf_fvg`
  (60 для 1h, 120 для 2h — выводится из `sig["htf_tf"]`)
- **no_entry**: если до касания entry цена коснулась TP или SL —
  outcome=NO_ENTRY (структура отработала без нас)

## Результаты raw baseline (3y BTCUSDT, RR=1.0)

```
raw       = 135
deduped   = 111
closed    = 15  (W=5, L=10)
NO_ENTRY  = 96    (86% — mid-FVG entry слишком оптимистична)
NOT_FILLED= 0
OPEN      = 0
WR        = 33.3%
total PnL = -5.0R
R / trade = -0.333
```

По годам (closed):
| Год | n | W | L | WR | PnL |
|---|---|---|---|---|---|
| 2023 | 1 | 0 | 1 | 0%   | -1R |
| 2024 | 6 | 2 | 4 | 33%  | -2R |
| 2025 | 6 | 2 | 4 | 33%  | -2R |
| 2026 | 2 | 1 | 1 | 50%  |  0R |

**Вывод:** стабильно слабо-отрицательная стратегия. Edge не подтверждён.

## Lookahead-bug найден и исправлен (2026-05-06)

Первый прогон давал WR 27% / -10R на 22 closed. Пользователь заметил,
что сигнал 2026-02-14 имел htf-FVG (1h) до закрытия cur 6h-macro
(htf c2=02-17 00:00, 6h cur_close=02-17 03:00).

**Корень:** `find_first_fvg_htf_in_zone` использовал `htf_start =
ob_macro.cur_time + htf_hours` (1 или 2), вместо `+ macro_hours`
(4 или 6). Длительность бара выводилась из ТФ поиска, а не из ТФ
candidate-структуры. Брат-близнец грабли
[[strategy-1-1-1-look-ahead-15min-vs-tf_duration]].

После fix'а: -5R вместо -10R на 15 closed (вместо 22). 7 «магических»
сигналов вычистились, оказались убыточными.

Детально: `vault/knowledge/debugging/strategy-1-1-6-look-ahead-macro-htf.md`.

## Распределение по геометрии (deduped)

```
top_tf  macro_tf  htf_tf   n      %
12h     4h        1h       43    39%
1d      4h        1h       20    18%
12h,1d  4h        1h       15    14%
12h     6h        1h       13    12%
12h,1d  6h        1h        6     5%
1d      6h        1h        5     5%
... остальное по 1-3
```

70% сетапов через `*, 4h, 1h`. 2h-htf и 6h-macro дают мало добавки.

## Файлы

### backtest/
- `backtest_strategy_1_1_6.py` — raw backtest (RR=1, no_entry, dedup
  bucketing 0.5%)

### optimize/
(пусто; кандидаты на будущее: vary entry_pct, vary sl_pct, SWEPT-аналог
если найдём — но edge'а пока нет)

### analyze/
(пусто)

## Запуск

Из корня репо:
```bash
./venv/bin/python research/1_1_6/backtest/backtest_strategy_1_1_6.py
```

Output: `signals/backtest_strategy_1_1_6.csv`.

## Связано

- `strategies/strategy_1_1_6.py` — детектор
- `tests/test_strategy_1_1_6.py` — 6 unit-тестов
- `vault/knowledge/strategies/strategy_1_1_6.md` — spec
