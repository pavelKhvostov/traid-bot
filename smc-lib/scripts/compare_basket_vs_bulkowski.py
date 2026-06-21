"""Compare Vadim C1-C7 basket (657 sigs) vs Andrey Bulkowski (520 sigs) on 12h close timeline.

Both signal at close of 12h candle. Compare:
  - Intersection: how many bars fire BOTH systems
  - Direction agreement
  - Williams confirmation rate per side
  - Coincident vs solo
"""
from __future__ import annotations
import pandas as pd
from pathlib import Path

BASKET = Path.home() / "Desktop" / "pred12h_baseline_c1c7.parquet"
BULK = Path.home() / "Desktop" / "etap_172_signals.csv"

# Load Vadim basket (657 in_basket)
df_b = pd.read_parquet(BASKET)
df_b = df_b[df_b["in_basket"] == True].copy()
df_b["close_ts"] = df_b["pivot_close_ts"]
df_b["side_match"] = df_b["direction"].map({"high": "short", "low": "long"})
print(f"Vadim basket: {len(df_b)}; dirs: {df_b['direction'].value_counts().to_dict()}")

# Load Andrey Bulkowski (520)
df_a = pd.read_csv(BULK, parse_dates=["time"])
df_a["close_ts"] = df_a["time"] + pd.Timedelta(hours=12)
df_a["close_ts"] = df_a["close_ts"].dt.tz_localize("UTC") if df_a["close_ts"].dt.tz is None else df_a["close_ts"]
print(f"Andrey Bulkowski: {len(df_a)}; sides: {df_a['side'].value_counts().to_dict()}")

# Period intersection
period_start = max(df_b["close_ts"].min(), df_a["close_ts"].min())
period_end = min(df_b["close_ts"].max(), df_a["close_ts"].max())
print(f"\nCommon period: {period_start} → {period_end}")

# Filter to common period
df_b_c = df_b[(df_b["close_ts"] >= period_start) & (df_b["close_ts"] <= period_end)]
df_a_c = df_a[(df_a["close_ts"] >= period_start) & (df_a["close_ts"] <= period_end)]
print(f"  Vadim in common: {len(df_b_c)}")
print(f"  Andrey in common: {len(df_a_c)}")

# === Intersection — same close_ts AND same direction ===
# Build keys (ts, side)
b_keys = set(zip(df_b_c["close_ts"], df_b_c["side_match"]))
a_keys = set(zip(df_a_c["close_ts"], df_a_c["side"]))
intersect = b_keys & a_keys
only_b = b_keys - a_keys
only_a = a_keys - b_keys

print(f"\n=== Strict match (same close_ts + same direction) ===")
print(f"  Vadim basket events: {len(b_keys)} (unique by ts+side)")
print(f"  Andrey events:       {len(a_keys)}")
print(f"  ∩ Both fire:         **{len(intersect)}**")
print(f"  Only Vadim:          {len(only_b)}")
print(f"  Only Andrey:         {len(only_a)}")
print(f"  Vadim ∩ / Vadim total = {len(intersect)/len(b_keys)*100:.1f}%")
print(f"  Vadim ∩ / Andrey total = {len(intersect)/len(a_keys)*100:.1f}%")

# === Same bar, IGNORING direction ===
b_ts = set(df_b_c["close_ts"])
a_ts = set(df_a_c["close_ts"])
print(f"\n=== Same close_ts (ANY direction) ===")
print(f"  ∩ Same bar:    {len(b_ts & a_ts)}")
print(f"  Only Vadim ts: {len(b_ts - a_ts)}")
print(f"  Only Andrey ts: {len(a_ts - b_ts)}")

# === Per side ===
print(f"\n=== Per direction ===")
for v_dir, a_side, label in [("high", "short", "HH/SHORT"), ("low", "long", "LL/LONG")]:
    b_sub = df_b_c[df_b_c["direction"] == v_dir]
    a_sub = df_a_c[df_a_c["side"] == a_side]
    b_ts = set(b_sub["close_ts"])
    a_ts = set(a_sub["close_ts"])
    inter = b_ts & a_ts
    print(f"  {label:<10} Vadim {len(b_ts):>4}  Andrey {len(a_ts):>4}  ∩ {len(inter):>4}  ({len(inter)/max(len(b_ts),1)*100:.1f}% / {len(inter)/max(len(a_ts),1)*100:.1f}%)")

# === Williams confirm rate ===
# Vadim basket has 'confirmed' field
print(f"\n=== Williams confirm rate ===")
b_in = df_b_c[df_b_c["close_ts"].isin(b_ts := set(df_b_c["close_ts"]))]
print(f"  Vadim basket P(W):       {df_b_c['confirmed'].mean()*100:.1f}% ({df_b_c['confirmed'].sum()}/{len(df_b_c)})")

# For intersection events, compute Vadim confirmed rate
inter_ts = {ts for ts, _ in intersect}
b_inter = df_b_c[df_b_c["close_ts"].isin(inter_ts)]
b_only = df_b_c[~df_b_c["close_ts"].isin(inter_ts)]
print(f"  Vadim ∩ Andrey conf:     {b_inter['confirmed'].mean()*100:.1f}% ({b_inter['confirmed'].sum()}/{len(b_inter)})")
print(f"  Vadim solo conf:         {b_only['confirmed'].mean()*100:.1f}% ({b_only['confirmed'].sum()}/{len(b_only)})")

# Per Bulkowski pattern: contribution to overlap
print(f"\n=== Andrey patterns within ∩ ===")
inter_a = df_a_c[df_a_c.apply(lambda r: (r["close_ts"], r["side"]) in intersect, axis=1)]
pat_count = inter_a["pattern"].value_counts()
for p, n in pat_count.items():
    total_p = (df_a_c["pattern"] == p).sum()
    print(f"  {p:<14} {n:>3} / {total_p:>3}  ({n/total_p*100:.0f}% of pattern in intersection)")

# Save full intersect for further analysis
out = Path.home() / "Desktop" / "basket_vs_bulkowski_intersect.csv"
df_inter = pd.DataFrame([{"close_ts": ts, "side": s} for ts, s in intersect])
df_inter = df_inter.sort_values("close_ts")
df_inter.to_csv(out, index=False)
print(f"\n→ Intersection saved: {out}")
