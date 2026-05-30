---
tags: [session, smc-lib, vc, volume-confirmation, fractal, 12h, f5, predicate, ob, fvg]
date: 2026-05-26
duration: средняя сессия
status: complete
related: [[smc-lib-as-canonical-source]], [[12h-fractal-prediction-final-strategy]], [[2026-05-19-rdrb-v2-babai-fractal-prediction]], [[2026-05-24-smc-lib-canon-vwap-asvk-introduction]]
---

# 2026-05-26 — VC канонизирована как концепция (не зона) + F5 поиск по фракталам

Сессия началась с продолжения 12h fractal filter работы (F4 v3 per-element mitigation), перешла в поиск F5 кандидата (цель: keep ≤ 560, P(Williams) ≥ 70%), и завершилась канонизацией **VC (Volume Confirmation)** как обобщённой концепции подтверждения в `~/smc-lib/elements/vc/`.

## I. F4 v3 финал — per-element mitigation canon

Завершили rewrite `~/smc-lib/scripts/pred12h_F4_v3_full_canon.py` со всеми правильными mitigation моделями (три класса):

- **Wick-fill** (постепенное сжатие): OB, block_orders, FVG, i-FVG, RDRB POI, i-RDRB POI
- **First-touch** (одноразовое consumption): RB, ob_liq
- **Sweep level** (точечный): fractal, marubozu (open level)

**Результаты на 6y BTC:**

| Стэк | keep | P(Williams) | imp |
|---|---:|---:|---:|
| Pre-Williams baseline | 2891 | 41.7% | 18/18 |
| F1 left_ext_5 | 1889 | 42.9% | 18/18 |
| F1 ∩ F2 | 1408 | 45.2% | 18/18 |
| **F1 ∩ F2 ∩ F3** | **1266** | **48.9%** | **18/18** |
| **F4 v3 (per-element)** | **1105** | **49.6%** | **16/16** |

F4 теряет **#4 (2026-02-12 15:00 FL 65118)** и **#9 (2026-02-24 15:00 FL 62510)** — оба fresh-extreme FL без активной HTF support-зоны. Семантически корректные потери: pivot **создаёт** новую зону, а не реагирует на старую.

## II. F5 search — поиск ≤560 keep & ≥70% P

Пользователь: «можем потерять ещё 16→14 imp, но нужен win 70%+, keep сократить в 2 раза».

### Тестировались семейства

1. **HTF confluence** (max_tf, tf_count, kind class) — потолок ~55%, recall сильно падает
2. **Pivot internals** (range/ATR, wick/body ratio) — потолок ~62%, recall катастрофически падает
3. **FVG inside pivot** (1h, 2h, 3h, 4h, 6h)
4. **i-FVG inside pivot** (15m, 20m, 30m)
5. **8 classic reversal candle patterns** на 5m/15m/30m/1h (Engulfing, Pin/Hammer/ShStar, Morn/Even Star, 3 Crows/Soldiers, Tweezer, Marubozu, Williams sweep, i-RDRB)
6. **VC inside pivot** (canon: OB-1h/2h × FVG-15m/20m)

### Ключевой принцип direction-asymmetry

Подтверждается на **всех** методах: внутри pivot 12h-свечи **direction LTF FVG ↔ Williams precision**:

| Type LTF FVG | Семантика | Δ Williams precision |
|---|---|---:|
| **Aligned** (направление импульса pivot) | импульс продолжается → pivot пробьётся | **−6 … −12pp** |
| **Counter** (направление reversal) | разворот уже начат внутри pivot | **+13 … +35pp** |
| **Any** (либо) | нейтрально | ~0 |

То же — для i-FVG, для VC (aligned VC = −2.7pp). **Фундаментальный закон**.

### Сводка F5 кандидатов

| Кандидат | keep | P(conf) | Δ | imp | Профиль |
|---|---:|---:|---:|---:|---|
| baseline F4 v3 | 1105 | 49.6% | — | 16/16 | base |
| **counter FVG ≥1h** | **572** | **63.1%** | +13.5 | 9/16 | ⭐ precision-leader |
| counter FVG ≥2h | 272 | 70.6% | +21.0 | 2/16 | цель P достигнута, recall убит |
| counter FVG ≥4h | 60 | 85.0% | +35.4 | 0/16 | precision-monster |
| counter i-FVG any (15/20/30m) | 365 | 54.8% | +5.2 | 2/16 | хуже counter FVG |
| Engulfing 60m | 741 | 52.8% | +3.2 | 13/16 | сопоставим с VC |
| 3 Crows 60m | 359 | 57.7% | +8.1 | 4/16 | |
| Marubozu 60m | 148 | 60.1% | +10.5 | 3/16 | |
| **COUNTER VC any (OB 1/2h × FVG 15/20m)** | **894** | **52.9%** | +3.3 | **13/16** | ⭐ recall-leader |
| COUNTER VC OB=2h × FVG=20m | 459 | 55.8% | +6.2 | 9/16 | balanced |
| ALIGNED VC ⚠ | 938 | 46.9% | −2.7 | 11/16 | контрольная: подтверждает direction |

### Выводы по F5

1. Барьер **70% P(Williams)** достигается только при **полной потере imp** (counter FVG ≥2h: 2/16).
2. **Counter FVG ≥1h** — лучший precision-trade-off: 572 keep, 63.1%, 9/16 imp.
3. **Counter VC** — лучший recall-trade-off среди F5: 894 keep, 52.9%, 13/16 imp.
4. Classic Western свечные паттерны (Engulfing/Pin/Star/...) **проигрывают** SMC-based фильтрам по всем метрикам.
5. **Aligned-LTF-displacement** — anti-signal на всех уровнях. Семантически: продолжение тренда, не разворот.

