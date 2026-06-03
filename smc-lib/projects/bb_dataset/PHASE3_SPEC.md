# bb-model Phase 3 — Trigger Zone + Strength Features

**Дата:** 2026-05-30
**Цель:** WR ≥ 60% AND RR ≥ 2.2 для ob_vc(1h+2h) с etap108 правилами

## Логика (user-articulated 2026-05-30 evening)

```
1. Market формирует HTF-зону интереса (anchor)
2. Цена возвращается → внутри HTF-зоны формируется ob_vc (reversal pattern)
3. Сила реакции зависит от:
   • Силы anchor HTF-зоны (size, age, mitigation depth, class)
   • Объёма ликвидности собранной свипом (BSL/SSL recently swept)
   • Глубины неэффективности (FVG/iFVG size)
   • Cascade pressure (recent HH/LL distance)
```

## Phase 2 vs Phase 3 — main change

Phase 2 считал **aggregate** контекст (12 containing zones, mixed surroundings). Result: AUC=0.54.

Phase 3 **идентифицирует конкретную trigger-зону** и измеряет ЕЁ свойства + добавляет recently-swept liquidity + cascade pressure.

## Trigger zone identification rule

Для каждого ob_vc event:

```python
candidates = [z for z in snapshot if
              z.tf >= "4h"  # HTF only (4h/6h/8h/12h/1d/2d/3d)
              and z.direction == ob_vc.direction
              and z contains ob_vc (overlap)]

# Score: most recently touched border in [born-24h, born]
for z in candidates:
    if z.direction == "long":  # LONG zone, lo is the support
        touched_ts = last 1m where low <= z.hi in [born-24h, born]
    else:  # SHORT, hi is the resistance
        touched_ts = last 1m where high >= z.lo in [born-24h, born]
    z.touch_recency = ob_vc.born - touched_ts  # hours

trigger = min(candidates, key=lambda z: z.touch_recency)
if not candidates: trigger = None (orphan flag)
```

Альтернативный fallback: oldest same-dir containing HTF (если no touch в окне).

## Feature catalog (~128 features)

### From Phase 2 (reused, some sliced) — 76 features

| Group | n | Notes |
|---|---|---|
| I. Containing zones | 12 | (cut from 18) |
| II. Surrounding density | 12 | (cut from 32 — keep aggregates per class) |
| III. Path | 12 | |
| IV. ob_vc self | 10 | |
| V. SMC sweep at birth | 6 | |
| VI. Liquidity BSL/SSL (unswept) | 7 | |
| VIII. Position in range | 5 | |
| IX. Confluence | 5 | |
| X. Temporal | 4 | |
| XI. Sweep magnitude (existing) | 3 | |
| **Σ Phase 2 retained** | **76** | |

### NEW in Phase 3 — 52 features

#### Trigger zone (anchor) — 15
| feature | description |
|---|---|
| `t_found` | Binary: trigger identified |
| `t_type` | OB / FVG / RDRB / iFVG / iRDRB / marubozu / block_orders / fractal / ob_liq / ob_vc (one-hot top types) |
| `t_class_block` / `t_class_inefficiency` / `t_class_liquidity` | One-hot class |
| `t_tf_minutes` | TF в минутах (240 / 360 / 480 / 720 / 1440 / 2880 / 4320) |
| `t_width_pct` | Ширина / price |
| `t_age_h` | Возраст в часах |
| `t_distance_pct` | Distance from ob_vc center to trigger center |
| `t_mitigation_wickfill` / `t_mitigation_sweep` | One-hot mitigation model |
| `t_n_prior_touches` | До этого touch |
| `t_touch_recency_h` | Часов от last touch до ob_vc born |
| `t_was_swept_at_birth` | Binary |
| `t_anchor_strength_score` | width × age × confluence count |

#### XII. Recently swept liquidity — 8
- `XII_n_HTF_fractal_swept_24h` (4h+)
- `XII_n_multi_TF_swept_at_same_level` (e.g. 1h+2h+4h fractals на одном уровне свипнуты = max stack)
- `XII_last_sweep_magnitude_pct` (% beyond swept level)
- `XII_time_since_last_HTF_sweep_h`
- `XII_BSL_vs_SSL_sweep_imbalance_24h` (signed: bull bias)
- `XII_max_sweep_magnitude_7d_pct`
- `XII_n_failed_sweeps_24h` (sweep + reverse)
- `XII_n_consecutive_sweeps_cascade_24h`

