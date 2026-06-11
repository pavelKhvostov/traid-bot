# Grimes — Art & Science of Technical Analysis — Master Reference

> Adam Grimes, *The Art and Science of Technical Analysis: Market Structure, Price Action, and Trading Strategies* (Wiley, 2012). Grimes is a discretionary trader with a quant/statistical discipline — his central demand is that any pattern must beat a **random-walk baseline** before you trade it.
>
> **Provenance note:** this note is written from working knowledge of the book and Grimes' public writing (adamhgrimes.com / MarketLife), **without fresh per-claim web verification** (unlike the Dalton/Harris notes in this folder). Treat the *framework* as faithful; **re-verify exact indicator settings** (MACD/Keltner periods) against the book before hard-coding them.

---

## 1. Philosophical / statistical foundation

- **Baseline = random walk.** Grimes' starting assumption is that markets are *mostly* efficient and price is *close to* a random walk. Any claimed edge must be demonstrated **against that null** — if your pattern's outcome distribution is indistinguishable from random bars, it is noise dressed up as signal.
- **Edges are small, statistical, and fleeting.** There is no holy grail. A real edge shifts the probability distribution of outcomes only slightly (e.g. a few percent of expectancy). It is exploited over *many* trades, never trusted on any single one. Edges also decay as markets adapt.
- **Trading = managing a small positive-expectancy edge.** Expectancy, not win-rate, is the objective. Risk management and consistent execution dominate; the entry "secret" is a small part of the result.
- **Mean reversion vs momentum.** Markets alternate between **trending (momentum)** and **ranging (mean-reverting)** regimes. The two demand opposite trades. Most failure comes from applying a range tactic in a trend or vice versa. Grimes stresses reading *which regime you are in* before choosing a tactic.
- **Direction OR magnitude, rarely both.** A recurring Grimes theme: you might have an edge on *direction* OR on *magnitude/target*, but precise targets are mostly illusory. Manage the trade (trail, scale) rather than predict an exact destination — this is the lesson that maps directly to "**let the system pick horizon/magnitude, don't hard-code +5%**."
- **The market is the teacher, but it lies.** Random reinforcement (a bad process can win, a good process can lose on any sample) makes naive learning dangerous → you must test statistically, not by anecdote.

---

## 2. Market structure & price action (his vocabulary)

- **Two states only: trends and trading ranges**, plus the **transitions** between them. Everything reduces to where you are in this cycle.
- **Pullback vs reversal.** A **pullback** is a counter-trend move that *resolves in the trend direction* (continuation). A **reversal** is a counter-trend move that *becomes the new trend* (termination). At the moment they start they look identical — the trade is a bet on which it is, managed with a stop where the "pullback" thesis dies.
- **Two legs / complex pullbacks.** Pullbacks are often **two-legged** (an initial dip, a bounce, a second dip — the "complex pullback"). The simple one-leg pullback frequently extends into a two-leg structure; sizing/entry should anticipate this rather than be stopped out on the second leg.
- **Swing points, HH/HL/LH/LL.** Trend defined structurally: uptrend = sequence of **higher highs and higher lows**; downtrend = lower highs and lower lows. Loss of that sequence = transition.
- **Support/resistance are ZONES, not lines.** Treat S/R as bands; precise-to-the-tick levels (and exact Fibonacci values) give a false sense of precision. Reactions happen *around* a zone.
- **Momentum and the first pullback.** A strong **momentum thrust** (sharp, range-expanding move) is information: it signals a likely *new or continuing trend*. The **first pullback after a strong momentum move is the highest-conviction continuation entry** — momentum has shown its hand, and the market has not yet built opposing structure. This is the heart of his "Anti."

---

## 3. THE FOUR TRADES (central taxonomy)

Grimes argues **every** technical trade reduces to one of four, derived from the two market states × (hold/break):

