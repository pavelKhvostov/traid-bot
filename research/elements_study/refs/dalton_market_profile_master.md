# Dalton — Market Profile / Auction Market Theory — Master Reference

> Source books: James F. Dalton, Eric T. Jones, Robert B. Dalton — *Mind Over Markets* (educational, mechanics) and *Markets in Profile* (philosophy, behavioral/neuroeconomic context). Profile technique originally from J. Peter Steidlmayer (CBOT). Definitions below are cross-verified against multiple public sources, cited inline as (source: domain). The Implementation sections translate every concept into something computable on BTC/ETH/SOL OHLCV+volume bars (1h, 12h) — using **only closed bars** at decision time.

---

## 1. Core philosophy (Auction Market Theory)

- **Purpose of the market = facilitate trade.** The market is a continuous two-way (double) auction. It moves *up* until it shuts off buyers (auctions too high → buying dries up), then moves *down* until it shuts off sellers, constantly probing in both directions (source: topstep.com, atas.net).
- **Price advertises opportunity; time and volume confirm (or reject) value.** Price is the *advertising mechanism*; the market broadcasts a price and then watches whether participants transact. Where the market spends **time** and trades **volume**, value is being built; where it spends little, the price was rejected (source: jimdaltontrading.com, topstep.com).
- **Price ≠ Value.** *Price* is where a trade can occur right now. *Value* is the price region where two-sided trade is accepted over time — "an area where both buyer and seller agree to transact, if only briefly" (the value area). The market is forever testing prices *away* from value to discover whether value should migrate (source: topstep.com).
- **Fair / unfair prices.** The center of the distribution (POC) is the "fairest" price — maximum two-sided activity. The extremes are "unfair" to one side, which is why they get rejected and form excess (source: tradebrigade.co, Dalton).
- **Three confirmations of acceptance — Dalton's tests at any reference level**: (1) **Price** — can the market hold above/below it? (2) **Time** — does it spend time building structure there? (3) **Volume** — does volume build to support those prices? Acceptance = all three; rejection = fast move away with single prints/excess and no time/volume build (source: algostorm.com).
- **Two participant horizons:** the **day timeframe** (locals/short-term) and the **Other Time Frame (OTF)** — larger, longer-horizon participants. Trends and value migration are driven by OTF conviction; rotation/balance is the day timeframe trading around fair value (source: jimdaltontrading.com).

---

## 2. The Market Profile construct (precise definitions)

### TPO — Time Price Opportunity
The atomic unit. Each time bracket (classically 30 minutes, lettered A, B, C…) prints a **letter at every price the market touched in that bracket**. A TPO = "the opportunity to transact at a given price during a specific time period." Stacking these letters horizontally per price row builds the bell-shaped distribution; the longest rows are where the market spent the most time (source: eminimind.com, sierrachart.com).

### POC — Point of Control
The price row with the **most TPOs** (TPO-POC) — equivalently, in a volume profile, the price with the **most volume** (Volume-POC / VPOC). It is the mode of the distribution, closest to the center of the value area; Dalton calls it the **"fairest price"** — the price of maximum two-sided acceptance (source: tradebrigade.co, eminimind.com).

### Value Area (VA) and the 70% rule
The price range containing **~70% of the day's TPOs (or volume)**, centered on the POC. 70% ≈ one standard deviation of a normal distribution. **VAH** = Value Area High, **VAL** = Value Area Low (source: eminimind.com, tradebrigade.co).

**Exact construction algorithm (TPO or volume):**
1. Sum total TPOs (or total volume) across all rows.
2. Target = 70% of that total.
3. Start at the POC row; its count is the running total.
4. Look at the **two rows above** the current cluster (combined) and the **two rows below** (combined). Add whichever **pair is larger** to the running total and extend the cluster to include those rows.
5. Repeat step 4, always adding the larger adjacent pair, until the running total **≥ 70%** of the total.
6. The top of the final cluster = VAH, bottom = VAL (source: eminimind.com).

### Volume Profile vs TPO Profile
- **TPO profile** counts *time* (letters) at each price → POC/VAH/VAL are time-based.
- **Volume profile** counts *contracts/coins traded* at each price → VPOC/VAH/VAL are volume-based.
- They usually agree closely but can diverge (lots of time, little volume = thin probing). For **crypto quant work prefer the volume profile** — volume is directly available from OHLCV and is the more meaningful "acceptance" measure. The volume mode is **VPOC**; the TPO mode is **TPOC** (source: sierrachart.com, quantvps.com).

