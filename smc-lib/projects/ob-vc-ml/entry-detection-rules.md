# Entry Detection Rules — ob_vc canon applied

## Reference

База: [[project-ob-vc]] canon + [[feedback-ob-vc-canon-7-relaxed]] (canon #7 relaxed).

## Detection logic

### Per HTF (1h or 2h):

```
For each closed HTF bar cur (with prev = cur - 1 bar):
  
  STEP 1: Check 2-bar OB pattern
  IF cur.color == prev.color AND prev.color != bar_before_prev.color:
    OB candidate = (prev, cur) — pair of same-color bars after color change
    OB.direction = LONG if green-green else SHORT
  
  STEP 2: Check Williams 5-fractal sweep
  Lookback: last 5 Williams fractals on HTF (5-bar pivot definition)
  IF LONG OB:
    swept = (min(prev.low, cur.low) < min of last 5 FL fractals' lows)
  IF SHORT OB:
    swept = (max(prev.high, cur.high) > max of last 5 FH fractals' highs)
  
  STEP 3: Check FVG presence
  Search FVG components in [prev.open_time, cur.close_time + 2×HTF]:
    Priority TF: 15m (closest LTF to 1h)
    Fallback TF: 20m (для 1h HTF) или 30m (для 2h HTF)
  
  FVG (bullish, для LONG OB): 
    c1.high < c3.low (gap between bar1.high and bar3.low)
    с canon #7 relaxed: fvg.c1 ≥ prev.open (не cur.open)
  
  FVG (bearish, для SHORT OB):
    c1.low > c3.high (gap between bar1.low and bar3.high)
  
  IF FVG found:
    n_FVG = count of unique FVGs after dedup (15m приоритет)
    
  STEP 4: Determine extreme
  IF LONG:
    extreme = "prev" if prev.low < cur.low else "cur"
  IF SHORT:
    extreme = "prev" if prev.high > cur.high else "cur"
  
  STEP 5: Strict detection timing
  detection_complete_time = max(
    cur.close_time,
    c3.close_time,           # FVG completion
    fractal_n2.close_time    # Williams 5-fractal pivot identified (n+2 bars)
  )
  
  Event timestamp = detection_complete_time (entry SIGNALED at this moment)
  
  STEP 6: Record event
  Event = {
    timestamp: detection_complete_time,
    asset: BTC | ETH,
    HTF: 1h | 2h,
    direction: LONG | SHORT,
    n_FVG: int (1 or ≥2),
    swept: bool,
    extreme: "prev" | "cur",
    type_T: T_code (1-16 per memory mapping),
    OB: {prev_OHLC, cur_OHLC, top, bottom},
    FVGs: [(TF, top, bottom), ...],
    c1_open_time, c2_open_time, c3_open_time,
  }
```

## Type T_code mapping (per memory [[feedback-ob-vc-2h-types-T1-T16]])

| T_code | Direction | Swept | n_FVG | Extreme |
|---|---|---|---|---|
| T1 | LONG | ✓ | ≥2 | prev |
| T2 | LONG | ✓ | ≥2 | cur |
| T3 | LONG | ✓ | 1 | prev |
| T4 | LONG | ✓ | 1 | cur |
| T5 | LONG | × | ≥2 | prev |
| T6 | LONG | × | ≥2 | cur |
| T7 | LONG | × | 1 | prev |
| T8 | LONG | × | 1 | cur |
| T9 | SHORT | ✓ | ≥2 | prev |
| T10 | SHORT | ✓ | ≥2 | cur |
| T11 | SHORT | ✓ | 1 | prev |
| T12 | SHORT | ✓ | 1 | cur |
| T13 | SHORT | × | ≥2 | prev |
| T14 | SHORT | × | 1 | cur |  ← memory shows T14 = SHORT × 1 cur (not ≥2 cur)
| T15 | SHORT | × | 1 | prev |
| T16 | SHORT | × | 1 | cur |

⚠ Memory T14 — может быть typo (was T14=SHORT×1cur but T13=SHORT×≥2prev). Verify in implementation.

## Two entry types (project focus)

### Type A: n_FVG = 1 (single FVG zone)
- More common (~70% of events)
- "Standard" ob_vc setup
- Hypothesis: needs ML filter to find quality signals (high noise)

### Type B: n_FVG ≥ 2 (multi-FVG confluence)
- Rarer (~30% of events)
- "Institutional confluence" (per vault session 2026-05-31)
- Hypothesis: higher baseline WR, ML may add marginal improvement

**Combined 1h + 2h dataset** for ML — model learns to distinguish both types via `event_n_FVG` feature.

## ⚠ Entry ≠ Detection — Critical distinction

**Detection (formation):** moment ob_vc structurally complete
```
t_birth = max(cur.close_time, c3.close_time, fractal_n2.close_time)
```

**Entry (decision moment):** somewhere AFTER t_birth, within wait window

```
wait_window = [t_birth, t_birth + MAX_WAIT]
MAX_WAIT = 48 hours (initial cap)

For each 1h bar t in wait_window:
    candidate_entry_timestamp = t
    candidate_entry_price = close[t]
    
    → ML evaluates this candidate
    → Records features (live HMA + MA + EMA + SMC + wait stats + ob_vc meta)
    → Records label (60d TBM from t)
```

### Why this matters

**ML learns** the optimal entry trigger from data:
- Model discovers: "entries +3h after formation when RSI<40 have 80% WR"
- Or: "entries when price returned to FVG midpoint better than touch entry"
- Or: "entries immediately at t_birth less reliable than waiting"

We don't pre-impose: A/B/C/D rules (touch/mid/wick-fill/etc.) — ML decides.

### Production rule: ONE entry per setup

```
For setup S in active_setups:
    candidates_in_window = [t for t in 1h_bars if t in S.wait_window]
    predictions = [model.predict(t, features=...) for t in candidates_in_window]
    
    if max(predictions) > threshold:
        peak_t = argmax(predictions)
        execute_entry(at=peak_t, direction=S.direction)
    
    setup_S.consumed = True  # No re-entry per dedup canon
```

## Entry price determination (per candidate)

```
For each candidate 1h timestamp t in wait_window:
    entry_price = close[t]
    
    # Wait window stats computed up to t
    wait_features[t] = {
        wait_bars_since_birth: (t - t_birth) / 1h,
        wait_max_high_pct: (max(high[t_birth:t]) - entry_zone_top) / entry_zone_width,
        wait_min_low_pct: (min(low[t_birth:t]) - entry_zone_bottom) / entry_zone_width,
        wait_touched_zone_count: count(price in [zone_bottom, zone_top] for bars in [t_birth, t]),
        wait_touched_sl_before_entry: any(low[t_birth:t] < pre_entry_SL),
        ...
    }
    
    # All other features computed LIVE at t
    ml_features[t] = compute_live_features(t)  # MA/EMA/HMA partial-bar canon
```

## SL / TP for labels

Per locked decision #6:
```
TP_3 = entry × 1.03 (LONG) or entry × 0.97 (SHORT)
TP_4 = entry × 1.04 or × 0.96
TP_5 = entry × 1.05 or × 0.95
SL = entry × 0.99 (LONG) or × 1.01 (SHORT)
Horizon = 60 days
```

## Dedup rule (важно)

Per [[feedback-ob-vc-2h-types-T1-T16]]:
**1 trade per OB.** Если FVG component overlap (15m vs 20m) → пометить как ≥2 FVG но НЕ дублировать trade.

При sequential events на одной OB (rare):
- Keep only first detection (earliest timestamp)
- Subsequent re-detections within same OB → skip

## Implementation file

`detector/detect_ob_vc.py` (to be written):
```python
def detect_ob_vc_events(asset: str, htf: int, raw_1m: pd.DataFrame) -> pd.DataFrame:
    """
    Returns DataFrame with columns:
      timestamp, asset, HTF, direction, n_FVG, swept, extreme, type_T,
      OB_top, OB_bottom, FVG_top, FVG_bottom, fvg_components_count
    """
    ...
```

Output: `data/ob_vc_events_{ASSET}_{HTF}.parquet`

## Audit

После detection обязательно:
1. **No-lookahead audit**: poison future bars, re-detect → events must be identical for past timestamps
2. **Sanity check**: total events ~150-200/year per asset per HTF
3. **Type distribution**: T3, T11, T1 топ-3 по объёму per memory
4. **Cross-asset consistency**: ETH events similar density to BTC
