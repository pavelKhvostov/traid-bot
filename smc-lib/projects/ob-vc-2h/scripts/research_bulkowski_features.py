"""Per-pattern Bulkowski WR uplift analysis on 2h ob_vc setups.

For each 2h ob_vc setup (after A1 drop), check if Bulkowski patterns were
detected in lookback window before born_ms on 4h and 1D timeframes.

Compare WR in (pattern present) vs out (no pattern) vs baseline.

No-lookahead: all pattern events have ts < born_ms_2h.
"""
import sys, pathlib, time
import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import load_1m, aggregate_all_tfs, to_candles
from bulkowski_detectors import (
    detect_engulfing, detect_hammer,
    detect_double_bottom, detect_double_top,
    detect_busted_double_top, detect_busted_double_bottom,
    annotate_with_ts,
)

t0 = time.time()
df = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")

# 2h setups (LTF priority 15m > 20m)
g2h = df[df.htf == "2h"].copy()
g2h["has_15m"] = g2h.groupby(["direction","ob_cur_open_ms"])["ltf"].transform(
    lambda x: "15m" in set(x))
mask = ((g2h.has_15m & (g2h.ltf=="15m")) | (~g2h.has_15m & (g2h.ltf=="20m")))
g2h = g2h[mask].copy()

cans_d = aggregate_all_tfs(load_1m())
cans_2h = to_candles(cans_d["2h"])
cans_4h = to_candles(cans_d["4h"])
cans_1d = to_candles(cans_d["1d"])
cans_12h = to_candles(cans_d["12h"])
cans_6h = to_candles(cans_d["6h"])
bar_idx = {c.open_time:i for i,c in enumerate(cans_2h)}

_rows = load_1m()
ts_1m = np.array([r[0] for r in _rows], dtype=np.int64)
h_1m = np.array([r[2] for r in _rows], dtype=np.float64)
l_1m = np.array([r[3] for r in _rows], dtype=np.float64)
HORIZON_MS = 14*24*3600*1000

print(f"Loaded TFs: 2h={len(cans_2h):,}  4h={len(cans_4h):,}  1d={len(cans_1d):,}")

# ─── Detect ALL Bulkowski patterns on 4h and 1D ─────────────
print("\nDetecting patterns on 4h...")
e4_ev = annotate_with_ts(detect_engulfing(cans_4h, min_body_pct=0.005), cans_4h)
h4_ev = annotate_with_ts(detect_hammer(cans_4h), cans_4h)
db4_ev = annotate_with_ts(detect_double_bottom(cans_4h, threshold_pct=0.03), cans_4h)
dt4_ev = annotate_with_ts(detect_double_top(cans_4h, threshold_pct=0.03), cans_4h)
bdt4_ev = annotate_with_ts(detect_busted_double_top(cans_4h, threshold_pct=0.03), cans_4h)
bdb4_ev = annotate_with_ts(detect_busted_double_bottom(cans_4h, threshold_pct=0.03), cans_4h)

print(f"  4h Engulfing: long={sum(1 for e in e4_ev if e[1]=='long')} short={sum(1 for e in e4_ev if e[1]=='short')}")
print(f"  4h Hammer:    long={sum(1 for e in h4_ev if e[1]=='long')} short={sum(1 for e in h4_ev if e[1]=='short')}")
print(f"  4h DB/DT:     {len(db4_ev)}/{len(dt4_ev)}")
print(f"  4h Busted DT→L / DB→S: {len(bdt4_ev)}/{len(bdb4_ev)}")

print("\nDetecting patterns on 1D...")
e1d_ev = annotate_with_ts(detect_engulfing(cans_1d, min_body_pct=0.005), cans_1d)
h1d_ev = annotate_with_ts(detect_hammer(cans_1d), cans_1d)
db1d_ev = annotate_with_ts(detect_double_bottom(cans_1d, threshold_pct=0.05), cans_1d)
dt1d_ev = annotate_with_ts(detect_double_top(cans_1d, threshold_pct=0.05), cans_1d)
bdt1d_ev = annotate_with_ts(detect_busted_double_top(cans_1d, threshold_pct=0.05), cans_1d)
bdb1d_ev = annotate_with_ts(detect_busted_double_bottom(cans_1d, threshold_pct=0.05), cans_1d)

