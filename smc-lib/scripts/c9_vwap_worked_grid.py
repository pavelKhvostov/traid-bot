"""C9 grid: проработанный VWAP (high total_interactions + moderate composite).

Target: catch #15 / #48 (very-worked levels) with WR ≥ 70%.
Pre-compute bar_data once, then scan grid.
"""
from __future__ import annotations
import csv, pickle
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd

CACHE = Path.home() / "Desktop" / "_bar_data_effectiveness.pkl"
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

if not CACHE.exists():
    print("Loading 1m + computing bar_data...")
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
            i1_s=int(np.searchsorted(ts_1h, f["ts"]+TF_1H_MS))
            i1_e=int(np.searchsorted(ts_1h, bc, side='right'))
            if i1_e<=i1_s:
                sw.append({"v":v_now,"composite":0,"total_inter":0}); continue
            interactions=0; reactions=0; breaks=0; prev_side=None
            for k in range(i1_s, i1_e):
                v_k = vwap_at(f["ts"], ts_1h[k]+TF_1H_MS-1)
                if v_k is None: continue
                touched = lo_1h[k]<=v_k<=hi_1h[k]
                cur = 'above' if cl_1h[k]>v_k else ('below' if cl_1h[k]<v_k else None)
                if touched and cur is not None and prev_side is not None:
                    interactions+=1
                    if cur==prev_side: reactions+=1
                    else: breaks+=1
                prev_side=cur
            composite = reactions/interactions if interactions>0 else 0.0
            sw.append({"v":v_now,"composite":composite,"total_inter":interactions})
        bar_data[bidx]=sw
    with CACHE.open("wb") as f: pickle.dump(bar_data, f)
    print(f"  Cached to {CACHE}")
else:
    print(f"Loading cached bar_data from {CACHE}...")
    with CACHE.open("rb") as f: bar_data=pickle.load(f)

df_base=pd.read_parquet(BASE_PATH)
missed_idx={}
for tag,t in TIMES.items():
    m=df_base[(df_base["ts"]==t) & (df_base["direction"]==DIRS[tag])]
    if not m.empty: missed_idx[tag]=m.index[0]

# === C9 grid (focused on проработанность) ===
print(f"\n=== C9 grid: high total_inter + moderate composite ===")
results=[]
for min_comp in [0.30, 0.40, 0.45, 0.50, 0.55]:
    for min_tot in [50, 100, 150, 200, 250, 300]:
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
df.to_csv(Path.home()/"Desktop"/"c9_vwap_worked_grid.csv", index=False)

print(f"\nConfigs catching #15 OR #48 (sorted by P_W):")
m48_15 = df[df["missed"].apply(lambda s: "#15" in s or "#48" in s)].sort_values("P_W%", ascending=False)
print(f"  Total: {len(m48_15)}")
print(f"{'comp':>5} {'tot':>4} {'cnt':>3} {'keep':>5} {'conf':>5} {'P_W%':>6} {'imp':>4} {'missed':<15}")
for _, r in m48_15.head(20).iterrows():
    flag = "★" if r["P_W%"]>=70 else " "
    print(f"{flag} {r['min_comp']:>4.2f} {r['min_tot']:>4} {r['min_count']:>3} {r['keep']:>5} {r['conf']:>5} {r['P_W%']:>5.1f}% {r['imp']:>4} {r['missed']:<15}")

print(f"\nConfigs catching ALL 3 missed:")
all3 = df[df["n_missed"]==3].sort_values("P_W%", ascending=False)
print(f"  Total: {len(all3)}")
for _, r in all3.head(10).iterrows():
    print(f"  comp≥{r['min_comp']:.2f} tot≥{r['min_tot']} count≥{r['min_count']} → keep={r['keep']} conf={r['conf']} P(W)={r['P_W%']:.1f}% imp={r['imp']}")

print(f"\nConfigs catching #15 AND #48 (without #14):")
m15_48 = df[df["missed"].apply(lambda s: "#15" in s and "#48" in s and "#14" not in s)].sort_values("P_W%", ascending=False)
print(f"  Total: {len(m15_48)}")
for _, r in m15_48.head(10).iterrows():
    print(f"  comp≥{r['min_comp']:.2f} tot≥{r['min_tot']} count≥{r['min_count']} → keep={r['keep']} conf={r['conf']} P(W)={r['P_W%']:.1f}% imp={r['imp']}")
