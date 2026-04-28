---
tags: [strategy, multi-tf, ob, fvg, strategy-1-1-1]
date: 2026-04-28
status: backtest-only
related: [[универсальные определения OB и FVG]], [[что такое order block]], [[что такое fvg]]
---

# Strategy 1.1.1 — OB-D + FVG-4h → OB-1h/2h + FVG-15m/20m

## Концепт

Многоуровневая вложенная зона: дневной OB подтверждается 4h FVG → внутри этой
макро-зоны ждём OB на 1h **или** 2h, подтверждённый FVG на 15m **или** 20m.

Используются [[универсальные определения OB и FVG]] (canon).

## Логика поиска

### Шаг 1: OB-D + FVG-4h (макро-зона)

1. Сканируем дневные пары для OB:
   - LONG OB: prev медвежья, cur.close > prev.open
   - SHORT OB: prev бычья, cur.close < prev.open

2. FVG-4h должна:
   - быть того же направления что OB-D
   - **c2 в prev_day или cur_day OB-D** (т.е. в `[prev_time, cur_time + 1d)`)
   - **Зона FVG попадает в OB-D**:
     - LONG: `OB-D.bottom ≤ FVG.bottom ≤ OB-D.top`
     - SHORT: `OB-D.bottom ≤ FVG.top ≤ OB-D.top`

3. **Если c2 в prev_day** — дополнительный invalidation-check:
   В окне `[c2_close, end_of_cur_day]` (где `c2_close = c2_open + 4h`)
   ни одна 4h-свеча не должна перекрывать FVG **по wick**:
   - LONG invalidation: любая `low < fvg.bottom` → отбрасываем
   - SHORT invalidation: любая `high > fvg.top` → отбрасываем
   Single wick = invalidation. Закрепление (close) не требуется.

4. **Каждая валидная FVG-4h = отдельная ситуация** (несколько FVG-4h на одну
   OB-D = несколько сигналов).

### Шаг 2: OB-1h и OB-2h параллельно

Для каждой пары (OB-D, FVG-4h) запускаем независимый поиск на 1h **и** на 2h.
2h строится из 1h через `compose_from_base(df_1h, "2h")`.

**Окно поиска OB-htf:** со следующего UTC-дня после cur OB-D без time-limit,
до stop conditions:

- **Entered_zone gate:** стоп срабатывает только ПОСЛЕ первого касания зоны
  FVG-4h ценой:
  - LONG: первое касание = `low ≤ fvg_4h.top`
  - SHORT: первое касание = `high ≥ fvg_4h.bottom`
- **Стоп после касания:** 2 подряд htf close на «противоположной» стороне
  - LONG: 2 close < `fvg_4h.bottom`
  - SHORT: 2 close > `fvg_4h.top`

**OB-htf требования:**
- Совпадает направлением с OB-D
- Пересекается с FVG-4h И с OB-D через `zones_overlap` (включая случай
  когда FVG-4h полностью внутри OB-htf)

### Шаг 3: Entry FVG — 15m или 20m, ранний выигрывает

Для каждого валидного OB-htf:
- FVG-15m в окне `[ob_htf.prev_open, ob_htf.cur_open + (htf_minutes - 15)]`
- FVG-20m в окне `[ob_htf.prev_open, ob_htf.cur_open + (htf_minutes - 20)]`

Конкретно:
- 1h OB: 15m в `[prev, cur+45min]`, 20m в `[prev, cur+40min]`
- 2h OB: 15m в `[prev, cur+105min]`, 20m в `[prev, cur+100min]`

**Выбор entry FVG:** если найдены оба — берём с более ранним `c2_time`.

### Шаг 4: Earliest-wins на htf-уровне

Если найден сигнал и на 1h, и на 2h — берём с более ранним `fvg_entry.c2_time`.

### Entry / SL / TP

- Entry = середина выбранной FVG (mid of zone)
- SL = `OB-D.bottom` (LONG) / `OB-D.top` (SHORT) — без буфера
- TP = `entry ± risk × RR` (RR=1.0 default)

## Результаты на 3 года BTC (2023-04 — 2026-04)

