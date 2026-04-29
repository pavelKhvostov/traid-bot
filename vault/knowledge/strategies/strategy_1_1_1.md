---
tags: [strategy, multi-tf, ob, fvg, strategy-1-1-1]
date: 2026-04-29
status: live-backtest
related: [[универсальные определения OB и FVG]], [[что такое order block]], [[что такое fvg]]
---

# Strategy 1.1.1 — OB-D/12h + FVG-4h/6h → OB-1h/2h + FVG-15m/20m

## Концепт

Многоуровневая вложенная зона: **top OB** (1d или 12h) подтверждается
**macro FVG** (4h или 6h) → внутри этой макро-зоны ждём **OB-htf** (1h
или 2h), подтверждённый **entry FVG** (15m или 20m).

Используются [[универсальные определения OB и FVG]] (canon).

Strategy backtest-only (в live не интегрирована).

## Логика поиска (4 уровня × 2 ТФ = 16 комбинаций путей)

### Шаг 1: Top OB — 1d ИЛИ 12h (параллельные ветки)

Сканируем top-OB пары на обоих ТФ независимо:
- **1d:** `top_tf_hours = 24`
- **12h:** `top_tf_hours = 12`

Для каждой ветки реализован `_scan_top(df_top, top_tf_hours, top_label)`
в [strategies/strategy_1_1_1.py](../../../strategies/strategy_1_1_1.py).

OB top:
- **LONG:** prev медвежья (`close < open`), cur.close > prev.open.
  Zone = `[min(prev.low, cur.low), prev.open]`.
- **SHORT:** prev бычья, cur.close < prev.open.
  Zone = `[prev.open, max(prev.high, cur.high)]`.

### Шаг 2: Macro FVG — 4h ИЛИ 6h

`collect_valid_macro_fvgs(df_macro, ob_top, htf_hours, top_tf_hours)`.

Macro FVG должна:
- быть того же направления что top-OB
- **c2 в `[prev_time, cur_time + top_tf_hours h)`** top-OB
- `c2_open ≤ cur_time + (top_tf_hours - htf_hours)h` — candle полностью
  закрывается до конца cur top-bar
- **Зона FVG попадает в top-OB**:
  - LONG: `top.bottom ≤ FVG.bottom ≤ top.top`
  - SHORT: `top.bottom ≤ FVG.top ≤ top.top`

**Если c2 в prev_bar** (= `c2.c2_time < ob_top.cur_time`) — дополнительный
invalidation-check на свечах того же ТФ в окне `[c2_close, end_of_cur_bar]`:
- LONG: любая `low < fvg.bottom` → отбрасываем
- SHORT: любая `high > fvg.top` → отбрасываем
- Single wick = invalidation. Закрепление (close) не требуется.

**Каждая валидная macro FVG = отдельная ситуация** (несколько macro FVG
на одно top-OB = несколько кандидатов сигналов; на dedup-уровне они
схлопываются если ведут к одной (entry, sl), см. ниже).

### Шаг 3: OB-1h И OB-2h параллельно

Для каждой пары (top OB, macro FVG) запускаем независимый поиск на 1h
**и** на 2h. 2h строится из 1h через `compose_from_base(df_1h, "2h")`.

**search_start:** `ob_top.cur_time + Timedelta(hours=top_tf_hours)`
(момент закрытия cur top-bar). Для 12h-top нет `.normalize()` — это
важно, иначе границы 12:00 UTC будут сломаны.

**Стоп-правило:** при формировании фрактала ниже macro FVG (LONG) /
выше macro FVG (SHORT) — OB-htf с `cur` в индексе `≤ j+2` (внутри
фрактала) ещё валидна; дальше FVG считается невалидной, поиск
прекращается.

**OB-htf требования:**
- Совпадает направлением с top-OB
- Пересекается с macro FVG И с top-OB через `zones_overlap`

### Шаг 4: Entry FVG — 15m ИЛИ 20m, ранний выигрывает

Для каждого валидного OB-htf:
- FVG-15m в окне `[ob_htf.prev_time, ob_htf.cur_time + (htf_minutes - 15)]`
- FVG-20m в окне `[ob_htf.prev_time, ob_htf.cur_time + (htf_minutes - 20)]`

Конкретно:
- 1h OB: 15m в `[prev, cur+45min]`, 20m в `[prev, cur+40min]`
- 2h OB: 15m в `[prev, cur+105min]`, 20m в `[prev, cur+100min]`

**Выбор entry FVG:** если найдены оба — берём с более ранним `c2_time`.

### Шаг 5: Earliest-wins на htf-уровне

Если найден сигнал и на 1h, и на 2h — берём с более ранним
`fvg_entry.c2_time`.

