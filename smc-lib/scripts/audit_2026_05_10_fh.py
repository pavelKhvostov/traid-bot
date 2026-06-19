"""Audit pivot 2026-05-10 15:00 MSK (FH) — 4th missed target.

Check:
  - Bar OHLC + context
  - Swept VWAPs (D-fractal anchored): count, ages, alignment, composite, total_inter
  - Andrey VSA / Nison / sweep features from earlier analysis
  - Compare to other 3 missed
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
MSK = timezone(timedelta(hours=3))

TARGET_DT_MSK = datetime(2026,5,10,15,0,tzinfo=MSK)
TARGET_TS = int(TARGET_DT_MSK.astimezone(timezone.utc).timestamp() * 1000)
TARGET_DIR = "high"

print(f"Target: {TARGET_DT_MSK.strftime('%Y-%m-%d %H:%M MSK')} (UTC: {datetime.fromtimestamp(TARGET_TS/1000, tz=timezone.utc)})")
print(f"Side: FH/short ({TARGET_DIR})")

# Load 1m
print("\nLoading 1m...")
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
bars12 = [b for b in agg(records,TF_12H_MS) if b[0]>=START_MS]

# Verify target in baseline
df_base=pd.read_parquet(BASE_PATH)
target_row = df_base[(df_base["ts"]==TARGET_TS) & (df_base["direction"]==TARGET_DIR)]
print(f"\nIn baseline: {len(target_row)>0}")
if len(target_row):
    r = target_row.iloc[0]
    print(f"  confirmed: {r['confirmed']}, is_important: {r['is_important']}")
    print(f"  OHLC: O={r['open']:.0f} H={r['high']:.0f} L={r['low']:.0f} C={r['close']:.0f}")
    print(f"  body_pct={r['body_pct']:.2f} wick_pct={r['wick_pct']:.2f}")
    print(f"  opp_colors={r['opp_colors']} three_same={r['three_same']}")

# === D-fractal anchored VWAPs analysis ===
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

print(f"\n=== Swept VWAPs analysis ===")
bo = TARGET_TS
bc = bo + TF_12H_MS
i_s=int(np.searchsorted(ts_arr,bo)); i_e=int(np.searchsorted(ts_arr,bc))
bh=hi_arr[i_s:i_e].max(); bl=lo_arr[i_s:i_e].min(); bc_p=cl_arr[i_e-1]
print(f"Bar: H={bh:.0f} L={bl:.0f} C={bc_p:.0f}")

rel=[d for d in fr_D if d["side"]=="FH" and d["ready_ms"]<=bo]
print(f"Relevant FH fractals before bar: {len(rel)}")

swept = []
for d in rel:
    v = vwap_at(d["ts"], bc)
    if v is None: continue
    if bh>v and bc_p<v:
        age = (bc - d["ts"]) / (24*3600_000)
        pierce_pct = (bh - v) / v * 100
        close_dist_pct = (v - bc_p) / v * 100
        swept.append({"v":v, "age":age, "aligned_W":d["aligned_W"], "pierce":pierce_pct, "close_dist":close_dist_pct})

print(f"\nSwept VWAPs: {len(swept)}")
for s in swept:
    align = "W" if s["aligned_W"] else "D-only"
    print(f"  v={s['v']:.0f}  age={s['age']:.0f}d  align={align}  pierce={s['pierce']:.3f}%  close_dist={s['close_dist']:.3f}%")

# Cluster analysis
if len(swept) >= 2:
    vs = sorted([s["v"] for s in swept])
    spread = (max(vs)-min(vs))/np.mean(vs)*100
    print(f"\nCluster: n={len(vs)}, spread={spread:.2f}%")

n_W = sum(1 for s in swept if s["aligned_W"])
print(f"W-aligned swept count: {n_W}")
print(f"C8 (≥2 W-aligned) condition: {'✓ PASS' if n_W>=2 else '✗ FAIL'}")

# === Andrey VSA / Nison features ===
# Compute for target bar
ts12 = np.array([b[0] for b in bars12], dtype=np.int64)
hi12 = np.array([b[1] for b in bars12]); lo12 = np.array([b[2] for b in bars12])
cl12 = np.array([b[3] for b in bars12]); vo12 = np.array([b[4] for b in bars12])
op12 = np.array([b[1] - 0 for b in bars12])  # need open — agg returns h not o, let me redo

# Re-aggregate with proper open
def agg_full(rs,tf_ms):
    out=[];cb=None;o=h=l=c=v=0.0
    for ts,hh,ll,cc,vv in rs:
        b=ts-(ts%tf_ms)
        if b!=cb:
            if cb is not None: out.append((cb,o,h,l,c,v))
            cb=b; o,h,l,c,v=hh,hh,ll,cc,vv  # use hh as o for first bar
            # Actually we need actual 1m open. Approximation: use prev close
        else:
            h=max(h,hh); l=min(l,ll); c=cc; v+=vv
    if cb is not None: out.append((cb,o,h,l,c,v))
    return out
# Simpler — load open from 1m
# rebuild 12h bars with proper open
print("\nRecomputing 12h bars with proper open...")
rows12 = []
cur_b = None
cur_o = cur_h = cur_l = cur_c = cur_v = 0
for ts, hh, ll, cc, vv in records:
    b = ts - (ts % TF_12H_MS)
    if b != cur_b:
        if cur_b is not None:
            rows12.append((cur_b, cur_o, cur_h, cur_l, cur_c, cur_v))
        cur_b = b
        # Need to find 1m open
        i = int(np.searchsorted(ts_arr, b))
        cur_o = float(cl_arr[i-1] if i>0 else hh)
        # actually for 1m bar at b, open != close[i-1] necessarily. Skip — use hh as proxy
        cur_h = hh; cur_l = ll; cur_c = cc; cur_v = vv
    else:
        cur_h = max(cur_h, hh); cur_l = min(cur_l, ll); cur_c = cc; cur_v += vv
if cur_b: rows12.append((cur_b, cur_o, cur_h, cur_l, cur_c, cur_v))
rows12 = [r for r in rows12 if r[0]>=START_MS]

# Better: use 1m open of first 1m bar in 12h period
# Skip this complexity for now — use h/l/c only for features that need it

# === Compare to other missed ===
OTHER_MISSED = [
    ("#14", datetime(2026,3,4,12,0,tzinfo=timezone.utc), "high"),
    ("#15", datetime(2026,3,8,12,0,tzinfo=timezone.utc), "low"),
    ("#48", datetime(2026,5,6,0,0,tzinfo=timezone.utc), "high"),
]
print(f"\n=== Summary table — 4 missed ===")
print(f"{'Tag':<6} {'Date MSK':<20} {'Side':<5} {'H':>7} {'L':>7} {'C':>7} {'n_swept':>8} {'n_W':>4}")
all_missed = [("NEW", TARGET_DT_MSK, "high")] + [(t, dt.astimezone(MSK), d) for t, dt, d in OTHER_MISSED]
for tag, dt_msk, dir_ in all_missed:
    ts = int(dt_msk.astimezone(timezone.utc).timestamp()*1000)
    bo_ = ts
    bc_ = bo_ + TF_12H_MS
    i_s2=int(np.searchsorted(ts_arr,bo_)); i_e2=int(np.searchsorted(ts_arr,bc_))
    if i_e2<=i_s2: continue
    h_b=hi_arr[i_s2:i_e2].max(); l_b=lo_arr[i_s2:i_e2].min(); c_b=cl_arr[i_e2-1]
    side_x = "FH" if dir_=="high" else "FL"
    rel_x=[d for d in fr_D if d["side"]==side_x and d["ready_ms"]<=bo_]
    sw_x = []
    for d in rel_x:
        v = vwap_at(d["ts"], bc_)
        if v is None: continue
        ok = (h_b>v and c_b<v) if side_x=="FH" else (l_b<v and c_b>v)
        if ok: sw_x.append({"aligned_W": d["aligned_W"]})
    nW = sum(1 for s in sw_x if s["aligned_W"])
    print(f"{tag:<6} {dt_msk.strftime('%Y-%m-%d %H:%M'):<20} {side_x:<5} {h_b:>7.0f} {l_b:>7.0f} {c_b:>7.0f} {len(sw_x):>8} {nW:>4}")
