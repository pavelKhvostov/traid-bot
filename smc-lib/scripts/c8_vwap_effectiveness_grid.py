"""C8 filter by VWAP effectiveness + total_interactions (per canon Rule 6).

Effectiveness (эффективный) = reactions / interactions on 1h LTF cascade.
Worked (проработанный) = total_interactions count.

For each baseline bar:
  Among swept VWAPs (direction-matched D-fractals), compute:
    composite     — score reactions/interactions on 1h LTF (canon LTF=1h is fastest reliable)
    total_inter   — count of 1h bars where bar.low ≤ VWAP_val ≤ bar.high

Grid:
  min_composite  ∈ {0.3, 0.5, 0.7, 0.9}
  min_total_inter ∈ {5, 10, 20, 50}
"""
from __future__ import annotations
import csv
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd

CSV_PATH = Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
BASE_PATH = Path.home() / "Desktop" / "baseline_1267.parquet"
TF_D_MS = 1440 * 60_000
TF_1H_MS = 60 * 60_000
TF_12H_MS = 720 * 60_000
START_MS = int(datetime(2020,1,1,tzinfo=timezone.utc).timestamp() * 1000)

DIRS={"#14":"high","#15":"low","#48":"high"}
TIMES={"#14":int(datetime(2026,3,4,12,0,tzinfo=timezone.utc).timestamp()*1000),
       "#15":int(datetime(2026,3,8,12,0,tzinfo=timezone.utc).timestamp()*1000),
       "#48":int(datetime(2026,5,6,0,0,tzinfo=timezone.utc).timestamp()*1000)}

print("Loading 1m + aggregating D, 1h...")
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

records=list(zip(ts_arr,hi_arr,lo_arr,cl_arr,vo_arr))
barsD=[b for b in agg(records,TF_D_MS) if b[0]>=START_MS]
bars1h=[b for b in agg(records,TF_1H_MS) if b[0]>=START_MS]
ts_1h=np.array([b[0] for b in bars1h],dtype=np.int64)
hi_1h=np.array([b[1] for b in bars1h]); lo_1h=np.array([b[2] for b in bars1h])
cl_1h=np.array([b[3] for b in bars1h])
print(f"  D: {len(barsD)}, 1h: {len(bars1h)}")

N=2; fractals=[]
for i in range(N,len(barsD)-N):
    h_i,l_i=barsD[i][1],barsD[i][2]
    if all(h_i>barsD[i+j][1] for j in [-2,-1,1,2]):
        fractals.append({"ts":barsD[i][0],"side":"FH","level":h_i})
    if all(l_i<barsD[i+j][2] for j in [-2,-1,1,2]):
        fractals.append({"ts":barsD[i][0],"side":"FL","level":l_i})
for f in fractals:
    f["ready_ms"] = f["ts"] + 3*TF_D_MS
print(f"  Fractals: {len(fractals)}")

pv_cum=np.cumsum(cl_arr*vo_arr); vol_cum=np.cumsum(vo_arr)
def vwap_at(a,q):
    i_a=int(np.searchsorted(ts_arr,a))
    i_q=int(np.searchsorted(ts_arr,q,side='right'))-1
    if i_a>i_q: return None
    pv=pv_cum[i_q]-(pv_cum[i_a-1] if i_a>0 else 0)
    v=vol_cum[i_q]-(vol_cum[i_a-1] if i_a>0 else 0)
    return pv/v if v>0 else None

print("Compute swept VWAPs per baseline bar + effectiveness on 1h LTF...")
df_base=pd.read_parquet(BASE_PATH)

