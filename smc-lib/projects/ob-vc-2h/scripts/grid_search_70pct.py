"""GRID SEARCH for filter delivering:
  - N ≤ 700 (5× cut from 3,378 post-A1 basket)
  - WR ≥ 70%
  - Must validate on BOTH full 6y AND 2023-06-06+ subset

Merge all feature tables and search top combos.
"""
import pathlib, time
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from itertools import product

CUT_2023 = int(datetime(2023, 6, 6, tzinfo=timezone.utc).timestamp() * 1000)
DATA = pathlib.Path(__file__).parent.parent / "data"

t0 = time.time()

# Bulkowski + B1 + dir
bulk = pd.read_parquet(DATA / "bulkowski_features.parquet")
# VWAP at 12h/1d latest (touch/above/below dist_pct)
vwap = pd.read_parquet(DATA / "htf_vwap_features.parquet")
# Age-90d D-VWAP counts
v90 = pd.read_parquet(DATA / "d_vwap_age90d.parquet")
# 4-canon interactions
inter = pd.read_parquet(DATA / "d_vwap_interaction.parquet")

# Merge on (born_ms, direction)
key = ["born_ms", "direction"]
df = bulk[key + ["touched","R","B1_aligned","t_id",
                 "1d_engulf","1d_db","1d_busted","1d_hammer",
                 "4h_engulf","4h_db","4h_busted","4h_hammer"]].copy()
df = df.merge(vwap[key + ["vwap_12h_dist_pct","vwap_1d_dist_pct"]], on=key, how="left")
df = df.merge(v90[key + ["n_same_touched","n_same_above","frac_same_above","n_same_active"]],
              on=key, how="left", suffixes=("","_v90"))
df = df.rename(columns={"n_same_touched":"n_touched_90","n_same_above":"n_above_90",
                        "frac_same_above":"frac_above_90","n_same_active":"n_active_90"})
df = df.merge(inter[key + ["n_A","n_B","n_C","n_D","n_any"]], on=key, how="left")
print(f"Merged: {len(df):,}  with all features: {df.dropna(subset=['vwap_12h_dist_pct','n_A']).shape[0]:,}")

df = df.dropna(subset=["n_A","vwap_12h_dist_pct"]).reset_index(drop=True)

# Helpers
def stats(mask):
    s = df[mask]
    if len(s) < 5: return None
    nt = s.touched.sum(); w=(s.R==1).sum(); l=(s.R==-1).sum()
    if nt < 5: return None
    wr = w/nt*100
    return {"N":len(s), "nt":int(nt), "W":int(w), "L":int(l), "WR":wr, "Σ":w-l}


def stats_sub(mask, sub):
    s = sub[mask[sub.index]]
    if len(s) < 5: return None
    nt = s.touched.sum(); w=(s.R==1).sum(); l=(s.R==-1).sum()
    if nt < 5: return None
    wr = w/nt*100
    return {"N":len(s), "WR":wr, "Σ":w-l}


full_baseline = stats(np.ones(len(df), dtype=bool))
sub = df[df.born_ms >= CUT_2023].reset_index(drop=True)
sub_baseline = {"N":len(sub), "WR":(sub.R==1).sum()/sub.touched.sum()*100,
                "Σ":(sub.R==1).sum()-(sub.R==-1).sum()}
print(f"FULL 6y baseline: N={full_baseline['N']} WR={full_baseline['WR']:.1f}% Σ={full_baseline['Σ']:+}R")
print(f"SUBSET 2023+ baseline: N={sub_baseline['N']} WR={sub_baseline['WR']:.1f}% Σ={sub_baseline['Σ']:+}R")

