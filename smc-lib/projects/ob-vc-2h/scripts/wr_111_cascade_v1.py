"""Strategy 1.1.1 v1 cascade — proper nested zones check for 2h ob_vc.

NESTING:
  OB-1d/12h ⊇ FVG-4h/6h ⊇ 2h.OB ⊇ FVG-15m/20m (last is in our canon already)

Detectors (simple, NOT canon ob_vc 9 conditions):
  OB (2-bar):
    LONG:  prev.close < prev.open AND cur.close > prev.open
           zone = [min(prev.low, cur.low), prev.open]
    SHORT mirror.
  FVG (3-bar gap):
    LONG:  c0.high < c2.low   zone = [c0.high, c2.low]
    SHORT mirror.

Mitigation check:
  OB-macro LONG: low never < ob_zone_lo after cur close
  FVG-macro LONG: low never < fvg_zone_lo after c2 close (50%+ fill = mitigated)

Per 2h ob_vc setup at born_ms:
  L1 (basic): 2h.OB overlap with active FVG-4h/6h (same direction)
  L2 (cascade): + FVG-macro overlap with active OB-1d/12h
  L3 (strict): + 100% containment at each layer
"""
import sys, pathlib, csv, time
import numpy as np
import pandas as pd
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import aggregate_all_tfs, to_candles

CSV_1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
CUT = int(datetime(2023, 6, 6, tzinfo=timezone.utc).timestamp() * 1000)
HORIZON_MS = 14*24*3600*1000
VALIDITY_MS = 14*24*3600*1000  # macro valid for 14 days max

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
cans_4h = to_candles(cans_d["4h"])
cans_6h = to_candles(cans_d["6h"])
cans_12h = to_candles(cans_d["12h"])
cans_1d = to_candles(cans_d["1d"])
cans_2h = to_candles(cans_d["2h"])
bar2h_idx = {c.open_time: i for i, c in enumerate(cans_2h)}


def detect_simple_fvgs(cans, direction):
    """3-bar FVG. LONG: c0.high < c2.low → [c0.high, c2.low]."""
    out = []
    for i in range(2, len(cans)):
        c0 = cans[i-2]; c2 = cans[i]
        if direction == "long" and c0.high < c2.low:
            out.append({
                "c0_open": int(c0.open_time), "c2_close": int(c2.open_time) + (cans[1].open_time - cans[0].open_time),
                "born": int(c2.open_time) + (cans[1].open_time - cans[0].open_time),
                "zone_lo": float(c0.high), "zone_hi": float(c2.low),
            })
        elif direction == "short" and c0.low > c2.high:
            out.append({
                "c0_open": int(c0.open_time), "c2_close": int(c2.open_time) + (cans[1].open_time - cans[0].open_time),
                "born": int(c2.open_time) + (cans[1].open_time - cans[0].open_time),
                "zone_lo": float(c2.high), "zone_hi": float(c0.low),
            })
    return out


def detect_simple_obs(cans, direction):
    """2-bar OB."""
    out = []
    for i in range(1, len(cans)):
        prev = cans[i-1]; cur = cans[i]
        if direction == "long" and prev.close < prev.open and cur.close > prev.open:
            out.append({
                "prev_open": int(prev.open_time), "cur_open": int(cur.open_time),
                "born": int(cur.open_time) + (cans[1].open_time - cans[0].open_time),
                "zone_lo": float(min(prev.low, cur.low)), "zone_hi": float(prev.open),
            })
        elif direction == "short" and prev.close > prev.open and cur.close < prev.open:
            out.append({
                "prev_open": int(prev.open_time), "cur_open": int(cur.open_time),
                "born": int(cur.open_time) + (cans[1].open_time - cans[0].open_time),
                "zone_lo": float(prev.open), "zone_hi": float(max(prev.high, cur.high)),
            })
    return out


# Pre-detect FVGs and OBs per TF and direction
print("Detecting macro structures...")
FVG_4h = {"long": detect_simple_fvgs(cans_4h, "long"), "short": detect_simple_fvgs(cans_4h, "short")}
FVG_6h = {"long": detect_simple_fvgs(cans_6h, "long"), "short": detect_simple_fvgs(cans_6h, "short")}
OB_12h = {"long": detect_simple_obs(cans_12h, "long"), "short": detect_simple_obs(cans_12h, "short")}
OB_1d = {"long": detect_simple_obs(cans_1d, "long"), "short": detect_simple_obs(cans_1d, "short")}
print(f"  FVG-4h:  long={len(FVG_4h['long'])}  short={len(FVG_4h['short'])}")
print(f"  FVG-6h:  long={len(FVG_6h['long'])}  short={len(FVG_6h['short'])}")
print(f"  OB-12h:  long={len(OB_12h['long'])}  short={len(OB_12h['short'])}")
print(f"  OB-1d:   long={len(OB_1d['long'])}  short={len(OB_1d['short'])}")


