---
name: feedback-pivot-filter-lookahead-vs-strict
description: Pivot-фильтр lookahead-версия (window от pivot.open) даёт ложно-высокий результат +132R/PF 3.47; strict (window от pivot.close) даёт +89R/PF 2.18 — хуже pure floating
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 436555f5-69d9-4434-ba35-f759547388d5
---

При тестировании фильтра «trade только во время 12h pivot ≥ 2% move» на BTC 6y floating:
- **Lookahead-версия** (window = `[pivot.open, next_opposite.open)`): +132.28R / PF 3.47 / WR 62%
- **Strict-версия** (window = `[pivot.close, next_opposite.close)`): +89.74R / PF 2.18 / WR 49%

Расхождение ~50% от lookahead inflation.

**Why:** Pivot.time (open) известен только через 24h (Williams n=2 confirmation), а «move ≥ 2%» требует знать будущее. Entry в lookahead-окне между pivot.open и его confirmation = доступ к будущим знаниям. В реальном времени эти entries нельзя получить.

**How to apply:**
- При тестировании любого SMC-фильтра на trade-стратегии ВСЕГДА начинать со strict timing
- Williams confirmation lag = 2 × TF_bar (n=2)
- Окно валидно с pivot.close = pivot.open + TF_bar
- Признак баг-теста: total R резко падает между lookahead и strict (>30%)

См. сессию [[2026-06-01-pivot-project-pred12h-c8-force-strict-grid-search]].
