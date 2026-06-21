---
name: pivot-money-hands-long-cascade-rule
description: Найдено правило LONG-cascade на MoneyHands multi-TF (2026-05-28) — bear-aligned + свежий cascade ≤1h даёт 62.9% accuracy для UP в 12h. SHORT-side не работает (асимметрия)
metadata: 
  node_type: memory
  type: project
  originSessionId: ff4f5d07-aadb-4148-b954-c32ba7546ea5
---

В рамках параллельного проекта `~/smc-lib/pivot-money-hands/` (задачи #9-#13) исследовали MoneyHands как multi-TF wave/cascade с целью предсказания pivot/direction. Чистый MH без extra features — AUC 0.5-0.57 (слабый signal). Но при определённой комбинации найдено реальное правило.

## Правило LONG-cascade (62.9% accuracy)

**Триггер:**
```
resonance_score ≤ -5
AND bw2_consensus ≤ -5
AND cascade_bear_freshness ≤ 1h
```

Где:
- `resonance_score` = (aligned_bull_TF − aligned_bear_TF) ∈ [-7, +7]
- `bw2_consensus` = (n_bw2_pos − n_bw2_neg) ∈ [-7, +7]
- `cascade_bear_freshness` = min{bears_since_bw2_bear_cross} по 7 TF в часах
- 7 TF = 3D, 1D, 12h, 8h, 4h, 2h, 1h

**Результат на 2 годах BTC:**
- n = 318 сигналов (~13/мес)
- p(up_12h) = **62.9%** vs baseline 52.4% (**+10.5%**)
- Trade direction: LONG (контрарианский — продажа закончилась, ждём bounce)

## Асимметрия — SHORT не работает

Симметричное правило bull-cascade (resonance ≥ +5, fresh bull) показало p_down ≈ 48-52% — нет edge. Это согласуется с tradingфактом:
- Bear capitulation на крипте — резкая, чёткие markers
- Bull tops — медленная distribution, sneaky

## Семантика "резонирующего накопительного эффекта"

Идея пользователя: bw2 → волны; MF (жёлтая) → подтверждение через 0; сигнал = когда **последний из TF только что флипнул bear, при всех остальных уже в bear** = cascade completes → exhaustion → bounce.

## Per-month consistency

Из 12 месяцев test:
- 8 месяцев: win-rate 56-87%
- 4 месяца: win-rate 33-45% (2024-07 проблемный: -2.16% mean ret)

Сигнал не universal — нужна или регимная фильтрация, или confluence с зонами интереса.

## Реализация

`~/smc-lib/pivot-money-hands/`:
- `multi_tf_mh.py` — snapshot MoneyHands на 7 TF
- `waves.py` — wave features (consensus, resonance, alignment)
- `cascade.py` — cascade timing features (bull/bear ages)
- `dataset.py`, `direction.py` — построение датасета + walk-forward
- `analysis.py`, `model.py` — EDA + xgboost-like classifier

## Memory

В будущих сессиях при «есть сигнал MoneyHands?» проверить:
1. Snapshot multi-TF MoneyHands
2. resonance_score
3. cascade_bear_freshness
4. Если все 3 условия LONG-cascade → высокая вероятность отскока

## Связи

- `[[zone-class-liquidity-inefficiency-block]]`
- `[[12h-fractal-prediction-final-strategy]]` — другой fractal-based pivot подход
- `[[prediction-algo-final-results]]` — параллельный проект (можно combine для confluence)
