---
type: external-source
source_file: "screencapture-ru-scribd-document-672495924-2022-ICT-Mentorship-Notes-Public.pdf"
source_pages: 38
author: "ICT 2022 Mentorship (community notes, Hasbulah)"
ingested: 2026-06-10
tags: [ict, smc, entry-model, external]
---

# ICT 2022 Mentorship — пошаговый entry-алгоритм (DOL, MSS, displacement)

Конспект community-заметок ICT 2022 Mentorship. В отличие от курса 2016-17 ([[ICT-source-индекс]]), 2022-версия даёт **конкретный исполняемый алгоритм входа** — top-down с явными шагами и TF. Самое операционное из всей ICT-пачки.

## Эпизоды 1-2: майндсет + Weekly bias

- **Independent mindset, backtest×3** — проверяй всё сам, делай домашку, бэктести.
- **Weekly bias:** перед началом недели — что сделает следующая недельная свеча (выше/ниже)? К чему тянется (imbalance выше / liquidity pool ниже)? Факторы недельной свечи: seasonal tendencies, interest rates, earnings seasons, price action W/D.

## ⭐ Пошаговый top-down entry-алгоритм (ядро)

1. **Weekly** → установить **weekly bias** (bullish/bearish).
2. **Daily (Long Term)** → где мы в range (расширяется выше/ниже). Если bearish по weekly — под short-term low'ами лежат stops (liquidity). Определить **DOL (Draw On Liquidity)** — куда тянется цена:
   - **DOL = либо (1) liquidity pool, либо (2) imbalance.**
   - Smart money смотрит old highs / old lows; ликвидность ищется на equal highs / equal lows.
   - **«Основная масса анализа — на Daily.»** Daily даёт фидбэк каждые 24ч по weekly-свече. Любое значимое движение = stop-hunt или снятие short-term high/low. «Market constantly engineers liquidity.»
3. **4 Hour (framework)** → с bias + DOL строим framework. Когда алгоритм (PDA) снял induced liquidity и двинул рынок выше/ниже — спускаемся на LTF за входом.
4. **15 minute (intermediate)** → дождаться **MSS или BOS с displacement** → искать **FVG**. Измерить displacement range фибой; FVG формируются в этом range (15m→1m).
   - **Лонг:** покупать в **discount** displacement-range (fib снизу range к топу).
   - **Шорт:** продавать в **premium** (fib сверху range к низу).
   - **Вход:** limit-ордер в FVG. **SL:** под свечой, создавшей FVG.
   - **Target:** FVG + ликвидность (предыдущие highs/lows). Правило: **«target the low-hanging fruit first»** (ближняя ликвидность первой).
5. **5 minute (short-term)** → дальнейшее уточнение.

## ⚡ Сопоставление с нашим проектом

- **DOL (Draw On Liquidity)** ⚡ — мощная рамка: цель цены = либо liquidity pool, либо imbalance. Это РОВНО Правило 8 prediction-algo (магнит между ⛽liquidity и 🧲inefficiency, [[traid-bot-ml-pivot]]). ICT formaлизует то же самое как DOL. Сильное подтверждение нашего направления.
- **MSS/BOS + displacement → FVG entry** = наш каскад «подтверждение → FVG-вход». У нас confirm на 1h ([[три типа подтверждения 1h ob fvg rdrb]]); ICT 2022 confirm на 15m с displacement. **Displacement-фильтр** (сильная свеча перед FVG) = тот же body_multiplier из [[medium-fvg-python-детектор-сверка-с-нашим]]. Сходятся два независимых источника → стоит проверить displacement-фильтр у нас.
- **Premium/Discount внутри displacement-range через fib** = OTE-логика; вход только в «правильной» половине. У нас mid-entry (50%); ICT уточняет — лонг строго в discount-половине. Кандидат: fib-zone вход вместо чистого mid.
- **«Low-hanging fruit first» (ближняя ликвидность = TP)** — у нас TP = next swing / RR-cap. Идея «ближняя ликвидность как первый таргет» близка к нашему floating-TP / частичной фиксации.

## Action items

- ☐ **Displacement-фильтр перед FVG** (сильная свеча) — сверить/проверить (совпадает с Medium body_multiplier).
- ☐ **DOL как явная цель** — формализовать «liquidity pool vs imbalance» как target-селектор (perekликается с prediction-algo Правилом 8).
- ☐ **Fib premium/discount вход** внутри displacement-range vs наш mid-entry — эксперимент.

⚠️ Forex-ориентировано (earnings/interest rates как факторы weekly). Крипта 24/7 — проверять. Нарратив без статистики → [[7-criteria-of-good-strategy]].

Каталог: [[ICT-source-индекс]]. Связь: [[traid-bot-ml-pivot]] (Правило 8 / DOL), [[medium-fvg-python-детектор-сверка-с-нашим]] (displacement-фильтр).
