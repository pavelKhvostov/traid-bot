# Feature Catalog — vc-ml-predictor

Полный список features для ML модели. Все features computed **LIVE** (no lookahead, partial-bar HMA where applicable).

## Tabular features (~2300 + 72 new)

### Group 1: MA family (same as ma-rr-predictor)

**Tokens:** 480 (8 TFs × 3 families × 20 periods)

| TF | Families | Periods |
|---|---|---|
| 15m, 1h, 2h, 4h, 6h, 12h, 1d, 1w | MA, EMA, **HMA (LIVE)** | 10, 20, ..., 200 |

Per token: `dist_norm`, `slope_5`, `slope_sign`, `pos_rank` (4 features = 1920 total)

**🚨 CRITICAL:** HMA на каждом TF считается LIVE с partial-bar update — см. [[feedback-hma-live-per-tf-at-entry]]. 
Использовать `hma_at_entry_honest.py` (НЕ `hma_at_entry.py` который имеет lookahead bug).

### Group 2: SMC (same)

**Tokens:** 56 (8 TFs × 7 elements)

Elements: FVG, iFVG, OB, OB_LIQ, OB_VC, i_RDRB, Williams

Per token: `dist_bull`, `dist_bear`, `age_bull`, `age_bear` (4 = 224 total)

### Group 3: Anatomy (same)

**Tokens:** 8 (per TF)

Per token (10 features): body_ratio, upper_wick_ratio, lower_wick_ratio, wick_asymmetry, range_atr, direction, close_position, gap_prev, body_to_atr, range_z50

### Group 4: SEQ stats (same)

**Tokens:** 8

Per token (10 features): consec_same_color, body_expansion_5, bullish_ratio_20, max_body_rank_50, range_rank_50, close_in_range_20, volume_ratio_5_vs_20, high_break_age_50, low_break_age_50, swing_count_50

### Group 5: NMA (same)

**Tokens:** 8

Per token (4 features): atr_14_norm, rsi_14, rsi_bars_since_fresh_exit, volume_zscore_50

### Group 6: Meta (existing + extended)

- `IS_ETH` (1)
- `regime_BULL` / `regime_BEAR` / `regime_CHOP` (3 one-hot)

### Group 7: ⭐ NEW — VWAPs ASVK

Per [[feedback-anchored-vwap-from-fractals]]:
- N_FRACTAL=2 anchor (свежий 2-fractal pivot)
- Multi-TF anchors из FH/FL fractals

**Anchors (8 total):**
- 4h FH (latest swept FH on 4h)
- 4h FL (latest swept FL on 4h)
- 6h FH, 6h FL
- 12h FH, 12h FL
- 1d FH, 1d FL

**Tokens:** 8 (one per anchor)

Per token (4 features):
- `vwap_dist` — price distance to VWAP (normalized by ATR-14 1h)
- `vwap_slope_20` — VWAP slope over last 20 bars (bp / bar)
- `vwap_touch_count` — # touches since anchor
- `vwap_age_h` — hours since anchor

**Total:** 8 × 4 = 32 features

**Source recipe:**
- N_FRACTAL = 2 (anchor требует 2-bar fractal sweep)
- VWAP computed cumulative from anchor: `sum(typical_price × volume) / sum(volume)`
- typical = (H + L + C) / 3
- Per TF anchor → cumulative from anchor → display on TF-1 (1h chart)
- Reds/Greens gradient (Reds for resistance VWAPs, Greens for support)

### Group 8: ⭐ NEW — Money Hands ASVK

Per [[mh-screening-best-config-not-lazybear]]:
- Config best: (7, 14, 3, 22, 60, 50, 60)
- Key axes: rsi_stoch=50, mf=smoothed

**Tokens:** 8 (one per TF)

Per token (5 features):
- `mh_state` — color/state integer (0=red, 1=yellow, 2=green based on cascade)
- `mh_mf` — money flow smoothed (0-100, like RSI variant)
- `mh_n4` — N4 oscillator (4-period composite)
- `mh_cascade` — cascade resonance score (0-100)
- `mh_dir_acc` — directional accuracy historical proxy

**Total:** 8 × 5 = 40 features

**Source recipe:**
- 7 params: n1=7, n2=14, n3=3, n4=22, mf_window=60, rsi_stoch=50, smoothing=60
- Color logic: green if mf>50 AND cascade>0; red if mf<50 AND cascade<0
- LazyBear original НЕ используем (worse per memory). Use ASVK config.

### Group 9: ⭐ NEW — ob_vc-specific meta features

