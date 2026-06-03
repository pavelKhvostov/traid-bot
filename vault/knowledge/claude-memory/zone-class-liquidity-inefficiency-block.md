---
name: zone-class-liquidity-inefficiency-block
description: "Three-class taxonomy of SMC zones (user's terminology) — liquidity / inefficiency / блок (formerly 'efficiency', renamed 2026-05-29)"
metadata: 
  node_type: memory
  type: user
  originSessionId: f4db015b-597b-4328-ad33-5010538fa5f2
---

Пользовательская классификация зон SMC, которой надо придерживаться при
обсуждении стратегий проекта traid-bot.

**Канон 2026-05-29** (по Правилу 8 в `~/smc-lib/rules.md`):

| Класс | Метафора | Элементы |
|---|---|---|
| **Ликвидность** (liquidity) | ⛽ Топливо | `fractal`, `rb`, `ob_liq.liq_zone` |
| **Неэффективность** (inefficiency) | 🧲 Магнит | `fvg`, `i_fvg`, `marubozu` (тело) |
| **Блок** (block) | 🎯 Точка реакции / исполнения | `OB`, `RDRB`, `block_orders`, `ob_liq.zone` |

## История термина

- **До 2026-05-29:** третий класс назывался **«эффективность» / «efficiency»**.
- **2026-05-29:** переименован в **«блок»** по решению пользователя — для согласованности с уже использовавшимся термином **«блок наторгованный»** (maxV ASVK). См. сессию `2026-05-29-prediction-algo-verification-and-roadmap.md`.
- **Старая memory** `zone-class-liquidity-inefficiency-efficiency.md` удалена при миграции.

## Семантика классов

- **Liquidity** ⛽ — скопления ордеров (стопы розницы, лимитки). Крупный игрок «собирает» их для набора позиции. Магнит-логика: цена тянется из-за **collected stops**.
- **Inefficiency** 🧲 — дисбаланс buyers/sellers, рынок не успел сформировать справедливую цену. Магнит-логика: цена возвращается **заполнить** untraded area.
- **Блок** 🎯 — точки исполнения institutional orders. **НЕ магнит**, а точка **реакции**: цена касается → отскок в направлении HTF-тренда. Эквивалент S/R в этой таксономии.

## Тонкости

- Классификация ортогональна направлению (LONG / SHORT).
- `ob_liq` — composite: содержит и `liq_zone` (liquidity), и `zone` (блок).
- `marubozu` — composite: тело = inefficiency, open level = liquidity (sweep magnet).
- 3-фазный цикл движения (Правило 8): `liquidity → inefficiency → блок → next liquidity`.

## Связи

- **Канон:** `~/smc-lib/rules.md` → Правило 8 — полная теория с фазами и таблицами.
- [[feedback-untraded-area-is-magnet]] — fundamental SMC principle untraded → magnet.
- [[feedback-marubozu-is-imbalance-not-support]] — marubozu = inefficiency, не S/R.
- [[feedback-fractal-liquidity-strength-and-sweep]] — сила liquidity = TF × age × cluster.
- [[feedback-fvg-wick-fill-mitigation]] — модели mitigation per class.
- Полный canon в проекте: `vault/knowledge/smc/три класса зон ликвидность эффективность неэффективность.md` (исторический файл, ещё не переименован).
