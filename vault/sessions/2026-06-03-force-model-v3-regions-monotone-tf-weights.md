---
date: 2026-06-03
project: zone-strength / force-model v3
status: closed
tags: [force-model, tf-weights, regions, monotone, williams, ml]
---

# Force-model v3: force-search regions + empirical monotonic TF weights

## TL;DR

- Построен **force-model v3** — pipeline для эмпирического обучения силы зон интереса
- Архитектура: 5 separate LR models (FVG, fractal, OB, block_orders, RDRB), **344 коэф** (8 TFs без 8h, 9/8 фичей на элемент)
- Search окно = **force-search regions** (SHORT [prior.H..cur.H] + LONG [cur.L..prior.L]) вместо all-zones
- Target — directional Williams: is_FH для SHORT, is_FL для LONG
- Liquidity-count в region — новая feature через backward HH/LL chain
- **Empirical monotonic TF weights** учены эмпирически (не наивные 1,2,4,...,72):
  - `1h=1.00 / 2h=1.48 / 4h=3.14 / 6h=4.20 / 12h=6.05 / 1d=7.65 / 2d=11.72 / 3d=13.04`
  - 3D ≈ **13× от 1h** (не 72×) — между sqrt и linear
- AUC test 0.65-0.83 по элементам; top-10 SHORT+LONG hit rate = 10/20 = **50%** (baseline 28%)
- 22 user-targets: только 2/22 в top-10 — модель ловит лучше baseline, но не различает специально важные

## Что сделали

### 1. Багфикс 3D resample (CRITICAL)

Старый `resample.py` использовал `origin = MONDAY_ANCHOR (2017-01-02 Mon)` для 3D. Continuous 72h ресемпл создавал **фантомные 3D bars на Sun/Wed/Sat/Tue/Fri** (вместо TV-канона Sat/Tue/Fri/Mon/Thu).

**Фикс:** для 3D использовать `EPOCH_ANCHOR (1970-01-01 Thu)` — Unix epoch. Все user-указанные даты (2026-01-31 Sat, 02-03 Tue, 02-06 Fri, 03-02 Mon) попадают на правильную сетку.

```python
origin = EPOCH_ANCHOR if tf == "3d" else MONDAY_ANCHOR
```

**Все 3D-анализы до 2026-06-03 были на сломанных bars** — невалидны.

Memory: [[feedback-3d-resample-monday-reset]]

### 2. Методология force-search regions

Принцип: каждая 12h candle имеет ДВЕ search-regions для force:
- **SHORT** = [prior 12h.HIGH .. current.HIGH] — где свеча wicked выше prior swing
- **LONG** = [current.LOW .. prior 12h.LOW] — где wicked ниже prior swing

Baseline:
- prior BULL (C > O) → baseline_short = prior.HIGH
- prior BEAR (C < O) → baseline_short = prior.LOW

Зоны давящие в region = candidates для force on current candle.

Memory: [[feedback-candle-zone-liquidity-methodology]]

### 3. Liquidity backward HH/LL chain

**Ошибка old:** считать все 4h bar highs попадающие в region.
**Correct:** backward HH chain — каждый level выше предыдущего pointer, останавливаемся при выходе за region.

Для 03-04 15:00 Candle: вместо 19 raw highs → **3 active liquidity peaks** (правильно).

### 4. Force-model v3 architecture

5 раздельных LR моделей под element type:

| Подмодель | Features × TFs | Коэф. |
|---|---|---|
| FVG | 10 × 8 | 80 |
| fractal | 10 × 8 | 80 |
| OB | 10 × 8 | 80 |
| block_orders | 9 × 8 | 72 |
| RDRB | 9 × 8 | 72 |
| **TOTAL** | | **384** |

Features per zone:
- per-element: age_bucket, first_touch (FVG), fill_state (FVG), failed_attempts (fractal), wick_size_atr (fractal), has_vc (OB)
- cross-element: direction_match, htf_trend_match, size_bucket
- candle context: candle_body_atr, candle_range_atr, candle_direction, prior_n_bars_trend
- **NEW:** liq_count_region (backward HH/LL chain)

Sources: `~/smc-lib/prediction-algo/force_model_v3/`

### 5. AUC results

Train на 2025-01..2026-01, test на 2026-02..2026-06:

| Model | AUC train | AUC test |
|---|---|---|
| FVG | 0.79 | 0.76 |
| fractal | 0.82 | **0.83** |
| OB | 0.77 | 0.79 |
| block_orders | 0.77 | 0.76 |
| RDRB | 0.78 | 0.65 |

### 6. Empirical monotonic TF weights

Constraint: `w_1h ≤ w_2h ≤ ... ≤ w_3d` (через параметризацию `w_i = w_{i-1} + softplus(δ_i)`).

