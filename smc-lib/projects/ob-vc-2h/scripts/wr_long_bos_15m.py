"""WR for LONG 2h ob_vc: filter where 15m BOS (Break of Structure) up happened
during formation (between prev_2h.open and cur_2h.close = born_ms).

BOS LONG canon:
  - Find latest 15m FH (Williams N=2) confirmed before prev_2h.open
  - Check if any 15m close between prev_open and born_ms exceeded that FH level
  - If yes → LONG BOS on 15m

Test ALL 2034 LONG 2h ob_vc, then combine with prior filters.
"""
import sys, pathlib, csv
import numpy as np
import pandas as pd
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import aggregate_all_tfs, to_candles, detect_williams_n2

CSV_1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
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
cans_15m = to_candles(cans_d["15m"])
bar2h_idx = {c.open_time: i for i, c in enumerate(cans_2h)}

# 15m Williams N=2 FHs
fhs_15m, _ = detect_williams_n2(cans_15m, n=2)
print(f"15m bars: {len(cans_15m):,}  15m FHs: {len(fhs_15m):,}")
# (i, level, ts_at_i_open)
# Anchor for "fresh" = i+2 close = (i+2)*15m + open_time

fh_arr = np.array([(int(cans_15m[i+2].open_time) if i+2 < len(cans_15m) else int(cans_15m[i].open_time),
                    float(lvl)) for (i, lvl, _) in fhs_15m if i+2 < len(cans_15m)],
                  dtype=np.float64)
# columns: confirm_ts, level
fh_confs = fh_arr[:, 0].astype(np.int64)
fh_levels = fh_arr[:, 1]
# Sort by confirm_ts
order = np.argsort(fh_confs)
fh_confs = fh_confs[order]
fh_levels = fh_levels[order]


def latest_fresh_fh(prev_open_ms: int):
    """Find the most recent 15m FH confirmed before prev_open_ms that is also still
    'fresh' (no prior close has broken above it before prev_open_ms).

    Simplest valid version: latest FH with confirm_ts < prev_open_ms.
    """
    idx = int(np.searchsorted(fh_confs, prev_open_ms, side="left")) - 1
    if idx < 0: return None
    return float(fh_levels[idx]), int(fh_confs[idx])


# Pre-build 15m close array (sorted by open_time)
ts_15m = np.array([c.open_time for c in cans_15m], dtype=np.int64)
c_15m = np.array([c.close for c in cans_15m], dtype=np.float64)
TF_15M = 15 * 60 * 1000


def bos_long_15m(prev_open_ms: int, born_ms: int):
    """Did 15m BOS up happen between prev_open and born_ms?

    Find latest 15m FH (confirmed before prev_open). Check if any 15m close in
    [prev_open, born_ms] exceeded that FH level.
    """
    fh = latest_fresh_fh(prev_open_ms)
    if fh is None: return False, None
    lvl, conf_ts = fh
    # Range of 15m bars in [prev_open, born_ms]
    i_lo = int(np.searchsorted(ts_15m, prev_open_ms, side="left"))
    i_hi = int(np.searchsorted(ts_15m, born_ms, side="right"))
    if i_hi <= i_lo: return False, lvl
    closes = c_15m[i_lo:i_hi]
    return bool((closes > lvl).any()), lvl


def tbm(entry, sl, born, d):
    if d == "long":
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
        return None  # LONG only
    if tp1r != -1 and (slr == -1 or tp1r <= slr): return {"out": "win"}
    elif slr != -1: return {"out": "loss"}
    return {"out": "timeout"}


# Load 2h LONG ob_vc — ALL 2034
df = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")
g2h = df[df.htf == "2h"].copy()
g2h["has_15m"] = g2h.groupby(["direction","ob_cur_open_ms"])["ltf"].transform(lambda x: "15m" in set(x))
mask_lt = ((g2h.has_15m & (g2h.ltf=="15m")) | (~g2h.has_15m & (g2h.ltf=="20m")))
g2h = g2h[mask_lt & (g2h.direction == "long")].copy()

records = []
for (d, co), sub in g2h.groupby(["direction","ob_cur_open_ms"]):
    born = int(sub.iloc[0].born_ms)
    nc = len(sub)
    cf = sub.sort_values("fvg_zone_hi", ascending=False).iloc[0]
    drop_lo = float(cf.drop_lo)
    fvg_hi = float(cf.fvg_zone_hi); fvg_lo = float(cf.fvg_zone_lo)
    dp = 0.8 if nc >= 2 else 0.2
    entry = fvg_hi - dp * (fvg_hi - fvg_lo)
    sl = drop_lo

    cur_open_ms = int(co)
    prev_open_ms = cur_open_ms - 2*3600*1000

    bos, fh_lvl = bos_long_15m(prev_open_ms, born)

    out = tbm(entry, sl, born, "long")
    if out is None: continue
    R = 0; touched = "out" in out
    if touched:
        if out["out"] == "win": R = 1
        elif out["out"] == "loss": R = -1
    records.append({
        "born_ms": born, "n_FVG": nc, "bos_15m_long": bos,
        "touched": touched, "R": R,
    })

rdf = pd.DataFrame(records)
print(f"\nLONG 2h ob_vc processed: {len(rdf):,}")
print(f"  BOS 15m long fired: {rdf.bos_15m_long.sum()} ({rdf.bos_15m_long.sum()/len(rdf)*100:.1f}%)")

