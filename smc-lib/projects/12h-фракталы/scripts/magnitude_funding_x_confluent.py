"""Empirical test: funding rate × n_confluent → realized magnitude.

Гипотеза: extreme funding + high confluence = непропорционально большой move
в направлении pivot за 48h после close бара i.

Pipeline:
1. Load 14 fire parquets → n_confluent per Basket event
2. Pull BTC funding rate from Binance API (2020-01-01 → now)
3. Map funding to 12h bar (causal: last funding ≤ close of bar i)
4. Compute realized max move in expected direction (4 bars forward)
5. Bucket by (funding × n_confluent) → mean realized magnitude
"""
from __future__ import annotations
import json
import urllib.request
import pathlib
from datetime import datetime, timezone
from collections import defaultdict
import numpy as np
import pandas as pd
from _lib import load_12h, OUT_DIR

# ─── Step 1: load fires + compute n_confluent ──────────────────
print("Loading 14 fire parquets...")
CODES = ["B1C1","B1C2","B1C3","B1C4","B1C5","B1C6",
         "B2C1","B2C2","B3C1","B4C1","B4C2","B5C1","B8C1","B9C1"]

fires_per = {}
for c in CODES:
    df = pd.read_parquet(OUT_DIR / f"{c}_fires.parquet")
    fires_per[c] = set(zip(df["bar_idx"].astype(int), df["zone_direction"]))

# n_confluent per Basket event
all_events = set()
for s in fires_per.values():
    all_events |= s

confluence = {}
fired_blocks = {}  # (k, d) → list of codes
for ev in all_events:
    cnt = 0; blocks = []
    for c in CODES:
        if ev in fires_per[c]:
            cnt += 1
            blocks.append(c)
    confluence[ev] = cnt
    fired_blocks[ev] = blocks

print(f"  Basket events: {len(all_events)}")
print(f"  Confluence distribution: {pd.Series(list(confluence.values())).value_counts().to_dict()}")

# ─── Step 2: fetch funding rates from Binance ──────────────────
CACHE = pathlib.Path.home() / "Desktop/btc_funding_binance.parquet"
if CACHE.exists():
    print(f"Loading funding cache from {CACHE}...")
    fdf = pd.read_parquet(CACHE)
else:
    print("Fetching BTC funding rate from Binance API...")
    base_url = "https://fapi.binance.com/fapi/v1/fundingRate"
    start_ms = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    records = []
    cursor = start_ms
    while cursor < end_ms:
        url = f"{base_url}?symbol=BTCUSDT&startTime={cursor}&endTime={end_ms}&limit=1000"
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            print(f"  ERROR: {e}"); break
        if not data: break
        records.extend(data)
        last = int(data[-1]["fundingTime"])
        if last <= cursor: break
        cursor = last + 1
        print(f"  fetched up to {datetime.fromtimestamp(last/1000, timezone.utc):%Y-%m-%d}, total {len(records)}")
    fdf = pd.DataFrame(records)
    fdf["fundingTime"] = fdf["fundingTime"].astype(np.int64)
    fdf["fundingRate"] = fdf["fundingRate"].astype(float)
    fdf = fdf.sort_values("fundingTime").reset_index(drop=True)
    fdf.to_parquet(CACHE, index=False)
    print(f"  Saved cache: {CACHE}  ({len(fdf):,} records)")

print(f"  Funding records: {len(fdf):,}")
print(f"  Range: {datetime.fromtimestamp(fdf['fundingTime'].iloc[0]/1000, timezone.utc):%Y-%m-%d} "
      f"→ {datetime.fromtimestamp(fdf['fundingTime'].iloc[-1]/1000, timezone.utc):%Y-%m-%d}")

# ─── Step 3: map funding to 12h pivot bar (causal) ──────────────
bars = load_12h()
n12 = bars["n"]
t12 = bars["t"]
TF12 = 12 * 60 * 60 * 1000
funding_ts = fdf["fundingTime"].values
funding_rate = fdf["fundingRate"].values

# For each pivot bar i: last funding ≤ close of bar i (= open of bar i + 12h)
def funding_at_close(i):
    close_ms = int(t12[i] + TF12)
    j = int(np.searchsorted(funding_ts, close_ms, side="right")) - 1
    if j < 0: return np.nan
    return funding_rate[j]

# ─── Step 4: realized magnitude (next 4 bars = 48h) ───────────
def realized_move(i, direction, N=4):
    """Max move in expected direction over next N bars (in %)."""
    if i + N >= n12: return np.nan
    c0 = bars["c"][i]
    fut_h = bars["h"][i+1:i+1+N]
    fut_l = bars["l"][i+1:i+1+N]
    if direction == "short":  # FH: expect price ↓
        return (c0 - fut_l.min()) / c0 * 100
    else:  # FL long: expect price ↑
        return (fut_h.max() - c0) / c0 * 100

# ─── Step 5: build event-level dataset ─────────────────────────
print("\nBuilding event dataset...")
rows = []
for (k, d), cnt in confluence.items():
    fund = funding_at_close(k)
    move = realized_move(k, d)
    rows.append({
        "bar_idx": k,
        "ts_ms": int(t12[k]),
        "direction": d,
        "n_confluent": cnt,
        "funding": fund,
        "move_pct": move,
        "blocks": ",".join(fired_blocks[(k, d)]),
    })
