---
tags: [session, strategy, strategy-1-1-1, backtest]
date: 2026-04-28
related: [[strategy_1_1_1]], [[универсальные определения OB и FVG]]
---

# Сессия 2026-04-28 (вечер): Strategy 1.1.1 — расширение до 2h × 20m + prev-day FVG-4h

Продолжение [[2026-04-28-strategy-1-1-1-vic-bos-research]]. Итеративные правки
Strategy 1.1.1 после первого 3y-бэктеста (69 сигналов, +4R).

## Что сделано

### 1. CSV reorganized для бэктеста

Перестроен `signals/strategy_1_1_1_3y_RR1.csv`:

- Первые 4 колонки = ключевые времена зон в **UTC+3** (`YYYY-MM-DD HH:MM`):
  `ob_d_time`, `fvg_4h_time`, `ob_htf_time`, `fvg_time`
- Helper `to_utc3(ts)` = `(ts + Timedelta(hours=3)).strftime(...)`
- `activation_time` и `exit_time` тоже в UTC+3 для согласованности
- Удалены избыточные `ob_d_prev_time`, `fvg_4h_c0_time` и т.п. (только cur/c2)

### 2. FVG-20m параллельно FVG-15m

Добавлен поиск FVG-20m на entry-уровне. **Если есть оба — берём первый по `c2_time`.**

20m строится через `compose_from_base(df_1m, "20m")` (resample 1m → 20m, выровнено
по эпохе → 00:00, 00:20, 00:40 — совпадает с границами 1h).

Окна поиска:
- 15m: `[ob_htf.prev, ob_htf.cur + 45min]` (4 candle для 1h cur)
- 20m: `[ob_htf.prev, ob_htf.cur + 40min]` (3 candle для 1h cur)

Helper `find_first_fvg_in_range(df, start, end, dir, ob_b, ob_t)`.

**Прогон:** 70 сигналов (vs 69), WR 53.7% / +5R. 51 взяли 15m, 19 взяли 20m.

### 3. OB-2h параллельно OB-1h

Добавлен полный mirror 1h-логики на 2h:
- Та же `find_search_end_htf` (rename из `find_search_end_1h`)
- 2h строится через `compose_from_base(df_1h, "2h")`
- Окна 15m/20m расширяются пропорционально длине htf candle:
  - 1h: `+45min` для 15m, `+40min` для 20m
  - 2h: `+105min` для 15m, `+100min` для 20m
- Параметризация через `htf_minutes` в `find_signal_in_htf(...)`

**Выбор:** на одну (OB-D, FVG-4h) пару — поиск 1h и 2h независимо, далее
из 4-х возможных комбинаций (1h+15m, 1h+20m, 2h+15m, 2h+20m) берём с самым
**ранним c2_time** entry FVG.

CSV: `ob_1h_*` → `ob_htf_*` + новая колонка `ob_htf_tf` (`1h`/`2h`).

**Прогон:** 93 сигнала (vs 70), WR 55.7% / +10R. 51 на 1h, 42 на 2h.

### 4. Prev-day FVG-4h с invalidation-check

Релаксация фильтра по c2 FVG-4h. **Раньше:** строго в cur_day OB-D.
**Теперь:** prev_day OK, если FVG не была перекрыта по wick до конца cur_day.

Конкретный кейс пользователя: OB-D 19/20 мая 2025 → FVG-4h `2025-05-19 19:00 UTC+3`
раньше отбрасывалась, теперь даёт win.

Логика invalidation:
- Окно проверки = `[c2_close, end_of_cur_day]` (закрытие c2 = `c2_open + 4h`)
- LONG invalidation: любая 4h-свеча с **`low < fvg.bottom`** (по wick)
- SHORT invalidation: любая 4h-свеча с **`high > fvg.top`** (по wick)
- Single wick = invalidation. Не 2 подряд close, не close-based.

**Уточнение от пользователя:** «fvg считается перекрытым, если low свечи ниже него
для лонг fvg, и high выше, если шорт fvg». Изначальная реализация была close-based,
заменена на wick-based.

**Прогон:** 98 сигналов, WR 56.5% / +12R.

## Финальные результаты на 3y BTC RR=1

