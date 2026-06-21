---
name: feedback-phase4-zone-precompute-must-chunk
description: precompute_zone_events + snapshot_from_events на 6y BTC даёт O(N²) slowdown в snapshot loop; обязательно чанковать по 1y с 180d warmup (22.9 мин vs 5+ часов)
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 436555f5-69d9-4434-ba35-f759547388d5
---

При батч-вычислении Phase 4 force snapshots на 1272 пивотах 6y BTC:

**Без чанкования (NAIVE)**:
- One-shot precompute на 6y: 7.7 мин
- Snapshot loop: catastrophic slowdown — первые 200 пивотов 0.48 сек/каждый, следующие 200 = 13 сек/каждый (×27)
- Total ETA: 5+ часов (так и не дождался, прервал)

**С чанкованием по 1y + 180d warmup** (`pred12h_C8_force_batch_chunked.py`):
- 6 chunks × (50s precompute + ~3 мин snapshot)
- Stable ~0.5-1.3 сек/pivot, без slowdown
- Total: **22.9 мин**

**Why:** `snapshot_from_events` делает sequential scan по растущему events-списку. На 6y events = 100k+, каждый snapshot ~O(N). Чанкование держит N в пределах ~25k events на каждом шаге.

**How to apply:**
- Для любого batch-теста Phase 4 / zones на ≥2 года: ОБЯЗАТЕЛЬНО чанковать
- Размер чанка: 365 дней (баланс precompute overhead vs snapshot size)
- Warmup: 180 дней (для age_factor зон с долгой жизнью)
- Шаблон: `~/smc-lib/scripts/pred12h_C8_force_batch_chunked.py`

См. [[2026-06-01-pivot-project-pred12h-c8-force-strict-grid-search]].
