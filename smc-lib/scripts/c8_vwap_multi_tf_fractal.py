"""Multi-TF fractal alignment: D fractals that also coincide with 3D or W fractals.

A D fractal is "aligned-3D" if its level (high/low) coincides with the 3D bar's
extreme AND that 3D bar is itself a 3D Williams N=2 fractal.

Same for W (Mon-Mon anchor per canon).

Hypothesis: aligned fractals → stronger VWAPs → higher WR on sweep.

Output:
  - Count of D fractals aligned with 3D/W
  - For each missed (#14, #15, #48): are swept VWAPs from aligned anchors?
  - WR of "sweep aligned VWAP" filter on baseline 1275
"""
from __future__ import annotations
import csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

CSV_PATH = Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
BASE_PATH = Path.home() / "Desktop" / "baseline_1267.parquet"
TF_D_MS = 1440 * 60_000
TF_3D_MS = 3 * TF_D_MS
TF_W_MS = 7 * TF_D_MS
TF_12H_MS = 720 * 60_000
START_MS = int(datetime(2020,1,1,tzinfo=timezone.utc).timestamp() * 1000)

# W anchor = Monday 00:00 UTC. Monday Jan 6 2020 = 1578268800000
MON_ANCHOR_MS = int(datetime(2020,1,6,tzinfo=timezone.utc).timestamp()*1000)

DIRS = {"#14":"high","#15":"low","#48":"high"}
TIMES = {"#14":int(datetime(2026,3,4,12,0,tzinfo=timezone.utc).timestamp()*1000),
         "#15":int(datetime(2026,3,8,12,0,tzinfo=timezone.utc).timestamp()*1000),
         "#48":int(datetime(2026,5,6,0,0,tzinfo=timezone.utc).timestamp()*1000)}

print("Loading 1m...")
rows=[]
with CSV_PATH.open() as f:
    rd=csv.reader(f); next(rd)
    for r in rd:
        ts=int(datetime.fromisoformat(r[0]).timestamp()*1000)
        if ts<START_MS-10*TF_W_MS: continue
        rows.append((ts,float(r[2]),float(r[3]),float(r[4]),float(r[5])))
ts_arr=np.array([r[0] for r in rows],dtype=np.int64)
hi_arr=np.array([r[1] for r in rows]); lo_arr=np.array([r[2] for r in rows])
cl_arr=np.array([r[3] for r in rows]); vo_arr=np.array([r[4] for r in rows])

def agg(rs, tf_ms, anchor=0):
    out=[]; cb=None; h=l=c=v=0.0
    for ts,hh,ll,cc,vv in rs:
        b = ts - ((ts - anchor) % tf_ms)
        if b!=cb:
            if cb is not None: out.append((cb,h,l,c,v))
            cb=b; h,l,c,v=hh,ll,cc,vv
        else: h=max(h,hh); l=min(l,ll); c=cc; v+=vv
    if cb is not None: out.append((cb,h,l,c,v))
    return out

print("Aggregating D, 3D (Mon-anchor), W (Mon-anchor)...")
records = list(zip(ts_arr,hi_arr,lo_arr,cl_arr,vo_arr))
barsD = [b for b in agg(records, TF_D_MS) if b[0]>=START_MS]
bars3D = [b for b in agg(records, TF_3D_MS, anchor=MON_ANCHOR_MS) if b[0]>=START_MS]
barsW = [b for b in agg(records, TF_W_MS, anchor=MON_ANCHOR_MS) if b[0]>=START_MS]
print(f"  D: {len(barsD)}, 3D: {len(bars3D)}, W: {len(barsW)}")

# Williams N=2 fractals on each TF
def detect_fractals(bars, N=2):
    out=[]
    for i in range(N, len(bars)-N):
        h_i, l_i = bars[i][1], bars[i][2]
        if all(h_i > bars[i+j][1] for j in [-2,-1,1,2]):
            out.append({"ts": bars[i][0], "ts_end": bars[i][0] + (bars[i+1][0]-bars[i][0]), "side":"FH", "level":h_i})
        if all(l_i < bars[i+j][2] for j in [-2,-1,1,2]):
            out.append({"ts": bars[i][0], "ts_end": bars[i][0] + (bars[i+1][0]-bars[i][0]), "side":"FL", "level":l_i})
    return out

fr_D  = detect_fractals(barsD)
fr_3D = detect_fractals(bars3D)
fr_W  = detect_fractals(barsW)
print(f"  Fractals: D={len(fr_D)}, 3D={len(fr_3D)}, W={len(fr_W)}")

# For each D fractal, check alignment with 3D and W
def is_aligned(d_f, htf_frs, htf_ms):
    """D fractal aligned if its level == HTF bar containing it, and HTF bar is HTF fractal."""
    for htf in htf_frs:
        # Check side match
        if htf["side"] != d_f["side"]: continue
        # D fractal's ts is within HTF bar window [htf.ts, htf.ts + htf_ms)
        if not (htf["ts"] <= d_f["ts"] < htf["ts"] + htf_ms): continue
        # Level must coincide (very close — same bar extreme)
        if abs(htf["level"] - d_f["level"]) < 0.01:
            return htf["ts"]
    return None

print("Computing D alignment with 3D/W...")
for d in fr_D:
    d["aligned_3D"] = is_aligned(d, fr_3D, TF_3D_MS)
    d["aligned_W"] = is_aligned(d, fr_W, TF_W_MS)