### Trade 1 — Trend continuation (pullback in a trend) ★ the quintessential trade
- **Context:** an established trend (momentum leg already printed), then an orderly counter-trend pullback.
- **Trigger:** evidence the pullback is ending and the trend is resuming (pullback high taken out / momentum turns back up / reclaim of a short MA).
- **Edge source:** trends persist more than random (momentum/auto-correlation); you enter at a *better price* than chasing, with a *tight, well-defined* invalidation (below the pullback structure). Best reward:risk of the four.
- **Failure mode:** the "pullback" was actually a reversal — price keeps going and takes out the structural low. Stop placement handles this; failures are frequent but small.

### Trade 2 — Trend termination (reversal / climax / failure)
- **Context:** an extended, often **climactic/parabolic** trend; momentum *divergence*; overextension from the mean (Keltner band).
- **Trigger:** failure to make a new extreme, momentum divergence, a failure test (false breakout) at the extreme.
- **Edge source:** exhaustion — late trend chasers run out, the move reverts to value.
- **Failure mode:** fading a strong trend too early; this is the **hardest, lowest-edge** trade (counter-trend). *(This is exactly the "reversal/counter-trend" side the project kept testing and finding weak — see project memory.)*

### Trade 3 — Support/resistance holding (range trade / fade the edge)
- **Context:** a defined **trading range** (balance); price at the edge (range high/low).
- **Trigger:** rejection at the edge (failure to break, reversal bar) → fade back toward the middle.
- **Edge source:** mean reversion inside balance; responsive participants defend the edges.
- **Failure mode:** the range is actually breaking (Trade 4) — the edge gives way.

### Trade 4 — Support/resistance breaking (breakout / range expansion)
- **Context:** a range that has coiled / contracted; energy building.
- **Trigger:** decisive break and *acceptance* beyond the edge (often after a failure-test shakeout first).
- **Edge source:** transition from balance to trend — a new directional auction begins; volatility expands.
- **Failure mode:** false breakout — price pokes out and reverses back inside (which is itself Trade 3 for the other side). Breakouts have **low base hit-rate but large winners**; require expansion confirmation, not just a level touch.

> Trades 3 and 4 are mirror outcomes of the same range edge (hold vs break); Trades 1 and 2 are mirror outcomes of the same trend (continue vs terminate). Knowing the regime tells you which pair is in play.

---

## 4. Pullback trade in depth (the setup we will build)

This is Trade 1 and the focus of our project's new angle.

- **Required context (must exist first):** a real trend with a **momentum leg** — a sharp, range-expanding thrust in the trend direction (not a slow drift). No momentum leg → no high-conviction pullback. Define momentum via range expansion / MACD thrust / a run of with-trend bars.
- **The pullback itself (orderly):** a **counter-trend retrace of modest depth** that does *not* erase the momentum move — typically a few bars, declining range/volume, drifting back toward a short moving average or prior structure. Grimes is explicit that the **depth is variable** (he does NOT prescribe a fixed Fib level); shallow pullbacks in strong trends are common and are *stronger* signals than deep ones.
- **Entry concepts (any of):**
  - Pullback to a **short moving average** (he often references shorter EMAs as a dynamic with-trend reference) and resumption off it.
  - Break of the **pullback's high** (for longs) — trend resumes.
  - **MACD "Anti"** turn (see §5) — momentum pulls back toward zero/signal then re-curls in the trend direction.
  - Entry on a **measured/structural** point, not a precise Fib number.
- **Stop:** beyond the **structural point that invalidates the pullback thesis** — below the pullback low (long) / above the pullback high (short), with a little buffer. If that breaks, it was a reversal, not a pullback; get out small.
- **Targets / management:** Grimes is **skeptical of fixed targets**. His preference: take **partial profits** and **trail** the rest; let winners run because you cannot reliably predict magnitude. Use prior swing, measured-move, or a trailing stop — but treat targets as management tools, not predictions. This operationalizes "**know direction, not magnitude**."
- **First leg vs second leg:** anticipate the **complex (two-leg) pullback**; either wait for the second leg, or size so the second leg doesn't stop you out. Being stopped on the second dip right before resumption is the classic avoidable loss.

---

## 5. Indicators Grimes actually endorses

Grimes is minimalist — he distrusts most indicators and overfit systems. The few he uses:

