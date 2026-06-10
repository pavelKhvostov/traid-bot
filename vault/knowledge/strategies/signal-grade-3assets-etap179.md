---
tags: [strategy, ml, neural-net, signal-quality, ordinal, pavel, live]
date: 2026-06-11
status: live
branch: pavel
related: [research/elements_study/etap_179_signal_grade_3assets_mda.py, neural_signals_live.py, neural_bot.py]
---

# Оценка сигналов 1-5 на 3 активах + фракталы Андрея + MDA (pavel) — etap_179

## Что это

Развитие [[signal-grade-1to5-ordinal-nn-etap178]]: оценка качества сигналов 1-5 нейросетью, но на **5 источниках сигналов × 3 активах** (BTC+ETH+SOL pooled) + MDA feature importance. **Запущено в live-бота** @test_neyro_traid_bot.

## Источники сигналов (5)

1. **1.1.1** (strategy_id=0), **1.1.2** (1), **1.1.3** (2) — каскады OB+FVG
2. **Фракталы Андрея** (3) — Williams N=2 развороты на 12h (вход на close подтверждения i+N, lookahead-safe)
3. **1.1.4 Extended-7** (4) — с EMA-фильтром (WR 67% в vault)

5574 сигнала (BTC 2028, ETH 1968, SOL 1924), метка = гонка TP(2.2R) vs SL по 1m, класс 1-5.

## Результаты (OOS test 2025+)

**WR по TP=2.2R baseline: 31.6%.** По стратегиям:

| Стратегия | n | WR_TP (grade≥4) | mean R |
| --- | --- | --- | --- |
| 1.1.4 | 677 | **37%** | 6.62 |
| 1.1.1 | 535 | 36% | 4.59 |
| 1.1.3 | 399 | 34% | 3.53 |
| 1.1.2 | 1564 | 30% | 4.36 |
| FRACTAL | 2399 | 30% | 2.39 |

**Ординальная нейросеть: CV ρ=0.066, TEST ρ=0.042** (слабая). Монотонность почти исчезла: pred=1→32%, pred=4→38% (всего 6pp разброс). TOP score≥3: WR 40% vs 34% baseline (lift ×1.19).

**Sanity shuffle ρ=0.06** (≈0) → lookahead'а НЕТ.

**MDA топ-фичи качества:** sig_direction_long (направление — главная!), bars_since_ll, dist_hh30_pct, bulk_hs_top_bars_since, hull_dist_pct, sweep_SSL_72h, n_SHORT_OB, trend_4h, Bulkowski (big_m/db_eve_eve/v_top), sig_risk_pct.

## ⚠️ Главный вывод (честно)

**Pooled 3 актива НЕ усилил фильтр качества сигналов — наоборот ослабил:** ρ упал 0.11 (BTC-only etap_178) → 0.06 (3 актива). Монотонность хуже (BTC: 34→57%, 3 актива: 32→38%).

**Почему:** 3 актива помогли предсказателю **фракталов** (etap_177: AUC 0.67→0.93), но НЕ оценщику **качества сигналов**. Качество сделки определяется рыночным шумом ПОСЛЕ входа — он не предсказуем из контекста, добавление активов лишь усреднило слабый сигнал. **etap_178 (BTC-only) остаётся сильнейшим фильтром.**

## Live (что работает в боте прямо сейчас)

- **Модель:** etap_179 (87 фич, 5 фолдов, сохранена в `output/etap179_model/`).
- **Прод-инференс:** [neural_signals_live.py](../../../neural_signals_live.py) — цикл 30 мин, генерит свежие сигналы (lookback 30д) → оценивает класс 1-5 → шлёт class≥4 в бота.
- **Бот:** @test_neyro_traid_bot (токен в .env). Команды /start /grade N /status. Дедуп.
- **Watchdog:** [neural_bot_watchdog.sh](../../../neural_bot_watchdog.sh) — держит живыми и бота, и инференс.
- ⚠️ Фильтр слабый (ρ 0.06) — это честный текущий уровень, не финал. Для усиления нужно либо вернуться к BTC-only (etap_178), либо признать, что качество сигнала слабо предсказуемо.

## Дальше (улучшение фильтра)

1. **Сохранить и пустить в бот BTC-only модель** (etap_178, ρ 0.11, WR 34→57%) — сильнее pooled. Требует выравнивания фич live-генератора под BTC-набор.
2. MDA показал: направление сигнала + фрактал-контекст + Bulkowski важнее всего — можно урезать фичи до топ-20 (меньше шума).
3. Возможно качество сделки просто слабо предсказуемо → честный потолок фильтра ~+6-20pp на топе.

Скрипт: [etap_179](../../../research/elements_study/etap_179_signal_grade_3assets_mda.py). Связь: [[signal-grade-1to5-ordinal-nn-etap178]], [[neural-full-arsenal-pavel-etap177]], [[traid-bot-strategies-winrate-audit]], [[adv-fin-ml-индекс]].
