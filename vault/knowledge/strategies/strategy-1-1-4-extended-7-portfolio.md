---
tags: [strategy, 1-1-4, portfolio, extended, ema-filter]
date: 2026-05-15
---

# Strategy 1.1.4 Extended-7 portfolio — +159R / 0 bad years

Расширение canonical BFJK (4 цепочки → 7 цепочек) + EMA-200(2h) trend filter.
Тестировано в etap_117 (wide grid) + etap_118 (portfolio assembly).

## Result vs canonical BFJK (BTC 6.3y)

| Config | n | WR | **PnL** | top5% | **Bad** | Δ vs canonical |
|---|---:|---:|---:|---:|---:|---:|
| Canonical BFJK | 115 | 64.3% | +107R | 9.3% | 1/7 | reference |
| BFJK + EMA-2h | 82 | 75.6% | +104R | 9.6% | 1/7 | filter alone не помог |
| **Extended-7 raw** | 210 | 59.5% | **+165R** | 6.1% | 1/7 | **+58R (+54%)** |
| **Extended-7 + EMA-2h** ★★ | 156 | **67.3%** | **+159R** | 6.3% | **0/7** ★ | **+52R + 0 bad** |

## 7 цепочек

| Chain | L1 | L2 | L3 | L4 | Origin |
|---|---|---|---|---|---|
| **B** | FVG-12h | OB-4h | OB-1h | FVG-15m | canonical |
| **K** | FVG-12h | OB-4h | OB-1h | FVG-20m | canonical |
| **J** | FVG-1d | OB-4h | OB-1h | FVG-20m | canonical |
| **F** | FVG-1d | OB-6h | OB-2h | FVG-15m | canonical |
| **E-4a** ★ | FVG-1d | OB-4h | **OB-2h** | **FVG-20m** | NEW (etap_117) |
| **B-2d** | FVG-12h | **FVG-4h** | OB-1h | FVG-15m | NEW (FVG-4h L2!) |
| **B-3a** | FVG-12h | OB-4h | **OB-2h** | FVG-15m | NEW (weakest) |

## Параметры

| Параметр | Значение |
|---|---|
| entry | `fb + 0.70 × (ft - fb)` (deep) |
| SL anchor | x1 = L1 ∩ L2 |
| SL LONG | `x1_b + 0.35 × (fb - x1_b)` |
| SL SHORT | `x1_t - 0.65 × (x1_t - ft)` (asymmetric) |
| MIN SL | ≥ 1.0% от entry |
| **EMA filter** | **close_2h > EMA200_2h** для LONG (mirror SHORT), на signal_time |
| RR | 2.0 fixed |
| Max hold | 7 дней |
| allow_multi | 5 cascades/L1 |
| Union dedup | `(signal_time, direction, round(fvg_b,2), round(fvg_t,2))` |

## По годам (Extended-7 + EMA-2h)

```
2020: +14R
2021: +11R
2022: +28R
2023: +42R
2024: +34R
2025: +4R    ← canonical BFJK имел -5R здесь
2026: +26R
```

**Все 7 лет плюсовые ★** (canonical BFJK имел 2025 = −5R).

## Разбивка по цепочкам (Extended-7 raw)

| Chain | n | W | PnL | WR |
|---|---:|---:|---:|---:|
| B | 34 | 23 | +35R | 67.6% |
| K | 27 | 18 | +27R | 66.7% |
| E-4a | 27 | 17 | **+24R** | 63.0% ★ |
| B-2d | 32 | 18 | +22R | 56.3% |
| J | 24 | 15 | +21R | 62.5% |
| B-3a | 36 | 16 | +12R | 44.4% (weakest) |
| F | 16 | 8 | +8R | 50.0% |
| Overlap (B+B-3a, J+K и др.) | — | — | +16R | mixed |

## Что особенного в новых цепочках

### E-4a (FVG-1d + OB-4h + OB-2h + FVG-20m)
- **Не в BFJK** — новая комбинация L2/L3/L4
- **0 bad years** на этой цепочке
- WR 63%, +24R
- Использует **OB-2h** на L3 + **FVG-20m** entry (J и K делают это отдельно, эта объединяет)

### B-2d (FVG-12h + FVG-4h + OB-1h + FVG-15m)
- **FVG-4h на L2** вместо OB-4h
- Похоже на гибрид 1.1.6 (FVG-macro) и 1.1.4 (deep entry)
- +22R, WR 56%

### B-3a (FVG-12h + OB-4h + OB-2h + FVG-15m)
- OB-2h L3 вместо OB-1h
- Самая слабая в группе (WR 44%, +12R)
- Возможно убрать → Extended-6

## Тестирование

Тестировано только BTC. ETH/SOL валидация pending.

## Файлы

- `research/elements_study/etap_117_fvg_d_wide_grid.py` — 28 chains survey
- `research/elements_study/etap_118_extended_portfolio.py` — portfolio assembly
- `strategies/strategy_1_1_4.py` — base detector

## Связи

- [[strategy-1-1-4-bfjk-portfolio]] — canonical 4-chain version
- [[c2-ema-or-hull6h-trend-filter-winner]] — EMA filter тот же что в C2
- [[2026-05-15-floating-tp-multi-symbol-c2-trendfilter]] — session note
