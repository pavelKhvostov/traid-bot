# Index of Training & Analysis Scripts

Все скрипты живут в `~/smc-lib/projects/ma-rr-predictor/`.

## Training Scripts

| Script | Variant | Walk-forward | Labels | Notes |
|---|---|---|---|---|
| `training/train_v3_regularized.py` | FT-only baseline | 6-fold sliding 60d | 60d horizon | v3 baseline |
| `training/train_v3_h2d.py` | FT-only | 6-fold sliding 60d | 2d horizon | early experiment |
| `training/train_v3_h14d.py` | FT-only | 6-fold sliding 60d | 14d horizon | confirmed ≈ 60d |
| `training/train_v3_regime.py` | FT-only 3-models per regime | 6-fold sliding 60d | 60d | FAILED (-5pp) |
| `training/train_v3_regimefeat.py` | FT-only + regime feat | 6-fold sliding 60d | 60d | Breakthrough |
| `training/train_v4_tcn.py` | TCN+FT | 6-fold sliding 60d | 60d | TCN added |
| `training/train_v4_ensemble.py` | TCN+FT (no regime) | 6-fold sliding 60d | 60d | seed-args |
| **`training/train_v4_regimefeat_ens.py`** | **TCN+FT + regime feat (CURRENT BEST)** | **6-fold sliding 60d** | **60d** | **4-seed ensemble** |
| `training/train_v4_strict_ens.py` | TCN+FT + regime feat | 6-fold sliding 60d | **48h strict** | A variant |
| `training/train_v4_strict_anchored_ens.py` | TCN+FT + regime feat | **6-fold anchored 2d** | 48h strict | **A+B variant** |
| `training/train_v4_strict_anchored_12f_ens.py` | TCN+FT + regime feat | **12-fold anchored 2d** | 48h strict | A+B+D variant |
| `training/train_v4_strict7d_anc_ens.py` | TCN+FT + regime feat | 6-fold anchored 2d | **7d strict** | (deprecated) |
| `training/train_v4_strict7d_anc_12f_ens.py` | TCN+FT + regime feat | **12-fold anchored 2d** | **7d strict** | **A+B+D 7d** (current) |

## Walk-Forward Modules

| Module | Use case |
|---|---|
| `training/walk_forward.py` | Original 6-fold sliding+60d (default) |
| `training/walk_forward_v2.py` | Support sliding/anchored mode + configurable embargo + n_folds |

## Label Generation

| Script | Output | Logic |
|---|---|---|
| `labels/triple_barrier.py` | `labels_{ASSET}.parquet` | 60d horizon triple-barrier, conservative tie-break |
| `labels/relabel_2d.py` | `labels_{ASSET}_h2d.parquet` | 2d horizon |
| `labels/relabel_14d.py` | `labels_{ASSET}_h14d.parquet` | 14d horizon |
| `labels/gen_strict_labels.py` | `labels_{ASSET}_strict.parquet` | **48h horizon + pct_move<5% filter** |
| `labels/...` (inline in 7d) | `labels_{ASSET}_strict7d.parquet` | 7d horizon + pct_move<5% filter |

## Feature Computation

| Script | Output | Logic |
|---|---|---|
| `features/precompute_sequences.py` | `data/seq_cache/{ASSET}_{TF}.npy` | Memmap OHLCV cache для TCN (~1.6 GB) |
| `features/compute_regime.py` | `data/regime_{ASSET}.parquet` | D-EMA based BULL/BEAR/CHOP classifier |
| `features/compute_path_filter.py` | `data/path_filter_{ASSET}.parquet` | pct_move_since_low/high_200 |
| `features/ma_compute.py` | (used by ma_family.py) | MA/EMA/HMA primitives |
| `features/ma_family.py` | features_{ASSET}_ma_family.parquet | MA features (1920) |
| `features/smc/*.py` + `features/smc_family.py` | features_{ASSET}_smc.parquet | SMC features (224) |
| `features/extras_family.py` | features_{ASSET}_extras.parquet | Anatomy/SEQ/NMA (193) |

## Analysis Scripts