Objective: maximize total wins = top-N actual FH + actual FL.

Nelder-Mead с 24 multi-start. **Optimal:**

| TF | Weight | vs naive×hrs |
|---|---|---|
| 1h | 1.000× | 1× |
| 2h | 1.481× | 2× (был слишком высокий) |
| 4h | 3.142× | 4× |
| 6h | 4.195× | 6× |
| 12h | 6.052× | 12× (в 2× меньше naive) |
| 1d | 7.654× | 24× (в 3× меньше) |
| 2d | 11.715× | 48× (в 4× меньше) |
| 3d | 13.036× | 72× (в 5.5× меньше) |

**Финдинг:** оптимум между sqrt(hrs) и naive×hrs. LTF не теряет смысл при 3D=13× а не 72×.

### 7. Top-10 SHORT + LONG hits

| Метрика | Value |
|---|---|
| Top-10 SHORT actual FH | 4/10 |
| Top-10 LONG actual FL | 6/10 |
| **Total top-20 wins** | **10/20 (50%)** |
| Baseline pivot rate | ~28% |
| 22-targets caught in top-10 | 2/22 (9%) |

### 8. Known missed cases (#14, #15, #48)

3 user-labeled important pivots что НЕ ловит basket C1-C7 (rule-based):
- #14: 2026-03-04 15:00 (FH) → force-v3 rank **26/100** (был 44 без TF weights)
- #15: 2026-03-08 15:00 (FL) → force-v3 rank **>30/114**
- #48: 2026-05-06 03:00 (FH) → force-v3 rank **74/100**

**ML force-v3 их тоже пропускает.** Текущие фичи + sum-aggregation fundamentally не различают эти pivots.

## Решения

- 3D anchor = Unix epoch (Thursday), не Monday-anchor
- Baseline для force-search = prior 12h's extreme в направлении prior's close
- Liquidity = active backward HH/LL chain (не raw bar highs)
- TF weights монотонны и эмпирически обучены (не hardcode)
- 8 TFs (без 8h)
- 22 user-targets — справочный список, общая цель = max overall wins

## Connections

- [[force-model-v2-architecture]] (предыдущая итерация, заменена v3)
- [[empirical-tf-weight-rejected]] (предыдущий ML-attempt отвергнут; v3 = новый pipeline)
- [[force-rank-inverted-vs-williams]] (force ≠ pivot — было найдено ранее)
- [[2026-06-03-empirical-tf-weight-rejected-force-rank-inverted.md]] (предыдущая сессия)
- `[[12h-fractal-orbasket-c1-c5]]` — rule-based basket (15/18 imp)

## Files

### Scripts (new):
- `~/smc-lib/prediction-algo/force_model_v3/`
  - `__init__.py` — module description
  - `labeling.py` — strict Williams n=2 (is_fh / is_fl)
  - `regions.py` — force-search region computation per candle
  - `features.py` — ATR, HMA-slope, age encoding, liquidity backward chain
  - `dataset.py` — directional dataset builder (region-filtered)
  - `train.py` — 5 LR models trainer
  - `run.py` — pipeline driver
  - `score.py` — single-candle scoring
  - `rank.py` — rank all candles in period
  - `targets_22.py` — 22 user-labeled important pivots
  - `optimize_tf_weights.py` — monotonic TF weight optimizer (Nelder-Mead)

### Modified:
- `~/smc-lib/prediction-algo/resample.py` — added EPOCH_ANCHOR for 3D
- `~/smc-lib/prediction-algo/zones.py` — (revert) using uniform tf_to_timedelta for 3D since bars regular

### Outputs:
- `~/Desktop/force_model_v3_coefficients_full.csv` — 384 optimal LR coefficients
- `~/Desktop/force_v3_ranking_20260201.csv` — full ranking 190 candles (uniform weights)
- `~/Desktop/imp_18_pivots.json` — 18 imp pivots (deprecated, now 22)

### Pending:
- Force-v3 final coefficients не сохранены централизованно (есть в model objects)
- 22-target catches требуют новых фичей (proximity weighting, cluster density, trend exhaustion)

## Что осталось / next steps

1. **Test on full 6y walk-forward** (heavy → Windows PC per [[feedback-heavy-compute-on-pc]])
2. **New features** для catching #14, #15, #48:
   - Proximity-weighted score (zones closer to high важнее)
   - Cluster density в узком price band
   - Trend exhaustion (cumulative move за N свечей)
3. **Alternative aggregation:** mean instead of sum, top-N max
4. **Save final model** + coefficients как deployment artefact (pickle)
5. **Live scoring** через `score.py` integration с force_opinion.py
