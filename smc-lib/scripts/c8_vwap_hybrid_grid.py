"""C8 hybrid: cluster OR macro-single VWAP sweep.

Two filter types in OR:
  A. cluster_K_X:   ≥K swept VWAPs in spread ≤X%
  B. macro_single_Y: ≥1 swept VWAP with age ≥Y days

Grid:
  K ∈ {2, 3}        cluster size requirement
  X ∈ {1.0, 1.5}    cluster spread max %
  Y ∈ {365, 500, 730, 1000}   macro age min days
"""
from __future__ import annotations
import csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

# Reuse precompute logic but inline for clarity
CSV_PATH = Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
BASE_PATH = Path.home() / "Desktop" / "baseline_1267.parquet"
TF_D_MS = 1440 * 60_000
TF_12H_MS = 720 * 60_000
START_MS = int(datetime(2020,1,1,tzinfo=timezone.utc).timestamp() * 1000)

DIRS = {"#14":"high","#15":"low","#48":"high"}
TIMES = {"#14":int(datetime(2026,3,4,12,0,tzinfo=timezone.utc).timestamp()*1000),
         "#15":int(datetime(2026,3,8,12,0,tzinfo=timezone.utc).timestamp()*1000),
         "#48":int(datetime(2026,5,6,0,0,tzinfo=timezone.utc).timestamp()*1000)}

print("[1/4] Load...")
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

print("[2/4] Precompute swept VWAPs per bar...")
df_base=pd.read_parquet(BASE_PATH)
bar_swept={}
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
        ok = (bh>v and bc_p<v) if side=="FH" else (bl<v and bc_p>v)
        if ok:
            age=(bc-f["ts"])/(24*3600_000)
            sw.append((v,age))
    bar_swept[bidx]=sw

# Map missed → (idx, direction)
missed_idx={}
for tag,t in TIMES.items():
    m=df_base[(df_base["ts"]==t) & (df_base["direction"]==DIRS[tag])]
    if not m.empty: missed_idx[tag]=m.index[0]
print(f"  Missed idx: {missed_idx}")
for tag, midx in missed_idx.items():
    print(f"  {tag} swept: {bar_swept.get(midx, [])[:5]}")

# === Grid (hybrid A ∪ B) ===
print(f"\n[3/4] Grid hybrid (cluster K,X ∪ macro_single Y_days):")

def filter_passes(sweep_list, K, X, Y):
    """True if cluster (K with spread ≤ X) OR macro-single (any age ≥ Y)."""
    if not sweep_list: return False
    # B: macro-single
    if any(a >= Y for _, a in sweep_list):
        return True
    # A: cluster — try all windows of size ≥K
    if len(sweep_list) >= K:
        vs = sorted([v for v, _ in sweep_list])
        # Find any K-window with spread ≤ X
        for i in range(len(vs) - K + 1):
            window = vs[i:i+K]
            spread = (max(window) - min(window)) / np.mean(window) * 100
            if spread <= X:
                return True
    return False

results=[]
for K in [2, 3]:
    for X in [1.0, 1.5]:
        for Y in [365, 500, 730, 1000]:
            keep=conf=imp=0
            caught=[]
            for bidx,sw in bar_swept.items():
                if filter_passes(sw, K, X, Y):
                    keep+=1
                    row=df_base.iloc[bidx]
                    if row["confirmed"]: conf+=1
                    if row["is_important"] and row["confirmed"]: imp+=1
                    for tag,midx in missed_idx.items():
                        if bidx==midx: caught.append(tag)
            p_w=conf/keep*100 if keep else 0
            results.append({"K":K,"X%":X,"Y_d":Y,"keep":keep,"conf":conf,
                            "P_W%":round(p_w,1),"imp":imp,
                            "missed":"+".join(sorted(caught)),
                            "n_missed":len(caught)})

df=pd.DataFrame(results).sort_values(["n_missed","P_W%"], ascending=[False, False])

print(f"\n{'K':>2} {'X%':>4} {'Y_d':>5} {'keep':>5} {'conf':>5} {'P_W%':>6} {'imp':>4} {'missed':<15}")
print("-"*70)
for _,r in df.iterrows():
    flag="★★★" if r["n_missed"]==3 else ("★★" if r["n_missed"]==2 else ("★" if r["n_missed"]==1 else " "))
    print(f"{flag} {r['K']:>2} {r['X%']:>4.1f} {r['Y_d']:>5} {r['keep']:>5} {r['conf']:>5} {r['P_W%']:>5.1f}% {r['imp']:>4} {r['missed']:<15}")

print(f"\nBaseline: 1275 / 620 / 48.6% / 18 imp")
print(f"Canon C1-C7: 654 / 437 / 66.8% / 15 imp")

# Best 3/3
all3 = df[df["n_missed"]==3].sort_values("P_W%", ascending=False)
if len(all3):
    print(f"\n=== Configs catching ALL 3 missed (sorted by P_W) ===")
    for _,r in all3.head(10).iterrows():
        print(f"  K={r['K']} X≤{r['X%']}% Y≥{r['Y_d']}d → keep={r['keep']} conf={r['conf']} P(W)={r['P_W%']:.1f}% imp={r['imp']}")
