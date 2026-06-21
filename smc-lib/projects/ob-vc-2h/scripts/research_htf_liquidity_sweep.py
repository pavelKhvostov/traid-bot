"""HTF liquidity sweep — does 2h ob_vc.drop_lo (LONG) / drop_hi (SHORT) sweep
fresh HTF fractal liquidity (FL/FH) on 4h, 12h, 1D?

Canon:
  - Williams N=2 fractals on HTF X
  - FL confirmed at cans_X[i+2].open_time
  - FL "fresh" = no 1m tick between confirm_ts and our ob_vc's bars has gone below it
  - LONG ob_vc swept fresh FL iff:
      confirm_ts < prev_open_ms_2h    (FL existed before our bars)
      AND drop_lo ≤ FL_level          (our wick reached the level)
      AND first_1m_below(level) ≥ prev_open_ms_2h  (we were first to sweep)
  - SHORT mirror

No-lookahead: only FLs/FHs confirmed before born_ms used.
"""
import sys, pathlib, time
import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import load_1m, aggregate_all_tfs, to_candles, detect_williams_n2

t0 = time.time()

# ─── Load data ──────────────────────────────────────────────
df = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/bulkowski_features.parquet")
print(f"ob_vc setups (post A1): {len(df):,}")

rows = load_1m()
cans_d = aggregate_all_tfs(rows)
cans_2h = to_candles(cans_d["2h"])
cans_4h = to_candles(cans_d["4h"])
cans_12h = to_candles(cans_d["12h"])
cans_1d = to_candles(cans_d["1d"])
print(f"Bars: 2h={len(cans_2h):,}  4h={len(cans_4h):,}  12h={len(cans_12h):,}  1d={len(cans_1d):,}")

ts_1m = np.array([r[0] for r in rows], dtype=np.int64)
l_1m = np.array([r[3] for r in rows], dtype=np.float64)
h_1m = np.array([r[2] for r in rows], dtype=np.float64)

# 2h bar index by open_time for prev_open lookup
bar2h_idx = {c.open_time: i for i, c in enumerate(cans_2h)}


# ─── Compute fresh FL/FH intervals using 1m sweep detection ──
def compute_fresh_intervals_1m(cans, n: int = 2):
    """Per FL/FH: (level, confirm_ts, sweep_ts_1m).
    sweep_ts_1m = first 1m moment after confirm where low ≤ level (FL) / high ≥ level (FH).
    """
    fhs, fls = detect_williams_n2(cans, n=n)
    INF_TS = int(ts_1m[-1]) + 10**13
    FL = []
    for (i, level, _) in fls:
        if i + n >= len(cans): continue
        confirm_ts = int(cans[i + n].open_time)
        i_start = int(np.searchsorted(ts_1m, confirm_ts))
        if i_start >= len(ts_1m):
            sweep_ts = INF_TS
        else:
            below = l_1m[i_start:] <= level
            if below.any():
                idx = int(np.argmax(below))
                sweep_ts = int(ts_1m[i_start + idx])
            else:
                sweep_ts = INF_TS
        FL.append((level, confirm_ts, sweep_ts))
    FH = []
    for (i, level, _) in fhs:
        if i + n >= len(cans): continue
        confirm_ts = int(cans[i + n].open_time)
        i_start = int(np.searchsorted(ts_1m, confirm_ts))
        if i_start >= len(ts_1m):
            sweep_ts = INF_TS
        else:
            above = h_1m[i_start:] >= level
            if above.any():
                idx = int(np.argmax(above))
                sweep_ts = int(ts_1m[i_start + idx])
            else:
                sweep_ts = INF_TS
        FH.append((level, confirm_ts, sweep_ts))
    return FL, FH


print("\nComputing fresh FL/FH intervals (1m-resolution sweep) on 4h, 12h, 1D...")
FL_4h, FH_4h = compute_fresh_intervals_1m(cans_4h)
FL_12h, FH_12h = compute_fresh_intervals_1m(cans_12h)
FL_1d, FH_1d = compute_fresh_intervals_1m(cans_1d)
print(f"  4h:  FL={len(FL_4h):,}  FH={len(FH_4h):,}")
print(f"  12h: FL={len(FL_12h):,}  FH={len(FH_12h):,}")
print(f"  1d:  FL={len(FL_1d):,}  FH={len(FH_1d):,}")


