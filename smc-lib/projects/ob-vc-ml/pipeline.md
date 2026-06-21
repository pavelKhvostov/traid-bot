# Pipeline — vc-ml-predictor

End-to-end data flow от raw CSV до production signals.

## Stage 0: Setup (one-time)

```
~/smc-lib/projects/vc-ml-predictor/
├── data/
│   ├── BTCUSDT_1m_vic_vadim.csv      (symlink to ma-rr-predictor/data/)
│   ├── ETHUSDT_1m_vic_vadim.csv      (symlink)
│   └── (more added per stage)
├── detector/
│   └── detect_ob_vc.py
├── features/
│   ├── compute_vwaps_asvk.py
│   ├── compute_money_hands_asvk.py
│   └── compute_event_features.py
├── labels/
│   └── compute_labels_on_events.py
├── training/
│   ├── train_v4_ob_vc_ens.py
│   └── compute_ensemble.py
└── results/
    └── (per-seed-fold outputs)
```

## Stage 1: ob_vc Detection

**Input:** `data/{ASSET}_1m_vic_vadim.csv`
**Output:** `data/ob_vc_events_{ASSET}_{HTF}.parquet`

Script: `detector/detect_ob_vc.py`

```bash
python detector/detect_ob_vc.py --asset BTCUSDT --htf 1h
python detector/detect_ob_vc.py --asset BTCUSDT --htf 2h
python detector/detect_ob_vc.py --asset ETHUSDT --htf 1h
python detector/detect_ob_vc.py --asset ETHUSDT --htf 2h
```

Output schema:
```
timestamp                  datetime64 (UTC)
asset                      str
HTF                        int (1 or 2 hours)
direction                  str (LONG/SHORT)
n_FVG                      int (1 or 2+)
swept                      bool
extreme                    str (prev/cur)
type_T                     int (1-16)
entry_price                float
OB_top, OB_bottom          float
FVG_top, FVG_bottom        float (combined zone)
fvg_components             list[(TF, top, bottom)]
c1_open_time, c2_open_time, c3_open_time   datetime64
```

Audit: `no_lookahead_check(asset, htf)` — bit-perfect identity.

## Stage 2: Combined event dataset

**Input:** 4 events parquets (BTC 1h, BTC 2h, ETH 1h, ETH 2h)
**Output:** `data/events_combined.parquet`

Script: `detector/combine_events.py`

```python
all_events = []
for asset in [BTC, ETH]:
    for htf in [1, 2]:
        evs = pd.read_parquet(f"data/ob_vc_events_{asset}_{htf}.parquet")
        all_events.append(evs)
combined = pd.concat(all_events).sort_values("timestamp").reset_index(drop=True)
combined.to_parquet("data/events_combined.parquet")
```

Schema includes additional column `asset_htf_key = f"{asset}_{htf}"` для dedup proverka.

## Stage 3: Existing features computation (re-use)

**Input:** `data/events_combined.parquet` (timestamps only)
**Output:** `data/features_events_*.parquet`

Re-use ma-rr-predictor features pipeline на event timestamps:

```bash
# Copy from ma-rr-predictor
cp ~/smc-lib/projects/ma-rr-predictor/features/*.py features/

# Modify to read events table → produce features only on event timestamps
python features/compute_events_ma.py        # → features_events_ma.parquet
python features/compute_events_smc.py       # → features_events_smc.parquet
python features/compute_events_extras.py    # → features_events_extras.parquet
```

Schema: indexed by event_id (matching events_combined.parquet rows).

## Stage 4: NEW features

### 4a: VWAPs ASVK

Script: `features/compute_vwaps_asvk.py`

```python
# For each event timestamp t:
#   For each HTF in [4h, 6h, 12h, 1d]:
#     Find last 2-fractal swept FH on HTF → anchor_FH
#     Find last 2-fractal swept FL on HTF → anchor_FL
#     For each anchor:
#       Compute VWAP from anchor to t (cumulative)
#       Compute dist, slope_20, touch_count, age_h
# 
# Output: features_events_vwaps.parquet (8 anchors × 4 = 32 features)
```

LIVE rule: VWAP integration uses closed bars only between anchor and entry_time.

### 4b: Money Hands ASVK

Script: `features/compute_money_hands_asvk.py`

```python
# For each event timestamp t:
#   For each TF in [15m, 1h, 2h, 4h, 6h, 12h, 1d, 1w]:
#     Compute Money Hands with config (7,14,3,22,60,50,60):
#       mh_state, mh_mf, mh_n4, mh_cascade, mh_dir_acc
# 
# Output: features_events_mh.parquet (8 TFs × 5 = 40 features)
```

LIVE rule: Money Hands считается на partial-bar at entry TF (1h or 2h depending on event), closed bars for other TFs.

### 4c: Event meta features

Script: `features/compute_event_meta.py`

```python
# From events_combined.parquet, derive:
#   event_HTF, event_n_FVG, event_swept, event_extreme, event_type_T
#   event_FVG_total_size, event_OB_size
#   event_age_to_c3, event_swept_n_fractals
# 
# Output: features_events_meta.parquet (9 features in 1 token)
```

