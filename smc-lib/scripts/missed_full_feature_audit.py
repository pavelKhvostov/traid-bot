"""Полный аудит 4 missed: что из всех известных features fires на каждом.

Sources:
  1. Andrey VSA/Nison/sweep features (precomputed via baseline_andrey_features_xjoin)
  2. Andrey ML signals (etap_173_signals_caught.csv)
  3. Bulkowski patterns nearby (etap_172_signals.csv ±5d window)
  4. C1-C7 basket (already known: 0 conditions fire — they're missed)
  5. VWAP swept count/aged/aligned (recap)
"""
from __future__ import annotations
import csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

CSV_PATH = Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
BASE_PATH = Path.home() / "Desktop" / "baseline_1267.parquet"
TF_12H_MS = 720 * 60_000
TF_D_MS = 1440 * 60_000
START_MS = int(datetime(2020,1,1,tzinfo=timezone.utc).timestamp() * 1000)
MSK = timezone(timedelta(hours=3))

MISSED = [
    ("#14",  datetime(2026,3,4,12,0,tzinfo=timezone.utc),  "high"),
    ("#15",  datetime(2026,3,8,12,0,tzinfo=timezone.utc),  "low"),
    ("#48",  datetime(2026,5,6,0,0,tzinfo=timezone.utc),   "high"),
    ("NEW",  datetime(2026,5,10,12,0,tzinfo=timezone.utc), "high"),
]

# === Recompute Andrey features for these bars ===
print("Loading 1m + computing 12h features...")
rows=[]
with CSV_PATH.open() as f:
    rd=csv.reader(f); next(rd)
    for r in rd:
        ts=int(datetime.fromisoformat(r[0]).timestamp()*1000)
        if ts<START_MS-7*TF_D_MS: continue
        rows.append((ts,float(r[1]),float(r[2]),float(r[3]),float(r[4]),float(r[5])))
ts1m=np.array([r[0] for r in rows],dtype=np.int64)
op1m=np.array([r[1] for r in rows]); hi1m=np.array([r[2] for r in rows])
lo1m=np.array([r[3] for r in rows]); cl1m=np.array([r[4] for r in rows]); vo1m=np.array([r[5] for r in rows])

# Aggregate 12h with proper open
def agg12h(rs, tf_ms):
    out=[]; cb=None; o=h=l=c=v=0.0
    for ts,oo,hh,ll,cc,vv in rs:
        b=ts-(ts%tf_ms)
        if b!=cb:
            if cb is not None: out.append((cb,o,h,l,c,v))
            cb=b; o,h,l,c,v=oo,hh,ll,cc,vv
        else: h=max(h,hh); l=min(l,ll); c=cc; v+=vv
    if cb is not None: out.append((cb,o,h,l,c,v))
    return out
bars12 = [b for b in agg12h(list(zip(ts1m,op1m,hi1m,lo1m,cl1m,vo1m)), TF_12H_MS) if b[0]>=START_MS]
n=len(bars12)
ts12=np.array([b[0] for b in bars12],dtype=np.int64)
op=np.array([b[1] for b in bars12]); hi=np.array([b[2] for b in bars12])
lo=np.array([b[3] for b in bars12]); cl=np.array([b[4] for b in bars12]); vo=np.array([b[5] for b in bars12])

rng=hi-lo; body=np.abs(cl-op)
upper_wick=hi-np.maximum(op,cl); lower_wick=np.minimum(op,cl)-lo
close_pos=np.where(rng>0,(cl-lo)/rng,0.5)

tr=np.zeros(n); tr[0]=hi[0]-lo[0]
for i in range(1,n):
    tr[i]=max(hi[i]-lo[i],abs(hi[i]-cl[i-1]),abs(lo[i]-cl[i-1]))
atr14=pd.Series(tr).rolling(14).mean().bfill().values

vol_mean20=pd.Series(vo).rolling(20).mean().bfill().values
vol_std20=pd.Series(vo).rolling(20).std().bfill().replace(0,1).values
vsa_vz=(vo-vol_mean20)/vol_std20
rng_mean20=pd.Series(rng).rolling(20).mean().bfill().values
rng_std20=pd.Series(rng).rolling(20).std().bfill().replace(0,1).values
z_range=(rng-rng_mean20)/rng_std20
climax_bull=np.clip(z_range,0,None)*np.clip(vsa_vz,0,None)*close_pos
climax_bear=np.clip(z_range,0,None)*np.clip(vsa_vz,0,None)*(1-close_pos)
range_vs_atr=rng/np.maximum(atr14,1e-9)

ema20=pd.Series(cl).ewm(span=20).mean().values
uptrend=np.concatenate([[False]*20, ema20[20:]>ema20[15:-5]])
downtrend=np.concatenate([[False]*20, ema20[20:]<ema20[15:-5]])
lwp=np.where(rng>0,lower_wick/rng,0); uwp=np.where(rng>0,upper_wick/rng,0); bp=np.where(rng>0,body/rng,0)
cdl_hammer=((lwp>=0.5)&(uwp<0.15)&(bp<0.4)&downtrend).astype(int)
cdl_shooting=((uwp>=0.5)&(lwp<0.15)&(bp<0.4)&uptrend).astype(int)
cdl_inv_hammer=((uwp>=0.5)&(lwp<0.15)&(bp<0.4)&downtrend).astype(int)
cdl_hanging=((lwp>=0.5)&(uwp<0.15)&(bp<0.4)&uptrend).astype(int)

