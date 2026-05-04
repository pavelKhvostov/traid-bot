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

Optimize/analyze не написаны — Pavel: «WIP, не успел».
