# Zone Correlations — Ranking Model (#2 roadmap)

> Spec для задачи **«корреляции между зонами»** — predict какая зона будет
> first-hit с учётом всех других активных зон в snapshot.
> Status: **spec approved** 2026-05-30. Решения зафиксированы пользователем.
> Owner: prediction-algo v3 (расширение текущей `LookupModel`).

## Проблема

Текущая `LookupModel` (`~/smc-lib/prediction-algo/model.py`) предсказывает
`P_first_hit_above/below` per zone **независимо** — без учёта геометрии других
активных зон в cut-off. Зафиксировано прямо в `zones_opinion.py:43-46`:

> P_first маржинальная — обнуляется на distance >0.5%, модель почти не видит
> first-touch далеко.

В реальности first-touch — это **гонка** зон same-side: ближайшие с высоким
`P_hit_D` блокируют дальние от того чтобы быть первыми. Эту корреляцию
текущая модель не моделирует.

## Цель

Дано snapshot всех активных зон в cut-off → ranking same-side:

```
INPUT (above-side):
  zone_A @ +0.3%, P_hit_D=0.65
  zone_B @ +0.8%, P_hit_D=0.85
  zone_C @ +1.5%, P_hit_D=0.90

CURRENT (marginal):
  P_first(A)=0.55  P_first(B)=0.50  P_first(C)=0.45  ← almost equal

RANKING MODEL (this task):
  P_first(A)=0.72  P_first(B)=0.22  P_first(C)=0.06  ← A blocks B,C
```

## Финальные решения (2026-05-30)

| # | Вопрос | Решение |
|---|---|---|
| 1 | Методы | **Все 3 метода как comparison:** Plackett-Luce + LightGBM Ranker + Pairwise classifier |
| 2 | Scope | **Both** — same-side ranker (2 модели: above-race, below-race) + cross-side binary classifier (UP_first vs DOWN_first); chain — сначала binary, потом same-side |
| 3 | Ground truth window | **24h (D)** — совпадает с P_hit_D базовой модели |
| 4 | Output | **Full ranking** всех зон со значимой дистанцией (≥0.30%) |
| 5 | Universe | BTC only (как у базовой модели) |
| 6 | Exclusion (ASVK-indicators) | **НЕ использовать** в zones-features: MoneyHands, VWAP, HMA, RSI, ViC, EVOT (live в отдельных agents) |
| 7 | Cut-off cadence | monthly (как `btc_full.csv` v2) |
| 8 | Walk-forward | 5y train / 1y test / monthly retrain (тот же канон) |

## Архитектура

```
Snapshot (cut-off ts) ──┐
                        │
                        ▼
                ┌────────────────┐
                │  Feature extr  │  (49 фичей per zone)
                └───────┬────────┘
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
   ┌─────────┐    ┌─────────┐    ┌──────────┐
   │  UP/DN  │    │ Above   │    │  Below   │
   │ binary  │    │ Ranker  │    │  Ranker  │
   │ classf. │    │ (same-  │    │ (same-   │
   └────┬────┘    │  side)  │    │  side)   │
        │         └────┬────┘    └────┬─────┘
        │              │              │
        └──────────────┼──────────────┘
                       ▼
            ┌────────────────────┐
            │   Decision chain   │
            │ P(side)→top-N того │
            │     same-side      │
            └────────────────────┘
```

Output:
```python
{
    "side_probability": {"up": 0.34, "down": 0.66},
    "above_ranking": [(zone_id, rank, P_first), ...],
    "below_ranking": [(zone_id, rank, P_first), ...],
    "expected_first_hit": (side, zone_id, time_estimate),
}
```

## Feature catalog (49 фичей)

**Все zone-only / structure-only. 0 ASVK-индикаторов.**

### A. Zone-internal базовые (8)

| фича | смысл |
|---|---|
| `tf` | ТФ зоны (1h/4h/12h/1d) |
| `type` | OB/FVG/RDRB/ob_vc/ob_liq/fractal/marubozu/block_orders/iFVG/iRDRB |
| `direction` | long/short |
| `distance_pct` | расстояние от текущей цены до ближней границы |
| `width_pct` | (hi-lo)/level |
| `age_bars` (в момент cut-off) | свежесть |
| `mitigation_model` | wick-fill / sweep / first-touch / sweep-open |
| `P_hit_D` (из текущей LookupModel) | базовый prior |

### B. Zone-internal birth context (7)

| фича | смысл |
|---|---|
| `body_to_wick_ratio_at_birth` | для OB/marubozu — сила импульса при создании |
| `displacement_size_pct_at_birth` | для FVG/RDRB |
| `swept_at_birth` | флаг: на birth-баре был sweep ликвидности |
| `htf_fractal_swept_within_24h_before_birth` | свежий HTF sweep до рождения |
| `n_prior_touches_inherited` | inherited zones — сколько касаний до born_ts |
| `level_round_number_dist_pct` | дистанция до круглого уровня |
| `same_direction_consecutive_at_birth` | сколько баров одного цвета до birth |

