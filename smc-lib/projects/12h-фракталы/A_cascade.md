# A — Cascade (отсекаем лишнее)

4-стадийный фильтр кандидатов на pivot bar.
Цель: на выходе остаются bar'ы с шансом сформировать Williams n=2 фрактал ≥ baseline 48.6%.

## Логика

Все стадии **AND**, применяются последовательно. На выходе: `mask_A4_short`, `mask_A4_long`.

### A1 — Pre-W (3-bar local extreme)

3-свечный локальный экстремум.

```
FH-кандидат i:  high[i] > high[i-1]  AND  high[i] > high[i-2]
FL-кандидат i:  low[i]  < low[i-1]   AND  low[i]  < low[i-2]
```

### A2 — ext_5 (был F1)

5 свечей левее меньший экстремум.

```
FH:  high[i] > max(high[i-5..i-1])
FL:  low[i]  < min(low[i-5..i-1])
```

### A3 — color (был F2)

Смена цвета на i-1, i **ИЛИ** 3 подряд однонаправленные (без доджей).

```
non_doji = (close != open)

opp_colors:   color[i] != color[i-1]   (оба non_doji)
three_same:   color[i] = color[i-1] = color[i-2]   (все non_doji)

A3 = (opp_colors OR three_same)
```

### A4 — body+wick (был F3)

Убирает признаки марубозу.

```
body_pct       = |close - open| / (high - low)
upper_wick_pct = (high - max(open, close)) / (high - low)
lower_wick_pct = (min(open, close) - low)  / (high - low)

A4(FH):  body_pct ≤ 0.80  AND  upper_wick_pct ≥ 0.03
A4(FL):  body_pct ≤ 0.80  AND  lower_wick_pct ≥ 0.03
```

## Параметры (зафиксированы)

```python
LEFT_EXT_N    = 5
SAME_COLOR_N  = 3
BODY_MAX      = 0.80
WICK_MIN      = 0.03
DOJI_EPS      = 0.0   # color tie = close == open exactly
```

## Confirmation (Williams n=2 right)

Pivot i считается **confirmed**, если:

```
FH:  high[i+1] < high[i]  AND  high[i+2] < high[i]
FL:  low[i+1]  > low[i]   AND  low[i+2]  > low[i]
```

## Текущие цифры (2020-01-01 → now, 4 698 12h-баров)

| stage | n | conf | WR | Δ |
|---|---:|---:|---:|---:|
| A1 Pre-W   | 3 099 | 1 289 | 41.59% | base |
| A2 ext_5   | 2 031 |   866 | 42.64% | +1.05 |
| A3 color   | 1 507 |   677 | 44.92% | +2.28 |
| **A4 final** | **1 356** | **659** | **48.60%** | +3.68 |

## Код

- **Скрипт:** `~/smc-lib/scripts/pred12h_baseline_v2.py`
- **Output parquet:** `~/Desktop/pred12h_baseline_v2.parquet`
  Колонки: `pivot_open_ts_ms`, `direction`, `confirmable`, `confirmed`, `body_pct`, `wick_pct`, `color`.

## Зависимости вниз

A4-output (1 356 кандидатов) — это **домен** для всех B-блоков.
Каждый Bx evaluate'ит свою логику и **матчит** с подмножеством A4 — выдаёт `(k, direction) → confirmed`.
