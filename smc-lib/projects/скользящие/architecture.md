# Архитектура v4 TCN + FT-Transformer + Regime Feature

## Обзор

Модель = **dual-branch fusion**: tabular (FT-Transformer) + sequence (TCN) → fusion MLP → 6 binary heads.

```
┌──────────────────────────────────────────────────────────────────┐
│                     ENTRY @ 1h close (t)                         │
└──────────────────┬───────────────────────────────────────────────┘
                   │
       ┌───────────┴───────────┐
       │                       │
   ╔═══▼═══════════════╗   ╔══▼══════════════════════════════╗
   ║ TABULAR FEATURES  ║   ║ SEQUENCE OHLCV                  ║
   ║ 2337 + 3 regime   ║   ║ 7 каналов на 7 ТФ               ║
   ╠═══════════════════╣   ╠═════════════════════════════════╣
   ║ MA family (1920)  ║   ║ 15m × 256 (64h)                 ║
   ║ SMC (224)         ║   ║ 1h × 128 (5d)                   ║
   ║ Anatomy (80)      ║   ║ 2h × 96 (8d)                    ║
   ║ SEQ stats (80)    ║   ║ 4h × 64 (10d)                   ║
   ║ NMA (32)          ║   ║ 6h × 64 (16d)                   ║
   ║ META (IS_ETH+regime)  ║ 12h × 64 (32d)                 ║
   ╚═══════╤═══════════╝   ║ 1d × 64 (64d)                   ║
           │               ╚═════════╤═══════════════════════╝
           │                         │
       ┌───▼──────────────┐      ┌──▼──────────────┐
       │  FT-Transformer  │      │   TCN per TF    │
       │  561 tokens      │      │  7 каналов      │
       │  embed=64        │      │  5 dilations    │
       │  2 layers        │      │  kernel=7       │
       │  → 256 vector    │      │  → 256 vector   │
       └───┬──────────────┘      └──┬──────────────┘
           │                        │
           └───┬────────────────────┘
               │
           ┌───▼──────────────────────┐
           │  Fusion MLP              │
           │  concat(256+256)→256→128 │
           │  dropout=0.4             │
           └───┬──────────────────────┘
               │
        ┌──────┼──────┬──────┬──────┬──────┐
        ▼      ▼      ▼      ▼      ▼      ▼
    LONG_3 LONG_4 LONG_5 SHORT_3 SHORT_4 SHORT_5
    (sigmoid → calibrated probability)
```

## Параметры

```python
EMBED_DIM = 64
N_LAYERS = 2
N_HEADS = 4
DROPOUT = 0.4
BATCH = 128
LR = 1e-4
WD = 1e-2
EPOCHS = 25 (early stop patience=5)
LOSS = focal_loss(gamma=2.0, label_smoothing=0.1)

# TCN
TCN_CHANNELS = 128
TCN_LEVELS = 5
TCN_KERNEL = 7
TCN_DROPOUT = 0.3
```

**Total params:** ~8.9M (TCN 8.4M + FT 0.34M + Fusion 0.15M)

## Что входит на вход (по группам токенов)

### Tabular tokens (562 total после добавления regime)

| Группа | TFs | Periods | Features per token | Кол-во токенов |
|---|---|---|---|---|
| MA / EMA / HMA | 8 (15m..1w) | 10..200 step 10 | 4 (dist_norm, slope_5, slope_sign, pos_rank) | 480 |
| SMC (FVG/iFVG/OB/OB_LIQ/OB_VC/i_RDRB/Williams) | 8 | — | 4 (dist_bull, dist_bear, age_bull, age_bear) | 56 |
| Anatomy (body_ratio, wick_asymmetry, range_atr, etc.) | 8 | — | 10 | 8 |
| SEQ stats (consec_same_color, swing_count, ...) | 8 | — | 10 | 8 |
| NMA (atr_14, rsi_14, rsi_bars_since_fresh_exit, volume_zscore) | 8 | — | 4 | 8 |
| META | — | — | IS_ETH + regime_BULL + regime_BEAR + regime_CHOP | 2 (IS_ETH, regime) |

### Sequence channels (TCN)

7 OHLCV-лент с нормализацией:
- OHLC: `(price - last_close) / last_close`
- Volume: `(log1p(vol) - mean) / std` over slice

## Что предсказывает (6 голов)

Каждая голова = binary classifier (sigmoid output):

| Head | Target | TP | SL | Horizon |
|---|---|---|---|---|
| LONG_3 | +3% reached before -1% | +3% | -1% | (60d/14d/48h в разных вариантах) |
| LONG_4 | +4% | +4% | -1% | |
| LONG_5 | +5% | +5% | -1% | |
| SHORT_3 | -3% reached before +1% | -3% | +1% | |
| SHORT_4 | -4% | -4% | +1% | |
| SHORT_5 | -5% | -5% | +1% | |

## Walk-forward (анchored + 2d embargo для strict, 60d для 60d-labels)

См. [walk-forward.md](walk-forward.md) для деталей.

6-fold по умолчанию, 12-fold вариант для финального теста (3-month val window).

## Critical: regime as INPUT feature (не routing)

Раньше пробовали 3 модели per regime — провал (data fragmentation).
Прорыв: добавить **3 one-hot колонки** (regime_BULL/BEAR/CHOP) как META токен.

**Эффект:** +25-27pp top-0.5% LONG_3 на breakthrough вариантах.

**Почему работает:**
- Модель **условно** учит правила: «if BULL + RSI 40 → P=0.7, if BEAR + RSI 40 → P=0.2»
- Не теряем данные (vs 3 модели)
- Регим знание помогает модели **переключаться** по фолдам

## Источник кода

- `~/smc-lib/projects/ma-rr-predictor/models/`
  - `ft_transformer.py` — FT-Transformer (FeatureTokenizer + TransformerEncoder)
  - `tcn.py` — MultiResTCN (7 каналов параллельно, dilated convolutions)
  - `fusion.py` — RRPredictor (FT + TCN fusion + 6 heads)
  - `dataset.py` — RRDataset (memmap sequence cache, no-lookahead audited)
- `~/smc-lib/projects/ma-rr-predictor/training/train_v4_regimefeat_ens.py` — главный training script
- `~/smc-lib/projects/ma-rr-predictor/features/precompute_sequences.py` — pre-cache TCN sequences
- `~/smc-lib/projects/ma-rr-predictor/features/compute_regime.py` — regime classifier (D-EMA based)
