# VC (Volume Confirmation)

**Концепция подтверждения объёма** — обобщённый принцип, по которому HTF-зона считается «подтверждённой» через присутствие impulse-displacement (FVG) на LTF внутри неё.

> ⚠️ **VC не является зоной интереса.** Это **подтверждающий предикат** над HTF-элементом. Сама зона остаётся за HTF-элементом (OB, block_orders, RDRB POI и т.д.). VC только **сигнализирует**, что эта зона валидирована LTF-displacement'ом.

Canon из vault: `~/traid-bot/vault/sessions/2026-05-19-rdrb-v2-babai-fractal-prediction.md` (2026-05-19).
Определение зафиксировано как обобщённая концепция 2026-05-26.

> ⚠️ Название «Volume Confirmation» — vestigial. Сам **расчёт чисто геометрический**, объём не участвует. Идея в том, что HTF-зона, через которую прошёл impulse (LTF FVG), считается «насыщенной объёмом» **по геометрии displacement'а**, а не по фактическому volume-индикатору.

## Принцип

```
VC(HTF_zone, LTF_TF) := ∃ FVG на LTF_TF, такой что
                         FVG.direction == HTF_zone.direction
                         AND FVG.zone ⊆ HTF_zone.zone
                         AND FVG сформирована в окне активности HTF_zone
```

То есть: «есть ли внутри HTF-зоны такой же по направлению FVG младшего TF».

## Три канонических варианта (зафиксированы пользователем 2026-05-26)

VC реализуется **тремя вариантами** канона. Два класса:

### Spatial containment (FVG внутри HTF OB)

**Variant 1.** HTF=OB на 1h/2h, LTF=FVG на 15m/20m.

| HTF (OB) | LTF (FVG) |
|---|---|
| 1h | 15m |
| 1h | 20m |
| 2h | 15m |
| 2h | 20m |

**Variant 2.** HTF=OB на 4h/6h, LTF=FVG на 1h/2h/90m.

| HTF (OB) | LTF (FVG) |
|---|---|
| 4h | 1h |
| 4h | 90m |
| 4h | 2h |
| 6h | 1h |
| 6h | 90m |
| 6h | 2h |

**Геометрия:** `FVG.zone ⊆ OB.zone` (containment).
**Direction:** aligned (`OB.dir == FVG.dir`).

### Temporal sequence (FVG сразу после OB на том же TF)

**Variant 3.** OB и FVG на **одном** TF (1h или 2h), FVG формируется **сразу после OB**.

| OB TF | FVG TF | Положение |
|---|---|---|
| 1h | 1h | FVG.c1 = OB.cur + 1 |
| 2h | 2h | FVG.c1 = OB.cur + 1 |

**Геометрия:** `FVG.c1 = OB.cur+1` (sequential). **Containment НЕ требуется** — FVG обычно ВНЕ OB.zone (above для LONG, below для SHORT), т.к. displacement-импульс выводит цену из зоны.
**Direction:** aligned.

**Семантика:** OB сработала как launchpad → следующая свеча начинает impulse → displacement → gap (FVG).

## Сводный предикат

```
VC(OB, FVG) := OB.direction == FVG.direction AND (
    (FVG.zone ⊆ OB.zone)                                  # Variants 1, 2 (spatial)
    OR
    (FVG.c1 = OB.cur+1 AND OB.tf == FVG.tf AND OB.tf ∈ {1h, 2h})  # Variant 3 (temporal)
)
```

## Обобщение на другие HTF-элементы

Концепция VC применима к любой HTF-зоне (block_orders, RDRB POI, ob_liq) по аналогии. **В каноне фиксируется только OB** — расширения являются feature пользовательских стратегий.

## Что VC даёт

| Аспект | Описание |
|---|---|
| **Подтверждение HTF-зоны** | HTF-OB с VC = «через эту зону прошёл impulse» → выше вероятность институциональной поддержки |
| **Не зона** | VC **не имеет собственной зоны интереса**. Reaction-зона = LTF FVG (если нужно entry) или HTF OB.zone (если нужен контекст) |
| **Boolean predicate** | На уровне API: `has_vc(ob, fvg) → bool` или `find_vc(ob, fvg_list) → list[FVG]` |

## Не путать

| Что | Чем НЕ является |
|---|---|
| VC | зоной интереса (не имеет своей зоны) |
| VC | volume-индикатором (объём не участвует) |
| VC | конкретным паттерном (это **семейство** проверок: FVG в любой HTF-зоне) |
| VC | i-FVG (i-FVG — инверсия FVG-A через FVG-B; VC — containment одного направления) |

## Mitigation

VC сам по себе не mitigated — это предикат, не зона. Что mitigated — это **HTF-зона**, к которой VC привязан (OB / block_orders / RDRB POI / …) по своим канонам.

LTF FVG, обеспечивающая VC, mitigated отдельно по канону FVG (wick-fill). После её consumption — VC «снимается» (если других LTF FVG нет в HTF-зоне).

## API (smc-lib)

```python
from elements.vc.code import has_vc, find_vc_confirmations

# Точечная проверка: подтверждает ли конкретная FVG данную OB?
ok: bool = has_vc(ob, fvg)

# Поиск всех LTF FVG, подтверждающих HTF OB:
confirmations: list[FVG] = find_vc_confirmations(ob, ltf_fvg_list)
```

Детектор работает с **уже посчитанными** OB и FVG. TF и временная корректность (LTF FVG внутри окна активности HTF OB) обеспечивает вызывающий код.

## Эталонный пример

См. эталонные числа в `tests/test_vc.py`.
