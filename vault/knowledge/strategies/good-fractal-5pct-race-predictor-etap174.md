---
tags: [strategy, reversal, fractal, ml, prediction]
date: 2026-06-10
status: research-baseline
related: [research/elements_study/etap_174_predict_good_fractal_5pct_race.py]
---

# Предсказатель «хорошего» фрактала-разворота на close (5% race) — etap_174

## Задача

На close КАЖДОЙ 12h-свечи i (СТРОГО до подтверждения фрактала — N=2 = +2 бара)
предсказать, станет ли свеча **«хорошим» фракталом-разворотом**, и сделать это сигналом.

## Определение метки (гонка двух событий)

- **LOW-фрактал (LONG):** ХОРОШИЙ, если `high` достиг `close[i]×1.05` **раньше**, чем `low` ушёл ниже `low[i]`. Иначе плохой.
- **HIGH-фрактал (SHORT):** ХОРОШИЙ, если `low` достиг `close[i]×0.95` **раньше**, чем `high` ушёл выше `high[i]`. Иначе плохой.
- Гонка по внутрибарным **1h** high/low, старт с `close_time[i]`. Горизонт 30 дней (не дождались → плохой). При одновременном касании в одном 1h-баре — стоп считается сработавшим раньше (anti-optimism).

## Защита от lookahead (применены known-pitfalls)

См. docstring скрипта. Ключевое: все фичи ≤ close[i]; фрактал-факт (i+1,i+2) — ТОЛЬКО диагностика, НЕ фича; HTF-тренд по last-closed бару; гонка с close_time[i], не с open[i]; гонка по реальным 1h-барам (не instant-fill); time-split + embargo.

**Sanity-чек пройден:** при перемешивании метки в train AUC падает до **0.51** (≈случайность) → утечки через фичи НЕТ. Реальный AUC 0.68 — не артефакт. (Это и есть проверка «WR>60% = подозрение»: настоящий edge выживает только с настоящими метками.)

## Результаты (BTCUSDT, 2022-04 → 2026-06, OOS test 2025+)

**Baseline (доля хороших среди ВСЕХ свечей):** LOW 21.3%, HIGH 18.4%.

**Сверка (среди РЕАЛЬНЫХ фракталов):** FL хороших **50.8%** (413 шт), FH хороших **40.6%** (416 шт). → Даже идеально зная, что свеча — фрактал, лишь ~половина даёт 5% раньше снятия. Это потолок сложности.

**Модель LightGBM (time-split, train<2025-01-01, test после embargo):**

| Цель | base_test | AUC | prec@0.5 (lift) | prec@0.8 (lift) |
| --- | --- | --- | --- | --- |
| **LOW→+5% (LONG)** | 17.8% | **0.676** | 0.335 (×1.89) | 0.326 (×1.84) |
| **HIGH→-5% (SHORT)** | 20.9% | 0.642 | 0.297 (×1.42) | **0.524 (×2.51)** |

**Топ-фичи:** `ema_dist_pct`, `atr_pct`, `close_in_range`, `hull_dist_pct`, `dist_ll30_pct`, `rsi`, `vol_z`, `ret_7`. → «растянутость от средних + позиция закрытия в диапазоне + дистанция до 30-bar экстремума».

## Честная оценка

- **Реальный, но умеренный edge.** Lift ×1.8-2.5 OOS, без lookahead (доказано sanity-чеком).
- **SHORT при высоком пороге (prob≥0.8) = precision 0.52, lift ×2.5** — самый сильный режим. Согласуется с эмпирикой проекта «SHORT сильнее на ~6pp» ([[reversal-3candle-fractal-prediction]], [[traid-bot-ml-pivot]]).
- **Как сигнал «в лоб» ещё сыро** (precision 33% для LONG = 2 из 3 ложных). Лучшее применение: **фильтр/confluence** к существующим зонам, либо высокопороговый SHORT-сигнал.

## Как улучшать (следующие шаги)

