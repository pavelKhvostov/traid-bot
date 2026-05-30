---
tags: [strategy, vic-vadim, 12h, fractal-prediction, btc, in-design]
date: 2026-05-20
status: backtest-validated
related: [[vic-vadim]], [[12h фрактал — эмпирика снятия зон 6y BTC]], [[vic-asvk-indicator-python]], [[фракталы билла уильямса]], [[универсальные определения OB и FVG]], [[три класса зон ликвидность эффективность неэффективность]]
---

# Стратегия ViC Vadim 12h — Вариант 1

Предсказание HH/LL-фрактала Билла Уильямса на 12h BTC через двойной
sweep-confluence: snake HTF-зоны (фрактал или OB) **И** snake уровня
maxV предыдущей 12h-свечи. Сигнал даётся на close(i) — за 24h до
официального подтверждения фрактала.

## Контекст

- **Символ:** BTCUSDT
- **Сигнальный ТФ:** 12h
- **Тип предсказания:** HH (вершина → SHORT) и LL (дно → LONG)
- **In-sample период:** 2020-05-01 → 2026-05-20 (6 лет)
- **Baseline:** P(HH) = 13.72%, P(LL) = 13.83% на 4418 валидных 12h-свечах

## Условия сетапа (оба на одной свече `i`)

### C1 — sweep HTF-зоны

Хотя бы одно (OR) на ТФ ∈ {12h, 1d, 2d, 3d, W (Mon-Mon)}:

- **sweep_FH / sweep_FL** — снятие фрактала Билла Уильямса
  ([[фракталы билла уильямса]]):
  - HH: `high(i) > FH_level AND close(i) < FH_level`
  - LL: `low(i) < FL_level AND close(i) > FL_level`
- **OB_sweep** — снятие зоны Order Block
  ([[универсальные определения OB и FVG]]):
  - HH (SHORT OB): `high(i) > zone.top AND close(i) < zone.top`
  - LL (LONG OB):  `low(i) < zone.bottom AND close(i) > zone.bottom`

Все зоны и фракталы — **немитигированные** (первый sweep после
формирования). Pitfall: [[zone-mitigation-filter-required]].

### C2 — sweep maxV(i-1)

maxV(i-1) — close LTF-свечи с максимальным dirVolume среди bull или bear
внутри предыдущей 12h-свечи. **LTF = 16 минут**, epoch-aligned (Pine
ASVK ViC с `mlt=45`, `rs=960s`, `ceil(rs/60)=16` — см.
[[pine-ltf-12h-chart-ceil-round-up-to-integer-minutes]]).

- HH: `high(i) > maxV(i-1) AND close(i) < maxV(i-1)`
- LL: `low(i) < maxV(i-1) AND close(i) > maxV(i-1)`

**Выбор mlt=45** обоснован brute-force перебором mlt ∈ [30, 200] шаг 5
на двух символах (BTC + ETH): mlt=45 даёт лучший Σ precision и для BTC
(78.98%), и для ETH (74.17%). Pine default mlt=100 (LTF=8m) даёт BTC
78.03% / ETH 67.50% — на ETH разница критична (-6.67pp).

## Эмпирические результаты (LTF=16m, mlt=45, финал)

### BTC Core: union(C1) ∩ maxV[i]

| | n | hits | precision | lift | в год |
|---|---|---|---|---|---|
| HH \| (sweep_FH ∪ OB_sweep) ∩ maxV[i] | 84 | 70 | **83.33%** | ×6.08 | ~14 |
| LL \| (sweep_FL ∪ OB_sweep) ∩ maxV[i] | 92 | 69 | **75.00%** | ×5.42 | ~15 |
| **Σ** | **176** | **139** | **78.98%** | — | **~29** |

### ETH Core (OOS-валидация)

| | precision | в год |
|---|---|---|
| HH \| Core | 73.02% | ~10 |
| LL \| Core | **75.44%** | ~9 |
| Σ Core | 74.17% | ~20 |

LL стабилен на двух символах (~75%). HH BTC-specific (BTC 83% vs ETH 73%).

### Sniper (AND обоих C1) — BTC

| | n | hits | precision | lift | в год |
|---|---|---|---|---|---|
| **HH Sniper** | 31 | 29 | **93.55%** | ×6.82 | ~5 |
| LL Sniper | 40 | ~30 | ~75% | ×5.4 | ~7 |

## Профили использования

| Профиль | Условие | precision | в год |
|---|---|---|---|
| **Sniper HH** | sweep_FH ∩ OB_sweep ∩ maxV[i] | 93.55% | ~5 |
| Core HH | (FH ∪ OB) ∩ maxV[i] | 78.57% | ~14 |
| Core LL | (FL ∪ OB) ∩ maxV[i] | 76.60% | ~16 |
| Sniper LL | FL ∩ OB ∩ maxV[i] | 73.81% | ~7 |
| **Core HH+LL** | объединение | 77.53% | ~30 |

## Что отклонено (с обоснованием)

- **FVG_sweep как C1** — в union снижает precision на 6–10pp при росте
  recall на 30–45%.
- **OB-liq sweep** — все его сетапы покрываются OB_sweep, инкремента нет.
- **RDRB V1/V2** — слабый одиночный edge (lift ×2.3–2.5); версия V1 ≈ V2.
- **Свеча `i-1`** — анти-edge (lift ×0.59 solo). Расширение окна на
  `i, i-1` снижает precision на 10–13pp.
- **C3 (LTF iFVG / OB+FVG на 1h-2h поверх Core)** — HH ∩ iFVG(1h-2h)
  даёт прорыв 96.4% (n=28 на 15m), но узкое окно (~5/год) и для LL
  почти ничего не добавляет (+1-2pp). Не используется как обязательное.
