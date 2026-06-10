---
type: external-source
source_file: Smart-Money-Concept-trading-strategy-PDF.pdf
source_pages: 11
author: "обзор SMC (Smart Money Concepts)"
ingested: 2026-06-10
tags: [smc, ict, methodology, external]
---

# SMC-обзор: OB, Breaker, BOS, CHoCH + SMC vs Price Action

Конспект `Smart-Money-Concept-trading-strategy-PDF.pdf`. Парная к [[ICT-методология-7-концептов-и-liquidity-sweep]]. Тезис источника: SMC — не стратегия, а **философия** «следуй за умными деньгами» (банки/хедж-фонды/ЦБ оставляют следы; ритейл — жертва liquidity-hunt). По сути SMC = переупакованный price action + терминология.

## Ключевые концепты (что добавляет сверх первого PDF)

1. **Order Blocks (OB)** — накопление/распределение крупных объёмов институционалами; на графике = ranging market. Сверка с каноном: [[что такое order block]], [[универсальные определения OB и FVG]].
2. **Breaker Blocks** ⚡НОВОЕ — order block, который НЕ удержал уровень и был пробит; маркет-мейкеры специально ломают S/R, чтобы снять стопы ритейла. (У нас как отдельного детектора нет — кандидат.)
3. **Fair Value Gaps (FVG)** — разрыв при быстром движении. См. [[что такое fvg]].
4. **Break of Structure (BOS)** — новый хай/лой со сломом предыдущего = продолжение тренда. (У нас фигурирует в VIC_BOS — [[vic_bos]].)
5. **Change of Character (CHoCH)** ⚡ — резкая смена поведения (волатильность/объём/price action) → слабость тренда → возможный разворот. Отличие от BOS: BOS = продолжение, CHoCH = разворот.
6. **Liquidity** — типы: trendline liquidity, buy-side, sell-side, double tops/bottoms. См. [[три класса зон ликвидность эффективность неэффективность]].
7. **Mitigation blocks** ⚡ — упомянуты в словаре SMC (наряду с «liquidity grabs»). Митигация у нас уже центральная (first-touch, [[zone-mitigation-filter-required]]).

## Сетап (3 шага)

- **Шаг 1 — тренд** через market structure: HH+HL = up, LH+LL = down, CHoCH = смена тренда.
- **Шаг 2 — high-probability OB**: лучший OB тот, что (а) вызвал CHoCH, (б) имеет liquidity и FVG прямо над/под собой. Ждём, что цена придёт снять эту ликвидность перед продолжением. → совпадает с нашей логикой confluence-каскадов ([[expert-opinion-multi-tf-cascade-methodology]]).
- **Шаг 3 — вход/выход**: entry над bullish OB, SL под зоной, TP до structural high.

## SMC vs Price Action

- Price Action: ЧТО происходит (паттерны, индикаторы, S/R), не «почему».
- SMC: ПОЧЕМУ — намерения маркет-мейкеров, supply/demand, «куда идут деньги».
- Критика (важно для нас): **нет конкретных доказательств** манипуляций; ликвидность ритейла мала для таргетинга институционалами; терминология перегружена. → подтверждает нашу позицию: эти концепты ценны как **геометрические детекторы зон**, а не как «теория рынка». Edge должен доказываться backtest'ом ([[7-criteria-of-good-strategy]]), не нарративом.

## Вывод для проекта

Новые кандидаты-детекторы из этого источника: **Breaker Block** (пробитый OB), **CHoCH как именованный элемент разворота** (родственно нашему [[reversal-3candle-fractal-prediction]] и Bulkowski-детекторам [[bulkowski-reversal-detectors-btc-12h-baseline]]). BOS у нас уже есть ([[vic_bos]]). Проверять на lookahead и cross-asset, как всегда.

Каталог: [[ICT-source-индекс]].
