---
type: index
tags: [ict, smc, external, index]
ingested: 2026-06-10
---

# Индекс внешних ICT / Smart Money источников

Конспекты внешних PDF-материалов по ICT (Inner Circle Trader, Michael J. Huddleston) и SMC. Сложены сюда в ходе разбора `~/Downloads` (10 июня 2026). Конвенция: 1 источник = 1 заметка; схожие по теме сливаются в одну. Всё прогонять через [[7-criteria-of-good-strategy]] и [[known-pitfalls]] перед применением.

## Обзорные / методология
- [[ICT-методология-7-концептов-и-liquidity-sweep]] — `ICT-Trading-Strategy-1.pdf` (12 стр). 7 концептов (Liquidity, Displacement, MSS, Inducement, FVG, OTE, BPR) + сетап Liquidity Sweep.

## Курс ICT Study Notes (помесячно, 2016–2017)

Полный годовой менторшип ICT (Sep 2016 → Aug 2017), 12 месяцев. Дубли в Downloads: Month02 и Month07 имеют копии `(1)` — читается один.

- [[ICT-курс-month01-сентябрь-основы-price-action]] — Month01 (32 стр). 4 фазы рынка, IPDA, True Day 00:00–15:00 NY, Equilibrium/Premium/Discount, Liquidity Void, FVG, Judas Swing, swing=3 свечи (N=1).
- [[ICT-курс-month02-октябрь-rr-money-management-mean-threshold]] — Month02 (121 стр). R:R-математика, money management, **Mean Threshold = 50% OB = наш mid-entry**, market-maker traps (false flags/breakouts), анонс SMT divergence.
- [[ICT-курс-month03-ноябрь-выбор-таймфрейма-top-down]] — Month03 (71 стр). TF↔тип трейдера (Monthly/Weekly/Daily/4H), top-down анализ — методологическое обоснование нашего multi-TF каскада.
- [[ICT-курс-month04-декабрь-orderblock-canon-liquidity-bias-mitigation-block]] — Month04 (105 стр). ⭐Каноничный OB (max body range + near support), External/Internal range liquidity, Liquidity-Based Bias (top-down matrix), **Mitigation Block** (новый детектор). Interest Rate Triads (forex-only, не переносим).
- [[ICT-курс-month05-06-intermarket-и-PD-arrays-иерархия-зон]] — Month05-06 (147+92 стр). Intermarket (forex, не переносим) + ⭐**PD Arrays** — ранжированная иерархия зон (Mitigation/Breaker/Void/FVG/OB/Rejection/Old H-L). Новые: Rejection Block, Breaker.
- [[ICT-курс-month07-08-09-time-price-killzones-weekly-profile-accumulation]] — Month07-09 (133+85+106 стр). Time & Price, каскад до **1H execution**, недельный профиль (low-of-week Mon-Wed), PD Array Matrix, OB size filter, Accumulation/Distribution фазы.
- [[ICT-курс-month10-11-12-open-interest-cot-smt-итоговый-pipeline]] — Month10-12 (201+52+101 стр). Open Interest, **SMT divergence**, COT, Fundamental Screen (forex), ⭐итоговый decision pipeline. Финал курса.

## Прочее (обзоры, 2022-модель, код, дельта)

- [[SMC-обзор-OB-breaker-BOS-choch-vs-price-action]] — `Smart-Money-Concept-trading-strategy-PDF.pdf` (11 стр). OB, **Breaker Blocks**, BOS vs **CHoCH**, mitigation blocks, SMC vs Price Action + критика.
- [[ICT-2022-mentorship-пошаговый-entry-алгоритм-DOL-MSS-displacement]] — scribd 2022 ICT Mentorship (38 стр). ⭐Операционный entry-алгоритм: Weekly bias → Daily **DOL** → 4H framework → 15m **MSS/BOS+displacement** → FVG-вход → 5m. **DOL = наше Правило 8**.
- [[medium-fvg-python-детектор-сверка-с-нашим]] — Medium Ziad Francis (8 стр). Рабочий **Python FVG-детектор**; ключевое — **body_multiplier фильтр** (middle_body > avg×1.5). Action: сверить с `smc-lib/fvg`.
- [[ICT-gatietrades-core-content-дельта-к-курсу]] — scribd GatieTrades (135 стр). Пересказ курса M1-12 (дубль). Дельта: **OTE core = 62-70%**, "One Shot One Kill" (breaker/mitigation entry).

## Новые кандидаты-детекторы, всплывшие из ICT/SMC источников

Сводка — что есть в источниках, но НЕ оформлено у нас отдельным детектором (приоритет проверки сверху вниз — дешевле к дороже):

- **SMT divergence** BTC/ETH/SOL — cross-asset расхождение на хаях/лоях (дёшево на наших данных)
- **Displacement / body_multiplier фильтр** перед FVG — 2 независимых источника (Medium + ICT-2022)
- **DOL (Draw On Liquidity)** как target-селектор — = Правило 8 prediction-algo
- **Mitigation Block** — зона закрытия убытка → разворот (ABC-логика)
- **Breaker Block** — пробитый OB
- **Rejection Block** — резкое отвержение уровня длинными тенями
- **OTE** — Fibonacci-вход 62-70% (core) / 61.8-78.6% (широкий)
- **CHoCH** как именованный элемент разворота
- **Day-of-week / weekly profile** — low-of-week в Mon-Wed (Time-фильтр)
- **Inducement** — stop-hunt пики мини-контртрендов
- **Balanced Price Range** — два встречных FVG
- **Liquidity Sweep single-candle** как фильтр входа
- **Accumulation/Distribution фазы** ↔ Money Hands ([[money-hands-asvk]])
- **Futures OI / funding** как confluence (дорого — новый data source)

---
Связь с каноном проекта: [[универсальные определения OB и FVG]], [[три класса зон ликвидность эффективность неэффективность]], [[фракталы билла уильямса]], [[smc-lib-as-canonical-source]].
