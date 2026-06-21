"""ML v1.5 — feature engineering on extended channels + HMA pack.

Pipeline:
  1. dataset.py        — load ob_vc events (BTC + ETH)
  2. data_loaders.py   — unified channel loaders (funding/OI/DVOL/cross/macro)
  3. quasi_seq.py      — snapshot at T, T-6h, T-1d, T-3d, T-1w
  4. feature_channels  — derive features per channel (delta, slope, z-score, regime)
  5. feature_hma.py    — rich HMA pack (numpy-vectorized)
  6. build_features.py — orchestrator → merged parquet for PC1
"""