These attached to each event (not multi-TF):

| Feature | Description | Type |
|---|---|---|
| `event_HTF` | 1h or 2h | int (1 or 2) |
| `event_n_FVG` | 1 or ≥2 | int |
| `event_swept` | Williams 5-fractal sweep | bool |
| `event_extreme` | prev or cur | int (0 or 1) |
| `event_type_T` | T1-T16 mapping | int (1-16) |
| `event_FVG_total_size` | combined FVG zone width in ATR-1h | float |
| `event_OB_size` | OB zone width in ATR-1h | float |
| `event_age_to_c3` | bars from c1 to c3 | int |
| `event_swept_n_fractals` | count of swept Williams fractals (1-5 lookback) | int |

**Tokens:** 1 (single "EVENT_META" token with 9 features)

### Group 10: ⭐ NEW — Wait Window Features (CRITICAL)

Per [[feedback-wait-window-before-entry-analyzed]] — обязательны для оценки качества setup.

Each candidate entry (1h bar in [t_birth, t_entry]) gets these computed **from t_birth до t (candidate)**:

| Feature | Description | Type |
|---|---|---|
| `wait_bars_since_birth` | hours since ob_vc formation (0...48) | int |
| `wait_max_high_pct` | max price excursion вверх (нормализован width zone) | float |
| `wait_min_low_pct` | max price excursion вниз | float |
| `wait_net_move_pct` | (current_price - zone_midpoint) / zone_width | float |
| `wait_touched_zone_count` | сколько раз price касался zone (mitigation count) | int |
| `wait_touched_sl_before_entry` | bool — был ли pre-trigger SL touch | bool |
| `wait_volume_zscore` | volume vs 50-bar baseline во время wait | float |
| `wait_ratio_in_zone` | доля баров в zone vs outside | float |
| `wait_rsi_1h_current` | RSI-14 на 1h в момент candidate | float |
| `wait_volatility` | mean(range/ATR_14_1h) во время wait | float |

**Tokens:** 1 ("WAIT_STATE" token × 10 features)

**Канон:** all wait features computed **strictly LIVE** — no lookahead.

### Why this is critical:

ML uses wait_window features чтобы **различать setups** где:
- ✅ Price «ждёт» entry правильно (low volatility, no SL touch, narrow consolidation)
- ❌ Price ушёл далеко от zone и returns may be «ловушка»
- ✅ Multiple touches без break = strong validation
- ❌ Single touch with deep wick = potential failure

## Sequence features (TCN) — same as skolzyashie

7 OHLCV streams:
- 15m × 256 bars
- 1h × 128
- 2h × 96
- 4h × 64
- 6h × 64
- 12h × 64
- 1d × 64

Pre-cached as memmap (same canon).

## Summary

| Group | Tokens | Features per token | Total features |
|---|---|---|---|
| MA family | 480 | 4 | 1920 |
| SMC | 56 | 4 | 224 |
| Anatomy | 8 | 10 | 80 |
| SEQ stats | 8 | 10 | 80 |
| NMA | 8 | 4 | 32 |
| Meta (IS_ETH + regime) | 2 | varied | 4 |
| **VWAPs ASVK ⭐** | **8** | **4** | **32** |
| **Money Hands ASVK ⭐** | **8** | **5** | **40** |
| **Event meta ⭐** | **1** | **9** | **9** |
| **Wait Window ⭐** | **1** | **10** | **10** |
| **TOTAL** | **580 tokens** | — | **2431 features** |

vs ma-rr-predictor: 2337 features → vc-ml-predictor: 2431 features (+94 from new groups)

## Live computation rules (mandatory canon)

1. **HMA** на каждом TF: partial-bar update via `hma_at_entry_honest.py`
2. **MA / EMA** на каждом TF: closed bars only (no partial)
3. **SMC elements** detected at closed bars only
4. **VWAPs ASVK** anchors могут update incrementally (live integration)
5. **Money Hands** на partial-bar at entry TF (1h or 2h depending on event)
6. **Regime** — based on closed D bars only

## NaN handling

- Pre-EMA warmup (early periods) → NaN → clip to 0 with mask track
- Missing FVGs (no recent anchor for VWAPs) → NaN → indicator feature (`anchor_exists` bool)
- Numeric clipping: features clipped to [-50, 50] before standardization

## Audit requirement

Каждая новая feature группа должна пройти `no_lookahead.py` audit:
```python
feature(t, data) == feature(t, data + future_noise) → bit-perfect
```

Same canon as ma-rr-predictor [[reference-pc-remote-access]] audit framework.
