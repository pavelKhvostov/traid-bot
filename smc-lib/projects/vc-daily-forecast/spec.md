# vc-daily-forecast — spec rev.3 (2026-06-14)

**Status:** Spec rev.3 — finalized after user lock-in on 11-model architecture
**Path:** `~/smc-lib/projects/vc-daily-forecast/`
**Compute:** PC1 (RTX 5070 Ti + Ryzen 7 7700) training; PC2 hourly inference; Mac M5 — только spec/charts/research preview
**Lineage:** Inspired by [[reference-andrey-12h-branch]] etap 156-173 (Williams pivot detection AUC 0.91-0.94); same methodology canon (Lopez Ch.3-19), different target (24h sparse strong-move binary).

## 1. Цель

**11 параллельных ML-моделей** на BTC, инференс каждый 1h close. Outputs:

- **8 sparse binary** — P(strong move ≥X% LONG/SHORT за rolling 24h), thresholds 2/3/4/5%
- **1 multi-output quantile** — q10/q50/q90 of remaining UP & DOWN move в течение 24h
- **1 regime classifier** — 4-class: TREND_UP / TREND_DOWN / ROTATION / CHOP за 24h
- **1 trend continuation** — P(intraday signed-move continues over remaining 24h)

Каждый час trader получает structured snapshot для решения «входить или нет».

## 2. Use case (трейдинг workflow)

1. **Hourly digest**: каждый 1h close — обновлённый prediction snapshot
2. **Level-watch presentation** (rule-based, не ML): список активных OB / FVG / ob_vc уровней не пробитых; их «реakция expected» от core ML (как trader дойдёт к уровню — features меняются, P(strong) пересчитывается автоматически)
3. **Sniper sigals** при P(strong move ≥3% LONG) > 0.7 ИЛИ при confluence нескольких высоких P-уровней
4. **Decision support**: regime + range quantiles + continuation = full daily picture

**Пример output** (формат финального Telegram-style вывода в Phase 6):
```yaml
Snapshot: 2026-06-14 16:00 UTC, BTC price 63817

Regime: ROTATION (0.62) | TREND_UP (0.18) | TREND_DOWN (0.12) | CHOP (0.08)
Direction continuation: P=0.47 (no strong bias)

Strong moves next 24h:
  LONG  ≥2%: 0.78    ≥3%: 0.42    ≥4%: 0.18    ≥5%: 0.07
  SHORT ≥2%: 0.31    ≥3%: 0.12    ≥4%: 0.04    ≥5%: 0.01

Range next 24h:
  UP move:   q10=+0.3%   q50=+1.2%   q90=+3.8%
  DOWN move: q10=-0.2%   q50=-0.7%   q90=-2.4%

Active levels (watching):
  64200 (FVG short 4h, age 8h, P_react=0.55 LONG when touched)
  62450 (ob_vc long 1h × FVG 15m, n_FVG=1, T7, P_react=0.71 LONG when touched)
  60880 (Williams FL 12h, P_react=0.62 LONG when touched)
```

## 3. Architecture: 11 моделей

### Group A — Strong move binary (8 моделей)

Каждая модель = independent LightGBM binary classifier.

| Model | Target |
|---|---|
| `y_long_2pct_24h` | max(high[+1..+24h_bars]) / close[i] - 1 ≥ +2% |
| `y_long_3pct_24h` | то же, threshold +3% |
| `y_long_4pct_24h` | +4% |
| `y_long_5pct_24h` | +5% |
| `y_short_2pct_24h` | close[i] - min(low[+1..+24h_bars]) / close[i] ≥ 2% |
| `y_short_3pct_24h` | 3% |
| `y_short_4pct_24h` | 4% |
| `y_short_5pct_24h` | 5% |

