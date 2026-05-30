---
tags: [strategy, i-rdrb, fvg, vwap, asvk, experiment, rejected]
date: 2026-05-23
status: experiment-completed-no-edge
related: [[2026-05-23-smc-lib-vwap-entry-experiments]], [[i-rdrb fvg митигация зоны 1h btc eth]], [[vadim 12 confluens asvk]]
---

# i-RDRB + FVG + VWAPs ASVK — экспериментальные entry/TP/filter

Серия экспериментов 2026-05-23: можно ли использовать `VWAPs ASVK`
(anchored VWAP) поверх i-RDRB+FVG для значимого повышения WR / sumR?
**Вывод: нет** — все VWAP-варианты не превосходят baseline RR=1 на total R,
дают маржинальные изменения WR.

## Подлежащая стратегия (baseline)

- Detection: i-RDRB (4 свечи, reversal) + FVG того же направления на C3-C4-C5
  (см. `~/smc-lib/elements/i_rdrb/`, `~/smc-lib/elements/fvg/`)
- Entry: 0.5 RDRB block (середина блока, limit, ждёт fill бессрочно)
- SL: pattern_extreme (low C1..C5 для LONG, high — для SHORT)
- TP: RR 1:1 от entry

**6y BTC 1h baseline**: 798 trades, **WR 57.02%**, **ΣR +112** (LONG +91, SHORT +21).

## Формула VWAPs ASVK

```
cumPV(t)  = Σ_{k=anchor}^{t}  volume(k) × close(k)
cumVol(t) = Σ_{k=anchor}^{t}  volume(k)
VWAP(t)   = cumPV(t) / cumVol(t)
```

Pine-source: `~/Desktop/Без названия 3.rtf` — рисует до 10 anchored VWAP'ов от выбранных дат.

## Эксперимент 1 — "Вход по VWAP" (strict entry rule)

- Anchor: 5m свеча, содержащая pattern_low (LONG) / pattern_high (SHORT) на 1m уровне
- Entry: первое 1m после C5 close, где VWAP попадает в `[bar.low, bar.high]`
- **Фильтр**: VWAP в момент fill ≤ block.top (LONG) / ≥ block.bottom (SHORT)
- SL/TP — как baseline

**Результат**:

| Side | WR | Trades | Net R |
|---|---:|---:|---:|
| LONG | 62.50% | 20W/12L=32 | +8R |
| SHORT | 30.77% | 4W/9L=13 | −5R |
| **TOTAL** | 53.33% | 24W/21L=45 | **+3R** |

- Filter режет 94.4% паттернов (763/808). Слишком жёстко.
- LONG WR близка к baseline, edge не улучшен.
- SHORT — слишком мало сделок, статистически шумно.

**Эталон verify**: BTC 1h 2026-05-23 02:00 MSK LONG (pattern_low 75220 в 03:41 MSK на 1m, anchor 5m 03:40). VWAP entry triggered at 08:24 MSK, VWAP=75490.48 (block.top=75500 ✓). Trade → LOSS (SL 75220 hit). Совпало с user-expected.

## Эксперимент 2 — VWAP как TP (mean reversion)

Entry/SL baseline, TP = текущее значение VWAP (динамический).
3 варианта anchor:

| Variant (anchor) | Trades | WR% | ΣR | R/tr | LONG ΣR | SHORT ΣR |
|---|---:|---:|---:|---:|---:|---:|
| **A baseline RR=1** | 780 | **56.67** | **+104.0** | +0.133 | +86.0 | +18.0 |
| B vwap_same (anchor=SL extreme) | 779 | 54.94 | +61.6 | +0.079 | +35.2 | +26.4 |
| C vwap_opposite (anchor=opp extreme) | 779 | 53.15 | +80.8 | +0.104 | +50.2 | +30.6 |
| D vwap_c5 (anchor=C5 open) | 779 | 52.50 | +95.0 | +0.122 | +61.0 | **+34.0** |

**Все VWAP-TP варианты хуже baseline на ΣR.** WR падает: динамический TP цепляется
раньше → меньше R за win, при том же loss-структуре.

