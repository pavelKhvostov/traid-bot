---
type: external-source
source_file: Month01-September_ICT_Notes.pdf
source_pages: 32
course: "ICT Monthly Mentorship 2016-2017"
month: "01 / Сентябрь 2016"
author: "Michael J. Huddleston (ICT)"
ingested: 2026-06-10
tags: [ict, smc, course, price-action, external]
---

# ICT-курс · Month 01 (сентябрь 2016) — основы Price Action

Первый месяц 12-месячного менторшипа ICT. Закладывает фундамент: язык рынка через призму IPDA (Interbank Price Delivery Algorithm). Цель месяца — «no fear of missing setups: они формируются ежедневно для трейдера с институциональным мышлением».

## Каркас сетапа (Elements To A Trade Setup)

**A. Контекст / фреймворк** — 4 фазы рынка, привязаны к сессиям:

1. **Expansion** = Judas Swing — цена быстро уходит от Equilibrium → ищем **Orderblock** у equilibrium.
2. **Retracement** = New York Session — цена возвращается внутрь недавнего диапазона → ищем **Fair Value Gaps / Liquidity Voids**.
3. **Reversal** = London Swing — разворот после снятия стопов → ищем **Liquidity Pools** над старым хаем / под старым лоем.
4. **Consolidation** = Asian Range — диапазон, заявки копятся с обеих сторон → ищем импульс от **Equilibrium** (ровно середина диапазона).

**B. Reference points в institutional order flow:** Orderblocks · Fair Value Gaps & Liquidity Voids · Liquidity Pools & Stop Runs · Equilibrium.

## Ключевые понятия

- **IPDA** — Interbank Price Delivery Algorithm: алгоритм, поставляющий цену банкам/институционалам. Структура daily range: equilibrium → manipulation → expansion → reversal → retracement → consolidation.
- **True Day / Daily Range** — IPDA задаёт дневной диапазон между **00:00 и 15:00 по Нью-Йорку**. Вне этого окна — «dead time», менее предсказуемо. ⚡ВАЖНО для нас: подтверждает идею временны́х окон (у нас всё в UTC; NY-сессия = понятие, которого в проекте нет, но может быть фильтром).
- **Equilibrium / Premium / Discount** — после движения вверх и ретрейса: ниже 50% хода = **Discount** (идеальные покупки); после движения вниз и ретрейса: выше 50% = **Premium** (идеальные продажи). 50% = equilibrium. → Это ровно Fibonacci-50% логика; родственно OTE из [[ICT-методология-7-концептов-и-liquidity-sweep]].
- **Liquidity Void** — после резкого хода крупные свечи = наименее эффективно проторгованный участок, «порозная» price action, стремится заполниться позже. = наша **неэффективность** ([[три класса зон ликвидность эффективность неэффективность]]).
- **Fair Valuation** — возврат цены к недавним уровням; Smart Money разгружает лонги / открывает шорты. Хорошее место для тейк-профита без выхода за диапазон.
- **Fair Value Gap (FVG)** — небольшой однонаправленный участок при уходе с уровня; аналог «Common Gap» из классического ТА. Может быть целью для прибыли ИЛИ новым сетапом. Сверка: [[что такое fvg]].
- **Low Resistance Liquidity Run** — у цены мало сопротивления на пути к ликвидности (под старым хаем / над старым лоем); резкий сёрдж, часто на выходе новостей. High-prob сетапы строятся на том, что путь к очевидным liquidity pools свободен.
- **Market Protraction (Judas Swing)** — в определённое время дня внезапный ход ПРОТИВ направления дневного диапазона; микро-экспансия, снимает ближнюю ликвидность и разворачивается.

## What To Focus On (чек-лист элементов на графике)

- **Old Highs** → Buy Stops (buy-side liquidity); **Old Lows** → Sell Stops (sell-side).
- **Clean Highs/Lows** → liquidity pool стопов.
- **Sharp Runs** → Liquidity Voids.
- **Swing High** — 3-свечной паттерн, центральная вверх; **Swing Low** — 3-свечной, центральная вниз. ⚡= наш фрактал N=1 (у нас Williams N=2, см. [[фракталы билла уильямса]]). У ICT swing = 3-свечной (N=1) — отличие!

## Выводы для проекта

- **Совпадает с нашим каноном:** Liquidity Void = неэффективность; FVG; equilibrium-50%; OB у equilibrium; liquidity на старых хаях/лоях.
- **Отличия/новое:** (1) **Swing = 3 свечи (N=1)** у ICT vs наш Williams-фрактал **N=2** — разные определения swing-точек, важно при сравнении детекторов. (2) **True Day окно 00:00–15:00 NY** — временной фильтр, которого у нас нет (мы 24/7 крипта; но идея «dead time» может проверяться). (3) **Premium/Discount как формализация направления сделки** (только покупки в discount, только продажи в premium) — потенциальный фильтр поверх каскадов.
- **Осторожно:** материал про FOREX и сессии; крипта торгуется 24/7 — прямой перенос сессий и True Day требует проверки. Это методология/нарратив, не статистика → гонять через [[7-criteria-of-good-strategy]].

Следующий месяц: [[ICT-курс-month02-октябрь]]. Каталог: [[ICT-source-индекс]].
