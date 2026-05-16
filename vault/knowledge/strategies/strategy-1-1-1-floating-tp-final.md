---
tags: [strategy, 1-1-1, floating-tp, live-candidate]
date: 2026-05-15
---

# Strategy 1.1.1 — финальная версия с Floating TP

Финальная версия 1.1.1 с **per-symbol floating TP** на основе
4-индикаторного momentum score. Заменяет fixed RR=2.2 на динамический
exit (R-cap + score + max-hold).

## Логика входа — не изменилась

Cascade 1.1.1 SWEPT (см. [[strategy_1_1_1]]):

```
L1: OB-{1d, 12h} top
└─ L2: FVG-{4h, 6h} macro
   └─ L3: OB-{1h, 2h} HTF + SWEPT filter
      └─ L4: FVG-{15m, 20m} entry
```

Entry: `fb + 0.80 × (ft - fb)` (80% deep into entry FVG).
SL: `obb + 0.35 × (fb - obb)` symmetric.

## Логика выхода — НОВАЯ (4 способа)

На каждом закрытом 1h-баре после fill проверяются 4 условия:

1. **Hard SL hit** → R = −1.0
2. **Hard TP cap hit** → R = +R_cap
3. **Score-exit** (momentum reversed) → R = (exit_price − entry) / risk
4. **Max hold 7 days** → R = mark-to-market

См. [[4-indicator-momentum-score]] для деталей score формулы.

## Per-symbol config (winner из etap_105-107)

| Symbol | R_cap | threshold | confirm bars |
|---|---:|---:|---:|
| **BTC** | 4.5 | −0.25 | 2 |
| **ETH** | 4.5 | −0.25 | 2 |
| **SOL** | 3.5 | 0.00 | 1 |

Логика: BTC/ETH более trend-like → более широкий cap, lenient threshold,
slower confirm. SOL volatile → tighter cap, neutral threshold, faster confirm.

## Результаты (multi-shot, limit-fill simulation, 6y)

| Symbol | Years | Baseline RR=2.2 | Floating TP | Δ |
|---|---:|---:|---:|---:|
| BTC | 6.34 | +165.2R / WR 45.4% | **+179.9R / WR 51.6%** | +14.7R (+9%) |
| ETH | 6.00 | +109.4R / WR 42.8% | **+152.2R / WR 49.8%** | +42.8R (+39%) |
| SOL | 5.76 | +43.2R / WR 35.0% | **+96.8R / WR 57.5%** | +53.6R (+124%) |
| **TOTAL** | ~6y | **+317.8R** | **+428.9R** | **+111.1R (+35%)** |

Smoothness — все 3 символа имеют top5% < 20% и medR > 0:

| Symbol | medR | top5% | Bad years |
|---|---:|---:|---:|
| BTC | +0.07 | 12.5% | 1/7 |
| ETH | 0.00 | 14.8% | 1/7 (vs baseline 1) |
| SOL | +0.12 | 16.6% | 2/7 |

## Caveat: multi-shot inflation

Multi-shot detector завышает trade count в ~1.8×. Реальные числа после
дедупа `(signal_time, direction, entry)`:
- BTC: 200 closed (vs 357 multi-shot)
- Real baseline ~+90R, real floating ~+100R на BTC
- См. [[multi-shot-detector-2.3x-inflation]]

Multi-shot OK для consistent comparison (baseline vs floating используют
ту же выборку) — relative uplift +35% honest.

## Lookahead safety

Все 4 индикатора score используют только закрытые бары до момента
checkpoint. SL/R_cap check на 1m walking — данные доступны в реал-тайме.
Exit price = close 1h бара подтверждения (не open следующего).
См. [[4-indicator-momentum-score]].

## Live-конфиг

```python
FLOATING_TP_CONFIG_111 = {
    "BTCUSDT": {"R_cap": 4.5, "threshold": -0.25, "confirm": 2},
    "ETHUSDT": {"R_cap": 4.5, "threshold": -0.25, "confirm": 2},
    "SOLUSDT": {"R_cap": 3.5, "threshold":  0.00, "confirm": 1},
}
MAX_HOLD_DAYS = 7
```

## Файлы

- `research/elements_study/etap_103_floating_tp.py` — base floating TP
- `research/elements_study/etap_104_floating_variants.py` — 14 variants smoothness
- `research/elements_study/etap_105_d_variant_tuning.py` — BTC grid winner
- `research/elements_study/etap_106_sol_specific.py` / `etap_107_sol_extended.py` — SOL tuning
- `research/elements_study/output/etap108_floating_tp_human_guide.pdf` — human PDF

## Связи

- [[strategy_1_1_1]] — backtest-only base
- [[4-indicator-momentum-score]]
- [[floating-tp-only-helps-low-wr-strategies]]
- [[2026-05-15-floating-tp-multi-symbol-c2-trendfilter]]
