"""Cross-join basket 676 × Andrey's etap_173 predictions.

For each basket pivot in Andrey's OOS window (2025-01-05 → 2026-05-21):
  - lookup p_3, p_4, p_5 (вероятность 3/4/5% move в expected direction)
  - compute expected magnitude
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timezone, timedelta

MSK = timezone(timedelta(hours=3))

# Load basket (C1-C7 ∪ C8 ∪ C9)
df_base = pd.read_parquet("/Users/vadim/Desktop/baseline_1267.parquet")
c1c7 = pd.read_parquet("/Users/vadim/Desktop/pred12h_baseline_c1c7.parquet")
c1c8 = pd.read_parquet("/Users/vadim/Desktop/pred12h_basket_c1c8.parquet")

# Merge basket flags
c1c7["key"] = c1c7["pivot_open_ts_ms"].astype(str)+"_"+c1c7["direction"]
basket_keys = set(c1c7[c1c7["in_basket"]==True]["key"])
df_base["key"] = df_base["ts"].astype(str)+"_"+df_base["direction"]
df_base["in_c1c7"] = df_base["key"].isin(basket_keys)
c1c8["key"] = c1c8["ts"].astype(str)+"_"+c1c8["direction"]
c8_keys = set(c1c8[c1c8["c8"]==True]["key"])
df_base["c8"] = df_base["key"].isin(c8_keys)

# Quick recompute C9 inline
df_f = pd.read_parquet("/Users/vadim/Desktop/force_all_bars_per_tf.parquet")
TF_LIST=["1h","2h","4h","6h","8h","12h","1d","2d","3d"]
df_f["buyer_total"]=sum(df_f[f"buyer_{tf}"] for tf in TF_LIST)
df_f["seller_total"]=sum(df_f[f"seller_{tf}"] for tf in TF_LIST)
df_f["net"]=df_f["buyer_total"]-df_f["seller_total"]
df_f["net_w2"]=df_f["net"].rolling(2).sum()
df_f_idx=df_f.set_index("open_ts_ms")
df_base["net"]=df_base["ts"].apply(lambda t: df_f_idx.loc[t,"net"] if t in df_f_idx.index else None)
df_base["net_w2"]=df_base["ts"].apply(lambda t: df_f_idx.loc[t,"net_w2"] if t in df_f_idx.index else None)
c9a=(df_base["direction"]=="low") & (df_base["net"]<=-1000)
c9b=(df_base["direction"]=="high") & (df_base["net"]>=500)
c9c=(df_base["direction"]=="low") & (df_base["net_w2"]<=-2000)
df_base["c9"] = c9a | c9b | c9c

df_base["in_basket"] = df_base["in_c1c7"] | df_base["c8"] | df_base["c9"]
basket = df_base[df_base["in_basket"]].copy()
print(f"Basket events total: {len(basket)}")

# Load Andrey's 6 prediction files
ANDR_DIR = Path("/Users/vadim/Desktop")
preds = {}
for tgt in ["y_low_strong_3","y_low_strong_4","y_low_strong_5",
            "y_high_strong_3","y_high_strong_4","y_high_strong_5"]:
    df = pd.read_csv(ANDR_DIR / f"etap_173_pred_{tgt}.csv", parse_dates=["time"])
    df["ts_ms"] = df["time"].apply(lambda t: int(t.timestamp()*1000))
    df = df.set_index("ts_ms")
    preds[tgt] = df[["p_hit"]].rename(columns={"p_hit": f"p_{tgt}"})

# OOS window
OOS_START = pd.Timestamp("2025-01-05 12:00:00+00:00")
OOS_END = pd.Timestamp("2026-05-21 12:00:00+00:00")
basket["dt"] = pd.to_datetime(basket["ts"], unit="ms", utc=True)
basket_oos = basket[(basket["dt"]>=OOS_START) & (basket["dt"]<=OOS_END)].copy()
print(f"Basket in Andrey OOS window (2025-01 → 2026-05): {len(basket_oos)}")

# Attach predictions
for tgt, df in preds.items():
    basket_oos = basket_oos.merge(df, left_on="ts", right_index=True, how="left")

# Per-event: select direction-matched predictions
def get_probs(row):
    if row["direction"]=="low":
        return row["p_y_low_strong_3"], row["p_y_low_strong_4"], row["p_y_low_strong_5"]
    else:
        return row["p_y_high_strong_3"], row["p_y_high_strong_4"], row["p_y_high_strong_5"]

probs = basket_oos.apply(get_probs, axis=1, result_type="expand")
basket_oos["p_3"] = probs[0]
basket_oos["p_4"] = probs[1]
basket_oos["p_5"] = probs[2]

# Expected magnitude (incremental):
# P(reaches ≥3%) = p_3
# P(reaches ≥4% | ≥3%) ≈ p_4 / p_3
# Expected_pct = 3*p_3 + 1*p_4 + 1*p_5 (since p_X is "max reach X%", expected = layered)
basket_oos["E_pct"] = 3 * basket_oos["p_3"].fillna(0) + 1 * basket_oos["p_4"].fillna(0) + 1 * basket_oos["p_5"].fillna(0)

# Sort & show
print(f"\n=== Distribution of Andrey p_X for basket pivots ===")
for col in ["p_3","p_4","p_5","E_pct"]:
    s = basket_oos[col].dropna()
    print(f"  {col}: mean={s.mean():.2f} median={s.median():.2f} q25={s.quantile(0.25):.2f} q75={s.quantile(0.75):.2f}")

# Top-15 by E_pct
print(f"\n=== TOP-15 basket events по E_pct (ожидаемая амплитуда) ===")
top = basket_oos.dropna(subset=["E_pct"]).nlargest(15, "E_pct")
for _, r in top.iterrows():
    dt_msk = r["dt"].astimezone(MSK).strftime('%Y-%m-%d %H:%M MSK')
    conf = "✓" if r["confirmed"] else "✗"
    print(f"  {dt_msk}  {r['direction']:>4}  p_3={r['p_3']:.2f} p_4={r['p_4']:.2f} p_5={r['p_5']:.2f}  E={r['E_pct']:.2f}%  conf={conf}")

# Bottom-10 (lowest E_pct)
print(f"\n=== BOTTOM-10 basket events по E_pct ===")
bot = basket_oos.dropna(subset=["E_pct"]).nsmallest(10, "E_pct")
for _, r in bot.iterrows():
    dt_msk = r["dt"].astimezone(MSK).strftime('%Y-%m-%d %H:%M MSK')
    conf = "✓" if r["confirmed"] else "✗"
    print(f"  {dt_msk}  {r['direction']:>4}  p_3={r['p_3']:.2f} p_4={r['p_4']:.2f} p_5={r['p_5']:.2f}  E={r['E_pct']:.2f}%  conf={conf}")

# Distribution by E_pct buckets
print(f"\n=== Распределение по E_pct buckets ===")
buckets = [(0,3), (3,5), (5,7), (7,9), (9,11), (11,15)]
for lo, hi in buckets:
    sub = basket_oos[(basket_oos["E_pct"]>=lo) & (basket_oos["E_pct"]<hi)]
    if sub.empty: continue
    conf_pct = sub["confirmed"].mean()*100
    print(f"  E in [{lo:>2},{hi:>2}): n={len(sub):>3}  confirmed_rate={conf_pct:>5.1f}%")

# Save
basket_oos[["ts","dt","direction","confirmed","is_important",
            "p_3","p_4","p_5","E_pct"]].to_csv(
    "/Users/vadim/Desktop/basket_andrey_magnitude.csv", index=False)
print(f"\n→ Saved: ~/Desktop/basket_andrey_magnitude.csv")
EOF
