---
tags: [strategy, 1-1-6, live, hybrid]
date: 2026-05-13
status: live (added 2026-05-13)
---

# Strategy 1.1.6 — FVG macro + immediate FVG-htf entry (live hybrid)

Гибрид 1.1.1 и 1.1.3:
- macro как в 1.1.1: FVG-4h/6h внутри OB-1d/12h
- entry как в 1.1.3: FVG того же ТФ что OB-htf (1h или 2h)

## Каскад

```
L1: OB-{1d, 12h}        ← top-OB
L2: FVG-{4h, 6h}        ← macro FVG, как в 1.1.1
L3: OB-{1h, 2h}         ← htf-OB
L4: FVG того же ТФ что L3 ← immediate entry, как в 1.1.3
```

## Параметры (live)

- entry_pct = 0.70 (deep FVG)
- sl_pct = 0.35 sym (между OB-htf edge и FVG entry edge)
- RR = 2.2
- Без confluence фильтра (1.1.1 has confluence, 1.1.6 doesn't)

Применяются через `MultiStrategyScanner.apply_user_params()`.

## Файлы

- Detector: [strategies/strategy_1_1_6.py](../../../../strategies/strategy_1_1_6.py)
- Live scanner: [multi_strategy_scanner.py](../../../../multi_strategy_scanner.py) (S116)
- Integration: [main.py](../../../../main.py)

## Статус

**LIVE** (с 2026-05-13). Бэктест не проведён — добавлен по запросу пользователя по аналогии с 1.1.3 параметрами.

## Hypothesis

Идея: 1.1.3 (OB+OB+OB+FVG-immediate) показала +11.4R / 3y. 1.1.1 с FVG-macro на L2 показала +46.8R / 3y. Может, immediate-entry архитектура из 1.1.3 + FVG-macro из 1.1.1 даст синергию.

TBD: backtest на тех же 3y данных что и 1.1.1/1.1.3 для прямого сравнения.

## Связи

- [[2026-05-13-live-bot-vic-ifvg-strategies-117-118]] — session note
- [[strategy_1_1_1]] — каноничная структура (с SWEPT)
- 1.1.3 (см. research/1_1_3/README.md) — immediate-entry архитектура
