# vc-ml-predictor — Full Spec

## Decisions LOG (locked or updateable)

| # | Decision | Locked | Source |
|---|---|---|---|
| 1 | Entry detector = ob_vc canon (strict) | ✅ | User 2026-06-12 |
| 2 | TFs = 1h + 2h combined dataset first | ✅ | User 2026-06-12 |
| 2.5 | After combined → separate 1h-only / 2h-only analysis | ✅ | User 2026-06-12 |
| 3 | Two entry types = n_FVG=1 vs n_FVG≥2 (label both, decide arch later) | ✅ | User 2026-06-12 |
| 4 | Assets = BTC + ETH | ✅ | User 2026-06-12 |
| 5 | Data start = 2020-01-01 | ✅ | User 2026-06-12 |
| 6 | Labels = 60d triple-barrier TP=3/4/5% SL=1% Conservative tie-break | ✅ | Same as skolzyashie |
| 7 | Architecture = v4 TCN + FT + regime feature | ✅ | Same as skolzyashie |
| 8 | Live HMA partial-bar update MANDATORY | ✅ | Canon |
| 9 | Additional features: VWAPs ASVK + Money Hands ASVK | ✅ | User 2026-06-12 |
| 10 | Phase 0: build detector + features | ✅ | Now |
| 11 | Phase 1: rule-based baseline (no ML) — measure floor | ✅ | Plan |
| 12 | Phase 2: ML experiment with all features | ✅ | Plan |
| 13 | Phase 3+: architecture variants, walk-forward variants | ✅ | Plan |

## Open questions (TBD)

| # | Question | Decision deadline |
|---|---|---|
| Q1 | One model with n_FVG feature OR two models routing? | Phase 2 — test both |
| Q2 | Walk-forward sliding vs anchored OR CPCV from start? | Phase 3 |
| Q3 | Multi-TF features same as skolzyashie OR ob_vc-specific TFs only? | Phase 0 (build) |
| Q4 | Test 7d strict labels too (как в skolzyashie)? | Phase 2 — start with 60d |

## Entry Detection (Phase 0 deliverable)

### Rules — strictly per ob_vc canon

```
On each 1h timestamp t (and 2h timestamp):
  IF ob_vc(t) detected:
    Record event with:
      - timestamp_t (entry time)
      - asset (BTC / ETH)
      - HTF (1h or 2h)
      - direction (LONG / SHORT)
      - n_FVG (1 or ≥2)
      - swept (boolean — Williams 5-fractal sweep)
      - extreme (prev or cur — где экстремум swept)
      - type_T (T1-T16 mapping)
      - c1.open_time, c2.open_time, c3.open_time
      - OB price levels
      - FVG components (list of (TF, top, bottom))
```

### Detection timing (strict, no lookahead)

Per [[feedback-ob-vc-strict-detection-timing]]:
```
fill_start = max(cur_HTF.close, c3.close, opposite_fractal_n2.close)
```

Detection completes at c3.close + fractal_n2.close (whichever later) — entry signaled THEN, not earlier.

### Canon #7 relaxed (применяем):
- fvg.c1 ≥ prev.open (не cur.open) — расширенное FVG detection
- Окно = OB pair = 2×HTF
- Prev-bar FVGs валидны

## Features for ML (Phase 0 deliverable)

### Existing (re-use from ma-rr-predictor catalog):
- MA family (480 tokens × 4 features = 1920)
- SMC (56 tokens × 4 = 224) — keep but probably less important
- Anatomy (8 tokens × 10 = 80)
- SEQ (8 tokens × 10 = 80)
- NMA (8 tokens × 4 = 32) — RSI/ATR/volume/rsi_cumulative_exit
- IS_ETH (1)
- Regime (3 one-hot — BULL/BEAR/CHOP)

### NEW for this project:

#### VWAPs ASVK (anchored VWAPs)
Per [[feedback-anchored-vwap-from-fractals]]:
- N_FRACTAL=2 (anchor on swept 2-fractal pivot)
- Multi-TF anchors: anchor от свежих FH/FL на 4h, 6h, 12h, 1d, 1w
- Features per VWAP:
  - `vwap_X_dist` — расстояние price до VWAP (normalized by ATR)
  - `vwap_X_slope` — slope of VWAP (rising/falling)
  - `vwap_X_touch_count` — how many touches since anchor
  - `vwap_X_age` — bars since anchor

**Expected features count**: ~8 anchors × 4 features = 32

