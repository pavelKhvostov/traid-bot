"""etap_207 — VWAP от ЗНАЧИМЫХ якорей + МНОГОКРАТНАЯ реакция (гипотеза пользователя).

Прошлый тест (etap_206) брал ВСЕ N=2 фракталы (много шумовых) и мерил одиночный hold —
поэтому edge размылся. Пользователь: anchor должен быть на ВАЖНОМ уровне, и сила VWAP —
в ПОВТОРНОЙ реакции (цена возвращается к уровню много раз и реагирует).

Проверяем по тирам значимости якоря (BTC, daily):
  - N=2  (мелкий фрактал, baseline)
  - N=5  (средний свинг)
  - N=10 (крупный свинг — значимый)
  - SWEEP (снятие 20-дн экстремума с разворотом — ликвидность-грабёж, «важная» точка)
  - RANDOM (случайные даты — null)
Метрика на каждый якорь за его жизнь: n_touch (касаний с cooldown), n_react (реакций),
react_rate. Сравниваем тиры: react_rate и СРЕДНЕЕ ЧИСЛО реакций на якорь (повторность).
Ранжируем отдельные якоря по n_react → «важные даты», чью VWAP цена уважает многократно.

Запуск: venv/Scripts/python.exe research/daily_engine/etap_207_vwap_significant_anchors.py
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
OUT = Path(__file__).resolve().parent / "output"
HOLD_ATR, BREAK_ATR, FWD, COOLDOWN = 0.5, 0.5, 12, 24


def load():
    df = pd.read_csv(FLOW/"BTCUSDT_1h_flow.csv", parse_dates=["open_time"]).set_index("open_time")
    return df[["open","high","low","close","volume"]]


def main():
    df = load()
    o,h,l,c,v = (df[x].values for x in ["open","high","low","close","volume"])
    ts = df.index; n = len(df)
    tr = np.maximum(h-l, np.maximum(np.abs(h-np.r_[c[0],c[:-1]]), np.abs(l-np.r_[c[0],c[:-1]])))
    A = pd.Series(tr).ewm(alpha=1/14, adjust=False).mean().values
    pv = np.concatenate([[0], np.cumsum(v*c)]); vv = np.concatenate([[0], np.cumsum(v)])

    # daily
    d = df.resample("1D",origin="epoch",label="left",closed="left").agg(
        {"open":"first","high":"max","low":"min","close":"last"}).dropna()
    dH,dL,didx = d["high"].values, d["low"].values, d.index
    def idx_at(t): return min(int(ts.searchsorted(t)), n-1)

    def fractals(N):
        out=[]
        for i in range(N,len(d)-N):
            if all(dH[i]>dH[j] for j in range(i-N,i)) and all(dH[i]>dH[j] for j in range(i+1,i+N+1)):
                out.append(("FH",didx[i],dH[i]))
            elif all(dL[i]<dL[j] for j in range(i-N,i)) and all(dL[i]<dL[j] for j in range(i+1,i+N+1)):
                out.append(("FL",didx[i],dL[i]))
        return out

    def sweeps():
        # день делает новый 20-дн экстремум, но закрывается внутрь (снятие ликвидности+разворот)
        out=[]; H20=pd.Series(dH).rolling(20).max().values; L20=pd.Series(dL).rolling(20).min().values
        cl=d["close"].values
        for i in range(20,len(d)-1):
            if dH[i]>=H20[i-1] and cl[i]<dH[i]-0.5*(dH[i]-dL[i]):  # вынос вверх + закрытие вниз
                out.append(("FH",didx[i],dH[i]))
            if dL[i]<=L20[i-1] and cl[i]>dL[i]+0.5*(dH[i]-dL[i]):
                out.append(("FL",didx[i],dL[i]))
        return out

    rng = np.random.default_rng(0)
    def randoms(k):
        out=[]
        for _ in range(k):
            i=int(rng.integers(20,len(d)-30)); out.append(("FL",didx[i],dL[i]))
        return out

    def react_stats(anchors):
        """для набора якорей: список (n_touch,n_react) на каждый + ранжир-инфо."""
        per=[]
        for kind, at, price in anchors:
            a=idx_at(at)
            if a>=n-FWD-1: continue
            # VWAP[i] для i>=a (векторно)
            ii=np.arange(a,n)
            V=(pv[ii+1]-pv[a])/np.where(vv[ii+1]-vv[a]>0, vv[ii+1]-vv[a], np.nan)
            touch_mask=(l[a:]<=V)&(V<=h[a:])
            tix=np.where(touch_mask)[0]+a
            ntouch=nreact=0; last=-10**9
            for i in tix:
                if i-last<COOLDOWN or i>=n-FWD: continue
                last=i; Vi=V[i-a]
                approach = "support" if c[i-1]>Vi else "resistance"
                ntouch+=1; r=None
                for kk in range(i+1,i+1+FWD):
                    if approach=="support":
                        if h[kk]>=Vi+HOLD_ATR*A[i]: r=True; break
                        if l[kk]<=Vi-BREAK_ATR*A[i]: r=False; break
                    else:
                        if l[kk]<=Vi-HOLD_ATR*A[i]: r=True; break
                        if h[kk]>=Vi+BREAK_ATR*A[i]: r=False; break
                if r: nreact+=1
            per.append((kind,at,price,ntouch,nreact))
        return per

    print("Сравнение тиров значимости якоря (BTC, 2020-2026):\n")
    print(f"{'тир':<10}{'якорей':>8}{'σtouch':>9}{'σreact':>9}{'react%':>9}{'reacts/anchor':>15}")
    results={}
    for name, anchors in [("N=2",fractals(2)),("N=5",fractals(5)),("N=10",fractals(10)),
                          ("SWEEP",sweeps()),("RANDOM",randoms(120))]:
        per=react_stats(anchors); results[name]=per
        tt=sum(p[3] for p in per); rr=sum(p[4] for p in per)
        rate=rr/tt if tt else 0
        reacts_per=np.mean([p[4] for p in per]) if per else 0
        print(f"{name:<10}{len(per):>8}{tt:>9}{rr:>9}{rate*100:>8.1f}%{reacts_per:>15.2f}")

    # ранжир значимых якорей (N=10 ∪ SWEEP) по числу реакций
    big=results["N=10"]+results["SWEEP"]
    big=sorted(big,key=lambda p:-p[4])[:12]
    print("\n=== ТОП якорей по МНОГОКРАТНОСТИ реакции (важные даты) ===")
    print(f"{'дата':<12}{'тип':<5}{'anchor$':>9}{'касаний':>9}{'реакций':>9}{'%':>6}")
    for kind,at,price,nt,nr in big:
        pct=nr/nt*100 if nt else 0
        print(f"{str(at.date()):<12}{kind:<5}{price:>9.0f}{nt:>9}{nr:>9}{pct:>6.0f}")

    # текущие VWAP-значения этих важных якорей (для нанесения)
    print("\n=== VWAP_now важных якорей ===")
    cur=[]
    for kind,at,price,nt,nr in big[:8]:
        a=idx_at(at); Vn=(pv[n]-pv[a])/(vv[n]-vv[a]); dd=(c[-1]-Vn)/Vn*100
        cur.append((str(at.date()),kind,price,round(Vn),round(dd,1),nr))
        print(f"   {at.date()} {kind} anchor {price:.0f} → VWAP_now {Vn:.0f} ({dd:+.1f}%) | реакций {nr}")
    print(f"   close {c[-1]:.0f}")
    pd.DataFrame(cur,columns=["date","kind","anchor","vwap_now","dist_pct","reactions"]).to_csv(
        OUT/"etap207_significant_vwaps.csv",index=False)


if __name__ == "__main__":
    main()
