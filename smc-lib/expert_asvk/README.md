# Expert ASVK — multi-agent market analysis

**Status:** scaffolding (2026-05-30)
**Owner:** Vadim
**Canon:** memory `feedback-expert-asvk-multi-agent-architecture.md`

## Архитектура

Каждый SMC-элемент / индикатор реализуется как **независимый агент**, который даёт собственное мнение о состоянии рынка в текущий момент. **Expert ASVK** — orchestrator, который собирает мнения и формирует итоговое заключение.

```
                            ┌─────────────────────┐
                            │   Expert ASVK       │
                            │   (orchestrator)    │
                            └──────────▲──────────┘
                                       │ AgentOpinion[]
        ┌───────────┬──────────┬───────┴──────┬──────────┬──────────┐
        │           │          │              │          │          │
   ┌────▼─────┐ ┌──▼──────┐ ┌──▼──────┐  ┌────▼───┐ ┌────▼───┐ ┌────▼────┐
   │  Zones   │ │  Money  │ │   RSI   │  │ Trend  │ │  VIC   │ │  VWAPs  │
   │  Agent   │ │  Hands  │ │  Agent  │  │  Line  │ │  Agent │ │  Agent  │
   │          │ │  Agent  │ │         │  │  Agent │ │        │ │         │
   └──────────┘ └─────────┘ └─────────┘  └────────┘ └────────┘ └─────────┘
```

## Принципы

1. **Независимость агентов** — каждый агент читает свои данные, использует свой набор инструментов и НЕ обращается к другим агентам.
2. **Унифицированный output** — `AgentOpinion` (см. `agents/base.py`):
   - `direction`: BULLISH / BEARISH / NEUTRAL
   - `conviction`: 0.0 - 1.0
   - `levels`: list of target/support/resistance с probability
   - `invalidation`: optional level breaking the thesis
   - `reasoning`: short human-readable text
   - `timeframe`: focus TF of the agent
3. **Orchestrator пассивен** — не имеет собственного мнения, только агрегирует.

## Список агентов

| Агент | Статус | Источник | Модуль |
|---|---|---|---|
| zones | ⚠️ существует прообраз | `prediction-algo/zones_opinion.py` | `agents/zones_agent.py` (адаптер) |
| money_hands | 🔧 в работе (PC2 screening 6912 configs) | `indicators/money_hands_asvk.py` | `agents/money_hands_agent.py` (todo) |
| rsi | 📋 placeholder | — | `agents/rsi_agent.py` (todo) |
| trendline | 📋 placeholder | `indicators/trend_line_asvk.py` (HMA 78+200) | `agents/trendline_agent.py` (todo) |
| vic | 📋 placeholder | `indicators/vic_asvk.py` (maxV) | `agents/vic_agent.py` (todo) |
| vwaps | 📋 placeholder | `indicators/vwap_anchored.py` | `agents/vwaps_agent.py` (todo) |

## План имплементации

1. ✅ Каркас (этот README + base classes)
2. **Zones agent** — адаптер вокруг `zones_opinion.py` (минимальная работа)
3. **Money Hands agent** — после PC2 screening завершится, делаем full WF top-20 → встроить лучший конфиг
4. **TrendLine agent** — самый простой, есть HMA 78+200 LIVE и Правило 7 ([[feedback-trendline-hma-78-200-default.md]])
5. **VIC agent** — maxV / fractal_maxV
6. **VWAPs agent** — anchored VWAP от fractals (есть шаблон `[[feedback-anchored-vwap-from-fractals]]`)
7. **RSI agent** — standard indicator wrapper
8. **Expert ASVK orchestrator** — после готовности 3-4 агентов, начать собирать verdict (правила агрегации обсудим тогда)

## Запуск (после готовности)

```python
from expert_asvk import ExpertASVK

expert = ExpertASVK(asset="BTC")
verdict = expert.opinion()  # вызывает всех агентов, собирает AgentOpinion[], формирует verdict
print(verdict)
```

## Связи

- Memory: `[[feedback-expert-asvk-multi-agent-architecture.md]]` — архитектурный принцип
- Memory: `[[feedback-expert-zones-opinion-trigger.md]]` — zones agent точка входа
- Memory: `[[feedback-trendline-hma-78-200-default.md]]` — TrendLine canon
- Memory: `[[feedback-anchored-vwap-from-fractals.md]]` — VWAP recipe
- НЕ путать с legacy `~/smc-lib/expert/opinion.py` — это старый combined-cascade, другой paradigm
