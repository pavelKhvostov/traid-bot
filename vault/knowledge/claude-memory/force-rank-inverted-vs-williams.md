---
name: force-rank-inverted-vs-williams
description: "Strong force imbalance НЕ улучшает P(Williams), наоборот; calm/low |imbalance| Q2 даёт peak lift 1.25×. Grid search 2026-06-03 на 1272 baseline pivots"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 436555f5-69d9-4434-ba35-f759547388d5
---

# Force rank vs Williams P(W) — inverted relationship

**Правило:** strong force (top 5% rank в 60d окне) → P(W) = 37.8% (lift 0.78×); calm zones (|imbalance| Q2 ≈ 327) → P(W) = 61.0% (lift 1.25×).

**Why:** Сильная directional imbalance = trend continuation expected (buyers/sellers поддерживают цену в направлении) = НЕТ pivot reversal. Calm/balanced zones = bar свободно может развернуться → Williams формируется чаще.

**How to apply:**
- НЕ использовать «strong force» как gate для Williams precision (lift < 1)
- Использовать **calm filter** (|imbalance| ≤ ~600, Q1+Q2) как potential C9 condition (lift 1.21× на baseline 48.7%)
- Strong force полезен для **trend continuation signals**, не для **pivot timing**
- 4 потеряшки (#14, #15, #48, 10-05) — outliers (strong force + confirmed), НЕ representative cluster

**Grid search results (1272 baseline pivots, 6y):**
```
|imbalance| quintile  mean   n    P(W)    lift
Q1 low                89    255   57.3%   1.18×
Q2                    327   254   61.0%   1.25×  ← peak
Q3                    730   254   50.4%   1.04×
Q4                   1383   254   36.6%   0.75×
Q5 high              3012   255   38.0%   0.78×
```

Связано с [[empirical-tf-weight-rejected]], [[pred12h-fractal-three-candles]], [[bb-model-phase4-negative-result]].
