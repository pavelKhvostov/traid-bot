# Живой рынок — финальная спецификация (lock 2026-06-15)

> **Главная концепция.** Рынок — живой organism. ML учится **чувствовать** куда цена пойдёт далее и **как** она туда придёт, через состояние 14 SMC элементов на 8 канонических TF. Никаких внешних индикаторов, макро, патернов извне SMC.

## 1. Аксиоматический базис

### 1.1 Состав
- **14 элементов** (canon-aware mitigation per Правило 2):  
  `ob, fvg, marubozu, block_orders, rdrb, i_rdrb, i_fvg, ob_liq, fractal, ob_vc, rb, breaker_block, mitigation_block, choch_bos`
- **8 TF** (anchor по Правилу 14):  
  `15m, 30m, 1h, 2h, 4h, 6h, 12h, 1D`
- **Роли zones** (Правило 8):  
  LIQ (⛽) · INE (🧲) · BLOCK (⚖) · STRUCT (CHoCH/BOS)

### 1.2 Что НЕ используется
- Никаких MA / EMA / HMA индикаторов
- Никаких macro filters (USDT.D / TOTAL2/3 / SPX/BTC)
- Никаких Lopez microstructure features (Amihud / Roll / Kyle / Entropy)
- Никаких Bulkowski / chart patterns
- Никаких 24-types / cascade / bb-model / 1.1.1 наследия

**Только 14 элементов + 8 TF + 1m данные.** Это финальная аксиома.

## 2. Anchor cadence

**Каждые 15 минут close** — модель «думает» 96 раз в день. На каждом anchor выдаёт structured prediction.

## 3. Input (что ML видит)

### 3.1 Per-zone features (для каждой active zone в snapshot)
- `element_type`, `tf`, `direction`, `role`
- `signed_distance_pct` от текущей цены (+ above / − below)
- `age_bars`, `mit_count`, `width_pct`
- `force` = TF_weight × age_weight × cluster_size
- `position`: above / inside / below price

### 3.2 Cross-TF intersection features (центральная часть)
**Это то что делает ML способной видеть "пересечения" — основа holistic view:**
- `is_inside_HTF_zone` — есть ли HTF zone которая включает эту LTF zone
- `overlap_with_HTF_count` — сколько HTF zones перекрывают
- `cluster_strength` — сколько zones из разных TF в overlap области
- `internal_vs_external` — внутри / вне HTF range  
- `nearest_HTF_zone_distance` — расстояние до ближайшей 12h+ zone

### 3.3 Structural & sweep memory
- CHoCH/BOS state per TF
- Sweep history (Fractal/RB/ob_liq.liq_zone events) за 72h окно
- Какие fractals ещё «горят» (unswept liquidity magnets) per TF

### 3.4 Past context (top-10 events за 72h)
- Last 10 significant events до anchor t
- Filter: HTF events (12h+) автоматически включены; LTF — только при magnitude ≥ 0.5%
- Encode как fixed feature: 10 events × (element, tf, direction, action, magnitude, time_delta) = 60 фич
- Используется для interpretability + контекст модели

## 4. Output (что ML предсказывает)

### 4.1 Output constraint — защита от тривиального

**Только 4h+ zones в output candidates** (`4h, 6h, 12h, 1D`). Никаких 15m/30m/1h/2h как target или correction. Это **архитектурный фильтр** — модель **обязана** выбрать 4h+ цель, даже если рядом куча мелких zones.

→ Предотвращает тривиальное «ближайшая 15m FVG = ответ».

### 4.2 Structured output (Layer A — ML)

```python
@dataclass
class Prediction:
    # Stage 1 — main goal
    main_goal_zone: ZoneRef          # из 4h+ candidates
    main_goal_probability: float     # после softmax
    main_goal_magnitude_pct: float   # ожидаемое % движения
    main_goal_direction: Literal["up", "down"]
    main_goal_time_hours: float      # через сколько часов
    
    # Stage 2 — next correction (conditional на main_goal)
    next_correction_zone: ZoneRef    # из 4h+ candidates
    next_correction_probability: float
    next_correction_magnitude_pct: float
    next_correction_time_hours: float
    
    # Past context для explanation
    past_context_events: list[Event] # last 10 significant
    
    # Stability
    confidence_score: float          # из meta-labeler
    stability_score: float           # smoothed across last 4 anchors
    main_goal_consistency: bool      # тот же main_goal что и 15 мин назад?
```

### 4.3 NLP rendering (Layer B — template, НЕ ML)