def to_arrays(lst):
    if not lst: return (np.zeros(0), np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64))
    levels = np.array([x[0] for x in lst], dtype=np.float64)
    confs = np.array([x[1] for x in lst], dtype=np.int64)
    sweeps = np.array([x[2] for x in lst], dtype=np.int64)
    return levels, confs, sweeps


FL_4h_a = to_arrays(FL_4h);  FH_4h_a = to_arrays(FH_4h)
FL_12h_a = to_arrays(FL_12h); FH_12h_a = to_arrays(FH_12h)
FL_1d_a = to_arrays(FL_1d);  FH_1d_a = to_arrays(FH_1d)


def count_swept(levels, confs, sweeps, prev_open_ms: int, drop_level: float, direction: str):
    """Count fresh FLs (LONG) / FHs (SHORT) swept by this ob_vc's bars.
    - confirm < prev_open  (existed before our bars)
    - sweep_ts ≥ prev_open  (NOT swept before our bars)
    - drop_level reached level (LONG: drop_lo ≤ level; SHORT: drop_hi ≥ level)
    """
    if len(levels) == 0: return 0
    fresh = (confs < prev_open_ms) & (sweeps >= prev_open_ms)
    if not fresh.any(): return 0
    fl = levels[fresh]
    if direction == "long":
        return int((fl >= drop_level).sum())
    return int((fl <= drop_level).sum())


# ─── Get drop_lo / drop_hi + prev_open per setup ────────────
src = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")
g2h = src[src.htf == "2h"].copy()
g2h["has_15m"] = g2h.groupby(["direction","ob_cur_open_ms"])["ltf"].transform(
    lambda x: "15m" in set(x))
mask_lt = ((g2h.has_15m & (g2h.ltf=="15m")) | (~g2h.has_15m & (g2h.ltf=="20m")))
g2h = g2h[mask_lt].copy()
ob_drops = g2h.groupby(["direction","ob_cur_open_ms"]).agg(
    drop_lo=("drop_lo","first"),
    drop_hi=("drop_hi","first"),
    born_ms=("born_ms","first"),
    cur_open_ms=("ob_cur_open_ms","first"),
).reset_index()
df_m = df.merge(ob_drops[["direction","born_ms","drop_lo","drop_hi","cur_open_ms"]],
                on=["direction","born_ms"], how="left")
print(f"\nMerged: {len(df_m):,}")

# prev_open = cur_open - 2h
TF_2H = 2*3600*1000
df_m["prev_open_ms"] = df_m["cur_open_ms"].astype(np.int64) - TF_2H


# ─── Compute features ──────────────────────────────────────
records = []
for _, r in df_m.iterrows():
    born = int(r.born_ms); d = r.direction
    prev_open = int(r.prev_open_ms)
    drop = float(r.drop_lo) if d == "long" else float(r.drop_hi)
    rec = {"born_ms": born, "direction": d, "t_id": r.t_id,
           "touched": r.touched, "R": r.R, "B1_aligned": r.B1_aligned}
    if d == "long":
        for tf, arrs in [("4h", FL_4h_a), ("12h", FL_12h_a), ("1d", FL_1d_a)]:
            n = count_swept(*arrs, prev_open, drop, d)
            rec[f"liq_{tf}_n"] = n
            rec[f"liq_{tf}_sweep"] = n > 0
    else:
        for tf, arrs in [("4h", FH_4h_a), ("12h", FH_12h_a), ("1d", FH_1d_a)]:
            n = count_swept(*arrs, prev_open, drop, d)
            rec[f"liq_{tf}_n"] = n
            rec[f"liq_{tf}_sweep"] = n > 0
    records.append(rec)

rdf = pd.DataFrame(records)
print(f"Records: {len(rdf):,}")

base_w = (rdf.R==1).sum(); base_l = (rdf.R==-1).sum(); base_nt = rdf.touched.sum()
base_wr = base_w/base_nt*100 if base_nt else 0
print(f"\nBaseline: N={len(rdf):,}  touch={base_nt}  WR={base_wr:.1f}%  Σ={base_w-base_l:+}R")

# Sweep coverage
for tf in ("4h","12h","1d"):
    n_sw = rdf[f"liq_{tf}_sweep"].sum()
    print(f"  liq_{tf}_sweep coverage: {n_sw} / {len(rdf)} ({n_sw/len(rdf)*100:.1f}%)")

