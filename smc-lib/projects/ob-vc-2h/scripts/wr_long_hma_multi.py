"""HMA multi-TF × multi-length analysis для LONG 2h ob_vc.

HMA lengths: 50, 78, 100, 144, 200 (canon: 78 + 200)
TFs: 2h, 4h, 12h, 1D

Per setup, compute:
  - HMA value at born_ms for each (TF, length)
  - Price (cur.close) position vs each HMA: above / below
  - Pairwise crossings: HMA_fast > HMA_slow (golden) or <  (death)
  - Cross-TF alignment: e.g., all 4 TFs price > HMA-200 = bullish stack

Find patterns predicting WIN vs LOSS.
"""
import sys, pathlib, csv, time
import numpy as np
import pandas as pd
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import aggregate_all_tfs, to_candles

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from indicators.trend_line_asvk import hma

CSV_1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
CUT = int(datetime(2023, 6, 6, tzinfo=timezone.utc).timestamp() * 1000)
HORIZON_MS = 14*24*3600*1000
HMA_LENGTHS = [50, 78, 100, 144, 200]
TFS = ["2h", "4h", "12h", "1d"]

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
cans_d = aggregate_all_tfs(rows_ohlc)

# Pre-compute HMA arrays per (TF, length)
print("Computing HMAs...")
HMA_MAP = {}  # (tf, length) -> (ts_arr, hma_arr)
for tf in TFS:
    cans = to_candles(cans_d[tf])
    closes = [c.close for c in cans]
    ts_arr = np.array([c.open_time for c in cans], dtype=np.int64)
    for L in HMA_LENGTHS:
        hma_vals = hma(closes, L)
        hma_arr = np.array([float(x) if x is not None else np.nan for x in hma_vals])
        HMA_MAP[(tf, L)] = (ts_arr, hma_arr)
    print(f"  {tf}: {len(cans)} bars")

cans_2h = to_candles(cans_d["2h"])
bar2h_idx = {c.open_time: i for i, c in enumerate(cans_2h)}


def hma_at(tf: str, length: int, target_ts: int):
    ts_arr, hma_arr = HMA_MAP[(tf, length)]
    i = int(np.searchsorted(ts_arr, target_ts, side="right")) - 1
    if i < 0: return None
    v = hma_arr[i]
    return None if np.isnan(v) else float(v)


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


# Load 2h LONG ob_vc
df = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")
g2h = df[df.htf == "2h"].copy()
g2h["has_15m"] = g2h.groupby(["direction","ob_cur_open_ms"])["ltf"].transform(lambda x: "15m" in set(x))
mask_lt = ((g2h.has_15m & (g2h.ltf=="15m")) | (~g2h.has_15m & (g2h.ltf=="20m")))
g2h = g2h[mask_lt & (g2h.direction == "long")].copy()

print(f"\nProcessing {len(g2h.groupby(['direction','ob_cur_open_ms']))} LONG setups...")
records = []
for (d, co), sub in g2h.groupby(["direction","ob_cur_open_ms"]):
    co = int(co); born = int(sub.iloc[0].born_ms)
    idx = bar2h_idx.get(co)
    if idx is None: continue
    cur = cans_2h[idx]
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
    # HMA values for all (TF, length) at born_ms
    for tf in TFS:
        for L in HMA_LENGTHS:
            v = hma_at(tf, L, born)
            rec[f"hma_{tf}_{L}"] = v
            rec[f"above_{tf}_{L}"] = (v is not None and cur_close > v)
    records.append(rec)

rdf = pd.DataFrame(records)
print(f"Records: {len(rdf)}")

# Filter to decisive
dec = rdf[rdf.R.isin([1, -1])].copy()
print(f"Decisive: W={(dec.R==1).sum()} L={(dec.R==-1).sum()}")


def winner_loser_diff(dec, col):
    w = dec[dec.R == 1][col].dropna()
    l = dec[dec.R == -1][col].dropna()
    if len(w) < 20 or len(l) < 20: return None
    return w.mean() * 100, l.mean() * 100, (w.mean() - l.mean()) * 100


# Above/below per TF/length
print(f"\n{'='*100}")
print(f"price ABOVE HMA — % of WINNERS vs % of LOSERS")
print(f"{'='*100}")
print(f"{'TF':<5} {'HMA':<5} {'%W_above':>9} {'%L_above':>9} {'diff_pp':>8}")
for tf in TFS:
    for L in HMA_LENGTHS:
        col = f"above_{tf}_{L}"
        d = winner_loser_diff(dec, col)
        if d is None: continue
        pw, pl, diff = d
        flag = "⭐" if diff >= 5 else ("✓" if diff >= 2 else ("❌" if diff <= -5 else ""))
        print(f"{tf:<5} {L:<5} {pw:>8.1f}% {pl:>8.1f}% {diff:>+7.1f}pp {flag}")


# Stack alignment — all TFs above all HMAs (full bull stack)
print(f"\n{'='*100}")
print(f"ALIGNMENT STACKS")
print(f"{'='*100}")


def stat(mask, lbl, ref):
    s = dec[mask]
    if len(s) < 10: print(f"  {lbl:<55} N={len(s)} (skip)"); return
    nt=s.touched.sum(); w=(s.R==1).sum(); l=(s.R==-1).sum()
    wr = w/nt*100 if nt else 0
    lift = wr - ref
    flag = "⭐" if lift >= 3 else ("✓" if lift >= 1 else ("❌" if lift <= -3 else ""))
    print(f"  {lbl:<55} N={len(s):>4} WR={wr:>5.1f}% Σ={w-l:>+4}R ({lift:+.1f}pp) {flag}")


