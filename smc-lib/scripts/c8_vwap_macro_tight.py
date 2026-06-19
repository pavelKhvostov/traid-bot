"""C8 single-mode: macro-old VWAP sweep + tight pierce + tight close distance.

Simpler than hybrid:
  swept = at least 1 VWAP with:
    age ≥ Y    (macro-old)
    pierce ≤ MP  (wick not too deep)
    close_dist ≤ MC  (close near VWAP)
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

print("Precompute swept VWAPs per bar with metrics...")
df_base=pd.read_parquet(BASE_PATH)
bar_data={}
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
            pierce_pct=(bh-v)/v*100
        else:
            if not (bl<v and bc_p>v): continue
            pierce_pct=(v-bl)/v*100
        close_dist_pct=abs(bc_p-v)/v*100
        age=(bc-f["ts"])/(24*3600_000)
        sw.append((v, age, pierce_pct, close_dist_pct))
    bar_data[bidx]=sw

missed_idx={}
for tag,t in TIMES.items():
    m=df_base[(df_base["ts"]==t) & (df_base["direction"]==DIRS[tag])]
    if not m.empty: missed_idx[tag]=m.index[0]

# === Grid: macro-tight single ===
results=[]
for Y in [365, 500, 730, 1000, 1200]:
    for MP in [0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 1.0]:
        for MC in [0.1, 0.2, 0.3, 0.5, 1.0]:
            keep=conf=imp=0; caught=[]
            for bidx, sw in bar_data.items():
                # at least one VWAP satisfies all 3
                qualified = [(v,a,p,d) for v,a,p,d in sw if a>=Y and p<=MP and d<=MC]
                if qualified:
                    keep+=1
                    row=df_base.iloc[bidx]
                    if row["confirmed"]: conf+=1
                    if row["is_important"] and row["confirmed"]: imp+=1
                    for tag,midx in missed_idx.items():
                        if bidx==midx: caught.append(tag)
            p_w=conf/keep*100 if keep else 0
            results.append({"Y_d":Y,"MP%":MP,"MC%":MC,"keep":keep,"conf":conf,
                            "P_W%":round(p_w,1),"imp":imp,"n_missed":len(caught),
                            "missed":"+".join(sorted(caught))})
df=pd.DataFrame(results)
df.to_csv(Path.home()/"Desktop"/"c8_vwap_macro_tight.csv", index=False)

# Show ALL configs with all 3 caught, sorted by P_W
print(f"\n=== ALL 3 missed caught, sorted by P_W ===")
all3 = df[df["n_missed"]==3].sort_values("P_W%", ascending=False)
print(f"  Total configs: {len(all3)}")
print(f"\n{'Y_d':>5} {'MP%':>5} {'MC%':>5} {'keep':>5} {'conf':>5} {'P_W%':>7} {'imp':>4}")
print("-"*55)
for _, r in all3.head(20).iterrows():
    flag="★" if r["P_W%"]>=70 else (" " if r["P_W%"]>=65 else " ")
    print(f"{flag} {r['Y_d']:>4} {r['MP%']:>5.2f} {r['MC%']:>5.2f} {r['keep']:>5} {r['conf']:>5} {r['P_W%']:>6.1f}% {r['imp']:>4}")

print(f"\n=== Configs with P_W ≥ 70% (any missed) ===")
top = df[(df["P_W%"]>=70) & (df["keep"]>=10)].sort_values(["n_missed","P_W%"], ascending=[False, False])
print(f"  Total: {len(top)}")
for _, r in top.head(15).iterrows():
    print(f"  Y≥{r['Y_d']}d MP≤{r['MP%']}% MC≤{r['MC%']}% → keep={r['keep']} P(W)={r['P_W%']:.1f}% imp={r['imp']} missed={r['missed']}")

# Best ≥2 missed with P_W ≥ 65%
print(f"\n=== ≥2 missed + P_W ≥ 65% ===")
g = df[(df["n_missed"]>=2) & (df["P_W%"]>=65) & (df["keep"]>=20)].sort_values("P_W%", ascending=False)
for _, r in g.head(15).iterrows():
    print(f"  Y≥{r['Y_d']}d MP≤{r['MP%']}% MC≤{r['MC%']}% → keep={r['keep']} P(W)={r['P_W%']:.1f}% imp={r['imp']} missed={r['missed']}")
