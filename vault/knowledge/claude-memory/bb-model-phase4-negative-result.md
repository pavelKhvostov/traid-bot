---
name: bb-model-phase4-negative-result
description: "Phase 4 bb-classifier на strict labels (honest, no lookahead) — AUC mean 0.510, 7/12 фолдов хуже random. Tabular ML на ob_vc(1h+2h)+etap108 потолок ~0.55 AUC. Strict baseline 6y BTC +301R (Phase 2 lookahead был +1076R = overstate 72%)."
metadata: 
  node_type: memory
  type: project
  originSessionId: 5dfe8bf0-bba6-41f4-89b4-4c25014664a4
---

## Что произошло

Phase 4 PC1 запуск (2026-05-31 ночь→утро): force/liquidity/anchor framework, 102 features, label = trade_outcome win/loss с STRICT fill_start (без lookahead). Runtime 117.9 мин.

**Результат: AUC mean 0.510 — практически random.** Хуже чем Phase 3 (0.540) и Phase 2 (0.537).

## Phase 2/3/4 сравнение

| | Phase 2 | Phase 3 | Phase 4 |
|---|---|---|---|
| AUC mean | 0.537 | 0.540 | **0.510** |
| AUC median | 0.534 | 0.542 | **0.494** |
| Folds AUC < 0.5 | 4/12 | 4/12 | **7/12** |
| Best WR after filter | 41.1% | 41.5% | 31.5% |
| Best RR | 2.27 | 2.59 | 2.34 |
| Labels | lookahead-tainted | lookahead-tainted | **strict honest** |

## Strict lookahead fix причина «ухудшения»

Phase 4 хуже потому что labels стали честными:
- Phase 2/3 fill_start = signal+15m → **lookahead 30мин-2ч** на трейд
- Phase 4 fill_start = max(cur_HTF.close, c3.close, fractal_n2_confirm.close) → strict
- Strict labels драматически меняют win/loss распределение

**Strict 6y backtest** (без любой ML модели):
- n_closed=3144, WR=30.0%, **total_R=+301R, R/tr=+0.10**
- Phase 2 lookahead-claim был +1076R / +0.36 → **overstate 72%**
- 2025 был **первый убыточный год (-38R)** в strict
- Best subset: LONG htf=2h +102R / R/tr +0.14

## Главный вывод

**Tabular bb-classifier на эту задачу не превзойдёт ~AUC 0.55** при честных labels. 3 итерации (Phase 2, 3, 4) дают около той же планки.

Причины:
1. Honest dataset гораздо сложнее lookahead-версии
2. Class imbalance 30/70 (только 30% wins на strict)
3. Phase 4 test fold = 2025 = единственный bad year
4. Возможно zone-context features недостаточны — нужны temporal/sequence patterns

MH directional модель (PC2 screening) даёт **dir_acc 0.553** — лучше чем Phase 4 (0.510). Sequence/temporal сильнее tabular zone-context.

## How to apply

- НЕ ожидать что добавление новых tabular фичей пробьёт 0.55 AUC на ob_vc(1h+2h)+etap108
- Phase 5 (macro ob_vc HTF) может дать +0.03 AUC, но не до 0.65
- Для прорыва нужен **архитектурный сдвиг**: DL sequence (LSTM/Transformer) ИЛИ другой strategy framework ИЛИ принять реальный baseline ~50R/год

## Связи

- [[2026-05-31-phase3-results-phase4-force-framework]] — полная сессия
- [[feedback-ob-vc-strict-detection-timing]] — strict canon
- [[mh-screening-best-config-not-lazybear]] — MH screening результаты parallel