# ─── Build candidate filter components ──────────────
# Each component is a (name, boolean Series)
COMPS = {
    "B1": df.B1_aligned.astype(bool),
    "1d_engulf": df["1d_engulf"].astype(bool),
    "1d_db": df["1d_db"].astype(bool),
    "vwap12_touch_03": df.vwap_12h_dist_pct.abs() <= 0.003,
    "vwap12_touch_05": df.vwap_12h_dist_pct.abs() <= 0.005,
    "vwap12_above_05": df.vwap_12h_dist_pct > 0.005,
    "vwap1d_touch_03": df.vwap_1d_dist_pct.abs() <= 0.003,
    "vwap1d_above_03": df.vwap_1d_dist_pct > 0.003,
    "n_touched90_ge1": df.n_touched_90 >= 1,
    "n_touched90_ge2": df.n_touched_90 >= 2,
    "n_touched90_ge3": df.n_touched_90 >= 3,
    "frac_above90_ge0.9": df.frac_above_90 >= 0.9,
    "n_A_ge1": df.n_A >= 1,
    "n_A_ge2": df.n_A >= 2,
    "n_B_ge1": df.n_B >= 1,
    "n_C_ge1": df.n_C >= 1,
    "n_D_ge1": df.n_D >= 1,
    "n_D_ge2": df.n_D >= 2,
    "n_D_ge3": df.n_D >= 3,
    "n_any_ge2": df.n_any >= 2,
}

# Required: B1 always in (per prior research — strongest base)
# Search: B1 + 1 or 2 other components

NAMES = [k for k in COMPS.keys() if k != "B1"]
results = []

print("\nSearching B1 + 1 component (singletons)...")
for n1 in NAMES:
    mask = COMPS["B1"] & COMPS[n1]
    st = stats(mask)
    if st is None: continue
    if st["N"] > 1500: continue  # too broad
    if st["WR"] < 65: continue
    st["filter"] = f"B1 + {n1}"
    st["mask_idx"] = mask
    results.append(st)

print(f"Searching B1 + 2 components (pairs) [will skip subset later]...")
for i in range(len(NAMES)):
    for j in range(i+1, len(NAMES)):
        mask = COMPS["B1"] & COMPS[NAMES[i]] & COMPS[NAMES[j]]
        st = stats(mask)
        if st is None or st["N"] < 30 or st["N"] > 1000: continue
        if st["WR"] < 67: continue
        st["filter"] = f"B1 + {NAMES[i]} + {NAMES[j]}"
        st["mask_idx"] = mask
        results.append(st)

print(f"Total candidates: {len(results)}")

# Sort by WR
results.sort(key=lambda x: (-x["WR"], -x["N"]))

# Filter that meets BOTH 6y and subset constraints
print(f"\n{'='*120}")
print(f"TOP CANDIDATES — must validate on BOTH FULL 6y AND SUBSET 2023+")
print(f"{'='*120}")
print(f"{'Filter':<50} {'N_6y':>5} {'WR_6y':>7} {'Σ_6y':>6}  {'N_sub':>5} {'WR_sub':>8} {'Σ_sub':>7}  Robust?")
print("-"*120)
robust_70 = []
robust_65 = []
for r in results[:60]:
    mask = r["mask_idx"]
    sub_mask = mask & (df.born_ms >= CUT_2023)
    sub_s = df[sub_mask]
    nt = sub_s.touched.sum()
    if nt < 5:
        # too few in subset, skip silently
        continue
    w = (sub_s.R==1).sum(); l = (sub_s.R==-1).sum()
    sub_wr = w/nt*100
    robust = r["WR"] >= 70 and sub_wr >= 65  # 6y ≥70%, subset relaxed to 65%
    very_robust = r["WR"] >= 70 and sub_wr >= 70  # both ≥70%
    flag = "✓✓" if very_robust else ("✓" if robust else "")
    print(f"{r['filter']:<50} {r['N']:>5} {r['WR']:>6.1f}% {r['Σ']:>+5}R  {len(sub_s):>5} {sub_wr:>7.1f}% {w-l:>+6}R  {flag}")
    if very_robust:
        robust_70.append((r["filter"], r["N"], r["WR"], len(sub_s), sub_wr))
    elif robust:
        robust_65.append((r["filter"], r["N"], r["WR"], len(sub_s), sub_wr))

print(f"\n{'='*120}")
print(f"VERY ROBUST (WR≥70% in BOTH windows): {len(robust_70)} filters")
for f, n6, wr6, ns, wrs in robust_70:
    print(f"  {f:<55} 6y: N={n6} WR={wr6:.1f}% | sub: N={ns} WR={wrs:.1f}%")

print(f"\nROBUST (WR≥70% full, ≥65% sub): {len(robust_65)} filters")
for f, n6, wr6, ns, wrs in robust_65[:15]:
    print(f"  {f:<55} 6y: N={n6} WR={wr6:.1f}% | sub: N={ns} WR={wrs:.1f}%")

print(f"\nElapsed: {time.time()-t0:.1f}s")
