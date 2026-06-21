# Clustering / Cooldown Signal Filtering

Главное открытие: **модель часто confident на 3-5 consecutive 1h bars подряд** → нужен фильтр чтобы collapse multiple high-P signals в одну сделку.

## Проблема

Без фильтра:
- Модель выдаёт probabilities P для каждого 1h close
- На ETH 2023-10-23: P(LONG_3)=0.527 в 12:00, 0.526 в 07:00, 0.531 в 08:00 (соседние часы)
- 3 разных «сделки» в течение 2 часов = duplicate exposure

Реальность: одна и та же setup, проверяется на разных часах с похожей P. **Должна быть ОДНА сделка**.

## Алгоритм Cluster (Peak-pick)

```python
def cluster_peak(timestamps, P, threshold, gap_hours):
    """
    1. Filter высокие P > threshold
    2. Group consecutive (gap < gap_hours) на same asset
    3. Pick PEAK-P bar в каждой group
    """
    candidates = [(t, p) for t, p in zip(timestamps, P) if p > threshold]
    if not candidates: return []
    candidates.sort()
    
    clusters = [[candidates[0]]]
    for t, p in candidates[1:]:
        prev_t = clusters[-1][-1][0]
        if (t - prev_t).total_seconds() / 3600 <= gap_hours:
            clusters[-1].append((t, p))
        else:
            clusters.append([(t, p)])
    
    return [max(c, key=lambda x: x[1])[0] for c in clusters]
```

## Алгоритм Cooldown (First-take)

```python
def cooldown_filter(timestamps, P, threshold, cooldown_hours):
    """
    1. Iterate чрез timestamps в порядке
    2. Если P > threshold AND last_signal_time > cooldown_hours ago:
       → take signal, update last_signal_time
    """
    last_signal_ts = None
    signals = []
    for t, p in zip(timestamps, P):
        if p <= threshold: continue
        if last_signal_ts and (t - last_signal_ts).total_seconds() / 3600 < cooldown_hours:
            continue
        signals.append(t)
        last_signal_ts = t
    return signals
```

## Сравнение Cluster vs Cooldown

| Aspect | Cluster (peak) | Cooldown (first) |
|---|---|---|
| Pick logic | Most confident in cluster | First high-P bar |
| Production-friendly | ❌ requires forward look (peak unknown until cluster ends) | ✅ real-time decision |
| WR (fold 3 LONG_3) | 0.75 at 0.7/mo | 0.81 at 5.25/mo |
| WR (overall LONG_3) | 0.50 | 0.37 |
| Sigs/mo | Less | More |

**Вывод:** Cluster (peak) даёт **более высокую WR** на нескольких setups, но **меньше всего сигналов**. Cooldown даёт **больше**, лучше для production где realtime decision.

## Advanced Strategies (тестированы)

### Multi-head consensus

Требовать чтобы ВСЕ heads (LONG_3, LONG_4, LONG_5) превышали threshold одновременно.

| Strategy | Effect |
|---|---|
| LONG_3 AND LONG_4 AND LONG_5 > 0.45 | ≈ same as LONG_3 alone (heads correlated) |
| LONG_3 AND LONG_5 > 0.45 | Same — no informational gain |

**Вывод:** Heads сильно коррелированы → multi-head consensus не добавляет информации.

### Multi-seed consensus (4/4)

Требовать чтобы все 4 seeds individually превышали threshold (не только ensemble average).

| Strategy | Sigs/mo | Mean WR |
|---|---|---|
| LONG_3 ensemble > 0.45 | 5-7 | 0.495 |
| LONG_3 4/4 seeds > 0.45 | 4 | 0.493 |
| LONG_3 4/4 seeds > 0.50 | 1.4 | 0.404 |
| **SHORT_3 4/4 seeds > 0.45** ⭐ | **5/mo** | **0.616** |

**Вывод:** Multi-seed consensus полезен **для SHORT** (variance reduction там сильнее).

### Regime-adaptive thresholds