def is_mitigated_long(zone_lo: float, born: int, check_until: int) -> bool:
    """LONG zone mitigated if any 1m low ≤ zone_lo (zone filled bottom) in window."""
    i_s = int(np.searchsorted(ts_1m, born, side="left"))
    i_e = int(np.searchsorted(ts_1m, check_until, side="right"))
    if i_e <= i_s: return False
    return bool((l_1m[i_s:i_e] <= zone_lo).any())


def is_mitigated_short(zone_hi: float, born: int, check_until: int) -> bool:
    i_s = int(np.searchsorted(ts_1m, born, side="left"))
    i_e = int(np.searchsorted(ts_1m, check_until, side="right"))
    if i_e <= i_s: return False
    return bool((h_1m[i_s:i_e] >= zone_hi).any())


def find_active_macro(macros: list, direction: str, born_ms: int):
    """Return list of macros active (born < born_ms, not mitigated, within validity)."""
    active = []
    for m in macros:
        if m["born"] >= born_ms: continue
        if born_ms - m["born"] > VALIDITY_MS: continue
        if direction == "long":
            if is_mitigated_long(m["zone_lo"], m["born"], born_ms): continue
        else:
            if is_mitigated_short(m["zone_hi"], m["born"], born_ms): continue
        active.append(m)
    return active


def zone_overlap_pct(z1_lo, z1_hi, z2_lo, z2_hi):
    """% of z1 covered by z2 (overlap / z1_width)."""
    lo = max(z1_lo, z2_lo); hi = min(z1_hi, z2_hi)
    if hi <= lo: return 0.0
    w1 = z1_hi - z1_lo
    return (hi - lo) / w1 if w1 > 0 else 0.0


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


# Load 2h ob_vc — ALL 4036
df = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")
g2h = df[df.htf == "2h"].copy()
g2h["has_15m"] = g2h.groupby(["direction","ob_cur_open_ms"])["ltf"].transform(lambda x: "15m" in set(x))
mask_lt = ((g2h.has_15m & (g2h.ltf=="15m")) | (~g2h.has_15m & (g2h.ltf=="20m")))
g2h = g2h[mask_lt].copy()

print(f"\nProcessing 4036 setups...")
records = []
for (d, co), sub in g2h.groupby(["direction","ob_cur_open_ms"]):
    co = int(co)
    born = int(sub.iloc[0].born_ms)
    nc = len(sub)
    cf = sub.sort_values("fvg_zone_hi" if d == "long" else "fvg_zone_lo",
                          ascending=(d != "long")).iloc[0]
    # Our 2h OB zone
    ob_lo = float(cf.ob_zone_lo); ob_hi = float(cf.ob_zone_hi)
    # Entry / SL
    fvg_hi = float(cf.fvg_zone_hi); fvg_lo = float(cf.fvg_zone_lo)
    dp = 0.8 if nc >= 2 else 0.2
    if d == "long":
        entry = fvg_hi - dp * (fvg_hi - fvg_lo); sl = float(cf.drop_lo)
    else:
        entry = fvg_lo + dp * (fvg_hi - fvg_lo); sl = float(cf.drop_hi)

    # Find active macro FVG (4h or 6h) where our 2h.OB-zone overlaps
    active_fvg_4h = find_active_macro(FVG_4h[d], d, born)
    active_fvg_6h = find_active_macro(FVG_6h[d], d, born)
    # Filter to those overlapping with 2h.OB (≥30% by default; track separately)
    fvg_matches_50 = []
    for m in active_fvg_4h + active_fvg_6h:
        ov = zone_overlap_pct(ob_lo, ob_hi, m["zone_lo"], m["zone_hi"])
        if ov >= 0.5:
            fvg_matches_50.append({**m, "_overlap": ov})
    fvg_matches_any = []
    for m in active_fvg_4h + active_fvg_6h:
        ov = zone_overlap_pct(ob_lo, ob_hi, m["zone_lo"], m["zone_hi"])
        if ov > 0:
            fvg_matches_any.append({**m, "_overlap": ov})

    # L1 has FVG-macro
    L1 = len(fvg_matches_any) > 0
    L1_50 = len(fvg_matches_50) > 0

    # L2: + has OB-macro (1d/12h) where FVG-macro is inside it
    active_ob_12h = find_active_macro(OB_12h[d], d, born)
    active_ob_1d = find_active_macro(OB_1d[d], d, born)
    L2 = False; L2_50 = False
    for fvg_m in fvg_matches_any:
        for ob_m in active_ob_12h + active_ob_1d:
            ov_inner = zone_overlap_pct(fvg_m["zone_lo"], fvg_m["zone_hi"],
                                        ob_m["zone_lo"], ob_m["zone_hi"])
            if ov_inner > 0:
                L2 = True
                if ov_inner >= 0.5 and fvg_m["_overlap"] >= 0.5:
                    L2_50 = True
                    break
        if L2_50: break

    # L3: full nesting at 100% containment
    L3 = False
    for fvg_m in fvg_matches_any:
        if fvg_m["_overlap"] < 1.0: continue  # 2h.OB fully inside FVG-macro
        for ob_m in active_ob_12h + active_ob_1d:
            ov_inner = zone_overlap_pct(fvg_m["zone_lo"], fvg_m["zone_hi"],
                                        ob_m["zone_lo"], ob_m["zone_hi"])
            if ov_inner >= 1.0:
                L3 = True; break
        if L3: break

    # TBM
    out = tbm(entry, sl, born, d)
    if out is None: continue
    R = 0; touched = "out" in out
    if touched:
        if out["out"] == "win": R = 1
        elif out["out"] == "loss": R = -1
    records.append({
        "born_ms": born, "direction": d, "n_FVG": nc,
        "touched": touched, "R": R,
        "L1_any": L1, "L1_50": L1_50,
        "L2_any": L2, "L2_50": L2_50, "L3_strict": L3,
    })

