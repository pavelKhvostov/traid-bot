---
name: i-rdrb-v1-pattern
description: "i-RDRB V1 + FVG — formal 5-candle bullish reversal pattern definition (user's terminology)"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 5e21d38b-e676-4f38-bd03-ad461c79b4c0
---

# i-RDRB V1 + FVG

User's formal definition of a 5-candle bullish reversal setup. Candles are labeled C1..C5 left-to-right; this naming convention is the shared vocabulary for all further work on this pattern.

## Components

- **i-RDRB V1 zone** = intersection of C1's lower wick and C3's upper wick
  - C1.lower_wick = `[C1.low, C1.body_bottom]`
  - C3.upper_wick = `[C3.body_top,  C3.high]`
  - zone = `[max(C1.low, C3.body_top), min(C1.body_bottom, C3.high)]`
  - preconditions (both must hold for wicks to overlap):
    - `C1.body_bottom ≥ C3.body_top` — body of C3 sits at or below body of C1 (C3 is the lower-priced candle)
    - `C3.high ≥ C1.low` — wicks reach each other
  - Stricter than range-overlap (`C3.high > C1.low` alone): a case like 2026-05-14 05-09 UTC+3 passed the looser check despite C3 sitting entirely above C1's body. Wick-overlap rejects it correctly.
  - In the reference example, zone simplifies to `[C1.low, C3.high]` because C3.body_top < C1.low and C1.body_bottom > C3.high; the general formula above always works.
- **FVG** = bullish 3-candle Fair Value Gap formed by C3-C4-C5 with C4 as displacement candle
  - top = C5.low
  - bottom = C3.high
  - precondition: C5.low > C3.high
- **Liquidity targets** (for long pattern): four levels above C5.close, each is the *nearest unfilled* level of its kind located strictly above C5.close at the time of pattern detection:
  - **liq1** = nearest unfilled Fractal High on **1h** TF (Williams fractal, N=2: high strictly > 2 lefts and 2 rights)
  - **liq2** = nearest unfilled Fractal High on **4h** TF (same Williams N=2)
  - **liq3** = nearest unfilled **bearish** FVG on **1h OR 2h** TF (take min of the two; bearish FVG: candle1.low > candle3.high, zone = [c3.high, c1.low], unfilled = no later candle has high ≥ c3.high)
  - **liq4** = nearest unfilled bearish FVG on **4h OR 6h** TF (same definition; take min)
  - "Nearest" = smallest price > C5.close. "Unfilled" = the level/zone hasn't been touched/violated by any candle after its formation and up to (and not including) pattern detection time.
  - Note: the legacy single-target `Liq = C1.high` is superseded by this 4-level hierarchy.

## C2 close condition

C2 must close strictly below C1's low:

```
C2.close < C1.low
```