bar_data={}
for bidx,row in df_base.iterrows():
    bo=int(row["ts"]); bc=bo+TF_12H_MS
    side="FH" if row["direction"]=="high" else "FL"
    i_s=int(np.searchsorted(ts_arr,bo)); i_e=int(np.searchsorted(ts_arr,bc))
    if i_e<=i_s: continue
    bh=hi_arr[i_s:i_e].max(); bl=lo_arr[i_s:i_e].min(); bc_p=cl_arr[i_e-1]
    rel=[f for f in fractals if f["side"]==side and f["ready_ms"]<=bo]
    sw=[]
    for f in rel:
        v_now=vwap_at(f["ts"],bc)
        if v_now is None: continue
        if side=="FH":
            if not (bh>v_now and bc_p<v_now): continue
        else:
            if not (bl<v_now and bc_p>v_now): continue
        # Compute effectiveness on 1h LTF from f.ts to bc
        i1_start=int(np.searchsorted(ts_1h, f["ts"]+TF_1H_MS))  # skip anchor bar
        i1_end=int(np.searchsorted(ts_1h, bc, side='right'))
        if i1_end <= i1_start:
            sw.append({"v":v_now,"composite":0,"total_inter":0})
            continue
        interactions=0; reactions=0; breaks=0; prev_side=None
        for k in range(i1_start, i1_end):
            v_k = vwap_at(f["ts"], ts_1h[k]+TF_1H_MS-1)
            if v_k is None: continue
            touched = lo_1h[k] <= v_k <= hi_1h[k]
            cur_side = 'above' if cl_1h[k]>v_k else ('below' if cl_1h[k]<v_k else None)
            if touched and cur_side is not None and prev_side is not None:
                interactions+=1
                if cur_side == prev_side: reactions+=1
                else: breaks+=1
            prev_side = cur_side
        composite = reactions/interactions if interactions>0 else 0.0
        sw.append({"v":v_now,"composite":composite,"total_inter":interactions})
    bar_data[bidx]=sw

missed_idx={}
for tag,t in TIMES.items():
    m=df_base[(df_base["ts"]==t) & (df_base["direction"]==DIRS[tag])]
    if not m.empty: missed_idx[tag]=m.index[0]

# === Show missed metrics ===
print(f"\n=== Missed pivots: swept VWAPs metrics ===")
for tag, midx in missed_idx.items():
    sw = bar_data.get(midx, [])
    print(f"\n{tag} (n_swept={len(sw)}):")
    for x in sw:
        print(f"  v={x['v']:.0f}  composite={x['composite']:.2f}  total_inter={x['total_inter']}")

# === Grid ===
print(f"\n=== Grid: filter by composite + total_inter ===")
results=[]
for min_comp in [0.0, 0.3, 0.5, 0.7]:
    for min_tot in [0, 5, 10, 20]:
        for min_count in [1, 2]:
            keep=conf=imp=0; caught=[]
            for bidx, sw in bar_data.items():
                qual = [x for x in sw if x["composite"]>=min_comp and x["total_inter"]>=min_tot]
                if len(qual) < min_count: continue
                keep+=1
                row=df_base.iloc[bidx]
                if row["confirmed"]: conf+=1
                if row["is_important"] and row["confirmed"]: imp+=1
                for tag,midx in missed_idx.items():
                    if bidx==midx: caught.append(tag)
            p_w=conf/keep*100 if keep else 0
            results.append({"min_comp":min_comp,"min_tot":min_tot,"min_count":min_count,
                            "keep":keep,"conf":conf,"P_W%":round(p_w,1),
                            "imp":imp,"n_missed":len(caught),"missed":"+".join(sorted(caught))})
df=pd.DataFrame(results)
df.to_csv(Path.home()/"Desktop"/"c8_vwap_effectiveness_grid.csv", index=False)

print(f"\nConfigs with P_W ≥ 70%:")
top=df[(df["P_W%"]>=70) & (df["keep"]>=20)].sort_values(["n_missed","P_W%"], ascending=[False, False])
print(f"  Total: {len(top)}")
for _, r in top.head(15).iterrows():
    print(f"  comp≥{r['min_comp']:.1f} tot≥{r['min_tot']} count≥{r['min_count']} → keep={r['keep']} conf={r['conf']} P(W)={r['P_W%']:.1f}% imp={r['imp']} missed={r['missed']}")

print(f"\nTop 10 catching missed:")
m = df[df["n_missed"]>=1].sort_values(["n_missed","P_W%"], ascending=[False, False])
for _, r in m.head(15).iterrows():
    print(f"  comp≥{r['min_comp']:.1f} tot≥{r['min_tot']} count≥{r['min_count']} → keep={r['keep']} P(W)={r['P_W%']:.1f}% imp={r['imp']} missed={r['missed']}")
