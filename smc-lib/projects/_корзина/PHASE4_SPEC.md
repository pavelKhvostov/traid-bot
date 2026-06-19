# bb-model Phase 4 — Force × Liquidity Framework

**Дата:** 2026-05-31
**Цель:** WR ≥ 60% AND RR ≥ 2.2 для ob_vc(1h+2h) с etap108 правилами
**Baseline:** Phase 3 на тех же условиях достиг 41.5% / 2.5 — переход на принципиально другой framework

## Фундаментальная переориентация

Phase 2/3 пытались предсказать success через **count / aggregates** зон вокруг ob_vc:
- сколько zones containing
- per class density above/below
- count overlapping at level

Result: AUC ~0.54 (close to random). **52 added features didn't help.**

Phase 4 строит модель на 5 принципах (накопленных в сессии 2026-05-30/31):

### Принцип #1: Zone STRENGTH ≠ Zone COUNT
Силу зоны определяют HTF tier × age × class × **что она сделала** (liquidity collected при birth).

### Принцип #2: Multi-TF Force Aggregation
На каждом ТФ (1h, 2h, 4h, 6h, 8h, 12h, 1d, 2d, 3d) считать BUYER vs SELLER force отдельно. Net force per TF + total weighted sum.

### Принцип #3: Liquidity = Fuel
ob_vc заряжается ликвидностью, собранной свипами при формировании cur HTF candle. Sweep'нул HTF SSL/BSL/OB → загружен. Нет sweep'а → холостой выстрел.

### Принцип #4: Opposing HTF zones above/below = MAGNETS (не resistance)
Зоны противоположной стороны над ценой = не «защитники продавца», а **targets для buyer'а** (liquidity grab pools). Critical re-interpretation.

### Принцип #5: 3D dominance + LTF noise filter
Когда 3D net force ≫ 0 одной стороны — LTF противоположный сигнал = transient. На 6y данных это **predictive heuristic**.

## Архитектура Phase 4

```
Per ob_vc signal_time:
  
  1. Compute multi-TF force snapshot
     для каждого tf in (1h..3d):
       buyer_force[tf] = Σ strength(z) for LONG zones near price
       seller_force[tf] = Σ strength(z) for SHORT zones near price
  
  2. Identify structural anchor
     найти HTF-зону same-direction с max strength × age, контейнер ob_vc
  
  3. Identify opposing force structural anchor
     mirror: opposite-direction anchor
  
  4. Compute liquidity charge
     сколько HTF SSL/BSL/OBs свипнуто в [ob_vc.cur_open, signal_time]
  
  5. Features (~80, focused on strength/force/liquidity)
  
  6. Label: trade win/loss (etap108 simulate_floating, STRICT lookahead-fixed)
  
  7. Train LightGBM Binary + isotonic
```

## Feature Catalog (~80 features)

### A. Multi-TF Force (15) ⭐
Per-TF force balance — главная новизна.

| # | Feature | Description |
|---|---|---|
| 1 | `force_1h_net` | net BUYER−SELLER on 1h tier (within 3% of price) |
| 2 | `force_2h_net` | то же на 2h |
| 3 | `force_4h_net` | 4h |
| 4 | `force_6h_net` | 6h |
| 5 | `force_8h_net` | 8h |
| 6 | `force_12h_net` | 12h |
| 7 | `force_1d_net` | 1d |
| 8 | `force_2d_net` | 2d |
| 9 | `force_3d_net` | **3d — главный** |
| 10 | `force_LTF_net` | sum 1h+2h+4h |
| 11 | `force_MTF_net` | sum 6h+8h+12h |
| 12 | `force_HTF_net` | sum 1d+2d+3d |
| 13 | `force_TOTAL_net` | sum across all TFs |
| 14 | `n_TFs_own_direction_wins` | count из 9 ТФ где net force совпадает с ob_vc.direction |
| 15 | `force_dominant_TF_value` | максимальный по модулю TF — какая ТФ решает |

**Strength formula:**
```
strength(z) = TF_weight[z.tf]              # 1h=1, 3d=72
            × (1 + (age_h / 24) ** 0.4)    # mature = stronger
            × class_weight[z.class]        # block=3, ineff=2, liq=1
            × proximity_factor(z.distance_pct, max=3%)
            × mitigation_modifier          # untouched=1.0, wick-fill=0.7, sweep=0.5
```

### B. Force Alignment (8)
Бинарные align-features — самые предиктивные при асимметричных силах.

