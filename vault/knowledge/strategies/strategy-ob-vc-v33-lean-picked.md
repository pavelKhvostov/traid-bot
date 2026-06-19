---
tags: [strategy, ob_vc, ml, hma, deprecated, lookahead]
date: 2026-06-09
status: ⚠️ DEPRECATED — built on lookahead bug
related: [[strategy_1_1_1]] [[ob-vc-hma-features-lookahead-fix]] [[2026-06-09-ob-vc-ml-lookahead-bug-honest-results]]
---

# Strategy ob_vc v3.3 — LEAN PICKED (⚠ DEPRECATED — lookahead иллюзия)

## ⚠️ КРИТИЧНО: НЕ ИСПОЛЬЗОВАТЬ В LIVE

**v3.3 production canon построен на lookahead bug в HMA features**. Цифры ниже — иллюзия.

```
v3.3 reported (lookahead):  WR 72.4%, Σ +1288R, AUC 0.79
v3.3 honest (after fix):    WR ~38%, Σ ~+50R, AUC 0.54
                            ↑ это реальность для live торговли
```

Bug в `hma_at_entry.py:80-87` — использовал `closes[idx_at_event]` где idx = бар СОДЕРЖАЩИЙ entry_ms (не закрытый), таким образом читая FINAL close in-progress бара (до 72h в будущем для 3d TF). См. [[ob-vc-hma-features-lookahead-fix]].

**Замена**: honest INTRADAY partial-bar fix в `hma_at_entry_honest.py`. См. session note [[2026-06-09-ob-vc-ml-lookahead-bug-honest-results]] для production walk-forward результатов.

---

## Historical content (для archeology — не для использования)

ML-based 2h ob_vc strategy на BTC + ETH. **Принят как production canon 2026-06-09**
(Variant A accepted после полного PC1 pipeline) — позднее **deprecated** после обнаружения lookahead.

## TL;DR

```
Setup:     2h ob_vc (relaxed canon #7)
Assets:    BTC + ETH
Features:  22 (11 wait-window + 11 HMA ML-picked)
Target:    hit_RR_20 (RR=2.0)
Threshold: proba ≥ 0.6088
Selection: top-N = 1100 events (6y)

Performance:
  WR        72.4%
  Σ R       +1288R / 6y (≈ +215R/year, RR=2.0)
  E[R]      +1.17R/trade
  Max DD    −6R
  PBO       0.55
  ETA       ~14 trades/month
```

## Architecture — entry_fill_ms anchor

Ключевая особенность: **признаки рассчитываются НЕ в born_ms (когда ob_vc сформировался), а в entry_fill_ms** (когда цена коснулась entry).

```
T_born ── DECISION WINDOW ── T_entry_fill ── TBM PHASE ── T_exit
                ↑
        ML scoring HERE
```

Это даёт +0.12 AUC vs обычной born-anchor архитектуры — ML видит реальное поведение
рынка от формирования паттерна до точки входа.

## 22 features

### 11 wait-window (computed во время [born → entry])

```
fill_delay_min, wait_max_high_pct, wait_min_low_pct, wait_net_move_pct,
wait_volume_total, wait_volatility_change_pct, wait_directional_efficiency,
wait_touched_sl_before_entry, wait_bars_count_15m, wait_bars_count_1h,
wait_bars_count_4h
```

Топ-3 по permutation importance: `wait_max_high_pct (0.057)`, `wait_min_low_pct (0.041)`,
`wait_net_move_pct (0.028)`.

### 11 HMA dist_pct (ML-picked best L per TF)

