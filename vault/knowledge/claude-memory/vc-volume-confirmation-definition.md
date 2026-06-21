---
name: vc-volume-confirmation-definition
description: "VC = подтверждение HTF-OB через displacement (FVG). 3 варианта: V1 (OB 1h/2h + FVG 15m/20m, containment), V2 (OB 4h/6h + FVG 1h/90m/2h, containment), V3 (OB 1h/2h + FVG SAME TF immediately after, NO containment). Direction = aligned всегда."
metadata: 
  node_type: memory
  type: project
  originSessionId: 92a19f52-96e8-4b59-9766-f29ae6786cff
---

# VC (Volume Confirmation)

**Концепция подтверждения объёма** — НЕ зона интереса, а **предикат над HTF-зоной**. Реализуется через три канонических варианта (spatial + temporal).

Canon: `~/smc-lib/vc/{definition.md, code.py, tests/}`. Записано как Правило 3 в `~/smc-lib/rules.md`.

## Сводный предикат (3 варианта, утверждены 2026-05-26)

```
VC(OB, FVG) := OB.dir == FVG.dir AND (
    # Spatial containment (Variants 1, 2)
    (FVG.zone ⊆ OB.zone AND (OB.tf, FVG.tf) ∈ {
        (1h, 15m), (1h, 20m), (2h, 15m), (2h, 20m),        # V1
        (4h, 1h), (4h, 90m), (4h, 2h),                      # V2
        (6h, 1h), (6h, 90m), (6h, 2h),                      # V2
    })
    OR
    # Temporal sequence (Variant 3)
    (FVG.c1 = OB.cur+1 AND OB.tf == FVG.tf AND OB.tf ∈ {1h, 2h})
)
```

| Variant | HTF (OB) | LTF (FVG) | Геометрия | Direction |
|---|---|---|---|---|
| V1 | 1h, 2h | 15m, 20m | FVG ⊆ OB.zone | aligned |
| V2 | 4h, 6h | 1h, 90m, 2h | FVG ⊆ OB.zone | aligned |
| V3 | 1h, 2h | **same TF** | FVG.c1 = OB.cur+1, **NO containment** | aligned |

**V3 семантика:** OB → импульс → FVG. FVG обычно ВНЕ OB.zone (above для LONG / below для SHORT), т.к. displacement выводит цену из зоны.

## Обобщение на другие HTF-элементы

Принцип применим к любой HTF-зоне (block_orders, RDRB POI, ob_liq), не только к OB. В каноне зафиксирован **только OB**, расширения — feature стратегий.

## Что VC НЕ является

- ❌ Не зоной интереса (не имеет собственной зоны)
- ❌ Не volume-индикатором (название vestigial; объём не используется)
- ❌ Не конкретным паттерном (это **семейство** проверок)
- ❌ Не подвержено mitigation (mitigated HTF-зона, не VC)

## API

```python
from elements.vc.code import has_vc, find_vc_confirmations
ok: bool = has_vc(ob, fvg)
confs: list[FVG] = find_vc_confirmations(ob, ltf_fvgs)
```

## Related

- [[smc-lib-location]] — ~/smc-lib/
- [[zone-class-liquidity-inefficiency-block]]