**Но SHORT-сторона улучшается**:
- baseline: +18R SHORT
- vwap_c5: **+34R SHORT** (+88%)
- vwap_c5: −25R LONG (-29%)

**Hybrid-гипотеза (не тестировал)**: LONG = RR=1, SHORT = VWAP-c5 TP. Цифры намекают
на +86 + 34 = +120R (vs baseline +104R), но это шаткое предположение из суммы
несовместимых выборок.

## Эксперимент 3 — VWAP как entry-фильтр (Baseline + VWAP-position)

Baseline (RR=1) + фильтр на позицию VWAP в момент C5 close. Anchor = pattern_extreme в направлении SL.

| Filter | n | WR% | ΣR | R/tr |
|---|---:|---:|---:|---:|
| **BASELINE** | 780 | 56.67 | **+104.0** | +0.133 |
| F1 VWAP в block | 56 | 55.36 | +6.0 | +0.107 |
| F2 VWAP выше block (long) / ниже (short) | 671 | **57.23** | +97.0 | +0.145 |
| F3 VWAP ниже block (long) / выше (short) — anti | 53 | 50.94 | +1.0 | +0.019 |
| F4 VWAP > entry (long) / < entry (short) | 710 | 57.18 | +102.0 | +0.144 |
| F5 VWAP < entry (long) / > entry (short) | 70 | 51.43 | +2.0 | +0.029 |

- F2 / F4 дают **маржинальный +0.5pp WR** ценой −2..−7R total.
- F3 / F5 — anti-edge подмножества (50-52% WR). Их исключение даёт чистый +1-2R.
- Slope-filter бесполезен: anchor на pattern_extreme гарантирует slope в сторону паттерна для 100% setup'ов.

## Итог по всем VWAP-вариантам

| Вариант | Edge vs baseline |
|---|---|
| VWAP-entry strict | −109R, 45 trades vs 798 — сильно режет, edge нет |
| VWAP-TP (best of B/C/D) | −9R на ΣR, чуть лучше SHORT |
| VWAP-filter (F2/F4) | −2 to −7R, +0.5pp WR — маржинально |
| Anti-filter (исключить F3/F5) | +1-2R — слабый чистый плюс |

**VWAP-индикатор не является существенным фактором edge для i-RDRB+FVG.**

## Где реальный edge

См. `[[i-rdrb-v1-pattern]]` (memory) и `[[i-rdrb-v1-fvg-f1-f2-f3-strategy-257-setups-wr72]]`:

- **HTF OB match (4h-12h)**: +4.15pp WR на baseline → 66.2% WR
- **R/ATR(20) ∈ [0.55, 1.03]**: после F1∪F2 даёт **257 trades, 71.6% WR, +111R, Sharpe 3.13**

Эти фильтры на порядок сильнее любого VWAP-варианта.

## Артефакты

Скрипты в `~/smc-lib/scripts/`:
- `backtest_i_rdrb_fvg_rr1.py` — baseline
- `backtest_i_rdrb_fvg_vwap_entry.py` — VWAP-entry strict
- `sweep_vwap_strategies.py` — TP-варианты A/B/C/D
- `sweep_vwap_filters.py` — filter-варианты F1-F10
- `verify_vwap_entry_2026_05_23.py` — sanity check
- `plot_vwap_entry_examples.py` — графики (`~/Desktop/i-rdrb-charts/vwap_entry_*.png`)

Графики:
- `vwap_entry_2026-05-23_long_loss.png` — эталонный кейс
- `vwap_entry_2025-07-23_long_win.png` — WIN LONG
- `vwap_entry_2026-03-03_short_win.png` — WIN SHORT

## Решение

**VWAP-варианты для i-RDRB+FVG отвергнуты.** Продолжение развития
направления — через HTF-структурные фильтры (OB, RDRB на старших ТФ) и
R/ATR-нормализацию SL. См. `[[smc-lib-as-canonical-source]]` для плана
следующих smc-lib элементов.
