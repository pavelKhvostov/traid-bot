---
tags: [session, prediction-algo, bb-model, phase3, phase4, ob_vc, force-framework, lookahead]
date: 2026-05-31
status: completed
---

# Phase 3 results + Phase 4 «Force × Liquidity Framework»

Большая сессия 2026-05-30 → 2026-05-31. Phase 3 на PC1 показал что добавление 52 «count» фичей почти не сдвинуло AUC (0.537 → 0.540). Это привело к фундаментальной переориентации: не quantity, а **сила**. Пользователь провёл walk-through на 4 примерах ob_vc и сформулировал 5 принципов которые легли в основу Phase 4 спецификации (101 фича в 12 группах). Phase 4 архив упакован, готов к запуску на PC1.

## Phase 3 результаты (PC1, ночь 2026-05-30/31)

Runtime: 120 мин (как Phase 2). PC1 output получен через PC1_3 на рабочем столе.

| Metric | Phase 2 | Phase 3 | Δ |
|---|---|---|---|
| AUC mean | 0.537 | **0.540** | +0.003 (шум) |
| Brier mean | 0.330 | 0.334 | хуже |
| Folds AUC > 0.6 | 4/12 | 3/12 | хуже |
| Folds AUC < 0.5 | 4/12 | 4/12 | то же |
| Best WR (filter) | 41.1% | 41.5% | то же |
| Best R/tr | +0.379 | **+0.417** | малый плюс |
| Best total_R | +50.8 | +44.8 | хуже |
| **Target WR≥60% RR≥2.2** | ❌ | ❌ | NOT REACHED |

**Вывод**: trigger zone identification + 47 новых count-фичей (XII-XVIII) не дали значимого lift'а. Это валидация принципиальной перестройки подхода.

## Strict detection time bug — фундаментальная находка

В разговоре с пользователем разобрали что текущий backtest имеет lookahead 30мин-2ч на каждом ob_vc.

### Strict canon

```python
strict_detection = max(
    cur_HTF.close,                           # OB-pair полностью валидна
    c3.close,                                # LTF FVG валидна
    opposite_fractal_n2.close                # canon condition #9 — Williams n=2
)
```

Где `opposite_fractal_n2.close` может быть pre-existing (готов к c3.close) или post (forms 30-90 мин после c3).

### Пройденные примеры

| # | Signal MSK | HTF | cur HTF.close | c3.close | Fractal confirm | Strict | Lookahead |
|---|---|---|---|---|---|---|---|
| 1 | 29-05 21:15 | 2h | 23:00 | 21:45 | **pre-existing** ≤21:45 | **29-05 23:00** | 1ч 30мин |
| 2 | 30-05 00:15 | 1h | 01:00 | 00:45 | post: pivot 01:00 → confirm 01:45 | **30-05 01:45** | 1ч 15мин |
| 3 | 30-05 06:15 | 1h | 07:00 | 06:45 | post: pivot 07:30 → confirm 08:15 | **30-05 08:15** | 1ч 45мин |

Средний лукахед **~1.5 часа на трейд**. Phase 2/3 baseline (+157R/year) **переоценён** на этот зазор — реальный edge меньше.

Записано в memory: [[feedback-ob-vc-strict-detection-timing]].

## n_fvg_components pipeline bug

В Phase 2/3 dataset **ВСЕ 6683 events имеют n_fvg_components=1**. Причина: `scan_ob_vc_events` берёт только первый FVG по c2.open_time и отбрасывает остальные. Multi-FVG информация **полностью утеряна**.

