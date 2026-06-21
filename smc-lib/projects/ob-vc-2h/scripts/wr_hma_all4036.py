"""HMA extended analysis на ВСЕХ 4036 setups (LONG + SHORT) с per-type breakdown.

Direction-aware:
  LONG  good context: above HMA / fan bull = HMA_short > HMA_long
  SHORT good context: below HMA / fan bear = HMA_short < HMA_long

10 TFs × 14 HMAs = up to 140 series.

Output:
  - WR per direction × n_aligned bucket
  - Per-type (T1a..T16) best HMA filter
  - Top combos surviving direction-aware test
"""
import sys, pathlib, csv, time
import numpy as np
import pandas as pd
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import agg, to_candles, MONDAY_USER_ANCHOR_MS

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from indicators.trend_line_asvk import hma

CSV_1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
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
HMA_DATA = {}
TF_BARS = {}
print("Computing HMAs...")
for tf_name, tf_ms, anchor in TF_SPECS:
    bars = agg(rows_ohlc, tf_ms, anchor=anchor)
    cans = to_candles(bars)
    TF_BARS[tf_name] = cans
    if len(cans) < 10: continue
    closes = [c.close for c in cans]
    ts_arr = np.array([c.open_time for c in cans], dtype=np.int64)
    for L in HMA_LENS:
        if L >= len(closes): continue
        h_vals = hma(closes, L)
        h_arr = np.array([float(x) if x is not None else np.nan for x in h_vals])
        HMA_DATA[(tf_name, L)] = (ts_arr, h_arr)
print(f"HMA series: {len(HMA_DATA)}, elapsed: {time.time()-t0:.1f}s")


def hma_at(tf, L, target_ts):
    if (tf, L) not in HMA_DATA: return None
    ts_arr, h_arr = HMA_DATA[(tf, L)]
    i = int(np.searchsorted(ts_arr, target_ts, side="right")) - 1
    if i < 0: return None
    v = h_arr[i]
    return None if np.isnan(v) else float(v)


def tbm(entry, sl, born, direction):
    if direction == "long":
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


# Load Phase 1.5 + bulkowski (for t_id)
df_p15 = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")
bulk = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/bulkowski_features.parquet")
bulk_keys = bulk[["born_ms","direction","t_id"]].drop_duplicates()
t_id_map = bulk_keys.set_index(["born_ms","direction"]).t_id.to_dict()

g2h = df_p15[df_p15.htf == "2h"].copy()
g2h["has_15m"] = g2h.groupby(["direction","ob_cur_open_ms"])["ltf"].transform(lambda x: "15m" in set(x))
mask_lt = ((g2h.has_15m & (g2h.ltf=="15m")) | (~g2h.has_15m & (g2h.ltf=="20m")))
g2h = g2h[mask_lt].copy()

bar2h_idx = {c.open_time: i for i, c in enumerate(TF_BARS["2h"])}

