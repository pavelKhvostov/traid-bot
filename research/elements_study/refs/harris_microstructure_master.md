# Harris — Trading & Exchanges (Market Microstructure) — Master Reference

> Larry Harris, *Trading and Exchanges: Market Microstructure for Practitioners* (Oxford University Press, 2003). This note distills the book's framework and maps every concept to something **computable on Binance BTC/ETH/SOL data** (OHLCV + kline taker-buy fields + aggTrades) or to a **testable hypothesis**. Sources verified via web research are cited inline as (source: domain).

---

## 0. The one-paragraph thesis (read this first)

Markets are a contest between **informed traders** (who know something about value) and **uninformed traders** (who trade for reasons unrelated to value: liquidity needs, hedging, noise). Informed order flow **moves price permanently** because dealers/market-makers who trade against it lose, and they protect themselves by widening spreads (adverse selection). **Profits accrue to those who supply liquidity to uninformed flow and to informed traders whose information is correct.** Everything in the book — order types, the book, spread components, price impact — is a consequence of this information game. For us as quants, the single most exploitable, *measurable* shadow of "who is trading and why" on Binance is **signed (taker) order flow**, available directly in the kline and aggTrades data without any trade-sign inference.

---

## 1. Who trades and why — the taxonomy (central to the book)

Harris classifies traders by **motive**, not by instrument. (source: bookey.app, cfainstitute.org, turtletrader.com)

### 1.1 Profit-motivated traders
- **Informed traders** — trade on estimates of fundamental value. Harris splits them:
  - **Value traders** — estimate fundamental value (deep research), buy cheap / sell dear. They are the ultimate source of liquidity and price discovery.
  - **News traders** — trade on new information about value before it is fully reflected; fast.
  - Informed traders impose **adverse selection** on liquidity suppliers: when they trade, the dealer is on the wrong side, so the dealer systematically loses to them.
- **Parasitic / predatory traders** — profit from *other traders' patterns*, not from value. (source: cfainstitute.org)
  - **Front-runners** — anticipate large orders and trade ahead.
  - **Quote-matchers / order-flow anticipators** — step in front of standing limit orders to capture the option-like value of priority.
  - **Sentiment-oriented technical traders** — trade on perceived crowd behavior.
  - **Market manipulators** — bluffing, spoofing, pump-and-dump (some illegal).
- **Dealers / market-makers** — supply **immediacy/liquidity**; profit from the spread; lose to informed flow, win from uninformed flow; manage **inventory**.
- **Arbitrageurs** — enforce price consistency across venues/instruments.

### 1.2 Utilitarian (uninformed) traders
- Trade for reasons **outside the market**: investors deploying cash, hedgers, gamblers, tax/liquidity-driven sellers, index rebalancers.
- **Noise traders** — trade on no real information (or on noise mistaken for information).
- **Key result:** *uninformed traders lose to informed traders, on average.* They pay the spread and suffer adverse price impact. They are the "prey" whose flow funds the dealers and the informed.

### 1.3 KEY THESIS (operational)
> **Profits come from (a) providing liquidity to uninformed flow, or (b) being the informed flow.** Informed order flow carries information → **permanent** price impact. Uninformed flow is noise → **temporary**, mean-reverting impact.
- **For us:** if a price move is accompanied by strong, persistent *signed* flow in the same direction, treat it as **informed/continuation**. If price moves *without* corroborating signed flow, suspect **uninformed/noise → fade or expect reversion**. This is the testable bridge from Harris to a feature set.

---

## 2. Order types, the book, liquidity

### 2.1 Limit vs market orders
- **Market order (taker / liquidity demander)** — demands immediacy, crosses the spread, **pays** the spread, accepts price uncertainty. On Binance this is the **taker** side.
- **Limit order (maker / liquidity supplier)** — offers immediacy, posts at a price, **earns** the spread but bears (a) **execution uncertainty** (may not fill) and (b) the **adverse-selection / free-option** risk (fills exactly when informed traders pick it off). On Binance this is the **maker** side.
- The **limit order book** is the aggregate of standing limit orders at each price; depth at each level shows available liquidity.

