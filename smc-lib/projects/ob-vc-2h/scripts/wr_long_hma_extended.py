"""EXTENDED HMA multi-TF × multi-length analysis для LONG 2h ob_vc.

TFs (10): 15m, 1h, 2h, 4h, 6h, 12h, 1D, 2D, 3D, W
HMA lengths (14): 9, 14, 21, 34, 50, 55, 78, 89, 100, 144, 200, 233, 365, 500

Skip combos where length > bar count (W × 500, etc.).

Features per setup at born_ms:
  - HMA values for all valid (TF, L) — up to 140
  - Above/below per HMA
  - Per-TF fan score (# of ordered pairs in monotonic descent)
  - Cross-TF fan_total
  - Multi-TF stack alignment (above ALL HMAs of length L on all TFs)
  - Cluster (HMAs converged within X%)
  - Slope direction per HMA (rising/falling at born_ms)

Then bucket-WR analysis on:
  - Per-TF fan = 13 (perfect bull, 14 lengths → 13 pairs)
  - Total fan score across TFs
  - Multi-TF perfect bull
  - Slope confluence
  - Distance extremes
"""
import sys, pathlib, csv, time
import numpy as np
import pandas as pd
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import agg, aggregate_all_tfs, to_candles, MONDAY_USER_ANCHOR_MS

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from indicators.trend_line_asvk import hma

CSV_1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
CUT = int(datetime(2023, 6, 6, tzinfo=timezone.utc).timestamp() * 1000)
HORIZON_MS = 14*24*3600*1000

TF_SPECS = [
    ("15m", 15*60*1000, 0),
    ("1h",  60*60*1000, 0),
    ("2h",  2*60*60*1000, 0),
    ("4h",  4*60*60*1000, 0),
    ("6h",  6*60*60*1000, 0),
    ("12h", 12*60*60*1000, 0),
    ("1d",  24*60*60*1000, 0),
    ("2d",  2*24*60*60*1000, 0),
    ("3d",  3*24*60*60*1000, 0),
    ("w",   7*24*60*60*1000, MONDAY_USER_ANCHOR_MS),
]
HMA_LENS = [9, 14, 21, 34, 50, 55, 78, 89, 100, 144, 200, 233, 365, 500]

t0 = time.time()

# Load 1m
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
print(f"Loaded 1m: {len(rows):,} bars")

# Build TF candles and HMAs
print("\nAggregating TFs and computing HMAs...")
rows_ohlc = [(r[0], r[1], r[2], r[3], r[4]) for r in rows]
HMA_DATA = {}  # (tf, L) -> (ts_arr, hma_arr)
TF_BARS = {}
for tf_name, tf_ms, anchor in TF_SPECS:
    bars = agg(rows_ohlc, tf_ms, anchor=anchor)
    cans = to_candles(bars)
    TF_BARS[tf_name] = cans
    if len(cans) < 10: continue
    closes = [c.close for c in cans]
    ts_arr = np.array([c.open_time for c in cans], dtype=np.int64)
    for L in HMA_LENS:
        if L >= len(closes): continue  # not enough bars
        h_vals = hma(closes, L)
        h_arr = np.array([float(x) if x is not None else np.nan for x in h_vals])
        HMA_DATA[(tf_name, L)] = (ts_arr, h_arr)
    print(f"  {tf_name}: {len(cans)} bars, {sum(1 for L in HMA_LENS if (tf_name,L) in HMA_DATA)} HMAs")

print(f"\nTotal HMA series: {len(HMA_DATA)}")


def hma_at(tf, L, target_ts):
    if (tf, L) not in HMA_DATA: return None, None
    ts_arr, h_arr = HMA_DATA[(tf, L)]
    i = int(np.searchsorted(ts_arr, target_ts, side="right")) - 1
    if i < 0: return None, None
    v = h_arr[i]
    if np.isnan(v): return None, None
    # Slope: rising if current > value 2 bars ago
    if i >= 2:
        v_prev = h_arr[i-2]
        slope = 1 if (not np.isnan(v_prev) and v > v_prev) else (-1 if (not np.isnan(v_prev) and v < v_prev) else 0)
    else:
        slope = 0
    return float(v), int(slope)


