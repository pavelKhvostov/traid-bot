"""HTF anchored VWAP from fractals — взаимодействие 2h ob_vc с VWAP_FL (LONG) / VWAP_FH (SHORT).

Canon (per [[feedback-anchored-vwap-from-fractals]]):
  - N_FRACTAL = 2 (Williams N=2)
  - Anchor = fractal index + N_FRACTAL (confirmation moment)
  - VWAP = Σ(P_close × V) / Σ(V) от anchor до target time on 1m data

Per ob_vc setup at born_ms:
  - For each HTF in (12h, 1D):
    - Find LATEST same-direction fractal with confirm_ts < born_ms
    - Compute VWAP value at born_ms
    - Features:
      * dist_pct = (drop_lo - vwap) / vwap   (LONG)
                 = (vwap - drop_hi) / vwap   (SHORT)
      * touched: |dist_pct| ≤ thr
      * below: dist_pct < -thr (LONG drop_lo broke below VWAP-FL → bearish break)
      * above: dist_pct > +thr (LONG drop_lo well above VWAP-FL → bullish hold)
"""
import sys, pathlib, time
import numpy as np
import pandas as pd
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import aggregate_all_tfs, to_candles, detect_williams_n2

# Custom 1m loader with VOLUME
import csv
CSV_1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)

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

# Cumulative PV (price × volume) and Vol — for fast anchored VWAP
pv = c_1m * v_1m
cum_pv = np.concatenate(([0.0], np.cumsum(pv)))
cum_v = np.concatenate(([0.0], np.cumsum(v_1m)))
print(f"Loaded 1m: {len(rows):,} bars")


def vwap_at(anchor_ts: int, target_ts: int) -> float | None:
    """Anchored VWAP from anchor_ts to target_ts."""
    i_a = int(np.searchsorted(ts_1m, anchor_ts, side="left"))
    i_t = int(np.searchsorted(ts_1m, target_ts, side="right"))
    if i_t <= i_a: return None
    p = cum_pv[i_t] - cum_pv[i_a]
    v = cum_v[i_t] - cum_v[i_a]
    return float(p / v) if v > 0 else None


# Convert 1m to HTFs
print("Aggregating TFs...")
rows_ohlc = [(r[0], r[1], r[2], r[3], r[4]) for r in rows]
cans_d = aggregate_all_tfs(rows_ohlc)
cans_12h = to_candles(cans_d["12h"])
cans_1d = to_candles(cans_d["1d"])

# Williams fractals on HTF
print("Detecting Williams N=2 fractals...")
N_FRACTAL = 2


def fracts_with_confirm(cans):
    """Return list of (anchor_ts = cans[i+N].open_time, level, direction) for each fractal."""
    fhs, fls = detect_williams_n2(cans, n=N_FRACTAL)
    out_fh = []
    for (i, lvl, _) in fhs:
        if i + 1 < len(cans):
            out_fh.append((int(cans[i + 1].open_time), float(lvl)))
    out_fl = []
    for (i, lvl, _) in fls:
        if i + 1 < len(cans):
            out_fl.append((int(cans[i + 1].open_time), float(lvl)))
    return out_fh, out_fl


FH_12h, FL_12h = fracts_with_confirm(cans_12h)
FH_1d, FL_1d = fracts_with_confirm(cans_1d)
print(f"  12h: FH={len(FH_12h)}  FL={len(FL_12h)}")
print(f"  1d:  FH={len(FH_1d)}   FL={len(FL_1d)}")


# Sort by anchor_ts for fast bisect
def to_arrays(lst):
    if not lst: return np.zeros(0,dtype=np.int64), np.zeros(0)
    s = sorted(lst, key=lambda x: x[0])
    return np.array([x[0] for x in s], dtype=np.int64), np.array([x[1] for x in s])


a_FH12, l_FH12 = to_arrays(FH_12h)
a_FL12, l_FL12 = to_arrays(FL_12h)
a_FH1d, l_FH1d = to_arrays(FH_1d)
a_FL1d, l_FL1d = to_arrays(FL_1d)


