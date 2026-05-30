---
tags: [session, i-rdrb, confluens, asvk, c2-research]
date: 2026-05-21
status: paused
related: [[i-rdrb fvg митигация зоны 1h btc eth]], [[vadim 12 confluens asvk]]
---

# 2026-05-21 — i-RDRB+FVG + расширенный C2-research + Vadim 12 Confluens ASVK

Продолжение того же дня после
[[2026-05-21-vic-vadim-12h-fractal-finalize]] и
[[2026-05-21-vic-vadim-c3-research-paused]]. Эта сессия — отдельная,
посвящена i-RDRB+FVG стратегии: завершение базы, проверка большого числа
C2-фильтров, построение confluence-score стратегии Vadim 12 Confluens ASVK.

## Что финализировано

### База i-RDRB+FVG zone-mitigation (BTC + ETH 1h, без SOL)

Зафиксирована основная стратегия — см. [[i-rdrb fvg митигация зоны 1h btc eth]].

**Параметры (universal):**
- Setup: V1 RDRB (3 свечи) → инверсия 4-й свечой → FVG того же направления на 5-й (offset+1 от инверсии)
- Zone interest: `[min(low #1..#4), low(#5)]` LONG / зеркально SHORT
- Mitigation trigger без таймстопа
- Entry=0.9, SL=0.2, RR=1.4 (доли ширины зоны)

**Метрики 6 лет (2020-05-15 → 2026-05-20):**

| Asset | Closed | WR% | ΣR | R/tr | R/год |
|---|---|---|---|---|---|
| BTC | 730 | 50.27 | +150.80 | +0.207 | +25.1 |
| ETH | 748 | 48.26 | +118.40 | +0.158 | +19.7 |
| **Σ** | **1478** | **49.26** | **+269.20** | **+0.182** | **+44.9** |

SOL исключён: WR 43.48% (margin всего +1.81pp над BE 41.67%), ΣR +32.80R/6y =
+5.5R/год.

## Проверенные C2-фильтры (полный список)

### Positive (улучшают edge)

| Фильтр | n | WR% | R/tr | Δprec | Решение |
|---|---|---|---|---|---|
| **OB-4h match (HTF OB-pair same dir)** | 674 | 53.41 | +0.282 | +4.15pp | Сохранён как ⭐⭐⭐ в [[i-rdrb fvg митигация зоны 1h btc eth]] |
| Hull-78 1d direct (BTC only) | 378 | 54.23 | +0.302 | +3.96pp | Включён в Vadim 12 как Ф1 (на 1h) |
| MH B (extremum bw2 ≥ ±60) 4h sniper | 67 | 61.19 | +0.469 | +10.92pp | Узкий sniper, не основной |
| rel_vol < 1.5 (тихий объём) | 608 | 51.97 | +0.251 | +1.70pp | Включён в Vadim 12 как Ф11 |
| EVoT BEAR winner (5h) | 398 | 52.26 | +0.254 | +2.0pp | Включён как Ф8 (другая форма) |
| EVoT maxV ниже entry (FVG-3) | 239 | 53.14 | +0.275 | +2.86pp | Не включён |
| EVoT maxV в зоне (FVG-3) | 258 | 52.33 | +0.256 | +2.05pp | Не включён |
| Hour 06-11 UTC (Лондонская сессия) | 361 | 52.63 | +0.263 | +3.38pp | Не включён |
| DoW Sun/Mon/Wed | ~665 | 51.87-53.88 | +0.247 | +2.6..+4.6pp | Не включён |
| Zone width Q0 (узкая) | 370 | 52.43 | +0.258 | +3.18pp | Не включён |
| Body #4 < 0.79 (не марубозу) | 1108 | 50.79 | +0.211 | +1.52pp | Не включён (exclude вариант) |
| Mit-depth Q1 (0.02-0.05 width) | 369 | 52.30 | +0.255 | +3.05pp | Не включён |

### Negative / Anti-edge (НЕ повторять)