#### Money Hands ASVK
Per [[mh-screening-best-config-not-lazybear]]:
- Config best: (7, 14, 3, 22, 60, 50, 60)
- Key axes: rsi_stoch=50, mf=smoothed
- Features per TF:
  - `mh_X_state` — color/regime indicator
  - `mh_X_mf` — money flow (smoothed)
  - `mh_X_n4` — N4 oscillator
  - `mh_X_cascade` — cascade resonance
  - `mh_X_dir_acc` — directional accuracy proxy

**Expected features count**: ~8 TFs × 5 features = 40

### Total new tokens added:
- VWAPs ASVK: ~8 tokens
- Money Hands ASVK: ~8 tokens
- Combined: **+72 features in 16 new tokens**

## Labels (Phase 0 deliverable)

Same as skolzyashie 60d baseline:
- y_LONG_3 = 1 if +3% before -1% within 60d, else 0
- y_LONG_4, y_LONG_5 — same with 4%, 5%
- y_SHORT_3, y_SHORT_4, y_SHORT_5 — mirror

**Re-compute on ob_vc event timestamps only** (not every 1h close → smaller labels dataset).

## Pipeline (Phase 0 deliverable)

```
1m CSV (BTC, ETH)
  ↓ resample
1h grid + 2h grid
  ↓ ob_vc detect
events table (~4000-8000 rows × asset)
  ↓ feature compute (LIVE HMA + VWAPs + Money Hands)
features_vc_*.parquet (event-indexed)
  ↓ label compute (60d TBM at event time)
labels_vc_*.parquet
  ↓ regime compute (D-EMA per event time)
regime_vc_*.parquet
  ↓ walk-forward + train
v4+regime-feat ensemble (4 seeds)
  ↓ ensemble averaging + cluster
production signals
```

## Sample sizes (estimated) — UPDATED per Entry≠Detection canon

### Formations (ob_vc setup formations)
- BTC 2h: ~4,036 / ETH 2h: ~3,500-4,000
- BTC 1h: ~8,000 (denser) / ETH 1h: ~7,000
- **Combined 1h+2h, BTC+ETH:** ~22,000-25,000 ob_vc formations

### Candidate ENTRIES per formation
- Max wait window = **48 hours** (per decision 17)
- Each 1h bar in [t_birth, t_birth+48h] = candidate
- Avg candidates per formation: **30** (some setups expire early)

### Total ML samples
- 22,000-25,000 formations × 30 avg candidates = **~700,000 samples**
- BTC + ETH separately maintained для walk-forward purge

### Train/val split per fold (6-fold WF)
- ~450,000-500,000 train per fold
- ~80,000-100,000 val per fold

**MORE samples than skolzyashie** (112k total), но каждый sample = informationally rich (active wait window state).

## Compute estimates

- Detection: ~2-5 min per asset
- Feature compute: ~10-20 min (incl. new VWAPs/Money Hands)
- Label compute: ~30 sec
- Training per seed (sparse data): ~5-10 min
- 4-seed ensemble: ~20-40 min

## Comparison expectation vs skolzyashie

| Metric | Skolzyashie | vc-ml-predictor expected |
|---|---|---|
| Signals/мес raw | ~17k entries/year = 200/мес | ~700-1000/мес raw events |
| Signals/мес after cluster top-1% | 5-10 | 1-5 (sparser, higher conviction) |
| Per-signal WR | 55-60% | **60-75% target** (если ML работает) |

## Risk: что может НЕ сработать

1. **Sample size too small** — ML может не находить signal на 20k events
2. **ob_vc events уже sample bias** — может ML добавит overfit
3. **VWAPs/Money Hands не дают edge** — могут не работать как новые features
4. **Multi-TF mixing (1h + 2h) сложнее** — 1h может dominate просто potому что более частый

## Fallback plan

Если ML на ob_vc events не работает:
- Use rule-based baseline (Phase 1) as production signal
- Per [[ob-vc-2h-tbm-results]] эта стратегия уже выдаёт +329R за 6y без drop
- ML add value optional, не критично

## Success criteria

- **Phase 1 baseline:** rule-based ob_vc gives **≥45% WR** at top-3 type (T3, T11, T1) per memory
- **Phase 2 ML:** model lifts top-1% WR to **≥60%** (vs baseline ~50%)
- **Phase 5 holdout:** out-of-sample top-1% WR **≥55%**
- **Phase 6 paper:** live WR within **5pp of backtest**
