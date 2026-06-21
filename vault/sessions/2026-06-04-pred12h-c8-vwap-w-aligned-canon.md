---
tags: [session, pred12h, c8, vwap, basket]
date: 2026-06-04
strategy: pred12h-fractal-prediction
status: c8-approved
---

# C8 утверждено: ≥2 W-aligned swept VWAPs (WR 80%)

Продолжение работы над OR-basket в pred12h-fractal проекте. После цепочки исследований VWAP-based фильтров — **зафиксировано C8 = ≥2 W-aligned swept VWAPs со standalone WR 80%**.

## Что сделано

### 1. Downloaded Andrey branch + vault (150 файлов)

Изучили `origin/andrey` ветку коллаборатора:
- Pure ML pipeline для HH/LL фракталов BTC 12h
- AUC 0.91-0.94 honest CV (etap_170 Lopez de Prado canon)
- 308 features (Vadim+Bulkowski интеграция в etap_173)
- Sniper composite 93% precision rule-based

**Главное:** Andrey НЕ заявляет trading edge. Цель — «искать точки разворота на ранних стадиях, НЕ trade execution с RR». ML detector, не стратегия.

Полный артефакт: `~/smc-lib/projects/andrey-12h.md`.

### 2. TBM-аудит ML signals (TP=3%/SL=1.5%)

305 OOS signals из `etap_173_signals_caught.csv` за 1.37 года:
- Path-free `hit_3` WR на A+B+C tier = 67%
- **Path-dependent TBM realized WR = 25-39%**
- A_sniper: 65.8% → 21.1% (path drop)
- Все tiers суммарно: **−99R / Sharpe −3.76**

Honest realized WR в 2× ниже path-free reported. AUC 0.94 ≠ trading edge.

### 3. C8-C18 кандидаты из Andrey features

#### Bulkowski (11 reversal-паттернов)

Прогнали raw `etap_172_signals.csv` (520 fires за 6.3 года) против baseline 1275.
**Результат: 28-56% WR** — равно baseline. Retrospective timing — паттерны fires на breakout-баре после pivot.

Не подходят для OR-basket архитектуры.

#### VSA / Nison / Sweep (Andrey top features)

Нашли 6 strict-causal кандидатов c WR ≥ 65% standalone:
- **C8 candidate:** climax_bear ≥ 2 → 81.6% short
- **C9 candidate:** cdl_hammer → 76.7% long
- **C10:** climax_bull ≥ 2 → 71.4% long
- **C11:** cdl_shooting_star → 67.7% short
- **C12-C13:** ssl/bsl_failed_24 → 62-65%

