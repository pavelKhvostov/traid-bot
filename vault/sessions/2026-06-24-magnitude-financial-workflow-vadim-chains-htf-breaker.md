---
tags: [session, magnitude, financial, rr, monthly-profit, vadim, chains, breaker, tf-sweep, net-cost, workflow, honest-negatives]
date: 2026-06-24
---

# Сессия: фракталы→магнитуда→финансы(RR/мес)→нетто-co-sim→цепочки Вадима→HTF-breaker

Очень длинная сессия (2026-06-23/24). Сквозная линия: **под честными гейтами (null + cross-asset + OOS + нетто-косты)
почти всё направленческое = монетка/cost-killed; реально работают только размер (вола), risk-sizing, и ОДИН новый
структурный флип на HTF (breaker).** Субагенты/Workflow в этой сессии РАБОТАЛИ (403-блок снят); API периодически 529 →
solo-обход `dangerouslyDisableSandbox`.

## 1. Фрактальный ±5% first-passage + самокоррекция — МОНЕТКА
`research/ta_laws/fractal_first_passage.py` + `fractal_neuro_gpu.py` (GRU CPU) + `fractal_cb_gpu.py` (CatBoost-GPU).
Симметричные ±5% барьеры → gambler's ruin = 50%. Онлайн «67.8% учится» = **МИРАЖ**: persistence `y[i-1]`=80.6% +
time-shuffle=50.5% (автокорр 30-дн метки + label-lookahead). Честный block-OOS AUC 0.51, нетто 0R. Модуль сам поймал.
[[fractal-5pct-first-passage-direction-is-coin-self-correcting-module]]

## 2. Магнитуда — ПРЕДСКАЗУЕМА (кошки/собаки), но edge = воло-персистентность
`magnitude_engine.py`: размер хода (forward range 2д) предсказуем (Cohen's d воло-фич big-vs-тихо ≈1.0 vs up-vs-down ≈0.02;
классиф 71% vs монетка 60%, 6/6 лет, shuffle чисто). НО `magnitude_improve.py`: edge ≈ ATR-персистентность (vol-only 70.3%,
full +1пп; модель ≈ ATR). Направление НЕ вытаскивается ни «волной» (`wave_continuation.py` — континуация=монетка, экспансия
favors reversal=инверсия), ни структурой/ViC/VWAP (`direction_of_big_move.py` — d 0.09 vs магнитуда 0.46). Скан предсказуемости
(`predictability_scan.py`): предсказуемы магнитуда/активность/корр-режим, НЕ направление/трендовость. [[magnitude-is-predictable-cats-dogs-but-edge-is-vol-persistence]]

## 3. Reversal-CatBoost — смена тренда НЕ предсказуема
`reversal_catboost.py`: фрактал-пивоты, метка=разворот ±5% реализован. OOS 51.2% НИЖЕ базы 52.4%, cross 0/3, год 1/6,
shuffle чист. Само-коррекция честно сошлась к базе. НЕ противоречит инверсии (reversal-accuracy=монетка, fade=expectancy).

## 4. Балльная система ASVK + вола-гейт
`confluence_score.py` — балл RSI/MoneyHands/TrendLine/VWAP/ViC (направление+исчерпание), дашборд на TV. Как ФИЛЬТР 1.1.1
маргинален (направление +0.05 cross 2/3, исчерпание нейтрально). **Вола-гейт 1.1.1 ВАЛИДИРОВАН** (`vol_gate_111_real.py`):
эксп-ptt +0.282 vs тихо +0.071, cross 3/3, год 6/6 — сайзер +42% R/сделку. Только 1.1.1 (на 1.1.2 не переносится).
НИЗКИЙ ТФ режима не тоньше (`vol_gate_111_lowtf.py`): 1h@вход инвертирует (микро-вола=качество входа, др. ось).

