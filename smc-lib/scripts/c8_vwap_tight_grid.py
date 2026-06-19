"""C8 VWAP — tightened filters for WR > 70% while keeping missed catch.

Add 2 extra filters beyond cluster/macro hybrid:
  - max_close_dist_pct: nearest swept VWAP must be within X% of close (tight return)
  - max_pierce_pct:     wick pierce ≤ Y% beyond VWAP (not extreme)

For each bar:
  swept = [(v, age, pierce_pct, close_dist_pct) for f in matched fractals if swept]
  pass = (
      (hybrid_filter A or B) AND
      min(close_dist_pct) ≤ max_close_dist AND
      min(pierce_pct) ≤ max_pierce
  )
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
TF_12H_MS = 720 * 60_000
START_MS = int(datetime(2020,1,1,tzinfo=timezone.utc).timestamp() * 1000)

DIRS = {"#14":"high","#15":"low","#48":"high"}
TIMES = {"#14":int(datetime(2026,3,4,12,0,tzinfo=timezone.utc).timestamp()*1000),
         "#15":int(datetime(2026,3,8,12,0,tzinfo=timezone.utc).timestamp()*1000),
         "#48":int(datetime(2026,5,6,0,0,tzinfo=timezone.utc).timestamp()*1000)}

print("Loading...")
rows=[]
with CSV_PATH.open() as f:
    rd=csv.reader(f); next(rd)
    for r in rd:
        ts=int(datetime.fromisoformat(r[0]).timestamp()*1000)
        if ts<START_MS-5*TF_D_MS: continue
        rows.append((ts,float(r[2]),float(r[3]),float(r[4]),float(r[5])))
ts_arr=np.array([r[0] for r in rows],dtype=np.int64)
hi_arr=np.array([r[1] for r in rows]); lo_arr=np.array([r[2] for r in rows])
cl_arr=np.array([r[3] for r in rows]); vo_arr=np.array([r[4] for r in rows])
def agg(rs,tf_ms):
    out=[];cb=None;h=l=c=v=0.0
    for ts,hh,ll,cc,vv in rs:
        b=ts-(ts%tf_ms)
        if b!=cb:
            if cb is not None: out.append((cb,h,l,c,v))
            cb=b; h,l,c,v=hh,ll,cc,vv
        else: h=max(h,hh); l=min(l,ll); c=cc; v+=vv
    if cb is not None: out.append((cb,h,l,c,v))
    return out
barsD=[b for b in agg(list(zip(ts_arr,hi_arr,lo_arr,cl_arr,vo_arr)),TF_D_MS) if b[0]>=START_MS]
N=2; fractals=[]
for i in range(N,len(barsD)-N):
    h_i,l_i=barsD[i][1],barsD[i][2]
    if all(h_i>barsD[i+j][1] for j in [-2,-1,1,2]):
        fractals.append({"ts":barsD[i][0],"ready":barsD[i+N][0]+TF_D_MS,"side":"FH"})
    if all(l_i<barsD[i+j][2] for j in [-2,-1,1,2]):
        fractals.append({"ts":barsD[i][0],"ready":barsD[i+N][0]+TF_D_MS,"side":"FL"})

pv_cum=np.cumsum(cl_arr*vo_arr); vol_cum=np.cumsum(vo_arr)
def vwap_at(a,q):
    i_a=int(np.searchsorted(ts_arr,a))
    i_q=int(np.searchsorted(ts_arr,q,side='right'))-1
    if i_a>i_q: return None
    pv=pv_cum[i_q]-(pv_cum[i_a-1] if i_a>0 else 0)
    v=vol_cum[i_q]-(vol_cum[i_a-1] if i_a>0 else 0)
    return pv/v if v>0 else None

print("Precompute swept VWAPs with metrics per bar...")
df_base=pd.read_parquet(BASE_PATH)
bar_data={}  # idx → list of (v, age_d, pierce_pct, close_dist_pct)
for bidx,row in df_base.iterrows():
    bo=int(row["ts"]); bc=bo+TF_12H_MS
    side="FH" if row["direction"]=="high" else "FL"
    i_s=int(np.searchsorted(ts_arr,bo)); i_e=int(np.searchsorted(ts_arr,bc))
    if i_e<=i_s: continue
    bh=hi_arr[i_s:i_e].max(); bl=lo_arr[i_s:i_e].min(); bc_p=cl_arr[i_e-1]
    rel=[f for f in fractals if f["side"]==side and f["ready"]<=bo]
    sw=[]
    for f in rel:
        v=vwap_at(f["ts"],bc)
        if v is None: continue
        if side=="FH":
            if not (bh>v and bc_p<v): continue
            pierce_pct = (bh - v) / v * 100  # how far high went above VWAP
        else:
            if not (bl<v and bc_p>v): continue
            pierce_pct = (v - bl) / v * 100  # how far low went below VWAP
        close_dist_pct = abs(bc_p - v) / v * 100
        age=(bc-f["ts"])/(24*3600_000)
        sw.append((v, age, pierce_pct, close_dist_pct))
    bar_data[bidx]=sw

missed_idx={}
for tag,t in TIMES.items():
    m=df_base[(df_base["ts"]==t) & (df_base["direction"]==DIRS[tag])]
    if not m.empty: missed_idx[tag]=m.index[0]

# === Show missed metrics ===
print(f"\nMissed metric stats:")
for tag, midx in missed_idx.items():
    sw = bar_data.get(midx, [])
    if not sw: continue
    pierces = [p for _, _, p, _ in sw]
    close_dists = [d for _, _, _, d in sw]
    ages = [a for _, a, _, _ in sw]
    print(f"  {tag}: n_swept={len(sw)} pierce%={min(pierces):.3f}-{max(pierces):.3f} close_dist%={min(close_dists):.3f}-{max(close_dists):.3f} ages={min(ages):.0f}-{max(ages):.0f}d")

# === Grid: hybrid + max_close_dist + max_pierce ===
def filter_passes(sweep_list, K, X, Y, max_close, max_pierce):
    if not sweep_list: return False
    # Apply pierce + close_dist constraints to swept VWAPs first
    valid = [(v,a,p,d) for v,a,p,d in sweep_list if p <= max_pierce and d <= max_close]
    if not valid: return False
    # Then check hybrid
    # B: macro single
    if any(a >= Y for _, a, _, _ in valid):
        return True
    # A: cluster
    if len(valid) >= K:
        vs = sorted([v for v, _, _, _ in valid])
        for i in range(len(vs) - K + 1):
            window = vs[i:i+K]
            spread = (max(window) - min(window)) / np.mean(window) * 100
            if spread <= X:
                return True
    return False

print(f"\nGrid: K, X, Y × max_close_dist × max_pierce")
results=[]
for K in [2, 3]:
    for X in [1.0, 1.5]:
        for Y in [365, 730, 1000]:
            for max_close in [0.3, 0.5, 1.0]:
                for max_pierce in [0.5, 1.0, 2.0]:
                    keep=conf=imp=0; caught=[]
                    for bidx, sw in bar_data.items():
                        if filter_passes(sw, K, X, Y, max_close, max_pierce):
                            keep+=1
                            row=df_base.iloc[bidx]
                            if row["confirmed"]: conf+=1
                            if row["is_important"] and row["confirmed"]: imp+=1
                            for tag,midx in missed_idx.items():
                                if bidx==midx: caught.append(tag)
                    p_w=conf/keep*100 if keep else 0
                    results.append({"K":K,"X%":X,"Y_d":Y,"max_close%":max_close,"max_pierce%":max_pierce,
                                    "keep":keep,"conf":conf,"P_W%":round(p_w,1),"imp":imp,
                                    "n_missed":len(caught),"missed":"+".join(sorted(caught))})
df=pd.DataFrame(results)
df.to_csv(Path.home()/"Desktop"/"c8_vwap_tight_grid.csv", index=False)

# Best by P_W with n_missed
print(f"\n=== Configs with P_W ≥ 70% (any missed caught) ===")
top70 = df[(df["P_W%"]>=70) & (df["keep"]>=20)].sort_values(["n_missed","P_W%"], ascending=[False, False])
print(f"  Total: {len(top70)}")
print(f"{'K':>2} {'X%':>4} {'Y_d':>5} {'CL%':>5} {'PR%':>5} {'keep':>5} {'P_W%':>6} {'imp':>4} {'missed':<15}")
for _, r in top70.head(20).iterrows():
    print(f"{r['K']:>2} {r['X%']:>4.1f} {r['Y_d']:>5} {r['max_close%']:>5.1f} {r['max_pierce%']:>5.1f} {r['keep']:>5} {r['P_W%']:>5.1f}% {r['imp']:>4} {r['missed']:<15}")

print(f"\n=== Configs catching ALL 3 missed (sorted by P_W) ===")
all3 = df[df["n_missed"]==3].sort_values("P_W%", ascending=False)
for _, r in all3.head(10).iterrows():
    print(f"  K={r['K']} X≤{r['X%']}% Y≥{r['Y_d']}d CL≤{r['max_close%']}% PR≤{r['max_pierce%']}% → keep={r['keep']} conf={r['conf']} P(W)={r['P_W%']:.1f}% imp={r['imp']}")

print(f"\n=== Configs catching ≥2 missed with P_W ≥ 70% ===")
two70 = df[(df["n_missed"]>=2) & (df["P_W%"]>=70)].sort_values("P_W%", ascending=False)
for _, r in two70.head(10).iterrows():
    print(f"  K={r['K']} X≤{r['X%']}% Y≥{r['Y_d']}d CL≤{r['max_close%']}% PR≤{r['max_pierce%']}% → keep={r['keep']} P(W)={r['P_W%']:.1f}% imp={r['imp']} missed={r['missed']}")
