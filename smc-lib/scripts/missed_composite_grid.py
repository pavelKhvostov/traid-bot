"""Composite filter grid для catch missed.

Кандидаты признаков (по аудиту 4 missed):
  FH: close_pos ≥ X AND range_vs_atr ≥ Y       (#48, NEW)
  FH: pre_3d_return ≥ Z%                        (#14)
  FL: close_pos ≤ X AND pre_3d ≤ -Y%            (#15)

C9 candidates:
  FH C9a = (close_pos ≥ 0.7 AND range_vs_atr ≥ 1.4)   → catch #48, NEW
  FH C9b = pre_3d_return ≥ 10%                         → catch #14
  FL C9c = (close_pos ≤ 0.2 AND pre_3d ≤ -5%)          → catch #15

Grid: пробуем варианты thresholds.
"""
from __future__ import annotations
import csv
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd

CSV_PATH = Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
BASE_PATH = Path.home() / "Desktop" / "baseline_1267.parquet"
TF_12H_MS = 720 * 60_000
START_MS = int(datetime(2020,1,1,tzinfo=timezone.utc).timestamp() * 1000)

# Load 22 targets
import sys
sys.path.insert(0, str(Path.home()/"smc-lib"))
sys.path.insert(0, str(Path.home()/"smc-lib/prediction-algo"))
from force_model_v3.targets_22 import TARGETS_22_MSK
targets_22 = set()
for t_msk, fh_fl in TARGETS_22_MSK:
    ts_ms = int(pd.Timestamp(t_msk+"+03:00").tz_convert("UTC").timestamp()*1000)
    targets_22.add((ts_ms, "high" if fh_fl=="FH" else "low"))

MISSED = {
    "#14": (int(datetime(2026,3,4,12,0,tzinfo=timezone.utc).timestamp()*1000), "high"),
    "#15": (int(datetime(2026,3,8,12,0,tzinfo=timezone.utc).timestamp()*1000), "low"),
    "#48": (int(datetime(2026,5,6,0,0,tzinfo=timezone.utc).timestamp()*1000), "high"),
    "NEW": (int(datetime(2026,5,10,12,0,tzinfo=timezone.utc).timestamp()*1000), "high"),
}

print("Loading + computing features per 12h bar...")
rows=[]
with CSV_PATH.open() as f:
    rd=csv.reader(f); next(rd)
    for r in rd:
        ts=int(datetime.fromisoformat(r[0]).timestamp()*1000)
        if ts<START_MS: continue
        rows.append((ts,float(r[1]),float(r[2]),float(r[3]),float(r[4]),float(r[5])))
ts1m=np.array([r[0] for r in rows],dtype=np.int64)
op1m=np.array([r[1] for r in rows]); hi1m=np.array([r[2] for r in rows])
lo1m=np.array([r[3] for r in rows]); cl1m=np.array([r[4] for r in rows]); vo1m=np.array([r[5] for r in rows])

def agg12h(rs,tf_ms):
    out=[];cb=None;o=h=l=c=v=0.0
    for ts,oo,hh,ll,cc,vv in rs:
        b=ts-(ts%tf_ms)
        if b!=cb:
            if cb is not None: out.append((cb,o,h,l,c,v))
            cb=b; o,h,l,c,v=oo,hh,ll,cc,vv
        else: h=max(h,hh); l=min(l,ll); c=cc; v+=vv
    if cb is not None: out.append((cb,o,h,l,c,v))
    return out
bars12=[b for b in agg12h(list(zip(ts1m,op1m,hi1m,lo1m,cl1m,vo1m)),TF_12H_MS) if b[0]>=START_MS]
n=len(bars12)
ts12=np.array([b[0] for b in bars12],dtype=np.int64)
op=np.array([b[1] for b in bars12]); hi=np.array([b[2] for b in bars12])
lo=np.array([b[3] for b in bars12]); cl=np.array([b[4] for b in bars12])
rng=hi-lo
close_pos=np.where(rng>0,(cl-lo)/rng,0.5)
tr=np.zeros(n); tr[0]=hi[0]-lo[0]
for i in range(1,n):
    tr[i]=max(hi[i]-lo[i],abs(hi[i]-cl[i-1]),abs(lo[i]-cl[i-1]))
atr14=pd.Series(tr).rolling(14).mean().bfill().values
range_vs_atr=rng/np.maximum(atr14,1e-9)
pre_3d=np.zeros(n)
for i in range(6,n):
    p3=cl[i-6]
    pre_3d[i]=(cl[i]-p3)/p3*100 if p3 else 0

ts_to_idx={int(t):k for k,t in enumerate(ts12)}

df_base=pd.read_parquet(BASE_PATH)
df_base["bar_idx"]=df_base["ts"].apply(lambda t:ts_to_idx.get(int(t),-1))
df_base=df_base[df_base["bar_idx"]>=0].copy()
df_base["close_pos"]=df_base["bar_idx"].apply(lambda i:close_pos[i])
df_base["range_vs_atr"]=df_base["bar_idx"].apply(lambda i:range_vs_atr[i])
df_base["pre_3d"]=df_base["bar_idx"].apply(lambda i:pre_3d[i])
df_base["t22"]=df_base.apply(lambda r:(int(r["ts"]),r["direction"]) in targets_22, axis=1)

missed_idx={tag:df_base[(df_base["ts"]==ts) & (df_base["direction"]==d)].index[0]
            for tag,(ts,d) in MISSED.items()
            if not df_base[(df_base["ts"]==ts) & (df_base["direction"]==d)].empty}

