---
name: feedback-rsi-cumulative-fresh-exit-edge
description: RSI cumulative bars_since_*_exit q1 (0-7 bars) даёт standalone P(W) 60-62% на baseline 49% — единственная structural feature с чистым edge без ML
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 436555f5-69d9-4434-ba35-f759547388d5
---

Прямой rule-test cumulative MH v2 features на 1272 baseline pivots BTC 6y:

| Feature | q1 range | P(W) | vs baseline |
|---|---|---:|---|
| `bars_since_rsi_os_exit_2h` | 0-7 bars | **62.4%** (FL=64.6%) | +13pp |
| `bars_since_rsi_ob_exit_1h` | 0-6 bars | **60.8%** | +12pp |

**Семантика**: «свежий выход RSI из oversold (для LONG) или overbought (для SHORT)». Bars_since считается на 15m grid. q1 = недавний exit.

Все остальные тестированные cumulative features (`bars_since_mf_zero_*`, `bars_since_bw2_*`, `cascade_*`) показали flat P(W) около 46-53% — **только RSI имеет clean edge standalone**.

**Применение в P4ZR v3** (post-filter v2 trades):
- LONG: bars_since_rsi_os_exit_2h ≤ 7 → WR 100% (16 trades)
- SHORT: bars_since_rsi_ob_exit_1h ≤ 7 → WR 93.8% (16 trades), R/tr +5.44
- Combined sweet spot: ≤15/≤15 → 53 trades, WR 92.5%, PF 42.6, +166R

**How to apply**:
- В любой reversal-стратегии добавлять RSI fresh-exit как entry filter
- LONG: ждать `bars_since_rsi_os_exit_2h ≤ 7-15`
- SHORT: ждать `bars_since_rsi_ob_exit_1h ≤ 7-15`
- Это identifies «mean reversion момент после устранения extreme»
- Pure floating + этот filter не тестирован — возможно clean improvement

Скрипт: `~/smc-lib/scripts/mh_cumulative_rule_test.py`

См. [[2026-06-02-pivot-mec-p4zr-multi-expert-deep-dive]].