ref_wr = (dec.R==1).sum()/dec.touched.sum()*100
print(f"BASELINE: N={len(dec)} WR={ref_wr:.1f}%")

# All TFs above HMA-200
all_above_200 = np.ones(len(dec), dtype=bool)
for tf in TFS: all_above_200 = all_above_200 & dec[f"above_{tf}_200"].fillna(False)
stat(all_above_200, "ALL TFs (2h+4h+12h+1d) ABOVE HMA-200", ref_wr)

all_above_78 = np.ones(len(dec), dtype=bool)
for tf in TFS: all_above_78 = all_above_78 & dec[f"above_{tf}_78"].fillna(False)
stat(all_above_78, "ALL TFs ABOVE HMA-78", ref_wr)

# All TFs above all lengths
all_above_all = np.ones(len(dec), dtype=bool)
for tf in TFS:
    for L in HMA_LENGTHS:
        all_above_all = all_above_all & dec[f"above_{tf}_{L}"].fillna(False)
stat(all_above_all, "ALL TFs × ALL HMA lengths (full bull stack)", ref_wr)

# All TFs BELOW HMA-200 (bear stack — counter-intuitive LONG)
all_below_200 = np.ones(len(dec), dtype=bool)
for tf in TFS: all_below_200 = all_below_200 & (~dec[f"above_{tf}_200"].fillna(True))
stat(all_below_200, "ALL TFs BELOW HMA-200 (bear stack)", ref_wr)

# Crossings: fast above slow (golden) per TF
print(f"\n--- Crossings per TF (HMA-fast > HMA-slow = bullish) ---")
for tf in TFS:
    cross_50_200 = dec[f"hma_{tf}_50"] > dec[f"hma_{tf}_200"]
    cross_78_200 = dec[f"hma_{tf}_78"] > dec[f"hma_{tf}_200"]
    cross_50_144 = dec[f"hma_{tf}_50"] > dec[f"hma_{tf}_144"]
    stat(cross_50_200.fillna(False), f"{tf}: HMA-50 > HMA-200 (golden)", ref_wr)
    stat(cross_78_200.fillna(False), f"{tf}: HMA-78 > HMA-200", ref_wr)
    stat(cross_50_144.fillna(False), f"{tf}: HMA-50 > HMA-144", ref_wr)

# 1D HMA-200 as macro filter
print(f"\n--- 1D HMA-200 as macro filter ---")
stat(dec[f"above_1d_200"].fillna(False), "price ABOVE 1D HMA-200", ref_wr)
stat(~dec[f"above_1d_200"].fillna(True), "price BELOW 1D HMA-200", ref_wr)

# 12h HMA-78 as mid filter
stat(dec[f"above_12h_78"].fillna(False), "price ABOVE 12h HMA-78", ref_wr)
stat(dec[f"above_12h_200"].fillna(False), "price ABOVE 12h HMA-200", ref_wr)

# Multi-TF: 1d + 12h + 4h ABOVE HMA-200 (3-TF bull confluence)
m_3tf = (dec.above_1d_200.fillna(False) &
         dec.above_12h_200.fillna(False) &
         dec.above_4h_200.fillna(False))
stat(m_3tf, "3 TFs (4h+12h+1d) ABOVE HMA-200", ref_wr)

# Subset 2023+
print(f"\n{'='*100}\nSUBSET 2023-06-06+\n{'='*100}")
sub = dec[dec.born_ms >= CUT].copy()
ref_wr_s = (sub.R==1).sum()/sub.touched.sum()*100 if sub.touched.sum() else 0
print(f"BASELINE SUBSET: N={len(sub)} WR={ref_wr_s:.1f}%")


def stat_s(mask, lbl):
    s = sub[mask]
    if len(s) < 10: return
    nt=s.touched.sum(); w=(s.R==1).sum(); l=(s.R==-1).sum()
    wr = w/nt*100 if nt else 0
    lift = wr - ref_wr_s
    flag = "⭐" if lift >= 3 else ("✓" if lift >= 1 else ("❌" if lift <= -3 else ""))
    print(f"  {lbl:<55} N={len(s):>4} WR={wr:>5.1f}% Σ={w-l:>+4}R ({lift:+.1f}pp) {flag}")


all_above_200_s = np.ones(len(sub), dtype=bool)
for tf in TFS: all_above_200_s = all_above_200_s & sub[f"above_{tf}_200"].fillna(False)
stat_s(all_above_200_s, "ALL TFs ABOVE HMA-200")

all_below_200_s = np.ones(len(sub), dtype=bool)
for tf in TFS: all_below_200_s = all_below_200_s & (~sub[f"above_{tf}_200"].fillna(True))
stat_s(all_below_200_s, "ALL TFs BELOW HMA-200")

stat_s(sub.above_1d_200.fillna(False), "ABOVE 1D HMA-200")
stat_s(~sub.above_1d_200.fillna(True), "BELOW 1D HMA-200")

m_3tf_s = (sub.above_1d_200.fillna(False) & sub.above_12h_200.fillna(False) &
           sub.above_4h_200.fillna(False))
stat_s(m_3tf_s, "3 TFs (4h+12h+1d) ABOVE HMA-200")

for tf in TFS:
    cross_78_200_s = (sub[f"hma_{tf}_78"] > sub[f"hma_{tf}_200"]).fillna(False)
    stat_s(cross_78_200_s, f"{tf}: HMA-78 > HMA-200")

# Save
out_path = pathlib.Path(__file__).parent.parent / "data/hma_features_long.parquet"
rdf.to_parquet(out_path)
print(f"\nSaved: {out_path}\nElapsed: {time.time()-t0:.1f}s")
