---
name: feedback-expert-opinion-is-multi-tf-cascade
description: "Экспертное заключение строится top-down каскадом W → D → 12h → 4h → 1h → 15m, не на одном ТФ"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: c2a93cd3-276b-4637-ad17-ca05219a1dfa
---

**Экспертное заключение о движении цены — это всегда multi-TF каскад top-down**, не анализ на одном ТФ.

## Каскад (W → 15m)

| ТФ | Вопрос, на который отвечает |
|---|---|
| **W** | Доминирующий трейд года; macro magnets |
| **D** | Текущая swing-структура (месяцы); primary reaction zones |
| **12h** | Intermediate confluence (недели) |
| **4h** | Setup zones; working area |
| **1h** | Entry context; confirmation zones |
| **15m** | Precision triggers; execution |

**W = Monday-anchor** ([[weekly-tf-anchor-monday]]), не epoch.

## Принципы

1. **HTF priority** — при конфликте HTF побеждает. См. [[feedback-fractal-liquidity-strength-and-sweep]]: HTF wick "проглатывает" LTF события.
2. **Confluence** — сетап считается valid если магниты/зоны нескольких ТФ align (например, D FL + 4h FVG + 1h OB в одной области).
3. **Top-down narrative** — мнение строится от макро (W trend) к микро (15m trigger). Не наоборот.
4. **LTF не отменяет HTF**: "пробой" 15m FH внутри 4h wick не разрушает 4h setup.

## Why

Поправка пользователя 2026-05-24: "экспертное заключение делается комплексно на всех ТФ спускаясь от W до 15m". До этого моё мнение было основано только на D — это методологически неполно.

## How to apply

- При любом запросе "куда пойдёт цена" / "что на графике" / "дай мнение" — прогонять каскад W → D → 12h → 4h → 1h → 15m.
- Output: краткое summary по каждому ТФ (trend + key zones) + **confluence section** + сценарии.
- Не давать одно-TF мнение без явного указания "только TF X, остальные не учтены".

См. `~/smc-lib/expert_opinion.md` (методология) и `~/smc-lib/scripts/expert_opinion.py` (реализация).
