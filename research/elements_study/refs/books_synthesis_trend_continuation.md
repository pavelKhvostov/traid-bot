# Синтез 3 книг → тестируемая стратегия trend-continuation pullback

> Сводит [Dalton](dalton_market_profile_master.md) + [Harris](harris_microstructure_master.md) + [Grimes](grimes_tested_edge_master.md) в одну спеку под новый угол проекта (см. `vault/.../project_neuro_metalabel_no_edge.md` + `текущие приоритеты`).
> Дата: 2026-06-11.

## Главная идея (одно предложение)

Все прошлые тесты были про **counter-trend reversal / zone-reaction** (Grimes Trade 2 + Trade 3 — самая трудная, низко-edge сторона, что подтвердили 8 null-артефактов). Три книги сходятся: edge — в **Grimes Trade 1 (pullback-continuation)**, входе по тренду на откате **в зону принятой стоимости (Dalton HVN/POC/VAH)**, подтверждённом **возвратом signed-flow (Harris CVD/delta)**.

## Кто что даёт

| Книга | Роль в сетапе | Конкретно |
|---|---|---|
| **Grimes** | СТОРОНА + структура + дисциплина | Trade 1: тренд (momentum-leg) → orderly pullback → вход на возобновлении. Валидация vs random-walk. «Знаем направление, не магнитуду» → не хардкодить +5%. |
| **Dalton** | ГДЕ (зона отката) | Откат в HVN/POC/VAH **по** направлению value-migration. HVN снизу = магнит/поддержка (там откат держится); LVN = быстрый проход (цель). |
| **Harris** | ПОДТВЕРЖДЕНИЕ (поток) | На дне отката: затухание sell-delta + возврат buy-delta / CVD-дивергенция / absorption. taker_buy из Binance klines (idx 9/10) — у нас сейчас дропается. |

## Спека сетапа (LONG; SHORT зеркально)

**Контекст (gate, всё на закрытых барах):**
1. **Тренд** (Grimes): EMA-slope > 0 + структура HH/HL, ИЛИ Dalton `value_migration_sign > 0` (VPOC растёт k периодов). Оба согласны → сильнее.
2. **Momentum-leg** (Grimes): был thrust = range-expansion бар(ы) / серия with-trend баров в последних j барах. Без него — пропуск.

**Триггер отката:**
3. Цена откатывает **в зону стоимости** (Dalton): касается prior **VAH / POC** или сильного **HVN** снизу. Глубина — band 0.2–0.7 от momentum-leg (Grimes: мельче = сильнее), НЕ фикс-Fib.
4. **Затухание** (Grimes+Harris): диапазоны/объём отката падают; `bar_delta` отрицательный, но затухает.

**Подтверждение входа (нужно ≥1, лучше 2):**
5. Возобновление (Grimes): пробой high отката / реклейм EMA / MACD-Anti разворот.
6. Поток (Harris): `delta` флипается в плюс ИЛИ **CVD-дивергенция** (цена lower-low, CVD higher-low) ИЛИ **absorption** (высокий объём, малый диапазон, sell-delta поглощён).
7. Зона держит (Dalton): rejection от HVN/POC, low-volume на проколе, нет value-migration вниз.

**Риск:**
- **SL** (Grimes): за структурой инвалидации = под low отката / под HVN (пробой = value мигрирует вниз = тезис мёртв).
- **TP/управление** (Grimes): НЕ фикс-цель. Частичная фиксация + трейл; ближайший LVN сверху = быстрый проход, prior swing / naked POC = магнит-цель. Лейблить мультигоризонтно (MFE/MAE 6/12/24/48 баров или first-touch RR 1/2/3), дать системе выбрать.

## Что дозагрузить в данные

**taker buy volume из Binance klines** — у нас в пайплайне дропается. Нужно: idx 9 = `taker_buy_base`, idx 10 = `taker_buy_quote`. Из них: `delta = 2·taker_buy_base − volume`, `CVD = cumsum(delta)`. (Harris §4.) Без этого вся flow-часть (п.4,6) недоступна — это первый технический шаг.

## Фичи (объединённый список под модель)

- **Тренд/momentum (Grimes):** `trend_strength`(EMA-slope/структура), `momentum_leg_size`(thrust/ATR), `bars_since_momentum_leg`.
- **Откат (Grimes):** `pullback_depth`, `pullback_bars`, `pullback_is_two_leg`, `pullback_range_decay`, `dist_to_EMA`.
- **Зона (Dalton):** `dist_to_VPOC`, `dist_to_nearest_HVN/LVN`, `at_HVN`, `inside_VA`/`pos_in_VA`, `value_migration_sign`, `va_overlap_pct`, `naked_POC_above`.
- **Поток (Harris):** `taker_buy_ratio`, `bar_delta`(/quote), `CVD_slope_N`, `CVD_div`, `absorption`(effort/result), `kyle_lambda_N`, `vpin_N`.

## Бар приёмки (Grimes-дисциплина, как в etap_188)

1. **vs random-walk null** (permutation/bootstrap, conditioning на тренд-режим) — p < 0.05, edge не из степеней свободы.
2. **AUC > 0.58** на чистом 1h-исполнении (порог из приоритетов).
3. **Плюс по годам** (train 2020-24 / test 2025-26) И **по активам** (BTC+ETH+SOL) — не один режим.
4. Edge переживает **leak-фиксы** (только closed-bar taker; профиль только из прошлых баров).

## Три первые гипотезы для теста

- **H1 (Harris):** в подтверждённом аптренде откаты с **CVD higher-low при price lower-low** дают выше forward-return, чем откаты с подтверждающим (падающим) CVD.
- **H2 (Dalton):** откат, держащий **HVN/POC** (rejection), бьёт откат, проваливающийся в LVN под ним.
- **H3 (Grimes):** наличие **momentum-leg перед откатом** — необходимое условие; без него pullback-вход = random.

## Связь с прошлым проектом

- Единственное с +OOS, что устояло: **in-process путь** (etap_193 AUC 0.58) — управление по ходу, согласуется с Grimes «manage, don't predict». Применять поверх сетапа с edge.
- **i-RDRB+FVG** (+257R, robust) — sweep/liquidity-grab каскад = Harris «liquidity grab → informed re-entry» (синтез §6 Harris). Можно усилить flow-подтверждением.
- Закон [[vadim 12 confluens asvk]] (фильтр повышает R/tr, режет ΣR) — держать в уме: цель здесь primary-edge новой СТОРОНЫ, а не ещё один фильтр.
