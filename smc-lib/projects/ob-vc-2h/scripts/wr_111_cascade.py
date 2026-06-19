"""Strategy 1.1.1 V2 cascade: 2h ob_vc must be nested inside a same-direction
macro ob_vc(HTF=D/12h, LTF=4h/6h) at born_ms.

Canon (per strategy-1-1-1-v2.md):
  - macro: ob_vc(HTF in {1d, 12h}, LTF in {4h, 6h})
  - macro.born_ms ≤ entry.born_ms
  - macro.valid_until_ms > entry.born_ms (still active)
  - macro.direction == entry.direction
  - entry.fvg_zone within macro.ob_zone (or ≥ 50% overlap)

Apply ONLY this filter — no other layers. Test on ALL 4036 2h ob_vc (LONG + SHORT).
"""
import sys, pathlib, csv
import numpy as np
import pandas as pd
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import aggregate_all_tfs, to_candles

CSV_1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
CUT = int(datetime(2023, 6, 6, tzinfo=timezone.utc).timestamp() * 1000)
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


# Load Phase 1.5 data
df = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")

# Macro candidates: htf in {1d, 12h} with ltf in {4h, 6h}
macro_df = df[((df.htf == "1d") | (df.htf == "12h")) &
              ((df.ltf == "4h") | (df.ltf == "6h"))].copy()
# Unique per (direction, ob_cur_open_ms, htf, ltf)
macro = macro_df.groupby(["htf","ltf","direction","ob_cur_open_ms"]).agg(
    born_ms=("born_ms","first"),
    ob_zone_lo=("ob_zone_lo","first"),
    ob_zone_hi=("ob_zone_hi","first"),
    valid_until_ms=("valid_until_ms","first"),
).reset_index()
print(f"Macro candidates (D/12h × 4h/6h LTF): {len(macro)}")
print(f"  By htf+ltf: \n{macro.groupby(['htf','ltf']).size()}")
print(f"  By direction: {macro.direction.value_counts().to_dict()}")

# Pre-sort macro by direction + born_ms
macros_by_dir = {}
for d in ["long","short"]:
    sub = macro[macro.direction == d].sort_values("born_ms").reset_index(drop=True)
    macros_by_dir[d] = {
        "born": sub.born_ms.values.astype(np.int64),
        "vuntil": sub.valid_until_ms.values.astype(np.int64),
        "zlo": sub.ob_zone_lo.values.astype(np.float64),
        "zhi": sub.ob_zone_hi.values.astype(np.float64),
        "htf": sub.htf.values,
        "ltf": sub.ltf.values,
    }
print(f"Macro by direction: long={len(macros_by_dir['long'])}  short={len(macros_by_dir['short'])}")


def has_macro_cascade(direction: str, born_ms: int, entry_lo: float, entry_hi: float,
                     min_overlap_pct: float = 0.0):
    """Check if 2h ob_vc has a parent macro ob_vc.
    Returns dict with count, htfs found.
    min_overlap_pct: 0 = any overlap; 0.5 = entry.zone covers ≥ 50% of macro overlap
    """
    M = macros_by_dir[direction]
    active = (M["born"] <= born_ms) & (M["vuntil"] > born_ms)
    if not active.any():
        return {"count": 0, "htfs": set(), "ltfs": set(), "best_overlap": 0.0}

    # Zone overlap: max(zlo, entry_lo) <= min(zhi, entry_hi)
    zlo_act = M["zlo"][active]; zhi_act = M["zhi"][active]
    overlap_lo = np.maximum(zlo_act, entry_lo)
    overlap_hi = np.minimum(zhi_act, entry_hi)
    overlap = overlap_hi - overlap_lo  # positive if overlap
    entry_width = entry_hi - entry_lo
    overlap_pct = np.where(entry_width > 0, np.clip(overlap, 0, None) / entry_width, 0)
    valid = overlap > 0
    if min_overlap_pct > 0:
        valid = valid & (overlap_pct >= min_overlap_pct)
    if not valid.any():
        return {"count": 0, "htfs": set(), "ltfs": set(), "best_overlap": 0.0}
    htfs = set(M["htf"][active][valid])
    ltfs = set(M["ltf"][active][valid])
    return {"count": int(valid.sum()), "htfs": htfs, "ltfs": ltfs,
            "best_overlap": float(overlap_pct[valid].max())}


# Process ALL 4036 2h ob_vc
g2h = df[df.htf == "2h"].copy()
g2h["has_15m"] = g2h.groupby(["direction","ob_cur_open_ms"])["ltf"].transform(lambda x: "15m" in set(x))
mask_lt = ((g2h.has_15m & (g2h.ltf=="15m")) | (~g2h.has_15m & (g2h.ltf=="20m")))
g2h = g2h[mask_lt].copy()