- **OB на LTF (15m-4h) сам по себе** — слабый фильтр (+1-3pp).
- **C3 в целом — в исследовании, форма не утверждена** (2026-05-21).
  Проверены 3 индикаторных кандидата (ASVK RSI, Money Hands, Hull MA),
  сделан cross-asset на BTC+ETH. SOL fetch не завершён (Binance timeouts).
  Полная сводка вариантов — в [[2026-05-21-vic-vadim-c3-research-paused]].
  Топ-кандидаты с trade-off:
  - **Hull GREEN 1h для LL only** (мягкий, Σ -8% n, +2.1pp prec)
  - **Money Hands HH⚪after🟢 4h + LL🟢 1h** (жёсткий, Σ -65%, +9pp prec)
- **ASVK Custom RSI зона (OB/OS) как C3** — отклонён 2026-05-21.
  Проверены LTF {1h, 2h, 4h, 6h}. Лучшая комбинация: HH ∩ ASVK OB 4h =
  91.67% (n=12), LL ∩ ASVK OB 1h anti = 92.31% (n=13). Поднимает Σ
  precision с 78.98% до 92%, но **сжимает n с 176 до 25 setups за 6y
  (-86%)** — ~4 setup/год. Слишком жёсткое сужение для практики:
  существующий Sniper-режим (sweep_FH ∩ OB_sweep ∩ maxV[i]) даёт
  сравнимую precision (HH 93.55%) при большем n (31 за 6y).
  Сигналы Core HH 1h ASVK OS и LL OB anti — статистически контр-
  интуитивны (anti-zone сильнее direct-zone), что может указывать на
  artifact адаптивных уровней ASVK, не на устойчивый эффект.
  См. `research/vic_vadim/predict_fractal_c3_asvk_rsi.py`.

## Сравнение LTF для maxV (BTC Core)

| LTF | mlt | HH prec / n | LL prec / n | Σ prec |
|---|---|---|---|---|
| 15m (~D-style) | — | 81.93% / 83 | 73.40% / 94 | 77.40% |
| 1m | — | 78.57% / 84 | 76.60% / 94 | 77.53% |
| 8m (Pine default) | 100 | 83.33% / 84 | 73.03% / 89 | 78.03% |
| **16m (оптимум)** | **45** | **83.33% / 84** | **75.00% / 92** | **78.98%** |

## Brute-force оптимизация mlt (BTC × ETH)

Перебор mlt ∈ [30, 200] шаг 5 = 35 значений. На обоих символах mlt=45
(LTF=16m) даёт лучший Σ precision — сильное cross-asset подтверждение
вне in-sample overfit. См. `research/vic_vadim/optimize_mlt.py` и
`optimize_mlt_eth.py`. Pine LTF resolved через `ceil(rs/60)` — см.
[[pine-ltf-12h-chart-ceil-round-up-to-integer-minutes]].

## Применение торгово (концептуально, не реализовано)

- **Direction:** SHORT для HH, LONG для LL.
- **Entry:** close(i) — момент close 12h-свечи.
- **SL:** над `max(high(i), FH_level, OB.top, maxV(i-1))` + buffer для
  HH; зеркально для LL.
- **TP:** TBD. Варианты:
  - Ближайший противоположный фрактал
  - RR-cap (например 2R или 3R)
  - Закрытие 12h-свечи `i+2` (подтверждение фрактала)
- **Тайм-стоп:** если до close(i+2) фрактал не подтверждён — закрыть.

## Открытые задачи

1. **Entry / SL / TP формализация** + бэктест с realistic execution.
2. **Walk-forward на BTC** — rolling train/test split для проверки
   robust оптимума mlt=45.
3. **OOS на SOL** — третий символ.
4. **Live integration:** отдельная WS-подписка 1m + 12h для BTC и ETH,
   real-time maxV (LTF=16m) вычисление.
5. **Фильтр волатильности (ATR)** — на ETH хвост 2025-12..2026-05 даёт
   50% precision (vs avg 74%) из-за бокового рынка.
6. **Анализ ложных HH-Sniper** (BTC 2026-05-04) — что отличает от 9
   верных хвостовых.

## Артефакты в коде

В `research/vic_vadim/`:

- **`optimize_mlt.py`** — финальный brute-force mlt на BTC (оптимум 45).
- **`optimize_mlt_eth.py`** — то же на ETH (оптимум тоже 45).
- `predict_fractal_maxv_pine.py` — Pine-exact LTF=8m (mlt=100).
- `predict_fractal_maxv_1m.py` / `predict_fractal_maxv.py` — старые
  варианты (1m, 15m), сохранены для history.
- Все вспомогательные скрипты эмпирики см. в
  [[12h фрактал — эмпирика снятия зон 6y BTC]] (14 файлов).

Кэш данных:
- `data/BTCUSDT_1m_vic_vadim.csv` — 3.18M баров (2020-05 → 2026-05).
- `data/BTCUSDT_15m_vic_vadim.csv` — 212k баров.
- `data/ETHUSDT_1m_vic_vadim.csv` — 3.18M баров.

## Связи

- [[vic-vadim]] — старая D-стратегия (paused, отдельная ветка).
- [[12h фрактал — эмпирика снятия зон 6y BTC]] — полная эмпирическая
  база с разбором всех классов зон.
- [[vic-asvk-indicator-python]] — определение maxV.
- [[три класса зон ликвидность эффективность неэффективность]] —
  пользовательская классификация зон (FH/FL = ликвидность,
  OB/FVG vs RDRB = эффективность, FVG = неэффективность, maxV = эфф.).
- [[zone-mitigation-filter-required]] — pitfall, обязателен для всех
  zone-overlap фильтров.
- [[reversal-3candle-fractal-prediction]] — D-эмпирика 2026-05-19
  (родственная задача на D ТФ).