### 2.2 Bid/ask spread — three components (source: acsu.buffalo.edu, sciencedirect.com)
The quoted half-spread compensates the liquidity supplier for:
1. **Order-processing cost** — fixed cost of matching/standing by.
2. **Inventory-holding cost** — compensation for holding unwanted inventory and the risk of price moves against it; drives **mean-reverting quote skew** as the dealer offloads inventory.
3. **Adverse-selection cost** — the expected loss to better-informed traders. This is the **information** component and the one Harris emphasizes: spreads widen exactly when informed trading is more likely.

### 2.3 The four/five dimensions of liquidity (source: empirica.io, medium.com, mostlyeconomics)
- **Depth** — quantity available at/near the best quotes (size you can trade without moving price).
- **Breadth** — many orders, large size, across many participants (a thin "breadth" = fragile).
- **Tightness** — the bid-ask **spread** itself (cost of a round trip for small size).
- **Resiliency** — how fast the book/price **recovers** after a liquidity-demanding shock. Resilient market: temporary imbalances quickly attract replenishing orders.
- **Immediacy** — how fast you can trade *now* (the service market orders buy and limit orders sell).

### 2.4 Price discovery & efficiency
- **Price discovery** = the process by which trading incorporates information into price. Informed trading is the engine.
- A market is **informationally efficient** if prices reflect available information; the *permanent* component of price impact is the measurable footprint of price discovery.

---

## 3. Order flow & price impact — THE KEY SECTION for us

### 3.1 Signed order flow / trade sign
- Each trade is **buyer-initiated** (aggressor was the buyer, lifting the ask) or **seller-initiated** (aggressor was the seller, hitting the bid).
- The **aggressor** is the one demanding immediacy with a marketable order = the **taker**.
- **Inferring sign when not given** (equities historically have no labeled side):
  - **Quote rule (Lee-Ready):** trade above the quote midpoint → buyer-initiated; below → seller-initiated. (source: medium.com/@simomenaldo)
  - **Tick rule:** price higher than previous trade → buyer-initiated; lower → seller-initiated; on a zero-tick, use the last non-zero change. Accuracy degrades in volatile/trending markets. (source: medium.com, sciencedirect.com)
  - **Lee-Ready algorithm (1991):** combines quote rule (primary) + tick rule (tie-break at midpoint). The canonical equity trade-sign classifier.
- **CRUCIAL for crypto:** On Binance we **do not need** Lee-Ready / tick rule. The exchange **labels the aggressor directly** (taker-buy volume in klines; `isBuyerMaker` in aggTrades). This is ground-truth trade sign — a major data advantage over the equity microstructure literature.

### 3.2 Order-flow imbalance & inventory
- **Trade/order-flow imbalance (OFI)** = (buyer-initiated volume − seller-initiated volume), aggregated over a window. Persistent positive OFI = net demand for immediacy from buyers.
- **Market-maker inventory:** as MMs absorb one-sided flow they accumulate inventory and **skew quotes** to revert it → a *temporary* impact / mean-reversion mechanism. Empirically, OFI is one of the strongest contemporaneous explainers of returns. (source: arxiv.org 2004.08290)

### 3.3 Price impact: temporary vs permanent
- **Permanent impact** — change in the *equilibrium* price caused by the **information** in the trade (informed flow). Does not revert. This is price discovery. (source: Almgren-Chriss 2000)
- **Temporary impact** — transient deviation from equilibrium caused by demanding immediacy / consuming depth; **reverts** as the book refills (resiliency). This is the uninformed/liquidity component.
- **Kyle's λ (lambda), 1985** — the slope **Δprice / net-order-flow**; the market-maker's pricing of *how much information is embedded per unit of signed volume*. High λ = illiquid / informationally sensitive (small flow moves price a lot); low λ = deep, liquid. (source: kniyer.substack.com, medium.com)
  - **Computable proxy:** regress bar return on bar signed volume (delta) over a rolling window; the slope is an empirical λ. Rising λ = market becoming informationally toxic / thin.