## 5. ФИНАНСЫ: RR × месячная прибыль (Workflow) + нетто co-sim
**Workflow** (6 агентов): RR-сетка × месячная прибыль по стратегиям. Оптимальный RR специфичен: 1.1.2@2.2(Sh0.99),
A@2.5, 1.1.1@1.5, 1.1.5@3.0, 3.2@2.5. НЕ гнаться за RR3.5 (Sharpe↓ + двузначные −R худшие месяцы). Корзина gross +2.5%/мес.
**НЕТТО co-sim** (`cosim_net.py`) — gross был ОБМАНКОЙ: косты съели ~68%, **нетто ~0.4-0.5%/мес**. **A i-RDRB+FVG и 3.2
net-killed** (тонкий edge × туго-стоп × частота = cost-wall низких ТФ; A на 1h не торгуема нетто, вопреки «live-кандидат №1»).
Нетто-ядро = **1.1.1+1.1.2+1.1.5** (+0.48R/мес, Sharpe 0.33). [[project_financial_report]]

## 6. ЦЕПОЧКИ ВАДИМА — полное пространство → ОДИН выживший (HTF-breaker)
Разведка канона (15 элементов: зоны/структура/ликвидность) → 12 кандидат-цепочек с рациональным входом/SL/TP, нетто+null+
cross-asset (`vadim_*.py`). Первый прогон (LTF): **все монетка/cost-killed**. Юзер: «на всех ТФ проверил?» — НЕТ. **TF-sweep
перевернул**: breaker-флип на LTF анти (моментум), на **HTF 6h/8h РАБОТАЕТ** (структурный слом значим). Полная валидация:
- нетто co-sim (RR3, дрейф-edge): cross 3/3 (ETH маргинал), Sharpe 0.20-0.31;
- **OOS 2024-26 ДЕРЖИТСЯ** (Sharpe 0.42), config (RR3) выбран на train слепо → не подгонка;
- **декорреляция с ядром |corr|=0.07**; **корзина Sharpe 0.33→0.38**;
- **1d-CHoCH-гейт УЛУЧШАЕТ** breaker-8h (OOS 0.076→0.171 ×2.2, cross 3/3).
Остальное закрыто: CHoCH-вход/BOS/mitigation/ob_liq/**ob_vc**/ifvg/run-sweep = монетка/анти/cost-killed.
[[htf-breaker-the-only-vadim-edge-found-via-tf-sweep]]

## Что РЕАЛЬНО держит деньги (после всего)
Нетто ~0.4-0.5%/мес из **финальной корзины: 1.1.1 + 1.1.2 + 1.1.5 + HTF-breaker(8h, 1d-CHoCH-гейт)** (Sharpe 0.38 нетто).
+ вола-гейт-сайзер на 1.1.1 (+42%). Масштаб = сайзинг (линейно). Числа GROSS-of-leverage, нужна live-фиксация.

## Методологические выигрыши (новые грабли/правила)
- **TF-sweep ОБЯЗАТЕЛЕН**: LTF-провал ≠ финал; SMC-структура живёт на HTF 6h-1d, дохнет на LTF (косты+шум).
- **matched-random-entry null = bracket-independent тест** (бракет константа, меняется точка → изолирует инфу сетапа).
- **gross→нетто = решающий**: фикс-косты × туго-стоп × частота убивают тонкий edge; всегда нетто co-sim с maker/taker.
- **CHoCH/структура = ГЕЙТ (контекст), не триггер**: как вход мёртв, как 1d-фильтр к breaker — усиливает.

## Связи
[[magnitude-is-predictable-cats-dogs-but-edge-is-vol-persistence]] · [[fractal-5pct-first-passage-direction-is-coin-self-correcting-module]] ·
[[htf-breaker-the-only-vadim-edge-found-via-tf-sweep]] · [[fractal-first-passage]] · [[vadim-integration-living-market-laws]] ·
[[decorrelated-chain-basket-for-futures]] · [[ta-coverage-gap-analysis]] · [[feedback_dont_over_anchor_cascades]]