```
"Сейчас цена {price:.0f}. 
Цена движется в {main_goal.element} {main_goal.tf} зону {main_goal.level:.0f} 
с вероятностью {main_goal.p}%, ожидаемое движение {magnitude:+.1f}%.

В ближайшие {correction.time}h коррекция к {correction.level:.0f} 
в {correction.element} {correction.tf}, откуда движение к {main_goal.level:.0f} продолжится.

Past context: {past_events_brief}
Confidence: {confidence}/10, Stability: {'mind stable' if consistent else 'mind shifting'}."
```

→ Текст генерируется детерминистически из structured output. Не часть ML pipeline.

## 5. Ground truth (как разметить historical data)

### 5.1 Для каждого 15-min anchor `t`

**Main goal label:**
1. Forward-look 30 дней на 1m данных
2. Найти первую zone из 4h+ active set которая была hit (wick касание по канону Правила 2 — модель применима к каждой role)
3. Эта zone = main_goal ground truth для anchor t
4. Magnitude_pct = (zone_center - price_t) / price_t × 100
5. Direction = up / down
6. Time_hours = (zone_hit_ts - anchor_t) / 3600

**Correction label:**
1. Из всех zones 4h+ касающихся в окне `[t, t + min(time_hours, 7d)]`
2. Найти первую которая была hit ДО main_goal arrival
3. Эта zone = correction ground truth (если есть; иначе null)

**Past context:**
- Last 10 significant events до t (sweep / fill_full / break / CHoCH-BOS)

### 5.2 Что если main_goal не достигнут за 30d?

- Запись с `main_goal = nearest_4h+_zone_eventually_visited` либо null
- Этих anchors будет мало (~ <5% по estimate); exclude из training или low-weight

## 6. Архитектура

### 6.1 Two-stage LightGBM lambdarank

**Stage 1 — Main goal ranker**
- Candidates: все active zones 4h+ в snapshot @ t
- Features: per-zone (Section 3.1) + cross-TF (3.2) + structural (3.3) + past context (3.4)
- Group_id = anchor_t
- Label = 1 если эта zone — ground truth main_goal, иначе 0
- Output: softmax probability per candidate

**Stage 2 — Correction ranker (conditional на Stage 1)**
- Candidates: zones 4h+ между current_price и main_goal_level в направлении path
- Features: per-zone + cross-TF + main_goal context (как extra features)
- Group_id = anchor_t
- Label = 1 если эта zone — ground truth correction
- Output: probability per candidate

**Multi-task heads** (на каждой stage):
- magnitude_pct (regression)
- time_to_arrive_hours (regression)
- direction (binary)

### 6.2 Почему LightGBM, а не Transformer

- Lopez literature support'ит GBM для tabular event ML — sufficient на baseline
- Transformer overkill без доп фич (user директива)
- Two-stage даёт чёткий debugging и explainability
- Если результат недостаточен → Phase 2 Transformer (отложен)

## 7. Помошники ML (обязательные для baseline)

### 7.1 Meta-labeling (Lopez Lec 4)
- Primary: Stage 1 ranker → top-3 main_goal candidates
- Secondary: ML «уверена ли модель в top-1 vs top-2/3»
- Output: confidence_score ∈ [0, 1]
- Если low confidence → narrative говорит «mind неуверен — top-2 candidates близки»

### 7.2 CPCV (Lopez Lec 5) — 15 paths вместо 1
- Combinatorial Purged Cross-Validation
- 5 folds × 3 combinations = 15 train/test paths
- Distribution of metrics (top-1 accuracy, magnitude MAE) вместо точки
- Защита от backtest overfitting + Probability of Backtest Overfitting (PBO) расчёт

### 7.3 MDA Permutation Importance (Lopez Lec 4)
- Run ПОСЛЕ baseline fit
- Перемешиваем каждую feature, измеряем drop accuracy
- Honest importance vs default GBM gain (overestimates correlated features)
- Используется для feature pruning в Phase 2

### 7.4 Time-decay sample weights
- `weight = exp(-(t_max - t) * ln(2) / half_life)`
- half_life = 90 дней
- Новые samples весомее (адресует regime shifts)

## 8. Stability механизм

### 8.1 Inference smoothing (architectural)
- На каждый anchor → output structured prediction
- Усредняем по последним 4 anchors (60 мин окно), exponential weights decay=0.7
- Main_goal флип допускается только если confidence на новый > confidence на старый × 1.3
- Иначе output дрейфует постепенно

### 8.2 Emergent stability
- Forward-look 30d даёт consistent ground truth (15-min noise не влияет)
- Training data сама стабильна → model learns smooth predictions
- → Дополнительная регуляризация