# ─── Per-feature WR uplift ─────────────────────────────────
print(f"\n{'='*110}")
print(f"PER-FEATURE WR")
print(f"{'='*110}")
print(f"{'Feature':<22} {'N_in':>6} {'WR_in':>7} {'EV_in':>9} {'Σ_in':>7}  |  {'N_out':>6} {'WR_out':>8} {'Σ_out':>7}  |  {'lift_pp':>8}")
print("-"*110)


def show(rdf, f, prev_wr=None):
    inn = rdf[rdf[f]]; out = rdf[~rdf[f]]
    nin = len(inn); nout = len(out)
    wi = (inn.R==1).sum(); li = (inn.R==-1).sum()
    wo = (out.R==1).sum(); lo = (out.R==-1).sum()
    nti = inn.touched.sum(); nto = out.touched.sum()
    wr_i = wi/nti*100 if nti else 0
    wr_o = wo/nto*100 if nto else 0
    lift = wr_i - wr_o
    flag = "⭐" if lift >= 3 and nin >= 50 else ("✓" if lift >= 1 and nin >= 50 else "")
    print(f"{f:<22} {nin:>6} {wr_i:>6.1f}% {(2*wr_i/100)-1:>+8.3f}R {wi-li:>+6}R  |  {nout:>6} {wr_o:>7.1f}% {wo-lo:>+6}R  |  {lift:>+7.1f}pp {flag}")
    return wr_i, lift


for f in ["liq_4h_sweep", "liq_12h_sweep", "liq_1d_sweep"]:
    show(rdf, f)

# ─── Multi-HTF combos ──────────────────────────────────────
print(f"\n{'='*110}")
print(f"MULTI-HTF COMBINATIONS")
print(f"{'='*110}")
rdf["any_sweep"] = rdf.liq_4h_sweep | rdf.liq_12h_sweep | rdf.liq_1d_sweep
rdf["2plus_sweep"] = (rdf.liq_4h_sweep.astype(int) + rdf.liq_12h_sweep.astype(int) + rdf.liq_1d_sweep.astype(int)) >= 2
rdf["all3_sweep"] = rdf.liq_4h_sweep & rdf.liq_12h_sweep & rdf.liq_1d_sweep
rdf["12h_or_1d"] = rdf.liq_12h_sweep | rdf.liq_1d_sweep
rdf["12h_and_1d"] = rdf.liq_12h_sweep & rdf.liq_1d_sweep
for f in ["any_sweep","2plus_sweep","all3_sweep","12h_or_1d","12h_and_1d"]:
    show(rdf, f)

# ─── Cross with B1 ─────────────────────────────────────────
print(f"\n{'='*110}")
print(f"B1 × LIQUIDITY SWEEP COMBINATIONS")
print(f"{'='*110}")
b1 = rdf[rdf.B1_aligned]
b1_nt = b1.touched.sum(); b1_w=(b1.R==1).sum(); b1_l=(b1.R==-1).sum()
b1_wr = b1_w/b1_nt*100 if b1_nt else 0
print(f"{'B1 baseline':<35} N={len(b1):>5} touch={b1_nt} WR={b1_wr:.1f}% Σ={b1_w-b1_l:+}R")
for f in ["liq_4h_sweep","liq_12h_sweep","liq_1d_sweep","any_sweep","2plus_sweep","12h_or_1d","12h_and_1d"]:
    combo = rdf[rdf.B1_aligned & rdf[f]]
    if len(combo) < 30: continue
    nt = combo.touched.sum(); w=(combo.R==1).sum(); l=(combo.R==-1).sum()
    wr = w/nt*100 if nt else 0
    lift_vs_b1 = wr - b1_wr
    flag = "⭐" if lift_vs_b1 >= 2 else ("✓" if lift_vs_b1 >= 0.5 else "")
    print(f"B1 + {f:<30} N={len(combo):>4} touch={nt:>4} WR={wr:>5.1f}% Σ={w-l:>+5}R   (vs B1: {lift_vs_b1:+.1f}pp) {flag}")

# Save
out_path = pathlib.Path(__file__).parent.parent / "data/htf_liquidity_features.parquet"
rdf.to_parquet(out_path)
print(f"\nSaved: {out_path}")
print(f"Elapsed: {time.time()-t0:.1f}s")
