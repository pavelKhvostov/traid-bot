# Production Strategy v3 — HMA-only ML

**Дата фиксации:** 2026-06-09
**Backtest period:** 2020-01-01 → 2026-06-08 (6.4 года)
**Universe:** BTC/USDT, ETH/USDT (Binance perpetual futures)

---

## Зафиксированные результаты (backtest)

```
Frequency:           ~10 trades/месяц (после refinement D)
WR (исторически):    74.5%
E[R] per trade:      +1.12R
Per trade return:    ~0.7% (на median R% = 0.6%)
Σ R / год:           ~137R/год
Cumulative ROI:      ~82% / год (1x leverage)
                     ~410% / год (5x leverage)

Risk profile:
  Max DD исторически:  -6R   (= -6% account at 1% risk)
  Max losing streak:   6 trades
  Max win streak:      20 trades
  PBO:                 0.40 (acceptable)
```

---

## ШАГ 1. Детекция ob_vc 2h setup

Setup активен когда выполнены **все 8 канонов** (relaxed #7):

```
#1  ob.direction == fvg.direction
#2  HTF OB на 2h timeframe
#3  LTF FVG на 15m или 20m
#4  fvg.zone ∩ drop_area ≠ ∅
    drop_area (LONG):  [min(prev.low, cur.low), prev.open]
    drop_area (SHORT): [prev.open, max(prev.high, cur.high)]
#5  fvg.zone ⊆ [low_ob_vc, first_opposite_Williams_N2]
#6  OB actionable (не consumed wick-fill)
#7  fvg.c1.open_time ≥ prev.open_time (RELAXED canon)
    окно = 2×HTF (prev + cur bars)
#8  fvg.c3.close_time ≤ first_fractal.confirmation_time
```

Момент когда все условия выполнены → `born_ms`.

---

## ШАГ 2. Базовые filters (skip setup если)

### A. R% filter
```
R = entry - SL (LONG) или SL - entry (SHORT)
R% = R / entry × 100

Если R% < 0.5% → SKIP
```

### B. Asset/direction filter
```
⚠ asset=BTC AND direction=SHORT → SKIP
   (исторически WR 60.8% < goal)
```

### C. T-type filter
```
⚠ t_id ∈ {T1a, T11a, T9a} → SKIP
   (слабые типы с WR < 65%)
```

---

## ШАГ 3. Расчёт entry / SL / TP

### LONG:
```
Identify chosen FVG (top-FVG = max fvg_hi среди 15m/20m FVGs)

n_comp ≥ 2:  deep = 0.8  (глубокий вход)
n_comp = 1:  deep = 0.2  (shallow вход)

entry = fvg_hi - deep × (fvg_hi - fvg_lo)
SL    = drop_lo (= low_OB_VC)
R     = entry - SL
TP    = entry + 1.7 × R   (RR = 1.7)
```

### SHORT (зеркально):
```
chosen FVG = bottom-FVG (min fvg_lo)

entry = fvg_lo + deep × (fvg_hi - fvg_lo)
SL    = drop_hi (= high_OB_VC)
R     = SL - entry
TP    = entry - 1.7 × R
```

---

## ШАГ 4. Размещение limit-order

```
В момент born_ms:
  Place limit BUY (LONG) at entry price
  Place limit SELL (SHORT) at entry price

Время жизни: 14 дней (TBM horizon)
Если 14d entry не touched → cancel order, skip setup
```

---

## ШАГ 5. ML scoring (КРИТИЧНО — at entry_fill_ms!)

**В момент когда limit filled = `entry_fill_ms`:**

### 5.1 Compute features at entry_fill_ms (НЕ при born_ms!)
```
- 590 HMA features:
   10 lengths × 11 TFs × 5 derivatives (above, dist_pct, slope5/20, slope_accel)
   + per-TF aggregates (fan_compression, bars_since_cross, cross_count)
   + cross-TF aggregates (aligned_count_200/78, slope_coherence, cascade_freshness)

- 11 wait-window features:
   fill_delay_min
   wait_max_high_pct
   wait_min_low_pct
   wait_touched_sl_before_entry  ⚠ CRITICAL
   wait_volatility_change_pct
   wait_volume_total
   wait_directional_efficiency
   wait_net_move_pct
   wait_bars_count_15m, 1h, 4h
```

### 5.2 Cluster prune (как в training)
```
Drop features with |correlation| > 0.95 to a kept feature
→ keep ~325 features (как в training pipeline)
```

### 5.3 Apply LightGBM model
```
ensemble = [lgb_seed_42, lgb_seed_1337, lgb_seed_2024]
proba = mean(model.predict_proba(X)[:, 1] for model in ensemble)
```

### 5.4 Validation gate (критично!)
```
IF wait_touched_sl_before_entry == 1:
   → ABORT trade immediately at market
   (price spike to SL за 1 bar — setup compromised)
```

### 5.5 Decision threshold
```
IF proba >= 0.5888:
   → KEEP trade (hold until SL or TP)

IF proba < 0.5888:
   → CLOSE trade immediately at market
   (accept slippage cost — saves bigger expected loss)
```

---

## ШАГ 6. Trade management

```
После KEEP:
  - SL placed at low_OB_VC / high_OB_VC (без buffers)
  - TP placed at +1.7R (fixed RR)
  - No moving SL to BE
  - No partial exits
  - No trailing
  - Hold until SL/TP touched
  - Horizon: 14 дней

Если за 14d ни SL ни TP не touched:
  → Close at market (timeout exit)
  → Record fact, accept achieved R
```

---

## ШАГ 7. Risk management

### Position sizing
```
Risk per trade: 1% капитала

Position size = 1% / (R% × leverage)
Example: R% = 0.6%, leverage = 5x
       = 1% / (0.6% × 5)
       = 0.33% капитала размер позиции
       Effective risk = 0.33% × 0.6% × 5 = 1% ✓
```

### Лимиты
```
Max 3 trades open simultaneously
Max 2 trades в одном direction (LONG/SHORT)
Если на день уже 2 trades → wait next day
```

### Risk-off triggers
```
6 consecutive losses    → stop trading на 24h, review setup
10% account drawdown    → stop trading, full review модели
Daily PnL < -3%         → stop trading rest of day
```

---

## ШАГ 8. Edge cases

```
1. ob_vc fires но другой ob_vc того же типа active < 24h
   → SKIP (избегаем clustering)

2. Major news event в ±2h окне (FOMC, CPI, NFP)
   → SKIP (волатильность непредсказуема)

3. Funding rate extreme (> 100 bp или < -100 bp)
   → опционально SKIP (need verification)

4. Cur 2h bar имеет huge wick (wick > 3 × body)
   → setup может быть «sweep+reclaim»
   → проверить дополнительно или skip

5. Position size < min exchange tick
   → SKIP

6. Multiple ob_vc на разных TFs same direction:
   → priority: HTF (12h, 1d) > MTF (4h, 6h) > LTF (2h, 1h)
   → правила не меняются; ML score сам учитывает confluence
```

---

## Critical reminders

```
1. ML scoring ОБЯЗАТЕЛЬНО at entry_fill_ms, не born_ms!
   Это главный edge архитектуры (+0.12 AUC).

2. ВСЕГДА проверять wait_touched_sl_before_entry
   1 = abort regardless of proba

3. Refinement D filters (BTC short OUT, weak types OUT):
   Не декорация — backtest показал <65% WR для этих ячеек

4. Paper trade ≥1 месяц до live money
   Verify AUC держится на свежих setups

5. Re-train cadence
   Раз в 3-6 месяцев retrain на свежих data
```

---

## Технические артефакты

```
Trained model:    LightGBM ensemble of 3 seeds (42, 1337, 2024)
Architecture:     LGBMClassifier с params из ml/models.py
Training data:    features_v3_hma.parquet (10,738 events)
Features count:   ~325 после cluster_prune (|r|>0.95)
Target:           hit_RR_17 (binary: 1 if MFE >= 1.7R)
Threshold:        0.5888 (top-1100 selection)

Re-train script:  ~/smc-lib/projects/ob-vc/ml_v3/build_features_v3.py
                  + PC1 archive ml/ modules
```

---

## Ожидаемая performance (forward-looking)

```
Под условием что post-2026-06 регим напоминает 2020-2026:

Scenarios:
                          Year 1     5-year cum
  Conservative (60% WR):   +30R      +150R
  Base case (70% WR):      +94R      +470R
  Backtest (74.5% WR):    +137R      +685R

Drawdown ожидается:
  Worst monthly:           -10R до -20R (если 2023-like regime)
  Worst yearly:            +30R до +50R (если bear)
  Recovery typical:        2-4 месяца
```

---

## История изменений

```
2026-06-09: v3 initial production strategy
            Based on HMA-only feature pack at entry_fill_ms anchor
            Backtest на 6.4 года BTC + ETH
            WR 70.5% baseline / 74.5% refinement D
            
TODO (future iterations):
  v3.1: Add Bulkowski v3 layer (10 family detectors)
        Expected lift: AUC +0.03-0.05 → WR ~78-80%
  v3.2: Add SOL + other major pairs
  v4.0: Sequence ML (Transformer) если v3.x упрётся в потолок
```