| TF | L | importance |
|---|---|---|
| **2h** | **4** | **0.025** ⭐ strongest HMA |
| 4h | 4 | 0.021 |
| 12h | 8 | 0.031 |
| 6h | 6 | 0.057 (#2 overall!) |
| 1d | 8 | 0.017 |
| 2d | 8 | 0.017 |
| 3d | 12 | 0.012 |
| 15m | 7 | 0.011 |
| 1h | 4 | 0.005 |
| 90m | 8 | 0.005 |
| 20m | 6 | 0.004 |

**Главное открытие:** короткие L (4-7) на коротких TF (1h-4h), L=8 на дневных,
L=12 на 3d. Старый канон L=9 на всех TF — НЕ оптимален.

## Entry / SL / TP rules

```
1. Detect ob_vc 2h with relaxed canon #7 → born_ms
2. Compute:
   deep = 0.8 if n_FVG >= 2 else 0.2
   LONG:  entry = fvg_hi - deep × (fvg_hi - fvg_lo)
          SL    = drop_lo
          TP    = entry + 2.0 × (entry - SL)
   SHORT: mirror
3. Filter: r_pct >= 0.5% (futures viable)
4. Filter: drop t_id ∈ [T1a, T9b, T7a] (WR < 65%)
5. Place limit order, lifetime 14 days
6. At entry_fill_ms — recompute 22 features
7. VALIDATION: if wait_touched_sl_before_entry → ABORT at market
8. ML scoring: proba = avg(LightGBM × 3 seeds)
9. If proba >= 0.6088 → KEEP (hold to SL/TP)
10. Else → CLOSE at market
```

## Risk management

```
Position size:   1% account risk / trade
Concurrent:      max 3 simultaneous, max 2 same direction
Pause triggers:  6 losses streak → 24h pause
                 10% DD → full review
                 −3% daily → stop day
```

## Performance breakdown

| Group | N | WR | Σ R |
|---|---|---|---|
| **All (BTC+ETH)** | 1100 | 72.4% | **+1288R** |
| BTC | 306 | 69.3% | +330R |
| **ETH** | 794 | **73.6%** | **+958R** ⭐ |
| LONG | 593 | 71.7% | +682R |
| SHORT | 507 | 73.2% | +606R |
| Pre-2023 | 562 | 72.2% | +656R |
| Post-2023 | 538 | 72.5% | +632R |

### By year

| Year | N | WR |
|---|---|---|
| 2020 | 140 | 75.7% |
| 2021 | 209 | 71.3% |
| 2022 | 213 | 70.9% |
| **2023** | **114** | **57.9%** ⚠ FTX consolidation |
| 2024 | 177 | 75.1% |
| 2025 | 185 | 76.2% |
| 2026 | 62 | 80.6% |

2023 — единственный weak year. Возможно стоит добавить regime gate
(global vol / BTC.D) как future filter.

## Per T-type performance (24 типа)

### 🟢 Top (WR ≥ 75%)
T16 (84%), T5b (82%), T2 (82%), T1b (80%), T5a (79%), T13a (78%), T15a (76%), T13b (75%)

### 🔵 Solid (WR 70-75%)
T12, T4, T8, T10, T15b, T14

### 🟠 Weak (WR 65-70%)
T3a, T3b, T6, T11a, T11b, T7b

### 🔴 Drop candidates (WR < 65%)
**T1a (63.5%), T7a (63.5%), T9b (57.9%)**

## Lineage

| Version | Features | AUC | WR @ N=1100 | Σ R | PBO |
|---|---|---|---|---|---|
| v3 baseline | 53 (L=9) | 0.752 | 70.5% (RR=1.7) | +995R | 0.40 |
| v3.2 neighborhood | 132 → 53 | 0.794 | 71.4% (RR=2.0) | +1255R | 0.60 |
| **v3.3 lean ⭐** | **22 picked** | **0.797** | **72.4% (RR=2.0)** | **+1288R** | **0.55** |

## Alternative RR picks (tradeoffs)

| RR | WR | E[R]/trade | Σ R | Use case |
|---|---|---|---|---|
| 1.4 | 78.7% | +0.89R | +978R | Max WR (psychological comfort) |
| 1.7 | 75.3% | +1.03R | +1136R | Balanced "sweet spot" |
| **2.0** | **72.4%** | **+1.17R** | **+1288R** | **Max profit (current canon)** |

## Smaller-N premium pickы (alternative thresholds)

```
hit_RR_28 N=700   WR=70.1%  E[R]=1.67R  Σ=+1166R   🔥 elite EV
hit_RR_25 N=800   WR=70.0%  E[R]=1.45R  Σ=+1160R
hit_RR_23 N=850   WR=70.6%  E[R]=1.33R  Σ=+1130R
hit_RR_20 N=1300  WR=70.2%  E[R]=1.11R  Σ=+1439R   max Σ R
hit_RR_14 N=2150  WR=70.1%  E[R]=0.68R  Σ=+1469R   max volume
```

## ⚠ Caveats

1. **PBO = 0.55** — не дотянули до < 0.50. Ranking стратегий в-/out-sample
   менее стабилен чем у v3 baseline. Re-train annually recommended.
2. **2023 weak** (WR 57.9%) — strategy чувствительна к consolidation regimes.
3. **L per TF (4, 6, 7, 8, 12)** — найдены на исторических данных,
   могут дрейфовать через 2-3 года.
4. **BTC short** — weakest sub-segment в v3 (0.78 AUC), частично исправлен в v3.3.

## Files

```
Library:    ~/smc-lib/strategies/strategy_ob_vc_v33_lean_picked/
  ├─ README.md
  ├─ features_v33_picked.parquet
  ├─ build_features_v33_picked.py
  ├─ run_lean_v33_picked.py
  ├─ analyze_production_strategy_v33.py
  ├─ plot_production_explanation_v33.py
  ├─ plot_2h_classification_24_multi_with_strategy.py
  └─ plot_btc_v33_trades.py

PC1:        ~/Desktop/compute-archives/compute-2026-06-09-ob-vc-hma-v33-pc1.zip
Results:    ~/Desktop/output4/

Charts:     ~/Desktop/i-rdrb-charts/
  ├─ ob_vc_2h_classification_24_multi_with_strategy.png  (24 types + strategy row)
  ├─ btc_v33_trade_W1_long_T1a_2025-03-17.png            (LONG winner)
  ├─ btc_v33_trade_W2_short_T16_2026-02-01.png           (SHORT winner)
  └─ btc_v33_trade_L1_long_T4_2024-08-07.png             (LONG loser)
```

## Related

- [[strategy_1_1_1]] — alternative cascade-based strategy
- [[ob_vc_canon_relaxed_7]] — underlying setup spec
- [[24-type classification]] — t_id taxonomy
