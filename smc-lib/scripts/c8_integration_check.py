"""Compute basket C1-C7 ∪ C8 (W-aligned swept VWAPs ≥2).

C8 spec:
  side-direction-matched D-fractal anchored VWAPs that are also W-fractal aligned;
  count of SWEPT (high>VWAP & close<VWAP for FH; mirror FL) ≥ 2.

Reports: new basket size, P(W), imp coverage, missed status.
"""
from __future__ import annotations
import csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

CSV_PATH = Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
BASE_PATH = Path.home() / "Desktop" / "baseline_1267.parquet"
C1C7_PATH = Path.home() / "Desktop" / "pred12h_baseline_c1c7.parquet"
TF_D_MS = 1440*60_000
TF_3D_MS = 3*TF_D_MS
TF_W_MS = 7*TF_D_MS
TF_12H_MS = 720*60_000
START_MS = int(datetime(2020,1,1,tzinfo=timezone.utc).timestamp()*1000)
MON_ANCHOR = int(datetime(2020,1,6,tzinfo=timezone.utc).timestamp()*1000)

print("Loading...")
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

def agg(rs,tf_ms,anchor=0):
    out=[];cb=None;h=l=c=v=0.0
    for ts,hh,ll,cc,vv in rs:
        b=ts-((ts-anchor)%tf_ms)
        if b!=cb:
            if cb is not None: out.append((cb,h,l,c,v))
            cb=b; h,l,c,v=hh,ll,cc,vv
        else: h=max(h,hh); l=min(l,ll); c=cc; v+=vv
    if cb is not None: out.append((cb,h,l,c,v))
    return out

records=list(zip(ts_arr,hi_arr,lo_arr,cl_arr,vo_arr))
barsD=[b for b in agg(records,TF_D_MS) if b[0]>=START_MS]
barsW=[b for b in agg(records,TF_W_MS,anchor=MON_ANCHOR) if b[0]>=START_MS]

def detect(bars,N=2):
    out=[]
    for i in range(N,len(bars)-N):
        h_i,l_i=bars[i][1],bars[i][2]
        if all(h_i>bars[i+j][1] for j in [-2,-1,1,2]):
            out.append({"ts":bars[i][0],"side":"FH","level":h_i})
        if all(l_i<bars[i+j][2] for j in [-2,-1,1,2]):
            out.append({"ts":bars[i][0],"side":"FL","level":l_i})
    return out

fr_D=detect(barsD); fr_W=detect(barsW)
print(f"  Fractals: D={len(fr_D)}, W={len(fr_W)}")

# Mark W-alignment
for d in fr_D:
    d["aligned_W"] = False
    for w in fr_W:
        if w["side"]==d["side"] and w["ts"]<=d["ts"]<w["ts"]+TF_W_MS and abs(w["level"]-d["level"])<0.01:
            d["aligned_W"] = True
            break
    d["ready_ms"] = d["ts"] + 3*TF_D_MS

n_W = sum(1 for d in fr_D if d["aligned_W"])
print(f"  D fractals W-aligned: {n_W} ({n_W/len(fr_D)*100:.1f}%)")

pv_cum=np.cumsum(cl_arr*vo_arr); vol_cum=np.cumsum(vo_arr)
def vwap_at(a,q):
    i_a=int(np.searchsorted(ts_arr,a))
    i_q=int(np.searchsorted(ts_arr,q,side='right'))-1
    if i_a>i_q: return None
    pv=pv_cum[i_q]-(pv_cum[i_a-1] if i_a>0 else 0)
    v=vol_cum[i_q]-(vol_cum[i_a-1] if i_a>0 else 0)
    return pv/v if v>0 else None

