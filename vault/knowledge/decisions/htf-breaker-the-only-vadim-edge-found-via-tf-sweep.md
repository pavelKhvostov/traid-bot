---
tags: [decision, vadim, breaker, smc, tf-sweep, htf, oos, net-cost, basket, new-edge]
date: 2026-06-24
---

# HTF-breaker — единственный edge из канона Вадима (найден TF-sweep'ом); + нетто-реальность корзины

## Контекст
Задача: построить цепочки из блоков/уровней Вадима, найти кандидатов, проанализировать тремя этапами (рациональный
вход/SL/TP), нетто. Разведка канона (15 элементов): ЗОНЫ (OB/breaker/mitigation/ob_vc/FVG/iFVG/RDRB/iRDRB/marubozu),
СТРУКТУРА (CHoCH/BOS), ЛИКВИДНОСТЬ (fractal/ob_liq/RB). 12 кандидат-цепочек. Скрипты `research/financial/vadim_*.py`.

## Ключевой поворот: TF-sweep (юзер: «на всех ТФ проверил?»)
Первый прогон цепочек был на ФИКСИРОВАННЫХ (в осн. НИЗКИХ) ТФ → ВСЕ монетка/cost-killed → ложный вывод «пусто».
**Это был LTF-артефакт.** TF-sweep breaker-флипа по {1h..1d}: на LTF (1h/2h) **анти-предсказателен** (цена продолжает
пробой=моментум), на **HTF (6h/8h/1d) РАБОТАЕТ** (структурный слом значим → разворот-дрейф). Стена-урок: **edge SMC-фильтров
дохнет на LTF (косты+шум), живёт на HTF 12h-1d — ВСЕГДА TF-sweep, LTF-провал ≠ финал.**

## Валидация HTF-breaker (полная программа)
Вход = лимит в breaker-зону (флип), SL = ATR-based, TP = RR, нетто-косты (maker вход+TP, taker SL).
- **signed-return** на 6h/8h положителен, бьёт null 2/3 активов, год 6-7/7.
- **Нетто co-sim**: edge = направленный дрейф → живёт на **RR3** (широкая цель; RR2 слабый). cross-asset 3/3 (ETH маргинал),
  Sharpe 0.20-0.31 ≈ нетто-ядро (0.33).
- **OOS чистый** (`vadim_breaker_oos.py`): конфиг SL0.5/RR3 выбран ТОЛЬКО на train(2020-23), на test(2024-26) держится →
  **OOS-Sharpe 0.42, cross 3/3** → RR3 НЕ in-sample подгонка.
- **Декорреляция с ядром |corr|=0.07** (другой элемент); **корзина {ядро+breaker} Sharpe 0.33→0.38**, maxDD −7.4→−7.1.
- **1d-CHoCH-ГЕЙТ усиливает** (`vadim_grid_harness.py`): breaker-8h + CHoCH-1d бьёт baseline по всем (signed 0.088→0.125,
  OOS 0.076→0.171 ×2.2, grid→0.106, cross 3/3, n 634). 12h-гейт не помогает (близко к входу); селективен только 1d-гейт.
- per-trade нетто **+0.07-0.11R** (OOS +0.11).

## Что НЕ выжило (всё остальное Вадима)
CHoCH/BOS как ВХОД→OB = мёртв/немонотонен; mitigation = анти HTF; ob_liq = пусто все ТФ; ob_vc = 12h близко (cross 3/3
OOS+) но null_p 0.18 (signed не бьёт random) → не edge; iFVG/run-sweep = cost-killed. CHoCH **как 1d-ГЕЙТ** к breaker — работает
(структура = контекст/фильтр, не триггер; зоны = POI/цель — ровно роль из интеграции [[vadim-integration-living-market-laws]]).

## Решение
**Финальная корзина-кандидат: 1.1.1 + 1.1.2 + 1.1.5 + HTF-breaker(8h, 1d-CHoCH-гейт)** — Sharpe 0.38 нетто.
HTF-breaker = первый и единственный новый торгуемый edge из всей ветки Вадима. Кавеаты: favorable конфиг SL0.5/RR3
(дрейф-edge, RR3-зависим, ETH-слабый); bar-resolution SL/TP; нужен live-фикс + maker-исполнение.

## Связи
[[magnitude-is-predictable-cats-dogs-but-edge-is-vol-persistence]] (вола-гейт-сайзер 1.1.1) ·
[[vadim-integration-living-market-laws]] · [[decorrelated-chain-basket-for-futures]] · [[cascade-grid-64-cross-asset-robust-shortlist]] ·
[[fractal-5pct-first-passage-direction-is-coin-self-correcting-module]] (направление=монетка стена).
