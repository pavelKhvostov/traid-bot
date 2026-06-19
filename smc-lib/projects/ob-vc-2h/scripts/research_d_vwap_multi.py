"""D-fractal anchored VWAPs (FULL set, не latest only) — canon per
[[feedback-anchored-vwap-from-fractals]] + [[feedback-12h-fractal-c8-vwap-w-aligned]].

Кол-во VWAPs = кол-во D fractals (Williams N=2 на 1D).

Per ob_vc setup at born_ms:
  For each D-fractal confirmed (confirm_ts < born_ms):
    compute VWAP value at born_ms
    classify drop_level interaction:
      LONG:  drop_lo (вника drop)
        - touch (±thr%): |drop_lo - vwap|/vwap ≤ thr
        - swept_below: drop_lo < vwap  (LONG drop went below VWAP)
        - above: drop_lo > vwap
      SHORT: drop_hi
        - touch (±thr%): |drop_hi - vwap|/vwap ≤ thr
        - swept_above: drop_hi > vwap
        - below: drop_hi < vwap

Aggregate count features:
  - n_FL_active: total D-FL VWAPs alive (confirm < born_ms)
  - n_FH_active: total D-FH VWAPs alive
  - n_FL_touched / n_FH_touched at ±thr
  - n_FL_above / n_FL_below (LONG drop_lo position vs FL VWAPs)
  - n_FH_above / n_FH_below
"""
import sys, pathlib, time, csv
import numpy as np
import pandas as pd
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import aggregate_all_tfs, to_candles, detect_williams_n2

CSV_1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
N_FRACTAL = 2

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
print(f"Loaded 1m: {len(rows):,}")

rows_ohlc = [(r[0], r[1], r[2], r[3], r[4]) for r in rows]
cans_d = aggregate_all_tfs(rows_ohlc)
cans_1d = to_candles(cans_d["1d"])

# D fractals
fhs_1d, fls_1d = detect_williams_n2(cans_1d, n=N_FRACTAL)
D_FL = []  # (confirm_ts, fractal_level)
D_FH = []
for (i, lvl, _) in fls_1d:
    if i + 1 < len(cans_1d):
        D_FL.append((int(cans_1d[i + 1].open_time), float(lvl)))
for (i, lvl, _) in fhs_1d:
    if i + 1 < len(cans_1d):
        D_FH.append((int(cans_1d[i + 1].open_time), float(lvl)))
D_FL = np.array(D_FL, dtype=np.float64)
D_FH = np.array(D_FH, dtype=np.float64)
print(f"D fractals: FL={len(D_FL)}  FH={len(D_FH)}  → total VWAPs={len(D_FL)+len(D_FH)}")


def vwap_at_batch(anchors_ts: np.ndarray, target_ts: int) -> np.ndarray:
    """Compute anchored VWAP values for all anchors at target_ts. NaN where anchor ≥ target."""
    i_t = int(np.searchsorted(ts_1m, target_ts, side="right"))
    if i_t == 0: return np.full(len(anchors_ts), np.nan)
    # For each anchor: i_a = searchsorted(ts_1m, anchor_ts, side='left')
    i_as = np.searchsorted(ts_1m, anchors_ts, side="left")
    # Active = anchor < target_ts (i_a < i_t)
    active = i_as < i_t
    out = np.full(len(anchors_ts), np.nan)
    if not active.any(): return out
    p = cum_pv[i_t] - cum_pv[i_as[active]]
    v = cum_v[i_t] - cum_v[i_as[active]]
    vwap = np.where(v > 0, p / v, np.nan)
    out[active] = vwap
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
print(f"Merged: {len(df_m):,}")


# ─── Compute features ──────────────────────────────────
FL_anchors = D_FL[:, 0] if len(D_FL) else np.array([])
FL_levels = D_FL[:, 1] if len(D_FL) else np.array([])
FH_anchors = D_FH[:, 0] if len(D_FH) else np.array([])
FH_levels = D_FH[:, 1] if len(D_FH) else np.array([])

THR = 0.005  # ±0.5% for touch