- **MACD (classic 12, 26, 9)** — as a **momentum** gauge, not a crossover system. Used for divergence (termination) and for the **"Anti"**: after a strong momentum move, MACD pulls back toward the zero line / signal line, then **turns back up** → enter with the original trend. The Anti is essentially a **momentum-confirmed pullback-continuation** entry. *(Verify exact MACD parameters in the book.)*
- **Moving averages** — shorter EMAs as a **dynamic trend reference** and pullback target; he uses MA *slope* and price's relation to it for trend state, not mechanical crossovers.
- **Keltner Channels** — **ATR-based bands around an EMA** to measure **overextension** from the mean (a far-outside-the-band close signals climax / Trade 2 conditions; pullbacks to the mid-line set up Trade 1). *(Verify his channel length / ATR multiple in the book.)*
- **Price action / market structure first** — swing points, momentum thrusts, failure tests are primary; indicators only *confirm* structure.
- **Rejects / treats as overfit:** precise Fibonacci targets, dense indicator stacks, optimized parameter systems, anything that can't beat a random-walk null.

---

## 6. Trade management & expectancy

- **Expectancy = (WinRate × AvgWin) − (LossRate × AvgLoss)**, measured in **R-multiples** (R = initial risk = entry−stop). A positive-expectancy process traded with discipline and proper sizing is the whole game.
- **Position sizing** off fixed fractional risk per trade (a constant % of equity per R). Survival/variance management > squeezing each entry.
- **Edge lives in context + management, not the indicator.** The same MACD/MA used without trend context is worthless; with the right structure it confirms a real edge.
- **Sample size & overfitting.** Insist on enough trades to distinguish skill from luck; beware curve-fit parameters. Think in **walk-forward / out-of-sample** terms — a pattern that only works on the data you tuned it on is noise.
- **Randomness of any single outcome.** Good trades lose, bad trades win — on any one sample. Judge the *process* over a large sample, not individual results.

---

## 7. Direct mapping to a quant pipeline (KEY SECTION)

### 7.1 "Established trend" — computable
- **MA slope:** EMA(N) slope > 0 over k bars (e.g. EMA20/EMA50 on 1h), and price above it.
- **Swing structure:** sequence of higher swing highs AND higher swing lows over the last m swings (fractal swing detector — the project already has fractal code).
- **Donchian / channel:** close near upper Donchian(N) band; recent N-bar high made.
- **Momentum leg precondition:** a thrust = a run of with-trend bars or a range-expansion bar (bar range > c·ATR) within the last j bars. **Gate the whole setup on a momentum leg existing.**

### 7.2 "Orderly pullback" — computable
- **Counter-trend bars:** `pullback_bars` = count of consecutive (or net) bars retracing against trend.
- **Depth band:** `pullback_depth = (swing_high − low_of_pullback) / momentum_leg_range` — keep it a *band*, not a fixed Fib (e.g. test 0.2–0.7); shallower = stronger signal in strong trends.
- **Declining energy:** pullback bar ranges / volumes declining vs the thrust (effort fading) — pairs with Harris delta fading.
- **Distance to MA:** `dist_to_EMA = (close − EMA(N)) / ATR` — pullback brings this toward 0 from above.

### 7.3 Entry trigger — computable
- Resumption: **break of pullback swing high** (long), OR **EMA reclaim** (close back above EMA after dipping to it), OR **MACD Anti** turn (MACD histogram/line re-curls up after pulling toward zero).
- Combine with Dalton (pullback into a prior **HVN / VAH / POC** that *holds*) and Harris (delta flips positive / CVD divergence at the pullback low) — confluence of the three books.

### 7.4 Candidate FEATURES
- `trend_strength` (EMA slope, ADX-like, swing-structure score), `momentum_leg_size` (thrust range / ATR).
- `pullback_depth`, `pullback_bars`, `pullback_is_two_leg` (complex flag), `pullback_range_decay`.
- `dist_to_EMA`, `dist_to_prior_swing`, `macd_anti_state`, `bars_since_momentum_leg`.
- `first_vs_second_leg`, `overextension` (Keltner-band distance, for filtering out late/Trade-2 conditions).

