---
name: force-model-v3-architecture
description: "Force-model v3 (2026-06-03): regions + directional Williams + empirical monotonic TF weights. Заменяет v2. 344 коэф."
metadata: 
  node_type: memory
  type: project
  originSessionId: 935dc13c-ff07-4b9a-8e0d-e35a63c1d0be
---

# Force-model v3 — final architecture (2026-06-03)

## Назначение

Empirical ML pipeline для оценки силы зон интереса воздействующей на 12h candle:
- predict P(candle = Williams i-high) on SHORT-region zones
- predict P(candle = Williams i-low) on LONG-region zones

Sum of per-zone P-scores × TF-weight = total reversal force on candle.

## Архитектура

### 5 раздельных LR моделей (per element type):

| Подмодель | Класс | Features × TFs | Коэф. |
|---|---|---|---|
| FVG | inefficiency | 10 × 8 | 80 |
| fractal | liquidity | 10 × 8 | 80 |
| OB | block | 10 × 8 | 80 |
| block_orders | block | 9 × 8 | 72 |
| RDRB | block | 9 × 8 | 72 |
| **TOTAL** | | | **344** |

### TFs (8): 1h, 2h, 4h, 6h, 12h, 1d, 2d, 3d (8h убран)

## Force-search regions

Для каждой 12h candle вычисляются TWO regions:
- **SHORT** [prior 12h.HIGH .. current.HIGH] — если current.H > prior.H
- **LONG** [current.LOW .. prior 12h.LOW] — если current.L < prior.L

Baseline зависит от направления prior candle:
- prior BULL → baseline_short = prior.HIGH
- prior BEAR → baseline_short = prior.LOW

См. [[feedback-candle-zone-liquidity-methodology]].

## Features per zone

**Per-element:**
- FVG: age_bucket, first_touch, fill_state
- fractal: age_bucket, failed_attempts, wick_size_atr
- OB: age_bucket, has_vc
- block_orders / RDRB: age_bucket

**Cross-element:**
- size_bucket (для interval zones)
- direction_match (зона = противовес candle direction?)
- htf_trend_match (slope HMA-78 на TF zone)

**Candle context (общие):**
- candle_body_atr, candle_range_atr, candle_direction, prior_n_bars_trend

**NEW в v3:**
- `liq_count_region` — backward HH/LL chain в region на 6 TFs (4h-3d)

## Target (directional)

Strict Williams n=2:
- SHORT zone → target = `is_FH` (high[i] > all 4 neighbors)
- LONG zone → target = `is_FL` (low[i] < all 4 neighbors)

Confirmation at open_time[i+n] = +24h after candle close.

## Empirical monotonic TF weights

Constraint: `w_1h ≤ w_2h ≤ ... ≤ w_3d`
Parameterization: `w_i = w_{i-1} + softplus(δ_i)` (gradient-friendly)
Objective: maximize top-N wins (actual FH/FL caught)

**Optimal weights (Nelder-Mead, 24 multi-starts):**

| TF | Weight (1h=1) |
|---|---|
| 1h | 1.000× |
| 2h | 1.481× |
| 4h | 3.142× |
| 6h | 4.195× |
| 12h | 6.052× |
| 1d | 7.654× |
| 2d | 11.715× |
| 3d | 13.036× |

**Между sqrt(hrs) и naive×hrs** — LTF не теряет полностью значимость при 3D=13× а не 72×.

## Performance

### Train AUC:
- FVG: 0.79, fractal: 0.82, OB: 0.77, block_orders: 0.77, RDRB: 0.78

### Test AUC (out-of-sample 2026-02..2026-06):
- FVG: 0.76, fractal: **0.83**, OB: 0.79, block_orders: 0.76, RDRB: 0.65

### Top-10 hit rate (overall actual FH/FL):
- SHORT top-10: 4/10 actual FH
- LONG top-10: 6/10 actual FL
- **Combined: 10/20 = 50%** (baseline ~28%)

### 22-targets recall:
- Only 2/22 in top-10 — модель ловит общие pivots но не различает специально важные

## Aggregation для inference

Per candle:
```
force_short = Σ tf_weight[z.tf] × P_pivot_z  (для всех z в SHORT region)
force_long  = Σ tf_weight[z.tf] × P_pivot_z  (для всех z в LONG region)
```

Sort candles by force → top-N = predicted pivots.

## Known limitations

1. **Sum-aggregation biased by zone count** — больше зон → выше score независимо от качества
2. **Candle context tautology** — `candle_range_atr` доминирует, отражает геометрию pivot, не силу зон
3. **3 missed imp** (#14 03-04, #15 03-08, #48 05-06) — force-v3 их тоже пропускает; нужны другие фичи

## Files

- Module: `~/smc-lib/prediction-algo/force_model_v3/`
- Coefficients output: `~/Desktop/force_model_v3_coefficients_full.csv`
- Ranking output: `~/Desktop/force_v3_ranking_20260201.csv`

## Связи

- [[force-model-v2-architecture]] — старая v2 (387 коэф, all-zones, без directional target) — **superseded**
- [[feedback-candle-zone-liquidity-methodology]] — методология force-search regions
- [[feedback-3d-resample-monday-reset]] — fix 3D anchor (нужен для корректных 3D bars)
- [[empirical-tf-weight-rejected]] — старый attempt empirical TF weights (отвергнут); v3 использует другой target
- [[force-rank-inverted-vs-williams]] — старый negative result; v3 это исправил через directional + region filter
- [[12h-fractal-orbasket-c1-c5]] — rule-based basket C1-C7 catches 15/18 imp; force-v3 — ML alternative

## Next steps

1. **Full 6y walk-forward** на Windows PC ([[feedback-heavy-compute-on-pc]])
2. **New features** для catching missed imp:
   - proximity-weighted scoring (zones closer to high важнее)
   - cluster density в narrow price band
   - multi-day trend exhaustion
3. **Pickle final model** для deployment
4. **Live scoring integration** через `score.py`
