---
name: feedback-expert-zones-opinion-trigger
description: При триггере «экспертное заключение по зонам интереса» запускать ~/smc-lib/prediction-algo/zones_opinion.py. Это НЕ то же что expert/opinion.py (multi-TF cascade)
metadata: 
  node_type: memory
  type: feedback
  originSessionId: ff4f5d07-aadb-4148-b954-c32ba7546ea5
---

«**Экспертное заключение по зонам интереса**» = run `python3 ~/smc-lib/prediction-algo/zones_opinion.py`.

**Why:** Пользователь явно различает 2 типа экспертных заключений и хочет канонический модуль для зон-варианта (создан 2026-05-28). `expert/opinion.py` решает другую задачу.

**How to apply:** Когда в запросе есть фраза «экспертное заключение» или «куда цена двинется» с упоминанием «зон интереса» / «зон» / упор на zone-based анализ → запускать `zones_opinion.py`. Если просят multi-TF cascade с индикаторами (MoneyHands, VWAP, TrendLine, RSI и т.д.) — это `expert/opinion.py`.

## Различия между двумя «экспертными заключениями»

| | `prediction-algo/zones_opinion.py` | `expert/opinion.py` |
|---|---|---|
| Что использует | predict_zones (ML-модель) | 11 индикаторов + детекторы зон |
| Output | карта кластеров + сценарии A/B + invalidation | top-down cascade W → 15m |
| Фокус | вероятностный прогноз касания зон | comprehensive market state |
| Время выполнения | ~5-10 сек | минуты |

## Триггеры

| Фраза пользователя | Запускать |
|---|---|
| «экспертное заключение по зонам интереса» | `zones_opinion.py` |
| «куда цена сперва двинется» | `zones_opinion.py` |
| «карта зон с прогнозом» | `zones_opinion.py` |
| «экспертный анализ» / «полный анализ» | `expert/opinion.py` |
| «multi-TF каскад» | `expert/opinion.py` |

## Output format zones_opinion (стабильный)

1. КАРТА КЛАСТЕРОВ (от верха до низа) с маркерами 🔥/⭐
2. БАЗОВЫЙ ПРОГНОЗ (первое касание) + дистанция + P(D)
3. ЦЕПОЧКА МАГНИТОВ
4. СЦЕНАРИИ A (базовый) / B (отскок)
5. INVALIDATION

## Связи

- `[[feedback-expert-chart-trigger]]` — другие expert/ триггеры
- `[[feedback-expert-opinion-is-multi-tf-cascade]]` — структура opinion.py
- `[[prediction-algo-final-results]]` — что такое prediction-algo
