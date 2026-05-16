---
tags: [decision, floating-tp, momentum, edge]
date: 2026-05-15
---

# Floating TP помогает только стратегиям с низким baseline WR

## Эмпирический закон

Score-based dynamic exit (floating TP) **улучшает** PnL только если
baseline WR стратегии ниже ~50%. Для стратегий с baseline WR ≥ 60%
floating exit **режет edge** потому что закрывает trades которые
статистически доходят до fixed TP.

## Доказательства (BTC 6.3y)

| Strategy | Baseline WR | Baseline PnL | Floating PnL | Δ |
|---|---:|---:|---:|---:|
| 1.1.1 SWEPT | 45.4% | +165R | **+247R** | +82R (+50%) |
| 1.1.2 macro-OB | 41.8% | +726R | **+1016R** | +290R (+40%) |
| **1.1.4 BFJK** | **64.3%** | **+107R** | **+35R** | **−72R (−67%)** ✗ |

См. результаты в [[strategy-1-1-1-floating-tp-final]], [[strategy-1-1-2-floating-tp-final]], [[strategy-1-1-4-floating-tp-not-applicable]].

## Объяснение механизма

### Низкий baseline WR (45%)

- Многие trades едва доходят до +2R и разворачиваются (становятся losses при fixed TP)
- Momentum score ловит момент разворота → захватывает MFE на пути к +2R
- Конвертирует часть «would-have-been-losses» в +1.5R, +2R, +3R wins
- **WR растёт +6-10pp, PnL +30-50%**

### Высокий baseline WR (64%)

- Trades **чисто** доходят до +2R и срабатывают fixed TP
- Drawdown во время roiding — НОРМАЛЬНАЯ часть пути к TP
- Score-exit закрывает позицию на drawdown «защитно» → пропускает +2R
- **WR падает с 64% до 47-54%, PnL минус 50-70%**

## Правило применения

```
IF baseline_WR < 50%:
    APPLY floating TP (4-indicator momentum score + R_cap)
    EXPECT +30-50% PnL boost

IF baseline_WR >= 60%:
    KEEP fixed RR
    DO NOT apply floating exit

IF 50% <= baseline_WR < 60%:
    TEST both, decide on per-strategy basis
```

## Какие стратегии куда попадают (по состоянию на 2026-05-15)

**Low WR (apply floating):**
- 1.1.1 SWEPT: 45% → use floating ✓
- 1.1.2 macro-OB: 42% → use floating ✓
- 1.1.5 fractal: 48% (TBD test)
- 1.1.7 iFVG: 39% (V2c)

**High WR (keep fixed):**
- 1.1.4 BFJK: 64% → keep RR=2.0 ✓
- C2 (OB-6h+FVG-2h): 55% — borderline, fixed RR=1 пока

## Альтернатива для high-WR strategies — TP extension

Для 1.1.4 нашли вариант G2 = «при touch +2R, если score > +0.5, расширить до cap=4R»:
- PnL чуть ниже (+94R vs baseline +107R)
- НО bad years 1/7 → 0/7 (улучшение robustness)
- WR 64% сохранена

Это не «floating exit», это «conditional TP extension». Работает для high-WR
если хочется захватывать редкие большие движения, не разрушая baseline.

## Связи

- [[4-indicator-momentum-score]]
- [[strategy-1-1-1-floating-tp-final]]
- [[strategy-1-1-2-floating-tp-final]]
- [[strategy-1-1-4-floating-tp-not-applicable]]
- [[2026-05-15-floating-tp-multi-symbol-c2-trendfilter]]
