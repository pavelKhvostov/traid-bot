"""Basket-only тесты (restrict to A4 baseline matched, ~724 events):

Test A — funding × n_confluent (raw count)
Test B — funding × score_weighted (WR-weighted)

Compares both as feature candidates для magnitude ML head.
"""
from __future__ import annotations
import pathlib
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from _lib import load_12h, OUT_DIR, load_baseline, match_pivots

CACHE = pathlib.Path.home() / "Desktop/btc_funding_binance.parquet"

# Per-block canonical WR (from run_all.py 2026-06-06)
WR = {
    "B1C1": 94.29, "B1C2": 87.30, "B1C3": 75.38, "B1C4": 77.36,
    "B1C5": 72.73, "B1C6": 68.42,
    "B2C1": 89.66, "B2C2": 68.49,
    "B3C1": 75.20,
    "B4C1": 65.98, "B4C2": 77.78,
    "B5C1": 80.00,
    "B8C1": 82.54,
    "B9C1": 72.91,
}
BASELINE_WR = 48.60

# ─── Load events + filter to Basket-matched ────────────────────
bars = load_12h()
pmap = match_pivots(bars, load_baseline())
events = pd.read_parquet(OUT_DIR / "events_with_funding_confluent.parquet")

def in_basket(row):
    return (int(row["bar_idx"]), row["direction"]) in pmap

events["in_basket"] = events.apply(in_basket, axis=1)
basket = events[events["in_basket"]].copy()

def is_confirmed(row):
    return pmap[(int(row["bar_idx"]), row["direction"])][0]
basket["confirmed"] = basket.apply(is_confirmed, axis=1)

# Compute WR-weighted score: for each fired BxCy, add (WR_block - baseline)
def score_weighted(blocks_str):
    if not blocks_str: return 0.0
    return sum(WR[c] - BASELINE_WR for c in blocks_str.split(","))

basket["score_w"] = basket["blocks"].apply(score_weighted)

print(f"Basket events: {len(basket)}")
print(f"Direction split: {basket['direction'].value_counts().to_dict()}")
print(f"Confirmed: {basket['confirmed'].sum()}/{len(basket)} = "
      f"{100*basket['confirmed'].mean():.2f}%")

# ─── Funding signed-for-direction ──────────────────────────────
basket["funding_bps"] = basket["funding"] * 10_000

def signed(row):
    f = row["funding_bps"]
    return f if row["direction"] == "short" else -f

basket["fund_s"] = basket.apply(signed, axis=1)

def f_bucket(b):
    if b < -3:    return "F_ext_neg"
    if b < -1:    return "F_neg"
    if b < 1:     return "F_neutral"
    if b < 3:     return "F_pos"
    return "F_ext_pos"

basket["f_bucket"] = basket["fund_s"].apply(f_bucket)


def show_heatmap(label, basket, conf_col, conf_buckets_fn, bucket_order):
    basket = basket.copy()
    basket["c_bucket"] = basket[conf_col].apply(conf_buckets_fn)
    order_f = ["F_ext_neg", "F_neg", "F_neutral", "F_pos", "F_ext_pos"]
    pivot_mean = basket.pivot_table(values="move_pct", index="f_bucket",
                                     columns="c_bucket", aggfunc="mean")
    pivot_n = basket.pivot_table(values="move_pct", index="f_bucket",
                                  columns="c_bucket", aggfunc="count")
    pivot_mean = pivot_mean.reindex(index=order_f, columns=bucket_order)
    pivot_n = pivot_n.reindex(index=order_f, columns=bucket_order)
    print(f"\n{'=' * 80}\n{label}\n{'=' * 80}")
    print("\nMEAN MOVE %:"); print(pivot_mean.round(2).fillna(0).to_string())
    print("\nN events:"); print(pivot_n.fillna(0).astype(int).to_string())

    # Marginals
    print(f"\nMarginal by {conf_col}:")
    print(basket.groupby("c_bucket")["move_pct"].agg(["count", "mean", "median"])
          .reindex(bucket_order).round(2))
    print(f"\nMarginal by funding:")
    print(basket.groupby("f_bucket")["move_pct"].agg(["count", "mean", "median"])
          .reindex(order_f).round(2))

    # Interaction test
    base_mean = basket["move_pct"].mean()
    print(f"\nBaseline mean (all basket): {base_mean:.2f}%")
    top_bucket = bucket_order[-1]
    top_cell = basket[(basket["f_bucket"].isin(["F_pos", "F_ext_pos"]))
                       & (basket["c_bucket"] == top_bucket)]
    if len(top_cell) > 0:
        print(f"\nTop cell (F_pos∪F_ext_pos × {top_bucket}):")
        print(f"  n = {len(top_cell)}")
        print(f"  mean move = {top_cell['move_pct'].mean():.2f}% "
              f"(lift {top_cell['move_pct'].mean()/base_mean:.2f}×)")
        p3 = (top_cell["move_pct"] >= 3).mean() * 100
        p5 = (top_cell["move_pct"] >= 5).mean() * 100
        all_p3 = (basket["move_pct"] >= 3).mean() * 100
        all_p5 = (basket["move_pct"] >= 5).mean() * 100
        print(f"  P(≥3%) = {p3:.1f}% vs baseline {all_p3:.1f}%  (lift {p3/all_p3:.2f}×)")
        print(f"  P(≥5%) = {p5:.1f}% vs baseline {all_p5:.1f}%  (lift {p5/all_p5:.2f}×)")


