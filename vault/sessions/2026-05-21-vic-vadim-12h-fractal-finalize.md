---
tags: [session]
date: 2026-05-21
status: closed
related: [[стратегия ViC Vadim 12h вариант 1]], [[12h фрактал — эмпирика снятия зон 6y BTC]], [[vic-asvk-indicator-python]], [[три класса зон ликвидность эффективность неэффективность]]
---

# 2026-05-21 — ViC Vadim 12h-fractal стратегия финализирована

Большая двухдневная сессия (началась 20-05, завершилась 21-05). Спроектирована
и забэктестена стратегия предсказания HH/LL-фрактала Билла Уильямса на 12h
BTC через двойной sweep-confluence. Найден точный LTF Pine ASVK ViC для 12h
chart, проведена brute-force оптимизация mlt по 35 значениям, OOS-валидация
на ETH. Создано 14+ скриптов research, 3 канон-заметки, 5 memory-записей.

## Установленные термины пользователя (memory)

- **Три класса зон SMC** — [[три класса зон ликвидность эффективность неэффективность]]:
  - ликвидность: FH, FL
  - неэффективность: FVG
  - эффективность: RDRB V1, RDRB V2, maxV ViC
- **W ТФ = понедельник-понедельник** (TV-стандарт), не epoch (чт-чт).
  Memory: `weekly-tf-anchor-monday`.
- **Время в чате UTC+3** (повтор из 19-05). Memory: `display-time-in-utc-plus-3`.

## Финальная стратегия

См. [[стратегия ViC Vadim 12h вариант 1]].

**Сигнал на close 12h-свечи `i`:**

C1 (OR):
- sweep_FH / sweep_FL (Билл Уильямс) на ТФ ∈ {12h, 1d, 2d, 3d, W}
- OB_sweep SHORT/LONG на тех же ТФ

C2:
- sweep maxV(i-1) (Pine ASVK ViC, LTF=ceil(rs/60)m, mlt=45 → 16m)

**Результаты 6y in-sample BTC:**
| | n | hits | precision | в год |
|---|---|---|---|---|
| HH Core | 84 | 70 | **83.33%** | ~14 |
| LL Core | 92 | 69 | **75.00%** | ~15 |
| **Σ Core** | **176** | **139** | **78.98%** | **~29** |
| HH Sniper (AND C1) | 31 | 29 | 93.55% | ~5 |
| LL Sniper (AND C1) | 40 | 30 | ~75% | ~7 |

**OOS на ETH (6y):**
| | precision | в год |
|---|---|---|
| HH Core | 73.02% | ~10 |
| LL Core | **75.44%** | ~9 |
| Σ Core | 74.17% | ~20 |

LL стабилен на двух символах (~75%), HH BTC-specific (BTC 83% vs ETH 73%).

## Важный технический вывод — Pine LTF resolution

Pine `timeframe.from_seconds(seconds)` на 12h-chart c mlt=100:
- `rs = 43200/100 = 432s = 7.2 min`
- Pine **round-up** до целой минуты → **"8"** (8m TF).

Универсальное правило: `LTF_minutes = math.ceil(rs/60)`.

Это **другое поведение, чем для D-chart** (там Pine выбирает closest valid
из стандартных 5/10/15m, для 864s = 15m). На 12h-chart Pine использует
non-standard integer minutes (7, 8, 11, 14, 16, 21, 24…).

См. [[pine-ltf-12h-chart-ceil-round-up-to-integer-minutes]].

## Перебор mlt — оптимум для обоих символов

Brute-force mlt ∈ [30, 200] шаг 5 (35 значений). **mlt=45 → LTF=16m**
оптимален для BTC (Σ prec 78.98%) и ETH (74.17%) одновременно. Это
сильный аргумент против overfit на одной in-sample выборке.

Pine default mlt=100 (LTF=8m): BTC -0.95pp, **ETH -6.67pp**. На ETH
особенно важно использовать mlt=45.

## Полный путь стратегии (хронология условий)

1. **Условие 1 — C1.** Sweep одной из HTF-зон. Перебраны 6 классов:
   - OB-liq (58-65%) — но coverage <1%, отклонено
   - FH/FL (54-55%) — основной кандидат
   - OB (52-54%) — второй кандидат
   - FVG (40-41%) — отклонено для union, но рассмотрено
   - RDRB V1/V2 (31-35%) — слабое, отклонено
2. **C2 на LTF (15m-4h) — отклонено.** «Голая FVG» — coverage 99%, lift 1.0.
   iFVG +4-10pp, OB(1h-2h)∩FVG(1h-2h) +5-11pp — но maxV даёт больше.
