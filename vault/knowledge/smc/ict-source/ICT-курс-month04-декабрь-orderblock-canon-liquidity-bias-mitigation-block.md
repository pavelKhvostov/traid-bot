---
type: external-source
source_file: Month04-december_study_notes.pdf
source_pages: 105
course: "ICT Monthly Mentorship 2016-2017"
month: "04 / Декабрь 2016"
author: "Michael J. Huddleston (ICT)"
ingested: 2026-06-10
tags: [ict, smc, course, orderblock, liquidity, external]
---

# ICT-курс · Month 04 (декабрь 2016) — каноничный Orderblock, Liquidity Bias, Mitigation Block

Самый технически плотный из ранних месяцев. Три ценные вещи: **точное определение OB**, **External/Internal Range Liquidity**, **Liquidity-Based Bias** + новый элемент **Mitigation Block**.

## ⚡ Каноничное определение Orderblock (сверка с нашим)

**Bullish Orderblock (по ICT):**
- **Definition:** самая нижняя свеча с **закрытием вниз (down close)**, имеющая **наибольший range open→close**, рядом с уровнем «support».
- **Validation:** когда High этой нижней down-close свечи пробивается позже сформированной свечой.
- **Entry:** цена ушла вверх от OB и **вернулась к High свечи OB** → бычий вход.
- **Risk (SL):** Low бычьего OB = относительно безопасный стоп. После ухода цены — подтянуть стоп чуть ниже **50% range орблока** (= Mean Threshold из [[ICT-курс-month02-октябрь-rr-money-management-mean-threshold]]).

🔗 **Сверка с нашим каноном** [[универсальные определения OB и FVG]] / [[что такое order block]]: совпадает по сути (последняя противоположная свеча перед импульсом, валидация пробоем, вход на возврате). Нюанс ICT: акцент на **«наибольший range open→close»** среди кандидатов и **«near support»** — у нас OB берётся как последняя противоположная свеча; критерий «max body range» у нас не основной. Стоит свериться, не теряем ли мы лучший OB при множественных кандидатах. SL = Low OB совпадает с нашим sl=max(15%·OB, 1%) по смыслу (стоп за зону).

## External vs Internal Range Liquidity (новая классификация)

- **External Range Liquidity** — ВНЕ текущего диапазона: Buy Side над хаем, Sell Side под лоем. Раны на ликвидность бывают **Low Resistance** или **High Resistance**.
- **Internal Range Liquidity** — ВНУТРИ диапазона: Liquidity Voids и FVG, которые заполнятся (gap risk); орблоки внутри range набираются новыми заявками.
- 🔗 Полезная рамка: наши зоны делятся на «внутри vs снаружи range» — помогает понимать, цена тянется наружу (к стопам) или внутрь (к FVG). Родственно Правилу 8 prediction-algo (магнит ликвидность↔неэффективность, [[traid-bot-ml-pivot]]).

## Liquidity-Based Bias (top-down bias matrix) ⚡

Если Monthly+Weekly+Daily все **Bearish** → интрадей 4H и ниже **корректируется вверх** в **Premium**, ищет Buy Side Liquidity чтобы продать. Шорты на: protective buy-stop raids / возврат к bearish OB или FVG / заполнение Liquidity Void → Low Resistance Liquidity Run вниз под недавний лой. (Bullish — зеркально: discount, sell-side, лонги.)

🔗 = формализованный **pro-trend + premium/discount** фильтр. Ровно наша логика: HTF тренд задаёт сторону, вход — на ретрейсе в зону против интрадей-движения. Совпадает с C2 pro-trend ([[strategy-c2-ob-6h-fvg-2h-pro-rr1]]) и тренд-фильтром Hull ([[c2-ema-or-hull6h-trend-filter-winner]]).

## Mitigation Block (новый элемент) ⚡НОВОЕ

ABC-логика: цена идёт A→B (лонги), падает B→C (слом структуры вниз, MSS). Когда цена **возвращается к точке A**, лонги, набранные A→B, получают шанс **«митигировать» убыток** от падения B→C → может дать новые более низкие свинги к C или ниже. **Mitigation Block** = зона, где институционал закрывает убыточную позицию в безубыток, разворачивая цену.

🔗 Отличие от Order Block: OB = зона исходного входа Smart Money; **Mitigation Block = зона закрытия убыточной позиции** (после слома структуры). У нас как отдельный детектор НЕ оформлен. Кандидат — родственен Breaker Block из [[SMC-обзор-OB-breaker-BOS-choch-vs-price-action]] (часто их путают/объединяют). Митигация у нас уже центральна как механика first-touch ([[zone-mitigation-filter-required]]), но «mitigation block как точка разворота» — другое.

## Interest Rate Triads (forex-специфика, для нас неприменимо)

30Y Bond / 10Y Note / 5Y Note overlay → подтверждение accumulation/distribution Smart Money через USDX. ⚠️ Чисто forex/макро — **для крипты неприменимо** (нет прямого аналога; разве что DXY-корреляция, но это слабо). Не переносим.

## Выводы для проекта

- **Свериться:** наш OB-детектор vs ICT-критерий «max body range + near support» при множественных кандидатах ([[универсальные определения OB и FVG]]).
- **Новые кандидаты-детекторы:** **Mitigation Block** (ABC, зона закрытия убытка → разворот), **External/Internal range liquidity** классификация зон.
- **Подтверждает:** Mean Threshold = SL-подтяжка к 50% OB; Liquidity-Based Bias = наш pro-trend + premium/discount.
- **Не переносим:** Interest Rate Triads (forex-only).

Предыдущий: [[ICT-курс-month03-ноябрь-выбор-таймфрейма-top-down]]. Следующий: [[ICT-курс-month05-январь]]. Каталог: [[ICT-source-индекс]].