### Entry / SL / TP

- **Entry** = середина выбранной FVG (`(bottom + top) / 2`).
- **SL:** `top.bottom` (LONG) / `top.top` (SHORT) — без буфера.
- **TP** = `entry ± risk × RR` (RR=1.0 default; RR=2.2 параллельно).

## Дедуп (на уровне `backtest_strategy_1_1_1.dedupe_signals`)

Стратегия возвращает **сырые** сигналы (по одному за каждый путь
top × macro × htf). Дедуп выполняется в backtest-слое, не в детекторе.

**Ключ:** `(signal_time, direction, round(entry, 8), round(sl, 8))`.

Расширение ключа на SL — следствие того, что разные top-OB могут
указать на одну entry FVG, но с разными bottoms (= разными SL = разными
risk = разными trades). См. [[strategy-1-1-1-разные-sl-на-одном-entry]].

**Меta-поля при схлопывании группы:**
- `top_tf`: `,`-joined sorted-uniq (`"1d"`, `"12h"`, или `"12h,1d"`)
- `top_tf_count`: количество разных top_tf
- `ob_d_time`: earliest top OB cur_time в группе (legacy-имя сохранено)
- `fvg_macro_time`: earliest c2_time
- `fvg_macro_tf`: `,`-joined (`"4h"`, `"6h"`, `"4h,6h"`)
- `fvg_macro_count`: число разных c2_time
- `ob_htf_time`: earliest cur_time
- `ob_htf_tf`: `,`-joined (`"1h"`, `"2h"`, `"1h,2h"`)
- `ob_htf_count`: число разных cur_time

**Outcome-зависимые поля** (entry, sl, tp, outcome, exit_time, exit_price,
hit_type, mfe_pct, mae_pct, fvg_time, fvg_tf, fvg_zone) **обязаны
совпадать** во всех строках группы — проверка `assert` с диагностикой.

## Backtest симуляция

`simulate_outcome` симулирует выполнение лимит-входа на 1m:
- **fill_scan_start** = `signal_time + tf_minutes` (15 для 15m, 20 для
  20m FVG). Это close c2 entry-свечи. Хардкод `+15min` ранее давал
  5-мин look-ahead на 20m сигналах — пофикшено в Ф1.
  См. [[strategy-1-1-1-look-ahead-15min-vs-tf_duration]] и
  [[strategy-1-1-1-почему-20m-фикс-нулевой-эффект]].
- После fill — SL/TP по 1m loop без EOD-cutoff.

## CSV layout (после dedup)

| Колонка | Тип | Пример |
|---|---|---|
| top_tf | str | `"1d"`, `"12h"`, `"12h,1d"` |
| top_tf_count | int | 1, 2 |
| ob_d_time | str UTC+3 | `"2026-02-15 03:00"` |
| fvg_macro_time | str UTC+3 | `"2026-02-15 19:00"` |
| fvg_macro_tf | str | `"4h"`, `"6h"`, `"4h,6h"` |
| fvg_macro_count | int | 1, 2 |
| ob_htf_time | str UTC+3 | `"2026-02-16 16:00"` |
| ob_htf_tf | str | `"1h"`, `"2h"`, `"1h,2h"` |
| ob_htf_count | int | 1 |
| fvg_time | str UTC+3 | `"2026-02-16 16:30"` |
| fvg_tf | str | `"15m"`, `"20m"` |
| direction | str | `"LONG"`, `"SHORT"` |
| entry, sl, tp, risk_pct | float | |
| ob_d_top/bottom, fvg_macro_top/bottom, intersection_top/bottom, ob_htf_top/bottom, fvg_top/bottom | float | |
| activation_time, fill_delay_min | str/float | |
| outcome | str | `win`, `loss`, `not_filled`, `open` |
| exit_time, exit_price, hit_type | str/float/str | |
| mfe_pct, mae_pct | float | |

## Результаты на 3 года BTC (2023-04 — 2026-04, после Ф1-Ф3)

### Общая сводка (RR=1.0, deduped)

| Метрика | Значение |
|---|---|
| Total signals | 144 |
| Closed | 141 |
| Wins | 86 |
| Losses | 55 |
| Not filled | 3 |
| **WR** | **61.0%** |
| **PnL** | **+31R** |

### По годам (RR=1)

| Год | n closed | WR | PnL R |
|---|---|---|---|
| 2023 | 28 | 53.6% | +2R |
| 2024 | 48 | 56.2% | +6R |
| 2025 | 57 | 64.9% | +17R |
| 2026 (4 мес) | 8 | 87.5% | +6R |

2023–2024 показывают здоровый baseline 53–56% WR. 2025–2026 высокие WR
объясняются bull-market drift'ом и малой выборкой 2026.

