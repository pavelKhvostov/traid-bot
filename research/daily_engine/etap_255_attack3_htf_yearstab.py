"""etap_255 — ATAKA 3 final: год-стабильность htf=2h как доп-правила к net-грейду.

Вопрос: htf2_g дал OOS-spread +29.7 и year-sign 6/6 ПО СПРЕДУ net. Но это потому что
2h добавляет сделки в hi-группу. Реальный вопрос: год-стабилен ли САМ вклад 2h?
  A) net-спред с htf2_g vs чистый net — по годам (улучшает ли спред в КАЖДОМ году?).
  B) conditional 2h-vs-1h ВНУТРИ net>=0 и ВНУТРИ net<0 — по годам.
  C) практический грейд: "торгуем net>=0 OR htf=2h" vs "только net>=0" — WR/PnL по годам.
ASCII-only.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
CACHE = HERE / "output" / "etap_251_dataset.csv"
CUTOFF = pd.Timestamp("2024-01-01", tz="UTC")
RR = 2.2


def load(a=None):
    d = pd.read_csv(CACHE, parse_dates=["signal_time"])
    if a: d=d[d.asset==a].copy()
    for c in ["risk_pct","gauge","p_green","trend_hold","eff","hour","dow","year"]:
        d[c]=pd.to_numeric(d[c],errors="coerce")
    return d.dropna(subset=["win"]).reset_index(drop=True)

def base_net(g):
    p33,p67=g.risk_pct.quantile(0.33),g.risk_pct.quantile(0.67)
    weak=((g.risk_pct>=p67).astype(int)+(g.gauge>=1.0).astype(int)+(g.fvg_tf=="20m").astype(int)
          +g.session.isin(["London (7-13)","NY (13-21)"]).astype(int)+(g.state=="ROTATION").astype(int))
    ct=(((g.direction=="SHORT")&(g.state=="TREND_UP"))|((g.direction=="LONG")&(g.state=="TREND_DOWN"))).astype(int)
    return (g.risk_pct<=p33).astype(int)+(g.hour<7).astype(int)+ct-weak

def pnl(g):
    w=g.win.sum(); return w*RR-(len(g)-w)

def main():
    d=load("BTCUSDT"); d["net"]=base_net(d)
    d["net2"]=d.net+(d.htf_tf=="2h").astype(int)
    print(f"BTC n={len(d)} base WR {d.win.mean()*100:.1f}%")

    print("\nA) net-spread per-year: baseline vs net+htf2  (does htf2 improve spread EACH year?)")
    print(f"{'year':<6}{'base_sp':>9}{'net2_sp':>9}{'delta':>7}")
    impr=0; tot=0
    for y,g in d.groupby("year"):
        def sp(col):
            hi=g[g[col]>=0]; lo=g[g[col]<0]
            if len(hi)<4 or len(lo)<4: return np.nan
            return (hi.win.mean()-lo.win.mean())*100
        b=sp("net"); n2=sp("net2")
        if not np.isnan(b) and not np.isnan(n2):
            tot+=1; impr+= (n2-b)>0
            print(f"{int(y):<6}{b:>+8.0f} {n2:>+8.0f} {n2-b:>+6.0f}")
        else:
            print(f"{int(y):<6}{'na' if np.isnan(b) else f'{b:+.0f}':>9}{'na' if np.isnan(n2) else f'{n2:+.0f}':>9}{'':>7}")
    print(f"  -> htf2 improves spread in {impr}/{tot} years")

    print("\nB) conditional 2h-vs-1h WITHIN net group, per-year (the actual edge):")
    print(f"{'year':<6}  net>=0: 2h/1h diff      net<0: 2h/1h diff")
    pos_hi=tot_hi=pos_lo=tot_lo=0
    for y,g in d.groupby("year"):
        def diff(sub):
            a=sub[sub.htf_tf=="2h"]; b=sub[sub.htf_tf=="1h"]
            if len(a)<3 or len(b)<3: return None
            return (a.win.mean()-b.win.mean())*100
        dh=diff(g[g.net>=0]); dl=diff(g[g.net<0])
        sh = "na" if dh is None else f"{dh:+.0f}pp"
        sl = "na" if dl is None else f"{dl:+.0f}pp"
        if dh is not None: tot_hi+=1; pos_hi+= dh>0
        if dl is not None: tot_lo+=1; pos_lo+= dl>0
        print(f"{int(y):<6}  {sh:>18}      {sl:>14}")
    print(f"  -> 2h>1h within net>=0: {pos_hi}/{tot_hi} years | within net<0: {pos_lo}/{tot_lo} years")

    print("\nC) PRACTICAL grade per-year: 'net>=0' vs 'net>=0 OR htf=2h' (trade-set WR/PnL):")
    print(f"{'year':<6}{'net>=0 WR(n) PnL':>26}{'net>=0|2h WR(n) PnL':>28}")
    for y,g in d.groupby("year"):
        a=g[g.net>=0]; b=g[(g.net>=0)|(g.htf_tf=="2h")]
        print(f"{int(y):<6}  {a.win.mean()*100:5.1f}% (n{len(a):>2}) {pnl(a):>+6.1f}R    "
              f"{b.win.mean()*100:5.1f}% (n{len(b):>2}) {pnl(b):>+6.1f}R")
    # totals all + OOS
    for lab,sub in [("ALL",d),("OOS",d[d.signal_time>=CUTOFF])]:
        a=sub[sub.net>=0]; b=sub[(sub.net>=0)|(sub.htf_tf=="2h")]
        print(f"  {lab}: net>=0 WR {a.win.mean()*100:.1f}% n{len(a)} PnL {pnl(a):+.1f}R | "
              f"net>=0|2h WR {b.win.mean()*100:.1f}% n{len(b)} PnL {pnl(b):+.1f}R")

    print("\nD) Does adding 2h just inflate trade count without raising trade-set WR?")
    a=d[d.net>=0]; b=d[(d.net>=0)|(d.htf_tf=="2h")]
    extra=d[(d.net<0)&(d.htf_tf=="2h")]  # trades 2h ADDS over pure net>=0
    print(f"  pure net>=0: n{len(a)} WR {a.win.mean()*100:.1f}%")
    print(f"  trades ADDED by '|2h': n{len(extra)} WR {extra.win.mean()*100:.1f}%  (these are net<0 & 2h)")
    print(f"  their per-year WR: " + " ".join(
        f"{int(y)}:{gy.win.mean()*100:.0f}%(n{len(gy)})" for y,gy in extra.groupby('year') if len(gy)>=3))


if __name__=="__main__":
    main()