records = []
for _, r in df_m.iterrows():
    born = int(r.born_ms); d = r.direction
    drop_lo = float(r.drop_lo); drop_hi = float(r.drop_hi)
    drop = drop_lo if d == "long" else drop_hi

    vwap_FL = vwap_at_batch(FL_anchors, born)
    vwap_FH = vwap_at_batch(FH_anchors, born)
    fl_valid = ~np.isnan(vwap_FL)
    fh_valid = ~np.isnan(vwap_FH)

    rec = {"born_ms": born, "direction": d, "t_id": r.t_id,
           "touched": r.touched, "R": r.R, "B1_aligned": r.B1_aligned,
           "n_FL_active": int(fl_valid.sum()),
           "n_FH_active": int(fh_valid.sum())}

    if fl_valid.any():
        fl_v = vwap_FL[fl_valid]
        # For LONG: drop_lo vs FL VWAPs (same direction = support)
        # For SHORT: drop_hi vs FL VWAPs (opposite direction = below-level)
        rel = (drop - fl_v) / fl_v  # positive: drop above VWAP
        rec["n_FL_touched"] = int((np.abs(rel) <= THR).sum())
        rec["n_FL_above"]   = int((rel >  THR).sum())
        rec["n_FL_below"]   = int((rel < -THR).sum())
    else:
        rec.update({"n_FL_touched":0, "n_FL_above":0, "n_FL_below":0})
    if fh_valid.any():
        fh_v = vwap_FH[fh_valid]
        rel = (drop - fh_v) / fh_v
        rec["n_FH_touched"] = int((np.abs(rel) <= THR).sum())
        rec["n_FH_above"]   = int((rel >  THR).sum())
        rec["n_FH_below"]   = int((rel < -THR).sum())
    else:
        rec.update({"n_FH_touched":0, "n_FH_above":0, "n_FH_below":0})

    # Direction-aware "same/opp" naming:
    # LONG  same-dir = FL, opp-dir = FH
    # SHORT same-dir = FH, opp-dir = FL
    if d == "long":
        rec["n_same_touched"] = rec["n_FL_touched"]
        rec["n_same_above"]   = rec["n_FL_above"]
        rec["n_same_below"]   = rec["n_FL_below"]
        rec["n_opp_touched"]  = rec["n_FH_touched"]
        rec["n_opp_above"]    = rec["n_FH_above"]
        rec["n_opp_below"]    = rec["n_FH_below"]
    else:
        rec["n_same_touched"] = rec["n_FH_touched"]
        rec["n_same_above"]   = rec["n_FH_above"]
        rec["n_same_below"]   = rec["n_FH_below"]
        rec["n_opp_touched"]  = rec["n_FL_touched"]
        rec["n_opp_above"]    = rec["n_FL_above"]
        rec["n_opp_below"]    = rec["n_FL_below"]

    records.append(rec)

rdf = pd.DataFrame(records)
print(f"Records: {len(rdf):,}")
print(f"\nMean active VWAPs (FL): {rdf.n_FL_active.mean():.1f}  (FH): {rdf.n_FH_active.mean():.1f}")
print(f"Median n_same_touched: {rdf.n_same_touched.median()}  n_same_above: {rdf.n_same_above.median()}  n_same_below: {rdf.n_same_below.median()}")

base_w=(rdf.R==1).sum(); base_l=(rdf.R==-1).sum(); base_nt=rdf.touched.sum()
base_wr = base_w/base_nt*100
print(f"\nBaseline: N={len(rdf)} WR={base_wr:.1f}% Σ={base_w-base_l:+}R")


def show_mask(rdf, mask, label):
    inn = rdf[mask]; out = rdf[~mask]
    nin = len(inn); nout = len(out)
    wi = (inn.R==1).sum(); li = (inn.R==-1).sum()
    wo = (out.R==1).sum(); lo = (out.R==-1).sum()
    nti = inn.touched.sum(); nto = out.touched.sum()
    wr_i = wi/nti*100 if nti else 0
    wr_o = wo/nto*100 if nto else 0
    lift = wr_i - wr_o
    flag = "⭐" if lift >= 3 and nin >= 50 else ("✓" if lift >= 1 and nin >= 50 else "")
    print(f"{label:<46} N={nin:>5} WR={wr_i:>5.1f}% EV={(2*wr_i/100)-1:>+6.3f}R Σ={wi-li:>+5}R | out WR={wr_o:.1f}% Σ={wo-lo:+}R | {lift:+5.1f}pp {flag}")