### По top_tf (RR=1)

| Top TF | n closed | n total | WR | PnL R |
|---|---|---|---|---|
| `"1d"` only | 70 | 73 | 55.7% | +8R |
| `"12h"` only | 57 | 57 | 61.4% | +13R |
| `"12h,1d"` (confluence) | 14 | 14 | **85.7%** | +10R |

**Confluence работает:** сигналы с подкреплением и через 1d, и через
12h дают 85.7% WR на 14 случаях — гипотеза 4-fold confluence
подтверждена. 12h-only ветка не мусорная (61.4% WR), 12h принёс 57
полностью новых сигналов.

### По RR

| Метрика | RR=1.0 | RR=2.2 |
|---|---|---|
| WR | 61.0% | 44.0% |
| PnL | +31R | +57.4R |

WR корректно падает с ростом RR, что подтверждает корректность RR
симуляции.

## Эволюция стратегии (по сессиям)

| Стадия | Signals (raw) | WR | PnL |
|---|---|---|---|
| 1h + 15m, FVG-4h только cur_day | 69 | 53.0% | +4R |
| + FVG-20m параллельно | 70 | 53.7% | +5R |
| + OB-2h параллельно | 93 | 55.7% | +10R |
| + prev-day FVG-4h (wick invalidation) | 98 | 56.5% | +12R |
| + FVG-6h параллельно | 129 | 64.2% | +35R |
| **+ dedup `(signal_time, direction, entry, sl)`** | **87** | **60.7%** | **+18R** |
| **+ OB-12h параллельно (Ф3)** | **144** | **61.0%** | **+31R** |

## Файлы

- [strategies/strategy_1_1_1.py](../../../strategies/strategy_1_1_1.py) — детектор
- [backtest_strategy_1_1_1.py](../../../backtest_strategy_1_1_1.py) — backtest 3y + dedup + simulate
- [tests/test_strategy_1_1_1.py](../../../tests/test_strategy_1_1_1.py) — 8 unit-тестов
- [dump_ob_d_fvg_4h.py](../../../dump_ob_d_fvg_4h.py) — диагностика валидных OB-D + FVG-4h пар
- `signals/strategy_1_1_1_3y_RR{1,2.2}.csv` — результаты бэктеста (gitignored)

## Известные edge cases

1. **FVG-15m в prev period OB-1h:** при OB-1h (23:00, 00:00) FVG-15m
   может образоваться в 23:45. По текущей логике это валидно —
   time range OB-1h включает оба часа. Принято осознанно.

2. **OB-1h поглощает FVG-4h:** когда OB-1h zone больше FVG-4h zone,
   bot/top OB-1h вне FVG-4h, но зоны пересекаются. Реализовано через
   `zones_overlap` — корректно.

3. **Разные SL на одной (signal_time, entry):** легитимный кейс
   2026-02-06. Два не-пересекающихся OB-D привели к одной entry FVG
   через ~16 месяцев. Решено расширением ключа дедупа на SL.
   См. [[strategy-1-1-1-разные-sl-на-одном-entry]].

4. **20m fill look-ahead (теоретический):** mid-of-FVG entry лежит
   вне диапазона c2 → fill внутри c2 невозможен → фикс +15min→+20min
   защитный, не корректирующий числа. См.
   [[strategy-1-1-1-почему-20m-фикс-нулевой-эффект]].

## Live deployment

Пока **только backtest**. Для интеграции в live требуется:
- WS-подписка на 12h (новое), 6h (composed из 1h), 4h, 1h, 2h (composed),
  15m, 20m (composed из 1m), 1m
- Логика дедупа сигналов (адаптировать `dedupe_signals` под потоковую
  модель)
- Адаптация под scanner-архитектуру (см. `vic_scanner.py` как референс)

## Связи

- [[универсальные определения OB и FVG]] — canon формул
- [[что такое order block]] — детальное описание OB
- [[что такое fvg]] — детальное описание FVG
- [[strategy-1-1-1-look-ahead-15min-vs-tf_duration]] — Ф1 фикс
- [[strategy-1-1-1-почему-20m-фикс-нулевой-эффект]] — почему фикс защитный
- [[strategy-1-1-1-разные-sl-на-одном-entry]] — Ф2 расширение dedup-ключа
- [[strategy-1-1-1-dedup-результаты-3y]] — наблюдения до Ф3
- [[s2 ob htf + ob1h]] — родственная стратегия с OB-HTF + FVG-4h фильтром
- [[2026-04-28-strategy-1-1-1-vic-bos-research]] — первая сессия
- [[2026-04-28-strategy-1-1-1-multi-htf-multi-ltf]] — расширение до 2h × 20m
