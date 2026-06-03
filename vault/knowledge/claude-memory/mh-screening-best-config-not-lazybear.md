---
name: mh-screening-best-config-not-lazybear
description: "PC2 MH parameter screening (6912 configs, 2026-05-31) — LazyBear-канон (9,12,4,14,60,40,81) в нижних 19% (rank 5629/6912 dir_acc=0.513). Best config (7,14,3,22,60,50,60) dir_acc=0.553. Money Hands agent НЕ использовать LazyBear-defaults."
metadata: 
  node_type: memory
  type: project
  originSessionId: 5dfe8bf0-bba6-41f4-89b4-4c25014664a4
---

## MH grid screening результаты (2026-05-31, PC2)

6912 configs × walk-forward на BTC 12h horizon. Output: `~/Desktop/output PC2/screening_results.csv`.

### Дистрибуция dir_acc

- mean=0.521, median=0.521, std=0.009 (узкая)
- min=0.491, **max=0.553**
- Параметры MH влияют **скромно** — разница max-min = 6%

### LazyBear canon — плохой выбор

```
LazyBear (9,12,4,14,60,40,81): dir_acc = 0.513
rank = 5629 / 6912 (хуже 81%)
```

### Best per-axis (mean dir_acc)

| Param | LazyBear | Best | Note |
|---|---|---|---|
| bw2_ema1 | 9 | 11 | +0.001 lift |
| bw2_ema2 | 12 | 16 | +0.002 |
| bw2_sma_out | 4 | 5 | +0.002 |
| color_sma | 14 | 22 | +0.001 |
| mf_sma | 60 | **60** ✓ | canon OK |
| **rsi_stoch** | 40 | **50** | **+0.007** ⭐ главный axis |
| stc_stoch | 81 | 60 | +0.002 |

### Top-2 winning configs

```
#1  (7, 14, 3, 22, 60, 50, 60)   dir_acc = 0.5530
#2  (11, 10, 5, 14, 60, 50, 81)  dir_acc = 0.5529
```

## How to apply

При реализации **Money Hands agent** в `~/smc-lib/expert_asvk/agents/money_hands_agent.py`:
- **НЕ использовать** LazyBear-defaults (9,12,4,14,60,40,81)
- **Использовать** `(bw2_ema1=7, bw2_ema2=14, bw2_sma_out=3, color_sma=22, mf_sma=60, rsi_stoch=50, stc_stoch=60)` или альтернативный top-20 config
- Главные axes для будущих экспериментов: `rsi_stoch` (50 vs 40), `bw2_ema2` (16 vs 12), `color_sma` (22 vs 14)

## Caveats

- dir_acc = 0.553 = **5.5% над random на 12h forecast** — модель MH сама по себе **слабая**
- Sequence/temporal signals дают больше чем zone-context features (Phase 4 bb-model AUC 0.510)
- Best MH config (0.553) **сильнее** Phase 4 bb-classifier (0.510)

## Связи

- [[2026-05-31-phase3-results-phase4-force-framework]] — полная сессия с этими результатами
- [[feedback-expert-asvk-multi-agent-architecture]] — где MH agent
