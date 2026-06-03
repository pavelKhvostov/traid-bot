"""
Force model v3 — directional force learning with region-filtered zones.

Отличия от v2 ([[force-model-v2-architecture]]):
- Search окно = force-search regions:
    SHORT [prior.H .. candle.H] — resistance давит вниз → формирование i-high
    LONG  [candle.L .. prior.L] — support давит вверх   → формирование i-low
- Per-row target — directional:
    short zones в SHORT region → target = is_FH (Williams pivot high)
    long zones в LONG region   → target = is_FL (Williams pivot low)
- Liquidity-count в region (backward HH/LL chain) — новая feature
- 8 TFs zones / 6 TFs liquidity (8h убран)

Канон baseline:
    prior 12h.close > .open (BULL) → baseline = prior.HIGH
    prior 12h.close < .open (BEAR) → baseline = prior.LOW

Files:
    labeling.py — directional Williams labels (is_FH, is_FL)
    regions.py  — force-search region computation per candle
    features.py — extension of v2 features + liquidity_count_in_region
    dataset.py  — region-filtered directional dataset
    train.py    — 5 element models, directional target
    run.py      — pipeline driver
"""