n_3d = sum(1 for d in fr_D if d["aligned_3D"])
n_w  = sum(1 for d in fr_D if d["aligned_W"])
n_3d_w = sum(1 for d in fr_D if d["aligned_3D"] and d["aligned_W"])
print(f"  D fractals: {len(fr_D)}")
print(f"  D aligned with 3D: {n_3d} ({n_3d/len(fr_D)*100:.1f}%)")
print(f"  D aligned with W:  {n_w} ({n_w/len(fr_D)*100:.1f}%)")
print(f"  D aligned 3D + W:  {n_3d_w}")

# === Cumulative VWAP ===
pv_cum=np.cumsum(cl_arr*vo_arr); vol_cum=np.cumsum(vo_arr)
def vwap_at(a,q):
    i_a=int(np.searchsorted(ts_arr,a))
    i_q=int(np.searchsorted(ts_arr,q,side='right'))-1
    if i_a>i_q: return None
    pv=pv_cum[i_q]-(pv_cum[i_a-1] if i_a>0 else 0)
    v=vol_cum[i_q]-(vol_cum[i_a-1] if i_a>0 else 0)
    return pv/v if v>0 else None

# Add ready_ms (need + 2 D bars confirmation)
for d in fr_D:
    d["ready_ms"] = d["ts"] + 3 * TF_D_MS  # i+2 bars

# === Precompute swept VWAPs per baseline bar (with alignment info) ===
print("\nComputing swept VWAPs per baseline bar with alignment...")
df_base=pd.read_parquet(BASE_PATH)
bar_swept={}
for bidx,row in df_base.iterrows():
    bo=int(row["ts"]); bc=bo+TF_12H_MS
    side="FH" if row["direction"]=="high" else "FL"
    i_s=int(np.searchsorted(ts_arr,bo)); i_e=int(np.searchsorted(ts_arr,bc))
    if i_e<=i_s: continue
    bh=hi_arr[i_s:i_e].max(); bl=lo_arr[i_s:i_e].min(); bc_p=cl_arr[i_e-1]
    rel=[d for d in fr_D if d["side"]==side and d["ready_ms"]<=bo]
    sw=[]
    for d in rel:
        v=vwap_at(d["ts"],bc)
        if v is None: continue
        ok = (bh>v and bc_p<v) if side=="FH" else (bl<v and bc_p>v)
        if ok:
            age=(bc-d["ts"])/(24*3600_000)
            sw.append({"v":v,"age":age,"aligned_3D":d["aligned_3D"] is not None,"aligned_W":d["aligned_W"] is not None})
    bar_swept[bidx]=sw

missed_idx={}
for tag,t in TIMES.items():
    m=df_base[(df_base["ts"]==t) & (df_base["direction"]==DIRS[tag])]
    if not m.empty: missed_idx[tag]=m.index[0]

# === Check missed: which swept VWAPs are aligned? ===
print(f"\n=== Missed pivots — swept VWAPs alignment ===")
for tag, midx in missed_idx.items():
    sw = bar_swept.get(midx, [])
    print(f"\n{tag} (n_swept={len(sw)}):")
    if not sw: continue
    for x in sw:
        flags = []
        if x["aligned_3D"]: flags.append("3D")
        if x["aligned_W"]: flags.append("W")
        flag = " + ".join(flags) if flags else "D-only"
        print(f"  v={x['v']:.0f}  age={x['age']:.0f}d  align={flag}")

# === Grid: filter by alignment ===
print(f"\n=== WR grid: filter by alignment requirement ===")
def evaluate(min_aligned_3D, min_aligned_W, min_total):
    keep=conf=imp=0; caught=[]
    for bidx, sw in bar_swept.items():
        n_3d = sum(1 for x in sw if x["aligned_3D"])
        n_w  = sum(1 for x in sw if x["aligned_W"])
        n_tot = len(sw)
        if n_3d < min_aligned_3D: continue
        if n_w < min_aligned_W: continue
        if n_tot < min_total: continue
        keep+=1
        row=df_base.iloc[bidx]
        if row["confirmed"]: conf+=1
        if row["is_important"] and row["confirmed"]: imp+=1
        for tag,midx in missed_idx.items():
            if bidx==midx: caught.append(tag)
    p_w = conf/keep*100 if keep else 0
    return {"min_3D":min_aligned_3D, "min_W":min_aligned_W, "min_total":min_total,
            "keep":keep, "conf":conf, "P_W%":round(p_w,1), "imp":imp,
            "n_missed":len(caught), "missed":"+".join(sorted(caught))}

results = []
for m3 in [0, 1, 2]:
    for mw in [0, 1, 2]:
        for mt in [1, 2, 3]:
            results.append(evaluate(m3, mw, mt))
df_r = pd.DataFrame(results)
df_r.to_csv(Path.home()/"Desktop"/"c8_vwap_aligned_grid.csv", index=False)

print(f"\n{'3D':>3} {'W':>3} {'Total':>5} {'keep':>5} {'conf':>5} {'P_W%':>6} {'imp':>4} {'missed':<12}")
print("-"*60)
for _, r in df_r.sort_values(["n_missed","P_W%"], ascending=[False, False]).iterrows():
    flag = "★" if r["P_W%"]>=70 else (" " if r["P_W%"]>=65 else " ")
    print(f"{flag} {r['min_3D']:>2} {r['min_W']:>2} {r['min_total']:>4} {r['keep']:>5} {r['conf']:>5} {r['P_W%']:>5.1f}% {r['imp']:>4} {r['missed']:<12}")

print(f"\nBaseline 1275 / P(W)=48.6% / 18 imp; Canon basket 654/66.8%/15 imp")