| # | Feature | Description |
|---|---|---|
| 1 | `aligned_with_3D` | binary: ob_vc.direction == sign(force_3d_net) |
| 2 | `aligned_with_HTF_tier` | sign(force_HTF_net) match |
| 3 | `aligned_with_MTF_tier` | sign(force_MTF_net) match |
| 4 | `aligned_with_LTF_tier` | sign(force_LTF_net) match |
| 5 | `LTF_vs_HTF_conflict` | binary: LTF и HTF не совпадают |
| 6 | `force_3D_dominance_ratio` | max(buyer_3d, seller_3d) / total_3d (0.5=balance, 1.0=monopoly) |
| 7 | `force_aligned_3D_strength_ratio` | own_3d_force / opposing_3d_force |
| 8 | `total_force_imbalance_pct` | abs(net_total) / sum_total * 100 |

### C. Structural Anchor (12)
Не просто containing, а сильнейшая поддерживающая HTF-зона.

| # | Feature | Description |
|---|---|---|
| 1 | `anchor_found` | binary: найдена ли trigger HTF zone same-direction |
| 2 | `anchor_tf_minutes` | TF в минутах (3d=4320 max) |
| 3 | `anchor_class_block` / `anchor_class_inefficiency` / `anchor_class_liquidity` | one-hot |
| 4-6 | (continued) | |
| 7 | `anchor_age_h` | возраст в часах |
| 8 | `anchor_width_pct` | ширина зоны |
| 9 | `anchor_strength_score` | computed strength |
| 10 | `anchor_was_swept_at_birth` | binary: зону свипнули при рождении (institutional pattern) |
| 11 | `anchor_n_prior_touches` | сколько касаний до текущего |
| 12 | `n_anchor_candidates` | сколько HTF same-dir zones containing ob_vc |

### D. Opposing Force (8)
Зеркальное: сила противоположной стороны на signal_time.

| # | Feature | Description |
|---|---|---|
| 1 | `opposing_anchor_found` | binary |
| 2 | `opposing_anchor_tf_minutes` |  |
| 3 | `opposing_anchor_strength_score` |  |
| 4 | `opposing_anchor_age_h` |  |
| 5 | `nearest_opposing_obvc_recency_h` | hours since last opposite ob_vc |
| 6 | `nearest_opposing_obvc_n_fvg` | сколько FVG components у соперника |
| 7 | `nearest_opposing_obvc_swept_count` | свипов перед его birth (его charge) |
| 8 | `strength_ratio_own_to_opposing` | own_anchor / opposing_anchor |

### E. Liquidity Charge ⚡ (12)
Sweep history при формировании cur HTF — главное «топливо».

| # | Feature | Description |
|---|---|---|
| 1 | `swept_HTF_SSL_24h_own_dir_count` | для LONG ob_vc — сколько SSL свипнуто |
| 2 | `swept_HTF_BSL_24h_own_dir_count` | для SHORT — сколько BSL |
| 3 | `swept_HTF_zones_consumed_24h_own_dir` | OB/FVG opposite direction пробитые своей стороной |
| 4 | `forming_daily_swept_prev_day_LL` | binary: текущий day in-progress свипнул prev day LL? |
| 5 | `forming_daily_swept_prev_day_HH` | binary для HH |
| 6 | `cur_HTF_candle_sweep_magnitude_pct` | насколько cur candle ушла за пределы prev range |
| 7 | `cur_HTF_candle_reclaim_pct` | насколько reclaim'нула обратно (institutional pattern) |
| 8 | `max_sweep_magnitude_7d_pct` | максимальная глубина sweep последние 7 дней |
| 9 | `n_failed_sweeps_24h` | sweep + reverse без пробоя |
| 10 | `n_consecutive_sweeps_cascade_24h` | каскад свипов на разных уровнях |
| 11 | `liquidity_charge_score` | weighted sum (TF × magnitude × age) |
| 12 | `ob_vc_uncharged` | binary: 0 свипов нашей стороны → холостой выстрел |

### F. HTF Magnets Above/Below (5)
Re-interpretation: opposite HTF zones как targets.

| # | Feature | Description |
|---|---|---|
| 1 | `n_opposing_HTF_magnets_above_2pct` | SHORT HTF zones over price (для LONG = upward targets) |
| 2 | `n_opposing_HTF_magnets_below_2pct` | mirror |
| 3 | `nearest_magnet_dist_aligned_pct` | дистанция до ближайшего «магнита» в направлении ob_vc |
| 4 | `magnet_strength_score_aligned` | sum widths × HTF × class в направлении ob_vc |
| 5 | `magnet_pull_imbalance` | aligned − contrary magnets |

