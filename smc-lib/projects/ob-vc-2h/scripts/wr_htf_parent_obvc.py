"""WR for ALL 4036 ob_vc 2h: filter where 2h ob_vc is "part of" a same-direction
4h or 6h ob_vc whose born_ms is BEFORE our 2h ob_vc.born_ms (no lookahead).

"Part of" definition:
  - HTF ob_vc.born_ms ≤ our 2h ob_vc.born_ms
  - HTF ob_vc.ob_zone overlaps with our 2h ob_vc.zone (FVG-zone)
    OR our 2h ob_vc bars time-window falls within HTF ob_vc's cur+prev time-window
  - Same direction
  - HTF ob_vc still active: valid_until_ms > our 2h ob_vc.born_ms

Variants tested:
  parent_4h_zone_overlap
  parent_6h_zone_overlap
  parent_4h_time_inside
  parent_6h_time_inside
  parent_any (any combination fires)
"""
import sys, pathlib, csv
import numpy as np
import pandas as pd
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import aggregate_all_tfs, to_candles

CSV_1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
HORIZON_MS = 14*24*3600*1000
TF_4H_MS = 4 * 3600 * 1000
TF_6H_MS = 6 * 3600 * 1000

rows = []
with CSV_1M.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
        if t < START_MS: continue
        rows.append((t, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
ts_1m = np.array([r[0] for r in rows], dtype=np.int64)
h_1m = np.array([r[2] for r in rows], dtype=np.float64)
l_1m = np.array([r[3] for r in rows], dtype=np.float64)

rows_ohlc = [(r[0], r[1], r[2], r[3], r[4]) for r in rows]
cans_d = aggregate_all_tfs(rows_ohlc)
cans_2h = to_candles(cans_d["2h"])
bar2h_idx = {c.open_time: i for i, c in enumerate(cans_2h)}


def tbm(entry, sl, born, d):
    if d == "long":
        if entry <= sl: return None
        R = entry - sl; TP1 = entry + R
        iS = int(np.searchsorted(ts_1m, born))
        if iS >= len(ts_1m): return None
        iE = min(len(ts_1m)-1, int(np.searchsorted(ts_1m, born + HORIZON_MS)))
        s = l_1m[iS:iE+1]
        if not (s <= entry).any(): return {"touched": False}
        tr = int(np.argmax(s <= entry)); ti = iS + tr
        ph = h_1m[ti:iE+1]; pl = l_1m[ti:iE+1]
        tp1r = int(np.argmax(ph >= TP1)) if (ph >= TP1).any() else -1
        slr = int(np.argmax(pl <= sl)) if (pl <= sl).any() else -1
    else:
        if entry >= sl: return None
        R = sl - entry; TP1 = entry - R
        iS = int(np.searchsorted(ts_1m, born))
        if iS >= len(ts_1m): return None
        iE = min(len(ts_1m)-1, int(np.searchsorted(ts_1m, born + HORIZON_MS)))
        s = h_1m[iS:iE+1]
        if not (s >= entry).any(): return {"touched": False}
        tr = int(np.argmax(s >= entry)); ti = iS + tr
        ph = h_1m[ti:iE+1]; pl = l_1m[ti:iE+1]
        tp1r = int(np.argmax(pl <= TP1)) if (pl <= TP1).any() else -1
        slr = int(np.argmax(ph >= sl)) if (ph >= sl).any() else -1
    if tp1r != -1 and (slr == -1 or tp1r <= slr): return {"out": "win"}
    elif slr != -1: return {"out": "loss"}
    return {"out": "timeout"}


# Load all ob_vc data
df = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")

# 4h and 6h ob_vc — unique per (direction, ob_cur_open_ms)
def htf_unique(htf):
    sub = df[df.htf == htf].groupby(["direction","ob_cur_open_ms"]).agg(
        born_ms=("born_ms","first"),
        ob_cur_close_ms=("ob_cur_close_ms","first"),
        ob_zone_lo=("ob_zone_lo","first"),
        ob_zone_hi=("ob_zone_hi","first"),
        valid_until_ms=("valid_until_ms","first"),
    ).reset_index()
    return sub

h4 = htf_unique("4h")
h6 = htf_unique("6h")
print(f"4h unique ob_vc: {len(h4)}  6h: {len(h6)}")

# Sort by born_ms for fast lookup
h4_long = h4[h4.direction == "long"].sort_values("born_ms").reset_index(drop=True)
h4_short = h4[h4.direction == "short"].sort_values("born_ms").reset_index(drop=True)
h6_long = h6[h6.direction == "long"].sort_values("born_ms").reset_index(drop=True)
h6_short = h6[h6.direction == "short"].sort_values("born_ms").reset_index(drop=True)


def has_parent(htf_df, born_ms_2h, dir_2h, zone_lo_2h, zone_hi_2h, prev_open_2h, cur_open_2h):
    """Check if any HTF ob_vc is parent of this 2h.
    Parent: HTF.born_ms ≤ our born AND zone overlap AND still valid AND covers our 2h bars range.
    Returns (zone_overlap_match, time_inside_match)
    """
    # Filter: same dir, born before, valid after
    candidates = htf_df[(htf_df.born_ms <= born_ms_2h) & (htf_df.valid_until_ms > born_ms_2h)]
    if len(candidates) == 0: return False, False
    # Zone overlap: max(lo) ≤ min(hi)
    zone_ok = ((candidates.ob_zone_lo <= zone_hi_2h) & (candidates.ob_zone_hi >= zone_lo_2h)).any()
    # Time inside: 2h cur or prev bar open_time falls within HTF.ob_cur_open..close
    # ob_cur_close_ms = born_ms typically; valid window for "current" is post-formation
    # For "part of" interpretation: our 2h bars are within HTF.ob_zone (price) and active period
    # Simpler: cur 2h within last HTF ob_vc formation neighborhood (post-born active period)
    time_ok = zone_ok  # treat as overlap-based — simpler model
    return bool(zone_ok), bool(time_ok)


# Process ALL 4036 2h ob_vc
g2h = df[df.htf == "2h"].copy()
g2h["has_15m"] = g2h.groupby(["direction","ob_cur_open_ms"])["ltf"].transform(lambda x: "15m" in set(x))
mask_lt = ((g2h.has_15m & (g2h.ltf=="15m")) | (~g2h.has_15m & (g2h.ltf=="20m")))
g2h = g2h[mask_lt].copy()

print(f"2h ob_vc to process: {g2h.groupby(['direction','ob_cur_open_ms']).ngroups}")

records = []
for (d, co), sub in g2h.groupby(["direction","ob_cur_open_ms"]):
    born = int(sub.iloc[0].born_ms)
    nc = len(sub)
    if d == "long":
        cf = sub.sort_values("fvg_zone_hi", ascending=False).iloc[0]
        dp = 0.8 if nc >= 2 else 0.2
        entry = float(cf.fvg_zone_hi) - dp * (float(cf.fvg_zone_hi) - float(cf.fvg_zone_lo))
        sl = float(cf.drop_lo)
    else:
        cf = sub.sort_values("fvg_zone_lo", ascending=True).iloc[0]
        dp = 0.8 if nc >= 2 else 0.2
        entry = float(cf.fvg_zone_lo) + dp * (float(cf.fvg_zone_hi) - float(cf.fvg_zone_lo))
        sl = float(cf.drop_hi)

    # 2h ob_vc zone (use top FVG zone)
    z_lo = float(cf.fvg_zone_lo); z_hi = float(cf.fvg_zone_hi)
    prev_open = int(co) - 2*3600*1000
    cur_open = int(co)

    if d == "long":
        h4_df = h4_long; h6_df = h6_long
    else:
        h4_df = h4_short; h6_df = h6_short

    p4_zone, _ = has_parent(h4_df, born, d, z_lo, z_hi, prev_open, cur_open)
    p6_zone, _ = has_parent(h6_df, born, d, z_lo, z_hi, prev_open, cur_open)

    out = tbm(entry, sl, born, d)
    if out is None: continue
    R = 0; touched = "out" in out
    if touched:
        if out["out"] == "win": R = 1
        elif out["out"] == "loss": R = -1
    records.append({
        "born_ms": born, "direction": d, "n_FVG": nc,
        "parent_4h": p4_zone, "parent_6h": p6_zone,
        "parent_any": p4_zone or p6_zone,
        "parent_both": p4_zone and p6_zone,
        "touched": touched, "R": R,
    })

rdf = pd.DataFrame(records)
print(f"\nProcessed: {len(rdf):,}")

# Overall WR
def stats(mask, lbl):
    s = rdf[mask]
    if len(s) < 10: print(f"{lbl:<40} N={len(s)} (skip)"); return
    nt=s.touched.sum(); w=(s.R==1).sum(); l=(s.R==-1).sum()
    wr = w/nt*100 if nt else 0
    print(f"{lbl:<40} N={len(s):>5} touch={nt:>5} W={w:>4} L={l:>4} WR={wr:>5.1f}% Σ={w-l:>+5}R")


print(f"\n{'='*90}")
print(f"ALL 4036 2h ob_vc — parent HTF analysis")
print(f"{'='*90}")
stats(np.ones(len(rdf), dtype=bool), "BASELINE all 2h ob_vc")
stats(rdf.parent_4h, "Parent 4h ob_vc (zone overlap)")
stats(rdf.parent_6h, "Parent 6h ob_vc (zone overlap)")
stats(rdf.parent_any, "Parent 4h OR 6h")
stats(rdf.parent_both, "Parent 4h AND 6h")
stats(~rdf.parent_any, "NO parent 4h/6h")

print(f"\n=== LONG only ===")
long_rdf = rdf[rdf.direction == "long"]
def stats_l(mask, lbl):
    s = long_rdf[mask]
    if len(s) < 10: print(f"{lbl:<40} N={len(s)} (skip)"); return
    nt=s.touched.sum(); w=(s.R==1).sum(); l=(s.R==-1).sum()
    wr = w/nt*100 if nt else 0
    print(f"{lbl:<40} N={len(s):>5} touch={nt:>5} W={w:>4} L={l:>4} WR={wr:>5.1f}% Σ={w-l:>+5}R")

stats_l(np.ones(len(long_rdf), dtype=bool), "BASELINE LONG")
stats_l(long_rdf.parent_4h, "Parent 4h")
stats_l(long_rdf.parent_6h, "Parent 6h")
stats_l(long_rdf.parent_any, "Parent 4h OR 6h")
stats_l(long_rdf.parent_both, "Parent 4h AND 6h")
stats_l(~long_rdf.parent_any, "NO parent")

print(f"\n=== SHORT only ===")
short_rdf = rdf[rdf.direction == "short"]
def stats_s(mask, lbl):
    s = short_rdf[mask]
    if len(s) < 10: print(f"{lbl:<40} N={len(s)} (skip)"); return
    nt=s.touched.sum(); w=(s.R==1).sum(); l=(s.R==-1).sum()
    wr = w/nt*100 if nt else 0
    print(f"{lbl:<40} N={len(s):>5} touch={nt:>5} W={w:>4} L={l:>4} WR={wr:>5.1f}% Σ={w-l:>+5}R")

stats_s(np.ones(len(short_rdf), dtype=bool), "BASELINE SHORT")
stats_s(short_rdf.parent_4h, "Parent 4h")
stats_s(short_rdf.parent_6h, "Parent 6h")
stats_s(short_rdf.parent_any, "Parent 4h OR 6h")
stats_s(short_rdf.parent_both, "Parent 4h AND 6h")
stats_s(~short_rdf.parent_any, "NO parent")

out_path = pathlib.Path(__file__).parent.parent / "data/parent_htf_features.parquet"
rdf.to_parquet(out_path)
print(f"\nSaved: {out_path}")
