"""Grid C8: ≥1 W-aligned swept VWAP + дополнительные критерии.

Цель: ловить NEW (2026-05-10 FH) + #14 (оба имеют 1 W-aligned) при WR ≥70%.

Тестируем:
  min_W           ∈ {1, 2}
  max_pierce_W%   ∈ {∞, 1.0, 0.5, 0.2}    (для W-aligned)
  max_close_W%    ∈ {∞, 1.0, 0.5}
  min_W_age_d     ∈ {0, 90, 365}
"""
from __future__ import annotations
import csv, pickle
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

CSV_PATH = Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
BASE_PATH = Path.home() / "Desktop" / "baseline_1267.parquet"
TF_D_MS = 1440 * 60_000
TF_W_MS = 7 * TF_D_MS
TF_12H_MS = 720 * 60_000
START_MS = int(datetime(2020,1,1,tzinfo=timezone.utc).timestamp() * 1000)
MON_ANCHOR = int(datetime(2020,1,6,tzinfo=timezone.utc).timestamp()*1000)

# 22 targets — but we focus on 4 missed
MISSED = {
    "#14":    (int(datetime(2026,3,4,12,0,tzinfo=timezone.utc).timestamp()*1000), "high"),
    "#15":    (int(datetime(2026,3,8,12,0,tzinfo=timezone.utc).timestamp()*1000), "low"),
    "#48":    (int(datetime(2026,5,6,0,0,tzinfo=timezone.utc).timestamp()*1000), "high"),
    "NEW":    (int(datetime(2026,5,10,12,0,tzinfo=timezone.utc).timestamp()*1000), "high"),
}

# Load 22 targets full
import sys
sys.path.insert(0, str(Path.home()/"smc-lib"))
sys.path.insert(0, str(Path.home()/"smc-lib/prediction-algo"))
from force_model_v3.targets_22 import TARGETS_22_MSK

targets_22 = set()
for t_msk, fh_fl in TARGETS_22_MSK:
    ts_ms = int(pd.Timestamp(t_msk+"+03:00").tz_convert("UTC").timestamp()*1000)
    direction = "high" if fh_fl=="FH" else "low"
    targets_22.add((ts_ms, direction))

print("Loading 1m + computing baseline aligned sweeps...")
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
    d["aligned_W"]=any(w["side"]==d["side"] and w["ts"]<=d["ts"]<w["ts"]+TF_W_MS and abs(w["level"]-d["level"])<0.01 for w in fr_W)
    d["ready_ms"]=d["ts"]+3*TF_D_MS

pv_cum=np.cumsum(cl_arr*vo_arr); vol_cum=np.cumsum(vo_arr)
def vwap_at(a,q):
    i_a=int(np.searchsorted(ts_arr,a))
    i_q=int(np.searchsorted(ts_arr,q,side='right'))-1
    if i_a>i_q: return None
    pv=pv_cum[i_q]-(pv_cum[i_a-1] if i_a>0 else 0)
    v=vol_cum[i_q]-(vol_cum[i_a-1] if i_a>0 else 0)
    return pv/v if v>0 else None

df_base=pd.read_parquet(BASE_PATH)
# Compute swept W-aligned VWAPs per bar with metrics
bar_W_swept = {}  # idx → list of (v, age, pierce_pct, close_dist_pct)
for bidx,row in df_base.iterrows():
    bo=int(row["ts"]); bc=bo+TF_12H_MS
    side="FH" if row["direction"]=="high" else "FL"
    i_s=int(np.searchsorted(ts_arr,bo)); i_e=int(np.searchsorted(ts_arr,bc))
    if i_e<=i_s: continue
    bh=hi_arr[i_s:i_e].max(); bl=lo_arr[i_s:i_e].min(); bc_p=cl_arr[i_e-1]
    rel=[d for d in fr_D if d["side"]==side and d["ready_ms"]<=bo and d["aligned_W"]]
    sw=[]
    for d in rel:
        v=vwap_at(d["ts"],bc)
        if v is None: continue
        if side=="FH":
            if not (bh>v and bc_p<v): continue
            pierce=(bh-v)/v*100
        else:
            if not (bl<v and bc_p>v): continue
            pierce=(v-bl)/v*100
        close_dist=abs(bc_p-v)/v*100
        age=(bc-d["ts"])/(24*3600_000)
        sw.append({"v":v,"age":age,"pierce":pierce,"close_dist":close_dist})
    bar_W_swept[bidx]=sw