### G. ob_vc Self (10)
Baseline свойств самого ob_vc — минимально.

| # | Feature | Description |
|---|---|---|
| 1-3 | `tf_hours`, `direction_long`, `width_pct` | |
| 4 | `n_fvg_components` ⭐ — **починить scan_ob_vc_events чтобы сохранялось правильно** |
| 5 | `fvg_components_LTF_diversity` | 1=only 15m, 2=only 20m, 3=both — confluence signal |
| 6 | `fvg_widths_ratio` | min/max FVG width (если ≥2) |
| 7 | `fvg_overlap_type` | subset / partial_overlap / disjoint (для multi-FVG) |
| 8 | `distance_to_zone_pct` | от текущей цены |
| 9 | `ob_age_to_signal_h` | от cur_open до signal_time |
| 10 | `position_in_HTF_tier_4h_range_pct` | где ob_vc в 4h range |

### H. Temporal (4)
Время суток / неделя.

| # | Feature | Description |
|---|---|---|
| 1 | `hour_of_day_utc` |  |
| 2 | `day_of_week` |  |
| 3 | `is_eu_us_overlap` |  |
| 4 | `hours_since_HTF_extremum` | от последнего D HH/LL |

### I. Historical Zone Memory (9) ⭐⭐⭐ NEW

«Зона интереса» как price band, протестированный multi-tier zones за месяцы.

| # | Feature | Description |
|---|---|---|
| 1 | `n_zones_aged_30d_in_local_band` | в радиусе 2% от цены: HTF zones возрастом 30+ дней |
| 2 | `n_zones_aged_60d_in_local_band` | 60+ дней |
| 3 | `n_zones_aged_90d_in_local_band` | 90+ дней (3 месяца — institutional memory) |
| 4 | `oldest_HTF_zone_age_d_in_band` | возраст самой старой выжившей |
| 5 | `band_resilience_score` | sum(age_d × class_w × tf_w) для HTF zones в band |
| 6 | `n_recent_touches_to_band_30d` | wick-fill касаний (свидетельство активности) |
| 7 | `n_recent_holds_to_band_30d` | сколько раз band «выдержала» |
| 8 | `aligned_with_historic_HTF_band` | binary: ob_vc.direction == direction защищающей band |
| 9 | `n_historic_OB_resistance_against_own_dir` | если LONG — сколько SHORT OBs возрастом 30+d НАД ценой |

### J. Volatility & Compression (6) ⚡ NEW

| # | Feature | Description |
|---|---|---|
| 1 | `atr_1h_pct` | ATR(14) на 1h в % от цены |
| 2 | `atr_4h_pct` | ATR(14) на 4h |
| 3 | `atr_ratio_current_vs_30d` | regime: current / 30d avg |
| 4 | `bb_width_pct_1h` | Bollinger Band ширина (period=20, std=2) |
| 5 | `bb_squeeze_active_1h` | binary: BB inside Keltner = компрессия |
| 6 | `range_contraction_ratio_24h` | last 24h range / mean 24h range за 7 дней |

### K. Classical Divergence (6) ⚡ NEW

Стандартные формулы (не ASVK).

| # | Feature | Description |
|---|---|---|
| 1 | `rsi_div_bullish_1h` | binary: price LL + RSI(14) Wilder higher = bullish div |
| 2 | `rsi_div_bearish_1h` | mirror |
| 3 | `rsi_div_bullish_4h` | то же на 4h |
| 4 | `rsi_div_bearish_4h` |  |
| 5 | `macd_div_bullish_1h` | MACD(12,26,9) histogram divergence bullish |
| 6 | `macd_div_bearish_1h` | bearish |

### L. Volume (non-ASVK) (6) ⚡ NEW

Стандартный exchange-volume анализ.

| # | Feature | Description |
|---|---|---|
| 1 | `volume_z_at_signal_1h` | z-score volume бара signal vs 60-bar avg |
| 2 | `volume_z_at_cur_HTF_sweep` | volume на cur 2h/4h свече sweep |
| 3 | `obv_slope_24h` | On-Balance Volume slope |
| 4 | `volume_climax_recent_24h` | binary: volume climax >2σ за 24h |
| 5 | `low_volume_at_signal` | binary: signal volume < median = slow drift |
| 6 | `volume_at_anchor_birth` | z-score volume на свече рождения trigger anchor |