| Метрика | RR=1.0 |
|---|---|
| Total signals | 98 |
| Closed | 92 |
| Wins | 52 |
| Losses | 40 |
| Not filled | 6 |
| **WR** | **56.5%** |
| **PnL** | **+12R** |

| Год | n | WR | PnL |
|---|---|---|---|
| 2023 | 19 | 42.1% | −3R |
| 2024 | 28 | 60.7% | +6R |
| 2025 | 38 | 55.3% | +4R |
| 2026 (4м) | 7 | 85.7% | +5R |

| Direction | n | WR | PnL |
|---|---|---|---|
| LONG | 42 | 59.5% | +8R |
| SHORT | 50 | 54.0% | +4R |

| HTF chosen | n | Entry TF | n |
|---|---|---|---|
| 1h | 54 | 15m | 72 |
| 2h | 44 | 20m | 26 |

## Funnel (3 года)

| Этап | Прошло |
|---|---|
| OB-D пар | 273 |
| + валидных FVG-4h (каждая = ситуация) | ~190 |
| + сигнал найден (1h или 2h) | 98 |

## Эволюция стратегии (по сессиям)

| Стадия | Signals | WR | PnL |
|---|---|---|---|
| 1h + 15m, FVG-4h только cur_day | 69 | 53.0% | +4R |
| + FVG-20m параллельно | 70 | 53.7% | +5R |
| + OB-2h параллельно | 93 | 55.7% | +10R |
| + prev-day FVG-4h (wick invalidation) | 98 | 56.5% | +12R |

## Файлы

- [strategies/strategy_1_1_1.py](../../../strategies/strategy_1_1_1.py) — детектор
- [backtest_strategy_1_1_1.py](../../../backtest_strategy_1_1_1.py) — backtest 3y
- [dump_ob_d_fvg_4h.py](../../../dump_ob_d_fvg_4h.py) — список валидных OB-D + FVG-4h пар
- `signals/strategy_1_1_1_3y_RR1.csv` — результаты бэктеста

## CSV layout

Первые 6 колонок (UTC+3):

```
ob_d_time, fvg_4h_time, ob_htf_time, ob_htf_tf, fvg_time, fvg_tf
```

`ob_htf_tf` ∈ {`1h`, `2h`}, `fvg_tf` ∈ {`15m`, `20m`}.

Дальше: `direction, entry, sl, tp, risk_pct`, зоны OB/FVG (`*_top`, `*_bottom`),
исход (`outcome, exit_time, exit_price, hit_type, mfe_pct, mae_pct`).

## Известные edge cases

1. **FVG-15m в prev period OB-1h:** при OB-1h (23:00, 00:00) FVG-15m может
   образоваться в 23:45 (внутри prev hour). По текущей логике
   это считается валидным — time range OB-1h включает оба часа.
   В реал-тайме это lookahead (на 23:45 OB-1h ещё не подтверждена).
   Принято осознанно.

2. **OB-1h поглощает FVG-4h:** когда OB-1h zone больше FVG-4h zone
   (FVG-4h полностью внутри OB-1h), bot/top OB-1h вне FVG-4h, но зоны
   пересекаются. Реализовано через `zones_overlap` — корректно покрывает.

3. **Дубль сигналов от двух FVG-4h:** иногда 2 разных FVG-4h к одному OB-D
   приводят к одному и тому же `(OB-htf, FVG entry)` (например 2023-06-02).
   По текущей логике это две строки CSV (две разных «ситуации» с разными
   FVG-4h validator). Дедупа нет.

## Live deployment

Пока **только backtest**. Для интеграции в live требуется:
- WS-подписка на 4h, 1h, 2h (resampled), 15m, 20m (resampled из 1m)
- Логика дедупа сигналов
- Адаптация под scanner-архитектуру (см. `vic_scanner.py` как референс)

## Связи

- [[универсальные определения OB и FVG]] — canon формул
- [[что такое order block]] — детальное описание OB
- [[что такое fvg]] — детальное описание FVG
- [[s2 ob htf + ob1h]] — родственная стратегия с OB-HTF + FVG-4h фильтром
- [[2026-04-28-strategy-1-1-1-vic-bos-research]] — первая сессия (создание стратегии)
- [[2026-04-28-strategy-1-1-1-multi-htf-multi-ltf]] — расширение до 2h × 20m + prev-day FVG-4h