### HVN / LVN — High / Low Volume Nodes
- **HVN** = a local **peak** in the volume histogram — a price area of heavy trade = **past acceptance / fair value**. Behavior: price tends to **slow, consolidate, and rotate** there; HVNs act as **magnets and support/resistance** — arrival/target zones, not clean bounce zones (source: quantvps.com, angelone.in).
- **LVN** = a local **trough** — little trade = **rejection / transition** zone. Behavior: price moves **fast through** LVNs (low friction); they mark **edges between distributions** and act as **breakout conduits** and decision points. A hold/rejection at an LVN is a strong directional signal (source: quantvps.com, tradingwyckoff.com).

### Excess (tails / single prints)
**Excess** = a sharp rejection at a profile extreme: price auctions quickly to a level, finds no trade, and snaps back. In TPO terms it shows as **single prints** (one-letter-wide rows) at the extreme followed by immediate rotation back inside; on a candle/volume basis it is a **long tail/wick with very low volume** at the extreme. Excess **marks the end of one auction and the start of another** and is a high-confidence top/bottom marker. A "**poor high/low**" (multiple TPOs at the extreme, no tail) is the opposite — weak, unfinished, likely to be revisited (source: beyondcandlesticks.substack.com, atas.net).

### Initial Balance (IB) and Range Extension
- **IB** = the price range of the **first hour** of the session (first two 30-min brackets) — the day-timeframe's opening "balance."
- **Range extension** = any move that pushes price **beyond the IB high or low** later in the session → signals OTF participants entered with conviction (source: eminimind.com).

### Open types (open sets the day's tone / confidence)
- **Open-Drive** — highest confidence. Opens and auctions aggressively in one direction and never looks back; OTF decided before the open. → trend day bias.
- **Open-Test-Drive** — opens, **tests** beyond a known reference (prior high/low) to confirm no business there, then **reverses and drives** the other way. High confidence.
- **Open-Rejection-Reverse** — opens, trades one way, meets opposite activity strong enough to reverse price back **through** the open. Medium confidence (initial extreme holds ~half the time).
- **Open-Auction (in range / in value)** — opens and rotates two-sidedly with no conviction; neither OTF buyer nor seller present. → balancing/rotational day bias (source: medium.com/Ratul Bhattacharya, threadreaderapp.com).

### Day types (brief)
- **Normal** — wide IB; little range extension (most of range made in first hour).
- **Normal Variation** — IB extended ~once in one direction (range extension ≈ up to 2× IB).
- **Trend** — directional, value migrates one way all day, IB is a small fraction of range, sequential single prints.
- **Double-Distribution (trend) day** — two separate balance areas connected by single prints (an LVN gap between two HVNs); price moved from one value shelf to another.
- **Neutral** — range extension on **both** sides of IB (OTF buyers and sellers both active); "neutral-center" closes near middle (indecision), "neutral-extreme" closes on an extreme (one side won) (source: marketcalls.in, eminimind.com).

### Balance vs Imbalance
- **Balance (horizontal development)** — two-sided rotation inside a range; bell-shaped profile; value accepted; price = "fair." Mean-reverting / responsive regime.
- **Imbalance (vertical development)** — directional repricing to find new value; elongated profile, single prints, value migrating. Trending / initiative regime. A move out of balance generally requires **new information** (source: algostorm.com, atas.net).

### Composite / longer-term profile
A profile built by **merging many sessions** (week, month, swing, or a custom anchored range) into one distribution. Reveals the **dominant longer-term value area, composite POC, and major HVN/LVN shelves** that govern multi-day structure. The shorter the merge, the more tactical; the longer, the more structural (source: jimdaltontrading.com, books.google.com).

### Naked / Virgin POC (nPOC / VPOC-untested)
A prior session's POC that price has **not yet returned to retest**. It is "unfinished business" and acts as a **magnet** — price tends to gravitate back to it days/weeks later. Once retested it loses special status and becomes an ordinary HVN. (Note: studies cite ~70–75% same-session POC-return when price extends away — treat as folklore to be validated, not gospel.) (source: mypivots.com, marketprofile.info).

---

## 3. Behaviour at key levels (tradeable rules)