**Notes:**
- Inference bar resolution = **1h** (24 prediction snapshots/день)
- Look-ahead window = **24 × 1h-bars = 24 hours**
- Each model trained independently with own LightGBM hyperparams
- Sample weights: Lopez Ch.4 `uniqueness × |return|` per target
- Probability calibration: isotonic per model

### Group B — Range quantile regression (1 multi-output модель)

Один LightGBM model с 6 outputs (multi-target quantile). Альтернатива — 6 раздельных моделей; в spec — multi-output, проще maintain.

| Output | Target |
|---|---|
| `range_up_q10` | quantile-10% of max_high[+24h] / close[i] - 1 (i.e., conservative UP estimate) |
| `range_up_q50` | median |
| `range_up_q90` | 90th percentile (rare big UP) |
| `range_down_q10` | quantile-10% of (close[i] - min_low[+24h]) / close[i] |
| `range_down_q50` | |
| `range_down_q90` | |

**Objective:** pinball loss per quantile (LightGBM `objective='quantile'`).
**Validation:** pinball loss on holdout, calibration curve.

### Group C — Context (2 моделей)

#### C1. Regime classifier
- 4-class: TREND_UP, TREND_DOWN, ROTATION, CHOP
- LightGBM multiclass + Platt calibration
- Target labelling (TBD methodology, see §6 open questions): combination of frac-diff stationarity + ATR z-score + directional ranking

#### C2. Trend continuation
- Binary: `signed_move_remaining_24h × sign(intraday_move_so_far_today) > 0`
- LightGBM binary
- Triggered only when intraday move > 0.3% (otherwise undefined)

## 4. Feature catalog (~1845 фич, shared across all 11 models)

### Group 1 — MA family (480)
8 TFs (15m, 1h, 2h, 4h, 6h, 12h, 1d, 1w) × 3 семейства (MA, EMA, **HMA LIVE**) × 5 ключевых периодов × 4 атрибута (`dist_norm`, `slope_5`, `slope_sign`, `pos_rank`).

**5 ключевых периодов** (locked at Phase 1):
- 15m/1h: 20, 50, 100, 200, 500
- 2h/4h/6h: 20, 50, 100, 200, 500
- 12h/1d: 10, 20, 50, 100, 200
- 1w: 10, 20, 50, 100, 200

⚠ HMA partial-bar canon: per [[feedback-hma-live-per-tf-at-entry]] — каждый TF LIVE с 1m partial.