records = []
for (d, co), sub in g2h.groupby(["direction","ob_cur_open_ms"]):
    born = int(sub.iloc[0].born_ms)
    nc = len(sub)
    if d == "long":
        cf = sub.sort_values("fvg_zone_hi", ascending=False).iloc[0]
        drop_lo = float(cf.drop_lo); drop_hi = float(cf.drop_hi)
        fvg_hi = float(cf.fvg_zone_hi); fvg_lo = float(cf.fvg_zone_lo)
        dp = 0.8 if nc >= 2 else 0.2
        entry = fvg_hi - dp * (fvg_hi - fvg_lo); sl = drop_lo
    else:
        cf = sub.sort_values("fvg_zone_lo", ascending=True).iloc[0]
        drop_lo = float(cf.drop_lo); drop_hi = float(cf.drop_hi)
        fvg_hi = float(cf.fvg_zone_hi); fvg_lo = float(cf.fvg_zone_lo)
        dp = 0.8 if nc >= 2 else 0.2
        entry = fvg_lo + dp * (fvg_hi - fvg_lo); sl = drop_hi

    # Entry zone for cascade check = fvg zone
    cascade_any = has_macro_cascade(d, born, fvg_lo, fvg_hi, min_overlap_pct=0)
    cascade_50 = has_macro_cascade(d, born, fvg_lo, fvg_hi, min_overlap_pct=0.5)
    cascade_100 = has_macro_cascade(d, born, fvg_lo, fvg_hi, min_overlap_pct=1.0)

    out = tbm(entry, sl, born, d)
    if out is None: continue
    R = 0; touched = "out" in out
    if touched:
        if out["out"] == "win": R = 1
        elif out["out"] == "loss": R = -1
    records.append({
        "born_ms": born, "direction": d, "n_FVG": nc,
        "touched": touched, "R": R,
        "macro_any": cascade_any["count"] > 0,
        "macro_50": cascade_50["count"] > 0,
        "macro_100": cascade_100["count"] > 0,
        "macro_count_any": cascade_any["count"],
        "macro_best_overlap": cascade_any["best_overlap"],
        "macro_12h": "12h" in cascade_any["htfs"],
        "macro_1d": "1d" in cascade_any["htfs"],
        "macro_both": ("12h" in cascade_any["htfs"]) and ("1d" in cascade_any["htfs"]),
    })

rdf = pd.DataFrame(records)
print(f"\nProcessed: {len(rdf)}")
print(f"  LONG: {(rdf.direction=='long').sum()}")
print(f"  SHORT: {(rdf.direction=='short').sum()}")
print(f"  macro_any coverage: {rdf.macro_any.sum()} ({rdf.macro_any.sum()/len(rdf)*100:.1f}%)")
print(f"  macro_50 coverage:  {rdf.macro_50.sum()} ({rdf.macro_50.sum()/len(rdf)*100:.1f}%)")
print(f"  macro_100 coverage: {rdf.macro_100.sum()} ({rdf.macro_100.sum()/len(rdf)*100:.1f}%)")


def stat(df_l, mask, lbl, ref):
    s = df_l[mask]
    if len(s) < 10: return
    nt=s.touched.sum(); w=(s.R==1).sum(); l=(s.R==-1).sum()
    wr = w/nt*100 if nt else 0
    lift = wr - ref
    flag = "⭐" if lift >= 3 else ("✓" if lift >= 1 else "")
    print(f"  {lbl:<45} N={len(s):>4} touch={nt:>4} W={w:>4} L={l:>4} WR={wr:>5.1f}% Σ={w-l:>+4}R ({lift:+.1f}pp) {flag}")


def report(df_l, title):
    print(f"\n{'='*100}\n{title}\n{'='*100}")
    bw=(df_l.R==1).sum(); bl=(df_l.R==-1).sum(); bnt=df_l.touched.sum()
    bwr = bw/bnt*100 if bnt else 0
    print(f"BASELINE: N={len(df_l)} WR={bwr:.1f}% Σ={bw-bl:+}R")
    stat(df_l, df_l.macro_any, "macro ANY overlap (D/12h + 4h/6h)", bwr)
    stat(df_l, df_l.macro_50, "macro ≥50% overlap", bwr)
    stat(df_l, df_l.macro_100, "macro 100% overlap (entry ⊆ macro)", bwr)
    stat(df_l, ~df_l.macro_any, "NO macro at all", bwr)
    stat(df_l, df_l.macro_1d, "macro 1D present (any LTF)", bwr)
    stat(df_l, df_l.macro_12h, "macro 12h present (any LTF)", bwr)
    stat(df_l, df_l.macro_both, "macro 1D AND 12h both", bwr)


# All directions
report(rdf, "ALL 4036 (LONG+SHORT)")
report(rdf[rdf.direction=="long"], "LONG only")
report(rdf[rdf.direction=="short"], "SHORT only")

# Subset 2023+
sub = rdf[rdf.born_ms >= CUT].copy()
report(sub, "SUBSET 2023-06-06+ (LONG+SHORT)")
report(sub[sub.direction=="long"], "SUBSET 2023+ LONG")
report(sub[sub.direction=="short"], "SUBSET 2023+ SHORT")

# T1a check
TARGET = int(datetime(2026, 6, 5, 22, 0, tzinfo=timezone.utc).timestamp() * 1000)
t1a = rdf[(rdf.direction=="long") & (rdf.born_ms == TARGET)]
if len(t1a):
    r = t1a.iloc[0]
    print(f"\n=== T1a (LONG cur 2026-06-05 23:00 МСК) ===")
    print(f"  macro_any: {r.macro_any}  macro_50: {r.macro_50}  macro_100: {r.macro_100}")
    print(f"  htfs: 1D={r.macro_1d}, 12h={r.macro_12h}")
    print(f"  best overlap: {r.macro_best_overlap*100:.1f}%")
    print(f"  R = {r.R}")

# Save
out_path = pathlib.Path(__file__).parent.parent / "data/cascade_111.parquet"
rdf.to_parquet(out_path)
print(f"\nSaved: {out_path}")