def tbm_long(entry, sl, born):
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
    if tp1r != -1 and (slr == -1 or tp1r <= slr): return {"out": "win"}
    elif slr != -1: return {"out": "loss"}
    return {"out": "timeout"}


# Load LONG 2h ob_vc
df = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")
g2h = df[df.htf == "2h"].copy()
g2h["has_15m"] = g2h.groupby(["direction","ob_cur_open_ms"])["ltf"].transform(lambda x: "15m" in set(x))
mask_lt = ((g2h.has_15m & (g2h.ltf=="15m")) | (~g2h.has_15m & (g2h.ltf=="20m")))
g2h = g2h[mask_lt & (g2h.direction == "long")].copy()

# Cur close per setup
bar2h_idx = {c.open_time: i for i, c in enumerate(TF_BARS["2h"])}

print(f"\nProcessing {len(g2h.groupby(['direction','ob_cur_open_ms']))} LONG setups...")
records = []
for (d, co), sub in g2h.groupby(["direction","ob_cur_open_ms"]):
    co = int(co); born = int(sub.iloc[0].born_ms)
    idx = bar2h_idx.get(co)
    if idx is None: continue
    cur = TF_BARS["2h"][idx]
    cur_close = cur.close

    nc = len(sub)
    cf = sub.sort_values("fvg_zone_hi", ascending=False).iloc[0]
    drop_lo = float(cf.drop_lo)
    fvg_hi = float(cf.fvg_zone_hi); fvg_lo = float(cf.fvg_zone_lo)
    dp = 0.8 if nc >= 2 else 0.2
    entry = fvg_hi - dp * (fvg_hi - fvg_lo); sl = drop_lo

    out = tbm_long(entry, sl, born)
    if out is None: continue
    R = 0; touched = "out" in out
    if touched:
        if out["out"] == "win": R = 1
        elif out["out"] == "loss": R = -1

    rec = {"born_ms": born, "R": R, "touched": touched, "cur_close": cur_close}

    # Per TF: HMA values + fan score
    for tf_name, _, _ in TF_SPECS:
        vals = {}
        slopes = {}
        for L in HMA_LENS:
            v, slope = hma_at(tf_name, L, born)
            vals[L] = v
            slopes[L] = slope
        # Fan score: pairs of (HMA_short > HMA_long) for consecutive lengths
        avail = [L for L in HMA_LENS if vals[L] is not None]
        if len(avail) < 2:
            rec[f"fan_{tf_name}"] = None
            rec[f"above_{tf_name}_200"] = None
            rec[f"slope_{tf_name}_200"] = None
            continue
        # Count consecutive ordered pairs in bull direction
        pairs_total = 0
        pairs_bull = 0
        for i in range(len(avail)-1):
            L_short = avail[i]; L_long = avail[i+1]
            pairs_total += 1
            if vals[L_short] > vals[L_long]:
                pairs_bull += 1
        rec[f"fan_{tf_name}"] = pairs_bull
        rec[f"fan_{tf_name}_total"] = pairs_total
        # Above HMA-200 (or longest available)
        L_long = max(avail)
        rec[f"above_{tf_name}_200"] = cur_close > vals[L_long] if L_long >= 200 else None
        # Slope of longest HMA
        rec[f"slope_{tf_name}_200"] = slopes[L_long] if L_long >= 200 else None
        # Distance from HMA-200 in %
        if L_long >= 200:
            rec[f"dist_{tf_name}_200"] = (cur_close - vals[L_long]) / vals[L_long] * 100
        else:
            rec[f"dist_{tf_name}_200"] = None
        # Stack count: how many HMAs cur_close is above on this TF
        rec[f"stack_above_{tf_name}"] = sum(1 for L in avail if cur_close > vals[L])
        rec[f"stack_total_{tf_name}"] = len(avail)
    records.append(rec)

rdf = pd.DataFrame(records)
print(f"Records: {len(rdf)}  Elapsed: {time.time()-t0:.1f}s")
dec = rdf[rdf.R.isin([1, -1])].copy()
print(f"Decisive: W={(dec.R==1).sum()} L={(dec.R==-1).sum()}")