print(f"  1D Engulfing: long={sum(1 for e in e1d_ev if e[1]=='long')} short={sum(1 for e in e1d_ev if e[1]=='short')}")
print(f"  1D Hammer:    long={sum(1 for e in h1d_ev if e[1]=='long')} short={sum(1 for e in h1d_ev if e[1]=='short')}")
print(f"  1D DB/DT:     {len(db1d_ev)}/{len(dt1d_ev)}")
print(f"  1D Busted DT→L / DB→S: {len(bdt1d_ev)}/{len(bdb1d_ev)}")

# Convert to numpy arrays for fast bisect lookup
def events_to_arr(events, direction):
    """Returns sorted ts_ms array of events with given direction."""
    return np.array(sorted([e[3] for e in events if e[1] == direction]), dtype=np.int64)

EVENTS = {
    ("4h", "engulf"):  (events_to_arr(e4_ev, "long"),  events_to_arr(e4_ev, "short")),
    ("4h", "hammer"):  (events_to_arr(h4_ev, "long"),  events_to_arr(h4_ev, "short")),
    ("4h", "db"):      (events_to_arr(db4_ev, "long"), events_to_arr(dt4_ev, "short")),
    ("4h", "busted"):  (events_to_arr(bdt4_ev, "long"), events_to_arr(bdb4_ev, "short")),
    ("1d", "engulf"):  (events_to_arr(e1d_ev, "long"),  events_to_arr(e1d_ev, "short")),
    ("1d", "hammer"):  (events_to_arr(h1d_ev, "long"),  events_to_arr(h1d_ev, "short")),
    ("1d", "db"):      (events_to_arr(db1d_ev, "long"), events_to_arr(dt1d_ev, "short")),
    ("1d", "busted"):  (events_to_arr(bdt1d_ev, "long"), events_to_arr(bdb1d_ev, "short")),
}

LOOKBACK_MS = {"engulf": 7*24*3600*1000, "hammer": 7*24*3600*1000,
               "db": 60*24*3600*1000, "busted": 30*24*3600*1000}


def has_event(ts_arr: np.ndarray, born_ms: int, lookback_ms: int) -> bool:
    """Check if any event in (born_ms - lookback_ms, born_ms]."""
    if len(ts_arr) == 0: return False
    lo = born_ms - lookback_ms
    i = np.searchsorted(ts_arr, born_ms, side="right")
    return i > 0 and ts_arr[i-1] > lo


# ─── Compute features per 2h ob_vc setup ───────────────────
NEGATIVE = {"T3b","T6","T13a","T13b","T16"}
ORIG_PREV={0:"T1",1:"T3",2:"T5",3:"T7",4:"T9",5:"T11",6:"T13",7:"T15"}
ORIG_CUR ={0:"T2",1:"T4",2:"T6",3:"T8",4:"T10",5:"T12",6:"T14",7:"T16"}
PI=[("long",True,"≥2"),("long",True,"1"),("long",False,"≥2"),("long",False,"1"),
    ("short",True,"≥2"),("short",True,"1"),("short",False,"≥2"),("short",False,"1")]


def wr_calc(d,prev,cur,E=0.01):
    if d=="long":
        pw=min(prev.open,prev.close)-prev.low; cw=min(cur.open,cur.close)-cur.low
    else:
        pw=prev.high-max(prev.open,prev.close); cw=cur.high-max(cur.open,cur.close)
    return float("inf") if cw<E else pw/cw


def gh(htf,ts):
    for i in range(len(htf)-1,-1,-1):
        if htf[i].open_time<ts: return htf[i]
    return None


