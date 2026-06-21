# Strategy ob_vc v3.3 — LEAN PICKED (production canon)

**Дата принятия канона:** 2026-06-09 (Variant A accepted)
**Setup:** 2h ob_vc (relaxed canon #7)
**Asset:** BTC + ETH (Binance USDT-M)
**ML model:** LightGBM ensemble (3 seeds), hit_RR_20 (RR=2.0)
**Selection:** top-N=1100 events (proba ≥ 0.6088)
**Anchor:** entry_fill_ms (not born_ms — decision-window architecture)

## Performance (6y backtest, 2020-01 → 2026-06)

| | All | BTC | ETH |
|---|---|---|---|
| N selected | 1100 | 306 | 794 |
| WR | 72.4% | 69.3% | 73.6% |
| Σ R | +1288R | +330R | +958R |
| E[R]/trade | +1.17R | +1.08R | +1.21R |
| Max DD | −6R | — | — |
| PBO | 0.55 | — | — |

## Feature pack (22 features)

### 11 wait-window features (computed during [born_ms → entry_fill_ms])

```
fill_delay_min               — delay born→entry
wait_max_high_pct            — max % above entry price
wait_min_low_pct             — min % below entry price
wait_net_move_pct            — close to close move
wait_volume_total            — sum volume in window
wait_volatility_change_pct   — late vs early vol ratio
wait_directional_efficiency  — net move / total path
wait_touched_sl_before_entry — touched SL? (validation gate)
wait_bars_count_15m          — number of 15m bars in window
wait_bars_count_1h           — number of 1h bars
wait_bars_count_4h           — number of 4h bars
```

### 11 HMA dist_pct features (best L per TF — ML-picked from v3.2 permutation)

```
TF   | L  | feature
─────┼────┼────────────────────────────
15m  | 7  | hma_15m_7_dist_pct
20m  | 6  | hma_20m_6_dist_pct
1h   | 4  | hma_1h_4_dist_pct
90m  | 8  | hma_90m_8_dist_pct
2h   | 4  | hma_2h_4_dist_pct     ⭐ strongest HMA overall
4h   | 4  | hma_4h_4_dist_pct
6h   | 6  | hma_6h_6_dist_pct
12h  | 8  | hma_12h_8_dist_pct
1d   | 8  | hma_1d_8_dist_pct
2d   | 8  | hma_2d_8_dist_pct
3d   | 12 | hma_3d_12_dist_pct
```

HMA dist_pct формула: `(price - hma) / hma × 100`

## Entry / SL / TP rules

```
1. ob_vc 2h detected with relaxed canon #7 → born_ms
2. Calculate entry, SL, TP:
   deep = 0.8 if n_FVG >= 2 else 0.2
   LONG:  entry = fvg_hi - deep × (fvg_hi - fvg_lo)
          SL    = drop_lo
          TP    = entry + 2.0 × (entry - SL)         (RR = 2.0)
   SHORT: entry = fvg_lo + deep × (fvg_hi - fvg_lo)
          SL    = drop_hi
          TP    = entry - 2.0 × (SL - entry)
3. Filter: r_pct = abs(entry - SL) / entry × 100; require r_pct >= 0.5%
4. Filter: drop t_id in [T9b, T1a, T7a] (WR < 65% in v3.3)
5. Place limit order at entry, lifetime 14 days
6. At entry_fill_ms — recompute all 22 features
7. VALIDATION GATE: if wait_touched_sl_before_entry == 1 → ABORT at market
8. ML scoring: proba = mean(LightGBM predict_proba over 3 seeds)
9. If proba >= 0.6088 → KEEP trade (hold to SL or TP, no trailing)
   Else → CLOSE at market
10. Trade exit: TP +2R / SL −1R / 14-day timeout (mark-to-market)
```

## Risk management

```
Position sizing:    1% account risk / trade
                    size = 1% / (R% × leverage)
Concurrent trades:  max 3 simultaneously, max 2 same direction
Risk-off triggers:  6 losses straight → 24h pause
                    10% DD → full review
                    -3% daily → stop day
```

## Files

```
data/features_v33_picked.parquet           (canon dataset)
ml_v3/build_features_v33_picked.py         (dataset builder)
ml_v3/run_lean_v33_picked.py               (Mac substudy)
ml_v3/analyze_production_strategy_v33.py   (deep analysis)
ml_v3/plot_production_explanation_v33.py   (dashboard PNG)
charts/plot_2h_classification_24_multi_with_strategy.py
charts/plot_btc_v33_trades.py              (3 trade examples)

PC1 archive: compute-2026-06-09-ob-vc-hma-v33-pc1.zip
PC1 results: ~/Desktop/output4/
```

## Charts

```
~/Desktop/i-rdrb-charts/ob_vc_2h_classification_24_multi_with_strategy.png
~/Desktop/output4/production_strategy_explanation.png
~/Desktop/i-rdrb-charts/btc_v33_trade_W1_long_T1a_2025-03-17.png
~/Desktop/i-rdrb-charts/btc_v33_trade_W2_short_T16_2026-02-01.png
~/Desktop/i-rdrb-charts/btc_v33_trade_L1_long_T4_2024-08-07.png
```

## Per-T-type performance under v3.3 strategy

### 🟢 Top (WR ≥ 75%)
T16 (84%), T5b (82%), T2 (82%), T1b (80%), T5a (79%), T13a (78%), T15a (76%), T13b (75%)

### 🔵 Solid (WR 70-75%)
T12, T4, T8, T10, T15b, T14

### 🟠 Weak (WR 65-70%)
T3a, T3b, T6, T11a, T11b, T7b

### 🔴 Drop candidates (WR < 65%)
**T1a (63.5%), T7a (63.5%), T9b (57.9%)** — рекомендую исключить

## Lineage

```
v3 baseline (53 features)         AUC 0.752  WR 70.5% (RR=1.7)  +995R
  ↓ ML-pick L per TF
v3.2 neighborhood (132 fts → 53)  AUC 0.794  WR 71.4% (RR=2.0)  +1255R  PBO 0.60
  ↓ keep only best L per TF
v3.3 lean (22 fts) ⭐ CANON       AUC 0.797  WR 72.4% (RR=2.0)  +1288R  PBO 0.55
```

## Key references

- Source ob_vc canon: `~/smc-lib/projects/ob-vc/canon.md`
- 24-type classification: `~/smc-lib/projects/ob-vc/scripts/classify_24_eth_sol.py`
- ML pipeline modules: `~/Desktop/compute-archives/compute-2026-06-09-ob-vc-hma-v33-pc1/ml/`
