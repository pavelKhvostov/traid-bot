"""B8: HTF zone confluence — 2h ob_vc.zone пересекается с unmitigated 12h/D ob_vc.zone
(такого же направления, сформированного раньше).

No-lookahead: HTF ob_vc.born_ms < 2h ob_vc.born_ms; mitigation проверяется 1m данными
только ДО born_ms_2h.

«100% mitigated» = price touched opposite edge (zone.lo для LONG, zone.hi для SHORT).
"""
import sys, pathlib, time
import numpy as np
import pandas as pd
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import load_1m, aggregate_all_tfs, to_candles

t0 = time.time()
df = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")

# HTF zones (12h + 1D) — unique per OB
htf_zones = []
for htf in ["12h", "1d"]:
    sub = df[df.htf == htf]
    for (d, op), g in sub.groupby(["direction","ob_cur_open_ms"]):
        r0 = g.iloc[0]
        htf_zones.append({
            "htf": htf,
            "direction": d,
            "born_ms": int(r0.born_ms),
            "zone_lo": float(r0.ob_zone_lo),
            "zone_hi": float(r0.ob_zone_hi),
            "valid_until_ms": int(r0.valid_until_ms),
        })
htf_df = pd.DataFrame(htf_zones).sort_values("born_ms").reset_index(drop=True)
print(f"HTF ob_vc zones: 12h={len(htf_df[htf_df.htf=='12h']):,}  1d={len(htf_df[htf_df.htf=='1d']):,}")

# 2h setups (positive types only, A1 filter applied)
g2h = df[df.htf == "2h"].copy()
g2h["has_15m"] = g2h.groupby(["direction","ob_cur_open_ms"])["ltf"].transform(
    lambda x: "15m" in set(x))
mask = ((g2h.has_15m & (g2h.ltf=="15m")) | (~g2h.has_15m & (g2h.ltf=="20m")))
g2h = g2h[mask].copy()

cans_d = aggregate_all_tfs(load_1m())
cans = to_candles(cans_d["2h"])
cans_12h = to_candles(cans_d["12h"])
cans_6h = to_candles(cans_d["6h"])
cans_4h = to_candles(cans_d["4h"])
bar_idx = {c.open_time:i for i,c in enumerate(cans)}

_rows = load_1m()
ts_1m = np.array([r[0] for r in _rows], dtype=np.int64)
h_1m = np.array([r[2] for r in _rows], dtype=np.float64)
l_1m = np.array([r[3] for r in _rows], dtype=np.float64)
HORIZON_MS = 14*24*3600*1000

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


def is_mitigated_at(zone_lo, zone_hi, direction, htf_born_ms, check_until_ms):
    """Was HTF zone 100% mitigated by check_until_ms? (price touched far edge after born)"""
    i_start = int(np.searchsorted(ts_1m, htf_born_ms))
    i_end = int(np.searchsorted(ts_1m, check_until_ms, side="right"))
    if i_end <= i_start: return False
    if direction == "long":
        return bool((l_1m[i_start:i_end] <= zone_lo).any())
    else:
        return bool((h_1m[i_start:i_end] >= zone_hi).any())


# Pre-sort HTF zones by born_ms for fast scanning
htf_arr = htf_df.values
htf_born_arr = htf_df.born_ms.values

records = []
for k, ((d, co), sub) in enumerate(g2h.groupby(["direction","ob_cur_open_ms"])):
    co=int(co); idx=bar_idx.get(co)
    if idx is None or idx<3: continue
    n2c=cans[idx-3]; n1c=cans[idx-2]; prev=cans[idx-1]; cur=cans[idx]
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
    ob_lo = float(chosen.ob_zone_lo); ob_hi = float(chosen.ob_zone_hi)

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

    # B8: HTF confluence check
    # Find HTF ob_vc with born < 2h born, same direction, zone overlap, not mitigated
    has_confluence_12h = False
    has_confluence_1d = False
    i_max = int(np.searchsorted(htf_df.born_ms.values, born))
    for j in range(i_max):
        hz = htf_df.iloc[j]
        if hz.direction != d: continue
        # Zone overlap check
        if not (max(hz.zone_lo, ob_lo) <= min(hz.zone_hi, ob_hi)): continue
        # Not 100% mitigated by 2h born_ms
        if is_mitigated_at(hz.zone_lo, hz.zone_hi, d, hz.born_ms, born): continue
        # Confluence!
        if hz.htf == "12h": has_confluence_12h = True
        elif hz.htf == "1d": has_confluence_1d = True
        if has_confluence_12h and has_confluence_1d: break

    records.append({
        "t_id": tid, "direction": d,
        "touched": out.get("touched",False), "R": rv,
        "B1_aligned": aligned,
        "B8_12h_confluence": has_confluence_12h,
        "B8_1d_confluence": has_confluence_1d,
        "B8_any": has_confluence_12h or has_confluence_1d,
    })

rdf = pd.DataFrame(records)
print(f"\nProcessed: {len(rdf):,}")
base_w=(rdf.R==1).sum(); base_l=(rdf.R==-1).sum()
base_nt=rdf.touched.sum()
print(f"Baseline (post A1): N={len(rdf):,}  touch={base_nt}  WR={base_w/base_nt*100:.1f}%  Σ={base_w-base_l:+}R")

# Test B8 variants
filters = [
    ("B8_12h: 12h ob_vc confluence",   "B8_12h_confluence"),
    ("B8_1d:  1d ob_vc confluence",    "B8_1d_confluence"),
    ("B8_any: 12h OR 1d confluence",   "B8_any"),
]
print(f"\n{'Filter':<32} {'In':>5} {'Out':>5} {'WR_in':>7} {'WR_out':>8} {'EV_in':>9} {'Σ_in':>7} {'Σ_out':>7}")
print("-"*90)
for name, col in filters:
    inn=rdf[rdf[col]]; out=rdf[~rdf[col]]
    nin=len(inn); nout=len(out)
    wi=(inn.R==1).sum(); li=(inn.R==-1).sum()
    wo=(out.R==1).sum(); lo=(out.R==-1).sum()
    nti=inn.touched.sum(); nto=out.touched.sum()
    wr_i=wi/nti*100 if nti else 0
    wr_o=wo/nto*100 if nto else 0
    ev_i=(2*wr_i/100)-1
    print(f"{name:<32} {nin:>5} {nout:>5} {wr_i:>6.1f}% {wr_o:>7.1f}% {ev_i:>+8.3f}R {wi-li:>+6}R {wo-lo:>+6}R")

# Test combined with B1
print(f"\n{'='*90}")
print(f"COMBINED B1 + B8 (aligned cascade AND HTF confluence)")
print(f"{'='*90}")
combo = rdf[rdf.B1_aligned & rdf.B8_any]
nt=combo.touched.sum(); w=(combo.R==1).sum(); l=(combo.R==-1).sum()
wr=w/nt*100 if nt else 0
print(f"B1 + B8_any: N={len(combo)}  touch={nt}  WR={wr:.1f}%  EV={(2*wr/100)-1:+.3f}R  Σ={w-l:+}R")

print(f"\nElapsed: {time.time()-t0:.1f}s")
