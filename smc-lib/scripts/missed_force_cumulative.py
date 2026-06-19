"""Анализ суммарной force i, i+i-1, i+i-1+i-2 для catch missed.

Hypothesis: force на одной свече может быть слабой, но cumulative (3 свечи) указывает
на confluence / накопление силы → разворот.

Используем precomputed force_all_bars_per_tf.parquet (4688 bars, all TFs).
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd

FORCE_PATH = Path.home()/"Desktop/force_all_bars_per_tf.parquet"
BASE_PATH = Path.home()/"Desktop/baseline_1267.parquet"

TF_LIST = ["1h","2h","4h","6h","8h","12h","1d","2d","3d"]

MISSED = {
    "#14": (int(datetime(2026,3,4,12,0,tzinfo=timezone.utc).timestamp()*1000), "high"),
    "#15": (int(datetime(2026,3,8,12,0,tzinfo=timezone.utc).timestamp()*1000), "low"),
    "#48": (int(datetime(2026,5,6,0,0,tzinfo=timezone.utc).timestamp()*1000), "high"),
    "NEW": (int(datetime(2026,5,10,12,0,tzinfo=timezone.utc).timestamp()*1000), "high"),
}

import sys
sys.path.insert(0, str(Path.home()/"smc-lib"))
sys.path.insert(0, str(Path.home()/"smc-lib/prediction-algo"))
from force_model_v3.targets_22 import TARGETS_22_MSK
targets22 = set()
for t_msk, fh_fl in TARGETS_22_MSK:
    ts_ms = int(pd.Timestamp(t_msk+"+03:00").tz_convert("UTC").timestamp()*1000)
    targets22.add((ts_ms, "high" if fh_fl=="FH" else "low"))

print("Loading...")
df_f = pd.read_parquet(FORCE_PATH)
df_base = pd.read_parquet(BASE_PATH)

# Aggregate force across all TFs
df_f["buyer_total"] = sum(df_f[f"buyer_{tf}"] for tf in TF_LIST)
df_f["seller_total"] = sum(df_f[f"seller_{tf}"] for tf in TF_LIST)
df_f["net_total"] = df_f["buyer_total"] - df_f["seller_total"]

# Rolling cumulative sums (window includes current bar)
df_f["net_w1"] = df_f["net_total"]
df_f["buyer_w1"] = df_f["buyer_total"]
df_f["seller_w1"] = df_f["seller_total"]
df_f["net_w2"]    = df_f["net_total"].rolling(2).sum()
df_f["buyer_w2"]  = df_f["buyer_total"].rolling(2).sum()
df_f["seller_w2"] = df_f["seller_total"].rolling(2).sum()
df_f["net_w3"]    = df_f["net_total"].rolling(3).sum()
df_f["buyer_w3"]  = df_f["buyer_total"].rolling(3).sum()
df_f["seller_w3"] = df_f["seller_total"].rolling(3).sum()

# Index force by open_ts_ms
df_f_idx = df_f.set_index("open_ts_ms")

# Map to baseline
def get_force(ts):
    return df_f_idx.loc[ts] if ts in df_f_idx.index else None

# Show missed
print(f"\n=== Force per missed (i, i+i-1, i+i-1+i-2) ===")
for tag, (ts, dir_) in MISSED.items():
    if ts not in df_f_idx.index:
        print(f"{tag}: not in force_all_bars"); continue
    r = df_f_idx.loc[ts]
    print(f"\n{tag} {dir_}:")
    print(f"  i=close   net={r['net_w1']:+8.1f}  buyer={r['buyer_w1']:7.1f}  seller={r['seller_w1']:7.1f}")
    print(f"  i+i-1     net={r['net_w2']:+8.1f}  buyer={r['buyer_w2']:7.1f}  seller={r['seller_w2']:7.1f}")
    print(f"  i+i-1+i-2 net={r['net_w3']:+8.1f}  buyer={r['buyer_w3']:7.1f}  seller={r['seller_w3']:7.1f}")

# Now compute filter WR on baseline 1275
df_base["t22"] = df_base.apply(lambda r:(int(r["ts"]), r["direction"]) in targets22, axis=1)
df_base["net_w1"] = df_base["ts"].apply(lambda t: df_f_idx.loc[t, "net_w1"] if t in df_f_idx.index else None)
df_base["net_w2"] = df_base["ts"].apply(lambda t: df_f_idx.loc[t, "net_w2"] if t in df_f_idx.index else None)
df_base["net_w3"] = df_base["ts"].apply(lambda t: df_f_idx.loc[t, "net_w3"] if t in df_f_idx.index else None)
df_base["buyer_w3"] = df_base["ts"].apply(lambda t: df_f_idx.loc[t, "buyer_w3"] if t in df_f_idx.index else None)
df_base["seller_w3"] = df_base["ts"].apply(lambda t: df_f_idx.loc[t, "seller_w3"] if t in df_f_idx.index else None)
df_base = df_base.dropna(subset=["net_w1"])

missed_idx = {}
for tag, (ts, d) in MISSED.items():
    m = df_base[(df_base["ts"]==ts) & (df_base["direction"]==d)]
    if not m.empty: missed_idx[tag] = m.index[0]

# === Grid: net_w * filter ===
def grid(col, side_col, expected_sign):
    """col: net_w1/w2/w3, side_col: 'high'/'low', expected_sign: +1 (buyer dom for FL) or -1 (seller dom for FH)"""
    print(f"\nGrid {col} for {side_col} side (expected sign {expected_sign:+d}):")
    print(f"{'thr':>6} {'keep':>5} {'conf':>5} {'P_W%':>6} {'imp':>4} {'t22':>4} {'missed':<15}")
    for thr in [500, 1000, 1500, 2000, 3000, 5000, 7500, 10000]:
        if expected_sign>0:
            mask = (df_base["direction"]==side_col) & (df_base[col]>=thr)
        else:
            mask = (df_base["direction"]==side_col) & (df_base[col]<=-thr)
        sub = df_base[mask]
        keep=len(sub); conf=int(sub["confirmed"].sum())
        imp=sub[sub["is_important"] & sub["confirmed"]].shape[0]
        t22=sub[sub["t22"] & sub["confirmed"]].shape[0]
        caught=[t for t,mi in missed_idx.items() if mi in sub.index]
        pw=conf/keep*100 if keep else 0
        if keep<10: continue
        flag = "★" if pw>=70 else (" " if pw>=65 else " ")
        print(f"{flag} {thr:>5} {keep:>5} {conf:>5} {pw:>5.1f}% {imp:>4} {t22:>4} {'+'.join(caught):<15}")

# FH = high pivot — expect strong SELLERS above (net negative when looking at zones)
# FL = low pivot — expect strong BUYERS below (net positive)
print(f"\n=== FH side ===")
grid("net_w1", "high", -1)
grid("net_w2", "high", -1)
grid("net_w3", "high", -1)

print(f"\n=== FL side ===")
grid("net_w1", "low", +1)
grid("net_w2", "low", +1)
grid("net_w3", "low", +1)

# Reverse interpretation: maybe net direction is OPPOSITE of expected (force IN direction of moving price)
print(f"\n=== Reverse: FH with positive net (BUYERS dominant = exhaustion) ===")
grid("net_w1", "high", +1)
grid("net_w2", "high", +1)
grid("net_w3", "high", +1)
print(f"\n=== Reverse: FL with negative net (SELLERS dominant = exhaustion) ===")
grid("net_w1", "low", -1)
grid("net_w2", "low", -1)
grid("net_w3", "low", -1)