This is the operational form of "C2 body covers C1's lower wick" — using the strict 2-side body containment check (`C2.body_top ≥ C1.body_bottom`) breaks on tick-level boundary effects between 1h aggregated candles (e.g., the reference example failed by $0.01: C2.open 76872.74 vs C1.close 76872.75). Requiring only `C2.close < C1.low` captures the intent (C2 drives meaningfully below C1's range) without false rejections from data-boundary noise.

Reference example check: C2.close = 76392.43; C1.low = 76596.00; condition holds.

## Non-requirements (explicit)

- **Sweep is NOT mandatory.** No requirement that any later candle takes out C2.low or any prior low.
- **Pattern low can be made by C2, C3, or C4** — which candle prints the swing low is not principled / not part of the definition.

## Reference example

BTCUSDT 1h, 2026-05-19, UTC+3:
- C1 16:00 — O 76940 / H 77048 / L 76596 / C 76872 (small bear)
- C2 17:00 — O 76872 / H 77023 / L 76144 / C 76392 (big bear, prints pattern low)
- C3 18:00 — O 76392 / H 76675 / L 76337 / C 76521 (small bull)
- C4 19:00 — O 76521 / H 76911 / L 76407 / C 76894 (big bull, displacement)
- C5 20:00 — O 76894 / H 77015 / L 76759 / C 76856 (small bear at top)

Computed zones for this example:
- i-RDRB V1: 76596 → 76675
- FVG: 76675 → 76759
- Liq target: 77048 (taken at 22:00, +2h after C5 close)

Annotated render: `/tmp/btc_pattern_v1.png`

## Trade lifecycle terminology

- **Armed window** — the interval from C5 close (= pattern confirmed, limit order placed at 0.5 RDRB) until the limit fills (price retraces down to entry for long, up to entry for short). The setup is "armed" — waiting for the trigger. Measured in hours in backtest output as `hours_to_fill`. If the limit never fills, the pattern stays in armed state indefinitely (no entry timeout configured by default).
- **Trade window** — from fill to TP/SL resolution (`hours_to_exit` in backtest).

## Filters

### Filter 1 — HTF Order Block overlap

Pattern qualifies if at least one of C1..C5 (1h) falls within the time range of an HTF Order Block candle on **any** of {4h, 6h, 8h, 12h}.
- **Bullish OB** (for long): HTF candle is bearish AND next HTF candle's close > this candle's high.
- **Bearish OB** (for short): HTF candle is bullish AND next HTF candle's close < this candle's low.
- "Part of" = 1h candle's open time falls in `[OB_open_time, OB_open_time + TF)`.

6y backtest impact (LONG+SHORT combined):
- Confirmed: 340/809 trades (42%), WR 66.2%, +110R, Exp +0.324R
- Not confirmed: 469/809 (58%), WR 62.0%, +113R, Exp +0.241R
- Strongest per-TF: 6h (bull 68.6% WR, bear 72.2% WR) and 12h (bull 65.8%, bear 72.4%). 4h is weakest (close to baseline).

### Filter 2 — HTF RDRB membership (weak confirmation)

Determines whether the 1h 5-candle pattern is part of a 3-candle RDRB structure on a higher timeframe **that has fully formed by the moment of entry** (fill candle close). Armed window is included in the time available for the HTF RDRB to confirm.

HTF RDRB definition (3-candle, applied on each of {4h, 6h, 8h, 12h}; mirrors our 5-candle 1h i-RDRB but without C4/C5/FVG):
- **LONG-shape**: `c1.body_bottom ≥ c3.body_top` AND `c3.high ≥ c1.low` AND `c2.close < c1.low`
- **SHORT-shape**: `c1.body_top ≤ c3.body_bottom` AND `c3.low ≤ c1.high` AND `c2.close > c1.high`

Match conditions:
1. At least one of the 5 1h pattern candles falls within the time range of one of the 3 HTF RDRB candles (c1, c2, or c3).
2. The HTF RDRB c3 candle has **closed by the fill candle's close** (`c3_open_time + TF ≤ fill_open_time + 1h`).
3. **Direction: ANY** (either LONG-shape or SHORT-shape RDRB on HTF qualifies — direction of HTF RDRB does NOT need to match the 1h pattern direction).

Use as **weak confirmation**, not restrictive filter. Discriminative power is small but positive context.

6y backtest impact (combined Long+Short, 809 closed trades):
- ANY direction match (576 trades, 71%): WR 63.2%, +152R, Exp +0.264R
- ANY direction no match (233 trades, 29%): WR 65.2%, +71R, Exp +0.305R

LONG specific (most useful signal):
- ANY match (284): WR 63.4%, +76R
- ANY no match (118): WR 68.6%, +44R

SAME-direction variant (computed but weaker discriminator):
- SAME match (32%): WR 64.0%, +73R
- SAME no match (68%): WR 63.7%, +150R

**Historical note**: an earlier version (v3) computed same-direction membership without the timing constraint and showed a strong −35R exclusion signal. That signal was a **look-ahead artifact** — same-direction HTF RDRBs were "ratified" by future price moves (the same moves that triggered our 1h SL). Once timing is properly enforced (HTF c3 must close by entry), the signal collapses. Lesson: always check timing for HTF-confluence filters.

## Entry rule (final V1)

**HTFs for both F1 and F2: {4h, 6h, 8h, 12h, 1D}**

Enter the trade if `F1 OR F2_same` is confirmed at C5 close / by fill. F2 in the entry rule uses the **same-direction** variant (bullish HTF RDRB for long pattern, bearish HTF RDRB for short pattern). F1 is same-direction by construction.

### Filter 3 (FINAL) — R/ATR(20) ∈ [0.55, 1.03]

After F1 ∪ F2_same, apply F3: `R / ATR(20)` on 1h at C5.close must be in `[0.55, 1.03]`.

- `R = entry − SL` for LONG (or `SL − entry` for SHORT)
- Rejects trades with too-tight SL (< 0.55 ATR, kicked by noise) or too-wide SL (> 1.03 ATR, pattern rough, TP not reached in time)
- Single condition replaces earlier multi-OR F4 attempt (in_ny ∪ R/ATR ∪ b4_b2 ∪ atr_ratio + hour exclude) — simpler and slightly higher WR.

### Filter funnel (final)

```
i-RDRB V1 + FVG strict (BTC 1h, 6y)        809 ─ 63.78% WR · +223R
   │ F1 ∪ F2_same
   ▼                                        525 ─ 64.57% WR · +153R
   │ F3: R/ATR(20) ∈ [0.55, 1.03]
   ▼                                        257 ─ 71.60% WR · +111R · MDD −6R · Sharpe 3.13
```

By side: LONG 129 (72.09% WR, +57R), SHORT 128 (71.09% WR, +54R) — symmetric.

By year: 2020 73.9%, 2021 74.5%, 2022 72.9%, 2023 64.9%, 2024 75.6%, 2025 60.5%, 2026 92.9%. All 7 years profitable.

Stratification inside F3: R/ATR 0.55–0.85 gives ~73% WR; 0.85–1.03 drops to 66.7%.

Working dataset: `/tmp/i_rdrb_v1_525_dataset.csv` (525 after F1∪F2_same).

### Filter 3 alt (1h FH/FL during armed window) — parked

Earlier exploration: require a 1h FH (long) or FL (short) to form during armed window. ~56% match rate, marginal/neutral impact, asymmetric (slight help to LONG, slight hurt to SHORT). Not in production stack. Reference: 2026-05-19 FH at 22:00 UTC+3 high 77065.80.

### Structural SL rules on 15m (parked, do not improve)

Explored replacing baseline SL = pattern.low/high with structural SL rules anchored to 15m TF elements (FVG, FL fractals, OB).

**OB classification on 15m extremum:**
- **V.1 strict**: i15 (15m with pattern.low/high) is BEAR + next 15m is BULL with body ≥ |bear body|. 58/257 trades, WR 65.5%.
- **V.2 hammer**: i15 is BULL (for long; BEAR for short) with deep wick reject (wick > body). 67/257, WR 76.1%.
- **V.3 block of orders**: i15 BEAR + next BULL weak, but strong BULL displacement within next 2-3 candles. 32/257, WR 65.6%.
- **NONE**: no clear OB. 100/257, WR 74.0%.

**4 entry × SL combinations:**
- Entry: FVG-1 (confluence with RDRB → entry = top RDRB) OR FVG-2 (below RDRB → entry = 50% of FVG-2)
- SL: 0.3 of i15 lower wick from low (V.3 rule) OR low of 15m FL after i15 (V.4 rule)
- Constraint: FVG-2 entry forces 0.3-wick SL
- Combos: A (FVG-1 + 0.3 wick), B (FVG-1 + 15m FL), C (FVG-2 + 0.3 wick)

**Impact on 257 trades:**
- Combo A: 67 trades, WR 68.7%, +25R
- Combo B: 63 trades, WR 58.7%, +11R
- Combo C: 82 trades, WR 63.0%, +21R
- All valid: 212 trades, WR 63.5%, **+57R** (vs baseline +111R)
- 45 trades had no valid FVG → skipped

**Lesson**: tighter structural SL rules systematically lose WR more than they save on cherry-picked cases. Three hand-walked examples (2026-05-17, 2026-05-02, 2026-04-23) preserved their outcomes with smaller R, but aggregate over 257 is **−54R vs baseline**. Not in production stack.

Artifacts: `/tmp/sl_combos_257_v2.csv`.

## Related

- Pattern classes per [[zone-class-liquidity-inefficiency-block]]: i-RDRB is the inefficiency/блок component; Liq is the liquidity component.
- Display times in chat per [[display-time-in-utc-plus-3]].
- "V1" suffix implies more versions to come — keep this definition stable; future revisions go to separate memory files (V2, V3...).
