---
date: 2026-06-03
project: zone-strength / pred12h
status: closed
tags: [empirical-tf-weight, force-rank, calm-zones, inversion, naive-canon]
---

# Empirical TF_WEIGHT rejected, force-rank inverted

## TL;DR

- Empirical TF_WEIGHT через walk-forward LR на 4688 12h bars → **результат отвергнут** (методология сломана)
- Канон **naive (1,2,4,6,8,12,24,48,72) остаётся** для HTF dominance
- Grid search `rank_60d × bias_aligned` показал **инвертированный эффект**: strong force = **LOWER** P(W); calm zones = **HIGHER** P(W)
- 4 «потеряшки» (#14, #15, #48, 10-05) — все confirmed + strong force, **outliers** (против общего тренда)

## Что делали

### 1. Empirical TF_WEIGHT (отвергнуто)

Тренировали multinomial LR (–1/0/+1) на 54 features (9 TF × 6 типов: buyer, seller, top_long, top_short, wage_long, wage_short) walk-forward 1y/1mo за 6 лет.

```
EMPIRICAL std_norm: 1h=1.000, 8h=1.420, 3d=0.612
NAIVE:              1h=1,     8h=8,     3d=72
```

**User reject:** «этот расчет — бред. Чем старше ТФ тем более он значимы»

**Признаны ошибки:**
- Target = next-bar Williams слишком granular для HTF
- HTF zones «всегда около цены» → low discrimination
- Model accuracy 45% < baseline 49.5% → modeль не учится
- В zone_strength уже baked naive 72× → StandardScaler «выровнял» → coefficient ≠ structural weight

### 2. Raw space recompute

```
TF   naive   std_norm   raw_norm   effective_norm
1h   1       1.000      1.000      1.000
8h   8       1.513      0.166      1.088
3d   72      0.612      0.007      0.252
```

Все три метрики показывают **3d ≤ 1h** для next-bar Williams. Это task-specific (predict timing), НЕ опровергает canon HTF dominance для structural reactions.

### 3. TOP-10 strongest bars (naive) 2026-04-01 → 2026-06-03

```
#1  2026-06-01 15:00  total=5692  LONG  imbal=+5563
#2  2026-05-23 03:00  total=5171  LONG  
#3  2026-05-22 15:00  total=4878  LONG  FL ✓
#7  2026-05-29 03:00  total=3626  LONG  FH ✓
```

### 4. 4 потеряшки — рейтинг

```
#14  04-03 15:00  rank=955/4688 (top 20%)   24/121 60d window  SHORT ✓ aligned, confirmed
#15  08-03 15:00  rank=1044/4688            24/121             LONG ✓ aligned, confirmed
#48  06-05 03:00  rank=428/4688 (top 9%)    6/121              SHORT ✓ aligned, confirmed
—    10-05 15:00  rank=805/4688             15/121             SHORT ✓ aligned, confirmed
```

### 5. Grid search rank × bias_aligned

```
Baseline pred12h F1∩F2∩F3 ∪ C1-C7: n=1272, P(W)=48.7%

rank≤   aligned  n     P(W)    lift   t22    m4
   3    Y        77    28.6%   0.59×  1/22   0/4
   5    Y       111    32.4%   0.67×  1/22   0/4
  10    Y       184    36.4%   0.75×  2/22   1/4
  25    Y       378    39.2%   0.80×  8/22   4/4   ← all 4 missed caught
  50    Y       601    38.9%   0.80×  10/22  4/4
```

**Strong force = LOWER precision** для всех порогов. 

### 6. Inverted check (weak force / low imbalance)

```
Force percentile 60d:
  top 5%:   135 bars, P(W)=37.8% (0.78×)
  top 10%:   92 bars, P(W)=46.7%
  bot 30%:  303 bars, P(W)=57.4% (1.18×)

|imbalance| quintiles:
  Q1 low  (89):     255, P(W)=57.3% (1.18×)
  Q2     (327):     254, P(W)=61.0% (1.25×) ← peak
  Q3     (730):     254, P(W)=50.4%
  Q4    (1383):     254, P(W)=36.6% (0.75×)
  Q5 high (3012):   255, P(W)=38.0% (0.78×)
```

## Findings

1. **Naive TF_WEIGHT остаётся канон** — empirical test был методологически некорректен для HTF dominance claim
2. **Calm zones lead to Williams formation** — low imbalance Q2 = 1.25× lift (61% P(W))
3. **Strong force = trend continuation** — heavy buy/sell load means price keeps going, no reversal pivot
4. **4 потеряшки = outliers** — strong force AND confirmed (contrarian success), не representative
5. **Force-rank filter не улучшает precision** — даже catches all 4 missed at cost P(W) 48.7% → 39%

## Семантика inversion

```
Сильная LONG-загрузка зон → buyers support price up → trend continuation → NO FH
Сильная SHORT-загрузка   → sellers reject price down → trend continuation → NO FL
Calm/balanced zones      → no dominant force → bar может реверс → YES Williams
```

Это **противоположно naive intuition** «strong setup = strong signal». Для **timing pivot** нужна *тишина*, не *шум*.

## Open questions

- Можно ли использовать **calm filter** (|imbalance| ≤ 600) как **C9 condition** для pred12h?
  - Pro: lift 1.21× на baseline
  - Con: не ловит 4 потеряшки (они в Q4-Q5)
- Combine pred12h F1∩F2∩F3 + calm gate → насколько P(W) растёт?
- 4 потеряшки нужно искать **отдельным механизмом** (contrarian sweep signal?)

## Files

```
~/Desktop/force_all_bars_per_tf.parquet         — 4688 bars × 54 features (+ labels)
~/Desktop/empirical_tf_weight_coefs.parquet     — saved coefficients (rejected)
~/smc-lib/scripts/empirical_tf_weight_train.py  — ML training (методологически broken)
~/smc-lib/scripts/force_per_tf_all_bars_batch.py — батч snapshot 4688 bars (62 мин)
```

## Memory updates

- `feedback-empirical-tf-weight-methodology-broken.md` — методология сломана: standardization neutralizes naive scaling
- `force-rank-inverted-vs-williams.md` — strong force = lower P(W); calm zones = higher P(W); peak Q2 |imb|=327, lift 1.25×
- `4-missed-pivots-are-outliers.md` — #14 #15 #48 10-05 = contrarian success, не representative cluster

## Next session candidates

1. Test **calm filter (|imbalance|≤600) + pred12h F1∩F2∩F3** combined → C9 condition
2. Per-zone-event labeling (proper HTF empirical test)
3. Contrarian sweep mechanism для potential 4-missed-style outliers
4. SYNC project — продолжить Этапы 1-5