### 8.3 Метрика stability
- `Δ_main_goal_15min` = % anchors где main_goal сменился относительно предыдущего
- `Δ_direction_4h` = % cases где direction перевернулся в 4-часовом окне без CHoCH HTF
- Целевые значения: `Δ_main_goal_15min < 15%`, `Δ_direction_4h < 5%`

## 9. Validation

### 9.1 CPCV метрики (15 paths)
- **Main goal accuracy**: top-1 hit rate (model main_goal был ground truth main_goal)
- **Top-3 hit rate**: ground truth в top-3
- **Magnitude MAE**: средняя ошибка предсказанного % движения
- **Time MAE**: средняя ошибка предсказанного timing
- **Correction accuracy**: top-1 hit rate для Stage 2
- **Per-year stability**: расхождение метрик по годам

### 9.2 Quality bar (целевые числа)
- Main goal top-1 accuracy: **≥ 40%** (random baseline ~5%, distance-only baseline ~25%)
- Top-3 hit rate: **≥ 70%**
- Direction accuracy: **≥ 65%**
- Magnitude MAE: **≤ 3%**
- Stability `Δ_main_goal_15min`: **≤ 15%**

Если CPCV распределение metrics показывает high variance → модель нестабильна, возвращаемся к design.

## 10. Pipeline (этапы 1-6)

| # | Этап | Часы | Машина |
|---|---|---|---|
| 0 | spec lock (этот документ) | ✓ done | Mac |
| 1 | Event detector + chronological log (14 × 8 TF на 6y BTC) | 3h | PC2 |
| 2 | Per-anchor state snapshot + past context (15-min cadence) | 3h | PC2 |
| 3 | Forward 30d ground truth labeler (main_goal + correction) | 2h | PC2 |
| 4 | Two-stage LightGBM ranker + multi-task heads + helpers (meta-labeling + CPCV + MDA + time-decay) | 4h | PC2 |
| 5 | NLP template renderer + sanity outputs на test anchors | 1h | PC2 |
| 6 | Stability validation + CPCV distribution + per-year report | 2h | PC2 |

**~15 часов** total на полный baseline + 4 помошника.

## 11. Опциональные помошники (Phase 2 если baseline недостаточен)

| # | Приём | Источник | Зачем |
|---|---|---|---|
| 5 | Fractional differentiation | Lopez Lec 3 | Stationary price features с памятью |
| 6 | SADF / CUSUM regime tag | Lopez Lec 8 | Bubble on/off как feature |
| 7 | Era-balancing | Numerai | Стабильность через regimes |
| 8 | Entropy features | Lopez Lec 8 | Predictability score |

## 12. Memory связи

- `[[feedback-untraded-area-is-magnet]]` — fundamental магнит
- `[[zone-class-liquidity-inefficiency-block]]` — таксономия ролей
- `[[feedback-fractal-liquidity-strength-and-sweep]]` — сила и sweep canon
- `[[feedback-htf-anchor-global-rule]]` — anchor=0 UTC, пн для W
- `[[feedback-ml-lookahead-must-verify]]` — anti-lookahead обязательная проверка
- `[[feedback-result-quality-bar]]` — honest top-5% ≥ 65%

## 13. Финальная сводка концепции

| Что | Решение |
|---|---|
| **Главная цель** | Прогноз HTF main_goal + next correction на 15-min cadence |
| **Output TF constraint** | Только 4h+ zones (защита от тривиального) |
| **Input vocabulary** | Все 14 элементов × 8 TF + cross-TF intersections + sweep history |
| **Anchor** | Каждые 15 мин close |
| **Ground truth** | Forward 30d look — первая 4h+ zone hit = main_goal |
| **Architecture** | Two-stage LightGBM lambdarank + multi-task heads |
| **Помошники ML** | Meta-labeling + CPCV + MDA + time-decay weights |
| **Stability** | Inference smoothing EMA + emergent через consistent labels |
| **Validation** | CPCV 15 paths + per-year stability report |
| **Машина** | PC2 (i5-14600KF + RTX 4070 — но GBM на CPU достаточно) |
| **NLP output** | Template-based rendering из structured (не часть ML) |

## 14. Прометей track — параллельно

Прометей живёт своим путём на **PC1** (RTX 5070 Ti). Это отдельный проект — different задача (snapshot ranker per t0), different mindset (cadence-based, не event-anchored), different output (strong-level of day).

**Живой рынок и Прометей не пересекаются по коду.** Этот проект — на PC2, чистый, без переиспользования Прометей-инфраструктуры.
