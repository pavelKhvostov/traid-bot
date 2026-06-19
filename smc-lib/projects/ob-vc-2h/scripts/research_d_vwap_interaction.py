"""Multi-canon VWAP interaction features (A/B/C/D) for 2h ob_vc.

Per same-direction D-fractal VWAP (90d age window), compute:

CANON A — Wick-sweep + recover
  LONG: drop_lo < VWAP_at_born  AND  cur.close > VWAP_at_born
  SHORT mirror.

CANON B — Zone-overlap (FVG zone contains VWAP)
  fvg_zone_lo ≤ VWAP_at_born ≤ fvg_zone_hi

CANON C — Touch+reject (wick to VWAP, body away)
  LONG: ANY of (prev, cur):  bar.low ≤ VWAP_at_born  AND  min(bar.open, bar.close) > VWAP_at_born
  SHORT mirror.

CANON D — Multi-bar history (recent tests + bounces)
  In last 5 closed 2h bars before born_ms:
    LONG: bar.low ≤ VWAP_at_bar_close  AND  min(bar.open, bar.close) > VWAP_at_bar_close
    Count #bars with successful test
  Per VWAP: D_score = count of test_reject events in lookback ≥ 1

Aggregate counts:
  n_A, n_B, n_C, n_D — # of same-dir VWAPs satisfying each canon (90d window)
  Also union/intersection.

Compare standalone + B1 cross.
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
AGE_DAYS = 90
AGE_MS = AGE_DAYS * 24 * 3600 * 1000
LOOKBACK_BARS = 5  # for canon D

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
cans_2h = to_candles(cans_d["2h"])
cans_1d = to_candles(cans_d["1d"])
bar2h_idx = {c.open_time: i for i, c in enumerate(cans_2h)}

# D fractals
fhs_1d, fls_1d = detect_williams_n2(cans_1d, n=N_FRACTAL)
FL_A = np.array([int(cans_1d[i + 1].open_time) for (i, _, _) in fls_1d if i + 1 < len(cans_1d)], dtype=np.int64)
FL_L = np.array([float(lvl) for (i, lvl, _) in fls_1d if i + 1 < len(cans_1d)], dtype=np.float64)
FH_A = np.array([int(cans_1d[i + 1].open_time) for (i, _, _) in fhs_1d if i + 1 < len(cans_1d)], dtype=np.int64)
FH_L = np.array([float(lvl) for (i, lvl, _) in fhs_1d if i + 1 < len(cans_1d)], dtype=np.float64)
idx_fl = np.argsort(FL_A); FL_A = FL_A[idx_fl]; FL_L = FL_L[idx_fl]
idx_fh = np.argsort(FH_A); FH_A = FH_A[idx_fh]; FH_L = FH_L[idx_fh]
print(f"D fractals: FL={len(FL_A)}  FH={len(FH_A)}")


def vwap_batch(anchors_ts: np.ndarray, target_ts: int) -> np.ndarray:
    if len(anchors_ts) == 0: return np.array([])
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


# ─── Load setups + FVG zone ───────────────────────────
df = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/bulkowski_features.parquet")
src = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")
g2h = src[src.htf == "2h"].copy()
g2h["has_15m"] = g2h.groupby(["direction","ob_cur_open_ms"])["ltf"].transform(
    lambda x: "15m" in set(x))
mask_lt = ((g2h.has_15m & (g2h.ltf=="15m")) | (~g2h.has_15m & (g2h.ltf=="20m")))
g2h = g2h[mask_lt].copy()

# Per setup: pick the FVG zone (top for LONG with n_FVG≥2, bottom for SHORT)
ob_setups = []
for (d, co), sub in g2h.groupby(["direction", "ob_cur_open_ms"]):
    nc = len(sub)
    if d == "long":
        cf = sub.sort_values("fvg_zone_hi", ascending=False).iloc[0]
    else:
        cf = sub.sort_values("fvg_zone_lo", ascending=True).iloc[0]
    ob_setups.append({
        "direction": d, "ob_cur_open_ms": int(co),
        "drop_lo": float(cf.drop_lo), "drop_hi": float(cf.drop_hi),
        "born_ms": int(cf.born_ms), "n_FVG": nc,
        "fvg_zone_lo": float(cf.fvg_zone_lo), "fvg_zone_hi": float(cf.fvg_zone_hi),
    })
ob_df = pd.DataFrame(ob_setups)
df_m = df.merge(ob_df, on=["direction", "born_ms"], how="left")
print(f"Merged: {len(df_m):,}  (drop+fvg cols: {df_m.fvg_zone_lo.notna().sum()})")


# ─── Per-setup feature computation ─────────────────────
def setup_features(born, d, drop, cur_close, prev, cur, fvg_lo, fvg_hi):
    """Return dict with A/B/C/D counts on same-direction VWAPs (90d window)."""
    lo = born - AGE_MS
    if d == "long":
        i_lo = int(np.searchsorted(FL_A, lo, side="left"))
        i_hi = int(np.searchsorted(FL_A, born, side="left"))
        a_sub = FL_A[i_lo:i_hi]
    else:
        i_lo = int(np.searchsorted(FH_A, lo, side="left"))
        i_hi = int(np.searchsorted(FH_A, born, side="left"))
        a_sub = FH_A[i_lo:i_hi]
    if len(a_sub) == 0:
        return {"n_A":0, "n_B":0, "n_C":0, "n_D":0, "n_active":0, "n_any":0,
                "n_AB":0, "n_AC":0, "n_BC":0, "n_ABC":0}
    vw = vwap_batch(a_sub, born)
    valid = ~np.isnan(vw)
    if not valid.any():
        return {"n_A":0, "n_B":0, "n_C":0, "n_D":0, "n_active":0, "n_any":0,
                "n_AB":0, "n_AC":0, "n_BC":0, "n_ABC":0}
    vw = vw[valid]
    n_active = len(vw)

    if d == "long":
        # CANON A — wick-sweep + recover
        m_A = (drop < vw) & (cur_close > vw)
        # CANON B — zone-overlap
        m_B = (fvg_lo <= vw) & (vw <= fvg_hi)
        # CANON C — touch+reject (any of prev/cur)
        prev_body_lo = min(prev.open, prev.close); cur_body_lo = min(cur.open, cur.close)
        m_C_prev = (prev.low <= vw) & (vw < prev_body_lo)
        m_C_cur  = (cur.low  <= vw) & (vw < cur_body_lo)
        m_C = m_C_prev | m_C_cur
    else:
        # SHORT mirror
        m_A = (drop > vw) & (cur_close < vw)
        m_B = (fvg_lo <= vw) & (vw <= fvg_hi)
        prev_body_hi = max(prev.open, prev.close); cur_body_hi = max(cur.open, cur.close)
        m_C_prev = (prev.high >= vw) & (vw > prev_body_hi)
        m_C_cur  = (cur.high  >= vw) & (vw > cur_body_hi)
        m_C = m_C_prev | m_C_cur

    # CANON D — multi-bar history (last 5 closed bars before born)
    # For each active VWAP, count bars in lookback where (LONG: low ≤ VWAP_at_close < body_lo)
    cur_idx = bar2h_idx.get(cur.open_time)
    m_D = np.zeros(len(vw), dtype=bool)
    if cur_idx is not None and cur_idx >= LOOKBACK_BARS + 1:
        anchors_active = a_sub[valid]
        for k in range(1, LOOKBACK_BARS + 1):
            b = cans_2h[cur_idx - 1 - k]  # k-th bar before prev
            vw_at_b = vwap_batch(anchors_active, int(b.open_time + 2*3600*1000 - 1))  # close-ish
            mask_v = ~np.isnan(vw_at_b)
            if not mask_v.any(): continue
            vv = vw_at_b
            if d == "long":
                bl = min(b.open, b.close)
                cond = (b.low <= vv) & (vv < bl)
            else:
                bh = max(b.open, b.close)
                cond = (b.high >= vv) & (vv > bh)
            m_D = m_D | (cond & mask_v)
    n_A = int(m_A.sum()); n_B = int(m_B.sum())
    n_C = int(m_C.sum()); n_D = int(m_D.sum())
    n_any = int((m_A | m_B | m_C | m_D).sum())
    n_AB = int((m_A & m_B).sum()); n_AC = int((m_A & m_C).sum())
    n_BC = int((m_B & m_C).sum()); n_ABC = int((m_A & m_B & m_C).sum())
    return {"n_A":n_A, "n_B":n_B, "n_C":n_C, "n_D":n_D,
            "n_active":n_active, "n_any":n_any,
            "n_AB":n_AB, "n_AC":n_AC, "n_BC":n_BC, "n_ABC":n_ABC}


print("Computing features (per setup)...")
records = []
skipped = 0
for _, r in df_m.iterrows():
    if pd.isna(r.ob_cur_open_ms) or pd.isna(r.fvg_zone_lo):
        skipped += 1; continue
    born = int(r.born_ms); d = r.direction
    co = int(r.ob_cur_open_ms)
    idx = bar2h_idx.get(co)
    if idx is None or idx < 1:
        skipped += 1; continue
    prev = cans_2h[idx - 1]; cur = cans_2h[idx]
    drop = float(r.drop_lo) if d == "long" else float(r.drop_hi)
    cur_close = float(cur.close)
    feats = setup_features(born, d, drop, cur_close, prev, cur, float(r.fvg_zone_lo), float(r.fvg_zone_hi))
    rec = {"born_ms": born, "direction": d, "t_id": r.t_id,
           "touched": r.touched, "R": r.R, "B1_aligned": r.B1_aligned}
    rec.update(feats)
    records.append(rec)
print(f"Records: {len(records):,}  skipped: {skipped}")

rdf = pd.DataFrame(records)


# ─── Report ────────────────────────────────────────────
def report_block(rdf, title):
    print(f"\n{'='*120}")
    print(f"{title}  (N={len(rdf):,})")
    print(f"{'='*120}")
    bw=(rdf.R==1).sum(); bl=(rdf.R==-1).sum(); bnt=rdf.touched.sum()
    bwr = bw/bnt*100 if bnt else 0
    b1 = rdf[rdf.B1_aligned]
    b1w=(b1.R==1).sum(); b1l=(b1.R==-1).sum(); b1nt=b1.touched.sum()
    b1wr = b1w/b1nt*100 if b1nt else 0
    print(f"baseline N={len(rdf)} WR={bwr:.1f}% Σ={bw-bl:+}R  |  B1 N={len(b1)} WR={b1wr:.1f}% Σ={b1w-b1l:+}R")
    print(f"mean n_active(same dir): {rdf.n_active.mean():.1f}")
    print(f"mean per-canon counts: A={rdf.n_A.mean():.2f} B={rdf.n_B.mean():.2f} C={rdf.n_C.mean():.2f} D={rdf.n_D.mean():.2f}")

    def stat(mask, lbl, ref):
        s = rdf[mask]
        if len(s)<20: print(f"  {lbl:<40} N={len(s)} (skip)"); return
        nt=s.touched.sum(); w=(s.R==1).sum(); l=(s.R==-1).sum()
        wr=w/nt*100 if nt else 0
        flag = "⭐" if wr - ref >= 2 else ("✓" if wr - ref >= 0.5 else "")
        print(f"  {lbl:<40} N={len(s):>4} WR={wr:>5.1f}% Σ={w-l:+4}R  ({wr-ref:+.1f}pp) {flag}")

    print("\nSTANDALONE per-canon:")
    for can in ("A","B","C","D"):
        for k in [1, 2, 3]:
            stat(rdf[f"n_{can}"] >= k, f"n_{can} ≥ {k}", bwr)

    print("\nSTANDALONE union/intersect:")
    stat(rdf.n_any >= 1, "n_any (A|B|C|D) ≥ 1", bwr)
    stat(rdf.n_any >= 2, "n_any (A|B|C|D) ≥ 2", bwr)
    for inter in ("n_AB","n_AC","n_BC","n_ABC"):
        stat(rdf[inter] >= 1, f"{inter} ≥ 1", bwr)

    print("\nB1 × per-canon:")
    for can in ("A","B","C","D"):
        for k in [1, 2, 3]:
            stat(rdf.B1_aligned & (rdf[f"n_{can}"] >= k), f"B1 + n_{can} ≥ {k}", b1wr)
    print("\nB1 × intersections:")
    stat(rdf.B1_aligned & (rdf.n_any >= 1), "B1 + n_any ≥ 1", b1wr)
    stat(rdf.B1_aligned & (rdf.n_any >= 2), "B1 + n_any ≥ 2", b1wr)
    for inter in ("n_AB","n_AC","n_BC","n_ABC"):
        stat(rdf.B1_aligned & (rdf[inter] >= 1), f"B1 + {inter} ≥ 1", b1wr)


report_block(rdf, "FULL 6y (2020-2026)")
report_block(rdf[rdf.born_ms >= CUT_2023].reset_index(drop=True), "SUBSET 2023-06-06+")

out_path = pathlib.Path(__file__).parent.parent / "data/d_vwap_interaction.parquet"
rdf.to_parquet(out_path)
print(f"\nSaved: {out_path}  Elapsed: {time.time()-t0:.1f}s")
