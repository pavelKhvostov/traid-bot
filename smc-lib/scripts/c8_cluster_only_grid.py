"""C8 cluster-only grid (без age, без alignment): просто ≥K swept VWAPs in spread ≤X%.

Узнать чистую precision cluster-логики.
"""
from __future__ import annotations
import pickle
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd

CACHE = Path.home() / "Desktop" / "_bar_swept_simple.pkl"
CSV_PATH = Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
BASE_PATH = Path.home() / "Desktop" / "baseline_1267.parquet"
TF_D_MS = 1440 * 60_000
TF_12H_MS = 720 * 60_000
START_MS = int(datetime(2020,1,1,tzinfo=timezone.utc).timestamp() * 1000)

DIRS={"#14":"high","#15":"low","#48":"high"}
TIMES={"#14":int(datetime(2026,3,4,12,0,tzinfo=timezone.utc).timestamp()*1000),
       "#15":int(datetime(2026,3,8,12,0,tzinfo=timezone.utc).timestamp()*1000),
       "#48":int(datetime(2026,5,6,0,0,tzinfo=timezone.utc).timestamp()*1000)}

if not CACHE.exists():
    import csv
    print("Computing bar swept lists...")
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
    N=2; fractals=[]
    for i in range(N,len(barsD)-N):
        h_i,l_i=barsD[i][1],barsD[i][2]
        if all(h_i>barsD[i+j][1] for j in [-2,-1,1,2]):
            fractals.append({"ts":barsD[i][0],"side":"FH","ready_ms":barsD[i+N][0]+TF_D_MS})
        if all(l_i<barsD[i+j][2] for j in [-2,-1,1,2]):
            fractals.append({"ts":barsD[i][0],"side":"FL","ready_ms":barsD[i+N][0]+TF_D_MS})
    pv_cum=np.cumsum(cl_arr*vo_arr); vol_cum=np.cumsum(vo_arr)
    def vwap_at(a,q):
        i_a=int(np.searchsorted(ts_arr,a))
        i_q=int(np.searchsorted(ts_arr,q,side='right'))-1
        if i_a>i_q: return None
        pv=pv_cum[i_q]-(pv_cum[i_a-1] if i_a>0 else 0)
        v=vol_cum[i_q]-(vol_cum[i_a-1] if i_a>0 else 0)
        return pv/v if v>0 else None
    df_base=pd.read_parquet(BASE_PATH)
    bar_swept={}
    for bidx,row in df_base.iterrows():
        bo=int(row["ts"]); bc=bo+TF_12H_MS
        side="FH" if row["direction"]=="high" else "FL"
        i_s=int(np.searchsorted(ts_arr,bo)); i_e=int(np.searchsorted(ts_arr,bc))
        if i_e<=i_s: continue
        bh=hi_arr[i_s:i_e].max(); bl=lo_arr[i_s:i_e].min(); bc_p=cl_arr[i_e-1]
        rel=[f for f in fractals if f["side"]==side and f["ready_ms"]<=bo]
        sw=[]
        for f in rel:
            v=vwap_at(f["ts"],bc)
            if v is None: continue
            ok = (bh>v and bc_p<v) if side=="FH" else (bl<v and bc_p>v)
            if ok: sw.append(v)
        bar_swept[bidx] = sorted(sw)
    with CACHE.open("wb") as f: pickle.dump(bar_swept, f)
    print(f"  Cached.")
else:
    with CACHE.open("rb") as f: bar_swept=pickle.load(f)

df_base=pd.read_parquet(BASE_PATH)
missed_idx={}
for tag,t in TIMES.items():
    m=df_base[(df_base["ts"]==t) & (df_base["direction"]==DIRS[tag])]
    if not m.empty: missed_idx[tag]=m.index[0]

# Show missed
for tag, midx in missed_idx.items():
    sw = bar_swept.get(midx, [])
    if sw:
        spread = (max(sw)-min(sw))/np.mean(sw)*100
        print(f"{tag}: n={len(sw)}, vals={[int(v) for v in sw]}, full_spread={spread:.2f}%")
    else:
        print(f"{tag}: NO swept")

# === Grid: cluster K + X spread (no age, no align) ===
print(f"\n=== Cluster-only grid (sweep ≥K within spread ≤X%) ===")
def cluster_passes(vs, K, X):
    if len(vs)<K: return False
    for i in range(len(vs)-K+1):
        window = vs[i:i+K]
        spread = (max(window)-min(window))/np.mean(window)*100
        if spread <= X: return True
    return False

results=[]
for K in [2,3,4,5]:
    for X in [0.5, 1.0, 1.5, 2.0, 3.0]:
        keep=conf=imp=0; caught=[]
        for bidx, sw in bar_swept.items():
            if cluster_passes(sw, K, X):
                keep+=1
                row=df_base.iloc[bidx]
                if row["confirmed"]: conf+=1
                if row["is_important"] and row["confirmed"]: imp+=1
                for tag,midx in missed_idx.items():
                    if bidx==midx: caught.append(tag)
        p_w=conf/keep*100 if keep else 0
        results.append({"K":K,"X%":X,"keep":keep,"conf":conf,"P_W%":round(p_w,1),
                        "imp":imp,"n_missed":len(caught),"missed":"+".join(sorted(caught))})

df=pd.DataFrame(results).sort_values(["P_W%"], ascending=False)
print(f"\n{'K':>2} {'X%':>4} {'keep':>5} {'conf':>5} {'P_W%':>6} {'imp':>4} {'missed':<10}")
for _, r in df.iterrows():
    flag = "★" if r["P_W%"]>=70 else (" " if r["P_W%"]>=65 else " ")
    print(f"{flag} {r['K']:>2} {r['X%']:>4.1f} {r['keep']:>5} {r['conf']:>5} {r['P_W%']:>5.1f}% {r['imp']:>4} {r['missed']:<10}")

# Best for #14 catch
print(f"\nBest configs catching #14:")
m14 = df[df["missed"].str.contains("#14")].sort_values("P_W%", ascending=False)
for _, r in m14.head(10).iterrows():
    print(f"  K={r['K']} X≤{r['X%']}% → keep={r['keep']} conf={r['conf']} P(W)={r['P_W%']:.1f}% imp={r['imp']}")
