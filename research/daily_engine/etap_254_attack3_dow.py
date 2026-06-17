"""etap_254 — ATAKA 3: dow (день недели) — реальный эффект или мультитест-шум?

dow: 0=Mon..6=Sun. Подсказка: Tue слаб 25% / Mon 61% / Sun 56%.
Проверяем:
  1) WR каждого dow (BTC), n, по годам -> год-стабильность КАЖДОГО dow.
  2) permutation: shuffle win, max|WR_dow - base| -> FWER p для лучшего/худшего dow.
  3) Bonferroni на 7 dow (binomial test каждого dow vs base WR).
  4) если какой-то dow робастен -> добавить как правило к net и проверить OOS-спред+год-знак.
  5) sanity на ETH/SOL.

ASCII-only.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
CACHE = HERE / "output" / "etap_251_dataset.csv"
CUTOFF = pd.Timestamp("2024-01-01", tz="UTC")
DOWN = {0:"Mon",1:"Tue",2:"Wed",3:"Thu",4:"Fri",5:"Sat",6:"Sun"}


def load(asset=None):
    d = pd.read_csv(CACHE, parse_dates=["signal_time"])
    if asset: d = d[d.asset == asset].copy()
    for c in ["risk_pct","gauge","p_green","trend_hold","eff","hour","dow","year"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return d.dropna(subset=["win"]).reset_index(drop=True)


def base_net(g):
    p33, p67 = g.risk_pct.quantile(0.33), g.risk_pct.quantile(0.67)
    weak = ((g.risk_pct>=p67).astype(int)+(g.gauge>=1.0).astype(int)+(g.fvg_tf=="20m").astype(int)
            +g.session.isin(["London (7-13)","NY (13-21)"]).astype(int)+(g.state=="ROTATION").astype(int))
    ct = (((g.direction=="SHORT")&(g.state=="TREND_UP"))|((g.direction=="LONG")&(g.state=="TREND_DOWN"))).astype(int)
    strong = (g.risk_pct<=p33).astype(int)+(g.hour<7).astype(int)+ct
    return strong-weak


def main():
    d = load("BTCUSDT")
    base_wr = d.win.mean()
    print(f"BTC n={len(d)} base WR {base_wr*100:.1f}%")

    print("\n" + "="*78)
    print("1) WR by dow (BTC) + year-by-year")
    print("="*78)
    print(f"{'dow':<5} {'n':>4} {'WR':>6} {'OOS_WR':>7} {'OOS_n':>6}   per-year WR (n)")
    dow_stats = {}
    for dw in range(7):
        g = d[d.dow==dw]
        if len(g)==0: continue
        oos = g[g.signal_time>=CUTOFF]
        yr = []
        pos_years = 0; tot_years = 0
        for y, gy in g.groupby("year"):
            if len(gy)>=4:
                w = gy.win.mean()*100
                yr.append(f"{int(y)}:{w:.0f}%(n{len(gy)})")
                tot_years += 1
                if (gy.win.mean()-base_wr)>0: pos_years += 1
            else:
                yr.append(f"{int(y)}:-(n{len(gy)})")
        dow_stats[dw] = dict(n=len(g), wr=g.win.mean(), oos_wr=oos.win.mean() if len(oos) else np.nan,
                             oos_n=len(oos), pos=pos_years, tot=tot_years)
        print(f"{DOWN[dw]:<5} {len(g):>4} {g.win.mean()*100:>5.1f}% "
              f"{oos.win.mean()*100 if len(oos) else float('nan'):>6.1f}% {len(oos):>6}   {' '.join(yr)}")

    # year-stability of sign vs base
    print("\n  dow sign vs base WR, year-stability (n>=4/year):")
    for dw,s in dow_stats.items():
        print(f"    {DOWN[dw]}: WR {s['wr']*100:.0f}% vs base {base_wr*100:.0f}% -> sign+ in {s['pos']}/{s['tot']} years")

    # ---- 2) permutation FWER: max deviation of any dow WR from base ----
    print("\n" + "="*78)
    print("2) PERMUTATION FWER: is any dow WR-deviation real?")
    print("="*78)
    win = d.win.values; dow = d.dow.values
    obs_dev = {}
    for dw in range(7):
        m = dow==dw
        if m.sum()>=8:
            obs_dev[dw] = (win[m].mean()-base_wr)*100
    best_dw = max(obs_dev, key=lambda k: abs(obs_dev[k]))
    best_abs = abs(obs_dev[best_dw])
    print(f"  observed: most extreme dow = {DOWN[best_dw]} dev={obs_dev[best_dw]:+.1f}pp")
    print(f"  all devs: " + " ".join(f"{DOWN[k]}{v:+.0f}" for k,v in obs_dev.items()))
    rng = np.random.RandomState(0)
    null_max = []
    for i in range(5000):
        wp = rng.permutation(win)
        devs = [abs(wp[dow==dw].mean()-wp.mean())*100 for dw in obs_dev]
        null_max.append(max(devs))
    null_max = np.array(null_max)
    p_fwer = (null_max>=best_abs).mean()
    print(f"  null max|dev| (5000 shuffles): mean {null_max.mean():.1f}pp p95 {np.percentile(null_max,95):.1f}pp")
    print(f"  p(any dow this extreme by chance) = {p_fwer:.3f}  -> {'REAL' if p_fwer<0.05 else 'NOISE (multitest)'}")

    # ---- 3) Bonferroni per-dow binomial ----
    print("\n" + "="*78)
    print("3) Per-dow binomial test vs base WR + Bonferroni (alpha=0.05/7=0.0071)")
    print("="*78)
    for dw in obs_dev:
        g = d[d.dow==dw]; k = g.win.sum(); n = len(g)
        p = stats.binomtest(int(k), int(n), base_wr).pvalue
        sig = "SIG-Bonf" if p<0.05/7 else ("nom-sig" if p<0.05 else "ns")
        print(f"    {DOWN[dw]}: {int(k)}/{n} WR={k/n*100:.0f}% p={p:.3f} {sig}")

    # ---- 4) Tue-skip rule: add to net (Tue = -bad) ----
    print("\n" + "="*78)
    print("4) Tue-as-weak rule added to net (OOS spread + year sign)")
    print("="*78)
    d["net"] = base_net(d)
    def spread(df, col):
        hi=df[df[col]>=0]; lo=df[df[col]<0]
        if len(hi)==0 or len(lo)==0: return np.nan,len(hi),len(lo)
        return (hi.win.mean()-lo.win.mean())*100, len(hi), len(lo)
    def yr_sign(df, col, mn=5):
        pos=tot=0; out=[]
        for y,gy in df.groupby("year"):
            hi=gy[gy[col]>=0]; lo=gy[gy[col]<0]
            if len(hi)>=mn and len(lo)>=mn:
                s=(hi.win.mean()-lo.win.mean())*100; tot+=1; pos+= s>0
                out.append(f"{int(y)}:{s:+.0f}")
            else: out.append(f"{int(y)}:na")
        return pos,tot,out
    for name, col_def in [("Tue-weak", d.net-(d.dow==1).astype(int)),
                          ("Mon-strong", d.net+(d.dow==0).astype(int)),
                          ("Sun-strong", d.net+(d.dow==6).astype(int)),
                          ("Tue-weak+Mon-strong", d.net-(d.dow==1).astype(int)+(d.dow==0).astype(int))]:
        d["_t"]=col_def
        oos=d[d.signal_time>=CUTOFF]
        sa,_,_=spread(d,"_t"); so,nh,nl=spread(oos,"_t"); pos,tot,yr=yr_sign(d,"_t")
        print(f"  {name:<22}: ALL {sa:+.1f}pp  OOS {so:+.1f}pp (hi n{nh}/lo n{nl})  yr+ {pos}/{tot}  [{' '.join(yr)}]")
    # baseline reminder
    oos=d[d.signal_time>=CUTOFF]; sa,_,_=spread(d,"net"); so,_,_=spread(oos,"net"); pos,tot,yr=yr_sign(d,"net")
    print(f"  {'BASELINE':<22}: ALL {sa:+.1f}pp  OOS {so:+.1f}pp  yr+ {pos}/{tot}")

    # ---- 5) cross-asset dow ----
    print("\n" + "="*78)
    print("5) Tue WR cross-asset (does Tue-weakness transfer?)")
    print("="*78)
    for a in ["BTCUSDT","ETHUSDT","SOLUSDT"]:
        g=load(a); base=g.win.mean()
        tue=g[g.dow==1]
        print(f"  {a}: base {base*100:.0f}%  Tue WR {tue.win.mean()*100:.0f}% (n={len(tue)}) dev {(tue.win.mean()-base)*100:+.0f}pp")


if __name__ == "__main__":
    main()