## Stage 5: Labels на events

**Input:** `data/events_combined.parquet` (timestamp + entry_price)
**Output:** `data/labels_events.parquet`

Script: `labels/compute_labels_on_events.py`

```python
# For each event:
#   entry_price = event["entry_price"] (close at detection_complete_time)
#   Scan 1m bars forward 60 days
#   For each (direction × X in [3,4,5]):
#     y = 1 if TP touched first (else 0, conservative tie-break)
# 
# Output: labels_events.parquet
#   columns: event_id, y_LONG_3, y_LONG_4, y_LONG_5, y_SHORT_3, y_SHORT_4, y_SHORT_5
```

Re-use `labels/triple_barrier.py` from ma-rr-predictor — same canon.

## Stage 6: Regime

**Input:** `data/events_combined.parquet`
**Output:** `data/regime_events.parquet`

Re-use `features/compute_regime.py` from ma-rr-predictor:
- D-EMA-50, D-EMA-200, slope_200
- BULL/BEAR/CHOP classifier

## Stage 7: Build feature matrix

**Input:** All `features_events_*.parquet` + `regime_events.parquet` + `labels_events.parquet`
**Output:** Loaded in training (no intermediate file)

Script merge logic:
```python
df = events_combined.copy()
for source in [ma, smc, extras, vwaps, mh, meta]:
    df = df.merge(source, on="event_id")
df = df.merge(regime, on="event_id")
df = df.merge(labels, on="event_id")
# Drop rows with too many NaNs (early periods)
df = df.dropna(thresh=2000)
```

## Stage 8: TCN sequence cache

**Input:** raw 1m + event timestamps
**Output:** `data/seq_cache/events_{TF}.npy` (memmap)

Re-use `features/precompute_sequences.py` adapted to event indices:
- For each event timestamp t, slice OHLCV from 1m → resample to each TF
- Store as (N_events, 5, T) memmap

## Stage 9: Walk-forward + Training

**Input:** merged dataset, sequence cache
**Output:** `results/v4_ob_vc_seed{S}_fold{F}_probs.npy`

Script: `training/train_v4_ob_vc_ens.py`

Adapted from `train_v4_regimefeat_ens.py`:
- Same architecture (v4 TCN + FT + regime feat)
- Different dataset (events, not 1h closes)
- Walk-forward on event timestamps (purge + embargo on event index, not time)

Per-seed run:
```bash
python training/train_v4_ob_vc_ens.py --seed 42 --folds all
```

## Stage 10: Ensemble + cluster

**Input:** All per-seed-fold probs
**Output:** Aggregate metrics

Re-use `training/compute_ensemble.py` with new prefix:
```bash
python training/compute_ensemble.py --seeds 42,43,44,45,46 --prefix v4_ob_vc_ --n-folds 6
```

## Stage 11: Production signals

Apply same cluster/cooldown canon (see skolzyashie/clustering.md):
```python
LONG_strategy = {threshold: 0.50, cooldown_h: 12, regime_skip: ["CHOP"]}
SHORT_strategy = {threshold: 0.45, cooldown_h: 12, seed_consensus: "4/4 > 0.45"}
```

## Comparison metric

Per locked decision (success criteria):
- Phase 1 (rule-based baseline): top-3 type WR ≥ 45%
- Phase 2 (ML lift): top-1% WR ≥ 60% (vs ~50% rule-based)
- Phase 5 (holdout): top-1% out-of-sample ≥ 55%

## Pipeline run order (Phase 0+1)

```bash
# Phase 0: Build foundations (~3-4 hours work)
python detector/detect_ob_vc.py --asset BTCUSDT --htf 1h
python detector/detect_ob_vc.py --asset BTCUSDT --htf 2h
python detector/detect_ob_vc.py --asset ETHUSDT --htf 1h
python detector/detect_ob_vc.py --asset ETHUSDT --htf 2h
python detector/combine_events.py

# Audits
python audits/no_lookahead_events.py

# Existing features on events
python features/compute_events_ma.py
python features/compute_events_smc.py
python features/compute_events_extras.py

# New features
python features/compute_vwaps_asvk.py
python features/compute_money_hands_asvk.py
python features/compute_event_meta.py

# Labels + regime
python labels/compute_labels_on_events.py
python features/compute_regime_events.py

# Phase 1: Rule-based baseline
python analysis/baseline_rule_based.py
# → results/baseline_per_type.csv (WR per T1-T16, per n_FVG, per direction)

# Phase 2: ML training
python training/train_v4_ob_vc_ens.py --seed 42 --folds all
python training/train_v4_ob_vc_ens.py --seed 43 --folds all
# ... etc
python training/compute_ensemble.py --seeds 42,43,44,45,46 --prefix v4_ob_vc_ --n-folds 6
python analysis/cluster_v4_ob_vc.py
```

## Estimated total compute (Phase 0+1+2)

- Phase 0 (detector + features): ~2-4 hours wall (sequential, mostly CPU)
- Phase 1 (baseline analysis): ~10 min
- Phase 2 (ML 4 seeds × 6 folds): ~30-60 min wall with parallel PC1+PC2

**Total: ~1 day work from spec to first ML result.**