### 7.5 Let the SYSTEM pick horizon/magnitude (his lesson)
- **Do not hard-code +5%.** Instead label outcomes with **multiple horizons / R-multiples** (e.g. MFE/MAE over 6/12/24/48 bars, or first-to-touch among RR 1/2/3) and let the model/empirics reveal where expectancy concentrates. Manage live with **partial + trail**, mirroring his discretionary management.
- This directly answers the project's open question (`текущие приоритеты`: "дать системе подобрать горизонт/магнитуду, не хардкодить +5%").

### 7.6 Validate vs random-walk null (his core demand)
- For any pullback rule, build the **null distribution** by sampling random entries (same count, same trend-regime conditioning, shuffled/blocked-bootstrap returns) and check the rule's expectancy/MFE percentile vs that null. *(The project already uses this — etap_188 permutation null-test, p=0.160. Apply the same gate here.)*
- Report **per-year** and **per-asset** stability, not just aggregate — an edge that only appears in one regime is suspect.

---

## 8. Pitfalls / caveats

- **Edge is horizon- and magnitude-limited.** Don't expect precise targets; expect a small directional tilt over a finite horizon. Over-precise TP/SL ratios overfit.
- **Counter-trend (Trade 2) is the low-edge trap.** Fading trends *feels* smart and is the hardest money — consistent with the project's repeated reversal/zone-reaction null results. Bias the work toward **Trade 1**.
- **Regime misclassification flips the sign** of every tactic (range fade vs trend follow). Gate on a regime read.
- **Random reinforcement.** A losing process can win on a sample and vice versa — only large-sample, null-tested statistics decide. Never promote a rule on a handful of good-looking charts.
- **Overfitting / curve fitting.** Few parameters, wide bands not exact levels, out-of-sample and per-year checks mandatory.
- **Fibonacci/precision illusion.** S/R and retracements are zones; precise levels create false confidence.

---

## 9. Glossary (one line each)

- **Random-walk baseline** — the null model price must beat for a pattern to count as edge.
- **Edge** — a small, statistical shift in the outcome distribution vs random; exploited over many trades.
- **Expectancy** — (WR×avgWin) − (LR×avgLoss), in R-multiples; the objective, not win-rate.
- **R / R-multiple** — initial risk (entry − stop); P&L expressed in multiples of R.
- **Trend** — structural sequence of higher highs+higher lows (up) / lower highs+lower lows (down).
- **Trading range / balance** — non-trending, mean-reverting state between two zones.
- **Transition** — shift between trend and range (the breakout/termination zone).
- **Pullback** — counter-trend move that *resolves with* the trend (continuation).
- **Reversal** — counter-trend move that *becomes* the new trend (termination).
- **Complex / two-leg pullback** — a pullback with a second dip after an initial bounce.
- **Momentum thrust / leg** — a sharp, range-expanding directional move; precondition for a high-conviction pullback.
- **The Anti** — momentum (MACD) pulls back toward zero then re-curls with the original trend = continuation entry.
- **Failure test** — false breakout that reverses (Wyckoff spring/upthrust); a termination/edge trigger.
- **Four Trades** — trend continuation, trend termination, S/R holding, S/R breaking.
- **Support/resistance zone** — a band (not a line) where reactions cluster.
- **Keltner Channel** — ATR bands around an EMA; gauges overextension from the mean.
- **MACD** — momentum tool (divergence + Anti), not a crossover system.
- **Direction-vs-magnitude** — you can usually know one, rarely both; manage rather than predict targets.
- **Walk-forward / out-of-sample** — test on data not used to tune; the discipline against overfitting.
- **Random reinforcement** — the market rewards/punishes process inconsistently on small samples.

---

### Sources (to re-verify before hard-coding settings)
- Adam Grimes, *The Art and Science of Technical Analysis* (Wiley, 2012) — primary.
- adamhgrimes.com / MarketLife blog & podcast — the Four Trades framing, the Anti, statistical-edge philosophy.
- (No per-claim web fetch was performed for this note — confirm exact MACD/Keltner/EMA parameters and the precise Four-Trades wording against the book.)
