---
tags: [strategy, vadim, confluens, asvk, c2, in-research]
date: 2026-05-21
status: in-research
related: [[i-rdrb fvg митигация зоны 1h btc eth]], [[2026-05-21-i-rdrb-confluens-asvk-research]]
---

# Vadim 12 Confluens ASVK

Confluence-score стратегия поверх [[i-rdrb fvg митигация зоны 1h btc eth]].
На каждом setup'е оценивается сумма баллов по 11 (задумано 12) независимых
факторов; setup проходит при score ≥ threshold.

## База

- Setup: i-RDRB + FVG (5-свечной element) на 1h
- Execution: митигация zone → entry=0.9, SL=0.2, RR=1.4, без таймстопа
- Ассеты: BTCUSDT + ETHUSDT 1h (SOL исключён — WR 43.48% margin +1.81pp)
- Период: 2020-05-15 → 2026-05-20 (6 лет)

## 11 факторов (max 16.0 балла на BTC+ETH)

| # | Фактор | Балл | Детали |
|---|---|---|---|
| 1 | Trendline HMA-78 1h на close(#5) direction-match | +1.0 | LONG: HMA<close(#5); SHORT: HMA>close(#5) |
| 2 | OB HTF same direction формирующийся в setup'е | +1.0 | OB-pair cur_time ∈ [open(#4), close(#5)+TF] на {4h,6h,12h,1d}, OR |
| 3 | Sweep FL/FH на {1h, 2h} свечой #1..#4 | +1.0 | LONG: sweep FL (low<level AND close>level); SHORT: sweep FH |
| 4 | Sweep FL/FH на HTF {4h, 6h, 12h, 1d, 2d, 3d} | +1.5 | Тоже что Ф3 но HTF |
| 5 | Свечи #1..#4 перекрывают предсущ. FVG на {15m, 1h, 2h} | +1.0 | `ready(FVG) ≤ open(#1)`, любое direction, zone overlap |
| 6 | Свечи #1..#4 перекрывают предсущ. FVG на HTF {4h..3d} | +1.5 | То же на HTF |
| 7 | Свечи #1..#4 заходят в предсущ. OB HTF same direction | +1.5 | `ready ≤ open(#1)`, direction match, zone overlap |
| 8 | Нетронутый ViC.D / ViC.2D / ViC.3D (LTF=15m), первое перекрытие в setup'е | +1.5 | maxV на 1/2/3-дневном окне, не касался в `[t_formed, open(#1)]`, перекрывается на #1..#5 |
| 9 | Raw RSI(14, Wilder) на close(#5) | +1.0 | LONG: <50; SHORT: >50 |
| 10 | Direction-aware дивы на 5 осцилляторах | +1 за каждый осциллятор (max +5) | MACD line, MACD hist, RSI, Stoch%K, OBV; pivot ∈ #1..#5 |
| 11 | rel_vol < 1.5 | +1.0 | `rel_vol = Σvol(#2..#4) / (3 × SMA20(vol_per_1h))` |

### Свечи setup'а

| Индекс | Роль | Источник |
|---|---|---|
| #1 = k-2 | anchor V1 RDRB | Detect_rdrb |
| #2 = k-1 | mid V1 | |
| #3 = k | trigger V1 | |
| #4 = k+1 | inversion (close пробивает V1 зону → i-RDRB) | |
| #5 = k+2 | FVG.c2 (формирует FVG того же направления что i-RDRB) | detect_fvg |

## In-sample результаты (BTC + ETH, 6 лет)

Baseline (без C2): n=1478 closed, WR 49.26%, ΣR +269.20, R/tr +0.182.

Cumulative threshold ≥ X:

| Threshold | n | WR% | ΣR | R/tr | ΔWR | trades/мес |
|---|---|---|---|---|---|---|
| baseline | 1478 | 49.26 | **+269.20** | +0.182 | 0 | 20.5 |
| ≥ 9.0 | 1246 | 49.84 | +244.40 | +0.196 | +0.58 | 17.3 |
| ≥ 10.0 | 924 | 51.30 | +213.60 | +0.231 | +2.04 | 12.8 |
| ≥ 11.0 | 580 | 51.90 | +142.40 | +0.246 | +2.64 | 8.1 |
| **≥ 12.0** ⭐ | 278 | **53.60** | +79.60 | **+0.286** | **+4.34** | 3.9 |
| ≥ 13.0 | 105 | 54.29 | +31.80 | +0.303 | +5.03 | 1.5 |
| ≥ 14.5 | 22 | 59.09 | +9.20 | +0.418 | +9.84 | 0.3 |

### Score distribution — пики

| Score | n | WR% | R/tr | ΔWR |
|---|---|---|---|---|
| 10.0 | 39 | 53.85 | +0.292 | +4.59 |
| **12.0** | 35 | **60.00** | **+0.440** | **+10.74** |
| 13.0 | 19 | 57.89 | +0.389 | +8.64 |
| 14.5 | 17 | 64.71 | +0.553 | +15.45 |

Пики на узких bucket'ах — статистическая значимость ограничена (n=17-35).

## Ключевое наблюдение

**Confluence-фильтр не даёт ΣR-прироста**: любой threshold ≥ X уменьшает
суммарный R относительно baseline +269.20R, потому что отсечённые setup'ы
тоже net-positive (просто хуже среднего edge).

Confluence повышает только **R/trade** (качество per-trade), не **ΣR**.
Чтобы конвертировать в реальный ΣR-прирост, нужны другие подходы:

1. **Score-based RR**: high-score → больший RR (WR 53-60% позволяет RR 2.0-2.5)
2. **Двухуровневая стратегия**: baseline RR=1.4 + дополнительный bet на ≥12 с RR=2.0
3. **Position sizing** (для live)

## Сравнение с другими C2 (на baseline BTC+ETH)

| Filter | n | WR% | R/tr | ΔWR |
|---|---|---|---|---|
| Baseline | 1478 | 49.26 | +0.182 | — |
| Vadim 12 ≥ 12.0 | 278 | 53.60 | +0.286 | +4.34 |
| OB-4h match | 674 | 53.41 | +0.282 | +4.15 |
| rel_vol < 1.5 (= Ф11) | 1247 | 51.97 | +0.251 | +2.71 |
| Hull-78 1d direct (BTC only) | 378 | 54.23 | +0.302 | +3.96 |

Vadim 12 ≥ 12.0 ≈ OB-4h match по WR/R-trade, но меньше охват (278 vs 674).

## Открытые задачи

1. **Score-based RR optimization** — grid RR × threshold для max ΣR
2. **Фактор 12** не задан (структура из 11 факторов на сегодня)
3. **Двухуровневая стратегия baseline + sniper** — реализация и оценка
4. **Walk-forward** — train 2020-23 / test 2024-26
5. **Per-factor analysis** — какие из 11 факторов реально дают signal, какие шум
6. **ETH overlay тестов** на ViC.2D/3D (правильность расчёта)

## Файлы

- Main: `research/vic_vadim/vadim_confluens_asvk.py`
- Signals: `signals/vadim_confluens_asvk.csv`
- Связанные C2-эксперименты: см. [[2026-05-21-i-rdrb-confluens-asvk-research]]

## Связи

- [[i-rdrb fvg митигация зоны 1h btc eth]] — родительская стратегия (база)
- [[что такое rdrb]] — canon RDRB V1
- [[asvk-custom-rsi]] — ASVK Custom RSI (компонент Ф9, Ф10)
- [[money-hands-asvk]] — Money Hands (не входит, проверен отдельно)
- [[asvk-trend-line-hull]] — Hull-78 (Ф1)
- [[vic-asvk-indicator-python]] — maxV ViC ASVK (Ф8)
- [[2026-05-21-i-rdrb-confluens-asvk-research]] — сессия создания
