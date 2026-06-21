# Прогнозирование фрактала 12h по трём свечам (Pred-12h)

## Цель

Предсказать вероятность формирования Williams-фрактала на 12h BTC по **строго causal** информации с трёх свечей (i-2, i-1, i) + дополнительным сигналам, доступным на момент close свечи i.

«Predicted» = свеча i пройдёт Williams-confirmation после i+1, i+2 → станет фактическим FH/FL фракталом.

## Ground truth

- **Данные**: BTC 1m из `~/traid-bot/data/BTCUSDT_1m_vic_vadim.csv`, агрегация до 12h.
- **In-sample окно**: 2020-01-01 → **текущий момент работы** (UTC). Канон per `[[feedback-pred12h-window-and-noimp]]` — перед расчётом дотягивать 1m.
- **Williams confirm**: для FH — pivot.high > обоих 2 справа; FL — pivot.low < обоих 2 справа.
- **imp pivots**: больше НЕ отслеживаем. Метрики только n / conf / WR / Δ.

## Methodology

Двухуровневая архитектура:

```
F1∩F2∩F3 (cascade)  →  baseline 1356 / 659 conf / P(W)=48.60%
        ↓
  + С1 ∪ С2 ∪ … ∪ С9 (OR-basket поверх baseline)
        ↓
  basket (TBD: пересчитать на новом окне)
```

### Архитектурные принципы

| Принцип | Описание |
|---|---|
| **F1-F3 cascade — все AND** | Эти 3 фильтра обязательны; задают популяцию для последующих условий |
| **С1-С9 — все OR (независимые)** | Каждое условие проверяется на полном baseline, basket = union |
| **WR ≥ 70% желателен** | Условия с P(W) < 70% принимаются только если дают значимый Δ vs baseline |

См. `[[feedback-pred12h-window-and-noimp]]`, `[[feedback-12h-fractal-or-basket-arch]]`.

## Этап 1: cascade F1-F3 (формирует baseline)

Snapshot 2026-06-06 (window: 2020-01-01 → текущий момент, 4 698 12h-баров):

| # | Filter | Условие | n (после стадии) |
|---|---|---|---:|
| Pre-W | 3-bar local extreme | `pivot.high > i-1,i-2.high` (FH) / mirror FL | 3 099 |
| **F1** | left_ext_5 | `pivot.ext > все экстремумы 5 баров слева` | 2 031 |
| **F2** | opp_colors ∨ three_same_color | `i.color ≠ i-1.color (no doji)` ИЛИ `i = i-1 = i-2 same color (no doji)` | 1 507 |
| **F3** | body+wick form | `body/range ≤ 0.80 AND relevant_wick/range ≥ 0.03` | **1 356 (baseline)** |

**BASELINE**: n=1 356 / conf=659 / **WR=48.60%**

Полный canon: `[[12h-fractal-filter-F1-F2]]` (memory). Скрипт: `~/smc-lib/scripts/pred12h_baseline_v2.py`.

Полный canon: [[12h-fractal-filter-F1-F2]] (memory).

## Этап 2: OR-basket С1-С7 (parallel conditions)

Каждое условие direction-matched (FH ↔ short-direction zone/level; FL ↔ long-direction).

| # | Условие | Параметры | keep | conf | P(W) | Δ | imp |
|---|---|---|---:|---:|---:|---:|---:|
| **С1** | sweep maxV(i-1) | maxV = close 1m-свечи с max dirVolume внутри 12h(i-1) | 357 | 268 | **75.1%** | +26.2 | 5 |
| **С2** | union P11_count {8,12,16,24}×15m | доля dir-matched 15m свечей за окно ≥ {0.65, 0.75, 0.65, 0.65} | 193 | 141 | **73.1%** | +24.2 | 5 |
| **С3** | FIRST 50%-sweep ob_liq | FIRST = первая 12h-свеча с sweep после ready_ms; 50%-sweep = wick ≥ midpoint zone + close back outside; multi-TF {12h,D,2D,3D,W}, union liq_zone OR OB.zone | 115 | 80 | 69.6% | +20.7 | 2 |
| **С4** | OR-sub-basket FVG (D1..D6) | sub-architecture: 6 параллельных Dx по 3 осям (lifecycle × sweep × filter), см. ниже | 251 | 162 | **64.5%** | +15.6 | **6** |
| **С5** | sweep HMA-78 (12h ∪ D) LIVE | HMA = ASVK Trend Line (Hull MA, length 78); LIVE = HMA value из закрытого предыдущего бара (как displayed); sweep = wick > level + close back; OR на 12h и D | 185 | 124 | 67.0% | +18.2 | 5 |
| **С6** | sweep HMA-200 D LIVE | то же, length 200, только D | 49 | 40 | **81.6%** | +32.8 | 1 |
| **С7** | FIRST 50%-sweep block_orders | (N₁, N₂) ≠ (1,1) HTF OB, multi-TF | 54 | 48 | **88.9%** | +40.0 | 1 |
| **С8** | ≥2 W-aligned swept VWAPs | D-fractal anchored VWAPs where anchor coincides with W Williams N=2 pivot (W-anchor=Mon); sweep = high>VWAP & close<VWAP (FH), mirror FL | 65 | 52 | **80.0%** | +31.1 | 1 |
| **С9** | reverse force divergence (∪3) | C9a: FL net≤-1000 (1 bar, 100% WR n=12) ∪ C9b: FH net≥+500 (1 bar, 82% WR n=39) ∪ C9c: FL net_w2≤-2000 (2 bars, 86% WR n=14). net = Σ(buyer-seller) across {1h,2h,4h,6h,8h,12h,1d,2d,3d} from force_opinion Phase 4. Семантика: exhaustion divergence — sellers at bottom = capitulation, buyers at top = distribution | 57 | 48 | **84.2%** | +35.3 | 0 |