def tbm(e,sl,d,b):
    if d=="long" and e<=sl: return None
    if d=="short" and e>=sl: return None
    R=abs(e-sl); TP1=e+R if d=="long" else e-R
    iS=int(np.searchsorted(ts_1m,b))
    if iS>=len(ts_1m): return None
    iE=min(len(ts_1m)-1,int(np.searchsorted(ts_1m,b+HORIZON_MS)))
    if d=="long":
        s=l_1m[iS:iE+1]; tr=int(np.argmax(s<=e)) if (s<=e).any() else -1
    else:
        s=h_1m[iS:iE+1]; tr=int(np.argmax(s>=e)) if (s>=e).any() else -1
    if tr==-1: return {"touched":False}
    ti=iS+tr; ph=h_1m[ti:iE+1]; pl=l_1m[ti:iE+1]
    if d=="long":
        tp1r=int(np.argmax(ph>=TP1)) if (ph>=TP1).any() else -1
        slr=int(np.argmax(pl<=sl)) if (pl<=sl).any() else -1
    else:
        tp1r=int(np.argmax(pl<=TP1)) if (pl<=TP1).any() else -1
        slr=int(np.argmax(ph>=sl)) if (ph>=sl).any() else -1
    if tp1r!=-1 and (slr==-1 or tp1r<=slr): return {"touched":True,"outcome":"win"}
    elif slr!=-1: return {"touched":True,"outcome":"loss"}
    return {"touched":True,"outcome":"timeout"}


records = []
for k, ((d, co), sub) in enumerate(g2h.groupby(["direction","ob_cur_open_ms"])):
    co=int(co); idx=bar_idx.get(co)
    if idx is None or idx<3: continue
    n2c=cans_2h[idx-3]; n1c=cans_2h[idx-2]; prev=cans_2h[idx-1]; cur=cans_2h[idx]
    if d=="long":
        sw=min(prev.low,cur.low)<min(n1c.low,n2c.low); ex="prev" if prev.low<cur.low else "cur"
    else:
        sw=max(prev.high,cur.high)>max(n1c.high,n2c.high); ex="prev" if prev.high>cur.high else "cur"
    nc=len(sub); nC="≥2" if nc>=2 else "1"
    fi=None
    for i,(dd,sww,ncc) in enumerate(PI):
        if dd==d and ncc==nC and sww==sw: fi=i; break
    if fi is None: continue
    if ex=="prev":
        r=wr_calc(d,prev,cur); suf="a" if r>=2.0 else "b"
        tid=ORIG_PREV[fi]+suf
    else: tid=ORIG_CUR[fi]
    if tid in NEGATIVE: continue

    chosen=sub.iloc[0]; born=int(chosen.born_ms)

    # A1 filter
    b12=gh(cans_12h,born); b6=gh(cans_6h,born); b4=gh(cans_4h,born)
    against=False; aligned=False
    if b12 and b6 and b4:
        bs=[(b.close-b.open)/b.open for b in (b12,b6,b4)]
        if d=="long":
            aligned=all(b>0.003 for b in bs); against=all(b<-0.003 for b in bs)
        else:
            aligned=all(b<-0.003 for b in bs); against=all(b>0.003 for b in bs)
    if against: continue

    # Entry/SL OLD rule
    if d=="long":
        cf=sub.sort_values("fvg_zone_hi",ascending=False).iloc[0]
        dp=0.8 if nc>=2 else 0.2
        en=cf.fvg_zone_hi-dp*(cf.fvg_zone_hi-cf.fvg_zone_lo); sl=cf.drop_lo
    else:
        cf=sub.sort_values("fvg_zone_lo",ascending=True).iloc[0]
        dp=0.8 if nc>=2 else 0.2
        en=cf.fvg_zone_lo+dp*(cf.fvg_zone_hi-cf.fvg_zone_lo); sl=cf.drop_hi

    out=tbm(en,sl,d,born)
    if out is None: continue
    rv=None
    if out.get("touched",False):
        rv=1 if out["outcome"]=="win" else (-1 if out["outcome"]=="loss" else 0)

    # ─── Bulkowski features: pattern present in lookback window? ───
    # For LONG ob_vc, check long-direction patterns (bullish)
    # For SHORT ob_vc, check short-direction patterns (bearish)
    feats = {}
    for (tf, pat), (long_arr, short_arr) in EVENTS.items():
        arr = long_arr if d == "long" else short_arr
        lb = LOOKBACK_MS[pat]
        feats[f"{tf}_{pat}"] = has_event(arr, born, lb)

    rec = {
        "t_id": tid, "direction": d, "born_ms": born,
        "touched": out.get("touched",False), "R": rv,
        "B1_aligned": aligned,
        **feats,
    }
    records.append(rec)

