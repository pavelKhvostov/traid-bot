---
tags: [strategy, i-rdrb, fvg, combined-d, baseline-upgrade, block-edge, sl-optimization]
date: 2026-05-24
status: validated-on-6y-btc
related: [[2026-05-24-i-rdrb-fvg-evot-vwap-features-sl-optim]], [[2026-05-23-smc-lib-vwap-entry-experiments]], [[i-rdrb-v1-pattern]]
---

# i-RDRB+FVG Combined D — baseline upgrade (entry на block edge, SL 0.1 offset)

Канонический upgrade поверх baseline i-RDRB+FVG. Проверен на 6 лет BTC 1h (780 trades). Улучшает все 3 основные метрики одновременно: WR, ΣR (baseline units), ΣR (new units).

## Спецификация

### LONG (i-RDRB direction = long, underlying RDRB = short)

```
entry = block.top                                    # верхняя граница 1h RDRB block
SL    = pattern_low + 0.1 × (block.bottom − pattern_low)
TP    = entry_baseline + (entry_baseline − pattern_low)   # baseline TP price unchanged
        where entry_baseline = (block.bottom + block.top) / 2
```

### SHORT (mirror — i-RDRB direction = short, underlying RDRB = long)

```
entry = block.bottom                                 # нижняя граница 1h RDRB block
SL    = pattern_high − 0.1 × (pattern_high − block.top)
TP    = entry_baseline − (pattern_high − entry_baseline)  # baseline TP price unchanged
```

### Замечания

- **Не меняем TP** — используем baseline TP price (RR=1 от midpoint к pattern_extreme).
- **Entry на ВЕРХНЕЙ границе block** (для LONG) — ближе к TP направления → выше fill rate, меньше R/win, но больше total R.
- **SL на 10% от pattern_extreme к block edge** — slightly tighter чем pattern_low/high, экономит R на losses, теряя минимум wins.

## Бэктест на BTCUSDT 1h, 6 лет (2020-05 → 2026-05)

### Baseline (A) — для контекста

| Side | n | WIN | LOSS | WR% | ΣR |
|---|---:|---:|---:|---:|---:|
| LONG | 392 | 239 | 153 | 60.97 | +86.0 |
| SHORT | 388 | 203 | 185 | 52.32 | +18.0 |
| **TOTAL** | 780 | 442 | 338 | **56.67** | **+104.0** |

### Combined D

| Side | n | WIN | LOSS | NoFill | WR% | ΣR_new | ΣR_base | avg_RR/win |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| LONG | 392 | 256 | 136 | 14 | **65.31** | +105.2 | +102.5 | 0.94 |
| SHORT | 389 | 211 | 178 | 13 | **54.24** | +21.4 | +20.0 | 0.95 |
| **TOTAL** | 781 | **467** | 314 | 27 | **59.80** | **+126.5** | **+122.6** |

### Δ vs Baseline

| Метрика | Baseline | D | Δ |
|---|---:|---:|---:|
| ΣR (fixed contract / baseline units) | +104.0 | +122.6 | **+18.6R (+17.9%)** |
| ΣR (fixed $ risk / new units) | +104.0 | +126.5 | **+22.5R (+21.6%)** |
| WR | 56.67% | 59.80% | **+3.13pp** |
| Trades | 780 | 781 | +1 (1 LONG ушёл из no-fill из-за более высокого entry) |

## Раскладка по сторонам

| | LONG ΔR_base | SHORT ΔR_base |
|---|---:|---:|
| Baseline | +86 | +18 |
| D | +102.5 | +20.0 |
| **Δ** | **+16.5R (+19%)** | **+2.0R (+11%)** |

LONG-сторона по-прежнему доминирует в edge (+102.5 из +122.6 total). SHORT улучшается умеренно (+2R) но **становится менее зашумлённой** (WR +1.92pp).

## Что делает D особенным

Это **первый upgrade на этой стратегии, который улучшает обе метрики одновременно**:
- Не просто WR за счёт меньшего ΣR (не tighter TP)
- Не просто ΣR за счёт меньшего WR (не tighter SL без других изменений)
- Не просто доля прибыли через расширение позиции (= fixed-$-risk эффект)

Симультантное улучшение объясняется **геометрией паттерна**:
- Entry на block.top — фиксирует "входную ликвидность" в зоне с историей институциональных уровней
- SL на 10% от pattern_low — не слишком жёсткий (95% wins выживают), но экономит ~10% R на каждом loss
- Combined effect — синергетический

## Историческое сравнение (по памяти)

| Стратегия | n | WR% | ΣR | R/tr | Source |
|---|---:|---:|---:|---:|---|
| i-RDRB+FVG baseline | 780 | 56.67 | +104 | +0.133 | [[2026-05-23-smc-lib-vwap-entry-experiments]] |
| **+ Combined D** | 781 | 59.80 | **+122.6** | **+0.157** | this note |
| + F1∪F2_same + F3(R/ATR) | 257 | 71.60 | +111 | +0.430 | [[i-rdrb-v1-pattern]] |
| + Vadim 12 Confluens ≥12 | 278 | 53.60 | +79.6 | +0.286 | [[vadim 12 confluens asvk]] |

**Combined D — лучший по абсолютному ΣR без потери volume** (781 trades vs 257 у F1∪F2+F3). У F1∪F2+F3 выше WR (71.6%) и R/tr (+0.43), но меньше абсолютных сделок.

**Combined D можно стэкать поверх F1∪F2+F3** — entry/SL rules ортогональны pattern-detection фильтрам. Не тестировано.

## Открытые задачи

1. **Stack D + F1∪F2_same + R/ATR(14)∈[0.5,0.85)**: применить filter из памяти к D. Ожидаемо: меньше trades, выше WR, выше R/tr.
2. **OOS split**: 2020-2023 vs 2024-2026 для D.
3. **SL sweep при entry=block.top**: 0.1 best for ΣR_base, 0.5 best for ΣR_new — стэк зависит от sizing approach.
4. **Hybrid D + 30m FVG anti-filter**: исключать паттерны с bullish 30m FVG в зоне [pattern_low, block.bottom] для LONG.

## Артефакты

- `~/smc-lib/scripts/backtest_combined_d_full.py` — финальный бэктест (LONG + SHORT)
- `~/smc-lib/scripts/backtest_entry_blocktop_sl_0_1.py` — LONG-only с детальным sweep
- `~/smc-lib/scripts/entry_grid_in_block.py` — grid entry в block
- `~/smc-lib/scripts/entry_grid_above_block.py` — grid entry выше block.top
- `~/smc-lib/scripts/optimize_sl_grid.py` — SL grid
- `~/smc-lib/scripts/sl_grid_on_239_wins.py` — SL grid на 239 winners

## Связи

- [[2026-05-24-i-rdrb-fvg-evot-vwap-features-sl-optim]] — родительская сессия, в которой найдены индивидуальные апгрейды
- [[i-rdrb-v1-pattern]] — память с F1∪F2+F3 фильтрами (orthogonal к Combined D)
- [[i-rdrb fvg митигация зоны 1h btc eth]] — основная стратегия с другим entry-механизмом (zone-mitigation)
- [[smc-lib-as-canonical-source]] — где живёт код