## C4 sub-basket: D1..D6 (FVG OR-sub-basket)

### Архитектура

```
C4 = D1 ∪ D2 ∪ D3 ∪ D4 ∪ D5 ∪ D6
```

Каждое Dx — независимая комбинация по 3 осям:

| Ось | Варианты | Что задаёт |
|---|---|---|
| **Lifecycle** | L0 / L1 / L2 / L3 / L4 | Когда FVG перестаёт быть «active» |
| **Sweep formula** | S50 / S70 / S100 / W50 / W100 / CINS | Что засчитывается как валидный sweep |
| **Filter** | ANY / HTF / 12h / AGE50 / WIDE / комбинации | Какие FVG проходят (TF, возраст, ширина) |

### Lifecycle gates (когда FVG исключается из active list)

| Lc | Условие abandon | Семантика |
|---|---|---|
| **L0** | никогда | вечный poll (старый default) |
| **L1** | при первом wick ≥ 50% | сразу после midpoint touch |
| **L2** | при первом wick ≥ 100% | full fill = mitigated (smc-lib canon) |
| **L3** | при первом close внутри зоны | gap consumed |
| **L4** | через 120 баров (60d) без действия | timeout |

### Sweep formulas

| Sw | Условие SHORT FVG [zlo, zhi] | Семантика |
|---|---|---|
| **S50** | high ≥ mid ∧ close < zlo | strict 50%-sweep + rejection (old default) |
| **S70** | high ≥ zlo+0.7·w ∧ close < zlo | deeper sweep |
| **S100** | high ≥ zhi ∧ close < zlo | full sweep + rejection ⭐ |
| **W50** | high ≥ mid | wick-fill 50% (close anywhere) |
| **W100** | high ≥ zhi | full wick-fill (smc-lib mitigation canon) |
| **CINS** | high ≥ mid ∧ close внутри | consumption rejection |

LONG FVG — зеркально.

### Filters (на FVG metadata)

| Filter | Условие |
|---|---|
| ANY | все FVG |
| HTF | TF ∈ {D, 2D, 3D, W} |
| 12h | TF = 12h |
| AGE50 | age ≥ 50 баров 12h |
| WIDE | (zhi-zlo) / ATR(14)\_12h ≥ 0.7 |
| HTF_AGE50 | HTF ∧ AGE50 |
| HTF_WIDE | HTF ∧ WIDE |
| AGE50_WIDE | AGE50 ∧ WIDE |

### Canonical D1..D6

