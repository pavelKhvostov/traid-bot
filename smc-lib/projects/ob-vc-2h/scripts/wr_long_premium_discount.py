"""Premium/Discount classification of drop_lo для LONG 2h ob_vc.

Canon (per AlexxxFlow study plan p.25-26):
  - Detect Swing structure on parent TF (Williams N=2 fractals)
  - Find most recent confirmed FL and FH before born_ms
  - Swing range = [last FL, last FH]
  - Fib 50% midpoint = (FL + FH) / 2
  - For LONG: drop_lo MUST be in DISCOUNT (≤ midpoint)
  - For SHORT: drop_hi MUST be in PREMIUM (≥ midpoint)

Test parent TFs: 4h, 6h, 12h, 1D, 3D.
Bucket drop_lo position (0 = bottom, 1 = top of swing):
  Deep Discount (0..0.3), Mid Discount (0.3..0.5),
  Mid Premium (0.5..0.7), Deep Premium (0.7..1.0+)
"""
import sys, pathlib, csv
import numpy as np
import pandas as pd
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import aggregate_all_tfs, to_candles, detect_williams_n2

CSV_1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
CUT = int(datetime(2023, 6, 6, tzinfo=timezone.utc).timestamp() * 1000)
N_FRACTAL = 2
HORIZON_MS = 14*24*3600*1000

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

# Detect Williams N=2 fractals on each parent TF
def get_fractals(cans):
    fhs, fls = detect_williams_n2(cans, n=N_FRACTAL)
    # Confirmation: cans[i+N_FRACTAL].open_time
    fls_data = [(int(cans[i+N_FRACTAL].open_time) if i+N_FRACTAL < len(cans) else None,
                 float(lvl)) for (i, lvl, _) in fls if i+N_FRACTAL < len(cans)]
    fhs_data = [(int(cans[i+N_FRACTAL].open_time) if i+N_FRACTAL < len(cans) else None,
                 float(lvl)) for (i, lvl, _) in fhs if i+N_FRACTAL < len(cans)]
    fls_data = sorted(fls_data, key=lambda x: x[0])
    fhs_data = sorted(fhs_data, key=lambda x: x[0])
    fl_ts = np.array([x[0] for x in fls_data], dtype=np.int64)
    fl_lvl = np.array([x[1] for x in fls_data], dtype=np.float64)
    fh_ts = np.array([x[0] for x in fhs_data], dtype=np.int64)
    fh_lvl = np.array([x[1] for x in fhs_data], dtype=np.float64)
    return fl_ts, fl_lvl, fh_ts, fh_lvl


TFs_to_test = [("4h", cans_d["4h"]), ("6h", cans_d["6h"]),
               ("12h", cans_d["12h"]), ("1d", cans_d["1d"]), ("3d", cans_d["3d"])]
FRACTALS = {}
for tf, raw in TFs_to_test:
    cans = to_candles(raw)
    FRACTALS[tf] = get_fractals(cans)
    print(f"{tf} FL={len(FRACTALS[tf][0])} FH={len(FRACTALS[tf][2])}")


def drop_position(tf: str, born_ms: int, drop_lo: float):
    """Return position of drop_lo in last swing on tf.
    0 = at swing low, 1 = at swing high.
    Returns None if no valid swing.
    """
    fl_ts, fl_lvl, fh_ts, fh_lvl = FRACTALS[tf]
    # Latest FL and FH confirmed before born_ms
    i_fl = int(np.searchsorted(fl_ts, born_ms, side="left")) - 1
    i_fh = int(np.searchsorted(fh_ts, born_ms, side="left")) - 1
    if i_fl < 0 or i_fh < 0: return None
    last_fl = fl_lvl[i_fl]; last_fh = fh_lvl[i_fh]
    if last_fh <= last_fl: return None  # inverted, no clean swing
    rng = last_fh - last_fl
    pos = (drop_lo - last_fl) / rng
    return float(pos)


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


# Load LONG ob_vc
df = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")
g2h = df[df.htf == "2h"].copy()
g2h["has_15m"] = g2h.groupby(["direction","ob_cur_open_ms"])["ltf"].transform(lambda x: "15m" in set(x))
mask_lt = ((g2h.has_15m & (g2h.ltf=="15m")) | (~g2h.has_15m & (g2h.ltf=="20m")))
g2h = g2h[mask_lt & (g2h.direction == "long")].copy()