# Tag bars as target22
df_base["t22"] = df_base.apply(lambda r: (int(r["ts"]), r["direction"]) in targets_22, axis=1)
missed_idx = {}
for tag, (ts, dir_) in MISSED.items():
    m = df_base[(df_base["ts"]==ts) & (df_base["direction"]==dir_)]
    if not m.empty: missed_idx[tag] = m.index[0]

# === Show missed W-aligned metrics ===
print(f"\n=== Missed W-aligned swept VWAPs metrics ===")
for tag, midx in missed_idx.items():
    sw = bar_W_swept.get(midx, [])
    print(f"\n{tag} (n_W={len(sw)}):")
    for s in sw:
        print(f"  v={s['v']:.0f}  age={s['age']:.0f}d  pierce={s['pierce']:.3f}%  close_dist={s['close_dist']:.3f}%")

# === Grid ===
print(f"\n=== Grid: ≥1 W-aligned swept + supplementary ===")
def filter_pass(sw_list, min_W, max_pierce, max_close, min_age):
    valid = [s for s in sw_list if s["pierce"]<=max_pierce and s["close_dist"]<=max_close and s["age"]>=min_age]
    return len(valid) >= min_W

results=[]
for min_W in [1, 2]:
    for max_pierce in [1.0, 0.5, 0.3, 0.2, 0.1, 0.05]:
        for max_close in [1.0, 0.5, 0.3]:
            for min_age in [0, 90, 365]:
                keep=conf=imp=t22=0; caught=[]
                for bidx, sw in bar_W_swept.items():
                    if filter_pass(sw, min_W, max_pierce, max_close, min_age):
                        keep+=1
                        row=df_base.iloc[bidx]
                        if row["confirmed"]: conf+=1
                        if row["is_important"] and row["confirmed"]: imp+=1
                        if row["t22"] and row["confirmed"]: t22+=1
                        for tag,midx in missed_idx.items():
                            if bidx==midx: caught.append(tag)
                p_w=conf/keep*100 if keep else 0
                results.append({"min_W":min_W,"max_pierce":max_pierce,"max_close":max_close,
                                "min_age":min_age,"keep":keep,"conf":conf,"P_W%":round(p_w,1),
                                "imp":imp,"t22":t22,"n_missed":len(caught),
                                "missed":"+".join(sorted(caught))})
df=pd.DataFrame(results)
df.to_csv(Path.home()/"Desktop"/"c8_w_aligned_grid.csv", index=False)

# Show top by # missed caught + WR
print(f"\nConfigs with P_W ≥ 70%:")
top70=df[(df["P_W%"]>=70) & (df["keep"]>=15)].sort_values(["n_missed","P_W%"], ascending=[False, False])
print(f"  Total: {len(top70)}")
print(f"{'mW':>2} {'pi%':>4} {'cl%':>4} {'age':>3} {'keep':>5} {'conf':>5} {'P_W%':>6} {'imp':>4} {'t22':>4} {'missed':<15}")
for _, r in top70.head(20).iterrows():
    print(f"{r['min_W']:>2} {r['max_pierce']:>4.2f} {r['max_close']:>4.1f} {r['min_age']:>3} {r['keep']:>5} {r['conf']:>5} {r['P_W%']:>5.1f}% {r['imp']:>4} {r['t22']:>4} {r['missed']:<15}")

print(f"\nConfigs catching ≥2 missed:")
mul=df[df["n_missed"]>=2].sort_values("P_W%", ascending=False)
print(f"  Total: {len(mul)}")
for _, r in mul.head(10).iterrows():
    print(f"  min_W={r['min_W']} pi≤{r['max_pierce']}% cl≤{r['max_close']}% age≥{r['min_age']}d → keep={r['keep']} P(W)={r['P_W%']:.1f}% t22={r['t22']} missed={r['missed']}")

print(f"\nConfigs catching NEW + #14 (W-aligned group) with P_W ≥ 65%:")
ng=df[df["missed"].apply(lambda s: "NEW" in s and "#14" in s) & (df["P_W%"]>=65)].sort_values("P_W%", ascending=False)
print(f"  Total: {len(ng)}")
for _, r in ng.head(15).iterrows():
    print(f"  min_W={r['min_W']} pi≤{r['max_pierce']}% cl≤{r['max_close']}% age≥{r['min_age']}d → keep={r['keep']} P(W)={r['P_W%']:.1f}% t22={r['t22']} missed={r['missed']}")