rdf = pd.DataFrame(records)
print(f"Processed: {len(rdf)}")


def stat(df_l, mask, lbl, ref):
    s = df_l[mask]
    if len(s) < 10: return
    nt=s.touched.sum(); w=(s.R==1).sum(); l=(s.R==-1).sum()
    wr = w/nt*100 if nt else 0
    lift = wr - ref
    flag = "⭐" if lift >= 3 else ("✓" if lift >= 1 else "")
    print(f"  {lbl:<55} N={len(s):>4} touch={nt:>4} W={w:>3} L={l:>3} WR={wr:>5.1f}% Σ={w-l:>+4}R ({lift:+.1f}pp) {flag}")


def report(df_l, title):
    print(f"\n{'='*100}\n{title}\n{'='*100}")
    bw=(df_l.R==1).sum(); bl=(df_l.R==-1).sum(); bnt=df_l.touched.sum()
    bwr = bw/bnt*100 if bnt else 0
    print(f"BASELINE: N={len(df_l)} WR={bwr:.1f}% Σ={bw-bl:+}R")
    stat(df_l, df_l.L1_any, "L1: 2h.OB ∩ FVG-4h/6h (any overlap)", bwr)
    stat(df_l, df_l.L1_50, "L1: 2h.OB in FVG-4h/6h (≥50% overlap)", bwr)
    stat(df_l, df_l.L2_any, "L2: + FVG-macro ∩ OB-1d/12h (any)", bwr)
    stat(df_l, df_l.L2_50, "L2: + FVG-macro in OB-1d/12h (≥50%)", bwr)
    stat(df_l, df_l.L3_strict, "L3: STRICT 100% nested cascade", bwr)
    stat(df_l, ~df_l.L1_any, "NO L1 (no FVG-macro contains 2h.OB)", bwr)
    stat(df_l, ~df_l.L2_any, "NO L2 (no cascade chain)", bwr)


# Reports
report(rdf, "ALL 4036 (LONG+SHORT)")
report(rdf[rdf.direction=="long"], "LONG only")
report(rdf[rdf.direction=="short"], "SHORT only")

sub = rdf[rdf.born_ms >= CUT].copy()
report(sub, "SUBSET 2023-06-06+ (LONG+SHORT)")
report(sub[sub.direction=="long"], "SUBSET 2023+ LONG")
report(sub[sub.direction=="short"], "SUBSET 2023+ SHORT")

# T1a verification
TARGET = int(datetime(2026, 6, 5, 22, 0, tzinfo=timezone.utc).timestamp() * 1000)
t1a = rdf[(rdf.direction == "long") & (rdf.born_ms == TARGET)]
if len(t1a):
    r = t1a.iloc[0]
    print(f"\n=== T1a verification (LONG) ===")
    print(f"  L1 any: {r.L1_any}")
    print(f"  L1 ≥50%: {r.L1_50}")
    print(f"  L2 any: {r.L2_any}")
    print(f"  L2 ≥50%: {r.L2_50}")
    print(f"  L3 strict: {r.L3_strict}")
    print(f"  R = {r.R}")

# Save
out_path = pathlib.Path(__file__).parent.parent / "data/cascade_111_v1.parquet"
rdf.to_parquet(out_path)
print(f"\nSaved: {out_path}\nElapsed: {time.time()-t0:.1f}s")