def latest_anchor(anchors, born_ms: int):
    """Return idx of latest anchor with anchor_ts < born_ms, else None."""
    i = int(np.searchsorted(anchors, born_ms, side="left"))
    return i - 1 if i > 0 else None


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
print(f"\nMerged: {len(df_m):,}")


# ─── Compute features ──────────────────────────────────
TAP_PCTS = [0.003, 0.005, 0.010]


def setup_vwap_features(born, d, drop):
    """Return dict with VWAP-related features for each HTF."""
    rec = {}
    # For LONG, use FL anchors. For SHORT, use FH anchors.
    for tf_name, anchors_long, levels_long, anchors_short, levels_short in [
        ("12h", a_FL12, l_FL12, a_FH12, l_FH12),
        ("1d",  a_FL1d, l_FL1d, a_FH1d, l_FH1d),
    ]:
        anchors = anchors_long if d == "long" else anchors_short
        if len(anchors) == 0:
            rec[f"vwap_{tf_name}_val"] = None
            rec[f"vwap_{tf_name}_dist_pct"] = None
            continue
        idx = latest_anchor(anchors, born)
        if idx is None:
            rec[f"vwap_{tf_name}_val"] = None
            rec[f"vwap_{tf_name}_dist_pct"] = None
            continue
        anchor_ts = int(anchors[idx])
        v = vwap_at(anchor_ts, born)
        if v is None or v <= 0:
            rec[f"vwap_{tf_name}_val"] = None
            rec[f"vwap_{tf_name}_dist_pct"] = None
            continue
        if d == "long":
            dist_pct = (drop - v) / v  # drop_lo - VWAP_FL
        else:
            dist_pct = (v - drop) / v  # VWAP_FH - drop_hi
        rec[f"vwap_{tf_name}_val"] = float(v)
        rec[f"vwap_{tf_name}_dist_pct"] = float(dist_pct)
    return rec


records = []
for _, r in df_m.iterrows():
    born = int(r.born_ms); d = r.direction
    drop = float(r.drop_lo) if d == "long" else float(r.drop_hi)
    rec = {"born_ms": born, "direction": d, "t_id": r.t_id,
           "touched": r.touched, "R": r.R, "B1_aligned": r.B1_aligned}
    rec.update(setup_vwap_features(born, d, drop))
    records.append(rec)

rdf = pd.DataFrame(records)
print(f"Records: {len(rdf):,}")
print(f"vwap_12h_dist_pct stats: {rdf.vwap_12h_dist_pct.describe()}")

base_w=(rdf.R==1).sum(); base_l=(rdf.R==-1).sum(); base_nt=rdf.touched.sum()
base_wr = base_w/base_nt*100
print(f"\nBaseline: N={len(rdf)} WR={base_wr:.1f}% Σ={base_w-base_l:+}R")


def show(rdf, mask, label):
    inn = rdf[mask]; out = rdf[~mask]
    nin = len(inn); nout = len(out)
    wi = (inn.R==1).sum(); li = (inn.R==-1).sum()
    wo = (out.R==1).sum(); lo = (out.R==-1).sum()
    nti = inn.touched.sum(); nto = out.touched.sum()
    wr_i = wi/nti*100 if nti else 0
    wr_o = wo/nto*100 if nto else 0
    lift = wr_i - wr_o
    flag = "⭐" if lift >= 3 and nin >= 50 else ("✓" if lift >= 1 and nin >= 50 else "")
    print(f"{label:<40} {nin:>5} {wr_i:>6.1f}% EV={(2*wr_i/100)-1:>+6.3f}R Σ={wi-li:>+5}R | out N={nout} WR={wr_o:.1f}% Σ={wo-lo:+}R | {lift:+5.1f}pp {flag}")


# ─── Touch / Above / Below per TF ─────────────────────
print(f"\n{'='*120}")
print(f"VWAP INTERACTION — for LONG: drop_lo vs VWAP_FL; SHORT: drop_hi vs VWAP_FH")
print(f"{'='*120}")