print(f"\nProcessing {g2h.groupby(['direction','ob_cur_open_ms']).ngroups} setups (LONG+SHORT)...")
records = []
for (d, co), sub in g2h.groupby(["direction","ob_cur_open_ms"]):
    co = int(co); born = int(sub.iloc[0].born_ms)
    idx = bar2h_idx.get(co)
    if idx is None: continue
    cur = TF_BARS["2h"][idx]
    cur_close = cur.close

    nc = len(sub)
    if d == "long":
        cf = sub.sort_values("fvg_zone_hi", ascending=False).iloc[0]
        drop_lo = float(cf.drop_lo)
        fvg_hi = float(cf.fvg_zone_hi); fvg_lo = float(cf.fvg_zone_lo)
        dp = 0.8 if nc >= 2 else 0.2
        entry = fvg_hi - dp * (fvg_hi - fvg_lo); sl = drop_lo
    else:
        cf = sub.sort_values("fvg_zone_lo", ascending=True).iloc[0]
        drop_hi = float(cf.drop_hi)
        fvg_hi = float(cf.fvg_zone_hi); fvg_lo = float(cf.fvg_zone_lo)
        dp = 0.8 if nc >= 2 else 0.2
        entry = fvg_lo + dp * (fvg_hi - fvg_lo); sl = drop_hi

    out = tbm(entry, sl, born, d)
    if out is None: continue
    R = 0; touched = "out" in out
    if touched:
        if out["out"] == "win": R = 1
        elif out["out"] == "loss": R = -1
    t_id = t_id_map.get((born, d), "Unknown")

    rec = {"born_ms": born, "direction": d, "t_id": t_id,
           "touched": touched, "R": R, "cur_close": cur_close}

    # Per TF: per-HMA values + fan, above
    n_above_200_total = 0
    n_below_200_total = 0
    fan_total_bull = 0
    fan_total_bear = 0
    fan_total_pairs = 0
    for tf_name, _, _ in TF_SPECS:
        vals = {}
        for L in HMA_LENS:
            v = hma_at(tf_name, L, born)
            vals[L] = v
        avail = [L for L in HMA_LENS if vals[L] is not None]
        if len(avail) < 2: continue
        for i in range(len(avail)-1):
            ls = avail[i]; ll = avail[i+1]
            fan_total_pairs += 1
            if vals[ls] > vals[ll]: fan_total_bull += 1
            else: fan_total_bear += 1
        # Above HMA-200 (or longest available ≥200)
        long_hmas = [L for L in avail if L >= 200]
        if long_hmas:
            L_long = max(long_hmas)
            if vals[L_long] is not None:
                if cur_close > vals[L_long]: n_above_200_total += 1
                else: n_below_200_total += 1

    rec["n_above_200"] = n_above_200_total
    rec["n_below_200"] = n_below_200_total
    rec["fan_bull"] = fan_total_bull
    rec["fan_bear"] = fan_total_bear
    rec["fan_pairs"] = fan_total_pairs
    rec["fan_bull_pct"] = fan_total_bull / fan_total_pairs if fan_total_pairs else None
    # Direction-aware "aligned" feature
    if d == "long":
        rec["aligned_count"] = n_above_200_total  # higher = better
        rec["aligned_fan"] = fan_total_bull
    else:
        rec["aligned_count"] = n_below_200_total
        rec["aligned_fan"] = fan_total_bear
    records.append(rec)

rdf = pd.DataFrame(records)
print(f"Records: {len(rdf)}  Elapsed: {time.time()-t0:.1f}s")

dec = rdf[rdf.R.isin([1, -1])].copy()
print(f"Decisive: W={(dec.R==1).sum()} L={(dec.R==-1).sum()}")
print(f"  LONG: W={((dec.direction=='long') & (dec.R==1)).sum()}  L={((dec.direction=='long') & (dec.R==-1)).sum()}")
print(f"  SHORT: W={((dec.direction=='short') & (dec.R==1)).sum()}  L={((dec.direction=='short') & (dec.R==-1)).sum()}")

ref_all = (dec.R==1).sum()/dec.touched.sum()*100 if dec.touched.sum() else 0
ref_long = ((dec.direction=='long') & (dec.R==1)).sum() / dec[dec.direction=='long'].touched.sum() * 100
ref_short = ((dec.direction=='short') & (dec.R==1)).sum() / dec[dec.direction=='short'].touched.sum() * 100
print(f"\nBaselines: ALL WR={ref_all:.1f}%  LONG WR={ref_long:.1f}%  SHORT WR={ref_short:.1f}%")


def stat(df_l, mask, lbl, ref):
    s = df_l[mask]
    if len(s) < 10: return None
    nt=s.touched.sum(); w=(s.R==1).sum(); l=(s.R==-1).sum()
    wr = w/nt*100 if nt else 0
    lift = wr - ref
    flag = "⭐" if lift >= 5 else ("✓" if lift >= 2 else ("❌" if lift <= -5 else ""))
    return (len(s), wr, w-l, lift, flag, lbl)


def show(r):
    if r is None: return
    print(f"  {r[5]:<55} N={r[0]:>4} WR={r[1]:>5.1f}% Σ={r[2]:>+5}R ({r[3]:+.1f}pp) {r[4]}")


# ─── Per-direction n_aligned analysis ───
print(f"\n{'='*120}")
print(f"DIRECTION-AWARE n_aligned (LONG=n_above_200, SHORT=n_below_200) on FULL 6y, all 4036")
print(f"{'='*120}")
for dirn, ref in [("long", ref_long), ("short", ref_short)]:
    sub_d = dec[dec.direction == dirn]
    print(f"\n--- {dirn.upper()} (baseline {ref:.1f}%) ---")
    for k in range(11):
        r = stat(sub_d, sub_d.aligned_count == k, f"aligned_count = {k}/10 TFs", ref)
        show(r)