### Open question (для следующей сессии)

- Совместить counter FVG ≥1h **OR** counter VC через rescue: ожидаемо recall ~14+/16, precision ~58%
- Расширить VC за OB на block_orders / RDRB POI / ob_liq (концепция обобщённая, канон фиксирует только OB-кейс)
- VC на pivot level — проверка что VC.ob.zone содержит pivot.level (F4-like contiguity)
- Сменить метрику с P(Williams) на P(trading win @ ATR target) — возможно реальный edge выше

## III. VC канонизирована в smc-lib

Поиск термина «VC» в Obsidian vault нашёл определение в [[2026-05-19-rdrb-v2-babai-fractal-prediction]]:

> **VC** = volume confirmation = FVG-15m/20m внутри OB-1h/2h того же направления (геометрия, объём не участвует).

### Финальная семантика (после уточнения пользователя)

> **VC НЕ зона интереса.** Это **обобщённая концепция подтверждения** — **предикат над HTF-зоной**.

Принцип:
```
VC(HTF_zone, LTF_TF) := ∃ FVG на LTF_TF, такой что
                         FVG.direction == HTF_zone.direction
                         AND FVG.zone ⊆ HTF_zone.zone
```

То есть HTF-зона считается **подтверждённой** если внутри неё лежит LTF FVG того же направления — это означает «через зону прошёл impulse-displacement».

### Канонический случай

| HTF (OB) | LTF (FVG) |
|---|---|
| 1h | 15m |
| 1h | 20m |
| 2h | 15m |
| 2h | 20m |

### Обобщение

Концепция применима к любой HTF-зоне (OB, block_orders, RDRB POI, ob_liq, ...). В каноне зафиксирован **только OB-кейс**; расширения — feature пользовательских стратегий.

### Что VC НЕ является

- ❌ Не зоной интереса (не имеет своей зоны)
- ❌ Не volume-индикатором (название vestigial; объём не используется)
- ❌ Не конкретным паттерном (это **семейство** проверок)
- ❌ Не подвержено mitigation (mitigated — HTF-зона, не VC)

### Артефакты в smc-lib

- `~/smc-lib/elements/vc/definition.md` — полная спецификация концепции
- `~/smc-lib/elements/vc/code.py`:
  - `has_vc(ob, fvg) → bool` — точечный предикат
  - `find_vc_confirmations(ob, ltf_fvgs) → list[FVG]` — поиск подтверждающих FVG
- `~/smc-lib/elements/vc/tests/test_vc.py` — 7 тестов (LONG/SHORT reference, mismatch, outside, partial, edge zero-margin, find-filter)
- `~/smc-lib/zone_of_interest.md` — добавлена краткая ссылка «VC не является зоной»

### Тесты

**113 passed** (полная регрессия, +7 новых VC).

### Эволюция определения в сессии

1. Изначально VC задизайнен как «композит-зона» с `VC.zone = FVG.zone` (по аналогии с другими элементами)
2. Пользователь скорректировал: «VC — это не зона интереса, а обобщённое понятие подтверждения объёма»
3. Переработали: VC = predicate, без своей зоны; код — boolean-функции

## IV. Memory обновлена

- `memory/vc-volume-confirmation-definition.md` — VC как concept/predicate, не зона
- Индекс `MEMORY.md` обновлён

## Артефакты сессии

### smc-lib
- `elements/vc/definition.md`, `code.py`, `tests/test_vc.py` (новый элемент)
- `zone_of_interest.md` (обновлён: VC помечен «не зона»)

### scripts
- `scripts/pred12h_F4_v3_full_canon.py` — F4 v3 с per-element mitigation
- `scripts/pred12h_F5_search.py` — F5 batch search (HTF confluence, ATR, wick/body)
- `scripts/pred12h_F5_fvg_in_pivot.py` — counter/aligned FVG ≥1h…6h
- `scripts/pred12h_F5_ifvg_in_pivot.py` — i-FVG 15/20/30m
- `scripts/pred12h_F5_patterns_batch.py` — 8 classic reversal patterns × 4 TFs
- `scripts/pred12h_F5_vc_in_pivot.py` — VC inside pivot (OB-1h/2h × FVG-15m/20m)

### Memory (Claude auto-memory)
- `vc-volume-confirmation-definition.md` (новый)
- `MEMORY.md` (обновлён индекс)

## Открытые задачи

1. Принять production-кандидат F5 — варианты:
   - A) counter FVG ≥1h: 572/63.1%/9 imp (precision)
   - B) counter VC any: 894/52.9%/13 imp (recall)
   - C) OR-composite (A∪B): ожидание ~14/16 imp, 58% P
2. Тест обобщения VC: VC от block_orders / RDRB POI / ob_liq как HTF-контейнеры
3. F4 rescue для #4, #9 (fresh extremes без HTF support) — потенциально вернуть recall 18/18
4. Сменить метрику оценки: с P(Williams confirm) на P(trading win @ ATR target)

## Источники

- Vault: [[2026-05-19-rdrb-v2-babai-fractal-prediction]] (исходное определение VC)
- Canon: `~/smc-lib/elements/vc/definition.md` (новый, 2026-05-26)
- Predecessor: [[2026-05-24-smc-lib-canon-vwap-asvk-introduction]] (smc-lib expansion 3→8 elements)
