# Strategy 1.1.4 — гибрид 1.1.1 + 1.1.3

Status: **WIP** (work in progress). Optimize/analyze не успели.

## Идея

Гибрид:
- **macro-слой как в 1.1.1**: FVG-4h/6h
- **entry-слой как в 1.1.3**: immediate FVG того же ТФ что OB-htf

«Что если взять macro-FVG обратно, но entry оставить как в 1.1.3» — промежуточная итерация для проверки гипотезы.

Иерархия ТФ:
```
OB-{1d, 12h}         ← top
+ FVG-{4h, 6h}        ← macro (как 1.1.1)
→ OB-{1h, 2h} + FVG того же ТФ  ← htf + immediate entry (как 1.1.3)
```

## Базовые показатели (3y BTC)

- @ RR=1.0: 53 closed, **WR 52.8%, +3.0R**
- @ RR=2.2: 53 closed, WR 37.7%, +11.0R

Тот же порядок что 1.1.3 (раздуленный пул на 122 сделках там, против 53 у 1.1.4).

## Файлы

### backtest/

- `backtest_strategy_1_1_4.py`

### analyze/

- `analyze_1_1_4_ob_swept.py` (2026-05-06) — split SWEPT для cross-strategy теста

Optimize не написаны — Pavel: «WIP, не успел».

## SWEPT split на default config (2026-05-06)

`analyze/analyze_1_1_4_ob_swept.py` на default (fvg_variant=v1, no_entry=on):

```text
deduped=53  SWEPT=43 (81%)  NOT-SWEPT=10 (19%)

RR=1.0:  ALL +7R / R-tr 0.226   SWEPT +4R / 0.143   NOT-SWEPT +3R / 1.000 (n=3, шум)
RR=2.2:  ALL +14.8R / 0.322     SWEPT +13.2R / 0.347 (≈ALL)   NOT-SWEPT +1.6R / 0.200
```

**Вывод:** SWEPT-фильтр для 1.1.4 на RR=2.2 нейтрален (Δ R/tr +0.025 в шуме),
на RR=1.0 хуже ALL. Выборка маленькая (53 deduped, 10 NOT-SWEPT). В live
применять не надо. См. [[swept-фильтр-применим-только-к-1-1-1]] и
[[2026-05-06-swept-cross-strategy-test]].