print(f"\n{'='*120}")
print(f"COUNT-BASED FEATURES — same-direction D-fractal VWAPs (drop_lo for LONG / drop_hi for SHORT)")
print(f"{'='*120}")
for k in [1, 2, 3, 5]:
    show_mask(rdf, rdf.n_same_touched >= k, f"same-dir TOUCHED ≥{k} VWAPs ±0.5%")
print()
for k in [1, 2, 3, 5, 10]:
    show_mask(rdf, rdf.n_same_above >= k, f"same-dir ABOVE ≥{k} VWAPs (drop above VWAP)")
print()
for k in [1, 2, 3, 5, 10]:
    show_mask(rdf, rdf.n_same_below >= k, f"same-dir BELOW ≥{k} VWAPs (drop below VWAP)")

print(f"\n{'='*120}")
print(f"OPPOSITE-direction D-fractal VWAPs")
print(f"{'='*120}")
for k in [1, 2, 3]:
    show_mask(rdf, rdf.n_opp_touched >= k, f"opp-dir TOUCHED ≥{k} VWAPs ±0.5%")
for k in [1, 2, 5, 10]:
    show_mask(rdf, rdf.n_opp_below >= k, f"opp-dir BELOW ≥{k} VWAPs")

# ─── Ratio-based features ─────────────────────────────
print(f"\n{'='*120}")
print(f"RATIO / RELATIVE position")
print(f"{'='*120}")
# Bullish regime score: % of same-dir VWAPs that drop is ABOVE
rdf["frac_same_above"] = rdf.n_same_above / (rdf.n_same_above + rdf.n_same_below + rdf.n_same_touched).clip(lower=1)
for q in [0.5, 0.7, 0.9]:
    show_mask(rdf, rdf.frac_same_above >= q, f"≥{int(q*100)}% same-dir VWAPs ABOVE drop (regime hold)")
for q in [0.5, 0.7, 0.9]:
    show_mask(rdf, rdf.frac_same_above <= 1-q, f"≤{int((1-q)*100)}% same-dir VWAPs ABOVE (regime broken)")

# ─── B1 cross ────────────────────────────────────────
print(f"\n{'='*120}")
print(f"B1 × VWAP COUNT")
print(f"{'='*120}")
b1 = rdf[rdf.B1_aligned]
b1_nt = b1.touched.sum(); b1_w=(b1.R==1).sum(); b1_l=(b1.R==-1).sum()
b1_wr = b1_w/b1_nt*100 if b1_nt else 0
print(f"B1 baseline: N={len(b1)} WR={b1_wr:.1f}% Σ={b1_w-b1_l:+}R")
top_combos = []
for col, ks in [("n_same_touched",[1,2,3]), ("n_same_above",[5,10,20]),
                ("frac_same_above",[0.7,0.9])]:
    for k in ks:
        if col == "frac_same_above":
            mask = rdf.B1_aligned & (rdf[col] >= k)
        else:
            mask = rdf.B1_aligned & (rdf[col] >= k)
        combo = rdf[mask]
        if len(combo) < 30: continue
        nt = combo.touched.sum(); w=(combo.R==1).sum(); l=(combo.R==-1).sum()
        wr = w/nt*100 if nt else 0
        lift = wr - b1_wr
        flag = "⭐" if lift >= 2 else ("✓" if lift >= 0.5 else "")
        label = f"B1 + {col} ≥ {k}"
        print(f"{label:<35} N={len(combo):>4} WR={wr:>5.1f}% Σ={w-l:+5}R  (vs B1: {lift:+.1f}pp) {flag}")
        if lift >= 1:
            top_combos.append((label, len(combo), wr, lift))

# Save
out_path = pathlib.Path(__file__).parent.parent / "data/d_vwap_features.parquet"
rdf.to_parquet(out_path)
print(f"\nSaved: {out_path}")
print(f"Elapsed: {time.time()-t0:.1f}s")