| Script | Purpose |
|---|---|
| `training/compute_ensemble.py` | Average probs across seeds → top-K% WR metrics |
| `training/perm_importance_fold2.py` | Permutation importance on fold 2 SHORT |
| `training/perm_importance_fold1.py` | Permutation importance on fold 1 LONG (recovery) |
| `training/perm_importance_fold3.py` | Permutation importance on fold 3 LONG (bull rally) |
| `training/plot_top_trade.py` | Plot top winning trades (PNG) |
| `training/plot_loss_trade.py` | Plot top losing trades (PNG) |
| `training/cluster_signals.py` | Basic cluster analysis (threshold × gap × pick) |
| `training/cluster_advanced.py` | Multi-head/multi-seed/regime-adaptive strategies |
| `training/cooldown_filter.py` | Cooldown filter analysis (4h/12h/24h) |

## Data Files

| File | Size | Where |
|---|---|---|
| `data/BTCUSDT_1m_vic_vadim.csv` | ~300 MB | PC1, PC2 |
| `data/ETHUSDT_1m_vic_vadim.csv` | ~230 MB | PC1, PC2 |
| `data/features_{BTC,ETH}_ma_family.parquet` | ~340 MB each | PC1, PC2 |
| `data/features_{BTC,ETH}_smc.parquet` | ~37 MB each | PC1, PC2 |
| `data/features_{BTC,ETH}_extras.parquet` | ~35 MB each | PC1, PC2 |
| `data/seq_cache/{ASSET}_{TF}.npy` | ~1.6 GB total | PC1, PC2 |
| `data/labels_{BTC,ETH}_*.parquet` | 530 KB each | PC1, PC2 |

## Results Files

| File pattern | Content |
|---|---|
| `results/v4_rf_seed{S}_fold{F}_{probs,labels,indices}.npy` | Per-seed-fold predictions |
| `results/v4_rf_seed{S}_foldsall.json` | Per-seed JSON metrics |
| `results/v4_rf_ensemble_seeds_*.json` | Aggregated ensemble metrics |
| `results/v4_strict_seed*_*.npy/json` | Strict 48h sliding variant |
| `results/v4_strict_anc_seed*_*.npy/json` | Strict 48h anchored (A+B) |
| `results/v4_strict7d_anc12_seed*_*.npy/json` | Strict 7d 12-fold (A+B+D) |
| `results/perm_importance_fold*.json` | Permutation importance results |

## How to Run

### Train single seed:
```bash
ssh vadim-pc
source ~/smc-lib/projects/ma-rr-predictor/.venv/bin/activate
cd ~/smc-lib/projects/ma-rr-predictor
python training/train_v4_regimefeat_ens.py --seed 42 --folds all
```

### Compute ensemble:
```bash
python training/compute_ensemble.py --seeds 42,43,44,45,46 --prefix v4_rf_ --n-folds 6
```

### Run permutation importance:
```bash
python training/perm_importance_fold3.py
# Outputs: results/perm_importance_fold3.json
```

### Generate PNG:
```bash
python training/plot_top_trade.py
# Outputs: /tmp/top_trade_fold{F}_rank{R}.png
scp vadim-pc2:/tmp/*.png ~/Desktop/
```

## Parallel Execution

### PC1 (28GB RAM, RTX 5070 Ti):
- 2 v4 seeds parallel (with num_workers=0 to avoid OOM)
- Or 1 v4 + perm-importance (small)

### PC2 (15GB RAM, RTX 4070):
- 1 v4 seed alone
- Or 1 v3 + perm-importance

### Cross-PC sync (for ensemble compute):
```bash
# PC2 push to PC1 (since PC2's pubkey is in PC1's authorized_keys):
ssh vadim-pc2 'rsync -av --include="v4_*_seed{S}_*" --exclude="*" \
  -e "ssh -p 2222" \
  ~/smc-lib/projects/ma-rr-predictor/results/ \
  vadim@192.168.0.76:~/smc-lib/projects/ma-rr-predictor/results/'
```

## Compute Time Reference

| Workload | PC1 (2 parallel) | PC2 (1 seed) |
|---|---|---|
| v3 FT-only 6-fold | ~25 min/seed | ~30 min/seed |
| v4 TCN+FT 60d 6-fold | ~30 min/seed | ~50 min/seed |
| v4 strict anchored 6-fold | ~60-80 min/seed | ~70 min/seed |
| v4 strict7d 12-fold | ~110-150 min/seed | ~120 min/seed |
| Permutation importance | ~15 min | ~20 min |
| Clustering analysis | ~1 min | ~1 min |