records = []
for (d, co), sub in g2h.groupby(["direction","ob_cur_open_ms"]):
    co = int(co); born = int(sub.iloc[0].born_ms)
    nc = len(sub)
    cf = sub.sort_values("fvg_zone_hi", ascending=False).iloc[0]
    drop_lo = float(cf.drop_lo)
    fvg_hi = float(cf.fvg_zone_hi); fvg_lo = float(cf.fvg_zone_lo)
    dp = 0.8 if nc >= 2 else 0.2
    entry = fvg_hi - dp * (fvg_hi - fvg_lo)
    sl = drop_lo

    out = tbm_long(entry, sl, born)
    if out is None: continue
    R = 0; touched = "out" in out
    if touched:
        if out["out"] == "win": R = 1
        elif out["out"] == "loss": R = -1
    rec = {"born_ms": born, "R": R, "touched": touched}
    for tf, _ in TFs_to_test:
        pos = drop_position(tf, born, drop_lo)
        rec[f"pos_{tf}"] = pos
    records.append(rec)

rdf = pd.DataFrame(records)
print(f"\nLONG 2h ob_vc processed: {len(rdf)}")


def bucket_position(rdf, col):
    out = pd.cut(rdf[col], bins=[-1e9, 0, 0.3, 0.5, 0.7, 1.0, 1e9],
                 labels=["below_swing","deep_disc","mid_disc","mid_prem","deep_prem","above_swing"])
    return out


# Compute buckets
for tf, _ in TFs_to_test:
    rdf[f"bk_{tf}"] = bucket_position(rdf, f"pos_{tf}")


def analyze(df_local, label):
    print(f"\n{'='*100}")
    print(f"{label}")
    print(f"{'='*100}")
    bw=(df_local.R==1).sum(); bl=(df_local.R==-1).sum(); bnt=df_local.touched.sum()
    bwr = bw/bnt*100 if bnt else 0
    print(f"BASELINE: N={len(df_local)} WR={bwr:.1f}% Σ={bw-bl:+}R")
    for tf, _ in TFs_to_test:
        col = f"bk_{tf}"
        print(f"\n--- Parent {tf} drop_lo position ---")
        for b in ["below_swing","deep_disc","mid_disc","mid_prem","deep_prem","above_swing"]:
            s = df_local[df_local[col] == b]
            if len(s) < 10: continue
            nt=s.touched.sum(); w=(s.R==1).sum(); l=(s.R==-1).sum()
            wr = w/nt*100 if nt else 0
            lift = wr - bwr
            flag = "⭐" if lift >= 3 else ("✓" if lift >= 1 else "")
            print(f"  {b:<15} N={len(s):>4} WR={wr:>5.1f}% Σ={w-l:>+4}R ({lift:+.1f}pp) {flag}")


analyze(rdf, "FULL 6y LONG")
sub = rdf[rdf.born_ms >= CUT].copy()
analyze(sub, "SUBSET 2023-06-06+ LONG")

# Combine — best parent TF, Discount only
print(f"\n{'='*100}\nCOMBINED: drop_lo in Discount (≤ 50% Fib)\n{'='*100}")
for tf, _ in TFs_to_test:
    col = f"pos_{tf}"
    for label, df_l in [("FULL 6y", rdf), ("SUBSET 2023+", sub)]:
        s = df_l[df_l[col] <= 0.5]
        if len(s) < 20: continue
        nt=s.touched.sum(); w=(s.R==1).sum(); l=(s.R==-1).sum()
        wr = w/nt*100 if nt else 0
        bw_l=(df_l.R==1).sum(); bl_l=(df_l.R==-1).sum(); bnt_l=df_l.touched.sum()
        bwr_l = bw_l/bnt_l*100
        lift = wr - bwr_l
        flag = "⭐" if lift >= 3 else "✓" if lift >= 1 else ""
        print(f"  {label} Discount@{tf}: N={len(s):>4} WR={wr:>5.1f}% Σ={w-l:+}R  (lift {lift:+.1f}pp) {flag}")

# T1a check
TARGET = int(datetime(2026, 6, 5, 22, 0, tzinfo=timezone.utc).timestamp() * 1000)
t1a = rdf[rdf.born_ms == TARGET]
if len(t1a):
    print(f"\n=== T1a (drop_lo = 59131) position in each TF swing ===")
    r = t1a.iloc[0]
    for tf, _ in TFs_to_test:
        pos = r[f"pos_{tf}"]; bk = r[f"bk_{tf}"]
        if pd.isna(pos):
            print(f"  {tf}: no swing (FL or FH unresolved)")
        else:
            print(f"  {tf}: pos = {pos:.2f} → {bk}")
    print(f"  R = {r.R}")

# Save
out_path = pathlib.Path(__file__).parent.parent / "data/premium_discount_long.parquet"
rdf.to_parquet(out_path)
print(f"\nSaved: {out_path}")
