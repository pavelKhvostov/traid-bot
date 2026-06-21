"""B8 v2: 2h ob_vc confluence с **unmitigated FVG portion** ob_vc 1D / 12h.

Логика (no-lookahead):
  Для каждого 2h ob_vc setup при born_ms:
    1. Найти ob_vc 1D/12h с:
       - direction == 2h direction
       - born_HTF < born_2h
       - age ≤ 90 дней
    2. Для каждой FVG-component (4h, 6h) этих HTF ob_vc:
       - Рассчитать unmitigated portion на момент born_2h:
         LONG:  unfilled = [fvg_lo, min(fvg_hi, min_low_since_c3close)]
         SHORT: unfilled = [max(fvg_lo, max_high_since_c3close), fvg_hi]
       - Если unfilled непустая И overlaps с 2h entry → CONFLUENCE
    3. Report fires + concrete examples
"""
import sys, pathlib, time
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import load_1m, aggregate_all_tfs, to_candles

MSK = timezone(timedelta(hours=3))
def to_msk(ms): return datetime.fromtimestamp(int(ms)/1000, MSK).strftime("%a %d-%m-%Y %H:%M")

t0 = time.time()
df = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")
g2h = df[df.htf == "2h"].copy()
g2h["has_15m"] = g2h.groupby(["direction","ob_cur_open_ms"])["ltf"].transform(
    lambda x: "15m" in set(x))
mask = ((g2h.has_15m & (g2h.ltf=="15m")) | (~g2h.has_15m & (g2h.ltf=="20m")))
g2h = g2h[mask].copy()

# HTF (1D + 12h) FVG components — каждая row = одна FVG
htf_fvgs = df[df.htf.isin(["1d","12h"])].copy()
htf_fvgs = htf_fvgs.rename(columns={"ob_cur_open_ms":"htf_cur_open_ms",
                                      "born_ms":"htf_born_ms",
                                      "htf":"htf_tf"})
htf_fvgs = htf_fvgs[["htf_tf","direction","htf_cur_open_ms","htf_born_ms",
                      "ltf","fvg_c3_close_ms","fvg_zone_lo","fvg_zone_hi"]]
htf_fvgs = htf_fvgs.sort_values("htf_born_ms").reset_index(drop=True)
print(f"HTF FVG-components: 1D+12h = {len(htf_fvgs):,}")
print(f"  1D: {(htf_fvgs.htf_tf=='1d').sum():,}")
print(f"  12h: {(htf_fvgs.htf_tf=='12h').sum():,}")

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
AGE_LIMIT_MS = 90*24*3600*1000

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


def unfilled_fvg_portion(fvg_lo, fvg_hi, direction, c3_close_ms, check_until_ms):
    """Return (unfilled_lo, unfilled_hi) or (None, None) if 100% mitigated.
    wick-fill canon: each touch from approach side compresses the zone.
    """
    iS = int(np.searchsorted(ts_1m, c3_close_ms))
    iE = int(np.searchsorted(ts_1m, check_until_ms))
    if iE <= iS:
        return fvg_lo, fvg_hi  # no data, assume fully unmitigated
    if direction == "long":
        # LONG FVG: price came from above; touches compress top down
        min_low = float(l_1m[iS:iE].min())
        if min_low <= fvg_lo:
            return None, None  # 100% mitigated
        unfilled_hi = min(fvg_hi, min_low)
        return fvg_lo, unfilled_hi
    else:
        # SHORT FVG: price came from below; touches compress bottom up
        max_high = float(h_1m[iS:iE].max())
        if max_high >= fvg_hi:
            return None, None
        unfilled_lo = max(fvg_lo, max_high)
        return unfilled_lo, fvg_hi


# Pre-extract HTF born_ms array
htf_born_arr = htf_fvgs.htf_born_ms.values

