"""C8 with VWAP-slope filter.

For each swept VWAP:
  slope = VWAP(now) - VWAP(now - LOOKBACK_DAYS)
  Direction-correct slope:
    FH (predicting top): slope_pct < 0  (descending resistance)
    FL (predicting bot): slope_pct > 0  (ascending support)

Grid:
  LOOKBACK ∈ {7, 14, 30, 60}  days
  min_correct_slope_swept ∈ {1, 2}  (how many swept VWAPs must have correct slope)
  combined with hybrid / aligned filters
"""
from __future__ import annotations
import csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

CSV_PATH = Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
BASE_PATH = Path.home() / "Desktop" / "baseline_1267.parquet"
TF_D_MS = 1440*60_000
TF_W_MS = 7*TF_D_MS
TF_12H_MS = 720*60_000
START_MS = int(datetime(2020,1,1,tzinfo=timezone.utc).timestamp()*1000)
MON_ANCHOR = int(datetime(2020,1,6,tzinfo=timezone.utc).timestamp()*1000)

DIRS={"#14":"high","#15":"low","#48":"high"}
TIMES={"#14":int(datetime(2026,3,4,12,0,tzinfo=timezone.utc).timestamp()*1000),
       "#15":int(datetime(2026,3,8,12,0,tzinfo=timezone.utc).timestamp()*1000),
       "#48":int(datetime(2026,5,6,0,0,tzinfo=timezone.utc).timestamp()*1000)}

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
for d in fr_D:
    d["aligned_W"] = any(w["side"]==d["side"] and w["ts"]<=d["ts"]<w["ts"]+TF_W_MS and abs(w["level"]-d["level"])<0.01 for w in fr_W)
    d["ready_ms"] = d["ts"] + 3*TF_D_MS

pv_cum=np.cumsum(cl_arr*vo_arr); vol_cum=np.cumsum(vo_arr)
def vwap_at(a,q):
    i_a=int(np.searchsorted(ts_arr,a))
    i_q=int(np.searchsorted(ts_arr,q,side='right'))-1
    if i_a>i_q: return None
    pv=pv_cum[i_q]-(pv_cum[i_a-1] if i_a>0 else 0)
    v=vol_cum[i_q]-(vol_cum[i_a-1] if i_a>0 else 0)
    return pv/v if v>0 else None

print("Precompute swept VWAPs per baseline bar with slope info...")
df_base=pd.read_parquet(BASE_PATH)

# Configurable lookback for slope; compute for each
LOOKBACKS = [7, 14, 30, 60]
LOOKBACK_MS = {d: d*TF_D_MS for d in LOOKBACKS}

# Per bar: for each swept VWAP, compute slope over each lookback
print("This is computationally heavy; precomputing all...")
bar_data={}
for bidx,row in df_base.iterrows():
    bo=int(row["ts"]); bc=bo+TF_12H_MS
    side="FH" if row["direction"]=="high" else "FL"
    i_s=int(np.searchsorted(ts_arr,bo)); i_e=int(np.searchsorted(ts_arr,bc))
    if i_e<=i_s: continue
    bh=hi_arr[i_s:i_e].max(); bl=lo_arr[i_s:i_e].min(); bc_p=cl_arr[i_e-1]
    rel=[d for d in fr_D if d["side"]==side and d["ready_ms"]<=bo]
    sw=[]
    for d in rel:
        v_now=vwap_at(d["ts"],bc)
        if v_now is None: continue
        if side=="FH":
            if not (bh>v_now and bc_p<v_now): continue
        else:
            if not (bl<v_now and bc_p>v_now): continue
        age=(bc-d["ts"])/(24*3600_000)
        # slope per lookback
        slopes = {}
        for LB_d, LB_ms in LOOKBACK_MS.items():
            q_past = bc - LB_ms
            if q_past <= d["ts"]:
                slopes[LB_d] = None  # VWAP didn't exist that far back
                continue
            v_past = vwap_at(d["ts"], q_past)
            if v_past is None or v_past == 0:
                slopes[LB_d] = None
                continue
            slopes[LB_d] = (v_now - v_past) / v_past * 100  # % change
        sw.append({"v":v_now,"age":age,"aligned_W":d["aligned_W"],"slopes":slopes})
    bar_data[bidx] = sw

missed_idx={}
for tag,t in TIMES.items():
    m=df_base[(df_base["ts"]==t) & (df_base["direction"]==DIRS[tag])]
    if not m.empty: missed_idx[tag]=m.index[0]

# === Show missed slopes ===
print(f"\n=== Missed pivots: swept VWAPs slopes ===")
for tag, midx in missed_idx.items():
    sw = bar_data.get(midx, [])
    side = "FH" if DIRS[tag]=="high" else "FL"
    print(f"\n{tag} ({side}): expected slope sign: {'< 0' if side=='FH' else '> 0'}")
    for x in sw[:6]:
        slopes_str = ", ".join(f"{lb}d:{x['slopes'][lb]:+.2f}%" if x['slopes'][lb] is not None else f"{lb}d:n/a" for lb in LOOKBACKS)
        align = "W" if x['aligned_W'] else ""
        print(f"  v={x['v']:.0f} age={x['age']:.0f}d {align:<3} slopes: {slopes_str}")

# === Grid: filter by slope ===
def slope_correct(slope, side):
    if slope is None: return None
    if side == "FH": return slope < 0  # descending resistance
    else: return slope > 0  # ascending support

print(f"\n=== Grid: WR by slope filter ===")
results=[]
for LB in LOOKBACKS:
    for min_correct in [1, 2]:
        for require_W_align in [False, True]:
            keep=conf=imp=0; caught=[]
            for bidx, sw in bar_data.items():
                side = "FH" if df_base.iloc[bidx]["direction"]=="high" else "FL"
                if require_W_align:
                    sw_x = [x for x in sw if x["aligned_W"]]
                else:
                    sw_x = sw
                correct = sum(1 for x in sw_x if slope_correct(x["slopes"].get(LB), side) == True)
                if correct < min_correct: continue
                keep+=1
                row=df_base.iloc[bidx]
                if row["confirmed"]: conf+=1
                if row["is_important"] and row["confirmed"]: imp+=1
                for tag,midx in missed_idx.items():
                    if bidx==midx: caught.append(tag)
            p_w=conf/keep*100 if keep else 0
            results.append({"LB_d":LB,"min_correct":min_correct,"W_align":require_W_align,
                            "keep":keep,"conf":conf,"P_W%":round(p_w,1),
                            "imp":imp,"n_missed":len(caught),"missed":"+".join(sorted(caught))})

df=pd.DataFrame(results)
df.to_csv(Path.home()/"Desktop"/"c8_vwap_slope_grid.csv", index=False)

print(f"\n{'LB':>3} {'k≥':>3} {'W?':>3} {'keep':>5} {'conf':>5} {'P_W%':>6} {'imp':>4} {'missed':<15}")
print("-"*65)
for _, r in df.sort_values(["P_W%"], ascending=False).iterrows():
    flag = "★" if r["P_W%"]>=70 else (" " if r["P_W%"]>=65 else " ")
    w = "W" if r["W_align"] else "-"
    print(f"{flag} {r['LB_d']:>3} {r['min_correct']:>3} {w:>3} {r['keep']:>5} {r['conf']:>5} {r['P_W%']:>5.1f}% {r['imp']:>4} {r['missed']:<15}")
