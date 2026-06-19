"""Age-limited D-fractal VWAPs — only last N days of D fractals active.

Per ob_vc at born_ms:
  Window = [born_ms - AGE_MS, born_ms)
  Only D fractals confirmed within window contribute to active VWAPs.

Features per AGE window (30/90/180 days):
  n_same_touched, n_same_above, n_same_below   (drop_lo vs FL VWAPs, LONG)
  n_opp_*                                       (drop vs FH VWAPs)
  frac_same_above = n_same_above / n_same_active
  frac_same_below = n_same_below / n_same_active

Report standalone + B1 combos.
Also robustness: full 6y vs 2023-06-06+ subset.
"""
import sys, pathlib, time, csv
import numpy as np
import pandas as pd
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import aggregate_all_tfs, to_candles, detect_williams_n2

CSV_1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
CUT_2023 = int(datetime(2023, 6, 6, tzinfo=timezone.utc).timestamp() * 1000)
N_FRACTAL = 2
AGE_DAYS = [30, 90, 180]
TOUCH_THR = 0.005
DAY_MS = 24 * 3600 * 1000

t0 = time.time()


def load_1m_with_vol():
    rows = []
    with CSV_1M.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
            if t < START_MS: continue
            rows.append((t, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return rows


rows = load_1m_with_vol()
ts_1m = np.array([r[0] for r in rows], dtype=np.int64)
c_1m = np.array([r[4] for r in rows], dtype=np.float64)
v_1m = np.array([r[5] for r in rows], dtype=np.float64)
cum_pv = np.concatenate(([0.0], np.cumsum(c_1m * v_1m)))
cum_v = np.concatenate(([0.0], np.cumsum(v_1m)))

rows_ohlc = [(r[0], r[1], r[2], r[3], r[4]) for r in rows]
cans_d = aggregate_all_tfs(rows_ohlc)
cans_1d = to_candles(cans_d["1d"])

fhs_1d, fls_1d = detect_williams_n2(cans_1d, n=N_FRACTAL)
FL_anchors_full = []
FL_levels_full = []
for (i, lvl, _) in fls_1d:
    if i + 1 < len(cans_1d):
        FL_anchors_full.append(int(cans_1d[i + 1].open_time))
        FL_levels_full.append(float(lvl))
FH_anchors_full = []
FH_levels_full = []
for (i, lvl, _) in fhs_1d:
    if i + 1 < len(cans_1d):
        FH_anchors_full.append(int(cans_1d[i + 1].open_time))
        FH_levels_full.append(float(lvl))

# Sort by anchor_ts
fl_idx = np.argsort(FL_anchors_full)
FL_A = np.array(FL_anchors_full, dtype=np.int64)[fl_idx]
FL_L = np.array(FL_levels_full, dtype=np.float64)[fl_idx]
fh_idx = np.argsort(FH_anchors_full)
FH_A = np.array(FH_anchors_full, dtype=np.int64)[fh_idx]
FH_L = np.array(FH_levels_full, dtype=np.float64)[fh_idx]
print(f"D fractals: FL={len(FL_A)}  FH={len(FH_A)}")


def vwap_values_batch(anchors_ts: np.ndarray, target_ts: int) -> np.ndarray:
    if len(anchors_ts) == 0:
        return np.array([])
    i_t = int(np.searchsorted(ts_1m, target_ts, side="right"))
    if i_t == 0: return np.full(len(anchors_ts), np.nan)
    i_as = np.searchsorted(ts_1m, anchors_ts, side="left")
    active = i_as < i_t
    out = np.full(len(anchors_ts), np.nan)
    if not active.any(): return out
    p = cum_pv[i_t] - cum_pv[i_as[active]]
    v = cum_v[i_t] - cum_v[i_as[active]]
    out[active] = np.where(v > 0, p / v, np.nan)
    return out


# ─── Load setups ─────────────────────────────────────────
df = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/bulkowski_features.parquet")
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
print(f"Setups: {len(df_m):,}")


# ─── Compute features for each age window ──────────────
def compute_features_for_setup(born, d, drop, age_ms):
    """Return dict for given age window."""
    lo = born - age_ms
    # Subset of FL/FH within age window
    i_fl_lo = int(np.searchsorted(FL_A, lo, side="left"))
    i_fl_hi = int(np.searchsorted(FL_A, born, side="left"))
    fl_a_sub = FL_A[i_fl_lo:i_fl_hi]
    fl_l_sub = FL_L[i_fl_lo:i_fl_hi]
    i_fh_lo = int(np.searchsorted(FH_A, lo, side="left"))
    i_fh_hi = int(np.searchsorted(FH_A, born, side="left"))
    fh_a_sub = FH_A[i_fh_lo:i_fh_hi]
    fh_l_sub = FH_L[i_fh_lo:i_fh_hi]

    vwap_fl = vwap_values_batch(fl_a_sub, born)
    vwap_fh = vwap_values_batch(fh_a_sub, born)
    fl_valid = ~np.isnan(vwap_fl); fh_valid = ~np.isnan(vwap_fh)
    n_FL = int(fl_valid.sum()); n_FH = int(fh_valid.sum())

    # drop vs same/opp direction VWAPs
    if d == "long":
        same_v = vwap_fl[fl_valid]; opp_v = vwap_fh[fh_valid]
    else:
        same_v = vwap_fh[fh_valid]; opp_v = vwap_fl[fl_valid]
    n_same = len(same_v); n_opp = len(opp_v)

    def counts(vs):
        if len(vs) == 0: return 0, 0, 0
        rel = (drop - vs) / vs if d == "long" else (vs - drop) / vs
        # For LONG: rel > 0 means drop_lo above VWAP (bullish above support)
        # For SHORT: rel > 0 means drop_hi below VWAP (bearish below resistance)
        # We use consistent semantic: "above" = drop_lo above FL (LONG) or drop_hi below FH (SHORT)
        if d == "long":
            r = (drop - vs) / vs
        else:
            r = (drop - vs) / vs  # SHORT: drop_hi - FH_vwap, positive if drop_hi above FH (broken above)
        touched = int((np.abs(r) <= TOUCH_THR).sum())
        above = int((r > TOUCH_THR).sum())
        below = int((r < -TOUCH_THR).sum())
        return touched, above, below

    t_s, a_s, b_s = counts(same_v)
    t_o, a_o, b_o = counts(opp_v)
    frac_same_above = a_s / max(n_same, 1)
    frac_same_below = b_s / max(n_same, 1)
    return {
        "n_same_active": n_same, "n_opp_active": n_opp,
        "n_same_touched": t_s, "n_same_above": a_s, "n_same_below": b_s,
        "n_opp_touched": t_o, "n_opp_above": a_o, "n_opp_below": b_o,
        "frac_same_above": frac_same_above, "frac_same_below": frac_same_below,
    }


print("Computing per-age features (this takes a moment)...")
all_age_results = {}
for age_days in AGE_DAYS:
    age_ms = age_days * DAY_MS
    recs = []
    for _, r in df_m.iterrows():
        born = int(r.born_ms); d = r.direction
        drop = float(r.drop_lo) if d == "long" else float(r.drop_hi)
        rec = {"born_ms": born, "direction": d, "t_id": r.t_id,
               "touched": r.touched, "R": r.R, "B1_aligned": r.B1_aligned}
        rec.update(compute_features_for_setup(born, d, drop, age_ms))
        recs.append(rec)
    all_age_results[age_days] = pd.DataFrame(recs)
    print(f"  age={age_days}d: done")


# ─── Report ──────────────────────────────────────────────
def report(rdf, title):
    print(f"\n{'='*120}")
    print(f"{title}  (N={len(rdf):,})")
    print(f"{'='*120}")
    base_w=(rdf.R==1).sum(); base_l=(rdf.R==-1).sum(); base_nt=rdf.touched.sum()
    base_wr = base_w/base_nt*100 if base_nt else 0
    print(f"baseline: WR={base_wr:.1f}% Σ={base_w-base_l:+}R | mean active VWAPs same/opp: {rdf.n_same_active.mean():.1f} / {rdf.n_opp_active.mean():.1f}")
    b1 = rdf[rdf.B1_aligned]
    b1_w=(b1.R==1).sum(); b1_l=(b1.R==-1).sum(); b1_nt=b1.touched.sum()
    b1_wr = b1_w/b1_nt*100 if b1_nt else 0
    print(f"B1 base: N={len(b1)} WR={b1_wr:.1f}% Σ={b1_w-b1_l:+}R")

    def stat(mask, lbl, ref):
        s = rdf[mask]
        if len(s)<20: return
        nt=s.touched.sum(); w=(s.R==1).sum(); l=(s.R==-1).sum()
        wr=w/nt*100 if nt else 0
        flag = "⭐" if wr - ref >= 2 else ("✓" if wr - ref >= 0.5 else "")
        print(f"  {lbl:<44} N={len(s):>4} WR={wr:>5.1f}% Σ={w-l:+4}R  ({wr-ref:+.1f}pp) {flag}")

    print("STANDALONE — regime broken (frac_same_above ≤ thr):")
    for thr in [0.5, 0.3, 0.1, 0.05]:
        stat(rdf.frac_same_above <= thr, f"frac_same_above ≤ {thr}", base_wr)
    print("STANDALONE — regime hold (frac_same_above ≥ thr):")
    for thr in [0.7, 0.9, 1.0]:
        stat(rdf.frac_same_above >= thr, f"frac_same_above ≥ {thr}", base_wr)
    print("STANDALONE — touched ≥ k:")
    for k in [1, 2, 3]:
        stat(rdf.n_same_touched >= k, f"n_same_touched ≥ {k}", base_wr)

    print(f"\nB1 × VWAP combos (vs B1 baseline {b1_wr:.1f}%):")
    for thr in [0.5, 0.3, 0.1]:
        stat(rdf.B1_aligned & (rdf.frac_same_above <= thr), f"B1 + frac_same_above ≤ {thr}", b1_wr)
    for thr in [0.7, 0.9]:
        stat(rdf.B1_aligned & (rdf.frac_same_above >= thr), f"B1 + frac_same_above ≥ {thr}", b1_wr)
    for k in [1, 2, 3]:
        stat(rdf.B1_aligned & (rdf.n_same_touched >= k), f"B1 + n_same_touched ≥ {k}", b1_wr)
    for k in [1, 2, 3]:
        stat(rdf.B1_aligned & (rdf.n_same_above >= k), f"B1 + n_same_above ≥ {k}", b1_wr)


for age_days in AGE_DAYS:
    rdf = all_age_results[age_days]
    report(rdf, f"AGE-LIMITED {age_days}d — FULL 6y")
    # subset 2023-06-06+
    sub = rdf[rdf.born_ms >= CUT_2023].reset_index(drop=True)
    report(sub, f"AGE-LIMITED {age_days}d — SUBSET 2023-06-06+")

# Save
for age_days in AGE_DAYS:
    out_path = pathlib.Path(__file__).parent.parent / f"data/d_vwap_age{age_days}d.parquet"
    all_age_results[age_days].to_parquet(out_path)
print(f"\nSaved 3 parquets.  Elapsed: {time.time()-t0:.1f}s")
