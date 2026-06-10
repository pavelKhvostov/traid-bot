---
type: external-source
source_file: "Month05-January_2017_Study_Notes.pdf + Month06-feb_studynotes.pdf"
source_pages: "147 + 92"
course: "ICT Monthly Mentorship 2016-2017"
month: "05-06 / Январь-Февраль 2017"
author: "Michael J. Huddleston (ICT)"
ingested: 2026-06-10
tags: [ict, smc, course, pd-arrays, intermarket, external]
---

# ICT-курс · Month 05-06 (январь-февраль 2017) — Intermarket Analysis + PD Arrays (иерархия зон)

Объединяю два месяца: Month05 (Intermarket, мало для крипты) + Month06 (⭐ ключевая иерархия PD Arrays). Текст слайдов слабо извлекается (много картинок), но смысловое ядро ясно.

## Month05 — Intermarket Analysis (forex-специфика)

- **4 рынка** в связке: Stock Market ↔ Bonds & Interest Rates ↔ Currencies ↔ Commodities (Intermarket Analysis).
- USDX inversion, strength/weakness, undervalued/overvalued, short covering, futures contract correlations.
- ⚠️ **Для крипты почти неприменимо** — это межрыночный анализ forex/macro. Слабый аналог — DXY/risk-on корреляция, но без edge. Не переносим как детектор. Концептуальный takeaway: подтверждение через коррелированный инструмент (см. SMT в [[ICT-курс-month02-октябрь-rr-money-management-mean-threshold]]); у нас есть cross-asset BTC/ETH/SOL + confluence в 1.1.1.

## Month06 — ⭐ PD Arrays: полная иерархия Premium/Discount зон

Главная ценность всего курса: **ранжированный список institutional reference points (PD Arrays)** — от внешних к внутренним. ICT задаёт ПОРЯДОК приоритета зон.

**Для BULLISH (покупки, снизу вверх по мере захода цены в discount):**

1. Bullish Mitigation Block
2. Bullish Breaker
3. Liquidity Void
4. Fair Value Gap
5. Bullish Orderblock
6. Rejection Block
7. Old Low or High

**Для BEARISH (продажи, зеркально):**

1. Old High or Low
2. Rejection Block
3. Bearish Orderblock
4. Fair Value Gap
5. Liquidity Void
6. Bearish Breaker
7. Bearish Mitigation Block

Применяется по TF-каскаду: **Monthly → Weekly → Daily → 4Hour** (та же top-down иерархия из [[ICT-курс-month03-ноябрь-выбор-таймфрейма-top-down]]).

## ⚡ Сопоставление PD Arrays с нашими 11 элементами smc-lib

| ICT PD Array | Наш аналог | Статус |
|---|---|---|
| Orderblock | ob | ✅ есть |
| Fair Value Gap | fvg | ✅ есть |
| Liquidity Void | (часть неэффективности) | ≈ родственно [[три класса зон ликвидность эффективность неэффективность]] |
| Rejection Block | — | ❌ нет (новый кандидат) |
| Breaker | — | ❌ нет (кандидат, см. [[SMC-обзор-OB-breaker-BOS-choch-vs-price-action]]) |
| Mitigation Block | — | ❌ нет (кандидат, см. [[ICT-курс-month04-декабрь-orderblock-canon-liquidity-bias-mitigation-block]]) |
| Old High/Low (liquidity) | fractal / ob_liq | ≈ частично |

**Rejection Block** ⚡НОВОЕ — ещё один элемент, которого у нас нет (зона, где цена резко отвергла уровень длинными тенями; отличается от OB телом/тенью).

## Выводы для проекта

- **PD Arrays = готовая иерархия приоритета зон.** У нас зоны конкурируют через empirical calibrator (hit-rate по бакетам, [[traid-bot-ml-pivot]]) — это эмпирический аналог ICT-ранжирования. Можно сверить: совпадает ли наш data-driven приоритет с ICT-ручным (Mitigation/Breaker сверху, Old High/Low снизу для bullish)?
- **3 недостающих элемента** к нашим 11: **Rejection Block, Breaker, Mitigation Block**. Все три — кандидаты в smc-lib (12-й, 13-й, 14-й типы зон после ob_vc).
- **Intermarket (Month05)** — не переносим в крипту.

Предыдущий: [[ICT-курс-month04-декабрь-orderblock-canon-liquidity-bias-mitigation-block]]. Следующий: [[ICT-курс-month07-март]]. Каталог: [[ICT-source-индекс]].
