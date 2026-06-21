---
tags: [session, pivot, pred12h, c8, force, phase4, strategy-1-1-1, floating, strict, lookahead, library-refactor]
date: 2026-06-01
status: completed
---

# Pivot project → pred12h C8 force, strict lookahead-safe backtest

Полнодневная сессия 2026-06-01. Стартовали с реорганизации библиотеки (раздел `strategies/`), затем создали pivot-проект под 50x leverage и 12h pivot-фильтр. Pivot выявил, что архитектурно он = Strategy 1.1.1 V2. Lookahead-версия фильтра дала впечатляющие +132R/PF 3.47/WR 62%, но strict-переработка показала **противоположный результат**: pred12h basket НЕ улучшает Strategy 1.1.1 (+89R vs pure floating +196R). Добавлена гипотеза C8 = Phase 4 force-match, прогнана batch на 6y BTC, найдены лучшие параметры — но даже они не превосходят pure floating в strict mode. Важный негативный результат с lookahead-урокa.

## Хронология

### Часть 1: Library refactor — раздел `strategies/`

Создан новый раздел `~/smc-lib/strategies/` (lowercase plural, согласован с canon: `elements/`, `indicators/`, `patterns/`).

**Перенесено из `projects/`** → `strategies/strategy_1_1_1/`:
- `strategy_1_1_1_floating.{py,pdf}` (production reference от etap108, **НЕ редактировать**)
- `strategy_1_1_1_v2.py` + `strategy-1-1-1-v2.md` (V2 design)
- `strategy_ob_vc_v1rules/` (backtest harness)

**Обновлены sys.path в 5 файлах** (импорты сохранены):
- `projects/bb_dataset/builder_v2.py`, `builder_v2_parallel.py` (×2), `builder_v3_parallel.py` (×2)
- `strategies/strategy_1_1_1/strategy_ob_vc_v1rules/backtest.py` (+ `out_dir` для `trades.csv`)
- `strategies/strategy_1_1_1/strategy_1_1_1_v2.py`

**Создано:**
- `strategies/README.md` — индекс раздела
- `strategies/strategy_1_1_1/README.md` — v1/v2/floating + архитектура каскада

Smoke-test импортов: ✓ `strategy_1_1_1_floating` и `backtest` загружаются из нового пути.

**Уточнение по floating.py от разработчика etap108**: это reference (тот же v1 cascade detector + Floating TP + 4-indicator score + per-symbol configs), не V1 production. V1 prod = `~/traid-bot/strategies/strategy_1_1_1.py`.

### Часть 2: Pivot project — design

Создан `projects/pivot.md`. Цель — отбор качественных точек разворота тренда. Изначально с 10x leverage / 8-12 trades/мес.

**Закрыто 8 design-вопросов**:
- Q1: label = Williams n=2 на 12h + |move to next opposite| ≥ 2%
- Q2: главный ТФ = 12h (LTF swing pivots, не D trend reversal)
- Q3: SL ≤ 1% структурный (при 50x), RR ≥ 2
- Q4: precision target ≥ 0.60
- Q5: гибрид strict cascade ∩ 12h pivot filter
- Q6: основной finger = pred12h F1∩F2∩F3 + OR-basket C1-C7
- Q7: BTC 6y in-sample
- Q8: 8-12 trades/мес target

**Важная реформулировка**: leverage 10x → **50x** после скриншота пользователя с 11 12h pivot за 5 недель (= 8-12/мес).

### Часть 3: 4-level rule = Strategy 1.1.1 V2

Пользователь зафиксировал 4-уровневую архитектуру:
- Уровень 1: D, 12h (macro HTF)
- Уровень 2: 6h, 4h (macro LTF)
- Уровень 3: 2h, 1h (entry HTF)
- Уровень 4: 15m, 20m (entry LTF)

Зона 1 = L1+L2 → macro `ob_vc(D/12h, 4h/6h)`
Зона 2 = L3+L4 → entry `ob_vc(1h/2h, 15m/20m)`

**Полное совпадение** со Strategy 1.1.1 V2 (`strategies/strategy_1_1_1/strategy-1-1-1-v2.md`). Pivot-проект = переиспользование уже описанного каскада под новый rubric (50x / ≥2% / 12h pivot).

### Часть 4: Floating BTC 6y baseline

Pure floating BTC fresh run (6.09 лет, R_cap=4.5, threshold=-0.25, confirm=2, etap108 D-winner config):

| Метрика | Значение |
|---|---:|
| Years | 6.09 |
| SWEPT signals | 688 |
| Closed trades | 378 (W=194, L=184) |
| WR | 51.32% |
| **Total R** | **+195.87R** |
| RR (\|w/l\|) | 2.090 |
| **PF** | **2.204** |
| Avg win | +1.848R |
| Avg loss | −0.884R |
| Median R | +0.074R |
| top5% concentration | 11.5% |

