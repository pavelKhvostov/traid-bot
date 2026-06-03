---
name: feedback-expert-force-opinion-trigger
description: При триггере «экспертное заключение по силе» запускать ~/smc-lib/prediction-algo/force_opinion.py. Это НЕ то же что zones_opinion.py (P_hit_D) — это Phase 4 force framework.
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 5dfe8bf0-bba6-41f4-89b4-4c25014664a4
---

«**Экспертное заключение по силе**» = run `python3 ~/smc-lib/prediction-algo/force_opinion.py`.

**Why:** Пользователь явно различает 3 типа «экспертных заключений» (создан 2026-05-31):
- `zones_opinion.py` — куда дойдёт цена (P_hit_D кластеры, базовый прогноз)
- **`force_opinion.py`** — **НА ЧЬЕЙ СТОРОНЕ СИЛА** (Phase 4 framework: Multi-TF force, anchors, magnets, historical memory, BIAS classification)
- `expert/opinion.py` — multi-TF cascade индикаторов (старый legacy, отдельный paradigm)

**How to apply:** Когда в запросе фраза «экспертное заключение по силе», «по чьей стороне сила», «сравни силу зон», «buyer vs seller balance», «multi-TF force», «pivot signature» — запускать `force_opinion.py`. Если про достижение зон — `zones_opinion.py`.

## Различия трёх «экспертных заключений»

| | `force_opinion.py` ⚡ | `zones_opinion.py` | `expert/opinion.py` |
|---|---|---|---|
| **Что считает** | Multi-TF BUYER vs SELLER force, anchors, magnets, historical memory | P_hit_D кластеры зон, ranking | 11 индикаторов + детекторы зон |
| **Output** | Per-TF force table, BIAS classification (UNANIMOUS / PIVOT signature / BALANCED / HTF BULLISH/BEARISH), top zones, verdict | Карта кластеров + сценарии A/B + invalidation | Top-down cascade W → 15m |
| **Фокус** | где доминирует сила, разворот ли это, anchor strength | вероятность касания зон, направление | comprehensive market state |
| **Время выполнения** | ~30-60 сек (precompute 1y × 9 TFs) | ~5-10 сек | минуты |
| **На основе** | Phase 4 spec (101 features, force formulas) | LookupModel из prediction-algo v2 | Multi-indicator cascade |

## Триггеры

| Фраза пользователя | Запускать |
|---|---|
| «экспертное заключение по силе» | `force_opinion.py` |
| «на чьей стороне сила» | `force_opinion.py` |
| «multi-TF force balance» | `force_opinion.py` |
| «pivot signature ли это?» | `force_opinion.py` |
| «сравни силу зон» | `force_opinion.py` (можно с --cut-off) |
| «экспертное заключение по зонам интереса» | `zones_opinion.py` |
| «куда цена сперва двинется» | `zones_opinion.py` |
| «карта зон с прогнозом» | `zones_opinion.py` |
| «экспертный анализ» / «полный анализ» | `expert/opinion.py` |
| «multi-TF каскад» | `expert/opinion.py` |

## Output format force_opinion (стабильный)

1. HEADER (BTC price, MSK time, n zones)
2. ПО ТФ таблица BUYER / SELLER / NET / Dominant (9 ТФ)
3. Summary: n_TFs BUYER wins / 3D dominance
4. **BIAS CLASSIFICATION** — 5 категорий:
   - UNANIMOUS BULLISH (9/9 TFs BUYER)
   - UNANIMOUS BEARISH (9/9 TFs SELLER)
   - PIVOT signature (HTF + LTF flip) — most informative для turning points
   - BALANCED (weak bias, NET < 100)
   - HTF BULLISH / BEARISH bias (mid-conviction)
5. TOP 5 LONG zones + TOP 5 SHORT zones (with strengths)
6. HISTORICAL ZONE MEMORY: aged 30d+/60d+/90d+ in band ±2%
7. ЗАКЛЮЧЕНИЕ ЭКСПЕРТА (textual verdict с reasoning)

## CLI options

```
python3 ~/smc-lib/prediction-algo/force_opinion.py [--cut-off "YYYY-MM-DD HH:MM"] [--train-days 365] [--no-fetch]
```

- `--cut-off`: historical analysis (MSK time)
- `--train-days`: window for precompute (default 365)
- `--no-fetch`: пропустить fetch_1m_missing

## Связи

- `[[feedback-expert-zones-opinion-trigger]]` — zones_opinion.py триггер
- `[[feedback-expert-chart-trigger]]` — другие expert/ триггеры
- `[[bb-model-phase4-negative-result]]` — Phase 4 ML не сработал, но force metrics — полезный layer
- `[[feedback-ob-vc-strict-detection-timing]]` — strict canon
- `~/smc-lib/projects/PHASE4_SPEC.md` — полная спека framework'а
