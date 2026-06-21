---
name: feedback-p4zr-entry-fill-lookahead
description: "P4ZR v2 backtest (+260R / WR 85% / PF 18.4) inflated за счёт entry-fill lookahead — simulate_trade ASSUMES позиция filled at zone-edge entry_px, не проверяет touch"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 436555f5-69d9-4434-ba35-f759547388d5
---

P4ZR (Phase 4 Zone Reversion) backtest v2 показал на BTC 6y:
- WR 85%, PF 18.36, Total R +260R, freq 1.48/мес

**Subtle lookahead bias**: `simulate_trade` walks 1m forward от close 12h-бара и проверяет SL/TP относительно `entry_px = z.hi` (или z.lo для SHORT). Но НЕ проверяет, что цена реально вернулась к entry_px чтобы limit-ордер filled.

**Сценарий bias**:
- Setup at i.close: entry_px = 74938 (z.hi LONG), cur price 75500
- Цена идёт сразу к TP=78000 без отката к 74938
- Simulator: high >= tp → +R win
- Real: limit not filled → NO TRADE

**Эффект на метрики** (estimate):
- WR 85% → 70-75% (real)
- PF 18.4 → 5-8 (real)
- Total R +260R → +150-200R (real)

**How to apply**:
- Любой backtest со structural entry на zone edge ДОЛЖЕН включать fill simulation
- Pattern: `for i in window: if direction=='LONG' and lo[i]<=entry_px and hi[i]>=entry_px: fill_idx=i; break; else: return None`
- Если fill_idx is None → no trade (limit never touched)
- Затем SL/TP simulation начинается от fill_idx, не от signal_time

Скрипт `~/smc-lib/scripts/p4zr_backtest.py` имеет этот bias. Fix не запущен из-за ETA 85 мин.

См. [[2026-06-02-pivot-mec-p4zr-multi-expert-deep-dive]].
