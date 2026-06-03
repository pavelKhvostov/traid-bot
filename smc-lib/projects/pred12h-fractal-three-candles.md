# Прогнозирование фрактала 12h по трём свечам (Pred-12h)

## Цель

Предсказать вероятность формирования Williams-фрактала на 12h BTC по **строго causal** информации с трёх свечей (i-2, i-1, i) + дополнительным сигналам, доступным на момент close свечи i.

«Predicted» = свеча i пройдёт Williams-confirmation после i+1, i+2 → станет фактическим FH/FL фракталом.

## Ground truth

- **Данные**: BTC 1m из `~/traid-bot/data/BTCUSDT_1m_vic_vadim.csv` (6 лет), агрегация до 12h.
- **In-sample окно**: 6 лет (2020-05-27 → 2026-05-26).
- **Williams confirm**: для FH — pivot.high > все 2 справа; FL — pivot.low < все 2 справа.
- **Important fractals (imp)**: 18 размеченных пользователем pivots с 2026-02-04 (4-месячное окно).

## Methodology

Двухуровневая архитектура:

```
F1∩F2∩F3 (cascade)  →  baseline 1267 / 619 conf / P=48.9% / 18 imp
        ↓
  + С1 ∪ С2 ∪ … ∪ С7 (OR-basket поверх baseline)
        ↓
  basket 654 / 437 conf / P=66.8% / 15 imp
        ↓
  остаток 613 / 182 conf / 3 missed (#14, #15, #48)
```

### Архитектурные принципы

| Принцип | Описание |
|---|---|
| **F1-F3 cascade — все AND**, recall 18/18 | Эти 3 фильтра обязательны и сохраняют 100% recall |
| **С1-С7 — все OR (независимые)** | Каждое условие проверяется на полном baseline 1267, basket = union |
| **WR ≥ 70% желателен**, но не строгий | Принимаются condition <70% если уникально ловят missed imp |
| **Recall 18/18 — цель** | Идеальный basket поймает все 18 imp |

См. [[../README.md|smc-lib README]] + памяти `[[feedback-12h-fractal-baseline-f1f2f3]]`, `[[feedback-12h-fractal-or-basket-arch]]`.

## Этап 1: cascade F1-F3 (формирует baseline)

| # | Filter | Условие | Эффект |
|---|---|---|---|
| Pre-W | 3-bar local extreme | `pivot.high > i-1,i-2.high` (FH) / mirror FL | 2891 кандидатов из 4380 12h-баров |
| **F1** | left_ext_5 | `pivot.ext > все экстремумы 5 баров слева` | 1889 (recall 18/18) |
| **F2** | opp_colors ∨ three_same_color | `i.color != i-1.color (no doji)` ИЛИ `i==i-1==i-2 same color (no doji)` | 1408 (recall 18/18) |
| **F3** | body+wick form | `body/range ≤ 0.80 AND relevant_wick/range ≥ 0.03` | **1267 (baseline)** |

Полный canon: [[12h-fractal-filter-F1-F2]] (memory).

## Этап 2: OR-basket С1-С7 (parallel conditions)

Каждое условие direction-matched (FH ↔ short-direction zone/level; FL ↔ long-direction).

| # | Условие | Параметры | keep | conf | P(W) | Δ | imp |
|---|---|---|---:|---:|---:|---:|---:|
| **С1** | sweep maxV(i-1) | maxV = close 1m-свечи с max dirVolume внутри 12h(i-1) | 357 | 268 | **75.1%** | +26.2 | 5 |
| **С2** | union P11_count {8,12,16,24}×15m | доля dir-matched 15m свечей за окно ≥ {0.65, 0.75, 0.65, 0.65} | 193 | 141 | **73.1%** | +24.2 | 5 |
| **С3** | FIRST 50%-sweep ob_liq | FIRST = первая 12h-свеча с sweep после ready_ms; 50%-sweep = wick ≥ midpoint zone + close back outside; multi-TF {12h,D,2D,3D,W}, union liq_zone OR OB.zone | 115 | 80 | 69.6% | +20.7 | 2 |
| **С4** | FIRST 50%-sweep FVG | то же, multi-TF, любая FVG зона | 180 | 107 | 59.4% | +10.6 | 3 |
| **С5** | sweep HMA-78 (12h ∪ D) LIVE | HMA = ASVK Trend Line (Hull MA, length 78); LIVE = HMA value из закрытого предыдущего бара (как displayed); sweep = wick > level + close back; OR на 12h и D | 185 | 124 | 67.0% | +18.2 | 5 |
| **С6** | sweep HMA-200 D LIVE | то же, length 200, только D | 49 | 40 | **81.6%** | +32.8 | 1 |
| **С7** | FIRST 50%-sweep block_orders | (N₁, N₂) ≠ (1,1) HTF OB, multi-TF | 54 | 48 | **88.9%** | +40.0 | 1 |

### Семантические определения

#### 50%-sweep (для зон с интервалом)