### Σ = 102 features (compact, focused)

## TODO для Phase 5 (зафиксировано 2026-05-31)

**НЕ перестраивать Phase 4 под Strategy 1.1.1 cascade.** Phase 4 — самостоятельная strategy с ob_vc на 1h+2h как entry trigger.

**В Phase 5 — расширить ob_vc canon HTF_TO_LTF**:

```python
# elements/ob_vc/code.py — текущий канон:
HTF_TO_LTF = {
    "1h": ("15m", "20m"),
    "2h": ("15m", "20m"),
}

# Phase 5 расширение:
HTF_TO_LTF = {
    "1h": ("15m", "20m"),
    "2h": ("15m", "20m"),
    "4h": ("30m", "45m"),
    "6h": ("1h", "90m"),
    "12h": ("2h", "3h"),
    "1d": ("4h", "6h"),
}
```

**Зачем:** Phase 4 сейчас имеет ob_vc=0 в snapshot на TFs 4h-3d. Расширение даст макро-ob_vc контекст:
- В group_C (Structural Anchor) anchor может быть macro ob_vc на D/12h
- В group_A (Multi-TF Force) ob_vc будет contributing на ВСЕ ТФ, не только 1h+2h
- В Strategy 1.1.1 V2 это и есть классическая логика «наш entry ob_vc сидит внутри macro ob_vc старшего ТФ»

**НЕ менять entry rules** — мы по-прежнему торгуем ob_vc(1h+2h). Расширение помогает только context features в snapshot.

Требуется перепрогон `btc_full.csv` с расширенным каноном перед Phase 5.

## Label

**Same as Phase 3** but with STRICT fill_start fix:
```python
trade_label = win(1) / loss(0)
where:
  fill_start = max(c3.close, cur_HTF.close, opposite_fractal_n2_confirm.close)
```

Это устраняет 1-2h lookahead из Phase 2/3 baseline. Trade outcomes будут более «честные».

## Walk-forward setup

- 4y train rolling / 1y test / monthly retrain (12 folds)
- sklearn HistGradientBoostingClassifier + isotonic calibration

## Hypothesis & success criteria

| Metric | Phase 3 | Phase 4 target |
|---|---|---|
| AUC walk-forward mean | 0.540 | **≥ 0.65** |
| Folds AUC > 0.6 | 3/12 | ≥ 8/12 |
| Best WR at threshold | 41.5% | **≥ 60%** |
| Best implied RR | 2.59 | **≥ 2.2** |
| Best total_R | +44.8 | > +100R |

Hypothesis (sharp): **3D-aligned ob_vc + sweep-charged + structural anchor present** = высокое P_win. **Counter-3D + uncharged** = очень низкое.

Если AUC > 0.65 — direction confirmed.
Если AUC ~0.54 как Phase 3 — нужна или другая label scheme, или cross-indicator features (нарушение ASVK-agent principle), или DL approach.

## Prerequisites перед запуском Phase 4

| # | Task | Owner |
|---|---|---|
| 1 | **Strict lookahead fix** в `scan_ob_vc_events` + `simulate_floating` | task #21 + #22 |
| 2 | Re-baseline ob_vc backtest на strict — получить honest WR/RR/total_R | task #23 |
| 3 | **Fix n_fvg_components save** в scan_ob_vc_events (потеряно в Phase 2/3) | бонус-фикс |
| 4 | Multi-TF precompute с 1h-3d (Phase 3 уже умеет, переиспользуем) |  |

## Estimated Phase 4 runtime

| Этап | На PC1 16T |
|---|---|
| precompute zones (9 TFs × 10 types) | ~10 min |
| Per-event extract (74 features × 6683 × parallel) | ~30-50 min (fewer features чем Phase 3) |
| Train + filter | ~3 min |
| **Total** | **~45-70 min** |

Меньше Phase 3 (120 min) — потому что меньше фичей и большая часть берётся из существующего snapshot.

## Архив

`compute-2026-05-31-bb-model-phase4/` с:
- `smc_context_v4.py` — новый extractor с force / liquidity / anchor / magnets
- `builder_v4_parallel.py`
- `train_v4_walkforward.py`
- `run.bat`, README

## Связи

- `[[feedback-ob-vc-strict-detection-timing]]` — strict fix prerequisites
- 5 principles articulated в session 2026-05-30/31 user-led
- `[[prediction-algo-roadmap-5-questions]]` — родительский roadmap (это #3 + переосмысленный)
