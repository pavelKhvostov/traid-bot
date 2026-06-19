"""HTF liquidity TAP-and-REJECT — ob_vc.drop_lo approaches but doesn't sweep fresh HTF FL.

Logic (LONG):
  - FL on HTF X exists: confirm_ts < born_ms
  - FL still fresh: sweep_ts_1m > born_ms (not yet broken)
  - ob_vc.drop_lo > FL_level (didn't sweep)
  - ob_vc.drop_lo ≤ FL_level * (1 + tap_pct) (close approach)

SHORT mirror.

Tap thresholds: 0.3%, 0.5%, 1.0%.
"""
import sys, pathlib, time
import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import load_1m, aggregate_all_tfs, to_candles, detect_williams_n2

t0 = time.time()
df = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/bulkowski_features.parquet")
print(f"ob_vc setups (post A1): {len(df):,}")

rows = load_1m()
cans_d = aggregate_all_tfs(rows)
cans_4h = to_candles(cans_d["4h"])
cans_12h = to_candles(cans_d["12h"])
cans_1d = to_candles(cans_d["1d"])

ts_1m = np.array([r[0] for r in rows], dtype=np.int64)
l_1m = np.array([r[3] for r in rows], dtype=np.float64)
h_1m = np.array([r[2] for r in rows], dtype=np.float64)


def compute_fresh_1m(cans, n: int = 2):
    fhs, fls = detect_williams_n2(cans, n=n)
    INF = int(ts_1m[-1]) + 10**13
    FL = []
    for (i, level, _) in fls:
        if i + n >= len(cans): continue
        confirm_ts = int(cans[i + n].open_time)
        i_start = int(np.searchsorted(ts_1m, confirm_ts))
        if i_start >= len(ts_1m): sweep_ts = INF
        else:
            below = l_1m[i_start:] <= level
            sweep_ts = int(ts_1m[i_start + int(np.argmax(below))]) if below.any() else INF
        FL.append((level, confirm_ts, sweep_ts))
    FH = []
    for (i, level, _) in fhs:
        if i + n >= len(cans): continue
        confirm_ts = int(cans[i + n].open_time)
        i_start = int(np.searchsorted(ts_1m, confirm_ts))
        if i_start >= len(ts_1m): sweep_ts = INF
        else:
            above = h_1m[i_start:] >= level
            sweep_ts = int(ts_1m[i_start + int(np.argmax(above))]) if above.any() else INF
        FH.append((level, confirm_ts, sweep_ts))
    return FL, FH


print("Computing fresh FL/FH on 4h, 12h, 1D...")
FL4, FH4 = compute_fresh_1m(cans_4h)
FL12, FH12 = compute_fresh_1m(cans_12h)
FL1d, FH1d = compute_fresh_1m(cans_1d)
print(f"  4h:  FL={len(FL4)}  FH={len(FH4)}")
print(f"  12h: FL={len(FL12)} FH={len(FH12)}")
print(f"  1d:  FL={len(FL1d)} FH={len(FH1d)}")


def to_arrays(lst):
    if not lst: return (np.zeros(0), np.zeros(0,dtype=np.int64), np.zeros(0,dtype=np.int64))
    return (np.array([x[0] for x in lst], dtype=np.float64),
            np.array([x[1] for x in lst], dtype=np.int64),
            np.array([x[2] for x in lst], dtype=np.int64))


FL4a, FH4a = to_arrays(FL4), to_arrays(FH4)
FL12a, FH12a = to_arrays(FL12), to_arrays(FH12)
FL1da, FH1da = to_arrays(FL1d), to_arrays(FH1d)


def tap_check(arrs, born_ms: int, drop_level: float, direction: str, tap_pct: float):
    """Return True if ANY fresh FL/FH was tapped (close approach without sweep).
    LONG:  FL.level > drop_lo  AND  drop_lo ≤ FL.level * (1 + tap_pct)
           AND fresh at born_ms (sweep_ts > born_ms)
    SHORT: FH.level < drop_hi  AND  drop_hi ≥ FH.level * (1 - tap_pct)
    """
    levels, confs, sweeps = arrs
    if len(levels) == 0: return False, 0
    fresh = (confs < born_ms) & (sweeps > born_ms)
    if not fresh.any(): return False, 0
    fl = levels[fresh]
    if direction == "long":
        # LONG tap-reject: drop_lo above FL_level (didn't break) but within tap_pct above
        # drop_lo > fl  AND  drop_lo ≤ fl * (1 + tap_pct)
        ok = (drop_level > fl) & (drop_level <= fl * (1 + tap_pct))
    else:
        # SHORT tap-reject: drop_hi below FH_level (didn't break) but within tap_pct below
        # drop_hi < fl AND drop_hi ≥ fl * (1 - tap_pct)
        ok = (drop_level < fl) & (drop_level >= fl * (1 - tap_pct))
    return bool(ok.any()), int(ok.sum())