**НЕ выбрали:** не ловят missed (#14/#15/#48/NEW). Marginal contribution мала.

### 4. VWAP-based C8 исследование (главное)

#### Базовая логика

- 645 D-fractal anchored VWAPs за 6.4 года
- Sweep semantics (per `[[Правило 6]]`): high > VWAP AND close < VWAP (FH); mirror FL
- Strict-causal: VWAP value на момент close 12h-свечи

#### Перебор фильтров

| Filter | WR | catches |
|--------|---:|---------|
| Naive sweep ≥1 | 48% | ≈baseline |
| Hybrid (cluster K ∪ macro single ≥730d) | 59% | catches 3/3 (старое counting) |
| Multi-TF alignment (≥2 W-aligned) | **80%** ★ | 0 missed |
| Multi-TF (≥1 W + ≥3 total) | 69.2% | #14 |
| Cluster K=5 X≤3% | 69.8% | #14 |
| Composite (эффективный) ≥ 0.7 | 73.1% | 0 missed |
| Worked (проработанный) tot ≥150 | 57.4% | #15+#48 |
| Slope correct (LB=7d, ≥2 swept) | 56.1% | #14 |
| Fresh × Old crossing | 56% | 0 (geographically wrong) |

#### Утверждено: C8 = ≥2 W-aligned swept VWAPs

- **WR 80.0%** standalone (n=65, conf=52)
- Catches 1 important pivot
- **0 missed** (#14, #15, #48, NEW не ловятся)
- Marginal к C1-C7: +13 unique events, **WR=46%** (≈baseline)
- В basket-WR не растёт, но C8 - канонически sound сигнал

## Архитектурный диагноз

### 22 targets / 4 missed

Из `~/smc-lib/prediction-algo/force_model_v3/targets_22.py`:

| # | Date MSK | Side | Status |
|---|----------|------|--------|
| ... | (18 caught) | | ✓ in C1-C7 basket |
| **#14** | 2026-03-04 15:00 | FH | **missed** — cluster 5 swept (1 W), spread 1.88% |
| **#15** | 2026-03-08 15:00 | FL | **missed** — 1 swept (age 1026d, 0 W) |
| **#48** | 2026-05-06 03:00 | FH | **missed** — 1 swept (age 776d, 0 W) |
| **NEW** | 2026-05-10 15:00 | FH | **missed** — 1 W-aligned swept (age 788d, pierce 0.139%) |

**Покрытие basket:** 18/22 = 81.8%.

### 4 missed разделены на 2 группы

| Группа | Missed | Свойство W | Подход catch |
|--------|--------|-----------|--------------|
| **W-cluster** | #14 | 1 W из 5 swept | cluster K=5 X≤3% (69.8% WR) |
| **W-single-tight** | NEW | 1 W (tight pierce+close) | ≥1 W age≥365 (50% WR) |
| **D-only macro** | #15, #48 | 0 W | tot ≥150 + comp ≥0.5 (57% WR) |

**Не существует** одного VWAP-filter с WR ≥ 70% ловящего все 4 missed.

## Открытое — что дальше

- 4 missed остаются непокрытыми
- VWAP-канон **исчерпан** для catch missed при высоком WR
- Возможные следующие track'и:
  - Order flow / micro-LTF (1m volume profile, sweep maxV)
  - Multi-asset correlation (USDT.D, BTC.D)
  - Composite Sniper-like rules (если найдём правила для отдельных missed)
  - ML head на 308 features (как у Andrey) — но это не OR-basket

## Артефакты

### Скрипты (новые)

- `~/smc-lib/scripts/baseline_1267_gen.py` — generates baseline F1∩F2∩F3 (1275 events)
- `~/smc-lib/scripts/baseline_bulkowski_xjoin.py` — Bulkowski cross-join
- `~/smc-lib/scripts/baseline_andrey_features_xjoin.py` — VSA/Nison/sweep features
- `~/smc-lib/scripts/andrey_features_independence.py` — pairwise overlap audit
- `~/smc-lib/scripts/compare_basket_vs_bulkowski.py` — sets comparison
- `~/smc-lib/scripts/plot_basket_vs_bulkowski_12h.py` — visualization
- `~/smc-lib/scripts/missed_vwap_interaction.py` — initial missed VWAP audit
- `~/smc-lib/scripts/c8_vwap_cluster_grid.py` — cluster grid
- `~/smc-lib/scripts/c8_vwap_hybrid_grid.py` — hybrid cluster+macro
- `~/smc-lib/scripts/c8_vwap_tight_grid.py` — tight pierce/close filters
- `~/smc-lib/scripts/c8_vwap_macro_tight.py` — single mode macro
- `~/smc-lib/scripts/c8_vwap_multi_tf_fractal.py` — D-3D-W alignment
- `~/smc-lib/scripts/c8_vwap_fresh_old_cluster.py` — cross-age crossing
- `~/smc-lib/scripts/c8_vwap_slope_filter.py` — slope direction filter
- `~/smc-lib/scripts/c8_vwap_effectiveness_grid.py` — composite + total_inter
- `~/smc-lib/scripts/c9_vwap_worked_grid.py` — worked-level filter
- `~/smc-lib/scripts/c8_cluster_only_grid.py` — pure cluster grid
- `~/smc-lib/scripts/c8_integration_check.py` — C8 ∪ C1-C7 integration
- `~/smc-lib/scripts/c8_w_aligned_grid.py` — ≥1 W with supplementary
- `~/smc-lib/scripts/audit_2026_05_10_fh.py` — NEW missed audit

### Output данные (Desktop)

- `baseline_1267.parquet` (1275 events)
- `pred12h_basket_c1c8.parquet` (с C8 column)
- `etap_172_signals.csv`, `etap_172_stats.csv` (Andrey Bulkowski)
- `etap_173_signals_caught.csv`, `etap_173_feature_importance.csv` (Andrey ML)
- `etap_173_pred_*.csv` (6 prediction files)
- `etap_173_run.log`
- `etap_169_meta_labeling.py`, `etap_171.py`, `etap_172.py`, `etap_173.py`
- `andrey_tbm_results.csv`, `andrey_tbm_grid.csv`, `andrey_tbm_per_tier.csv`
- `andrey_equity_curve.png`
- `c8_vwap_*_grid.csv` (несколько grid выходов)
- `basket_vs_bulkowski_intersect.csv`
- `basket_vs_bulkowski_12h_2mo.png`, `_3mo.png`

### Скачанные обсидиан-файлы

`~/Desktop/andrey_vault/` — 150 .md (полный vault Andrey branch)

## Связано

- [[2026-06-03-bulkowski-12-reversal-detectors-etap-172]] — Andrey Bulkowski session
- [[bulkowski-top-12-patterns-for-btc-12h]] — Bulkowski выбор паттернов
- [[bulkowski-reversal-detectors-btc-12h-baseline]] — Bulkowski spec
- [[strategy-1-1-1-honest-audit-failed]] — canon: WR > 60% suspect
- `~/smc-lib/projects/pred12h-fractal-three-candles.md` — canon basket
- `~/smc-lib/projects/andrey-12h.md` — Andrey project mirror
- `~/smc-lib/prediction-algo/force_model_v3/targets_22.py` — 22 targets list