rdf = pd.DataFrame(records)
print(f"\nProcessed: {len(rdf):,}")
base_w=(rdf.R==1).sum(); base_l=(rdf.R==-1).sum()
base_nt=rdf.touched.sum()
base_wr = base_w/base_nt*100 if base_nt else 0
base_ev = (2*base_wr/100) - 1
print(f"Baseline (post A1): N={len(rdf):,}  touch={base_nt}  WR={base_wr:.1f}%  EV={base_ev:+.3f}R  Σ={base_w-base_l:+}R")

# ─── Per-feature WR uplift ───────────────────────────────────
features = [f"{tf}_{pat}" for tf in ("4h","1d") for pat in ("engulf","hammer","db","busted")]

print(f"\n{'='*100}")
print(f"PER-FEATURE WR UPLIFT (Bulkowski patterns in same direction as ob_vc)")
print(f"{'='*100}")
print(f"{'Feature':<18} {'N_in':>6} {'WR_in':>7} {'EV_in':>9} {'Σ_in':>7}  |  {'N_out':>6} {'WR_out':>8} {'Σ_out':>7}  |  {'lift_pp':>8}")
print("-"*110)
for f in features:
    inn = rdf[rdf[f]]; out = rdf[~rdf[f]]
    nin = len(inn); nout = len(out)
    wi = (inn.R==1).sum(); li = (inn.R==-1).sum()
    wo = (out.R==1).sum(); lo = (out.R==-1).sum()
    nti = inn.touched.sum(); nto = out.touched.sum()
    wr_i = wi/nti*100 if nti else 0
    wr_o = wo/nto*100 if nto else 0
    ev_i = (2*wr_i/100) - 1
    lift = wr_i - wr_o
    flag = "⭐" if lift >= 3 and nin >= 50 else ("✓" if lift >= 1 and nin >= 50 else "")
    print(f"{f:<18} {nin:>6} {wr_i:>6.1f}% {ev_i:>+8.3f}R {wi-li:>+6}R  |  {nout:>6} {wr_o:>7.1f}% {wo-lo:>+6}R  |  {lift:>+7.1f}pp {flag}")

# ─── Cross with B1 ──────────────────────────────────────────
print(f"\n{'='*100}")
print(f"B1 + Bulkowski COMBINATIONS")
print(f"{'='*100}")
print(f"{'Combo':<35} {'N':>5} {'touch':>6} {'WR':>7} {'EV':>9} {'Σ':>7}  {'vs B1':>8}")
print("-"*100)
b1 = rdf[rdf.B1_aligned]
b1_nt = b1.touched.sum(); b1_w=(b1.R==1).sum(); b1_l=(b1.R==-1).sum()
b1_wr = b1_w/b1_nt*100 if b1_nt else 0
print(f"{'B1 baseline':<35} {len(b1):>5} {b1_nt:>6} {b1_wr:>6.1f}% {(2*b1_wr/100)-1:>+8.3f}R {b1_w-b1_l:>+6}R  {'-':>8}")
for f in features:
    combo = rdf[rdf.B1_aligned & rdf[f]]
    if len(combo) < 30: continue
    nt = combo.touched.sum(); w=(combo.R==1).sum(); l=(combo.R==-1).sum()
    wr = w/nt*100 if nt else 0
    lift_vs_b1 = wr - b1_wr
    flag = "⭐" if lift_vs_b1 >= 2 else ("✓" if lift_vs_b1 >= 0.5 else "")
    print(f"B1 + {f:<29} {len(combo):>5} {nt:>6} {wr:>6.1f}% {(2*wr/100)-1:>+8.3f}R {w-l:>+6}R  {lift_vs_b1:>+7.1f}pp {flag}")

# Save records for ML stage
out_path = pathlib.Path(__file__).parent.parent / "data/bulkowski_features.parquet"
rdf.to_parquet(out_path)
print(f"\nSaved features to: {out_path}")
print(f"Elapsed: {time.time()-t0:.1f}s")
