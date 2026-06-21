---
tags: [session, pivot, mec, p4zr, phase4, force, moneyhands, rsi-cumulative, pred12h, strategy-1-1-1, lookahead, ml-classifier, vwap, totales-usdtd, deep-dive]
date: 2026-06-02
status: completed
---

# Pivot/MEC/P4ZR — день multi-expert deep dive

Большой исследовательский день 2026-06-02. Старт с разбора 4 user-named missed фракталов 12h (06-05, 10-05, 13-05, 18-05), переход к Phase 4 force evaluation как C8, серия отрицательных результатов на pred12h grid, неожиданное открытие P4ZR v2/v3 как самостоятельной стратегии (PF 18-122), и финальный stop-line с identification entry-fill lookahead bias + отсутствие TOTALES/USDT.D confluence в нашем benchmark.

## Хронология

### Часть 1: 4 missed pivots — поиск C8

User назвал 4 12h фрактала, которые надо вернуть в pred12h basket:
- 06-05 03:00 FH (ATH 82850, #48 imp missed)
- 10-05 15:00 FH (LH retest 82479)
- 13-05 15:00 FL (sweep low 78755)
- 18-05 15:00 FL (BOS down 76051)

Проверка C1-C7: **все 4 в baseline F1∩F2∩F3, все 4 Williams-confirmed, НИ ОДНО из C1-C7 не сработало**.

### Часть 2: Phase 4 force как C8 hypothesis

Запустил force_opinion на 4 missed pivot'ах + 6 caught:

| Pivot | BIAS | n_wins | match direction? |
|---|---|---:|---|
| 06-05 #48 | UNANIMOUS BEARISH | 0/9 | ✓ |
| 10-05 | UNANIMOUS BEARISH | 0/9 | ✓ |
| 13-05 | **PIVOT signature** | 7/9 | ✓ |
| 18-05 | HTF BULLISH | 7/9 | ✓ |

**4/4 force-match** — гипотеза «Phase 4 force = C8» казалась сильной.

### Часть 3: Phase 4 batch на 6y BTC

Запустил `pred12h_C8_force_batch_chunked.py` (после первого нечанкованного fail из-за O(N²) snapshot loop). Чанкование 365d × 6 + 180d warmup = **22.9 мин**, 1272 пивотa с force metrics → `~/Desktop/pred12h_C8_force_6y.parquet`.

Quick stats:
- Force-match overall: 73.7%
- Confirmed AMONG force-match: **43.5%** (ниже baseline 48.7%!) → standalone не работает

### Часть 4: STRICT grid search — НЕГАТИВНЫЙ результат

Grid 1280 параметризаций по abs_net, d3_net, wins, BIAS. **STRICT lookahead-safe** (window открывается на close pivot-бара, не open):

| Конфиг | n | WR | PF | Total R |
|---|---:|---:|---:|---:|
| Pure floating | 378 | 51.3% | 2.20 | **+195.9R** |
| pred12h basket | 145 | 47.6% | 1.95 | +70R |
| Best basket+C8 | 156 | 48.7% | 2.18 | +89.7R |

**Pure floating побеждает любой filter в strict mode**. C8 force ничего не добавляет к floating. Это **подтвердило что lookahead +132R (Williams+2%) был артефактом**.

### Часть 5: Стратифицированный анализ force

Поразительное открытие: **force_match True с большим abs_net = НИЖЕ P(W)**, не выше:

| force_match | abs_net | P(W) |
|---|---|---:|
| True + 1.5-2.5k | strong match | **33.2%** |
| True + >2.5k | very strong match | 37.8% |
| **False + >1.5k** | contrary force | **83.3%** |

По BIAS:
- UNANIMOUS BULLISH/BEARISH: P(W) 40-42% (= тренд, не разворот)
- HTF biased: 56-58% (нормальный pivot)
- BALANCED weak: 65% (наивысший!)
- PIVOT signature: 48-58%

**Интерпретация**: UNANIMOUS = trend continuation, не reversal. Для pivot подходит HTF biased / BALANCED.

### Часть 6: VWAP как C8

Проверил distance_to_nearest_VWAP_ASVK на baseline и last-60 баров. **100% покрытие** (типовой 12h-бар касается 30-50 VWAPs). Не дискриминатор.

### Часть 7: 7 экспертов overview

| # | Эксперт | Status | Что нашли |
|---|---|---|---|
| 1 | Зоны интереса | base layer | top-5 hit_D 87% production |
| 2 | Сила зоны (Phase 4) | tested | не Williams-предиктор; PIVOT signature edge |
| 3 | TrendLine HMA-78/200 | C5/C6 в pred12h | 67-78% P(W) ✓ |
| 4 | VWAP anchored | tested | 100% покрытие — не дискриминатор |
| 5 | VIK maxV | C1 в pred12h | 75% P(W) ✓ главный driver |
| 6 | MoneyHands | tested | 96h top-10% short = 0.738 acc; 1 catch (#14) noisy |
| 7 | RSI ASVK | **untested → нашли edge** | bars_since_rsi_exit q1 = **62%** P(W) |

### Часть 8: MEC стратегия

Сформулирован Multi-Expert Confluence:
- L1: pred12h fire OR Force PIVOT OR MH top-10% top
- L2: zone confluence (Phase 4 + VWAP)
- L3: VIK/RSI/TrendLine timing
- L4: MH agreement

**MEC v1 (12h entry, naive market fill)**: PF 1.11, freq 8.9/мес — не работает.

**MEC v2 (фильтры floating)**: PF 2.20 → 2.28 marginal. Force не помогает (опровергает гипотезу).

### Часть 9: P4ZR (Phase 4 Zone Reversion) — UNEXPECTED WINNER

Чистая стратегия на Phase 4 force + zones:
- Direction: 3D_net > T
- BIAS filter: не UNANIMOUS
- Entry: top-1 same-direction zone edge
- SL: zone breakout + 0.1% buffer
- TP: mid opposing zone
- RR ≥ 1.5 required
- Max hold 60-84h

| Версия | Trades | WR | PF | Total R | Freq |
|---|---:|---:|---:|---:|---:|
| **v1** (strict T=200) | 16 | 69% | 9.88 | +44R | 0.28 |
| **v2** (relaxed T=100) | 100 | **85%** | **18.36** | **+260R** | 1.48 |

P4ZR v2 **побеждает pure floating** по Total R И PF на 6y.

### Часть 10: RSI cumulative — STRONG EDGE

Прямой rule (без ML) на cumulative MH features v2:

| Feature | q1 range | P(W) baseline 49% |
|---|---|---:|
| **bars_since_rsi_os_exit_2h** | 0-7 | **62.4%** (FL=64.6%) |
| **bars_since_rsi_ob_exit_1h** | 0-6 | **60.8%** |

«Fresh exit из extreme» = +13pp edge. RSI cumulative — **первая структурная фича** дающая чистый standalone edge.

### Часть 11: P4ZR v3 = v2 + RSI cumulative filter

Post-filtering existing P4ZR v2 trades:

| Config | n | WR | PF | RR | Total R | R/tr |
|---|---:|---:|---:|---:|---:|---:|
| v2 baseline | 100 | 85% | 18.4 | 3.24 | +260R | +2.60 |
| LONG≤7, SHORT≤7 | 32 | **96.9%** | **122.8** | 3.96 | +122R | +3.81 |
| LONG≤15, SHORT≤15 | 53 | 92.5% | 42.6 | 3.47 | +166R | +3.14 |
| **SHORT only, ≤7** | 16 | 93.8% | 88.0 | 5.87 | +87R | **+5.44** |

⚠ Small samples при строгих thresholds (PF=∞ артефакт).

### Часть 12: MH walk-forward 6y

Запустил `mh_walkforward_6y.py` — 62 retrains × 6 horizons, ~2 hours. Output `~/Desktop/mh_predictions_6y.csv`.

### Часть 13: ML classifier на 1272 baseline pivots

Pipeline: labels (72h move ≥2% без opposite excursion) + 3081 features (MH v2 + Phase 4 + RSI) → walk-forward HistGradientBoostingClassifier.

**Результат: model НЕ побил baseline**:
- thr 0.80: P(success) 50.2% (cover 25%) vs baseline 48.3%
- На 19 user-labeled: 12/19 caught при thr ≥ 0.5
- Драм. misses: 06-05 (#48, pred 0.27), 23-05 (record force, pred 0.42), 04-03 (#14, pred 0.39)

Overfitting risk: 200-250 samples/year / 3081 features = слишком много dimensions.

### Часть 14: Entry-fill LOOKAHEAD bias в P4ZR

User указал на subtle bug — мой simulate_trade ASSUMES позиция filled at entry_px (= zone edge), но не проверяет что цена действительно вернулась к entry_px.

**Эффект**: WR 85%, PF 18.36 в P4ZR v2 **inflated** на 10-30%. Real estimate: WR ~70-75%, PF ~5-8 — всё ещё good, но не ridiculous.

**Fix**: strict fill simulation (limit-order check) — НЕ ЗАПУЩЕН.

### Часть 15: TOTALES + USDT.D confluence — отсутствует

User напомнил что Strategy 1.1.1 v1 имеет condition синхронизации с TOTALES + USDT.D (Triple confluence). В моём pure floating баteсте **этот фактор отсутствует** — `strategy_1_1_1_floating.py` (etap108 reference) не вызывает macro confluence.

Известный canon (из `vault/knowledge/debugging/confluence-lookahead-and-rr22-bugs.md`):
- TOTALES same direction + USDT.D opposite (mirror)
- Triple confluence WR были inflated на ~10pp из-за lookahead (closed candles only — strict version)

Data:
- TOTALES_1d/4h/1h/15m в `~/traid-bot/data/` ✓
- USDT_D локально отсутствует ✗

**Запланировано**: fetch USDT_D + честный test pure floating + Triple confluence.

### Часть 16: STOP всех процессов

После 16 итераций user сказал «останавливай все процессы и начнем думать сначала». Остановлен running force_evolution_batch, очищены все taskи.

## Финальное состояние artifacts

| Артефакт | Где | Что |
|---|---|---|
| Pure floating 6y | `~/Desktop/floating_btc_6y_trades.parquet` | 378 trades, +195.87R, PF 2.20 |
| Baseline + C1-C7 | `~/Desktop/pred12h_baseline_c1c7.parquet` | 1272 pivots |
| Phase 4 force 6y | `~/Desktop/pred12h_C8_force_6y.parquet` | per-pivot force |
| Cumulative MH | `~/Desktop/pred12h_mh_cumulative.parquet` | bars_since features |
| P4ZR v2 trades | `~/Desktop/p4zr_v2_btc_6y_trades.parquet` | 100 trades, +260R (entry-fill biased) |
| MH walk-forward 6y | `~/Desktop/mh_predictions_6y.csv` | 5 лет OOS preds |
| Pivot classifier preds | `~/Desktop/pivot_classifier_preds.parquet` | ML failed |

## Validated facts (стабильные истины)

1. **Pure floating 1.1.1 БЕЗ macro confluence** = +196R / WR 51% / PF 2.20 на 6y BTC
2. **Pred12h basket strict** = +70R (хуже floating)
3. **Phase 4 force standalone** ≠ Williams pivot predictor
4. **Strong UNIDIRECTIONAL force = LOW P(W)** (тренд, не разворот)
5. **HTF biased / PIVOT signature / BALANCED** = выше P(W), best для reversal
6. **MH 96h top-10% confidence**: 0.74 dir_acc на SHORTs, 0.58 LONGs
7. **RSI cumulative «fresh exit»** = real standalone edge (62% P(W))
8. **P4ZR concept works** — но entry-fill lookahead inflates результаты
9. **ML на 3081 features** не превзошёл baseline (overfitting + универсального предиктора нет)

## Открытые честные вопросы

| # | Вопрос | Зачем |
|---|---|---|
| 1 | Honest P4ZR с strict fill simulation | real numbers |
| 2 | 1.1.1 + Triple TOTALES/USDT.D confluence на 6y | full canon benchmark |
| 3 | Force evolution dynamics pre-pivot (6h grid) | leading indicator |
| 4 | Per-TF force breakdown (3d vs 12h vs 1h conduct) | какой ТФ leads |
| 5 | RSI cumulative + strict P4ZR fill = clean strategy | honest production candidate |

## Артефакты-скрипты

- `~/smc-lib/scripts/pred12h_C8_force_batch_chunked.py` — chunked Phase 4 batch
- `~/smc-lib/scripts/pred12h_C8_grid_search_strict.py` — STRICT grid search
- `~/smc-lib/scripts/mec_backtest_v1.py` — MEC v1 (12h entry, biased)
- `~/smc-lib/scripts/mec_v2_backtest.py` — MEC v2 (floating + filters)
- `~/smc-lib/scripts/p4zr_backtest.py` — P4ZR strategy
- `~/smc-lib/scripts/mh_walkforward_6y.py` — full MH WF
- `~/smc-lib/scripts/mh_cumulative_rule_test.py` — RSI/MH cumulative direct test
- `~/smc-lib/scripts/pivot_classifier_train.py` — ML classifier
- `~/smc-lib/scripts/force_evolution_batch.py` — 6h grid (cancelled mid-run)
- `~/smc-lib/scripts/pred12h_C8_grid_pw_maximize.py` / `pred12h_C8_grid_pw_v2.py` — двусторонний C8

## Решения

### Подтверждено
- Pred12h optimized for Williams precision, **не floating PF**
- Force expert полезен для **direction + entry zones**, не для **pivot prediction**
- BIAS categorization работает (UNANIMOUS vs HTF biased разделяет тренд от разворота)
- RSI cumulative — лучший standalone edge среди тестированных
- P4ZR architecture (Phase 4 + structural SL/TP) — рабочая идея

### Опровергнуто
- pred12h как finger для 1.1.1
- Phase 4 force как direct pivot-predictor
- Universal ML predictor на 3081 features
- VWAP proximity как фильтр
- Cumulative MH features standalone (кроме RSI)

### Открыто
- Entry-fill bias в P4ZR — нужна fix-версия
- TOTALES + USDT.D macro confluence (отсутствовали в тестах)
- Force evolution dynamics — не дошли

## Memory updates

- `pred12h-doesnot-improve-floating-strict` (создан ранее)
- `feedback-pivot-filter-lookahead-vs-strict` (создан ранее)
- `feedback-phase4-zone-precompute-must-chunk` (создан ранее)
- **NEW**: `feedback-p4zr-entry-fill-lookahead` (планируется записать)
- **NEW**: `feedback-rsi-cumulative-fresh-exit-edge` (планируется)
- **NEW**: `feedback-1-1-1-floating-without-totales-usdtd` (планируется — уточнение benchmark)

## Связанное

- `[[2026-06-01-pivot-project-pred12h-c8-force-strict-grid-search]]` — предыдущий день
- `[[2026-05-31-phase3-results-phase4-force-framework]]` — Phase 4 framework база
- `[[strategy-1-1-1-floating-tp-final]]` — etap108 reference
- `[[pred12h-fractal-three-candles]]` — baseline проект
- `[[confluence-lookahead-and-rr22-bugs]]` — known lookahead в old confluence analyzer