ref_full = (dec.R==1).sum()/dec.touched.sum()*100 if dec.touched.sum() else 0
sub = dec[dec.born_ms >= CUT].copy()
ref_sub = (sub.R==1).sum()/sub.touched.sum()*100 if sub.touched.sum() else 0


def stat(df_l, mask, lbl, ref):
    s = df_l[mask]
    if len(s) < 10: return None
    nt=s.touched.sum(); w=(s.R==1).sum(); l=(s.R==-1).sum()
    wr = w/nt*100 if nt else 0
    lift = wr - ref
    flag = "⭐" if lift >= 3 else ("✓" if lift >= 1 else ("❌" if lift <= -3 else ""))
    return {"N": len(s), "WR": wr, "Σ": w-l, "lift": lift, "flag": flag, "lbl": lbl}


def print_block(df_l, title, ref):
    print(f"\n{'='*120}\n{title}  (baseline WR={ref:.1f}%)\n{'='*120}")
    results = []
    # Per-TF fan score = max possible
    for tf_name, _, _ in TF_SPECS:
        if f"fan_{tf_name}_total" not in df_l.columns: continue
        avail_total = df_l[f"fan_{tf_name}_total"].dropna()
        if len(avail_total) == 0: continue
        max_pairs = int(avail_total.max())
        for fan in range(max_pairs + 1):
            m = df_l[f"fan_{tf_name}"] == fan
            r = stat(df_l, m, f"{tf_name} fan = {fan}/{max_pairs}", ref)
            if r and abs(r["lift"]) >= 2 and r["N"] >= 30:
                results.append(r)

    # Sum fan total across TFs
    df_l = df_l.copy()
    fan_cols = [f"fan_{tf_name}" for tf_name, _, _ in TF_SPECS if f"fan_{tf_name}" in df_l.columns]
    df_l["fan_total_all"] = df_l[fan_cols].sum(axis=1)
    df_l["fan_max_all"] = df_l[[c.replace("fan_", "fan_") + "_total" for c in fan_cols if c + "_total" in df_l.columns or c.replace("fan_", "fan_") + "_total" in df_l.columns]].sum(axis=1)
    # Simpler: max_all = sum of TF max pairs
    max_total = 0
    for tf_name, _, _ in TF_SPECS:
        col = f"fan_{tf_name}_total"
        if col in df_l.columns:
            max_total += int(df_l[col].max(skipna=True)) if df_l[col].notna().any() else 0
    print(f"\nMax possible fan_total_all: {max_total}")
    # Bucket
    if df_l.fan_total_all.notna().any():
        df_l["fan_total_bucket"] = pd.cut(df_l.fan_total_all,
                                          bins=[0, max_total*0.2, max_total*0.4, max_total*0.6, max_total*0.8, max_total],
                                          labels=["deep_bear","bear_lean","mixed","bull_lean","deep_bull"], include_lowest=True)
        for b in ["deep_bear","bear_lean","mixed","bull_lean","deep_bull"]:
            m = df_l.fan_total_bucket == b
            r = stat(df_l, m, f"fan_total bucket: {b}", ref)
            if r:
                print(f"  {r['lbl']:<55} N={r['N']:>4} WR={r['WR']:>5.1f}% Σ={r['Σ']:>+5}R ({r['lift']:+.1f}pp) {r['flag']}")

    # Multi-TF stack alignment: cur_close above HMA-200 on N TFs
    stack200_cols = [c for c in df_l.columns if c.startswith("above_") and c.endswith("_200")]
    df_l["n_above_200"] = df_l[stack200_cols].fillna(False).astype(bool).sum(axis=1)
    print(f"\n--- Number of TFs price ABOVE HMA-200 ---")
    for k in range(int(df_l.n_above_200.max()) + 1):
        m = df_l.n_above_200 == k
        r = stat(df_l, m, f"n_above_200 = {k}", ref)
        if r and r["N"] >= 30:
            print(f"  {r['lbl']:<55} N={r['N']:>4} WR={r['WR']:>5.1f}% Σ={r['Σ']:>+5}R ({r['lift']:+.1f}pp) {r['flag']}")

    # Top per-TF fan = max (perfect bull on that TF)
    print(f"\n--- Per-TF: fan = max (perfect bull on TF) ---")
    for tf_name, _, _ in TF_SPECS:
        col_fan = f"fan_{tf_name}"
        col_max = f"fan_{tf_name}_total"
        if col_fan not in df_l.columns or col_max not in df_l.columns: continue
        if df_l[col_max].isna().all(): continue
        max_pairs = int(df_l[col_max].max(skipna=True))
        m = df_l[col_fan] == max_pairs
        r = stat(df_l, m, f"{tf_name} PERFECT BULL fan ({max_pairs}/{max_pairs} pairs)", ref)
        if r:
            print(f"  {r['lbl']:<55} N={r['N']:>4} WR={r['WR']:>5.1f}% Σ={r['Σ']:>+5}R ({r['lift']:+.1f}pp) {r['flag']}")

    # ALL TFs PERFECT BULL fan
    print(f"\n--- Multi-TF PERFECT BULL combinations ---")
    perfect_masks = []
    for tf_name, _, _ in TF_SPECS:
        col_fan = f"fan_{tf_name}"
        col_max = f"fan_{tf_name}_total"
        if col_fan not in df_l.columns or col_max not in df_l.columns: continue
        if df_l[col_max].isna().all(): continue
        max_pairs = int(df_l[col_max].max(skipna=True))
        perfect_masks.append((tf_name, (df_l[col_fan] == max_pairs).fillna(False)))
    # Subsets of TFs
    for n_tfs in [3, 5, 7, len(perfect_masks)]:
        if n_tfs > len(perfect_masks): continue
        # Try all combos? Too many. Use top N TFs by ordering: high → low
        # Take first n_tfs as "lowest TFs perfect"
        m = np.ones(len(df_l), dtype=bool)
        names_used = []
        for tf_n, mask in perfect_masks[:n_tfs]:
            m = m & mask
            names_used.append(tf_n)
        r = stat(df_l, m, f"PERFECT bull on first {n_tfs} TFs ({','.join(names_used)})", ref)
        if r:
            print(f"  {r['lbl']:<70} N={r['N']:>4} WR={r['WR']:>5.1f}% Σ={r['Σ']:>+5}R ({r['lift']:+.1f}pp) {r['flag']}")

    # ALL TFs perfect bull
    m = np.ones(len(df_l), dtype=bool)
    for tf_n, mask in perfect_masks:
        m = m & mask
    r = stat(df_l, m, f"ALL TFs ({len(perfect_masks)}) PERFECT BULL", ref)
    if r:
        print(f"  {r['lbl']:<70} N={r['N']:>4} WR={r['WR']:>5.1f}% Σ={r['Σ']:>+5}R ({r['lift']:+.1f}pp) {r['flag']}")

    # Bear: All TFs fan = 0 (perfect bear)
    bear_masks = []
    for tf_name, _, _ in TF_SPECS:
        col_fan = f"fan_{tf_name}"
        if col_fan not in df_l.columns: continue
        bear_masks.append((tf_name, (df_l[col_fan] == 0).fillna(False)))
    m = np.ones(len(df_l), dtype=bool)
    for tf_n, mask in bear_masks:
        m = m & mask
    r = stat(df_l, m, f"ALL TFs PERFECT BEAR (fan=0 everywhere)", ref)
    if r:
        print(f"  {r['lbl']:<70} N={r['N']:>4} WR={r['WR']:>5.1f}% Σ={r['Σ']:>+5}R ({r['lift']:+.1f}pp) {r['flag']}")


print_block(dec, "FULL 6y LONG", ref_full)
print_block(sub, "SUBSET 2023-06-06+ LONG", ref_sub)

# Save
out_path = pathlib.Path(__file__).parent.parent / "data/hma_extended_long.parquet"
rdf.to_parquet(out_path)
print(f"\nSaved: {out_path}\nElapsed: {time.time()-t0:.1f}s")