1. Добавить **зональные фичи** (расстояния до OB/FVG на 1d/12h/4h — как в [[reversal-3candle-fractal-prediction]] и etap_170): там precision доходил до 62-64% именно с зонами-confluence.
2. Добавить **Bulkowski-паттерны** ([[bulkowski-reversal-detectors-btc-12h-baseline]], etap_172) и **Money Hands** фичи ([[money-hands-asvk]]).
3. **SADF/CUSUM режим-фича** (крипто-пузыри — из López de Prado, [[adv-fin-ml-индекс]]) — режим разворота зависит от bubble-фазы.
4. Проверить на **ETH/SOL** (BTC-оптимум ≠ universal, [[traid-bot-empirical-laws]]).
5. **Meta-labeling** ([[adv-fin-ml-lec2-4-bars-labeling-purged-kfold]]): этот предсказатель как вторичная модель поверх первичного «свеча — кандидат в фрактал».
6. Сравнить метку «от close» vs «от low[i]» (вторая ближе к движению от дна).

## Развитие: etap_175 (+sweep +zones +Bulkowski +нейросеть)

Добавлены фичи из подхода Андрея на ТУ ЖЕ метку 5%-race: sweep-история ликвидности (sweep_SSL/BSL_mag/failed — это ICT Liquidity Sweep / DOL из внешних PDF), OB/FVG-дистанции, Bulkowski top-5 fires (big_w/db_eve_eve/v_bottom/hs_bottom/big_m из etap_172, lookahead-safe). Плюс сравнение LightGBM vs нейросеть (MLP).

**Результаты (OOS, sanity-чисто 0.46-0.50):**

| Версия | LOW AUC | LOW prec@0.8 | HIGH AUC | HIGH prec@0.8 |
| --- | --- | --- | --- | --- |
| etap_174 (база, 22 фичи) | 0.676 | 0.33 (×1.84) | 0.642 | 0.52 (×2.51) |
| etap_175 +sweep+zones (52) | 0.667 | 0.40 (×2.25) | 0.650 | 0.39 |
| etap_175 +Bulkowski (62) | 0.639 | 0.38 (×2.15) | 0.660 | 0.50 (×2.39) |

**Ключевые выводы:**

1. **Фичи Андрея НЕ дали его 62-64% precision — потому что разница в МЕТКЕ, не в фичах.** Метка Андрея «фрактал + движение ≥X% за N баров» (AUC 0.94) мягче моей метки «5% РАНЬШЕ снятия экстремума» (встроенный честный SL). Половина настоящих фракталов снимается до +5% (сверка: FL 50.8%, FH 40.6% хороших). Потолок AUC честной 5%-race ≈ 0.65-0.68 — и это не баг, а цена честности.
2. **Нейросеть (MLP) стабильно НЕ лучше LightGBM** на табличных фин-фичах (López de Prado прав, [[neural-networks-nielsen-backprop-reference]]). MLP иногда даёт высокий precision на 5-18 сигналах — статистически пусто.
3. **Sweep-фичи и Bulkowski вошли в топ-importance** (sweep_mag, bulk_big_w_bars_since), но прироста AUC не дали — потолок метки.
4. **Рабочий режим:** SHORT при prob≥0.8 → precision ~0.50, lift ×2.4-2.5 стабильно во всех версиях. Редкий (18-23/год), но реальный сигнал.

**Что осталось непробовано (если возвращаться):** полный стек Андрея с 1m-данными (Vadim maxV sniper ~93% но 5 сигналов/год), Money Hands фичи, SADF-режим, ETH/SOL. Но честный вывод: при метке «5%-race» потолок ~0.65 AUC; для высокого precision нужна либо мягче метка (как у Андрея), либо узкий редкий сигнал (Vadim sniper).

Скрипты: [research/elements_study/etap_174_predict_good_fractal_5pct_race.py](../../../research/elements_study/etap_174_predict_good_fractal_5pct_race.py), [etap_175_fractal_5pct_sweep_nn.py](../../../research/elements_study/etap_175_fractal_5pct_sweep_nn.py).

## Связь

[[reversal-3candle-fractal-prediction]] (предыдущий подход, precision 62-64% с зонами), [[bulkowski-reversal-detectors-btc-12h-baseline]], [[фракталы билла уильямса]] (канон N=2), [[traid-bot-ml-pivot]], [[traid-bot-empirical-laws]] (lookahead-законы).
