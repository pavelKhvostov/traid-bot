"""STAGE 4 — Combine Basket × D-layer ML.

Two INDEPENDENT systems converge:
    1. Basket (724 events) — boolean filter "is this a pivot candidate?"
    2. D-layer ML (4 480 predictions) — probability of magnitude reach

Combination = A_sniper analog:
    Premium tier: Basket fires AND D-layer P(direction-matched) ≥ p90
    Strong:      Basket fires AND P ≥ p75
    Standard:    Basket fires AND P ≥ p50
    Weak:        Basket fires AND P < p50

Per-tier metrics:
    n events
    confirmed Williams n=2 rate
    mean realized move in expected direction
    P(reach ≥5% move)
    E_pct expected magnitude
"""
from __future__ import annotations
import pathlib
import numpy as np
import pandas as pd
from _lib import load_12h, OUT_DIR, load_baseline, match_pivots

# ─── Load Basket + D-layer ──────────────────────────────────────
print("Loading Basket events + D-layer predictions...")
bars = load_12h()
pmap = match_pivots(bars, load_baseline())

# Basket events with funding/confluent (724 + features)
events = pd.read_parquet(OUT_DIR / "events_with_funding_confluent.parquet")
events["in_basket"] = events.apply(
    lambda r: (int(r["bar_idx"]), r["direction"]) in pmap, axis=1)
basket = events[events["in_basket"]].copy().reset_index(drop=True)
basket["confirmed"] = basket.apply(
    lambda r: pmap[(int(r["bar_idx"]), r["direction"])][0], axis=1)
print(f"  Basket events: {len(basket)}  confirmed: {basket['confirmed'].sum()}")

# D-layer predictions
preds = pd.read_parquet(OUT_DIR / "D_stage3_predictions.parquet")
print(f"  D-layer predictions: {len(preds)}")

# ─── Join D-layer onto Basket events ────────────────────────────
joined = basket.merge(
    preds[["bar_idx", "pred_y_high_strong_3", "pred_y_high_strong_4", "pred_y_high_strong_5",
           "pred_y_low_strong_3", "pred_y_low_strong_4", "pred_y_low_strong_5"]],
    on="bar_idx", how="left")
print(f"  Joined: {len(joined)}  (NaN preds: {joined['pred_y_high_strong_5'].isna().sum()})")

# ─── Direction-matched D-layer prediction ───────────────────────
# SHORT pivot (FH): expect price ↓ → align with pred_y_low_strong_X
# LONG pivot (FL):  expect price ↑ → align with pred_y_high_strong_X
def aligned_pred(row, thr):
    if row["direction"] == "short":
        return row[f"pred_y_low_strong_{thr}"]
    return row[f"pred_y_high_strong_{thr}"]

for thr in [3, 4, 5]:
    joined[f"p_{thr}"] = joined.apply(lambda r: aligned_pred(r, thr), axis=1)

# E_pct expected magnitude
joined["E_pct"] = 3 * joined["p_3"].fillna(0) + joined["p_4"].fillna(0) + joined["p_5"].fillna(0)

# Drop NaN
joined_clean = joined.dropna(subset=["p_3", "p_4", "p_5"]).copy()
print(f"  Events with valid D-layer preds: {len(joined_clean)}")

# ─── Tier assignment by p_5 percentile ─────────────────────────
p5_q90 = joined_clean["p_5"].quantile(0.90)
p5_q75 = joined_clean["p_5"].quantile(0.75)
p5_q50 = joined_clean["p_5"].quantile(0.50)

def tier_assign(p5):
    if p5 >= p5_q90: return "Premium"
    if p5 >= p5_q75: return "Strong"
    if p5 >= p5_q50: return "Standard"
    return "Weak"

joined_clean["tier"] = joined_clean["p_5"].apply(tier_assign)

print(f"\nTier thresholds (by p_5):")
print(f"  Premium:  p_5 ≥ {p5_q90:.3f}  (top 10%)")
print(f"  Strong:   p_5 ≥ {p5_q75:.3f}  (top 25%)")
print(f"  Standard: p_5 ≥ {p5_q50:.3f}  (top 50%)")
print(f"  Weak:     p_5 <  {p5_q50:.3f}  (bottom 50%)")

# ─── Per-tier confirmation rate ────────────────────────────────
print("\n" + "=" * 90)
print("PER-TIER METRICS — confirmation rate + realized move")
print("=" * 90)

# Already have realized move from events file (move_pct)
joined_clean["realized_move"] = joined_clean["move_pct"]