def sweep_failed(win_bars):
    bsl=np.zeros(n,dtype=int); ssl=np.zeros(n,dtype=int)
    for i in range(win_bars,n):
        prev_hi=hi[i-win_bars:i].max(); prev_lo=lo[i-win_bars:i].min()
        if hi[i]>prev_hi and cl[i]<prev_hi: bsl[i]=1
        if lo[i]<prev_lo and cl[i]>prev_lo: ssl[i]=1
    return bsl, ssl
bsl_f_24, ssl_f_24 = sweep_failed(2)
bsl_f_72, ssl_f_72 = sweep_failed(6)
bsl_f_168, ssl_f_168 = sweep_failed(14)

# Pre-3d return
pre_3d=np.zeros(n)
for i in range(6,n):
    p3=cl[i-6]
    pre_3d[i]=(cl[i]-p3)/p3*100 if p3 else 0

ts_to_idx={int(t):k for k,t in enumerate(ts12)}

# === Andrey ML signals ===
df_ml=pd.read_csv(Path.home()/"Desktop/etap_173_signals_caught.csv", parse_dates=["time_utc"])
df_ml["ts"]=df_ml["time_utc"].apply(lambda t: int(t.timestamp()*1000))

# === Bulkowski ===
df_bul=pd.read_csv(Path.home()/"Desktop/etap_172_signals.csv", parse_dates=["time"])
df_bul["bar_close_ts"] = df_bul["time"] + pd.Timedelta(hours=12)

# === Per missed audit ===
print(f"\n{'='*80}")
print(f"PER-MISSED FEATURE AUDIT")
print(f"{'='*80}")

for tag, dt_utc, side_dir in MISSED:
    ts = int(dt_utc.timestamp()*1000)
    idx = ts_to_idx.get(ts)
    if idx is None: print(f"\n{tag}: NO bar found for {dt_utc}"); continue
    side_short = "FH" if side_dir=="high" else "FL"

    print(f"\n{'-'*80}")
    print(f"{tag} @ {dt_utc.astimezone(MSK).strftime('%Y-%m-%d %H:%M MSK')} ({side_short})")
    print(f"  Bar: O={op[idx]:.0f} H={hi[idx]:.0f} L={lo[idx]:.0f} C={cl[idx]:.0f}")
    print(f"  body_pct={bp[idx]:.2f}  upper_wick%={uwp[idx]:.2f}  lower_wick%={lwp[idx]:.2f}")
    print(f"  close_pos_in_range={close_pos[idx]:.2f}  range_vs_atr={range_vs_atr[idx]:.2f}")
    print(f"  pre_3d_return%={pre_3d[idx]:.2f}")

    # VSA + Nison
    print(f"\n  VSA/Nison fires:")
    fires = []
    if side_dir=="high":  # FH — want short/bear signals
        if climax_bear[idx]>=1: fires.append(f"climax_bear={climax_bear[idx]:.2f}")
        if cdl_shooting[idx]==1: fires.append("cdl_shooting_star")
        if cdl_hanging[idx]==1: fires.append("cdl_hanging_man")
        if bsl_f_24[idx]: fires.append("bsl_failed_24")
        if bsl_f_72[idx]: fires.append("bsl_failed_72")
        if bsl_f_168[idx]: fires.append("bsl_failed_168")
    else:  # FL — want long/bull signals
        if climax_bull[idx]>=1: fires.append(f"climax_bull={climax_bull[idx]:.2f}")
        if cdl_hammer[idx]==1: fires.append("cdl_hammer")
        if cdl_inv_hammer[idx]==1: fires.append("cdl_inv_hammer")
        if ssl_f_24[idx]: fires.append("ssl_failed_24")
        if ssl_f_72[idx]: fires.append("ssl_failed_72")
        if ssl_f_168[idx]: fires.append("ssl_failed_168")
    if range_vs_atr[idx]>=1.5: fires.append(f"range_vs_atr={range_vs_atr[idx]:.2f}")
    print(f"    {', '.join(fires) if fires else 'NONE'}")

    # Andrey ML signal at this bar
    ml_match = df_ml[df_ml["ts"]==ts]
    print(f"\n  Andrey ML signal at this bar: {'YES' if not ml_match.empty else 'NO'}")
    if not ml_match.empty:
        for _, r in ml_match.iterrows():
            print(f"    side={r['side']}  tier={r['tier']}  p_main={r['p_main']:.3f}  hit_3={r['hit_3']}  hit_5={r['hit_5']}")

    # Bulkowski signals within ±5 days
    dt_window_lo = dt_utc - timedelta(days=5)
    dt_window_hi = dt_utc + timedelta(days=2)
    bul_near = df_bul[(df_bul["bar_close_ts"] >= dt_window_lo) & (df_bul["bar_close_ts"] <= dt_window_hi)]
    print(f"\n  Bulkowski signals nearby (±5d before to +2d after): {len(bul_near)}")
    expected_side = "short" if side_dir=="high" else "long"
    for _, r in bul_near.iterrows():
        flag = "✓" if r["side"]==expected_side else "✗"
        delta_h = (r["bar_close_ts"] - dt_utc).total_seconds()/3600
        print(f"    [{flag}] {r['bar_close_ts']} {r['pattern']:<12} {r['side']:<5} ult={r['ult_move_pct']:+.2f}% busted={r['busted']} Δ={delta_h/24:+.1f}d")