### 3.4 VPIN / order-flow toxicity (concept)
- **VPIN** = Volume-Synchronized Probability of Informed Trading (Easley, López de Prado, O'Hara 2012). Bucket trades into **equal-volume buckets**, measure |buy_vol − sell_vol| / bucket_volume, average over a rolling window. (source: quantresearch.org, stern.nyu.edu)
- High VPIN = **toxic flow** = liquidity providers are being adversely selected → precedes liquidity withdrawal and large adverse moves (it spiked before the 2010 Flash Crash). Order flow is "toxic" when it is informed/imbalanced and the MM is on the losing side. (source: medium.com/@lucasastorian — applied to BTC spot)
- **For us:** a crypto-adapted VPIN (volume buckets from aggTrades, signed by `isBuyerMaker`) is a candidate **regime/risk feature** — high toxicity = avoid mean-reversion, expect trend/continuation or volatility expansion.

### 3.5 CVD (Cumulative Volume Delta) and delta — define precisely
- **Delta (per bar)** = aggressive-buy volume − aggressive-sell volume = `taker_buy_base − (volume − taker_buy_base)` = `2·taker_buy_base − volume`. (source: coinglass.com, bookmap.com)
- **CVD** = running cumulative sum of delta: `CVD_t = CVD_{t-1} + delta_t`. It tracks **only aggressive (taker) trades**, i.e. who is *demanding* immediacy. (source: coinglass.com, luxalgo.com)
- CVD is the practitioner's directly-observable analogue of Harris's **cumulative signed order flow** — the running net of buyer- vs seller-initiated volume that drives permanent price impact.

---

## 4. Binance data mapping (CONCRETE)

### 4.1 Kline / candlestick response — all 12 fields (VERIFIED)
Binance returns each kline as a **12-element array** (source: developers.binance.com spot market-data-endpoints):

| Index | Field | Notes |
|------:|-------|-------|
| 0 | Kline **open time** (ms) | bar start |
| 1 | **Open** price | |
| 2 | **High** price | |
| 3 | **Low** price | |
| 4 | **Close** price | |
| 5 | **Volume** (base asset) | total base traded |
| 6 | Kline **close time** (ms) | bar end |
| 7 | **Quote asset volume** | total quote (e.g. USDT) traded |
| 8 | **Number of trades** | trade count |
| 9 | **Taker buy base asset volume** | ← aggressive-buy base volume |
| 10 | **Taker buy quote asset volume** | ← aggressive-buy quote volume |
| 11 | **Unused / ignore** | legacy field |

- **Index 9 = Taker buy base asset volume** and **Index 10 = Taker buy quote asset volume** — CONFIRMED. (source: developers.binance.com, dev.binance.vision/t/taker-buy-base-asset-volume/6026)
- **Meaning of taker-buy:** the portion of total volume where the **buyer was the taker** (aggressor lifting the ask = market buys). "When a buyer is a maker, the seller must be a taker, and vice versa." (source: dev.binance.vision)

### 4.2 Deriving signed flow from a kline
```
buy_vol   = taker_buy_base                       # index 9 (aggressive buying)
sell_vol  = volume - taker_buy_base              # index 5 - index 9 (aggressive selling)
delta     = buy_vol - sell_vol = 2*taker_buy_base - volume
CVD_t     = CVD_{t-1} + delta_t                  # cumulative
```
(source: dev.binance.vision — "Taker sell volume = Total volume − Taker buy base volume")

Quote-denominated version (better cross-asset comparability, removes price-level scaling):
```
buy_quote  = taker_buy_quote                     # index 10
sell_quote = quote_asset_volume - taker_buy_quote # index 7 - index 10
delta_quote = 2*taker_buy_quote - quote_asset_volume
```

### 4.3 Finer signed flow — aggTrades / trades endpoints
- `GET /api/v3/aggTrades` returns each aggregated trade with field **`m` = `isBuyerMaker`** (boolean). (source: developers.binance.com)
- **Sign convention (IMPORTANT, easy to get backwards):**
  - `isBuyerMaker == true` → the **buyer was the maker (passive)** → the **seller was the taker/aggressor** → **seller-initiated** trade → counts as **sell volume** (negative delta).
  - `isBuyerMaker == false` → the **buyer was the taker/aggressor** → **buyer-initiated** → **buy volume** (positive delta).
- Use aggTrades when you need intrabar delta, footprint, true volume-bucket VPIN, or absorption timing finer than the 1h/12h bar.

### 4.4 Caveat — no trade-sign inference needed
> Unlike equities (where Lee-Ready/tick-rule *infers* the aggressor), Binance **publishes the aggressor side directly** (taker-buy in klines, `isBuyerMaker` in aggTrades). This is a clean, ground-truth trade sign. Do **not** layer tick-rule inference on top — it only adds error.

---

## 5. Candidate FEATURES for a model (computable per bar)

All features below use **closed-bar** taker fields (no look-ahead). Prefer quote-denominated or ratio forms for cross-asset (BTC/ETH/SOL) comparability.

| Feature | Formula (per bar, closed) | Microstructure meaning |
|---|---|---|
| `taker_buy_ratio` | `taker_buy_base / volume` ∈ [0,1] | aggressor balance; >0.5 = net aggressive buying |
| `bar_delta` | `2·taker_buy_base − volume` | net signed (taker) volume this bar |
| `bar_delta_quote` | `2·taker_buy_quote − quote_vol` | same, $-denominated (scale-free) |
| `CVD` | `cumsum(bar_delta)` | running net order-flow (Harris cum. signed flow) |
| `CVD_slope_N` | OLS slope of CVD over last N bars | order-flow trend / pressure |
| `CVD_div` | sign mismatch: price lower-low while CVD higher-low (or vice versa) | seller/buyer exhaustion (see §6) |
| `OFI_N` | `Σ bar_delta` over N bars | order-flow imbalance over window |
| `rel_volume` | `volume / SMA(volume, N)` | participation / effort |
| `effort_vs_result` | `abs(delta) / abs(price_change)` (or vs ATR) | high effort + tiny result = **absorption** |
| `kyle_lambda_N` | rolling OLS slope: `return ~ bar_delta` | informational price sensitivity / toxicity |
| `vpin_N` | rolling mean of `abs(delta)/bucket_vol` over equal-volume buckets | order-flow toxicity / informed-trading prob |
| `delta_at_pullback` | bar_delta during the counter-trend leg | who is pushing the pullback |
| `signed_vol_z` | z-score of bar_delta_quote | normalized pressure spike |

**Absorption (key derived signal):** **high volume + small price range** = aggressive flow being absorbed by hidden passive orders on the other side. Compute as `rel_volume high AND (high−low)/ATR low`, optionally with the *opposite* side's delta dominating. (source: bookmap.com — "aggressive buyers push CVD higher but price doesn't budge → a large seller absorbing.")

---

## 6. Relevance to TREND-CONTINUATION PULLBACK (our edge)

Mapping Harris's information game onto a pullback in an uptrend:

1. **Healthy continuation pullback** = the counter-trend leg is **uninformed/liquidity-driven** (profit-taking, weak hands), so it shows **declining volume and negative-but-fading delta**. When the pullback ends, **positive delta returns** as informed/with-trend buyers re-assert. The sellers were *absorbed*; their flow was temporary (no permanent impact).
2. **CVD divergence = exhaustion / continuation tell:** price makes a **lower low** on the pullback but **CVD does NOT** make a lower low (higher low) → sellers are out of ammunition; the down-move lacked corroborating aggressive selling → **bullish continuation signal**. (source: coinglass.com, bookmap.com)
3. **Absorption at the pullback low:** a spike of aggressive **selling** (negative delta, high volume) met with **little price decline** = a passive buyer absorbing supply = informed accumulation → expect continuation up.
4. **Liquidity grab → informed re-entry:** price wicks below an obvious level (stop pool), uninformed stops are hit (parasitic/sweep), then **delta flips positive** and CVD reclaims — informed flow re-enters *with* the trend after harvesting liquidity. This is exactly Harris's "uninformed lose to informed" at the micro level, and it dovetails with the RDRB/sweep cascades already in this project's memory.

**Testable hypotheses (BTC/ETH/SOL, 1h/12h):**
- H1: Conditional on an established uptrend, pullback bars with **rising CVD vs falling price** precede higher forward returns than pullbacks with confirming (falling) CVD.
- H2: **Absorption bars** (high rel_volume, low range, opposite-side delta) at pullback extremes mark continuation entries with positive expectancy.
- H3: Continuation is stronger when `kyle_lambda`/`vpin` indicate the prior impulse was **informed** (high toxicity) rather than noise.

---

## 7. Pitfalls / caveats

- **Spot vs perp:** Binance **spot** taker-buy ≠ **USDⓈ-M futures** taker-buy. Perp flow is dominated by leverage, funding-driven positioning, and liquidations; aggression patterns differ. **Pick one consistent venue** per study (don't mix spot klines with perp CVD). Note funding-rate skew biases perp taker flow.
- **Coarse vs fine:** hourly/12h **delta is coarse** — it nets all intrabar aggression into one number, hiding absorption *sequence*. It is still a valid feature; for absorption *timing* and footprint, drop to **aggTrades**.
- **Look-ahead:** only use **closed-bar** taker fields. The live (still-forming) kline's index-9 value is partial and will repaint — never feature on the open bar.
- **CVD is path/anchor dependent:** absolute CVD has no natural zero; it depends on where you start the cumulative sum. Use **CVD over a fixed lookback / since session start**, or its **slope/divergence**, not raw level, as a feature.
- **Sign-flip bug risk:** in aggTrades, `isBuyerMaker == true` means **seller-initiated** (sell volume). Getting this backwards inverts every delta. Validate against klines: `Σ taker-buy from aggTrades ≈ index-9` for the same window.
- **Maker/taker is aggression, not direction of conviction per se:** a large informed player may *work* an order passively (as maker) to hide. Taker flow captures *demanders of immediacy* — usually the right proxy, but not the whole story (some informed flow is passive). This is the residual limitation vs a full LOB reconstruction.
- **Not value information:** Harris's "informed" means *fundamental value* info. Taker imbalance is a **proxy** for informed pressure, contaminated by noise/momentum-chasers. Treat it as a noisy signal, validate OOS.

---

## 8. Glossary (one line each)

- **Informed trader** — trades on value/news information; imposes adverse selection; drives permanent impact.
- **Uninformed / liquidity / noise trader** — trades for non-information reasons; pays the spread; loses on average.
- **Utilitarian trader** — trades to meet an external need (hedging, cash, tax), not to profit from price.
- **Parasitic trader** — profits from others' order patterns (front-runner, quote-matcher, manipulator), not from value.
- **Dealer / market-maker** — supplies immediacy, earns the spread, manages inventory, loses to informed flow.
- **Adverse selection** — liquidity supplier's expected loss from trading against the better-informed; a spread component.
- **Limit order book** — standing limit orders by price/level; shows depth and breadth.
- **Maker** — passive order supplying liquidity (earns spread, bears free-option risk).
- **Taker** — aggressive marketable order demanding liquidity (pays spread); the **aggressor / trade sign**.
- **Bid-ask spread** — quoted gap; components: order-processing + inventory-holding + adverse-selection.
- **Liquidity dimensions** — depth, breadth, tightness (spread), resiliency, immediacy.
- **Price discovery** — process of impounding information into price via trading.
- **Trade sign / signed flow** — buyer-initiated (+) vs seller-initiated (−) classification of each trade.
- **Lee-Ready algorithm** — equity trade-sign classifier (quote rule + tick rule tie-break); unneeded on Binance.
- **Tick rule** — sign a trade by comparing its price to the previous trade's price.
- **Order-flow imbalance (OFI)** — net signed volume over a window; strong contemporaneous return driver.
- **Permanent impact** — information-driven, non-reverting price change (informed flow).
- **Temporary impact** — immediacy/inventory-driven, mean-reverting price change (uninformed flow).
- **Kyle's lambda (λ)** — price change per unit net order flow; market's pricing of information per unit volume.
- **VPIN** — volume-synchronized probability of informed trading; order-flow **toxicity** gauge.
- **Toxic flow** — informed/imbalanced flow that adversely selects liquidity providers; precedes liquidity withdrawal.
- **Delta (volume delta)** — per-period aggressive-buy minus aggressive-sell volume.
- **CVD** — cumulative sum of delta; running net aggressive order flow.
- **CVD divergence** — price and CVD disagree (e.g. lower price low, higher CVD low) → exhaustion/reversal-or-continuation tell.
- **Absorption** — large aggressive flow filled by hidden passive orders with little price movement.
- **taker_buy_base (kline idx 9)** — base-asset volume where the buyer was the taker (aggressive buying).
- **taker_buy_quote (kline idx 10)** — quote-asset ($) version of the above.
- **isBuyerMaker (aggTrades `m`)** — true ⇒ buyer was maker ⇒ **seller-initiated** trade (sell volume).

---

### Sources
- Binance spot kline/aggTrades fields: [developers.binance.com](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints); [dev.binance.vision — taker buy base asset volume](https://dev.binance.vision/t/taker-buy-base-asset-volume/6026); [dev.binance.vision — volume relationships](https://dev.binance.vision/t/relationship-between-different-types-of-volume/19499)
- Harris taxonomy: [bookey.app](https://www.bookey.app/book/trading-and-exchanges); [CFA Institute review](https://rpc.cfainstitute.org/research/financial-analysts-journal/2016/trading-and-electronic-markets); [turtletrader.com](https://www.turtletrader.com/larry-harris-review/)
- Spread components & liquidity dimensions: [acsu.buffalo.edu lecture notes](http://www.acsu.buffalo.edu/~keechung/MGF743/Lecture%20Notes/LN%20-%20Components%20of%20the%20spread.pdf); [empirica.io](https://empirica.io/blog/introduction-to-liquidity-metrics/)
- Trade classification (Lee-Ready / tick rule): [medium.com/@simomenaldo](https://medium.com/@simomenaldo/trade-classification-algorithms-6a2fede1e4f5)
- Kyle's λ, permanent/temporary impact, VPIN: [kniyer.substack.com](https://kniyer.substack.com/p/the-plumbing-beneath-the-price-order); [arxiv 2004.08290](https://arxiv.org/pdf/2004.08290); [quantresearch.org VPIN](https://www.quantresearch.org/VPIN.pdf); [Easley/O'Hara, stern.nyu.edu](https://www.stern.nyu.edu/sites/default/files/assets/documents/con_035928.pdf); [BTC toxicity, medium.com](https://medium.com/@lucasastorian/empirical-market-microstructure-f67eff3517e0)
- CVD / delta / absorption / divergence: [bookmap.com](https://bookmap.com/blog/how-cumulative-volume-delta-transform-your-trading-strategy); [coinglass.com](https://www.coinglass.com/learn/cvd-en); [luxalgo.com](https://www.luxalgo.com/blog/cumulative-volume-delta-explained/)