By year: bad years 1/7 (2020 partial −6.95R). 2021-2026 все положительные.
By exit: R_cap (53 trades, +238R) — главный driver; score_exit (172, +110R); sl_hit (153, −153R).

### Часть 5: LOOKAHEAD pivot filter — иллюзия +132R / PF 3.47

Lookahead-версия фильтра: Williams n=2 на 12h + ≥2% move + direction match.
Window: `[pivot.open, next_opposite.open)` — pivot.open неизвестен в реальном времени!

| | Pure floating | + Williams+2% (lookahead) |
|---|---:|---:|
| Total R | +195.87R | +132.28R |
| n trades | 378 | 164 |
| WR | 51.3% | **61.6%** |
| RR | 2.09 | 2.16 |
| **PF** | 2.20 | **3.47** |
| freq/мес | 5.17 | 2.24 |

Впечатляющий +57% PF. **Но это lookahead bias** — entry разрешены ВНУТРИ pivot-бара, когда Williams ещё не подтверждён (+24h confirmation lag) и ≥2% move до next opposite вообще из будущего.

Пользователь поймал баг: «в момент входа в сделку ты еще не знаешь что это будет фрактал».

### Часть 6: C8 = Phase 4 force-match гипотеза

Проверка 4 missed pivot'ов (06-05, 10-05, 13-05, 18-05) через Phase 4 `force_opinion`:

| Pivot | Side | BIAS | n_wins | match |
|---|---|---|---:|---|
| 06-05 03:00 #48 ATH | FH | UNANIMOUS BEARISH | 0/9 | ✓ |
| 10-05 03:00 LH retest | FH | UNANIMOUS BEARISH | 0/9 | ✓ |
| 13-05 03:00 sweep FL | FL | **PIVOT signature** | 7/9 | ✓ |
| 18-05 03:00 BOS down FL | FL | HTF BULLISH | 7/9 | ✓ |

**4 из 4 force-match** в нужную сторону. 13-05 явно label «PIVOT signature» — собственный термин Phase 4. **Сильное подтверждение** что Phase 4 catches то, что C1-C7 zone-touching upstream миссит.

### Часть 7: Рейтинг 12h-баров мая 2026 по силе

62 12h-бара мая ранжированы по |NET force|. Топ-1 = **2026-05-23 03:00**:
- NET +4604 (9/9 BULLISH)
- Top LONG zones: 3d OB (716, 27d), 3d OB (590, 18d), 3d RDRB (494, 30d)
- Цена 74 790 (бар сформировал low 74 290)
- Next 24h: +3.7% bounce

Формула силы Phase 4:
```
strength(zone) = TF_weight × age_factor × class_weight × proximity × mit_w
```
3D dominance (TF_weight=72) даёт почти половину total NET в топовых барах.

Все 4 missed pivot'а попали в TOP 33/62 рейтинга. Phase 4 рейтинг **накапливает силу за 1-2 бара ДО pivot bar** — сильный предиктивный сигнал.

### Часть 8: STRICT lookahead-safe rewrite

Перестроена архитектура grid search v2 как **strict** изначально:
- Trade-окно открывается на **close** pivot-бара i (когда pred12h+C8 уже causally вычислимы)
- Закрывается на следующем opposite predicted pivot OR max_hold = 60h (5 баров)
- Direction matched (FH → SHORT, FL → LONG)

### Часть 9: Batch Phase 4 — chunked architecture

Первая попытка нечанкованного батча: **3 часа без вывода**, slowdown O(N²) в snapshot_from_events (sequential scan по растущему списку events).

Переписано в чанкование по 365 дней с 180d warmup:
```python
for chunk in 6 chunks:
    precompute_zone_events(1m_window_545d)  # ~50s
    snapshot_from_events для пивотов в chunk  # ~0.5s/pivot
```

**Итого 22.9 мин на 1272 пивота** (vs 5+ часов в нечанкованном). Кэш в `~/Desktop/pred12h_C8_force_6y.parquet`.

Quick stats:
- Confirmed: 619/1272 = 48.7%
- Force-match: 938/1272 = 73.7%
- Confirmed AMONG force-match: **43.5%** (ниже baseline 48.7%!) — стандалон force-match слишком broad

### Часть 10: STRICT grid search v2 — НЕГАТИВНЫЙ РЕЗУЛЬТАТ

Grid 1280 комбинаций (`abs_net`, `d3`, `wins_fh`, `wins_fl`, `bias`):

| Конфигурация | Total R | WR | PF | RR | freq/мес |
|---|---:|---:|---:|---:|---:|
| **Pure floating (без фильтра)** | **+195.87R** | 51.3% | **2.204** | 2.09 | 5.17 |
| pred12h basket C1-C7 strict | +70.07R | 47.6% | 1.951 | 2.15 | 1.98 |
| **best basket ∪ C8 strict** | +89.74R | 48.7% | 2.179 | 2.29 | 2.13 |

Best C8 params: `abs_net=1000, d3=200, wins_fh=0, wins_fl=6, bias=NOBAL`.

