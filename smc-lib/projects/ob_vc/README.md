# ob_vc s1 — Set Transformer для ob_vc 2h trading

Pipeline: **e12** (events) → **s7b** (snapshots) → **c1** (clusters) → **ob_vc s1** ML.

## Структура

```
ob_vc/
├── scripts/                    общие (24-type classifier, plots)
├── s1/                         главный проект ML
│   ├── scripts/                Phase 1-3 pipeline
│   │   ├── phase1_label.py      TBM labeling (TP=1R, SL=1R, RR=1)
│   │   ├── phase2_features.py   29 aggregated features (v1, deprecated)
│   │   ├── phase2v2_tokenize.py token-set features per event (production)
│   │   ├── phase3v2_transformer.py Set Transformer round-based train
│   │   └── dump_r5.py          dump R5 ckpt + 167 BTC TEST trades
│   ├── rounds_v2/
│   │   └── s1v2_round_05.pt    🌟 canonical R5 ckpt (production)
│   ├── history_v2.json         13 rounds VAL/TEST results
│   └── r5_test_trades_summary.txt   BTC R5 dump 167 trades summary
└── eth/                        cross-asset ETH тест
    └── scripts/                ETH-patched copies of s1 + cross_asset_compare
```

## Канон-результат R5 (2026-06-23)

| Setup | N | WR | EV | Trades/мес |
|---|---|---|---|---|
| BTC TEST (2025-07→2026-06) @ thr=0.71 | 167 | 71.3% | +0.43R | 14.5 |
| ETH OOD (2023-01→2026-06) @ thr=0.71 | 573 | **71.7%** | +0.43R | 13.9 |
| ETH @ thr=0.90 (selective) | 285 | **84.9%** | +0.70R | 6.9 |

**R5 модель обучена только на BTC** 2020-01→2025-01. ETH результаты — out-of-distribution validation. Edge transferable, цели user (6-8 trades/мес @ WR>70%) достигнуты thr=0.90.

## Архитектура R5

- 600 zone tokens + 20 cluster tokens + 50 event tokens + 4 self tokens
- 3-layer Transformer, D=128, H=4, GELU, norm_first
- 3 heads: main BCE + critic L1 + aux_r SmoothL1
- C3-style round-based с adaptive pos_weight
- 0.66M params

## Reproducing

Данные не закоммичены (большие parquet). Чтобы воспроизвести:

```bash
# на машине с e12 events + 1m CSV:
python scripts/phase1_label.py        # → labels_2h.parquet
python scripts/phase2v2_tokenize.py   # → features_v2.npz + meta_v2.parquet
python scripts/phase3v2_transformer.py # train rounds_v2/s1v2_round_*.pt
python scripts/dump_r5.py             # → r5_test_trades.parquet

# ETH cross-asset:
python eth/scripts/run_e12_eth.py     # → ETH events
python eth/scripts/s7b_eth.py         # → ETH snapshots
python eth/scripts/c1_batch_eth.py    # → ETH clusters
python eth/scripts/phase1_label_eth.py
python eth/scripts/classify_24_types_eth.py
python eth/scripts/phase2v2_tokenize_eth.py
python eth/scripts/r5_eth_inference.py # → R5 ETH WR report
```