events = pd.DataFrame(rows).dropna(subset=["funding", "move_pct"])
print(f"  Events with valid funding+move: {len(events):,}")

# ─── Step 6: bucket analysis ───────────────────────────────────
# Funding buckets: quintiles (sign-aware)
events["funding_bps"] = events["funding"] * 10_000  # bps (per 8h)
events["funding_z"] = (events["funding_bps"] - events["funding_bps"].mean()) / events["funding_bps"].std()

print(f"\nFunding distribution (per-8h, bps = 0.01%):")
print(f"  min={events['funding_bps'].min():.2f}  p10={events['funding_bps'].quantile(0.10):.2f}  "
      f"median={events['funding_bps'].median():.2f}  "
      f"p90={events['funding_bps'].quantile(0.90):.2f}  max={events['funding_bps'].max():.2f}")

# Funding buckets by absolute extremes (because both extremes drive squeezes)
def funding_bucket(b):
    if b < -3:    return "F_extreme_neg"
    if b < -1:    return "F_neg"
    if b < 1:     return "F_neutral"
    if b < 3:     return "F_pos"
    return "F_extreme_pos"

# Direction-aware: short pivots care about positive funding (lots of longs to squeeze)
#                  long pivots care about negative funding (lots of shorts to squeeze)
def funding_signed_for_direction(row):
    """Returns funding aligned with squeeze direction.
    Short pivot (price ↓ expected): high positive funding = many longs to squeeze = good
    Long pivot  (price ↑ expected): high negative funding = many shorts to squeeze = good (flip sign)
    """
    f = row["funding_bps"]
    return f if row["direction"] == "short" else -f

events["funding_signed"] = events.apply(funding_signed_for_direction, axis=1)
events["funding_bucket"] = events["funding_signed"].apply(funding_bucket)

# Confluence buckets
def conf_bucket(c):
    if c == 1: return "C1"
    if c == 2: return "C2"
    if c == 3: return "C3"
    return "C4+"

events["conf_bucket"] = events["n_confluent"].apply(conf_bucket)

# ─── Heatmap: mean realized move ───────────────────────────────
print("\n" + "=" * 90)
print("HEATMAP — mean realized move % by (funding_signed × n_confluent)")
print("            (funding_signed: positive = squeeze setup для нашего направления pivot)")
print("=" * 90)

pivot_mean = events.pivot_table(values="move_pct",
                                 index="funding_bucket",
                                 columns="conf_bucket",
                                 aggfunc="mean")
pivot_n = events.pivot_table(values="move_pct",
                              index="funding_bucket",
                              columns="conf_bucket",
                              aggfunc="count")
order_f = ["F_extreme_neg", "F_neg", "F_neutral", "F_pos", "F_extreme_pos"]
order_c = ["C1", "C2", "C3", "C4+"]
pivot_mean = pivot_mean.reindex(index=order_f, columns=order_c)
pivot_n = pivot_n.reindex(index=order_f, columns=order_c)

print("\nMEAN MOVE %:")
print(pivot_mean.round(2).fillna(0.0).to_string())
print("\nN events:")
print(pivot_n.fillna(0).astype(int).to_string())

# ─── Marginal effects ─────────────────────────────────────────
print("\n" + "=" * 90)
print("MARGINAL effects (за counterfactuals)")
print("=" * 90)
print("\nBy n_confluent only:")
print(events.groupby("conf_bucket")["move_pct"].agg(["count", "mean", "std", "median"]).round(2))
print("\nBy funding_signed only:")
print(events.groupby("funding_bucket")["move_pct"].agg(["count", "mean", "std", "median"])
      .reindex(order_f).round(2))

# ─── Interaction effect ────────────────────────────────────────
print("\n" + "=" * 90)
print("INTERACTION test — is funding × confluence > sum of marginals?")
print("=" * 90)
base_mean = events["move_pct"].mean()
print(f"Baseline (all events): mean move = {base_mean:.2f}%")

# Top-right cell: extreme funding + high confluence
top_cell = events[(events["funding_bucket"].isin(["F_pos", "F_extreme_pos"]))
                  & (events["conf_bucket"].isin(["C3", "C4+"]))]
print(f"\nTop interaction cell (funding≥+1bps AND n_confluent≥3):")
print(f"  n = {len(top_cell)}")
if len(top_cell) > 0:
    print(f"  mean move = {top_cell['move_pct'].mean():.2f}%")
    print(f"  median = {top_cell['move_pct'].median():.2f}%")
    print(f"  lift vs baseline: {top_cell['move_pct'].mean()/base_mean:.2f}x")

# Confirmed proxy
print(f"\nMove ≥ 3% threshold rate:")
for bucket, sub in [("All", events),
                     ("Top cell (F_pos AND C3+)", top_cell),
                     ("Anti cell (F_neutral AND C1)", events[(events["funding_bucket"]=="F_neutral") & (events["conf_bucket"]=="C1")])]:
    if len(sub) == 0: continue
    p3 = (sub["move_pct"] >= 3).mean() * 100
    p5 = (sub["move_pct"] >= 5).mean() * 100
    print(f"  {bucket}: n={len(sub):>4}  P(move≥3%) = {p3:>5.1f}%   P(move≥5%) = {p5:>5.1f}%")

# Save events
out = OUT_DIR / "events_with_funding_confluent.parquet"
events.to_parquet(out, index=False)
print(f"\nSaved event dataset: {out}")