# Fan_bull_pct bucket
print(f"\n--- LONG fan_bull_pct buckets ---")
long_dec = dec[dec.direction == "long"].copy()
long_dec["fbp_bucket"] = pd.qcut(long_dec.fan_bull_pct, q=10, duplicates='drop')
for b, g in long_dec.groupby("fbp_bucket", observed=True):
    if len(g) < 30: continue
    nt=g.touched.sum(); w=(g.R==1).sum(); l=(g.R==-1).sum()
    wr = w/nt*100 if nt else 0
    lift = wr - ref_long
    flag = "⭐" if lift >= 3 else ("❌" if lift <= -3 else ("✓" if lift >= 1 else ""))
    print(f"  fbp={str(b):<30} N={len(g):>4} WR={wr:>5.1f}% ({lift:+.1f}pp) {flag}")

print(f"\n--- SHORT fan_bear_pct buckets ---")
short_dec = dec[dec.direction == "short"].copy()
short_dec["fbp"] = 1 - short_dec.fan_bull_pct  # bear pct
short_dec["fbp_bucket"] = pd.qcut(short_dec.fbp, q=10, duplicates='drop')
for b, g in short_dec.groupby("fbp_bucket", observed=True):
    if len(g) < 30: continue
    nt=g.touched.sum(); w=(g.R==1).sum(); l=(g.R==-1).sum()
    wr = w/nt*100 if nt else 0
    lift = wr - ref_short
    flag = "⭐" if lift >= 3 else ("❌" if lift <= -3 else ("✓" if lift >= 1 else ""))
    print(f"  bear_pct={str(b):<26} N={len(g):>4} WR={wr:>5.1f}% ({lift:+.1f}pp) {flag}")

# ─── PER-TYPE breakdown ───
print(f"\n{'='*120}")
print(f"PER-TYPE WR with best HMA filter (n_aligned ≥ K with biggest lift)")
print(f"{'='*120}")
print(f"{'type':<5} {'dir':<6} {'N_base':>6} {'WR_base':>8}  best_filter                          {'N_f':>5} {'WR_f':>6} {'Σ_f':>5} {'lift':>6}")
print("-"*120)
results_per_type = []
for t_id in sorted(dec.t_id.unique()):
    if t_id == "Unknown": continue
    sub = dec[dec.t_id == t_id]
    if len(sub) < 20: continue
    direction = sub.direction.iloc[0]
    base_wr = (sub.R==1).sum() / sub.touched.sum() * 100 if sub.touched.sum() else 0

    best_filter = None
    for k in range(11):
        m = sub.aligned_count == k
        s = sub[m]
        if len(s) < 10: continue
        nt = s.touched.sum(); w = (s.R==1).sum(); l = (s.R==-1).sum()
        wr = w/nt*100 if nt else 0
        lift = wr - base_wr
        if best_filter is None or lift > best_filter["lift"]:
            best_filter = {"k": k, "N": len(s), "WR": wr, "Σ": w-l, "lift": lift}
    # Also try cumulative ≥ k
    for k in range(11):
        m = sub.aligned_count >= k
        s = sub[m]
        if len(s) < 10: continue
        nt = s.touched.sum(); w = (s.R==1).sum(); l = (s.R==-1).sum()
        wr = w/nt*100 if nt else 0
        lift = wr - base_wr
        if best_filter is None or (lift > best_filter["lift"] and len(s) >= 15):
            best_filter = {"k_ge": k, "N": len(s), "WR": wr, "Σ": w-l, "lift": lift}

    if best_filter:
        k_label = f"=={best_filter.get('k')}" if 'k' in best_filter else f">={best_filter.get('k_ge')}"
        flag = "⭐" if best_filter["lift"] >= 5 else ("✓" if best_filter["lift"] >= 2 else "")
        print(f"{t_id:<5} {direction:<6} {len(sub):>6} {base_wr:>7.1f}%  aligned_count {k_label:<8}                    {best_filter['N']:>5} {best_filter['WR']:>5.1f}% {best_filter['Σ']:>+4}R {best_filter['lift']:>+5.1f}pp {flag}")
        results_per_type.append({
            "t_id": t_id, "direction": direction,
            "N_base": len(sub), "WR_base": base_wr,
            **best_filter, "k_label": k_label,
        })

# Save
dec.to_parquet(pathlib.Path(__file__).parent.parent / "data/hma_all4036.parquet")
print(f"\nElapsed: {time.time()-t0:.1f}s")