tier_stats = joined_clean.groupby("tier").agg(
    n=("confirmed", "count"),
    confirmed_rate=("confirmed", "mean"),
    mean_move=("realized_move", "mean"),
    median_move=("realized_move", "median"),
    p_reach_3=("realized_move", lambda s: (s >= 3).mean()),
    p_reach_5=("realized_move", lambda s: (s >= 5).mean()),
    mean_p5=("p_5", "mean"),
).round(3)
tier_stats["confirmed_rate"] = (tier_stats["confirmed_rate"] * 100).round(1)
tier_stats["p_reach_3"] = (tier_stats["p_reach_3"] * 100).round(1)
tier_stats["p_reach_5"] = (tier_stats["p_reach_5"] * 100).round(1)
tier_order = ["Premium", "Strong", "Standard", "Weak"]
print(tier_stats.reindex(tier_order).to_string())

# Baseline
overall_conf = joined_clean["confirmed"].mean() * 100
overall_move = joined_clean["realized_move"].mean()
overall_p5 = (joined_clean["realized_move"] >= 5).mean() * 100
print(f"\nBaseline (всё Basket, n={len(joined_clean)}):")
print(f"  Confirmed rate: {overall_conf:.1f}%")
print(f"  Mean move:      {overall_move:.2f}%")
print(f"  P(reach ≥5%):   {overall_p5:.1f}%")

# ─── Lift vs baseline ──────────────────────────────────────────
print("\n" + "=" * 90)
print("LIFT vs Basket-only baseline")
print("=" * 90)
print(f"  {'Tier':<10} {'n':>5} {'Conf%':>7} {'Lift':>7} {'P(≥5%)':>8} {'Lift':>7}")
for t in tier_order:
    row = tier_stats.loc[t]
    lift_conf = row["confirmed_rate"] / overall_conf
    lift_p5 = row["p_reach_5"] / overall_p5 if overall_p5 > 0 else 0
    print(f"  {t:<10} {int(row['n']):>5} {row['confirmed_rate']:>6.1f}% "
          f"{lift_conf:>6.2f}× {row['p_reach_5']:>7.1f}% {lift_p5:>6.2f}×")

# ─── Direction-aware tier metrics ──────────────────────────────
print("\n" + "=" * 90)
print("DIRECTION-AWARE per-tier")
print("=" * 90)
for direction in ["short", "long"]:
    sub = joined_clean[joined_clean["direction"] == direction]
    if len(sub) == 0: continue
    print(f"\n  Direction = {direction.upper()}  (n={len(sub)})")
    sub_stats = sub.groupby("tier").agg(
        n=("confirmed", "count"),
        conf=("confirmed", lambda s: round(s.mean() * 100, 1)),
        mean_move=("realized_move", lambda s: round(s.mean(), 2)),
        p_reach_5=("realized_move", lambda s: round((s >= 5).mean() * 100, 1)),
    )
    print(sub_stats.reindex(tier_order, fill_value=0).to_string())

# ─── Top-15 Premium events ────────────────────────────────────
print("\n" + "=" * 90)
print("TOP-15 events by E_pct (D-layer expected magnitude proxy)")
print("=" * 90)
top15 = joined_clean.nlargest(15, "E_pct").copy()
top15["dt"] = pd.to_datetime(top15["ts_ms"], unit="ms", utc=True)
top15["dt_msk"] = top15["dt"].dt.tz_convert("Europe/Moscow")
print(f"  {'Date (MSK)':<19} {'Dir':<6} {'Tier':<10} {'p_3':>5} {'p_5':>5} {'E_pct':>6} "
      f"{'Actual':>8} {'Conf':>5}")
for _, r in top15.iterrows():
    dt_str = r["dt_msk"].strftime("%Y-%m-%d %H:%M")
    conf = "✓" if r["confirmed"] else "✗"
    print(f"  {dt_str:<19} {r['direction']:<6} {r['tier']:<10} "
          f"{r['p_3']:>5.2f} {r['p_5']:>5.2f} {r['E_pct']:>6.2f} "
          f"{r['realized_move']:>7.2f}% {conf:>5}")

# ─── Save ──────────────────────────────────────────────────────
keep = ["bar_idx", "ts_ms", "direction", "confirmed", "n_confluent",
        "blocks", "funding_bps",
        "p_3", "p_4", "p_5", "E_pct", "tier", "realized_move"]
out = OUT_DIR / "D_stage4_combined.parquet"
joined_clean[keep].to_parquet(out, index=False)
print(f"\nSaved combined: {out}")

# ─── Compare с Andrey A_sniper ─────────────────────────────────
print("\n" + "=" * 90)
print("Comparison с Andrey A_sniper (208 events, 75% confirmed)")
print("=" * 90)
prem = joined_clean[joined_clean["tier"] == "Premium"]
print(f"  Andrey A_sniper:           n=208,  confirmed=75.0%, baseline 66.7%")
print(f"  Наш Premium tier:          n={len(prem)},  confirmed={prem['confirmed'].mean()*100:.1f}%, "
      f"baseline {overall_conf:.1f}%")
lift_andrey = 75.0 / 66.7
lift_naш = prem['confirmed'].mean() * 100 / overall_conf if overall_conf > 0 else 0
print(f"  Andrey lift:               {lift_andrey:.2f}×")
print(f"  Наш Premium lift:          {lift_naш:.2f}×")