### C. Race-context — same-side соседи (10) ⭐ главный блок для #2

| фича | смысл |
|---|---|
| `n_competitors_closer` | зон same-side ближе цены |
| `n_competitors_within_0.5pct` | конкуренты в радиусе 0.5% |
| `n_competitors_within_1.0pct` | в 1.0% |
| `n_competitors_within_2.0pct` | в 2.0% |
| `competitor_max_P_hit_D` | max P_hit_D среди закрывающих доступ |
| `competitor_sum_P_hit_D_closer` | сумма P_hit_D конкурентов впереди |
| `nearest_competitor_dist_pct` | дистанция до ближайшего same-side впереди |
| `nearest_competitor_tf` | ТФ ближайшего конкурента |
| `nearest_competitor_type` | тип ближайшего конкурента |
| `relative_strength_rank` | rank нашей зоны по P_hit_D среди same-side |

### D. Structural inventory — что между ценой и зоной (8)

**Канон [[feedback-untraded-area-is-magnet]] — untraded областям нужно отдать ход.**

| фича | смысл |
|---|---|
| `n_untouched_FVG_between` | FVG-магниты по пути |
| `n_untouched_OB_between` | OB между |
| `n_untouched_marubozu_open_levels_between` | marubozu open-уровни как точечные магниты |
| `untraded_inventory_pct` | сумма widths untouched FVG/iFVG/marubozu между |
| `n_unswept_fractals_between` | BSL/SSL ликвидность по пути |
| `n_inverted_zones_between` | флаг: opposite-direction зоны (= obstruction) |
| `nested_in_HTF_zone` | флаг: эта зона вложена в HTF same-direction |
| `wider_zone_overlap` | флаг: есть wider same-direction зона перекрывающая |

### E. Cross-side context — opposite (5)

| фича | смысл |
|---|---|
| `n_zones_opposite_total` | всего значимых на противоположной |
| `nearest_opposite_dist_pct` | дистанция до ближайшей противоположной |
| `nearest_opposite_max_P_hit_D` | сила ближайшей противоположной |
| `mean_P_hit_D_opposite_side` | средняя сила противоположной |
| `imbalance_above_minus_below` | asymmetry magnetic mass |

### F. Global snapshot (7)

| фича | смысл |
|---|---|
| `n_zones_total_significant` | всего значимых (≥0.30%) на обеих сторонах |
| `n_HTF_zones_above` | только D/12h-зоны выше |
| `n_HTF_zones_below` | только D/12h-зоны ниже |
| `nearest_HTF_zone_above_dist_pct` | до ближайшей HTF-зоны сверху |
| `nearest_HTF_zone_below_dist_pct` | то же снизу |
| `time_since_last_swept_zone_h` | свежесть рыночной активности |
| `n_swept_zones_last_24h` | количество свежих свипов за сутки |

### G. Temporal (4)

| фича | смысл |
|---|---|
| `hour_of_day_utc` | session timing |
| `day_of_week` | Mon/Fri effects |
| `hours_since_HTF_extremum` | расстояние от последнего D-HH/LL |
| `price_position_in_24h_range_pct` | где цена в недавнем рейндже (0=low, 100=high) |

## Ground truth labels

Окно: **24h** после `cut_off_ts`. Для каждой зоны определяем:

| label | условие | relevance score (LGBM Ranker) |
|---|---|---|
| `first_hit` | зона задета **первой** на своей стороне в 24h | 2 |
| `also_hit` | задета в 24h, но не первой | 1 |
| `not_hit` | не задета в 24h | 0 |

**Touch criterion:**
- LONG zone (side=below): `low ≤ hi` (цена впервые вошла сверху)
- SHORT zone (side=above): `high ≥ lo` (цена впервые вошла снизу)

**Group key** для ranking-models:
- Same-side ranker → `(cut_off_ts, side)`
- Binary cross-side → `cut_off_ts`

## Dataset structure

```
corr_dataset.parquet
columns:
  cut_off_ts        - timestamp snapshot
  zone_id           - unique zone identifier
  side              - 'above' / 'below'
  ...49 features... - все из секции выше
  rel_score         - {0, 1, 2} relevance label
  time_to_hit_h     - время до touch в часах (NaN если не задета)
  was_first_hit     - binary: задета первой на своей стороне
  side_first_hit    - 'above' / 'below' / 'none' (для cross-side модели)
```

Cut-off cadence: **monthly** (~72 cuts на 6y). Ожидаемый размер: ~500K rows
(72 cuts × ~7K зон в среднем snapshot).

## Метрики evaluation