| Level | Expected behaviour | Trade logic |
|---|---|---|
| **POC / VPOC** | Magnet; fairest price; rotation pivot | Mean-revert toward it from outside; fade extremes back to POC; nPOC = directional target |
| **VAH / VAL** | Edges of fair value | **Inside→edge**: rejection back to POC (responsive). **Acceptance outside** (time+volume build beyond): initiative breakout, value about to migrate |
| **HVN** | Price slows / consolidates / supports | Pullback **into** an HVN in trend direction = high-prob support/continuation; expect it to hold or at least pause |
| **LVN** | Price accelerates through; rejection edge | If price **rejects** an LVN → strong directional signal; if it **enters and accepts** → fast move to next HVN (breakout conduit) |
| **Excess / tail** | Auction ended there | Strong reversal marker; fade toward value, or use as stop reference (a break of excess = real new info) |
| **Poor high/low** | Unfinished | Expect revisit; not a durable turning point |

- **Value migration = trend read.** Compare consecutive value areas (POC/VAH/VAL): **higher value each period = uptrend continuation**; **lower value = downtrend**; **overlapping value = balance/rotation**. This is the single most important trend signal in Auction Market Theory (source: atas.net, algostorm.com).
- **Responsive vs initiative activity.** *Responsive* = participants reacting **against** price moving away from value (buying below value / selling above value) → supports balance/mean reversion. *Initiative* = participants pushing **with** conviction **away from** value (buying above value / selling below value) → drives breakouts and value migration. Identifying which is present tells you whether to fade or follow (source: algostorm.com, atas.net).
- **Acceptance vs rejection.** Acceptance = price **spends time and builds volume** at the new level (Dalton's price/time/volume tests pass) → trade with it. Rejection = fast move out with single prints/excess, no volume build → fade it (source: algostorm.com).

---

## 4. Direct mapping to a quant pipeline (THE KEY SECTION)

### 4.1 Build a volume profile from OHLCV bars
For a chosen window of closed bars (rolling N bars or anchored range):
1. **Define price bins.** Bin width = a fixed tick (e.g. `$10` BTC, `$1` ETH) or, better cross-asset, `(max_high − min_low)/n_bins` with `n_bins ≈ 50–100`, or a percentage grid (e.g. 0.1% bins) for scale-invariance.
2. **Distribute each bar's volume across its high–low range.** Choices, weakest→strongest:
   - **Close/midpoint bin** (simplest, biased): dump all of bar volume into the close or `(H+L)/2` bin.
   - **Uniform spread (recommended default):** spread `bar.volume` **uniformly across all bins overlapping `[low, high]`** (proportional to the fraction of each bin covered). Good OHLCV approximation of traded-at-price.
   - **Triangular/typical-price weighting:** weight bins by proximity to `HLC3 = (H+L+C)/3` (more mass near typical price). Closer to real intrabar shape; tune empirically.
   - **Sub-bar refinement:** if 1m data is available, build the 1h/12h profile from 1m closes for a far more accurate distribution.
3. **Aggregate** volume per bin across the window → histogram `vol[bin]`.

```python
# uniform-spread volume profile over closed bars
import numpy as np
def volume_profile(highs, lows, vols, n_bins=80):
    lo, hi = lows.min(), highs.max()
    edges = np.linspace(lo, hi, n_bins+1)
    prof = np.zeros(n_bins)
    for h,l,v in zip(highs, lows, vols):
        b0 = np.searchsorted(edges, l, 'right')-1
        b1 = np.searchsorted(edges, h, 'right')-1
        b0, b1 = max(b0,0), min(b1, n_bins-1)
        if b1==b0: prof[b0]+=v; continue
        prof[b0:b1+1] += v/(b1-b0+1)   # uniform; swap for weighted
    return edges, prof
```

### 4.2 Compute POC / VPOC, VAH / VAL, HVN / LVN, excess
- **VPOC** = `edges[argmax(prof)]` (bin center of max-volume bin).
- **Value Area (70%):** start at POC bin, iteratively add the **larger of the two-bins-above vs two-bins-below** sums until cumulative ≥ `0.70 * prof.sum()`; **VAH/VAL** = top/bottom edges of the resulting contiguous cluster.

```python
def value_area(edges, prof, frac=0.70):
    total=prof.sum(); poc=prof.argmax()
    lo=hi=poc; cum=prof[poc]
    n=len(prof)
    while cum < frac*total:
        up   = prof[hi+1:hi+3].sum() if hi+1<n else -1
        down = prof[lo-2:lo].sum()   if lo-1>=0 else -1
        if up==-1 and down==-1: break
        if up>=down: hi=min(hi+2,n-1); cum+=max(up,0)
        else:        lo=max(lo-2,0);   cum+=max(down,0)
    return edges[lo], edges[hi+1], edges[poc]  # VAL, VAH, VPOC
```

- **HVN / LVN** = **local maxima / minima** of `prof`. Use `scipy.signal.find_peaks` on `prof` (HVN) and on `-prof` (LVN), with `prominence` and `distance` thresholds (e.g. prominence ≥ X% of total, distance ≥ 2–3 bins) to avoid noise. Optionally smooth `prof` (rolling/Gaussian) first.
- **Excess (computable proxy):** at a profile extreme, flag excess when a bar has a **long wick with very low volume** beyond an LVN edge that is **not revisited** within k bars — e.g. `wick_frac = (H − max(O,C)) / (H − L) > 0.6` AND bin-volume in that wick zone `< p20` of profile AND price closes back inside the prior value area.

### 4.3 Anchoring for 24/7 crypto (no session close)
Crypto has **no exchange close**, so the "daily profile" must be defined explicitly. Maintain several profiles in parallel:
- **Calendar-anchored:** daily (00:00 UTC), weekly (Mon 00:00 UTC) — pragmatic, comparable to TradFi sessions.
- **Rolling composite:** last N bars (e.g. trailing 24×N hours) — adapts continuously; good for features.
- **Swing-anchored:** reset the profile at each confirmed swing high/low (or structural break) — best aligns with "value built during this leg."
- **Visible/event-anchored:** anchor from a major event (halving, listing, macro print) for the structural composite.
Run a **fast** profile (e.g. rolling 1–2 days on 1h bars) for tactical levels and a **slow** composite (weekly/monthly on 12h bars) for structural HVN/LVN shelves.

### 4.4 Candidate model FEATURES (all from closed bars only)
Distances normalized by ATR or by price (%) for cross-asset comparability:
- `dist_to_VPOC = (close − VPOC)/ATR`, signed; `abs_dist_to_VPOC`.
- `inside_VA` (bool: `VAL ≤ close ≤ VAH`); `pos_in_VA = (close−VAL)/(VAH−VAL)`.
- `dist_to_VAH`, `dist_to_VAL` (/ATR or %).
- `at_HVN` / `at_LVN` (bool: close within ±0.5 bin of nearest node); `dist_to_nearest_HVN`, `dist_to_nearest_LVN`, signed.
- `value_migration_sign` = sign(VPOC_t − VPOC_{t−1}); also `VAH`/`VAL` migration; rolling slope of VPOC over k periods (trend strength).
- `va_overlap_pct` between consecutive periods (low overlap = imbalance/trend; high = balance).
- `naked_POC_above` / `naked_POC_below` = distance to nearest untested prior-session POC (magnet targets).
- `nearest_excess_above/below` distance; `in_LVN_gap` (price inside a double-distribution single-print zone).
- `profile_shape`: skew/kurtosis of `prof`, `IB_range/period_range`, range-extension flags.
- `acceptance_score` at a tested level: bars-of-time + volume-built beyond a reference over last k bars (encodes Dalton's price/time/volume test).

---

## 5. Relevance to TREND-CONTINUATION PULLBACK (our edge focus)

This is the **highest-probability Market-Profile trade** and aligns directly with the `project_neuro_metalabel_no_edge.md` finding that the edge lives in **trend-continuation pullback + volume-profile (POC/HVN-LVN)**.

- **Why pullback-to-value works:** In an established trend, **value migrates** in the trend direction (each period's VPOC/VA higher in an uptrend). A pullback brings price back **into prior accepted value** (prior POC / VAH / a strong HVN). If that value **holds** (responsive buyers in an uptrend defend it — price/time/volume acceptance), the OTF that built the trend re-engages and price resumes. You are buying the **fair price within an up-migrating value structure**, not chasing the extreme (source: atas.net, Dalton).
- **The setup, computably:**
  1. **Trend filter:** `value_migration_sign` positive over the last k periods (VPOC slope up) — confirms OTF control. (Pairs with the Hull-1h / confluence filters already in the project.)
  2. **Pullback trigger:** price retraces **into prior value** — touches prior-period **VAH or POC**, or a high-prominence **HVN** below current price.
  3. **Rejection confirmation:** at that node, see **acceptance failure of lower prices** — fast rejection back up, low volume on the dip into the node, no value migration down (excess/wick at the low).
  4. **Entry/stop/target:** enter on rejection; **stop below the HVN/value** (a break = value migrating down = thesis dead); **target the prior swing / nearest naked POC above** (LVN above offers fast travel).
- **LVN vs HVN roles in the pullback:**
  - **HVN below = magnet/support** → the place the pullback *stops and holds*. Pullbacks that reach a strong HVN and reject are the cleanest continuation entries.
  - **LVN = fast-rejection / acceleration zone** → price travels *quickly through* it. A continuation move from the HVN should **slice through the LVN** above to the next shelf; conversely, if a pullback **blows through** an HVN into an LVN below without holding, expect a fast adverse move (avoid / invalidate).
- **Double-distribution logic:** a pullback that holds the *upper* HVN of a two-shelf structure (not falling into the single-print LVN gap) is textbook continuation; entry near the top of the LVN gap with stop below it gives tight risk.

---

## 6. Pitfalls / crypto-specific caveats

- **No regular session.** Every "daily/weekly" profile is an arbitrary UTC anchor; results are **sensitive to the anchor choice**. Test multiple anchorings (calendar, rolling, swing) and don't overfit one. Steidlmayer's 30-min bracket lettering is meaningless in 24/7 markets — use **volume profiles**, not TPO time-counts.
- **OHLCV volume profile is an approximation.** Distributing bar volume across the high–low range is **not** true traded-at-price (you don't know intrabar path). Uniform/triangular spreading introduces bias; refine with 1m data or accept it as a proxy. Footprint/order-flow data (taker-buy CVD, per the Harris note) is the truer "acceptance" signal — combine, don't replace.
- **Look-ahead is the killer bug.** A profile/POC/VA/HVN computed over a window that **includes the current (unclosed) bar or future bars** leaks the answer. Rule: at decision time `t`, build the profile from **bars ≤ t that are CLOSED**; VPOC/VAH/VAL/HVN must be functions of past bars only. Anchored "visible range" tools in charting platforms routinely include future bars — never replicate that in backtest features.
- **Magnet/return stats are folklore.** The "70–75% POC return" figure is from TradFi equity-index studies; **re-measure it on BTC/ETH/SOL** before relying on it. Crypto regimes (low-liquidity weekends, funding-driven squeezes) violate auction assumptions.
- **Bin width sensitivity.** Too few bins → blurred POC; too many → spurious HVN/LVN. Standardize (% bins or ATR-scaled) for cross-asset comparability and validate node detection thresholds out-of-sample.
- **Balance vs trend regime matters.** Mean-reversion-to-POC rules (fade VA edges) and continuation rules (follow value migration) are **opposite trades**; misclassifying the regime flips your edge. Gate every profile trade on `va_overlap` / `value_migration` regime detection.

---

## 7. Glossary (one line each)

- **Auction Market Theory** — markets exist to facilitate trade via a continuous two-way auction probing for value.
- **TPO (Time Price Opportunity)** — one letter marking that price traded in a given time bracket; the unit of the TPO profile.
- **POC / TPOC** — price row with the most TPOs (most *time*); the time-mode of the profile.
- **VPOC** — price bin with the most *volume*; the volume-mode (preferred for crypto quant).
- **Value Area (VA)** — price range holding ~70% of TPOs/volume around the POC (≈1 std dev).
- **VAH / VAL** — Value Area High / Low, the upper/lower bounds of the value area.
- **70% rule** — the value-area threshold; built by adding the larger of the two rows above vs below the POC until 70% is reached.
- **Volume profile** — histogram of volume traded per price level over a window.
- **TPO profile** — histogram of time (letters) per price level.
- **HVN (High Volume Node)** — local volume peak = accepted/fair value; magnet & support, price slows there.
- **LVN (Low Volume Node)** — local volume trough = rejection/transition; price moves fast through it.
- **Excess** — sharp rejection at an extreme (single prints / long low-volume tail) marking an auction's end.
- **Tail / single print** — one-letter-wide rows from a fast directional move; conviction & future decision zone.
- **Poor high / low** — extreme with no tail/excess; unfinished, likely revisited.
- **Initial Balance (IB)** — the first hour's price range.
- **Range extension** — price moving beyond the IB high/low.
- **Open-Drive** — open auctions aggressively one way, no return; highest confidence (trend bias).
- **Open-Test-Drive** — open tests a reference then drives the other way; high confidence.
- **Open-Rejection-Reverse** — open trades one way, reverses back through open; medium confidence.
- **Open-Auction** — two-sided rotation, no conviction; rotational/balance bias.
- **Normal / Normal-Variation / Trend / Double-Distribution / Neutral day** — day-type taxonomy by IB size, range extension, and value migration.
- **Balance (horizontal development)** — two-sided rotation; value accepted; mean-reverting regime.
- **Imbalance / vertical development** — directional repricing; value migrating; trending regime.
- **Value migration** — directional drift of successive POC/VA; up = uptrend, down = downtrend, overlapping = balance.
- **Responsive activity** — participants fading price away from value (buy below/sell above); supports balance.
- **Initiative activity** — participants pushing away from value with conviction (buy above/sell below); drives trends.
- **Acceptance** — price holds with time + volume building (Dalton's price/time/volume tests pass).
- **Rejection** — fast move out, single prints/excess, no volume build.
- **Other Time Frame (OTF)** — larger, longer-horizon participants who drive value migration and trends.
- **Composite profile** — profile merging many sessions to reveal longer-term value, POC, and HVN/LVN shelves.
- **Naked / Virgin POC (nPOC)** — a prior POC not yet retested; acts as a magnet/target until touched.
- **Fairest price** — Dalton's term for the POC: the point of maximum two-sided acceptance.

---

### Sources
- [eminimind.com — Ultimate Guide to Market Profile](https://eminimind.com/the-ultimate-guide-to-market-profile/) (TPO, POC, VA 70% algorithm, IB, range extension, day types)
- [tradebrigade.co — POC and Value Area](https://tradebrigade.co/point-of-control-and-value-area/) (POC fairest price, VA 70% = 1 std dev)
- [topstep.com — Intro to Auction Market Theory & Market Profile](https://www.topstep.com/blog/intro-to-auction-market-theory-and-market-profile) (philosophy, price vs value)
- [sierrachart.com — TPO Profile Charts](https://www.sierrachart.com/index.php?page=doc/StudiesReference/TimePriceOpportunityCharts.html) (TPO/volume profile mechanics)
- [quantvps.com — Mastering Volume Profile / Value Area guide](https://www.quantvps.com/blog/mastering-volume-profile) (HVN/LVN behavior)
- [angelone.in — High Volume Nodes](https://www.angelone.in/knowledge-center/online-share-trading/high-volume-nodes-hvn) (HVN as fair value/magnet)
- [tradingwyckoff.com — Volume Profile Complete Guide](https://tradingwyckoff.com/en/volume-profile-2/) (LVN rejection/breakout conduit)
- [algostorm.com — Market Profile / Auction Theory Guide](https://algostorm.com/market-profile/) (initiative vs responsive, balance/imbalance, Dalton's tests)
- [atas.net — Analyzing TPO: 5 elements in Dalton's opinion](https://atas.net/volume-analysis/analyzing-tpo-5-important-elements-in-jim-daltons-opinion/) and [Auction Market Theory](https://atas.net/market-theory/the-auction-market-theory/) (excess, value migration, auction logic)
- [beyondcandlesticks.substack.com — Poor Highs, Excess & Repair](https://beyondcandlesticks.substack.com/p/structural-imperfections-and-subtle) (excess vs poor high definitions)
- [medium.com / Ratul Bhattacharya — Opening Types](https://medium.com/@bhattacharya.ratul/opening-types-open-range-strategy-and-practical-applications-153df89e2bf5) & [threadreaderapp.com — Mind Over Markets Open Types](https://threadreaderapp.com/thread/1266594167347646465.html) (open types)
- [marketcalls.in — Different Types of Profile Days](https://www.marketcalls.in/market-profile/market-profile-different-types-of-profile-days.html) & [POC/PPOC](https://www.marketcalls.in/market-profile/understanding-point-of-control-poc-and-prominent-point-of-control-ppoc.html) (day types, POC)
- [mypivots.com — Virgin Point of Control](https://www.mypivots.com/dictionary/definition/158/virgin-point-of-control-vpoc) & [marketprofile.info — POC trading](https://marketprofile.info/articles/point-of-control-trading) (naked/virgin POC, magnet stats)
- [jimdaltontrading.com — What is the Market Profile](https://jimdaltontrading.com/what-is-the-market-profile-2/) (Dalton primary framing, OTF, composite)
- [github.com/bfolkens/py-market-profile](https://github.com/bfolkens/py-market-profile) & [pyquantlab.com volume profile in Python](https://www.pyquantlab.com/article.php?file=An+Algorithmic+Exploration+of+Enhanced+Volume+Profile+with+Python+and+Backtrader.html) (OHLCV volume-distribution methods)