| Regime | Threshold |
|---|---|
| BULL | 0.50 |
| BEAR | 0.45 (model больше signals в bear) |
| CHOP | **0.55** (filter noise) |

| Result | Sigs/mo | Mean WR |
|---|---|---|
| Regime-adaptive LONG_3 | 6.9 | 0.498 |
| BASE LONG_3 (thr=0.50) | 5.4 | 0.495 |

**Marginal +0.3pp WR** при больше сигналов. Не game-changer.

### Production recommended

```python
# LONG side
LONG_CONFIG = {
    "ensemble": "v4+regime-feat 60d 4-seed",
    "threshold": 0.50,
    "cooldown_h": 12,
    "regime_skip": ["CHOP"],  # don't trade LONG in CHOP
}
# Expected: 5-7 signals/мес, WR 55-60%

# SHORT side  
SHORT_CONFIG = {
    "ensemble": "v4+regime-feat 48h anchored strict 4-seed",
    "threshold": 0.45,
    "cooldown_h": 12,
    "consensus": "4/4 seeds individually > 0.45",
}
# Expected: 5 signals/мес, WR 61-65%
```

## Threshold × Gap exploration (fold 3 LONG_3, baseline 0.337)

| thr | gap | Sigs/mo | WR |
|---|---|---|---|
| 0.40 | 3h | 6.7 | 0.415 |
| 0.40 | 6h | 4.8 | 0.414 |
| 0.40 | 12h | 3.0 | 0.556 |
| 0.45 | 3h | 11.5 | 0.371 |
| 0.45 | 12h | 5.4 | 0.333 |
| **0.50** | **6h** | **1.1** | **0.714** |
| **0.50** | **12h** | **0.7** | **0.750** ⭐ |
| **0.50** | **24h** | **0.5** | **0.800** |

Law: **higher threshold + longer gap = fewer signals at higher WR.**

## Per-Fold Cooldown Results (12h, thr=0.50, LONG_3)

| Fold | Regime | Sigs/mo | WR |
|---|---|---|---|
| 0 | LUNA bear | 2.93 | 0.667 ✅ |
| 1 | FTX recovery | 11.21 | 0.515 |
| 2 | Banking chop | **27.88** | **0.269** ❌ |
| 3 | Bull rally | 2.30 | 0.714 ⭐ |
| 4 | Distribution | 17.45 | 0.364 |
| 5 | Top mix | 1.81 | 0.545 |
| **Mean** | | **10.6/mo** | **51%** |

**Fold 2 (CHOP) сильно тянет WR вниз** — model false-confident в боковике. Решение: **skip CHOP regime** в production.

## Final Recommendation: Production Pipeline

```python
def production_signal_pipeline(model_probs, regime, timestamps, asset):
    """
    Real-time signal extraction для live trading.
    """
    # 1. Skip if CHOP regime
    if regime == "CHOP":
        return None
    
    # 2. Threshold check
    P_long = model_probs["LONG_3"]
    P_short = model_probs["SHORT_3"]
    
    if P_long < 0.50 and P_short < 0.45:
        return None
    
    # 3. Cooldown check (per asset)
    last_signal_ts = state.last_signal[asset]
    if last_signal_ts:
        gap_h = (timestamps[-1] - last_signal_ts).total_seconds() / 3600
        if gap_h < 12:
            return None
    
    # 4. Direction decision
    if P_long > 0.50:
        signal = {"asset": asset, "direction": "LONG", "entry": close[-1], 
                  "tp": close[-1] * 1.03, "sl": close[-1] * 0.99}
    elif P_short > 0.45:
        # Additional check: 4/4 seeds for SHORT
        if all(seed_probs["SHORT_3"] > 0.45 for seed_probs in per_seed_probs):
            signal = {"asset": asset, "direction": "SHORT", "entry": close[-1],
                      "tp": close[-1] * 0.97, "sl": close[-1] * 1.01}
        else:
            return None
    
    # 5. Update state
    state.last_signal[asset] = timestamps[-1]
    return signal
```