# ===== C9a (FH): close_pos ≥ X AND range_vs_atr ≥ Y =====
print(f"\n=== C9a (FH): close_pos ≥ X AND range_vs_atr ≥ Y ===")
print(f"{'X_cp':>5} {'Y_rva':>6} {'keep':>5} {'conf':>5} {'P_W%':>6} {'imp':>4} {'t22':>4} {'missed':<15}")
for cp_thr in [0.6, 0.65, 0.7, 0.75, 0.8]:
    for rva_thr in [1.2, 1.4, 1.5, 1.6, 1.8]:
        mask = (df_base["direction"]=="high") & (df_base["close_pos"]>=cp_thr) & (df_base["range_vs_atr"]>=rva_thr)
        sub = df_base[mask]
        keep=len(sub); conf=int(sub["confirmed"].sum())
        imp=sub[sub["is_important"] & sub["confirmed"]].shape[0]
        t22=sub[sub["t22"] & sub["confirmed"]].shape[0]
        caught=[t for t,mi in missed_idx.items() if mi in sub.index]
        pw=conf/keep*100 if keep else 0
        if keep<15: continue
        flag = "★" if pw>=70 else (" " if pw>=65 else " ")
        print(f"{flag} {cp_thr:>4.2f} {rva_thr:>5.1f} {keep:>5} {conf:>5} {pw:>5.1f}% {imp:>4} {t22:>4} {'+'.join(caught):<15}")

# ===== C9b (FH): pre_3d_return ≥ Z% =====
print(f"\n=== C9b (FH): pre_3d_return ≥ Z% ===")
print(f"{'Z':>5} {'keep':>5} {'conf':>5} {'P_W%':>6} {'imp':>4} {'t22':>4} {'missed':<15}")
for z in [3, 5, 7, 10, 12, 15]:
    mask = (df_base["direction"]=="high") & (df_base["pre_3d"]>=z)
    sub = df_base[mask]
    keep=len(sub); conf=int(sub["confirmed"].sum())
    imp=sub[sub["is_important"] & sub["confirmed"]].shape[0]
    t22=sub[sub["t22"] & sub["confirmed"]].shape[0]
    caught=[t for t,mi in missed_idx.items() if mi in sub.index]
    pw=conf/keep*100 if keep else 0
    flag = "★" if pw>=70 else (" " if pw>=65 else " ")
    print(f"{flag} {z:>3}% {keep:>5} {conf:>5} {pw:>5.1f}% {imp:>4} {t22:>4} {'+'.join(caught):<15}")

# ===== C9c (FL): close_pos ≤ X AND pre_3d ≤ -Y% =====
print(f"\n=== C9c (FL): close_pos ≤ X AND pre_3d ≤ -Y% ===")
print(f"{'X_cp':>5} {'Y_p3':>5} {'keep':>5} {'conf':>5} {'P_W%':>6} {'imp':>4} {'t22':>4} {'missed':<15}")
for cp_thr in [0.15, 0.20, 0.25, 0.30]:
    for p3_thr in [-3, -5, -7, -10]:
        mask = (df_base["direction"]=="low") & (df_base["close_pos"]<=cp_thr) & (df_base["pre_3d"]<=p3_thr)
        sub = df_base[mask]
        keep=len(sub); conf=int(sub["confirmed"].sum())
        imp=sub[sub["is_important"] & sub["confirmed"]].shape[0]
        t22=sub[sub["t22"] & sub["confirmed"]].shape[0]
        caught=[t for t,mi in missed_idx.items() if mi in sub.index]
        pw=conf/keep*100 if keep else 0
        if keep<5: continue
        flag = "★" if pw>=70 else (" " if pw>=65 else " ")
        print(f"{flag} {cp_thr:>4.2f} {p3_thr:>4}% {keep:>5} {conf:>5} {pw:>5.1f}% {imp:>4} {t22:>4} {'+'.join(caught):<15}")

# ===== Combined: union of C9a + C9b + C9c =====
print(f"\n=== Composite union C9 = C9a ∪ C9b ∪ C9c ===")
for cp_FH in [0.7, 0.8]:
    for rva in [1.4, 1.5]:
        for z3 in [10, 12]:
            for cp_FL in [0.15, 0.20]:
                for p3_FL in [-5, -7]:
                    mask_a = (df_base["direction"]=="high") & (df_base["close_pos"]>=cp_FH) & (df_base["range_vs_atr"]>=rva)
                    mask_b = (df_base["direction"]=="high") & (df_base["pre_3d"]>=z3)
                    mask_c = (df_base["direction"]=="low") & (df_base["close_pos"]<=cp_FL) & (df_base["pre_3d"]<=p3_FL)
                    mask = mask_a | mask_b | mask_c
                    sub = df_base[mask]
                    keep=len(sub); conf=int(sub["confirmed"].sum())
                    imp=sub[sub["is_important"] & sub["confirmed"]].shape[0]
                    t22=sub[sub["t22"] & sub["confirmed"]].shape[0]
                    caught=[t for t,mi in missed_idx.items() if mi in sub.index]
                    pw=conf/keep*100 if keep else 0
                    flag = "★" if pw>=70 else (" " if pw>=65 else " ")
                    print(f"{flag} FH(cp≥{cp_FH} rva≥{rva}) ∪ FH(p3≥{z3}%) ∪ FL(cp≤{cp_FL} p3≤{p3_FL}%) → n={keep} P(W)={pw:.1f}% imp={imp} t22={t22} miss={'+'.join(caught)}")
