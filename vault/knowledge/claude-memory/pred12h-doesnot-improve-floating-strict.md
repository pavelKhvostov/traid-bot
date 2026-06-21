---
name: pred12h-doesnot-improve-floating-strict
description: STRICT 6y test показал — pred12h F1∩F2∩F3+C1-C7+C8(force) не улучшает Strategy 1.1.1 floating; pure floating +196R/PF 2.20 vs best filter +90R/PF 2.18
metadata: 
  node_type: memory
  type: project
  originSessionId: 436555f5-69d9-4434-ba35-f759547388d5
---

**Strict lookahead-safe backtest на BTC 6y (2026-06-01):**

| Конфигурация | Total R | PF | WR | freq/мес |
|---|---:|---:|---:|---:|
| Pure floating (без фильтра) | **+195.87R** | **2.204** | 51.3% | 5.17 |
| pred12h basket C1-C7 strict | +70.07R | 1.951 | 47.6% | 1.98 |
| basket ∪ best C8 (Phase 4 force) | +89.74R | 2.179 | 48.7% | 2.13 |

Best C8 params: `abs_net=1000, d3=200, wins_fh=0, wins_fl=6, bias=NOBAL` (но даже они хуже pure).

**Why:** Pred12h оптимизирован под Williams confirmation precision (P=66.8%), а не под maximize-floating-PF. Pred12h pivot windows и floating SWEPT cascade entries — это **разные процессы**, не выровненные по timing/setup. Floating уже сам себе оптимальный selector.

**How to apply:**
- Не использовать pred12h как finger для Strategy 1.1.1 floating
- Pred12h полезен как **standalone predictive layer** (предсказание Williams), но требует своей trade-стратегии с custom entry/SL/TP
- Pure floating BTC = текущий максимум доступного на этой связке
- Target 8-12 trades/мес для 1.1.1 на BTC **недостижим** (max в strict ~5/мес)

Артефакты в `~/Desktop/`: `pred12h_C8_force_6y.parquet`, `floating_btc_6y_trades.parquet`, `pred12h_C8_grid_strict_results.parquet`.

См. [[2026-06-01-pivot-project-pred12h-c8-force-strict-grid-search]].