### Group 2 — SMC element panel (~608)
**Все 16 элементов** на 8 TF (user lock #7):
- Zone-элементы (12) × 8 TF × 4 фичи (dist_bull, dist_bear, age_bull, age_bear) = **384**
- State/event-элементы (4: breaker, choch, mitigation, inducement) × 8 TF × 6 фич (last_dir, bars_since_last, count_24h, count_72h, is_active_bull, is_active_bear) = **192**
- Event-flag фичи для (rdrb, i_rdrb, marubozu, choch) × 8 TF × 1 binary (`fired_at_close + bars_since_fire`) = **32**

### Group 3 — Anatomy (80)
8 TF × 10 фич: body_ratio, upper_wick_ratio, lower_wick_ratio, wick_asymmetry, range_atr, direction, close_position, gap_prev, body_to_atr, range_z50.

### Group 4 — SEQ stats (80)
8 TF × 10 фич: consec_same_color, body_expansion_5, bullish_ratio_20, max_body_rank_50, range_rank_50, close_in_range_20, volume_ratio_5_vs_20, high_break_age_50, low_break_age_50, swing_count_50.

### Group 5 — NMA (32)
8 TF × 4 фичи: atr_14_norm, rsi_14, rsi_bars_since_fresh_exit, volume_zscore_50.

### Group 6 — VWAPs ASVK (32)
8 anchors из fractals: 4h_FH, 4h_FL, 6h_FH, 6h_FL, 12h_FH, 12h_FL, 1d_FH, 1d_FL × 4 фичи (vwap_dist, vwap_slope_20, vwap_touch_count, vwap_age_h).
Recipe: [[feedback-anchored-vwap-from-fractals]].

### Group 7 — Money Hands ASVK (40)
8 TF × 5 фичи: mh_state, mh_mf, mh_n4, mh_cascade, mh_dir_acc.
Config: (7, 14, 3, 22, 60, 50, 60) [[mh-screening-best-config-not-lazybear]].

### Group 8 — Lopez microstructure (15)
- `lopez_amihud`, `lopez_amihud_zscore`
- `lopez_vpin`, `lopez_roll_spread`
- `lopez_parkinson`, `lopez_gk_vol`, `lopez_parkinson_vs_atr`, `lopez_gk_vs_cc`
- `lopez_fracdiff_d04`, `lopez_fracdiff_d03`
- `lopez_sadf`, `lopez_sadf_explosive`, `lopez_sadf_steady`

### Group 9 — VSA + Nison + Wyckoff + Doji + Bulkowski (~48)
- VSA cluster (8): no_demand, no_supply, stopping_vol, absorption, effort_no_result, test_bar, climax_bull/bear
- VSA context (5): vol_ud_ratio, climax_memory, smart_money, vol_zscore_session
- Wyckoff (4): phase_accum, phase_markup, phase_distrib, phase_markdown
- Nison candles (12): hammer, hanging_man, shooting_star, inv_hammer, engulfing×2, harami×2, morning/evening_star, harami_cross, cloud_penetration
- Doji (6): is, gravestone_at_top, dragonfly_at_bottom, long_legged, after_long_white, rarity_30d
- Bulkowski top-5 (10): big_w, db_eve_eve, v_bottom, hs_bottom, big_m → fired + bars_since per pattern

### Group 10 — Confluence score (2)
- `confluence_score` (0-10) — Nison-style count of agreement across groups
- `confluence_zones_at_price` — count zones overlap at current price

### Group 11 — Macro (~25)
- USDT.D (6): returns_1d/3d/7d, above_ema50, ema50_dist, rsi14
- TOTALES (6): то же (альт-капитализация без стейблов)
- SPX/BTC ratio (6): то же + `current_zone_label` (accumulation/distribution) — берётся из user-разметки layout «Вадим» (Phase 2)
- SPX standalone (7): returns_1d/7d/30d, above_ema50, ema50_dist, rsi14, vs_BTC_correlation_30d

### Group 12 — Session features (24)
Asian / London / NY активность, overlaps, opens/closes, funding ticks, daily/weekly anchors, volume/range z-scores per session. Полный список §6.

### Group 13 — Bollinger compression (5)
- `bb_width_percentile_1y_1h` / `_4h` / `_1d` / `_1w` (4 ключевых TF)
- `bb_compression_active` (boolean, percentile < 0.20 на 1d)

### Group 14 — Divergences (~296)
**4 oscillators** (RSI, MACD, OBV, AO) × **6 TF** (1h, 2h, 4h, 6h, 12h, 1d) × **4 типа** (reg_bull, reg_bear, hidden_bull, hidden_bear) × **3 фичи** (fired_at_close, bars_since_fire, magnitude) + 8 meta (confluence, n_active_24h, majority_dir и др.).

### Group 15 — Funding rate (6)
Binance perpetual: current, 24h avg, 7d avg, z-score_60d, divergence_sign, cumulative_7d. Per-snapshot.

### Group 16 — Volume Profile / POC (~30)
Per anchor period: day, week, month, quarter, naked-POC. Per anchor (6 фич): dist_to_POC, dist_to_VAH, dist_to_VAL, is_inside_value_area, naked_POC_count, dist_to_nearest_naked_POC.

### Group 17 — Event meta (ob_vc-specific, 9)
- `nearest_ob_vc_active_dist` / `_age` / `_n_FVG` / `_type_T` / `_swept` / `_extreme` / `_strict_detect_lag` / `_is_at_entry_zone` / `_HTF`

### Group 18 — Wait window (10)
Per [[feedback-wait-window-before-entry-analyzed]]: wait_bars_since_birth, wait_max_high_pct, wait_min_low_pct, wait_net_move_pct, wait_touched_zone_count, wait_touched_sl_before_entry, wait_volume_zscore, wait_ratio_in_zone, wait_rsi_1h_current, wait_volatility.

### Group 19 — Sweep magnitude (Andrey-style, ~9)
- `sweep_BSL_mag_24h_pct`, `sweep_SSL_mag_24h_pct`
- `sweep_BSL_24h`, `sweep_SSL_24h` (binary)
- `sweep_BSL_failed_24h`, `sweep_SSL_failed_24h`
- Per window 24h/72h/168h variants — приоритет 24h, остальные опц.

### Group 20 — Vadim sweep / maxV / Sniper composite (Andrey etap_173 add-ons, 14)
- Vadim zone-sweep[i] features (8): per class (OB / FH-FL) × tf (12h/1d) × dir (LONG/SHORT)
- Vadim maxV(i-1) C2 features (4)
- Vadim Sniper composite (2): HH/LL binary

**Total ≈ 1845 фич** (точное число локнем после Phase 1 implementation).

## 5. Validation methodology (Lopez canon)

| Step | Применение | Источник |
|---|---|---|
| **Ch.3** Triple-barrier labeling | Не применяется напрямую (наш target = simple binary), но Lopez framework берём | Andrey etap 169 |
| **Ch.4** Sample weights | uniqueness × \|return\| per target; добавляем **time decay** weight (user lock #13) — exponential decay со полупериодом 1-2y | Andrey 170 |
| **Ch.5** Frac-diff d=0.4, d=0.3 | stationary close с памятью | 170 |
| **Ch.7** Purged K-Fold | 5-fold; embargo=14 baras (на 1h cadence = 14h, на 24h target = ~14×1h после fold end) | 170 |
| **Ch.17** SADF | structural break как feature (Group 8) | 170 |
| **Ch.19** Microstructure | Amihud/VPIN/Roll/Parkinson/GK (Group 8) | 170 |

**Splits:**
- Train: 2020-01-01 → 2024-12-31 (5y) — **~43,800 1h snapshots** для BTC
- OOS Holdout: 2025-01-01 → 2026-05-31 — **~12,500 snapshots**
- Sample/feature ratio = ~24:1 (отличный)

**Per-target calibration:**
- Isotonic regression на validation fold
- Per-regime calibration (user lock #14): отдельная calibration map per (regime, head)

**Conformal prediction (user lock #16):**
- Wrap range quantile model — output calibrated intervals
- Alpha = 0.10 (90% coverage interval)

**Forecast revision tracking (user lock #15):**
- Log per-bar predictions
- Audit: `forecast[t+1] - forecast[t]` distribution
- Anomaly: |Δforecast| > N×std → flag

**Ablation per feature group (user lock #17):**
- Phase 2 — обязательный шаг
- Для каждой группы 1-20: leave-one-out → measure ΔAUC per target
- Final feature set: только группы с ≥ +0.005 ΔAUC на ≥3 targets

## 6. Open questions (Phase 0 → Phase 1 lock)

| # | Question | Текущий tentative answer |
|---|---|---|
| 1 | Какие 5 ключевых MA-периодов per TF | Listed в §4 Group 1, finalize after Phase 1 ablation |
| 2 | Regime labels — как генерируются | Lock в Phase 1: combo (ATR_zscore 1d + frac_diff stationarity + signed_close_change 5d) → 4 buckets через K-means + user-rule sanity check на ~30 manual examples |
| 3 | Horizon: 24h fixed или multi (12h/24h/48h) | **24h locked** (user 2026-06-14: «горизонт на день-два»); multi-horizon как Phase 4 extension если ablation покажет marginal lift |
| 4 | Anchor: 12h close × 2/день или 1 | Не релевантно — наш cadence 1h close |
| 5 | BTC only или BTC+ETH parallel | **BTC only locked** (user 2026-06-14) |
| 6 | TCN потоки — отдельный head или embed | **Откладываем на Phase 5** — tabular baseline → потом neural lift test |
| 7 | Trade layer (Phase 5) — обязателен или optional | Optional — main goal = forecast quality, trade layer = downstream presentation |

## 7. Phase plan

| Phase | Goal | Compute | Срок |
|---|---|---|---|
| **0** | Spec rev.3 lock (done) | Mac | ✅ |
| **1** | Reproduce Andrey base on BTC 12h → confirm AUC ~0.92 на 3-5% pivot targets. Sanity check pipeline (Lopez, Purged K-Fold, etc.) | PC1 | 5-7d |
| **2** | Migrate target к 24h-rolling sparse binary (8 targets ≥2/3/4/5% LONG/SHORT) на 1h cadence. Build Group 1-11 features. Train 8 binary + range quantile + regime + continuation = 11 моделей baseline | PC1 | 10-14d |
| **3** | **Per-group ablation** — каждая группа фич in/out → ΔAUC per target. Lock финальный feature set (probably ~500-1000 фич остаётся) | PC1 | 5-7d |
| **4** | Calibration (isotonic + per-regime), conformal prediction wrapper, forecast revision tracking. Multi-horizon extension test (12h+24h+48h) | PC1 | 5-7d |
| **5** | TCN neural head test поверх Group A binary. Ensemble lift measurement | PC1 | 7-10d |
| **6** | Live inference deployment на PC2 + Telegram-style output synthesis + level-watch presentation layer | PC2 | 3-5d |

**Total estimated: 5-7 недель** до production-ready system.

## 8. Decisions locked (полный список 2026-06-14)

| # | Решение | Источник |
|---|---|---|
| 1 | Variant A (new project from scratch, not fork of Andrey) | User: «я за новый проект» |
| 2 | MA/EMA/HMA сокращены до 5 ключевых периодов per TF | User: «3-5 ключевых периодов согласен» |
| 3 | Heavy compute (PC1 RTX 5070 Ti + PC2) — не лениться | User: «у меня в разы больше вычислительной мощности» |
| 4 | Macro: USDT.D + TOTALES + SPX/BTC + SPX standalone | User: «Totales работает не хуже USDT.D» + см. №18 |
| 5 | Lopez canon обязателен (Ch.3/4/5/7/17/19) | Andrey AUC 0.92 = доказан |
| 6 | Architecture: 11 параллельных моделей (НЕ multi-head) | User 2026-06-14: «давай 11 моделей» |
| 7 | Все 16 SMC элементов на 8 TF (~608 фич) | User: «мы не ленимся. Используем все 16 элементов» |
| 8 | Session features обязательны (~24) | User: «учитываем сессии разных бирж» |
| 9 | TOTALES обоснование: только криптоактивы без стейблкойнов | User explanation |
| 10 | Bollinger compression/squeeze (~5) | User: «9 да» |
| 11 | Multi-horizon forecast — extension в Phase 4 | User: «10 да» |
| 12 | Asset stratified CV folds | User: «21 да» (отменено №24, теперь BTC only) |
| 13 | Time decay sample weights | User: «22 да» |
| 14 | Calibration per regime | User: «23 да» |
| 15 | Forecast revision tracking | User: «24 да» |
| 16 | Conformal prediction для range head | User: «25 да» |
| 17 | Ablation per feature group obligatory Phase 3 | User: «26 да» |
| 18 | SPX/BTC ratio (`SP:SPX/CRYPTOCAP:BTC`, layout «Вадим») | User: «есть мой любимый график» |
| 19 | Divergences Medium scope (~296) | User: «осцилляторы на 1h 2h 4h 6h 12h D применяем» |
| 20 | Funding rate (~6) | User: «funding rate если на всех ТФ то полезно» |
| 21 | Volume profile / POC (~30) | User: «volume profile если смотреть на всех ТФ очень полезно» |
| 22 | TradFi SPX standalone (~7) | User: «SPX можно добавить» |
| 23 | SKIP: OI, Liquidations, BTC.D, Halving, DXY, VIX | User explicit reject [[feedback-macro-features-preference]] |
| 24 | Asset = BTC only (NO ETH, NO SOL) | User 2026-06-14: «только BTC» |
| 25 | Inference cadence = 1h close (24× в день) | User: «каждый час я могу поинтересоваться ожиданиями» |
| 26 | Target horizon = 24h rolling | User: «горизонт на день-два» |
| 27 | Target thresholds 4 уровня: ≥2/3/4/5% (не 3/4/5 как Andrey) | User: «таргет для меня будет достаточен >2% движения цены» |
| 28 | НЕ multi-stage architecture — single model на бар, level-watch — presentation layer | User: «а разве у Андрея не такая логика была?» — поправка |
| 29 | Level-watch list — rule-based presentation, ML интегрирована через features | Andrey-canon |
| 30 | НЕ разделять «level detection» от «move prediction» — joint target (Andrey-style) | User clarified: «strong level + reaction = одно событие» |

## 9. Related memory

- [[reference-andrey-12h-branch]] — base pipeline reference
- [[project-vc-ml-predictor]] — параллельная ветка (ob_vc TBM, deprecated в пользу этого проекта)
- [[project-skolzyashie]] — parent reference для feature catalog architecture
- [[feedback-ob-vc-n-fvg-per-ltf]] — per-LTF канон для ob_vc events feature
- [[feedback-ob-vc-entry-rule-deep]] — entry canon (для level-watch presentation)
- [[feedback-hma-live-per-tf-at-entry]] — HMA partial-bar canon
- [[feedback-htf-anchor-global-rule]] — 03:00 MSK anchor
- [[feedback-ml-lookahead-must-verify]] — lookahead audit obligatory
- [[feedback-all-compute-on-pc1]] — heavy ML на PC1
- [[feedback-phase3-inference-on-pc2]] — inference на PC2
- [[mh-screening-best-config-not-lazybear]] — MH config canon
- [[feedback-anchored-vwap-from-fractals]] — VWAPs ASVK recipe
- [[feedback-spx-btc-ratio-favorite]] — SPX/BTC ratio layout «Вадим»
- [[feedback-macro-features-preference]] — macro features whitelist/blacklist
- [[feedback-wait-window-before-entry-analyzed]] — wait window features canon

## 10. Files structure

```
~/smc-lib/projects/vc-daily-forecast/
├── spec.md                  ← THIS file (rev.3)
├── decisions.md             ← lock-in log per decision
├── pipeline.md              ← data flow + feature build steps
├── feature-catalog.md       ← detailed per-feature spec (Phase 1)
├── README.md                ← user-facing summary
├── detector/                ← rule-based: SMC elements, ob_vc, levels, sessions
├── features/                ← feature build scripts per group (Phase 1)
├── labels/                  ← target generation per head
├── training/                ← model training scripts (LightGBM per model)
├── analysis/                ← ablation, calibration, conformal scripts (Phase 3+)
├── results/                 ← saved models, predictions, metrics
└── live/                    ← Phase 6 — PC2 hourly inference + Telegram output
```

## 11. Next step

Phase 1 start. Готов к:
1. Setup `~/smc-lib/projects/vc-daily-forecast/` repository structure
2. Bootstrap pipeline: data loaders для BTC 1m + macros + sessions
3. Reproduce Andrey's etap_171 на BTC 12h (sanity check)
4. Migrate target к 24h-1h cadence
5. Build first features → train baseline 11 models

User confirm — go ahead with Phase 1?
