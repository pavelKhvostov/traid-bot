---
name: feedback-trendline-hma-78-200-default
description: "TrendLine ASVK (Hull MA) — по умолчанию применяются length=78 и length=200, режим Hma, value LIVE"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 3af6f0d9-c3ee-48ba-ae08-4c05d8c82af3
---

TrendLine ASVK (Hull MA) везде в библиотеке и проектах **по умолчанию применяется с двумя длинами: 78 и 200**, в режиме `Hma`, значение **LIVE** (HMA[i] = считается на close предыдущего бара, strict-causal).

**Why:** Эти параметры эмпирически приняты в проекте Pred-12h на baseline F1∩F2∩F3 (1267 кандидатов 12h-фракталов на BTC 6y):
- С5 (sweep HMA-78 на 12h ∪ D, LIVE) → P(W) **67.0%**, поймал 5 important фракталов
- С6 (sweep HMA-200 на D, LIVE) → P(W) **81.6%**, поймал 1 important
- Другие длины (21, 50, 100, 150) проигрывали или давали маржинальный edge при tune

**How to apply:**
- При любом упоминании "TrendLine" / "HMA" в коде, документации, бэктестах — default 78 и 200, mode Hma.
- Helpers в коде: `trend_line_hma_78(closes)`, `trend_line_hma_200(closes)` в `~/smc-lib/indicators/trend_line_asvk.py`.
- Канон в [[../smc-lib/rules.md|Правило 7]] и в проекте [[../smc-lib/projects/pred12h-fractal-three-candles.md]].
- Другие длины допустимы ТОЛЬКО при явном обосновании на baseline и не как замена, а дополнительный slot.
- Value semantics — всегда LIVE: HMA на pivot bar i = значение, отображаемое на чарте во время формирования i, до его close. Никаких lookahead.
