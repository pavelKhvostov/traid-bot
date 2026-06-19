---
tags: [decisions, ml, feature-engineering, lessons]
date: 2026-06-09
related: [[ob-vc-hma-features-lookahead-fix]] [[strategy-ob-vc-v33-lean-picked]]
---

# Tabular ML видит snapshot, не trajectory

## Принцип

LightGBM / RandomForest / HistGradientBoosting принимают **одну точку в feature space** per event. Не путь, не последовательность, не историю изменений.

Два сетапа с identical features-snapshot но **разной траекторией** прошлого выглядят для tabular ML **одинаково**:

```
Snapshot:      [HMA_2h_9_dist = +1.5%]   ←  ML видит только это
Trajectory A:  -2.0 → -1.0 → +0.5 → +1.5%   (растущий momentum)
Trajectory B:  +3.0 → +2.5 → +2.0 → +1.5%   (ускоряющееся убывание!)
```

Эти setupы могут вести себя противоположно после entry, но ML не различает.

## Когда это проблема

- Setupы где **направление изменения** важнее **абсолютного значения**
- Прогноз movement за 14 дней по price-derived features
- Любой momentum-based filter

## Когда не проблема

- Features уже содержат "history": slopes (slope5 = HMA - HMA_5_back), bars_since_cross, count_30d
- Production где сетап одноразовый и context капсулирован в features
- Snapshot-natural задачи (классификация изображений)

## Что мы делали (правильно)

В v3 / v3.5 feature pack уже есть:
- `slope5_pct, slope20_pct, slope_accel` — производные, проксируют trajectory
- `bars_since_78_200_cross` — historical events count
- `cascade_freshness_min_bars` — across TFs

Это **частичный proxy** для trajectory. Но не равноценно sequential model.

## Что не делали

- LSTM / Transformer для price-time-series → ML видит actual trajectory
- Autoencoder для "regime embedding"
- Hand-crafted "pattern templates" matching

## Lesson

Tabular ML на price snapshot features имеет **фундаментальный потолок** AUC ~0.55-0.65 для multi-day directional prediction. Lookahead-based "edges" можно получить выше — но они не реализуемы live.

Если нужен realистичный AUC > 0.65 на crypto prediction:
1. Добавить proper sequence model (LSTM/Transformer)
2. Добавить features НЕ из price (volume, OI, sentiment, macro)
3. Снизить prediction horizon (1-day легче 14-day)
4. Принять что pure technical ML на крипте имеет ~5-15% edge ceiling
