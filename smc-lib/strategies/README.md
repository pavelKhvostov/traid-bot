# Strategies

Раздел для **торговых стратегий** библиотеки — целостных trade-pipelines (detection → entry → exit), объединяющих элементы / правила / индикаторы.

Отличие от смежных разделов:
- `elements/` — atomic SMC primitives
- `patterns/` — composite SMC структуры (без trade-rules)
- `projects/` — research/predictive пайплайны (без exit-механик)
- **`strategies/`** — полные trade-стратегии с entry/SL/TP

## Список

| Стратегия | Описание | Статус |
|---|---|---|
| [strategy_1_1_1](strategy_1_1_1/) | Каскад `OB+FVG` macro → entry. V1 production в `~/traid-bot/`. V2 (унификация на `ob_vc` canon) — design. Floating TP reference от etap108 | v1 production / v2 design |