print("Compute C8 trigger per baseline bar (≥2 W-aligned swept VWAPs)...")
df_base=pd.read_parquet(BASE_PATH)
df_base["c8"] = False
for bidx,row in df_base.iterrows():
    bo=int(row["ts"]); bc=bo+TF_12H_MS
    side="FH" if row["direction"]=="high" else "FL"
    i_s=int(np.searchsorted(ts_arr,bo)); i_e=int(np.searchsorted(ts_arr,bc))
    if i_e<=i_s: continue
    bh=hi_arr[i_s:i_e].max(); bl=lo_arr[i_s:i_e].min(); bc_p=cl_arr[i_e-1]
    rel=[d for d in fr_D if d["side"]==side and d["ready_ms"]<=bo and d["aligned_W"]]
    n_swept=0
    for d in rel:
        v=vwap_at(d["ts"],bc)
        if v is None: continue
        if side=="FH":
            if bh>v and bc_p<v: n_swept+=1
        else:
            if bl<v and bc_p>v: n_swept+=1
    if n_swept >= 2:
        df_base.at[bidx, "c8"] = True

n_c8 = df_base["c8"].sum()
conf_c8 = df_base[df_base["c8"]]["confirmed"].sum()
print(f"  C8 keeps: {n_c8}, conf: {conf_c8}, P(W)={conf_c8/n_c8*100:.1f}%")

# === Merge with C1-C7 basket ===
df_c1c7 = pd.read_parquet(C1C7_PATH)
df_c1c7["key"] = df_c1c7["pivot_open_ts_ms"].astype(str) + "_" + df_c1c7.get("direction", pd.Series(["?"]*len(df_c1c7))).astype(str)
df_base["key"] = df_base["ts"].astype(str) + "_" + df_base["direction"].astype(str)

# Align: c1c7 has 1272 rows, we have 1275 baseline. Some new bars after 2026-05-27
c1c7_basket_keys = set(df_c1c7[df_c1c7["in_basket"]==True]["key"])
df_base["in_c1c7"] = df_base["key"].isin(c1c7_basket_keys)

# New basket = C1-C7 ∪ C8
df_base["in_new_basket"] = df_base["in_c1c7"] | df_base["c8"]

print(f"\nBasket stats:")
print(f"  C1-C7 basket: keep={df_base['in_c1c7'].sum()}, conf={df_base[df_base['in_c1c7']]['confirmed'].sum()}, P(W)={df_base[df_base['in_c1c7']]['confirmed'].mean()*100:.1f}%, imp={df_base[df_base['in_c1c7'] & df_base['is_important'] & df_base['confirmed']].shape[0]}/18")
print(f"  C8 alone:     keep={df_base['c8'].sum()}, conf={df_base[df_base['c8']]['confirmed'].sum()}, P(W)={df_base[df_base['c8']]['confirmed'].mean()*100:.1f}%, imp={df_base[df_base['c8'] & df_base['is_important'] & df_base['confirmed']].shape[0]}")
print(f"  New basket (C1∪…∪C8): keep={df_base['in_new_basket'].sum()}, conf={df_base[df_base['in_new_basket']]['confirmed'].sum()}, P(W)={df_base[df_base['in_new_basket']]['confirmed'].mean()*100:.1f}%, imp={df_base[df_base['in_new_basket'] & df_base['is_important'] & df_base['confirmed']].shape[0]}/18")
print(f"  Overlap (C8 ∩ C1-C7): {df_base[df_base['c8'] & df_base['in_c1c7']].shape[0]}")
print(f"  C8 unique (not in C1-C7): {df_base[df_base['c8'] & ~df_base['in_c1c7']].shape[0]}")

c8_unique = df_base[df_base['c8'] & ~df_base['in_c1c7']]
print(f"  C8 unique events conf rate: {c8_unique['confirmed'].mean()*100:.1f}% ({c8_unique['confirmed'].sum()}/{len(c8_unique)})")

# Save updated basket
out = Path.home() / "Desktop" / "pred12h_basket_c1c8.parquet"
df_base.to_parquet(out, index=False)
print(f"\n→ Saved: {out}")
