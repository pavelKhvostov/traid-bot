# Сравнение всех экспериментов (12 июня 2026)

## Главная таблица: эволюция top-0.5% LONG_3 mean

| # | Эксперимент | Type | top-0.5% LONG_3 | top-0.5% SHORT_3 | top-1% LONG_3 |
|---|---|---|---|---|---|
| 1 | v3 baseline | FT-only | 0.365 | 0.360 | 0.358 |
| 2 | v3 + horizon 14d | label change | 0.357 | 0.359 | 0.358 |
| 3 | v3 + horizon 2d | label change | 0.323 | 0.283 | 0.324 |
| 4 | v3 + 3-models per regime (routing) | regime arch | 0.280 ❌ | 0.376 | 0.263 |
| 5 | v3 + regime as feature | regime input | 0.288 | 0.421 | 0.307 |
| 6 | v4 TCN ensemble (5 seeds) | architecture | 0.432 | 0.448 | 0.414 |
| 7 | **v4 + regime feat (single seed)** | breakthrough | **0.617** ⭐ | 0.402 | 0.545 |
| 8 | **v4 + regime feat (4-seed)** | breakthrough | **0.538** | 0.531 | **0.502** |
| 9 | v4 + 48h strict labels (4-seed sliding) | label change | 0.245 | 0.396 | — |
| 10 | **v4 + 48h strict + anchored (4-seed)** | A+B variant | 0.260 | **0.576** ⭐ | 0.283 |
| 11 | v4 + 7d strict + anchored 12-fold | in progress | TBD | TBD | TBD |

## Acceptance counts (4+ folds ≥65%)

| # | Эксперимент | top-0.5% LONG_3 ≥65% | top-0.5% SHORT_3 ≥65% | top-1% LONG_3 ≥60% |
|---|---|---|---|---|
| 8 | v4 + regime feat 4-seed (60d) | **3/6** | 2/6 | 2/6 |
| 10 | v4 + anchored 48h strict | 0/6 | **2/6** | 0/6 |

## По fold-сравнение (4-seed ensembles)

### Top-0.5% LONG_3 per fold

| Fold | v4+regime-feat 60d | v4 anchored 48h strict | Best variant |
|---|---|---|---|
| 0 (LUNA bear) | 0.64 | 0.12 | 60d |
| 1 (FTX recovery) | **0.77** | 0.18 | 60d |
| 2 (banking) | 0.23 | 0.49 | strict (better!) |
| 3 (bull rally) | **0.79** | 0.20 | 60d |
| 4 (distribution) | 0.30 | 0.05 | 60d (marginal) |
| 5 (top mix) | 0.51 | 0.52 | tie |

### Top-0.5% SHORT_3 per fold

| Fold | v4+regime-feat 60d | v4 anchored 48h strict | Best variant |
|---|---|---|---|
| 0 (LUNA bear) | **0.68** | 0.30 | 60d |
| 1 (FTX recovery) | 0.58 | 0.64 | strict |
| **2 (banking chop)** | 0.61 | **0.86** ⭐ | strict (+25pp!) |
| 3 (bull rally) | 0.00 | 0.30 | strict |
| **4 (distribution)** | 0.61 | **0.88** ⭐ | strict (+27pp!) |
| 5 (top mix) | **0.70** | 0.48 | 60d |

**Закон:**
- 60d ensemble лучше для **stable bull/bear/LUNA** регимов
- Anchored 48h strict лучше для **chop/distribution** регимов
- Hybrid (разные модели per direction) — оптимальный путь

## Permutation Importance — кто доминирует

| Fold | Head | Baseline WR | Top feature | Δ при shuffle |
|---|---|---|---|---|
| 1 | LONG_3 | 0.37 | MA_MA_100_1h | −14pp |
| 2 | SHORT_3 | **0.93** | MA_MA_130_1w | −16pp |
| 3 | LONG_3 | 0.23 | MA_HMA_190_1h | −8pp |

## Clustering / Cooldown Analysis (fold 3 LONG_3, baseline 0.337)

| Strategy | Sigs/mo | WR | Notes |
|---|---|---|---|
| Raw top-5% | 14 | 0.41 | unfiltered baseline |
| Cluster peak thr=0.50 gap=12h | **0.7** | **0.75** ⭐ | conservative |
| Cluster peak thr=0.50 gap=6h | 1.1 | 0.71 | balanced |
| Cooldown 4h thr=0.50 | 5.25 | 0.81 ⭐ | first-take |
| Cooldown 12h thr=0.50 | 2.30 | 0.71 | balanced |
| Cooldown 24h thr=0.50 | 1.3 | 0.62 | aggressive |
| Multi-seed 4/4 > 0.45 | 0.0 | nan | fold 3 — no overlap |

## Walk-Forward Variants Tested

| Variant | Mode | Embargo | Folds | Status |
|---|---|---|---|---|
| Baseline | Sliding | 60d | 6 | ✅ All experiments |
| A | Sliding | **2d** | 6 | ✅ Strict variant |
| B | **Anchored** | 60d | 6 | ✅ Anchored strict |
| A+B | Anchored | 2d | 6 | ✅ Anchored strict 4-seed |
| D = A+B+12-fold | Anchored | 2d | **12** | 🔄 In progress (7d strict) |
| C (CPCV) | 6-group combinatorial | 60d | 15 paths | 📝 Planned |

## Label Variants Tested

| Variant | Horizon | Filter | Baseline WR LONG_3 |
|---|---|---|---|
| Original | 60d | none | 26% |
| 14d | 14d | none | 26% (≈ original) |
| 2d | 2d | none | 22% |
| **Strict 48h** | 48h | pct_low<5% | 9.7% (BTC) |
| **Strict 7d** | 7d | pct_low<5% | 13.0% (BTC) |

## Ensemble Compute Times (PC1 5070 Ti / PC2 4070)

| Variant | Per seed (6 folds) | Per seed (12 folds) | 4-seed parallel |
|---|---|---|---|
| v3 FT-only | ~20 min PC1 | n/a | ~50 min |
| v4 TCN+regime-feat | ~30 min PC1, ~50 min PC2 | n/a | ~80 min |
| v4 strict anchored | ~60-80 min (slower) | n/a | ~150 min |
| v4 strict7d 12-fold | n/a | ~100-120 min | ~3 ч |

## Disk Footprint

| Dataset | Size |
|---|---|
| features parquets | ~1.0 GB |
| seq_cache memmap | ~1.6 GB |
| labels parquets | ~3 MB |
| Per-fold probs (per seed) | ~200 KB |
| Total results/ folder | ~50 MB |

## Hardware Utilization

| PC | GPU | VRAM peak | RAM peak | Throughput |
|---|---|---|---|---|
| **PC1** | RTX 5070 Ti 16GB | 8GB / 2 parallel | 13GB / 27GB | 2 ensemble seeds parallel stable |
| **PC2** | RTX 4070 12GB | 4GB / 1 parallel | 6GB / 15GB | 1 ensemble seed at a time |

## Next Step Priorities

1. ⏳ Complete 7d strict 12-fold ensemble (4 seeds)
2. ⏳ Apply advanced clustering analysis к 7d 12-fold
3. ⏳ Phase 1 holdout test (2026-04→06) — honest out-of-sample
4. 📝 Implement CPCV (C variant) — academic robustness
5. 📝 Execution simulation with realistic costs
6. 📝 Paper trading setup
