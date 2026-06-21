"""
Force model v2 — empirically learned per-zone strength через 5 раздельных LR моделей.

Заменяет старую `force_opinion.zone_strength()` (TF_WEIGHT × hours × class_W formula).
См. [[force-model-v2-architecture]] в memory.

Структура:
    labeling.py  — strict Williams-i target на 12h candle
    features.py  — 9/8 features per zone per element type
    dataset.py   — assemble per-element DataFrames (5 штук)
    train.py     — 5 logistic regressions (FVG / fractal / OB / block_orders / RDRB)
    run.py       — end-to-end driver

Coefficients total = 81+81+81+72+72 = 387.
"""
