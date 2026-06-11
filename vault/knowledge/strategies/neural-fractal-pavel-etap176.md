---
tags: [strategy, reversal, fractal, ml, neural-net, pavel]
date: 2026-06-10
status: research-baseline
branch: pavel
related: [research/elements_study/etap_176_neural_fractal_pavel.py]
---

# Нейросеть для предсказания хорошего фрактала-разворота (ветка pavel) — etap_176

## Что это

Полноценная **нейросеть (PyTorch, MPS на Mac M5)** для предсказания «хорошего» фрактала-разворота на close 12h-свечи. Метка — 5%-race (как [[good-fractal-5pct-race-predictor-etap174]]). Обучена по стандартам López de Prado + на эталонных фичах Андрея (= канон ICT). Ветка `pavel`.

## Стандарты из книг (применены)

**López de Prado «Advances in Financial ML»** (см. [[adv-fin-ml-индекс]]):
- **Triple-barrier labeling** = метка 5%-race (TP +5% / SL снятие экстремума / timeout 30д).
- **Purged K-Fold + Embargo** (5 фолдов, embargo 14 баров): train/val не пересекаются по времени жизни меток. Метка живёт 30д → из train выкидываются метки, чьи горизонты пересекают val-период.
- **Sample weights по uniqueness**: вес ∝ 1/concurrency (перекрывающиеся по времени метки весят меньше — борьба с serial correlation).
- **Sanity shuffle-тест**: на перемешанных метках AUC должен быть ~0.5.

**Эталон Андрея = канон ICT** (фичи из [[good-fractal-5pct-race-predictor-etap174]] / etap_175):
- sweep_SSL/BSL_mag/failed (ICT **Liquidity Sweep / DOL** — топ-importance у Андрея),
- OB/FVG зоны-дистанции, Bulkowski top-5 fires, фрактал-структура. Всего 62 фичи.

**Архитектура сети (DL-стандарты для табличных фин-данных):**
- MLP с **BatchNorm + Dropout(0.3) + residual-блоки** (GELU), не голый Linear.
- **Focal loss** (α=0.7, γ=2) вместо BCE — дисбаланс классов ~20%.
- **AdamW + weight decay 1e-2**, OneCycle LR, grad-clip, **early-stopping по val-AUC**.
- StandardScaler по TRAIN-статистике каждого фолда (нет утечки из test).
- **Ансамбль 5 моделей** (по одной на фолд) → усреднение вероятностей на test.

## Результаты (OOS test 2025+, BTC 12h)

| Цель | Purged-CV val-AUC | TEST AUC | prec@0.5 (lift) | prec@0.6 (lift) |
| --- | --- | --- | --- | --- |
| LOW→+5% (LONG) | 0.698 | 0.670 | 0.299 (×1.68) | 0.367 (×2.07) |
| HIGH→-5% (SHORT) | 0.662 | **0.684** | **0.471 (×2.26)** | **0.600 (×2.87)** |

**Sanity-чек (строгий, 3 независимых shuffle-прогона):** mean shuffle-AUC = **0.501 (LOW) / 0.471 (HIGH)** = чистая случайность → **lookahead'а НЕТ**, реальный AUC честный. (Единичное 0.55-0.59 в основном прогоне было шумом короткого фолда.)

## Честный вывод

1. **Нейросеть НЕ превзошла LightGBM** на этих фичах. NN test-AUC 0.67/0.68 ≈ LightGBM 0.64-0.68 ([[good-fractal-5pct-race-predictor-etap174]]). López de Prado был прав: на табличных фин-фичах глубина не даёт преимущества над gradient boosting.
2. **НО нейросеть дала лучший SHORT-режим:** HIGH AUC 0.684 (> GBM 0.66), и **precision@0.6 = 0.60 (×2.87)** — каждый второй-третий уверенный SHORT-сигнал хороший. Это сильнее, чем GBM давал. Правда, сигналов мало (5-87).
3. **Потолок задаёт МЕТКА**, не модель: честная 5%-race (встроенный SL) имеет потолок ~0.67-0.70 AUC. Метка Андрея мягче (движение за N баров без «раньше снятия») → AUC 0.94, но это другая, менее честная задача.

## Стандарты соблюдены — что это даёт

Это первая в проекте полноценная нейросеть, обученная **строго по López de Prado** (Purged K-Fold + uniqueness weights + triple-barrier), с честным shuffle-контролем. Инфраструктура переиспользуема: `train_net`, `purged_kfold_splits`, `uniqueness_weights`, `focal_loss` в [research/elements_study/etap_176_neural_fractal_pavel.py](../../../research/elements_study/etap_176_neural_fractal_pavel.py).

## Дальше (если развивать)

- **LSTM/Transformer на сырых последовательностях баров** (не hand-engineered фичи) — единственный путь, где NN может реально обойти GBM. Риск overfit на 3043 свечах — нужен careful regularization / больше данных (ETH/SOL/мульти-TF).
- Полный стек Андрея с 1m (Vadim maxV sniper ~93%).
- Meta-labeling: NN как вторичная модель.

## Связь

[[good-fractal-5pct-race-predictor-etap174]] (метка + LightGBM-версия), [[adv-fin-ml-индекс]] (стандарты López de Prado), [[neural-networks-nielsen-backprop-reference]], [[traid-bot-ml-pivot]], [[traid-bot-empirical-laws]].
