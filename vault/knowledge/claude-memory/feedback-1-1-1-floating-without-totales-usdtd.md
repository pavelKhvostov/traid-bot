---
name: feedback-1-1-1-floating-without-totales-usdtd
description: "Pure floating BTC 6y benchmark (+195.87R / WR 51% / PF 2.20) НЕ включает TOTALES + USDT.D macro confluence; это «stripped» 1.1.1, не full canon"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 436555f5-69d9-4434-ba35-f759547388d5
---

В сессии 2026-06-02 обнаружено: все мои floating-тесты на 6y BTC (etap_104_floating_variants.py reference) **НЕ используют TOTALES/USDT.D confluence**.

**Что в etap108 reference**:
- 1.1.1 SWEPT cascade detector ✓
- OB+FVG zones ✓
- Floating TP (R_cap=4.5, score_exit) ✓
- 4-indicator score (Hull/Money Hands/RSI/ASVK) ✓
- Per-symbol configs ✓
- **TOTALES confluence** ✗
- **USDT.D confluence** ✗

**Где живёт confluence**:
- `~/traid-bot/research/rdrb/analyze/analyze_rdrb_confluence_macro.py` — анализатор (группирует existing trades)
- Strategy 1.1.1 v1 production code (`~/traid-bot/strategies/strategy_1_1_1.py`) — confluence reference отсутствует
- v2 design doc (`strategy-1-1-1-v2.md`): помечен «опционально — ml-feature, не hard filter»

**Canonical rule** (из старого analyze):
```
TOTALES daily direction = same as BTC trade direction (за N closed days)
USDT.D daily direction = OPPOSITE BTC direction (mirror)
Triple confluence = оба совпали
Any sync = любой из двух
```

**Lookahead warning** (из `confluence-lookahead-and-rr22-bugs.md`):
- Старая реализация использовала close сегодняшней (незакрытой) свечи
- WR Triple был inflated на ~10pp
- Strict version: только closed candles, lookahead 0

**Data availability**:
- TOTALES 15m/1h/4h/1d в `~/traid-bot/data/` ✓
- USDT_D локально отсутствует, нужно fetch ✗

**How to apply**:
- При repor1.1.1 production benchmark **уточнять**: «pure floating, без macro confluence»
- Full canon =floating + Triple confluence (strict, closed candles only)
- Гипотеза: +3-5pp WR от Triple sync (но frequency −30-50%)
- **Не запущено** в сессии 2026-06-02 — отложено

См. [[2026-06-02-pivot-mec-p4zr-multi-expert-deep-dive]].