# ── Test A: raw n_confluent ───────────────────────────────────
def conf_raw(c):
    if c == 1: return "C1"
    if c == 2: return "C2"
    if c == 3: return "C3"
    return "C4+"

show_heatmap("TEST A — funding × n_confluent (raw count)",
              basket, "n_confluent", conf_raw, ["C1", "C2", "C3", "C4+"])


# ── Test B: WR-weighted score ─────────────────────────────────
# Score quartiles for clean bucketing
print(f"\n\nScore distribution: min={basket['score_w'].min():.1f}  "
      f"p25={basket['score_w'].quantile(0.25):.1f}  "
      f"median={basket['score_w'].median():.1f}  "
      f"p75={basket['score_w'].quantile(0.75):.1f}  "
      f"max={basket['score_w'].max():.1f}")

q25 = basket["score_w"].quantile(0.25)
q50 = basket["score_w"].quantile(0.50)
q75 = basket["score_w"].quantile(0.75)

def score_bucket(s):
    if s < q25: return "S_low"
    if s < q50: return "S_mid_lo"
    if s < q75: return "S_mid_hi"
    return "S_high"

show_heatmap("TEST B — funding × score_weighted (WR-weighted sum)",
              basket, "score_w", score_bucket,
              ["S_low", "S_mid_lo", "S_mid_hi", "S_high"])


# ── Side-by-side comparison ───────────────────────────────────
print("\n\n" + "=" * 80)
print("HEAD-TO-HEAD: raw n_confluent vs WR-weighted score")
print("=" * 80)
print(f"\nBaseline (all basket events, n={len(basket)}):")
print(f"  Mean move: {basket['move_pct'].mean():.2f}%  "
      f"P(≥3%): {(basket['move_pct'] >= 3).mean()*100:.1f}%  "
      f"P(≥5%): {(basket['move_pct'] >= 5).mean()*100:.1f}%")

# Correlation between confluence/score and move
corr_n = basket[["n_confluent", "move_pct"]].corr().iloc[0, 1]
corr_s = basket[["score_w", "move_pct"]].corr().iloc[0, 1]
print(f"\nCorrelation with move_pct:")
print(f"  n_confluent  (raw):     ρ = {corr_n:+.3f}")
print(f"  score_w (WR-weighted):  ρ = {corr_s:+.3f}  "
      f"({'lepszy' if abs(corr_s) > abs(corr_n) else 'хуже'} чем raw)")

# Funding alone correlation
corr_f = basket[["fund_s", "move_pct"]].corr().iloc[0, 1]
print(f"  funding_signed:        ρ = {corr_f:+.3f}")

# Interaction terms
basket["int_n"] = basket["n_confluent"] * basket["fund_s"]
basket["int_s"] = basket["score_w"] * basket["fund_s"]
corr_in = basket[["int_n", "move_pct"]].corr().iloc[0, 1]
corr_is = basket[["int_s", "move_pct"]].corr().iloc[0, 1]
print(f"\nInteraction correlation:")
print(f"  n_confluent × funding:    ρ = {corr_in:+.3f}")
print(f"  score_w × funding:        ρ = {corr_is:+.3f}")

# Save final
out = OUT_DIR / "basket_only_with_score.parquet"
basket.to_parquet(out, index=False)
print(f"\nSaved: {out}")
