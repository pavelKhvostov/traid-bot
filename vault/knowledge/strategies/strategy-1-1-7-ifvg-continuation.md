---
tags: [strategy, 1-1-7, ifvg, backtest-only]
date: 2026-05-13
status: prototype (not approved, not live)
---

# Strategy 1.1.7 — iFVG Structural Break Continuation

Каскад на основе [[inverse-fvg-definition]] (iFVG-4h). Торгуем В НАПРАВЛЕНИИ iFVG-B (continuation после структурного break).

## Каскад

```
L1: iFVG-event на 4h (FVG-A untouched → iFVG-B formed as A first violation)
L2: retest zone B (1h wick) — implicit через L3 zone overlap
L3: OB-1h в направлении B, zone overlaps B
L4: FVG-15m inside L3 AND inside B
  entry = 0.70 deep FVG
SL: external side of B + 0.5×B_width
allow_multi: 3
```

## Лучшие варианты (BTC 2024-2026, ~28 месяцев)

| Variant | n | closed | WR | Total R | avg R | bad/yrs |
|---------|---|--------|-----|---------|-------|---------|
| V1 RR=2.0 baseline | 117 | 96 | 38.5% | +15R | +0.16 | 0/3 |
| V2 RR=1.5 (higher WR) | 117 | 91 | **49.5%** | +21.5R | +0.24 | 0/3 |
| **V2c RR=2.5** | 117 | **99** | 39.4% | **+37.5R** | **+0.38** | **0/3** ⭐ |
| **V2c + C5 age>=5** | 87 | 72 | 41.7% | +33R | **+0.46** | 0/3 ⭐⭐ |

**RR=2.5 побеждает** потому что iFVG-continuation captures large structural moves. WR ~39% × 2.5R = +0.38 avg.

## Direction = B.direction (continuation)

Критически: НЕ fade iFVG. **Concept C1 (failed iFVG fade) показал WR 38%, +11R only** — концепт не работает. iFVG = надёжная continuation.

## Что НЕ работает

- C1 Failed iFVG (fade B) → +11R, WR 38% — не торговать против
- C4 regime detector (iFVG count) — слишком редкие на 4h
- C6 maxV-1d confluence — marginal (+10R, n=25)
- Hull-4h aligned filter — режет WR до 29% (другая природа сетапа vs 1.1.4)

## Что работает (в дополнение к baseline)

- **C5 age filter (FVG-A untouched ≥ 5 bars)**: +0.46 avg R vs +0.38 baseline
- **C7 breakout entry without retest**: +35R RR=2.0, WR 42.7%, n=124 closed
  - Альтернативная архитектура (без L2/L3/L4) — кандидат на 1.1.8

## Сравнение с уже утверждёнными

| | n | WR | Total R | avg | bad/yrs |
|---|---|----|---------|-----|---------|
| 1.1.4 BFJK (6.3y) | 115 | 64.3% | +107R | +0.93 | 1/7 |
| 1.1.5 hi-freq (6.3y) | 242 | 47.9% | +106R | +0.44 | 0/7 |
| 1.1.7 V2c (2.3y) | 99 | 39.4% | +37.5R | +0.38 | 0/3 |
| 1.1.7 V2c + C5 (2.3y) | 72 | 41.7% | +33R | +0.46 | 0/3 |

Middle-tier strategy. **0 bad years** — лучший stability metric.

## Файлы

- Detector: [research/elements_study/etap_95_strategy_117_ifvg.py](../../../../research/elements_study/etap_95_strategy_117_ifvg.py)
- Tuning: [etap_96_strategy_117_tuning.py](../../../../research/elements_study/etap_96_strategy_117_tuning.py)
- Concepts: [etap_97_ifvg_concepts_all.py](../../../../research/elements_study/etap_97_ifvg_concepts_all.py)

## Статус

**Backtest-only**, NOT approved, NOT live. Pending решения пользователя по утверждению.

## Связи

- [[inverse-fvg-definition]] — концепция iFVG
- [[ifvg-7-concepts-tested]] — 7 альтернативных концепций
- [[2026-05-13-live-bot-vic-ifvg-strategies-117-118]] — session note