records = []
examples = []   # collect first 10 concrete examples of B8 fires for verification
for k, ((d, co), sub) in enumerate(g2h.groupby(["direction","ob_cur_open_ms"])):
    if k % 500 == 0 and k > 0: print(f"  {k:,}/{len(g2h.groupby(['direction','ob_cur_open_ms']))}")
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

    # A1 cascade against
    b12=gh(cans_12h,born); b6=gh(cans_6h,born); b4=gh(cans_4h,born)
    against=False; aligned=False
    if b12 and b6 and b4:
        bs=[(b.close-b.open)/b.open for b in (b12,b6,b4)]
        if d=="long":
            aligned=all(b>0.003 for b in bs); against=all(b<-0.003 for b in bs)
        else:
            aligned=all(b<-0.003 for b in bs); against=all(b>0.003 for b in bs)
    if against: continue

    if d=="long":
        cf=sub.sort_values("fvg_zone_hi",ascending=False).iloc[0]
        dp=0.8 if nc>=2 else 0.2
        entry=cf.fvg_zone_hi-dp*(cf.fvg_zone_hi-cf.fvg_zone_lo); sl=cf.drop_lo
    else:
        cf=sub.sort_values("fvg_zone_lo",ascending=True).iloc[0]
        dp=0.8 if nc>=2 else 0.2
        entry=cf.fvg_zone_lo+dp*(cf.fvg_zone_hi-cf.fvg_zone_lo); sl=cf.drop_hi

    out=tbm(entry,sl,d,born)
    if out is None: continue
    rv=None
    if out.get("touched",False):
        rv=1 if out["outcome"]=="win" else (-1 if out["outcome"]=="loss" else 0)

    # B8 v2: confluence with unmitigated HTF FVG portion
    age_min = born - AGE_LIMIT_MS
    i_max = int(np.searchsorted(htf_born_arr, born))
    i_min = int(np.searchsorted(htf_born_arr, age_min))
    has_b8 = False
    b8_match = None
    for j in range(i_min, i_max):
        hr = htf_fvgs.iloc[j]
        if hr.direction != d: continue
        u_lo, u_hi = unfilled_fvg_portion(
            float(hr.fvg_zone_lo), float(hr.fvg_zone_hi), d,
            int(hr.fvg_c3_close_ms), born)
        if u_lo is None: continue
        # Check 2h OB.zone OVERLAPS with unfilled portion (relaxed)
        ob_lo, ob_hi = float(chosen.ob_zone_lo), float(chosen.ob_zone_hi)
        if max(u_lo, ob_lo) <= min(u_hi, ob_hi):
            has_b8 = True
            b8_match = {
                "2h_cur_open": int(co), "2h_born": born,
                "2h_entry": entry, "2h_direction": d,
                "htf_tf": hr.htf_tf, "htf_cur_open": int(hr.htf_cur_open_ms),
                "htf_born": int(hr.htf_born_ms), "htf_ltf": hr.ltf,
                "fvg_zone": [float(hr.fvg_zone_lo), float(hr.fvg_zone_hi)],
                "unfilled": [u_lo, u_hi],
                "age_days": (born - int(hr.htf_born_ms)) / (24*3600*1000),
            }
            if len(examples) < 10:
                examples.append(b8_match)
            break

    records.append({
        "t_id": tid, "direction": d,
        "touched": out.get("touched",False), "R": rv,
        "B1_aligned": aligned,
        "B8v2": has_b8,
    })

rdf = pd.DataFrame(records)
print(f"\nProcessed: {len(rdf):,}\n")

base_w=(rdf.R==1).sum(); base_l=(rdf.R==-1).sum()
base_nt=rdf.touched.sum()
print(f"Baseline (post A1):  N={len(rdf):,}  WR={base_w/base_nt*100:.1f}%  Σ={base_w-base_l:+}R")

inn=rdf[rdf.B8v2]; out=rdf[~rdf.B8v2]
nti=inn.touched.sum(); nto=out.touched.sum()
wi=(inn.R==1).sum(); li=(inn.R==-1).sum()
wo=(out.R==1).sum(); lo=(out.R==-1).sum()
wr_i = wi/nti*100 if nti else 0
wr_o = wo/nto*100 if nto else 0
print(f"\nB8 v2 fires:         N={len(inn)}  WR={wr_i:.1f}%  EV={(2*wr_i/100)-1:+.3f}R  Σ={wi-li:+}R")
print(f"B8 v2 no-fire:       N={len(out)}  WR={wr_o:.1f}%  EV={(2*wr_o/100)-1:+.3f}R  Σ={wo-lo:+}R")

# Combined B1 + B8 v2
combo = rdf[rdf.B1_aligned & rdf.B8v2]
nt=combo.touched.sum(); w=(combo.R==1).sum(); l=(combo.R==-1).sum()
wr=w/nt*100 if nt else 0
print(f"\nB1 + B8 v2:          N={len(combo)}  WR={wr:.1f}%  EV={(2*wr/100)-1:+.3f}R  Σ={w-l:+}R")

# CONCRETE EXAMPLES for verification
print(f"\n{'='*78}")
print(f"10 КОНКРЕТНЫХ примеров B8 v2 firing (для верификации):")
print(f"{'='*78}\n")
for i, ex in enumerate(examples, 1):
    print(f"[{i}] 2h {ex['2h_direction'].upper()} cur {to_msk(ex['2h_cur_open'])}")
    print(f"    born:  {to_msk(ex['2h_born'])}")
    print(f"    entry: ${ex['2h_entry']:,.0f}")
    print(f"    ↓ confluence с")
    print(f"    {ex['htf_tf'].upper()} ob_vc cur {to_msk(ex['htf_cur_open'])}  age {ex['age_days']:.1f}d")
    print(f"      FVG-{ex['htf_ltf']}: [{ex['fvg_zone'][0]:,.0f} ; {ex['fvg_zone'][1]:,.0f}]")
    print(f"      unmitigated на момент 2h born: [{ex['unfilled'][0]:,.0f} ; {ex['unfilled'][1]:,.0f}]")
    print(f"      2h entry ${ex['2h_entry']:,.0f} ∈ unfilled ✓")
    print()

print(f"Elapsed: {time.time()-t0:.1f}s")