Пример: на сигнале 29-05 21:15 (наш #1) реально **2 FVGs** (15m + 20m, второй вложен в первый = strong confluence). Будет пофикшено перед Phase 4 запуском.

## 5 фундаментальных принципов (от пользователя)

Сформулированы во время walk-through 4 примеров:

### Принцип #1: Zone STRENGTH ≠ Zone COUNT
> «зона как сила которая в ней кроется», не «количество зон разных ТФ»

Сила = TF_weight × age × class × что зона сделала (sweep history).

### Принцип #2: Multi-TF Force Aggregation
На рынке две противодействующие силы. Считать BUYER vs SELLER force на каждом ТФ (1h-3d) отдельно. Total net force со взвешиванием HTF.

Для #1 example, multi-TF расчёт показал:
- 3D: BUYER 1984 vs SELLER 0 → +1984 BUYER ⭐
- LTF (1h-4h): SELLER doминирует (мелкий шум)
- Total: +2087 BUYER (4.6× больше SELLER)

### Принцип #3: Liquidity = Fuel
> ob_vc заряжается ликвидностью, собранной свипами при формировании cur HTF candle

BUYER's ob_vc 17:00-19:00 (LONG): swept 8h SSL fractal + daily LL + 4h OB SHORT = **3+ HTF sweep**.
SELLER's ob_vc 21:00-23:00 (SHORT): swept **0 levels** → uncharged → холостой выстрел.

### Принцип #4: HTF Magnets above/below
> SHORT zones сверху НАД ценой — на самом деле **targets для BUYER**, не resistance

Re-interpretation: opposite HTF zones above/below pull price toward them (institutional liquidity grab targets), not block it.

### Принцип #5: 3D Dominance + LTF Noise Filter
Когда 3D net force ≫ 0 одной стороны — LTF противоположный сигнал = transient noise. На 6y данных это predictive heuristic.

## Historical Zone Memory (поздний инсайт)

Пользователь добавил **критический недостающий принцип**: зоны имеют **историческую память**.

Пример для #1: текущая «зона интереса» 72 500-74 500 — это price band тестированный multiple times за 2-3 месяца:
- **2026-03-05 03:00** — OB SHORT 1d, age 85d (зона resistance)
- **2026-04-11 15:00** — OB SHORT 1d, age 48d (зона support: bounce от 72 513)
- 2026-04-? — другие
- 2026-05-28 LL=72 582 → bounce
- 2026-05-29 LL=72 512 → MASSIVE bounce (BUYER's ob_vc fired here)

**4 теста band за 48 дней, все hold** → зона **очень сильная**. Phase 4 group I добавлен (9 фичей про historic memory).

## Multi-FVG context (4 примера, два с 2 FVGs)

Пример #1 SELLER: 2 FVG components (15m + 20m, вложен subset).
Пример BUYER's 17:00 (LONG, тот что massively swept): **4 FVG components** (2 на 15m + 2 на 20m) — extreme institutional confluence.

Это объясняет почему BUYER уверенно дальше двинул цену вверх а SELLER через 4 часа провалился.

## Phase 4 спецификация

Сохранена в `~/smc-lib/projects/PHASE4_SPEC.md`.

### Feature catalog (101 features, 12 групп)

| Группа | n | Фокус |
|---|---|---|
| A. Multi-TF Force | 15 | Per-TF buyer vs seller balance |
| B. Force Alignment | 8 | aligned_with_3D, dominance_ratio |
| C. Structural Anchor | 12 | Strongest backing HTF zone |
| D. Opposing Force | 8 | Сила противоположной стороны |
| E. Liquidity Charge | 12 | Sweep events = fuel |
| F. HTF Magnets | 5 | Opposing zones above/below |
| G. ob_vc Self | 10 | tf, dir, FVG count, position |
| H. Temporal | 4 | hour, day, session |
| I. Historical Zone Memory | 9 | Aged zones in band, durability |
| J. Volatility & Compression | 6 | ATR, BB squeeze, range contraction |
| K. Classical Divergence | 6 | RSI/MACD div (Wilder, не ASVK) |
| L. Volume (non-ASVK) | 6 | Volume z-score, OBV, climax |

### Архитектура

Smoke-test на Mac: 101 фича за ~15ms на event, все 12 групп работают, 0 ошибок.

Архив: `~/Desktop/compute-archives/compute-2026-05-31-bb-model-phase4.zip` (60 MB).

Прогноз runtime PC1: ~60-80 мин (меньше Phase 3 → меньше фичей + умнее compute).

### Targets

| Metric | Phase 3 | Phase 4 target |
|---|---|---|
| AUC mean | 0.540 | ≥ 0.65 |
| Folds AUC > 0.6 | 3/12 | ≥ 8/12 |
| Best WR | 41.5% | ≥ 60% |
| Best RR | 2.59 | ≥ 2.2 |

## Что ещё открыто

| # | TODO | Когда |
|---|---|---|
| 1 | Phase 4 PC1 запуск + analysis | сразу |
| 2 | ~~Strict lookahead fix в scan_ob_vc_events + simulate_floating~~ | **✅ done** |
| 3 | ~~Re-baseline backtest на strict (honest WR/RR)~~ | **в процессе (background)** |
| 4 | ~~Fix n_fvg_components save в scan_ob_vc_events~~ | **✅ done** |
| 5 | **Phase 5 prerequisite**: extend HTF_TO_LTF for macro ob_vc на 4h/12h/D с LTF=hour/half-hour | **Phase 5 ONLY** — Phase 4 не трогать |
| 6 | Phase 5 (если Phase 4 hit target — fine-tune; если miss — пересмотр label или DL) | по результату |

## Update 2026-05-31 ночь — Strict-fix completed + Phase 5 заметки

### Strict lookahead fix реализован

`~/smc-lib/projects/strategy_ob_vc_v1rules/backtest.py`:
- `scan_ob_vc_events` теперь вычисляет и записывает в event:
  - `ob_cur_close_ts` (cur HTF close)
  - `c3_close_ts` (LTF FVG close)
  - `fractal_confirm_ts` (Williams n=2 для opposite fractal)
  - `strict_detection_ts = max(...)` — самый ранний валидный момент детекции
  - **`n_fvg_components`** (bug fix — раньше всегда =1)
  - **`fvg_components_LTFs`** (list — какие LTF вообще валидируют VC)

`~/smc-lib/projects/strategy_1_1_1_floating.py`:
- `simulate_floating` использует `sig["strict_detection_ts"]` как `fill_start` (с fallback на старую формулу если не задан)

Smoke-test на example #1 (29-05 21:15 MSK):
- ob_cur_close_ts = 23:00 MSK
- c3_close_ts = 21:45 MSK
- fractal_confirm_ts = 22:30 MSK
- **STRICT detection_ts = 23:00 MSK** ✓ совпадает с manual calc пользователя
- n_fvg_components = 2 ✓
- fvg_components_LTFs = ['15m', '20m'] ✓

### Phase 4 архив re-packed

`~/Desktop/compute-archives/compute-2026-05-31-bb-model-phase4.zip` (60 MB):
- Содержит strict-fixed `backtest.py` + `strategy_1_1_1_floating.py`
- В `smc_context_v4.py` добавлен **G_fvg_multi_LTF_confluence** (binary) — теперь 102 features (а не 101)
- Phase 4 модель будет учиться на **honest** trade labels (без lookahead)

### Phase 5 prerequisite зафиксирован

Пользователь указал на критический архитектурный gap: ob_vc canon только на 1h+2h HTF, на 4h-3d ob_vc=0 в snapshot. **Strategy 1.1.1 V2** именно об этом — наш entry ob_vc(1h/2h) сидит внутри macro ob_vc(D/12h).

**В Phase 5** расширить `HTF_TO_LTF` в `~/smc-lib/elements/ob_vc/code.py`:
```python
HTF_TO_LTF = {
    "1h": ("15m", "20m"),     # текущее (entry)
    "2h": ("15m", "20m"),
    "4h": ("30m", "45m"),     # NEW: mid
    "6h": ("1h", "90m"),       # NEW
    "12h": ("2h", "3h"),       # NEW: macro
    "1d": ("4h", "6h"),        # NEW: super-macro
}
```

После этого:
- ob_vc будет appear в snapshot на ALL TFs (10 elements consistent)
- Phase 5 group_C structural anchor может быть macro ob_vc — куда более точная attribution
- Phase 5 group_A force aggregation учитывает ob_vc на каждом ТФ

**НЕ менять entry rules для Phase 4** — продолжаем торговать ob_vc(1h+2h). Это только snapshot context enhancement.

Требует **перепрогон btc_full.csv** с расширенным каноном перед Phase 5.

### Backtest на strict — результаты

| Метрика | Phase 2 lookahead | **Strict** | Δ |
|---|---|---|---|
| n_closed | 3 018 | 3 144 | +126 |
| WR | 37.1% | **30.0%** | **−7.1 п.п.** |
| total_R (6y) | **+1 076R** | **+301R** | **−72%** |
| R/tr mean | +0.36 | **+0.10** | **−72%** |

**Lookahead в Phase 2/3 систематически завышал результаты на ~72%.** Реальный edge baseline-стратегии ≈ **50R/год**, а не +157R как мы думали.

**Per-year strict:**
- 2020: +68.6R / 2021: +3.0R / 2022: +103.8R / 2023: +53.3R / 2024: +84.0R / **2025: −38.4R** / 2026 (5м): +27.0R

2025 — **первый убыточный год** (в lookahead-версии был +54R). Criterion #1 (zero bad years) **не проходит**.

Best subset strict: **LONG htf=2h** — n=752, WR=31.0%, R/tr=+0.14, +102.6R.

## Phase 4 PC1 РЕЗУЛЬТАТЫ (2026-05-31 04:02)

Runtime: 117.9 мин. Output в `~/Desktop/output PC1/`.

### Metrics (12-fold walk-forward на strict labels)

| Metric | Phase 2 | Phase 3 | **Phase 4** | Δ Phase 3→4 |
|---|---|---|---|---|
| AUC mean | 0.537 | 0.540 | **0.510** | **−0.030** ⚠️ |
| AUC median | 0.534 | 0.542 | **0.494** | −0.048 |
| Brier mean | 0.330 | 0.334 | 0.288 | better |
| **Folds AUC < 0.5** | 4/12 | 4/12 | **7/12** | **+3 хуже** |
| Folds AUC > 0.6 | 4/12 | 3/12 | 3/12 | same |
| Folds AUC > 0.65 | 1/12 | 1/12 | 2/12 | +1 |

**Phase 4 AUC=0.510 — практически random.** 7 из 12 фолдов **хуже монетки**.

### Strategy filter results

```
P_win_th  n_kept  WR   RR    R_per_tr  total_R
   0.00     531  27.3  2.61   -0.012   -6.6  ← baseline negative!
   0.40     150  31.3  2.42    0.065    9.8   ← best total_R
   0.45     143  31.5  2.34    0.047    6.7   ← best WR/RR
   0.90      43  30.2  2.90    0.158    6.8   ← best R/tr (top 8%)
```

**Target WR≥60% AND RR≥2.2 — НЕ достигнут.** Лучшее: WR=31.5% / RR=2.34.

### Анализ почему модель ухудшилась

1. **Strict honest labels** — гораздо сложнее, чем lookahead-tainted
2. **Test fold = 2025** = единственный убыточный год strict-baseline (−38R)
3. **Tabular bb-classifier потолок** возможно ~AUC 0.55 на этой задаче
4. **5 фичей placeholder values** (anchor_was_swept, opposing_obvc_n_fvg, hours_since_HTF_extremum, volume_at_anchor_birth, anchor_n_prior_touches)

### Структурный вывод

Phase 2/3 «успехи» были артефактом lookahead'а. Когда labels стали честными, разница между bb-models исчезла. Tabular ML на ob_vc(1h+2h) + etap108 не превзойдёт baseline существенно с текущими feature catalogs.

## PC2 MH parameter screening — РЕЗУЛЬТАТЫ (2026-05-31 04:12)

Runtime: ~3 часа (threading backend). 6912 configs, **0 ошибок**. Output `~/Desktop/output PC2/screening_results.csv`.

### dir_acc распределение

| | Value |
|---|---|
| Mean | 0.521 |
| Median | 0.521 |
| Std | **0.009** (очень узкая) |
| Min | 0.491 |
| Max | **0.553** |

**Дистрибуция узкая** — параметры MH влияют скромно, разница max-min = 6%.

### LazyBear canon — в нижних 19%

```
LazyBear (9,12,4,14,60,40,81): dir_acc = 0.5127
ранг = 5629/6912 (хуже 81% всех конфигов)
```

**LazyBear-канон оказался плохим выбором.** Лучшие конфиги дают +0.04 над ним.

### Top-2 winners

```
#1  (7, 14, 3, 22, 60, 50, 60)   dir_acc = 0.553
#2  (11, 10, 5, 14, 60, 50, 81)  dir_acc = 0.553
```

### Best params per axis (mean dir_acc)

| Param | LazyBear | Best | Лучший axis lift |
|---|---|---|---|
| bw2_ema1 | 9 | **11** | +0.001 |
| bw2_ema2 | 12 | **16** | +0.002 |
| bw2_sma_out | 4 | **5** | +0.002 |
| color_sma | 14 | **22** | +0.001 |
| mf_sma | 60 | **60** ✓ | — |
| **rsi_stoch** | 40 | **50** | **+0.007 ⭐** |
| stc_stoch | 81 | **60** | +0.002 |

**Главные выводы:**
- `mf_sma=60` — оптимально (canon угадал)
- `rsi_stoch=50` — оптимально (canon 40 — отличается)
- Все top-20 имеют эти 2 значения
- LazyBear-канон **не использовать** — Money Hands agent брать config `(7, 14, 3, 22, 60, 50, 60)`

## Сводная таблица «AUC/dir_acc по всем экспериментам»

| Эксперимент | Metric | Value | Note |
|---|---|---|---|
| Phase 2 bb-model | AUC mean | 0.537 | lookahead baseline |
| Phase 3 bb-model | AUC mean | 0.540 | trigger zone + 47 фичей |
| **Phase 4 bb-model** | **AUC mean** | **0.510** | **force/liquidity, honest labels** |
| MH screening max | dir_acc | 0.553 | 6912 configs, threading PC2 |
| MH LazyBear canon | dir_acc | 0.513 | в нижних 19% |
| MH screening mean | dir_acc | 0.521 | random + ~2% |
| Phase 4 baseline (no filter, test fold) | total_R | −6.6 | 2025 был bad year |
| Strict baseline 6y | total_R | +301R | vs +1076 lookahead |
| Strict baseline R/tr | — | +0.10 | vs +0.36 lookahead (overstate 3.6×) |

## Главные выводы

1. **Lookahead был 1.5h в среднем** — завышал результаты на ~72%
2. **Tabular bb-classifier не пробивает 0.55 AUC** на этой задаче (3 итерации, все близко)
3. **Phase 4 force framework + honest labels = 0.51 AUC** — модель ухудшилась когда стала «честнее»
4. **MoneyHands параметры дают скромный lift** — best 0.553 vs canon 0.513, +0.04
5. **rsi_stoch=50 главный axis** для MH-агента
6. **2025 = bad year** в strict — стратегия в текущей форме marginal

## Roadmap дальше — пересмотр

| # | Опция | Срок | Risk | Ожидание |
|---|---|---|---|---|
| 1 | Phase 5 macro ob_vc HTF (extend HTF_TO_LTF) + полные fixes placeholders | 1-2 дня + PC1 | low | maybe +0.03 AUC |
| 2 | Sequence DL модель (LSTM/Transformer на 15m bars) | 1 неделя + PC1 GPU | medium | possibly significant |
| 3 | Money Hands agent с best config (7,14,3,22,60,50,60) | сразу | low | working agent |
| 4 | Принять baseline +50R/год и перейти к rule-based + manual filter | 1 день | conservative | minimal viable |
| 5 | Re-design strategy framework (другой entry/SL/TP) | weeks | unbounded | unknown |

## Update 2026-05-31 день — 12h fractal анализ + force_opinion module

После анализа Phase 4 — фокус сместился на **rule-based usability of Phase 4 metrics** (поскольку ML на них не сработал).

### 12h fractal basket — углубление

Pred-12h basket C1-C7 conditions расшифрованы и зафиксированы (см. [[12h-fractal-orbasket-c1-c5]]):
- **C1** = sweep maxV(i-1) на 1m
- **C2** = sweep P11_count 15m fractal direction-matched
- **C3** = sweep ob_liq 50% FIRST
- **C4** = sweep FVG multi-TF 50% FIRST
- **C5** = sweep HMA-78 12h ∪ D LIVE
- **C6** = sweep HMA-200 D LIVE
- **C7** = sweep block_orders multi-TF 50% FIRST

Basket = C1∪…∪C7 = 654 pivots / WR 66.8% / 15 impulses на 6y BTC (+17.9pp над baseline).

### 4 missed fractals — типизация

User обнаружил 4 missed pivots: **06-05 03:00, 10-05 15:00, 13-05 15:00, 18-05 15:00**.

Анализ показал **2 архетипа** missed:

**Тип A: «Momentum break»** (3 из 4):
- 06-05 03:00 (FH 82 850): body 76% range, small upper wick (327)
- 10-05 15:00 (FH 82 479): body 63%, wick up 269
- 13-05 15:00 (FL 78 755): body 65%, wick dn 559

Свеча **пробивает уровень И закрывается ЗА ним** (не reclaim). C1-C7 формулируются как «sweep+reclaim», не ловят momentum break.

**Тип B: «Liquidity sweep in dominant-force zone»** (1 из 4):
- 18-05 15:00 (FL 76 051): body 16%, lower wick 951 — proper sweep shape
- Phase 4 force показал: BUYER force +1394 (massive BUYER zone)
- Cвип ниже стопов, потом reclaim — но НЕ свип отслеживаемого basket-уровня

Это даёт candidate **C8 condition**:
- C8a: body ≥ 60% + close past N-bar high/low + small breaking-side wick
- C8b: big wick contra-direction в HTF-dominated force zone

### Phase 4 force framework — практическая ценность

Несмотря на отрицательный ML результат, **Phase 4 force metrics остаются полезным аналитическим слоем**.

Сравнение 2 пар свечей по force:

**07-05 15:00 vs 08-05 03:00** (force FLIP):
- 07-05: NET = **−266 SELLER** (resistance ceiling 3D FVG SHORT 90d str=440)
- 08-05: NET = **+398 BUYER** (3D OB LONG активировалась +316)
- Δ = +664 за 12h = force REVERSAL = классический pivot point

**17-05 close (18-05 03:00 MSK) vs 18-05 close (19-05 03:00 MSK)** (без lookahead):
- 17-05 close: **9/9 TFs BUYER**, NET +1400, UNANIMOUS BULLISH
- 18-05 close: 7/9 TFs BUYER, 4h+12h flipped SELLER, NET +1274, **PIVOT signature** (HTF BUYER + LTF flip)
- 3D OB strength: 412 → **528** (+28%, цена приблизилась к границе)

PIVOT signature (HTF unified vs LTF flipped) — **новая интерпретируемая категория**.

### force_opinion.py создан

`~/smc-lib/prediction-algo/force_opinion.py` — **новый отдельный модуль**, не ломает `zones_opinion.py`.

Триггер: **«экспертное заключение по силе»**.

Output (стабильный 7-section format):
1. Header (price, MSK time)
2. Per-TF force table (9 ТФ × BUYER/SELLER/NET/Dominant)
3. Total summary + n_TFs BUYER wins + 3D dominance
4. **BIAS CLASSIFICATION** (5 категорий):
   - UNANIMOUS BULLISH/BEARISH
   - PIVOT signature (HTF + LTF flip)
   - BALANCED (weak bias)
   - HTF BULLISH/BEARISH bias
5. Top 5 LONG / Top 5 SHORT zones (with strengths)
6. Historical Zone Memory (aged 30d+/60d+/90d+ в band ±2%)
7. Verdict с reasoning

CLI:
```
python3 ~/smc-lib/prediction-algo/force_opinion.py [--cut-off "YYYY-MM-DD HH:MM"]
```

Память сохранена: [[feedback-expert-force-opinion-trigger]].

### 3 экспертных заключения теперь

| | force_opinion | zones_opinion | expert/opinion |
|---|---|---|---|
| Что | Multi-TF force balance + BIAS | P_hit_D кластеры | 11 индикаторов cascade |
| Trigger | «по силе» / «на чьей стороне сила» / «pivot signature» | «по зонам интереса» / «куда дойдёт» | «полный анализ» |
| Phase | 4 | v2 LookupModel | legacy |

## Связанные памяти

- [[feedback-ob-vc-strict-detection-timing]] — strict canon (создано вчера)
- [[prediction-algo-roadmap-5-questions]] — родительский roadmap (#3 + переосмысленный)
- [[zone-class-liquidity-inefficiency-block]] — class taxonomy
- [[feedback-untraded-area-is-magnet]] — fundamental SMC principle
- [[prediction-algo-final-results]] — Phase 2 v2 (87% top-5 hit_D baseline)

## Связи

- [[2026-05-30-prediction-algo-v2-bb-dataset-strategy-111-v2-floating-tp]] — предыдущая сессия
- `~/smc-lib/projects/PHASE4_SPEC.md` — Phase 4 спека
- `~/Desktop/PC1_3/` — Phase 3 raw outputs (bb_predictions, bb_metrics, parquet, logs)
- Phase 4 archive: `~/Desktop/compute-archives/compute-2026-05-31-bb-model-phase4.zip`
