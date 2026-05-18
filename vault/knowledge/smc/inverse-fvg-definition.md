---
tags: [smc, fvg, ifvg, definition]
date: 2026-05-13
---

# Inverse FVG (iFVG) — определение и детектор

## Определение

**iFVG = FVG противоположного направления, чьи свечи ПЕРВЫМИ перекрывают зону ранее untouched FVG.**

```
FVG-A (например bull) сформирована и НЕ затронута за N баров
  ↓
Через N баров цена возвращается
  ↓
FVG-B (bear, противоположная) формируется — её c0/c1/c2 ПЕРВЫЕ касаются зоны A
  ↓
B = inverse FVG для A
  ↓
Зона A инвертирована: была support, стала resistance
```

## Алгоритм детекции

```python
fvgs = detect_all_fvgs_chronologically(df)
for A in fvgs:
    # touch_idx = первая свеча после A.c2, чей фитиль вошёл в зону A
    touch_idx = find_first_touch(df, A)
    if touch_idx is None: continue

    # Найти FVG-B противоположного направления, чьи 3 свечи захватывают touch_idx
    for B in fvgs:
        if B.direction != A.direction \
           and B.c0_idx <= touch_idx <= B.c2_idx \
           and B.c0_idx > A.c2_idx \
           and zones_overlap(A, B):
            yield (A, B, touch_idx)  # iFVG event
            break
```

См. [research/elements_study/etap_93_inverse_fvg.py](../../../../research/elements_study/etap_93_inverse_fvg.py).

## SMC интерпретация

- До iFVG: зона A валидная support (bull-FVG) / resistance (bear-FVG)
- При iFVG: первое касание = разворот структуры
- После iFVG: зона A инвертирована (support → resistance или наоборот)

Это **подтверждённый Break of Structure** через volume imbalance, не просто пробой границы.

## Статистика на BTC 1h за 48 дней

- 233 всего FVG (124 bull, 109 bear — почти баланс)
- 31 iFVG event (13.3% от всех FVG)
- Median delay A.c2 → touch: **3 бара**, mean 20, max 307
- 15 bull→bear iFVG, 16 bear→bull iFVG (balanced)

## Какие торговые стратегии можно построить

См. [[ifvg-7-concepts-tested]] — протестировано 7 концепций.

**Работает**:
- iFVG-continuation cascade (см. [[strategy-1-1-7-ifvg-continuation]])
- iFVG breakout entry без retest (кандидат на 1.1.8)
- iFVG-against как POSITIVE filter для 1.1.4 (n=16 surprise)

**НЕ работает**:
- Failed iFVG fade (двойная инверсия) — iFVG это надёжная continuation
- iFVG count regime detector (на 4h редкие события)

## Связи

- [[strategy-1-1-7-ifvg-continuation]] — основная стратегия на iFVG
- [[ifvg-7-concepts-tested]] — концепции
- [[универсальные определения OB и FVG]] — canon FVG
- [[2026-05-13-live-bot-vic-ifvg-strategies-117-118]] — session note
