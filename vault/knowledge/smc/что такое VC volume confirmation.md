---
tags: [smc, vc, volume-confirmation, predicate, ob, fvg, canon]
date: 2026-05-26
status: canon
related: [[универсальные определения OB и FVG]], [[что такое order block]], [[что такое fvg]], [[три класса зон ликвидность эффективность неэффективность]], [[2026-05-19-rdrb-v2-babai-fractal-prediction]], [[2026-05-26-vc-concept-canon-in-smc-lib-and-f5-search]]
---

# VC (Volume Confirmation) — концепция подтверждения

**VC — обобщённая концепция подтверждения объёма.** Это **предикат над HTF-зоной**, не зона интереса.

> ⚠️ **VC НЕ является зоной интереса.** HTF-зона остаётся за HTF-элементом (OB, block_orders, RDRB POI и т.д.). VC только **сигнализирует** что зона подтверждена через LTF impulse-displacement.

> ⚠️ Название «Volume Confirmation» — **vestigial**. Расчёт чисто геометрический, объём не используется. Идея в том, что HTF-зона, через которую прошёл impulse (LTF FVG), считается «насыщенной объёмом» **по геометрии displacement'а**, а не по volume-индикатору.

## Принцип

VC = OB подтверждена displacement'ом (FVG того же направления). Две формы:

### Spatial (containment)

```
VC_spatial(OB, FVG) := OB.dir == FVG.dir AND FVG.zone ⊆ OB.zone
```

LTF FVG лежит **внутри** HTF OB.

### Temporal (sequential)

```
VC_temporal(OB, FVG) := OB.dir == FVG.dir AND OB.tf == FVG.tf AND FVG.c1 = OB.cur+1
```

FVG формируется **сразу после** OB на **том же TF**. Containment НЕ требуется — FVG обычно ВНЕ OB.zone (above для LONG / below для SHORT), т.к. impulse выводит цену из зоны.

## Три канонических варианта (зафиксированы 2026-05-26)

| Variant | Класс | OB TF | FVG TF | Геометрия |
|---|---|---|---|---|
| **V1** | spatial | 1h, 2h | 15m, 20m | FVG ⊆ OB.zone |
| **V2** | spatial | 4h, 6h | 1h, 90m, 2h | FVG ⊆ OB.zone |
| **V3** | temporal | 1h, 2h | **same TF** (1h, 2h) | FVG.c1 = OB.cur+1, **NO containment** |

**Direction:** во всех вариантах — `OB.dir == FVG.dir` (aligned).

### V1, V2 пары TF (containment)

| HTF (OB) | LTF (FVG) | Variant |
|---|---|---|
| 1h | 15m | V1 |
| 1h | 20m | V1 |
| 2h | 15m | V1 |
| 2h | 20m | V1 |
| 4h | 1h | V2 |
| 4h | 90m | V2 |
| 4h | 2h | V2 |
| 6h | 1h | V2 |
| 6h | 90m | V2 |
| 6h | 2h | V2 |

### V3 пары TF (temporal)

| OB TF | FVG TF |
|---|---|
| 1h | 1h |
| 2h | 2h |

### Семантика V3

OB сформирована → следующая свеча запускает impulse → displacement → gap (FVG). OB сработала как launchpad. FVG обычно выше (LONG) / ниже (SHORT) OB.zone, т.к. цена выкинута из зоны.

История: V1 зафиксирован 2026-05-19 ([[2026-05-19-rdrb-v2-babai-fractal-prediction]]). V2, V3 добавлены 2026-05-26 пользователем. См. [[2026-05-26-vc-3-variants-rules-md-fractal-or-basket]].

## Обобщение

Принцип применим к **любой HTF-зоне** того же направления:

| HTF-элемент | VC через |
|---|---|
| OB | LTF FVG того же направления ⊆ OB.zone |
| block_orders | LTF FVG того же направления ⊆ block.zone |
| RDRB POI | LTF FVG того же направления ⊆ POI |
| ob_liq | LTF FVG того же направления ⊆ ob_liq.zone |
| ... | (по аналогии) |

В каноне зафиксирован **только OB-кейс**. Расширения на другие HTF-зоны — feature пользовательских стратегий.

## Что VC даёт

| Аспект | Описание |
|---|---|
| **Подтверждение HTF-зоны** | OB с VC = «через эту зону прошёл impulse» → выше вероятность институциональной поддержки |
| **Не зона** | VC **не имеет собственной зоны интереса** |
| **Boolean predicate** | `has_vc(ob, fvg) → bool` или `find_vc_confirmations(ob, fvgs) → list[FVG]` |

## Не путать

| Что | Чем НЕ является |
|---|---|
| VC | зоной интереса |
| VC | volume-индикатором |
| VC | конкретным паттерном (это **семейство** проверок) |
| VC | i-FVG (i-FVG — инверсия FVG-A через FVG-B; VC — containment одного направления) |

## Mitigation

VC сам по себе не mitigated — это предикат, не зона. Mitigated **HTF-зона**, к которой VC привязан (OB / block_orders / RDRB POI / …) по своим канонам. LTF FVG, обеспечивающая VC, mitigated отдельно по канону FVG (wick-fill).

## Применения

1. **Confluence-фильтр для входа**: HTF OB подтверждённая LTF FVG того же направления — сильный signal-trigger.
2. **F5-кандидат для фракталов 12h**: counter VC внутри pivot bar (см. [[2026-05-26-vc-concept-canon-in-smc-lib-and-f5-search]] §II).
3. **Entry-zone setup**: вход по касанию LTF FVG (узкая зона реакции), SL за OB-зоной (широкий стоп).

## Эмпирика (BTC 6y, 12h фракталы)

Counter VC inside pivot 12h (см. [[2026-05-26-vc-concept-canon-in-smc-lib-and-f5-search]]):

| Filter | keep | P(Williams) | imp recall |
|---|---:|---:|---:|
| COUNTER VC any (OB 1/2h × FVG 15/20m) | 894 / 1105 | 52.9% (+3.3pp) | 13/16 |
| COUNTER VC OB=2h × FVG=20m | 459 / 1105 | 55.8% (+6.2pp) | 9/16 |
| ALIGNED VC ⚠ | 938 / 1105 | 46.9% (**−2.7pp**) | 11/16 |

**Aligned VC = anti-signal** (LTF displacement в направлении импульса → продолжение, не разворот). **Counter VC = positive signal**, лучший recall-trade-off среди F5 кандидатов.

## API (smc-lib)

```python
from elements.vc.code import has_vc, find_vc_confirmations

ok: bool = has_vc(ob, fvg)
confs: list[FVG] = find_vc_confirmations(ob, ltf_fvg_list)
```

## Артефакты

- Canon: `~/smc-lib/vc/{definition.md, code.py, tests/test_vc.py}` (7 тестов, 2026-05-26)
- Session: [[2026-05-26-vc-concept-canon-in-smc-lib-and-f5-search]]
- Истоки: [[2026-05-19-rdrb-v2-babai-fractal-prediction]]