def stat(mask, lbl, ref=None):
    s = rdf[mask]
    if len(s) < 10: print(f"  {lbl:<40} N={len(s)} (skip)"); return
    nt=s.touched.sum(); w=(s.R==1).sum(); l=(s.R==-1).sum()
    wr = w/nt*100 if nt else 0
    lift = (wr - ref) if ref else 0
    flag = "⭐" if lift >= 2 else ("✓" if lift >= 0.5 else "")
    suffix = f" ({lift:+.1f}pp) {flag}" if ref else ""
    print(f"  {lbl:<40} N={len(s):>4} touch={nt:>4} W={w:>4} L={l:>4} WR={wr:>5.1f}% Σ={w-l:>+4}R{suffix}")

print(f"\nWR results:")
bw = (rdf.R==1).sum(); bl = (rdf.R==-1).sum(); bnt = rdf.touched.sum()
base_wr = bw/bnt*100
print(f"  BASELINE LONG               N={len(rdf):>4} WR={base_wr:.1f}% Σ={bw-bl:+}R")
stat(rdf.bos_15m_long, "BOS 15m long fires", base_wr)
stat(~rdf.bos_15m_long, "BOS 15m long NOT fires", base_wr)

# Test full window AND subset 2023+
CUT = int(datetime(2023, 6, 6, tzinfo=timezone.utc).timestamp() * 1000)
sub = rdf[rdf.born_ms >= CUT]
print(f"\n=== Subset 2023-06-06+ (N={len(sub)}) ===")
sbw=(sub.R==1).sum(); sbl=(sub.R==-1).sum(); sbnt=sub.touched.sum()
sbwr = sbw/sbnt*100 if sbnt else 0
print(f"  BASELINE LONG subset        N={len(sub):>4} WR={sbwr:.1f}% Σ={sbw-sbl:+}R")
def stat_s(mask, lbl, ref):
    s = sub[mask]
    if len(s) < 10: print(f"  {lbl:<40} N={len(s)} (skip)"); return
    nt=s.touched.sum(); w=(s.R==1).sum(); l=(s.R==-1).sum()
    wr = w/nt*100 if nt else 0
    lift = wr - ref
    flag = "⭐" if lift >= 2 else ("✓" if lift >= 0.5 else "")
    print(f"  {lbl:<40} N={len(s):>4} WR={wr:>5.1f}% Σ={w-l:+4}R ({lift:+.1f}pp) {flag}")
stat_s(sub.bos_15m_long, "BOS 15m long fires", sbwr)
stat_s(~sub.bos_15m_long, "BOS 15m long NOT fires", sbwr)

# Combine with parent HTF features (saved earlier)
print(f"\n{'='*90}")
print(f"COMBINE BOS_15m + Parent HTF")
print(f"{'='*90}")
ph = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/parent_htf_features.parquet")
ph = ph[ph.direction == "long"]
mer = rdf.merge(ph[["born_ms","parent_4h","parent_6h","parent_any","parent_both"]],
                on="born_ms", how="inner")
print(f"Merged: {len(mer)}")
bw = (mer.R==1).sum(); bl = (mer.R==-1).sum(); bnt = mer.touched.sum()
bwr = bw/bnt*100 if bnt else 0
print(f"  BASELINE merged             N={len(mer):>4} WR={bwr:.1f}% Σ={bw-bl:+}R")

def stat_m(mask, lbl):
    s = mer[mask]
    if len(s) < 10: print(f"  {lbl:<45} N={len(s)} (skip)"); return
    nt=s.touched.sum(); w=(s.R==1).sum(); l=(s.R==-1).sum()
    wr = w/nt*100 if nt else 0
    lift = wr - bwr
    flag = "⭐" if lift >= 2 else ("✓" if lift >= 0.5 else "")
    print(f"  {lbl:<45} N={len(s):>4} WR={wr:>5.1f}% Σ={w-l:+4}R ({lift:+.1f}pp) {flag}")

stat_m(mer.bos_15m_long, "BOS_15m fires")
stat_m(mer.parent_any, "Parent 4h/6h")
stat_m(mer.bos_15m_long & mer.parent_4h, "BOS_15m AND Parent_4h")
stat_m(mer.bos_15m_long & mer.parent_6h, "BOS_15m AND Parent_6h")
stat_m(mer.bos_15m_long & mer.parent_any, "BOS_15m AND Parent_any")
stat_m(mer.bos_15m_long & mer.parent_both, "BOS_15m AND Parent_4h AND Parent_6h")

# Subset
print(f"\n--- Subset 2023-06-06+ ---")
mer_s = mer[mer.born_ms >= CUT]
bw = (mer_s.R==1).sum(); bl = (mer_s.R==-1).sum(); bnt = mer_s.touched.sum()
bwr = bw/bnt*100 if bnt else 0
print(f"  BASELINE subset             N={len(mer_s):>4} WR={bwr:.1f}%")
def stat_ms(mask, lbl):
    s = mer_s[mask]
    if len(s) < 10: print(f"  {lbl:<45} N={len(s)} (skip)"); return
    nt=s.touched.sum(); w=(s.R==1).sum(); l=(s.R==-1).sum()
    wr = w/nt*100 if nt else 0
    lift = wr - bwr
    flag = "⭐" if lift >= 2 else ("✓" if lift >= 0.5 else "")
    print(f"  {lbl:<45} N={len(s):>4} WR={wr:>5.1f}% Σ={w-l:+4}R ({lift:+.1f}pp) {flag}")
stat_ms(mer_s.bos_15m_long, "BOS_15m fires")
stat_ms(mer_s.parent_any, "Parent any")
stat_ms(mer_s.bos_15m_long & mer_s.parent_any, "BOS_15m AND Parent_any")
stat_ms(mer_s.bos_15m_long & mer_s.parent_both, "BOS_15m AND Parent_both")