# ─── Get drop_lo / drop_hi per setup ────────────
src = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")
g2h = src[src.htf == "2h"].copy()
g2h["has_15m"] = g2h.groupby(["direction","ob_cur_open_ms"])["ltf"].transform(
    lambda x: "15m" in set(x))
mask_lt = ((g2h.has_15m & (g2h.ltf=="15m")) | (~g2h.has_15m & (g2h.ltf=="20m")))
g2h = g2h[mask_lt].copy()
ob_drops = g2h.groupby(["direction","ob_cur_open_ms"]).agg(
    drop_lo=("drop_lo","first"), drop_hi=("drop_hi","first"),
    born_ms=("born_ms","first"),
).reset_index()
df_m = df.merge(ob_drops[["direction","born_ms","drop_lo","drop_hi"]],
                on=["direction","born_ms"], how="left")
print(f"Merged: {len(df_m):,}")


def show(rdf, f):
    inn = rdf[rdf[f]]; out = rdf[~rdf[f]]
    nin = len(inn); nout = len(out)
    wi = (inn.R==1).sum(); li = (inn.R==-1).sum()
    wo = (out.R==1).sum(); lo = (out.R==-1).sum()
    nti = inn.touched.sum(); nto = out.touched.sum()
    wr_i = wi/nti*100 if nti else 0
    wr_o = wo/nto*100 if nto else 0
    lift = wr_i - wr_o
    flag = "⭐" if lift >= 3 and nin >= 50 else ("✓" if lift >= 1 and nin >= 50 else "")
    print(f"{f:<28} {nin:>5} {wr_i:>6.1f}% {(2*wr_i/100)-1:>+8.3f}R {wi-li:>+5}R  |  {nout:>5} {wr_o:>6.1f}% {wo-lo:>+5}R  |  {lift:>+6.1f}pp {flag}")


# ─── Iterate over tap thresholds ─────────────────────────
for tap_pct in [0.003, 0.005, 0.010, 0.020]:
    print(f"\n{'='*110}")
    print(f"TAP-AND-REJECT, threshold = ±{tap_pct*100:.1f}%")
    print(f"{'='*110}")
    rows_out = []
    for _, r in df_m.iterrows():
        born = int(r.born_ms); d = r.direction
        drop = float(r.drop_lo) if d == "long" else float(r.drop_hi)
        rec = {"born_ms": born, "direction": d, "t_id": r.t_id,
               "touched": r.touched, "R": r.R, "B1_aligned": r.B1_aligned}
        for tf, arrs_long, arrs_short in [
            ("4h", FL4a, FH4a), ("12h", FL12a, FH12a), ("1d", FL1da, FH1da)
        ]:
            arrs = arrs_long if d == "long" else arrs_short
            ok, n = tap_check(arrs, born, drop, d, tap_pct)
            rec[f"tap_{tf}"] = ok
        rec["tap_any"] = rec["tap_4h"] or rec["tap_12h"] or rec["tap_1d"]
        rec["tap_12h_or_1d"] = rec["tap_12h"] or rec["tap_1d"]
        rec["tap_2plus"] = sum([rec["tap_4h"], rec["tap_12h"], rec["tap_1d"]]) >= 2
        rows_out.append(rec)
    rdf = pd.DataFrame(rows_out)

    base_w=(rdf.R==1).sum(); base_l=(rdf.R==-1).sum(); base_nt=rdf.touched.sum()
    base_wr = base_w/base_nt*100
    print(f"Baseline: N={len(rdf):,} WR={base_wr:.1f}% Σ={base_w-base_l:+}R")
    print(f"{'Feature':<28} {'N_in':>5} {'WR_in':>7} {'EV':>9} {'Σ_in':>5}  |  {'N_out':>5} {'WR_out':>7} {'Σ_out':>5}  |  {'lift':>6}")
    print("-"*110)
    for f in ["tap_4h","tap_12h","tap_1d","tap_any","tap_12h_or_1d","tap_2plus"]:
        show(rdf, f)

    # B1 cross
    b1 = rdf[rdf.B1_aligned]
    b1_nt = b1.touched.sum(); b1_w=(b1.R==1).sum(); b1_l=(b1.R==-1).sum()
    b1_wr = b1_w/b1_nt*100 if b1_nt else 0
    print(f"\n{'B1 baseline':<28} N={len(b1):>4} WR={b1_wr:.1f}% Σ={b1_w-b1_l:+}R")
    for f in ["tap_4h","tap_12h","tap_1d","tap_any","tap_12h_or_1d"]:
        combo = rdf[rdf.B1_aligned & rdf[f]]
        if len(combo) < 30: continue
        nt = combo.touched.sum(); w=(combo.R==1).sum(); l=(combo.R==-1).sum()
        wr = w/nt*100 if nt else 0
        lift = wr - b1_wr
        flag = "⭐" if lift >= 2 else ("✓" if lift >= 0.5 else "")
        print(f"B1 + {f:<24} N={len(combo):>4} WR={wr:>5.1f}% Σ={w-l:+5}R  (vs B1: {lift:+.1f}pp) {flag}")

print(f"\nElapsed: {time.time()-t0:.1f}s")
