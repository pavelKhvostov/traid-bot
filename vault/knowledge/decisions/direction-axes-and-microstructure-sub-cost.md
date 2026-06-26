---
tags: [decision, direction, coin, cross-asset, funding, order-flow, microstructure, cost-floor]
date: 2026-06-25
---

# Направление: экзогенные оси = coin, микроструктура реальна но ≤ cost-floor (слой ликвидности)

## Контекст
Юзер: можно ли улучшить предсказание НАПРАВЛЕНИЯ не индикатором, а классом данных? Затем: «боты→инфа в OHLCV, проверь дыры контролей».
`research/direction_axes/`. Стены: own-AR baseline + block-OOS + permutation-null + год + cross-asset + net-cost.

## Оси ортогональные цене — ВСЕ KILL для направления
- **Cross-asset lead-lag** (ETH/SOL/USDT.D/TOTALES/BTC1!): дневка cross над own-AR **−0.028**, OOS<монетки, null p=0.82; интрадей ~52% = собств. микро-AR BTC (cross-only≈own, прибавка +0.001); ETH/SOL = синхронные дубли. Гипотеза «USDT.D↑→BTC↓» обратная, не извлекается OOS.
- **Funding** (Binance fapi, 7100×8h): над own-AR −0.011, null p=0.71. Перегрев шортов→отскок описательно, но односторонне+спутано с дрейфом, не OOS, не cross.
- **Signed order flow** (taker delta/CVD): над own-AR +0.005, null p=0.000, год-стаб → сигнал ЕСТЬ, но per-bar +0.007% ≪ интрадей-косты (~0.08% RT) → экономически мёртв.
- Data-blocked: OI(эндпоинт 30д), ликвидации, on-chain.
**Глубокая причина:** оси не ортогональны — ETH/SOL/funding/flow суть ФУНКЦИИ цены; после контроля на own-AR дают ≈0.

## Самокритика контролей → микроструктура (rich-OHLCV)
Признаны 2 дыры (false-negative): (1) все direction-тесты были ≥1h; (2) бедность фич. Патч `micro_direction.py`+`micro_threshold.py`:
rich-OHLCV (геометрия бара+объём+bar-rule flow) → знак BTC[t+1] на 5m/15m, purged walk-forward, CatBoost, two-cost.
- **НАЙДЕН реальный сигнал, который ≥1h прятал:** 15m acc **0.534**, топ-conviction (top-1%) **0.6145**, null p=0.000, год-стабильно.
- НО flow над price-geometry **+0.0003** (бот-«поток» в bar-rule форме НЕ помог; сигнал в форме свечи).
- **Экономика убивает:** gross 0.38bps/бар ≪ даже maker 2bps RT. Conviction-фильтр: топ-1-2% переходят maker лишь **+0.1…+0.37bps**, но adverse-selection на maker directional-fill инвертирует edge (наливают когда неправ). 5m деградирует по годам (рост эффективности).

## Решение / уточнённая стена
**Направление предсказуемо в OHLCV до ~61% на топ-conviction, НО edge ≤ транзакционного пола → принадлежит слою ЛИКВИДНОСТИ
(MM rebate+спред+колокация), не слою сигнала.** Для нас (тейкер / наивный maker) = net-ноль-или-минус. «Монетка» = точнее «coin
для нас как агрессоров на горизонтах ≥1h; суб-минутка/maker — недоступны». Capital → магнитуда/режим/сайзинг/кондишн-экстремумы, НЕ предсказание направления. Это рефреймит и **усиливает** прежние kill'ы (см. [[fractal-5pct-first-passage-direction-is-coin-self-correcting-module]]).

## Мета-урок про контроли
Раньше боялся только false-POSITIVE (миражи). Юзер указал на false-NEGATIVE: горизонт + бедность фич могут прятать реальный сигнал.
Правило: при «X не предсказывает» проверять и горизонт (суб-час), и богатый фичесет, и maker-косты — иначе ложный отрицательный.

## Связи
[[magnituda-reversal-strategy]] · [[ta-coverage-gap-analysis]] · [[magnitude-is-predictable-cats-dogs-but-edge-is-vol-persistence]]