**Pure floating побеждает любую фильтрацию в strict mode**. Pred12h basket снижает Total R на 64% и PF на 0.25. C8 force частично восстанавливает (+19R, +0.23 PF vs basket alone), но всё равно хуже pure floating.

**Frequency 8-12/мес недостижима** в strict mode — максимум 2.13/мес.

## Причина расхождения lookahead vs strict

Pred12h **оптимизирован под Williams confirmation precision**, а не под maximize-floating-PF. Strategy 1.1.1 floating ловит другие setups (ob_vc SWEPT cascade на 1h/2h+15m/20m). **Эти две задачи не выровнены** — фильтрация floating по 12h pivot windows режет хорошие entries floating-а в момент, когда они ещё не «in pivot context».

Lookahead +132R был от entries ВНУТРИ pivot-бара (мы их не можем видеть в реальном времени, т.к. Williams confirmation +24h).

## Артефакты

### Скрипты
- `~/smc-lib/scripts/pred12h_C8_force_batch.py` — первый (нечанкованный) batch — DEPRECATED
- `~/smc-lib/scripts/pred12h_C8_force_batch_chunked.py` — **chunked batch** (22.9 мин на 6y)
- `~/smc-lib/scripts/pred12h_basket_export.py` — F1∩F2∩F3 + C1-C7 в parquet
- `~/smc-lib/scripts/pred12h_floating_export.py` — pure floating signals + trades в parquet
- `~/smc-lib/scripts/pred12h_C8_grid_search_strict.py` — STRICT grid search (lookahead-safe windows)

### Parquet кэши
- `~/Desktop/pred12h_baseline_c1c7.parquet` — 1272 пивота × C1-C7 flags
- `~/Desktop/pred12h_C8_force_6y.parquet` — 1272 пивота × Phase 4 metrics (total_net, d3_net, n_wins, bias, top_long/short_str, force_match)
- `~/Desktop/floating_btc_6y_trades.parquet` — 688 floating signals + trades (signal_time, direction, outcome, R, exit_reason)
- `~/Desktop/pred12h_C8_grid_strict_results.parquet` — 1280 grid combinations × stats

### Документация
- `~/smc-lib/projects/pivot.md` — pivot session summary, помечен **validated → merged into pred12h**
- `~/smc-lib/projects/README.md` — обновлён
- `~/smc-lib/strategies/README.md` + `strategies/strategy_1_1_1/README.md` — новый раздел

### Конфигурация expert chart
- `~/smc-lib/expert/chart.py`:
  - `anchor_horizon`: 180 → **1100 дней** (расширен поиск VWAP anchors)
  - `top_below`: 2 → **4** (4 VWAPs снизу)
  - Добавлен **`pick_diverse(min_dist_pct=1.0)`** — фильтр min разнос между picked VWAPs

## Решения и выводы

### Подтверждено
- **Library refactor**: `strategies/` lowercase plural, переиспользует canon ob_vc
- **Pivot 4-level rule = Strategy 1.1.1 V2** структурно идентично
- **Phase 4 force** действительно catches missed pivots с direction match (4 из 4 в мае)
- **Phase 4 batch** работоспособен в chunked-режиме (22.9 мин на 6y BTC)

### Опровергнуто
- **Pred12h НЕ улучшает Strategy 1.1.1 в strict mode**. +132R lookahead был иллюзией
- **8-12/мес недостижима** в strict — max 2.13/мес
- **Hybrid (cascade ∩ pivot filter)** не работает с floating exit-машинерией без переобучения

### Открытые вопросы
- **Что делает Strategy 1.1.1 v1.5+**: переориентировать под pivot или оставить как есть? Pure floating уже максимизирует доступное на BTC.
- **Pred12h как самостоятельный layer**: возможно отдельная trade-стратегия с custom entry/SL/TP под pred12h (вместо floating)
- **OOS на ETH/SOL**: pred12h условия валидированы только на BTC 6y
- **C8 без C1-C7**: что если basket = ТОЛЬКО force, без OR с zone-touching?

## Memory updates

- В index добавлена ссылка на эту сессию (через [[2026-06-01-pivot-project-pred12h-c8-force-strict-grid-search]])
- Memory `feedback-pred12h-strict-vs-lookahead`: lookahead Williams+2% завышает результат на 50%+ (132 vs 90 R)
- Memory `prediction-algo-final-results` остаётся в силе для отдельных predict-задач, но не для downstream-floating

## Связанное

- `[[2026-05-31-phase3-results-phase4-force-framework]]` — Phase 4 framework, на котором основан C8
- `[[strategy-1-1-1-floating-tp-final]]` — etap108 reference, использованный как baseline
- `[[pred12h-fractal-three-candles]]` — пред12h spec
- `[[12h-fractal-prediction-final-strategy]]` — старая 12h strategy ((sweep_FH ∪ OB_sweep) ∩ sweep_maxV)
- `[[pivot-money-hands]]` — соседний 1h pivot модуль