3. **C2 = maxV ViC ASVK — победитель.** Закрыл треугольник классификации
   (ликвидность + эффективность). Прибавил +20-30pp.
4. **C3 (LTF iFVG / OB+FVG поверх Core) — отклонено.** HH ∩ iFVG(1h-2h)
   даёт 96.4% (n=28 на 15m), но узкое окно и LL почти ничего.
5. **FVG возвращён в исследование** (по запросу пользователя), но не
   как обязательная C1 — в union он понижает precision.
6. **maxV LTF подобран:** 15m → 1m → 8m (Pine default) → **16m (mlt=45,
   оптимум для BTC+ETH)**.

## Артефакты

В `research/vic_vadim/` (14 скриптов):
- **`predict_fractal_maxv_pine.py`** — финальный прогон (LTF=8m Pine).
- `optimize_mlt.py` / `optimize_mlt_eth.py` — brute-force mlt для BTC/ETH.
- `predict_fractal_maxv.py` / `predict_fractal_maxv_1m.py` — 15m/1m варианты.
- `predict_fractal_zones.py` — sweep_FH/FL + FT-OB+FVG (база).
- `predict_fractal_ob_liq.py` — OB с явно выраженной ликвидностью.
- `predict_fractal_ob.py` — простой OB.
- `predict_fractal_fvg.py` / `predict_fractal_fvg_stages.py` — FVG.
- `predict_fractal_rdrb_v1.py` / `predict_fractal_rdrb_v2.py` — RDRB.
- `predict_fractal_ltf_fvg_ifvg.py` — LTF FVG/iFVG.
- `predict_fractal_confluence.py` / `predict_fractal_confluence_ob_ltf.py`
  / `predict_fractal_confluence_triple.py` — confluence-прогоны.
- `predict_fractal_core_plus_c3.py` — C3 поверх Core.
- `predict_hh_12h.py` — baseline и первоначальный тест.
- `find_pair_examples.py` / `find_signal_candle.py` — раннее research для
  D-стратегии ViC Vadim (отложена, см. [[vic-vadim]]).
- `fetch_15m_extend.py` / `fetch_1m.py` / `fetch_eth_1m.py` — fetch
  скрипты, расширяющие кэш.

Кэши данных:
- `data/BTCUSDT_1m_vic_vadim.csv` — 3.18M баров (2020-05 → 2026-05).
- `data/BTCUSDT_15m_vic_vadim.csv` — 212k баров.
- `data/ETHUSDT_1m_vic_vadim.csv` — 3.18M баров.

## Pitfall — Pine 12h-chart LTF resolution

См. [[pine-ltf-12h-chart-ceil-round-up-to-integer-minutes]] — добавлен в
[[known-pitfalls]].

`from_seconds(seconds)` на non-D chart возвращает **non-standard integer
minute** (например 7, 8, 11, 14, 16). Это отличается от D-chart
([[vic-maxv-расходился-с-pine-индикатором-из-за-1m-вместо-15m]]), где
Pine использует closest valid из стандартного набора.

## Открытые задачи

1. **Entry / SL / TP формализация** — все эмпирические числа precision
   на «свеча станет фракталом», без торговой логики.
2. **Walk-forward на BTC** — rolling train/test split для проверки
   robust оптимума mlt=45.
3. **OOS на SOL** — третий символ для cross-asset валидации.
4. **Live integration** — отдельная WS-подписка 1m + 12h для BTC и ETH,
   real-time maxV(LTF=16m) вычисление.
5. **Фильтр волатильности** — на ETH хвост 2025-12..2026-05 даёт 50%
   precision (vs avg 74%) из-за бокового движения; ATR-фильтр может
   помочь.
6. **Recent BTC хвост (2026-05-04)** — единственный ложный HH-Sniper
   в свежей выборке. Понять — что отличает от 9 верных хвостовых.

## Связи

- [[стратегия ViC Vadim 12h вариант 1]] — финальная strategy-spec
- [[12h фрактал — эмпирика снятия зон 6y BTC]] — исследовательская база
- [[три класса зон ликвидность эффективность неэффективность]]
- [[vic-asvk-indicator-python]]
- [[фракталы билла уильямса]]
- [[универсальные определения OB и FVG]]
- [[что такое order block]]
- [[что такое rdrb]]
- [[reversal-3candle-fractal-prediction]] — родственная D-эмпирика 19-05
- [[zone-mitigation-filter-required]] — pitfall
- [[pine-ltf-12h-chart-ceil-round-up-to-integer-minutes]] — новый pitfall