for tf in ("12h", "1d"):
    col_d = f"vwap_{tf}_dist_pct"
    valid = rdf[col_d].notna()
    print(f"\n--- {tf} VWAP, valid records: {valid.sum()} ---")
    for thr in TAP_PCTS:
        mask_touch = valid & (rdf[col_d].abs() <= thr)
        mask_above = valid & (rdf[col_d] > thr)
        mask_below = valid & (rdf[col_d] < -thr)
        show(rdf, mask_touch, f"{tf} touch ±{thr*100:.1f}%")
        show(rdf, mask_above, f"{tf} above +{thr*100:.1f}%")
        show(rdf, mask_below, f"{tf} below -{thr*100:.1f}%")

# ─── Combined: any HTF touch ──────────────────────────
print(f"\n{'='*120}")
print(f"COMBINED ACROSS HTFs")
print(f"{'='*120}")
for thr in TAP_PCTS:
    m12_t = rdf.vwap_12h_dist_pct.notna() & (rdf.vwap_12h_dist_pct.abs() <= thr)
    m1d_t = rdf.vwap_1d_dist_pct.notna() & (rdf.vwap_1d_dist_pct.abs() <= thr)
    m12_a = rdf.vwap_12h_dist_pct.notna() & (rdf.vwap_12h_dist_pct > thr)
    m1d_a = rdf.vwap_1d_dist_pct.notna() & (rdf.vwap_1d_dist_pct > thr)
    m12_b = rdf.vwap_12h_dist_pct.notna() & (rdf.vwap_12h_dist_pct < -thr)
    m1d_b = rdf.vwap_1d_dist_pct.notna() & (rdf.vwap_1d_dist_pct < -thr)
    show(rdf, m12_t | m1d_t, f"ANY touch ±{thr*100:.1f}%")
    show(rdf, m12_a & m1d_a, f"BOTH above +{thr*100:.1f}% (bullish regime)")
    show(rdf, m12_b & m1d_b, f"BOTH below -{thr*100:.1f}% (bearish break)")

# ─── B1 cross ────────────────────────────────────────
print(f"\n{'='*120}")
print(f"B1 × VWAP")
print(f"{'='*120}")
b1 = rdf[rdf.B1_aligned]
b1_nt = b1.touched.sum(); b1_w=(b1.R==1).sum(); b1_l=(b1.R==-1).sum()
b1_wr = b1_w/b1_nt*100 if b1_nt else 0
print(f"B1 baseline: N={len(b1)} WR={b1_wr:.1f}% Σ={b1_w-b1_l:+}R")
for thr in TAP_PCTS:
    for label, mask_fn in [
        (f"touch12h ±{thr*100:.1f}%", lambda r,thr=thr: r.vwap_12h_dist_pct.notna() & (r.vwap_12h_dist_pct.abs() <= thr)),
        (f"above12h +{thr*100:.1f}%", lambda r,thr=thr: r.vwap_12h_dist_pct.notna() & (r.vwap_12h_dist_pct > thr)),
        (f"below12h -{thr*100:.1f}%", lambda r,thr=thr: r.vwap_12h_dist_pct.notna() & (r.vwap_12h_dist_pct < -thr)),
    ]:
        combo = rdf[rdf.B1_aligned & mask_fn(rdf)]
        if len(combo) < 30: continue
        nt = combo.touched.sum(); w=(combo.R==1).sum(); l=(combo.R==-1).sum()
        wr = w/nt*100 if nt else 0
        lift = wr - b1_wr
        flag = "⭐" if lift >= 2 else ("✓" if lift >= 0.5 else "")
        print(f"B1 + {label:<28} N={len(combo):>4} WR={wr:>5.1f}% Σ={w-l:+5}R  (vs B1: {lift:+.1f}pp) {flag}")

# Save
out_path = pathlib.Path(__file__).parent.parent / "data/htf_vwap_features.parquet"
rdf.to_parquet(out_path)
print(f"\nSaved: {out_path}")
print(f"Elapsed: {time.time()-t0:.1f}s")