| Стадия | Signals | WR | PnL | LONG | SHORT |
|---|---|---|---|---|---|
| Baseline (1h + 15m, cur_day FVG-4h) | 69 | 53.0% | +4R | 26/57.7%/+4R | 40/50%/0R |
| + FVG-20m | 70 | 53.7% | +5R | 27/59.3%/+5R | 40/50%/0R |
| + OB-2h | 93 | 55.7% | +10R | 40/57.5%/+6R | 48/54.2%/+4R |
| **+ prev-day FVG-4h (wick inval)** | **98** | **56.5%** | **+12R** | 42/59.5%/+8R | 50/54.0%/+4R |

По годам:
- 2023: 19 / 42.1% / −3R
- 2024: 28 / 60.7% / +6R
- 2025: 38 / 55.3% / +4R
- 2026 (4м): 7 / 85.7% / +5R

Распределение по выбранному пути:
- HTF: 54 на 1h, 44 на 2h (≈45% сигналов из 2h)
- Entry: 72 на 15m, 26 на 20m (≈27% на 20m)

## Ключевые рефакторинги в коде

**`strategies/strategy_1_1_1.py`:**
- `find_search_end_1h` → `find_search_end_htf` (generic, без bind к 1h)
- Новый helper `find_first_fvg_in_range(df, start, end, dir, ob_b, ob_t)` —
  переиспользуется для 15m и 20m.
- Новый helper `find_signal_in_htf(df_htf, ..., htf_minutes, htf_label)` —
  инкапсулирует поиск (OB-htf + entry FVG) для одного htf-таймфрейма.
- Главный цикл: для каждой (OB-D, FVG-4h) → `find_signal_in_htf` × 2 (1h + 2h),
  выбор по `fvg_entry.c2_time`.

**`backtest_strategy_1_1_1.py`:**
- `df_2h = compose_from_base(df_1h, "2h")`
- `df_20m = compose_from_base(df_1m, "20m")`
- Все 6 фреймов передаются в детектор: `(1d, 4h, 1h, 2h, 15m, 20m)`.

## Несколько правок дизайна

1. **«Один сигнал на (OB-D, FVG-4h) пару»** сохранён. На две FVG-4h к одному
   OB-D — **два разных сигнала** (как просил пользователь). 10 OB-D в 3y CSV
   имеют по 2 сигнала.

2. **Иногда два сигнала указывают на один и тот же OB-htf + entry FVG**
   (например, `2023-06-02`: обе FVG-4h дают OB-1h `2023-06-04 01:00` /
   FVG-15m `01:15`). Дедупа нет — каждая FVG-4h = отдельная ситуация.

3. **Earliest-wins** правило применяется на 2-х уровнях:
   - При выборе entry FVG (15m vs 20m) внутри одного OB-htf
   - При выборе htf path (1h vs 2h) внутри одной (OB-D, FVG-4h)

## Insights

- **2h добавил больше edge, чем 20m.** 1h+15m → 1h+15m+20m: +1 сигнал, +1R.
  1h+15m+20m → 1h/2h+15m+20m: +23 сигнала, +5R. 2h-уровень даёт более стабильные
  setups (видимо потому что цена дольше формирует структуру).
- **Prev-day FVG-4h работает.** Релаксация c2-фильтра дала +5 сигналов
  (3W/2L/0NF + удаление 1L через wick-инвалидацию = +1R). Идея «хорошая
  FVG-4h, не задетая до открытия cur day» = валидный сетап.
- **SHORT улучшился больше всех.** 50%/0R → 54%/+4R. Вероятно prev-day FVG-4h
  чаще валидны на боковиках (без сильного хода), что любит SHORT-направление.

## Файлы

**Изменены:**
- `strategies/strategy_1_1_1.py` — новые helpers, multi-htf, prev-day FVG-4h
- `backtest_strategy_1_1_1.py` — UTC+3, df_2h/df_20m, новые CSV колонки

**CSV:**
- `signals/strategy_1_1_1_3y_RR1.csv` — 98 сигналов, 4 time columns + tf indicators

## Что дальше

- Strategy 1.1.1 — продолжать итерации (selective, ~33 сигнала/год — приемлемо
  для активной стратегии).
- ETH/SOL прогоны для проверки переносимости edge.
- Если результаты держатся на других монетах — кандидат на live deployment.

## Связи

- [[strategy_1_1_1]] — обновлённая спецификация
- [[универсальные определения OB и FVG]] — canon формул
- [[2026-04-28-strategy-1-1-1-vic-bos-research]] — предыдущая сессия