| метрика | для какой модели | цель |
|---|---|---|
| **NDCG@5** | same-side ranker | ≥ 0.65 (baseline marginal ~0.45) |
| **Top-1 accuracy** | same-side ranker | ≥ 50% (baseline ~30%) |
| **Spearman correlation** | same-side ranker | ≥ 0.40 |
| **AUC-ROC** | cross-side binary | ≥ 0.65 |
| **Brier score** | cross-side binary | ≤ baseline × 0.85 |
| **Calibration slope** | both (post isotonic) | 0.95 - 1.05 |

## 3-метода comparison

Все 3 модели на **одном** датасете для честного сравнения:

### 1. Plackett-Luce (baseline)
- Scoring: `s_i = w·features_i + b` (линейный).
- Softmax loss: `P(order) = ∏ exp(s_i) / Σ_remaining exp(s_j)`.
- Implementation: torch + custom training loop, или `choix` package.

### 2. LightGBM Ranker (main contender)
- LambdaRank objective, `group` = same-side per cut_off.
- Output: relevance score → isotonic calibration → P_first.
- Hyperparams: n_estimators=500, num_leaves=63, lr=0.05.

### 3. Pairwise classifier (heavy alternative)
- Для каждой пары `(zone_i, zone_j)` same-side same-cut_off → `P(i first than j)`.
- LightGBM Binary Classifier на 2× features (concat zone_i и zone_j).
- Aggregation: Bradley-Terry MLE → final score per zone.

**Ожидание:** LGBM Ranker > Pairwise > Plackett-Luce.
Plackett-Luce служит **sanity baseline** — если он почти равен LGBM, значит
race-context фичи не имеют non-linear interactions (что маловероятно).

## План имплементации

1. **Этот документ** ✅ approved 2026-05-30
2. **Feature extractor** — `~/smc-lib/prediction-algo/correlations/features.py`
   - функция `extract_features(snap_df, cut_off_ts, df_1m, resampled) → DataFrame`
   - reuse существующих helpers где возможно
   - 49 features per zone, наследует существующий snapshot-механизм
3. **Dataset builder** — `~/smc-lib/prediction-algo/correlations/builder.py`
   - cycle: cut_offs ∈ monthly grid × snapshot → features × ground truth
   - heavy compute → **PC1 archive**
4. **PC1 archive** — `compute-YYYY-MM-DD-corr-dataset/`
   - input: btc_full v2 + `BTCUSDT_1m_vic_vadim.csv`
   - output: `corr_dataset.parquet` (~500K rows)
5. **PC2 archive** — `compute-YYYY-MM-DD-corr-training/`
   - 3 модели × 2 same-side (above/below) + 1 cross-side binary = 7 моделей
   - Walk-forward 5y/1y/monthly
   - Output: per-method metrics + predictions + winner model artifact
6. **Evaluation** — на Mac, сравнение методов, выбор winner
7. **Integration** — встроить winner в `zones_opinion.py` (override marginal P_first)

## Зависимости

| компонент | где |
|---|---|
| Zone snapshot | `~/smc-lib/prediction-algo/zones.py` (`snapshot_from_events`) |
| Resampler | `~/smc-lib/prediction-algo/resample.py` |
| 1m данные | `~/traid-bot/data/BTCUSDT_1m_vic_vadim.csv` |
| Walk-forward harness | `~/smc-lib/prediction-algo/validate.py` (адаптировать под ranking) |
| Existing base model | `~/smc-lib/prediction-algo/model.py` (`LookupModel`) → как prior P_hit_D |
| Existing dataset | `~/Desktop/btc_full.csv` v2 (10.17M rows) — переиспользуем |

## Что НЕ входит в zones-ranking

Чтобы не повторять и зафиксировать exclusion:

| Категория | Почему НЕ используем |
|---|---|
| MoneyHands (bw2, color, MF, stoch) | live в money_hands agent |
| VWAP (anchored, session) | live в vwaps agent |
| HMA (78, 200) | live в trendline agent |
| RSI (любой) | live в rsi agent |
| ViC (maxV, sweep_maxV) | live в vic agent |
| EVOT-confirmation logic (FVG-15m + LL/HH-фрактал) | live в evot/vic_evot agent (TBD) |
| ATR / cum delta | разрешено как «general fundamentals», но в этой задаче не используем для чистоты эксперимента |

## Связи

- [[prediction-algo-roadmap-5-questions]] — задача #2 из roadmap
- [[prediction-algo-final-results]] — текущая LookupModel (даёт P_hit_D как prior)
- [[zones_opinion]] — финальная integration target
- [[feedback-untraded-area-is-magnet]] — обоснование структурной inventory фичей
- [[feedback-fractal-liquidity-strength-and-sweep]] — обоснование sweep-related фичей
- [[zone-class-liquidity-inefficiency-block]] — таксономия зон (фича `type`)
- [[bounce-or-break]] — соседняя задача #3, complementary
