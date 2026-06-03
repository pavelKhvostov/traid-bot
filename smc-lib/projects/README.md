# Проекты

Раздел для **прикладных проектов** библиотеки — комбинаций элементов / правил / индикаторов под конкретную предсказательную задачу.

Отличие от других разделов:
- `elements/` — atomic SMC primitives (canon)
- `indicators/` — independent numeric features (canon)
- `rules.md` / `zone_of_interest.md` — общие правила (canon)
- `scripts/` — одноразовые research/backtest (НЕ canon)
- **`projects/`** — целостные прикладные пайплайны, использующие canon (semi-canon, документируются как фиксированные пайплайны)

## Текущие проекты

| Проект | Описание | Статус |
|---|---|---|
| [pred12h-fractal-three-candles](pred12h-fractal-three-candles.md) | Прогнозирование Williams-фрактала на 12h по строго causal (i-2, i-1, i) сигналам. Cascade F1-F3 + OR-basket С1-С7 | active |
| [bounce-or-break](bounce-or-break.md) | ML classifier P(bounce) при касании зоны интереса. Per-element series, первая модель = ob_vc(1h+2h). 8 design-вопросов закрыты 2026-05-29 | **approved**, готов к coding |
| [prediction-algo](prediction-algo.md) | Зональный калибратор P_hit_12h/D. v1 в production (top-5 hit_D 87%). v2 на PC1 сейчас | production v1 / v2 wf |
| [pivot](pivot.md) | Selectivity-эксперимент 2026-06-01. Подтвердил: (1.1.1 SWEPT cascade ∩ 12h Williams ≥2%) → WR 62% / PF 3.47 на BTC 6y. Доработка перенесена в pred12h | **validated → merged** |
| [sync](sync.md) | Синхронизация BTC × TOTAL × USDT.D в окне 2025-01 → сейчас. Главный TF 2h. Цель — найти sync/divergence паттерны для отбора качественных setups | **active design** |

> **Strategy 1.1.1** (v1/v2 + Floating TP reference) переехала в [`strategies/strategy_1_1_1/`](../strategies/strategy_1_1_1/). Ссылка из [bounce-or-break.md](bounce-or-break.md) на `[[strategy-1-1-1-v2]]` теперь указывает туда.

## Структура проекта-документа

Каждый проект включает:
1. **Цель** — что прогнозируем
2. **Ground truth** — на чём измеряем (BTC 6y in-sample, 18 imp)
3. **Methodology** — архитектура (cascade / OR-basket / иное)
4. **Этапы / условия** — таблицы с числами
5. **Текущая корзина** — состояние basket
6. **Открытые задачи** — что осталось

## Связи

- Правила: [`rules.md`](../rules.md)
- Зоны: [`zone_of_interest.md`](../zone_of_interest.md)
- Элементы: [`elements/`](../elements/)
