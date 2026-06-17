"""etap_205 — Multi-horizon зоны BTC: ДЕНЬ / НЕДЕЛЯ / МЕСЯЦ.

Зоны по канону (Dalton VP + ICT) на 3 горизонтах + фильтр «ещё актуальна» (неотработана):
  - Volume Profile: POC/VAH/VAL, HVN (магниты), LVN (быстрый проход)
  - ICT: НЕОТРАБОТАННЫЕ (unmitigated) OB и FVG (канон c1-c3)
  - Ликвидность/DOL: НЕСНЯТЫЕ фрактальные swing high/low (resting liquidity)
  - Naked POC: POC прошлых периодов, к которым цена не возвращалась
W = пн-пн (TV-стандарт), M = календарный месяц. Данные: BTCUSDT 1h flow → ресемпл.

Запуск: venv/Scripts/python.exe research/daily_engine/etap_205_multi_horizon_zones.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

ROOT = Path(__file__).resolve().parents[2]
FLOW = ROOT / "research" / "elements_study" / "data"


def load(tf_rule, label="left", closed="left"):
    df = pd.read_csv(FLOW / "BTCUSDT_1h_flow.csv", parse_dates=["open_time"]).set_index("open_time")
    d = df.resample(tf_rule, origin="epoch", label=label, closed=closed).agg(
        {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna(subset=["open"])
    # отрезать незакрытый последний бар
    step = {"1D":pd.Timedelta(days=1),"W-MON":pd.Timedelta(weeks=1),"MS":pd.Timedelta(days=31)}.get(tf_rule)
    now = pd.Timestamp.utcnow()
    if step is not None and len(d) and d.index[-1] + step > now and tf_rule != "MS":
        pass  # для дня/недели оставляем форм. бар как «текущий»
    return d


def vp(H, L, V, n_bins=60, frac=0.7):
    lo, hi = L.min(), H.max()
    edges = np.linspace(lo, hi, n_bins+1); prof = np.zeros(n_bins)
    for h,l,v in zip(H,L,V):
        b0=max(np.searchsorted(edges,l,"right")-1,0); b1=min(np.searchsorted(edges,h,"right")-1,n_bins-1)
        if b1==b0: prof[b0]+=v
        else: prof[b0:b1+1]+=v/(b1-b0+1)
    poc=int(prof.argmax()); cen=lambda i:(edges[i]+edges[i+1])/2
    tot=prof.sum(); lo_i=hi_i=poc; cum=prof[poc]
    while cum<frac*tot:
        up=prof[hi_i+1:hi_i+3].sum() if hi_i+1<n_bins else -1
        dn=prof[lo_i-2:lo_i].sum() if lo_i-1>=0 else -1
        if up<0 and dn<0: break
        if up>=dn: hi_i=min(hi_i+2,n_bins-1); cum+=max(up,0)
        else: lo_i=max(lo_i-2,0); cum+=max(dn,0)
    sm=np.convolve(prof,np.ones(3)/3,mode="same"); cc=(edges[:-1]+edges[1:])/2
    hvn=[cc[i] for i in range(1,n_bins-1) if sm[i]>sm[i-1] and sm[i]>=sm[i+1] and sm[i]>sm.mean()]
    lvn=[cc[i] for i in range(1,n_bins-1) if sm[i]<sm[i-1] and sm[i]<=sm[i+1] and sm[i]<sm.mean()*0.5]
    return cen(poc), cen(hi_i), cen(lo_i), hvn, lvn


def unmitigated_fvg(o,h,l,c,price,band):
    n=len(c); bull=[]; bear=[]
    for i in range(1,n-1):
        if h[i-1]<l[i+1]:
            top,bot=l[i+1],h[i-1]
            filled=(l[i+2:]<bot).any() if i+2<n else False
            if not filled and abs((top+bot)/2/price-1)<=band: bull.append((bot,top))
        if l[i-1]>h[i+1]:
            top,bot=l[i-1],h[i+1]
            filled=(h[i+2:]>top).any() if i+2<n else False
            if not filled and abs((top+bot)/2/price-1)<=band: bear.append((bot,top))
    return bull,bear


def unmitigated_ob(o,h,l,c,price,band):
    n=len(c); bull=[]; bear=[]
    for i in range(1,n):
        if c[i-1]<o[i-1] and c[i]>o[i-1]:
            top,bot=o[i-1],min(l[i-1],l[i])
            if not ((l[i+1:]<bot).any() if i+1<n else False) and abs((top+bot)/2/price-1)<=band: bull.append((bot,top))
        if c[i-1]>o[i-1] and c[i]<o[i-1]:
            top,bot=max(h[i-1],h[i]),o[i-1]
            if not ((h[i+1:]>top).any() if i+1<n else False) and abs((top+bot)/2/price-1)<=band: bear.append((bot,top))
    return bull,bear


def untested_swings(h,l,price,band,N=2):
    n=len(h); bsl=[]; ssl=[]
    for i in range(N,n-N-1):
        if h[i]>max(h[i-N:i].max(),h[i+1:i+1+N].max()):
            if not (h[i+N+1:]>h[i]).any() and abs(h[i]/price-1)<=band: bsl.append(h[i])  # не снят сверху
        if l[i]<min(l[i-N:i].min(),l[i+1:i+1+N].min()):
            if not (l[i+N+1:]<l[i]).any() and abs(l[i]/price-1)<=band: ssl.append(l[i])
    return bsl,ssl


def fmt(x): return f"{x:,.0f}"
def zr(z): return f"{z[0]:,.0f}-{z[1]:,.0f}"


def horizon(name, d, price, band, vp_lookback):
    o,h,l,c,v=(d[x].values for x in ["open","high","low","close","volume"])
    w=slice(max(0,len(d)-vp_lookback),len(d))
    poc,vah,val,hvn,lvn=vp(h[w],l[w],v[w])
    fb,fbe=unmitigated_fvg(o,h,l,c,price,band)
    ob,obe=unmitigated_ob(o,h,l,c,price,band)
    bsl,ssl=untested_swings(h,l,price,band)
    near=lambda xs:sorted(set(round(x,-1) for x in xs),key=lambda x:abs(x-price))
    print(f"\n{'='*66}\n▌ {name} (баров {len(d)}, цена {fmt(price)})\n{'='*66}")
    print(f"  VP: POC {fmt(poc)} | VA [{fmt(val)} .. {fmt(vah)}]")
    print(f"  HVN (сильные магниты): {', '.join(fmt(x) for x in near(hvn)[:6]) or '—'}")
    print(f"  LVN (быстрый проход):  {', '.join(fmt(x) for x in near(lvn)[:5]) or '—'}")
    above=lambda zs:[z for z in zs if (z[0]+z[1])/2>price]; below=lambda zs:[z for z in zs if (z[0]+z[1])/2<=price]
    print(f"  СОПРОТИВЛЕНИЕ ↑ (неотработанные):")
    for z in sorted(above(fbe)+above(obe),key=lambda z:(z[0]+z[1])/2)[:4]:
        print(f"     {zr(z)}  ({'FVG' if z in fbe else 'OB'} bear)")
    print(f"  ПОДДЕРЖКА ↓ (неотработанные):")
    for z in sorted(below(fb)+below(ob),key=lambda z:-(z[0]+z[1])/2)[:4]:
        print(f"     {zr(z)}  ({'FVG' if z in fb else 'OB'} bull)")
    print(f"  Несн. ликвидность: BSL↑ {', '.join(fmt(x) for x in sorted(set(round(b,-1) for b in bsl))[:4]) or '—'}")
    print(f"                     SSL↓ {', '.join(fmt(x) for x in sorted(set(round(s,-1) for s in ssl),reverse=True)[:4]) or '—'}")


def main():
    dD=load("1D"); dW=load("W-MON"); dM=load("MS")
    price=dD["close"].iloc[-1]
    print(f"BTCUSDT · текущая цена {fmt(price)} · данные до {dD.index[-1]:%Y-%m-%d}")
    horizon("МЕСЯЦ (макро-зоны, ±40%, VP 18 мес)", dM, price, 0.40, 18)
    horizon("НЕДЕЛЯ (±22%, VP 26 нед)", dW, price, 0.22, 26)
    horizon("ДЕНЬ (±10%, VP 90д)", dD, price, 0.10, 90)
    # глубокие исторические HVN-полки (вся история) — справочно
    o,h,l,c,v=(dM[x].values for x in ["open","high","low","close","volume"])
    _,_,_,hvn_all,_=vp(h,l,v)
    print(f"\n[справочно] глубокие исторические HVN-полки (вся история): "
          f"{', '.join(fmt(x) for x in sorted(hvn_all))}")


if __name__ == "__main__":
    main()