| Dx | Lc | Sw | Filter | n | conf | P(W) | imp | роль |
|---|---|---|---|---:|---:|---:|---:|---|
| **D1** | L0 | S100 | WIDE | 33 | 31 | **93.9%** | 0 | precision anchor (full-sweep wide) |
| **D2** | L0 | S50 | AGE50_WIDE | 64 | 57 | **89.1%** | 0 | aged-wide classic 50% |
| **D3** | L0 | S70 | AGE50 | 126 | 96 | 76.2% | 2 | aged + deeper sweep |
| **D4** | L0 | S50 | HTF_WIDE | 53 | 42 | 79.2% | 0 | HTF wide precision |
| **D5** | L1 | W50 | AGE50 | 94 | 52 | 55.3% | **4** | wick-fill rebalance (catches missed #14, #48) ⭐ |
| **D6** | L2 | W100 | AGE50 | 96 | 50 | 52.1% | **5** | full-fill rebalance (recall driver) ⭐ |

### Incremental basket (greedy build)

| Шаг | + Dx | + pivs | + imp | basket_n | basket_WR | basket_imp |
|---|---|---:|---:|---:|---:|---:|
| 1 | D1 | 33 | 0 | 33 | 93.9% | 0 |
| 2 | D2 | 39 | 0 | 72 | 90.3% | 0 |
| 3 | D3 | 88 | 2 | 160 | 78.8% | 2 |
| 4 | D4 | 13 | 0 | 173 | 76.9% | 2 |
| 5 | **D5** | 49 | **3** | 222 | 68.5% | 5 |
| 6 | **D6** | 29 | 1 | **251** | **64.5%** | **6** |

### C4_v2 vs C4 default

| | n | conf | P(W) | imp |
|---|---:|---:|---:|---:|
| C4 default (L0/S50/ANY) | 182 | 109 | 59.9% | 3 |
| **C4_v2 = D1∪…∪D6** | **251** | 162 | **64.5%** | **6** |
| Δ | +69 | +53 | **+4.7pp** | **+3 (×2)** |

### Imp coverage (9 уникальных дат из 18)

```
✓ 02-06 03:00 LOW   D3,D5,D6     ← было в default
✓ 02-08 15:00 HIGH  D7 only      ← было в default
✓ 02-25 15:00 HIGH  D6           ← НОВЫЙ
✓ 02-28 03:00 LOW   D6           ← НОВЫЙ
✓ 03-04 15:00 HIGH  D5,D6        ← missed #14 пойман ⭐
✓ 03-17 03:00 HIGH  D6           ← НОВЫЙ
✓ 03-22 15:00 LOW   D3           ← было в default
✓ 04-17 15:00 HIGH  D5,D6        ← НОВЫЙ
✓ 05-06 03:00 HIGH  D5,D6        ← missed #48 пойман ⭐⭐
```

#15 (2026-03-08 LOW) всё ещё не пойман.

### Архитектурные принципы C4 sub-basket

| Принцип | Объяснение |
|---|---|
| **Mirroring C-basket** | Та же OR-логика, но один уровень глубже — для FVG-conditions |
| **Precision Dx vs Recall Dx** | Strict close-outside дают WR (D1-D4), wick-fill дают imp (D5-D6) |
| **Lifecycle gate** | Решает проблему дефолта что FVG никогда не abandoned |
| **AGE50 везде в D3-D6** | aged-untouched-magnet принцип — основной structural edge |

### Скрипты

- `~/smc-lib/scripts/pred12h_c4_subbasket.py` — full grid 225 variants (5 Lc × 6 Sw × 8 Filter)
- `~/smc-lib/scripts/pred12h_c4_basket_build.py` — greedy basket build из 10 кандидатов
- Output CSV: `~/Desktop/c4_subbasket_grid.csv`

## Canonical Chart Output

Эталон-скрипт: `~/smc-lib/scripts/plot_basket_ml_intersection_2026_expert.py`
Output: `~/Desktop/i-rdrb-charts/btc_12h_basket_ml_intersection_6mo.png`

Spec: см. memory `[[feedback-pred12h-canonical-chart]]` и session `[[2026-06-05-pred12h-extended-ml-and-expert-chart]]`.

Параметры:
- 12h TF, rolling 180d window, Y 50k-100k, 24-bar right buffer
- Markers ▼ FH red / ▲ FL green, filled=confirmed, hollow=not
- `★` × n_C confluence stars над/под маркером
- HMA-78/200 на 12h+D LIVE (Правило 7)
- 6 VWAPs (2 eff + 1 worked под и над ценой), anchors с 2018-01-01 (Правило 6)
- Filter: basket ∩ Andrey ML p_main ≥ 0.3 (hybrid signals: original ≤21-05 + synthetic 22-05+)

## ML Integration (Andrey etap_173)

Источник: `~/Desktop/etap_173_full_pred_*.csv` × 6 targets, merged train (inverted-split) + OOS

Coverage:
- 676 basket events × ML predictions (672/676 with ML)
- E_pct = 3·p_3 + p_4 + p_5 (interpolated expected magnitude)
- Calibration monotonic: E_pct ↔ WR (0% → 27%, 5% → 82%)

Скрипты:
- `~/traid-bot-andrey/research/elements_study/etap_173_inverted.py` — inverted split
- `~/traid-bot-andrey/research/elements_study/etap_171_extended.py` — патч без skip последних 14 баров

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
- **2026-06-06** — **C4 переработан в OR-sub-basket D1..D6**. Найдена структурная проблема дефолта (нет lifecycle gate → FVG никогда не abandoned). Введены 3 оси: lifecycle (L0-L4) × sweep (S50/70/100/W50/W100/CINS) × filter (TF/age/width комбинации). C4_v2 = 251 fires / WR 64.5% (vs default 182/59.9%). Architecture: precision Dx (D1-D4) + recall Dx (D5-D6)
- **2026-06-06** — **окно расширено до 2020-01-01 → текущий момент**; **прекращено отслеживание imp** (per `[[feedback-pred12h-window-and-noimp]]`). Baseline пересчитан: n=1356 / conf=659 / WR=48.60% (старое 2020-05-27→2026-05-26 окно давало n=1267 / WR=48.9%). Новый clean скрипт: `pred12h_baseline_v2.py`. Числа C1-C9 и C4 sub-basket подлежат пересчёту на новом окне

## Класс задачи

Strictly causal prediction → classification (probability of Williams confirmation) → entry trigger.

Не trading strategy в полном смысле (нет SL/TP/sizing). Это **predictive layer** на котором можно строить торговую стратегию.