#### XIII. Cascade / drawdown pressure — 6
- `XIII_drawdown_from_HH_7d_pct`
- `XIII_drawup_from_LL_7d_pct`
- `XIII_days_since_HH_7d`
- `XIII_max_daily_drop_7d_pct`
- `XIII_velocity_pct_per_day_24h`
- `XIII_n_consecutive_red_days`

#### XIV. Wick-reclaim signature — 5
Bar(s) at/near ob_vc.born:
- `XIV_reversal_wick_to_body_ratio` (highest wick within 6 bars before signal)
- `XIV_reversal_close_back_pct` (how far close exceeds swept level)
- `XIV_bars_from_extreme_to_reclaim` (within 1h pre-signal)
- `XIV_volume_z_at_reversal_bar` (from 1m if present)
- `XIV_range_expansion_ratio_at_reversal` (ATR jump)

#### XV. Multi-TF level confluence — 4
At ob_vc anchor level (use trigger zone border if available, else ob_vc center):
- `XV_n_TFs_with_zone_at_same_level` (distinct TFs)
- `XV_n_zone_types_at_same_level` (distinct types)
- `XV_cross_class_confluence_score` (3 classes meeting = 3.0; 2 classes = 2.0)
- `XV_total_overlap_widths_at_level_pct` (агрегированная толщина зон в радиусе 0.1%)

#### XVI. Inefficiency strength — 5
- `XVI_largest_HTF_FVG_width_within_2pct_pct`
- `XVI_n_iFVG_within_2pct`
- `XVI_FVG_age_oldest_HTF_h`
- `XVI_total_untraded_inventory_HTF_pct` (sum width untouched FVG+iFVG+marubozu HTF same-dir within 2%)
- `XVI_inefficiency_at_round_number_dist_pct`

#### XVII. Run room for trade — 5
Куда цена может пойти:
- `XVII_dist_to_nearest_opposing_HTF_zone_pct`
- `XVII_dist_to_HTF_HH_pct` (7d high)
- `XVII_dist_to_HTF_LL_pct` (7d low)
- `XVII_clear_path_pct` (отсутствие магнитов между ob_vc и target — sum widths obstacles)
- `XVII_imbalance_size_to_clear_pct` (общий объём FVG/iFVG between)

#### XVIII. Pristine / fresh OB context — 4
- `XVIII_trigger_OB_birth_with_marubozu` (binary; only meaningful if trigger.type=OB)
- `XVIII_trigger_OB_n_prior_touches` (same as t_n_prior_touches but expanded)
- `XVIII_trigger_OB_body_to_range_at_birth`
- `XVIII_trigger_HTF_displacement_pct_at_birth`

## Label

Same as Phase 2: `trade_label = win(1)/loss(0)` from etap108 simulate_floating.

## Model architecture

Same: sklearn HistGradientBoostingClassifier + isotonic calibration, walk-forward
4y train / 1y test / monthly retrain.

## Output

```
output/
├── bb_obvc_1h2h_v3.parquet         dataset (~6683 × ~140 cols)
├── bb_predictions_v3.csv           walk-forward P_win + actual
├── bb_metrics_v3.json              per-fold AUC/Brier
├── bb_feature_importance_v3.csv    feature importance
├── bb_strategy_filter_v3.csv       WR/RR per threshold
└── *.log                           progress logs
```

## Success criteria

| Metric | Target | If not reached |
|---|---|---|
| Walk-forward AUC mean | ≥ 0.65 | Logic неверна или нужны кросс-индикаторы |
| WR at best threshold | ≥ 60% | Cascade анализ всё ещё не достаёт |
| RR at best threshold | ≥ 2.2 | Может быть достижимо но trade-off с WR |
| total_R after filter | > baseline +157R | Если меньше → фильтр не работает по PnL |

## Estimated runtime PC1

- precompute zone events (10 TFs × 10 types) — ~5-10 min
- per-event extract_features 128 features × 6683 × parallel — ~80-120 min
- train + filter — ~3 min
- **Total ≤ 3h**

## Key implementation notes

1. **Trigger identification надо делать ПРАВИЛЬНО** — это core change. Edge cases:
   - Orphan (no containing HTF) → `t_found=0`, остальные t-фичи default value
   - Multiple candidates equally recent — tie-break by largest width
2. **Recently swept fractals** требуют рассмотрения mitigation_model='sweep' и недавнего age
3. **Run room features** считают расстояние до **opposing HTF** — opposite direction, ближайшая
4. **Cascade pressure** считается на 1m rolling — нужен careful window

## Связи

- [[bb_model_phase2_result]] — baseline AUC 0.54
- [[bounce-or-break]] — оригинальная #3 roadmap spec
- 29-05-2026 case study — textbook trigger sweep+reclaim сетап в analysis