| Идея | Почему отвергнута |
|---|---|
| HTF sweep confluence на {12h..W} (свечи #1..#3) | n -35%, ΣR -37%, не улучшает edge — i-RDRB сам уже эмулирует sweep |
| EVoT-entry 50% (между maxV и FVG-границей) | BTC: WR 52.82%/SHORT 64.44% но **ETH: WR 39.44%** — BTC-specific overfit |
| Trendline entry (Hull-1h как entry-level) | BTC: WR 36.11% LONG, ETH: WR 59% — ETH-specific overfit |
| RSI 2h в OS-зоне (≤ below_level в 10 баров до setup) | **Inverse**: anti (RSI не касался) лучше |
| Fractal sweep 1h на свечах #1..#3 | **Inverse**: no-sweep лучше (95% сетапов имеют sweep на 1h — фракталов слишком много) |
| ViC.D(D-1) в зоне интереса (просто overlap, BTC+ETH) | Cross-asset разнобой: BTC −4.71pp / ETH +1.74pp = шумный, не паттерн |
| ViC.D > SL (maxV защищает SL) — гипотеза из примера 2026-05-19 | На 730 setup'ах Δprec +0.04pp — пример был частным случаем |

## Vadim 12 Confluens ASVK — новая стратегия (in research)

См. [[vadim 12 confluens asvk]] для spec.

**11 факторов с разными весами (на сегодня; задумано 12, ещё 1 не задан):**

| # | Фактор | Балл |
|---|---|---|
| 1 | Trendline HMA-78 1h на close(#5) direction-match | +1.0 |
| 2 | OB HTF same direction формирующийся в setup'е (cur в [open(#4), close(#5)+TF]) на {4h,6h,12h,1d} | +1.0 |
| 3 | Sweep FL/FH на {1h, 2h} свечой #1..#4 direction-aware | +1.0 |
| 4 | Sweep FL/FH на HTF {4h, 6h, 12h, 1d, 2d, 3d} direction-aware | +1.5 |
| 5 | Свечи #1..#4 перекрывают предсущ. FVG (`ready ≤ open(#1)`) на {15m, 1h, 2h} | +1.0 |
| 6 | Свечи #1..#4 перекрывают предсущ. FVG на HTF {4h..3d} | +1.5 |
| 7 | Свечи #1..#4 заходят в предсущ. OB HTF same direction | +1.5 |
| 8 | Нетронутый ViC.D / ViC.2D / ViC.3D (LTF=15m), первое перекрытие в setup'е | +1.5 |
| 9 | Raw RSI(14, Wilder) на close(#5) `<50` LONG / `>50` SHORT | +1.0 |
| 10 | Direction-aware дивы на 5 осцилляторах (MACD line, MACD hist, RSI, Stoch%K, OBV) с pivot на #1..#5 | +1 за каждый осциллятор (max +5) |
| 11 | rel_vol < 1.5 (тихий объём свечей #2..#4 относительно SMA20) | +1.0 |

**Max теоретический = 12.0 + 5.0 = 17.0 балла** (фактически 16.0 на BTC+ETH).

### In-sample результаты (BTC + ETH, 6y)

Cumulative threshold ≥ X:

| Threshold | n | WR% | ΣR | R/tr | ΔWR |
|---|---|---|---|---|---|
| baseline | 1478 | 49.26 | **+269.20** | +0.182 | 0 |
| ≥ 9.0 | 1246 | 49.84 | +244.40 | +0.196 | +0.58 |
| ≥ 10.0 | 924 | 51.30 | +213.60 | +0.231 | +2.04 |
| ≥ 11.0 | 580 | 51.90 | +142.40 | +0.246 | +2.64 |
| **≥ 12.0 sweet spot** | 278 | **53.60** | +79.60 | **+0.286** | **+4.34** |
| ≥ 13.0 sniper | 105 | 54.29 | +31.80 | +0.303 | +5.03 |
| ≥ 14.5 ultra-sniper | 22 | 59.09 | +9.20 | +0.418 | +9.84 |

**Score distribution есть pики** (буfer-bucketsize малый — статистическая значимость низкая):
- score 12.0: 35 trades, WR 60.00%, R/tr +0.440
- score 14.5: 17 trades, WR 64.71%, R/tr +0.553

### Ключевое наблюдение

**Confluence-score не даёт ΣR-prirostu** (любой threshold ≥ X уменьшает ΣR
относительно baseline +269.20R, потому что отсечённые setup'ы тоже net-positive).

Confluence работает только для **повышения качества** (R/tr) — это nужно
конвертировать в больший RR на high-score setup'ах:
- При score ≥ 12 WR 53.60% → margin +11.93pp → можно поднять RR до 2.0-2.5
- Это даст ΣR прирост без потери baseline (двухуровневая стратегия)

## Открытые направления

1. **Score-based RR** — grid RR=1.4..3.0 × threshold ≥ 9/10/11/12 для finding оптимума ΣR
2. **Двухуровневая стратегия**: baseline RR=1.4 + дополнительный bet на score ≥ 12 с RR=2.0
3. **Фактор 12** — не задан (если решим расширить с 11)
4. **Walk-forward / OOS** — split 2020-23 vs 2024-26
5. **Per-asset RR-оптимум** (BTC=1.4, ETH=2.8) — даёт +13R но overfit-risk

## Файлы

- Финал базы: `research/vic_vadim/backtest_irdrb_fvg_mit_zone.py` (BTC+ETH, RR=1.4)
- Vadim 12 main: `research/vic_vadim/vadim_confluens_asvk.py`
- C2-исследование (большой список):
  - `analyze_trendline_filter.py` — Hull-78 на разных ТФ
  - `analyze_money_hands_filter.py` — MH формы × ТФ
  - `analyze_evot_filter.py` — EVoT rNorm
  - `analyze_evot_maxv_filter.py` — EVoT maxV в зоне
  - `backtest_irdrb_fvg_evot_entry.py` — EVoT-entry 50% (BTC-specific)
  - `backtest_irdrb_fvg_evot_entry_eth.py` — ETH-провал EVoT-entry
  - `backtest_irdrb_fvg_trendline_entry.py` — Hull-1h entry (ETH-specific)
  - `backtest_irdrb_fvg_mit_c2.py` — HTF sweep confluence (rejected)
  - `backtest_irdrb_fvg_rsi_filter.py` — RSI 2h в OS (inverse)
  - `backtest_irdrb_fvg_fractal_sweep_1h.py` — fractal sweep 1h (inverse)
  - `backtest_irdrb_fvg_ob4h_confluence.py` — OB-4h match (saved as candidate)
  - `backtest_irdrb_fvg_vicd_confluence.py` — ViC.D в зоне (rejected)
  - `analyze_volume_filter.py` — rel_vol (теперь Ф11)
  - `analyze_misc_filters.py` — body#4, mit-depth, hour-of-day, DoW
  - `analyze_confluence_score.py` — старая 12-факторная версия

## Связи

- [[i-rdrb fvg митигация зоны 1h btc eth]] — родительская стратегия
- [[vadim 12 confluens asvk]] — спецификация новой стратегии (будет создана)
- [[что такое rdrb]] — canon RDRB
- [[asvk-custom-rsi]], [[money-hands-asvk]], [[asvk-trend-line-hull]],
  [[vic-asvk-indicator-python]] — ASVK-индикаторы
- [[2026-05-21-vic-vadim-12h-fractal-finalize]] — sibling-сессия (12h fractal)
- [[2026-05-21-vic-vadim-c3-research-paused]] — sibling-сессия (C3 на 12h)