```
SHORT zone [zone_lo, zone_hi]:
  high(t) ≥ (zone_lo + zone_hi)/2   ← wick пробил минимум до середины
  AND close(t) < zone_lo            ← close вернулся НИЖЕ зоны

LONG zone [zone_lo, zone_hi]:
  low(t) ≤ (zone_lo + zone_hi)/2
  AND close(t) > zone_hi
```

#### FIRST (для зон с first-touch mitigation)

Pivot — самый первый 12h-бар после `ready_ms` зоны, который выполнил sweep.

#### LIVE (для time-varying levels вроде HMA)

Значение индикатора на pivot bar i = значение, вычисленное при close предыдущего бара (i-1). Это значение, которое отображается на чарте во время формирования бара i, до его close — strict-causal.

#### Direction-matched

- FH pivot (top, ожидаем reversal вниз) ← sweep SHORT-direction зоны/уровня
- FL pivot (bot, ожидаем reversal вверх) ← sweep LONG-direction зоны/уровня

## Текущая корзина (состояние на 2026-05-27)

| | n | conf | not | P(W) | Δ | imp/18 |
|---|---:|---:|---:|---:|---:|---:|
| Baseline F1∩F2∩F3 | 1267 | 619 | 648 | 48.9% | — | 18 |
| **Basket = C1∪…∪C7** | **654** | 437 | 217 | **66.8%** | +17.9 | **15** |
| Остаток (в работе) | 613 | 182 | 431 | 29.7% | -19.2 | 3 |

### Прогресс recall (нарастающий)

| Шаг | imp в basket | missed |
|---|---:|---:|
| F1∩F2∩F3 baseline | 18 | 0 (без edge) |
| + С1 | 5 | 13 |
| + С2 | 8 | 10 |
| + С3 | 9 | 9 |
| + С4 | 11 | 7 |
| + С5 | 14 | 4 |
| + С6 | 15 | 3 |
| + С7 | 15 | 3 *(С7 polностью overlap с уже-в-basket)* |

### 3 непойманных missed

| # | MSK | dir |
|---|---|---|
| **#14** | 2026-03-04 15:00 | high |
| **#15** | 2026-03-08 15:00 | low |
| **#48** | 2026-05-06 03:00 | high |

Не реагируют ни на одну из протестированных зон/индикаторов с настройками по умолчанию.

## Открытые задачи

- **С8 для оставшихся 3** (#14, #15, #48) — кандидаты не найдены среди классических зон
- **OOS validation** — все condition только на BTC 6y in-sample. Нужно ETH/SOL, walk-forward
- **Entry / SL / TP** — пайплайн прогнозирования, не торговый сетап. Конкретные правила входа TBD
- **Live integration** — не реализовано

## Артефакты

### Скрипты

| Скрипт | Назначение |
|---|---|
| `scripts/pred12h_basket_c1c2c3.py` | Полный расчёт basket C1-C7, missed list |
| `scripts/pred12h_ob_liq_condition.py` | С3 standalone + sweep semantics test |
| `scripts/pred12h_fvg_50sweep_condition.py` | С4 standalone |
| `scripts/pred12h_trendline_test.py` | TrendLine sweep test (initial) |
| `scripts/pred12h_trendline_tune.py` | TrendLine parameter tuning |
| `scripts/pred12h_c6_mining.py` | Mining кандидатов С6, С7 |
| `scripts/pred12h_missed10_profile.py` | Профиль непойманных imp |
| `scripts/plot_trendline_l78_from_feb1.py` | TrendLine визуализация |

### Memories

- `[[12h-fractal-filter-F1-F2]]` — F1+F2+F3 канон
- `[[feedback-12h-fractal-baseline-f1f2f3]]` — baseline pinning
- `[[feedback-12h-fractal-or-basket-arch]]` — OR-basket архитектура
- `[[12h-fractal-orbasket-c1-c5]]` — C1-C5 состояние (нужно обновить до C7)
- `[[feedback-ob-liq-no-fractality]]` — ob_liq канон без Williams (используется в С3)

### Vault notes

- `[[2026-05-26-vc-3-variants-rules-md-fractal-or-basket]]` — VC канон + OR-basket arch
- `[[2026-05-27-12h-fractal-or-basket-c3-c4-c5-ob-liq-canon-update]]` — С3+С4+С5 + ob_liq canon

## История изменений

- **2026-05-21** — изначальная стратегия (sweep_FH ∪ OB_sweep) ∩ sweep_maxV[i] для HH/LL
- **2026-05-26** — baseline F1∩F2∩F3 утверждён, переход на OR-basket архитектуру
- **2026-05-26** — С1 (sweep maxV) принято
- **2026-05-26** — С2 (P11_count union) принято
- **2026-05-27** — С3 (FIRST 50%-sweep ob_liq), С4 (FIRST 50%-sweep FVG), С5 (HMA-78 LIVE) приняты
- **2026-05-27** — С6 (HMA-200 D LIVE), С7 (block_orders 50% FIRST) приняты

## Класс задачи

Strictly causal prediction → classification (probability of Williams confirmation) → entry trigger.

Не trading strategy в полном смысле (нет SL/TP/sizing). Это **predictive layer** на котором можно строить торговую стратегию.
