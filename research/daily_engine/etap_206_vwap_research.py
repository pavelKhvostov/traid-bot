"""etap_206 — Исследование VWAPs-ASVK: anchored-VWAP от 10 дневных фракталов как S/R.

Индикатор VWAPs-ASVK = 10 anchored-VWAP, каждая от одного из 10 последних подтверждённых
D-фракталов (Williams N=2). Логика из smc-lib/scripts/plot_d_10_fractals_vwap.py.

ГИПОТЕЗА (Dalton/Harris): VWAP от значимой точки = «справедливая цена» → действует как
динамическая поддержка/сопротивление (магнит). Проверяем СТРОГО:
  H-VWAP1: касание anchored-VWAP даёт реакцию (hold) ЧАЩЕ, чем случайный уровень (NULL).
  H-VWAP2: КОНФЛЮЭНС (≥2 VWAP рядом) усиливает реакцию.
Метрика hold: после касания цена уходит ≥0.5·ATR в сторону отскока РАНЬШЕ, чем пробивает
≥0.5·ATR насквозь. Approach: пришли сверху → ждём поддержку (вверх); снизу → сопротивление.
NULL: случайные горизонтальные уровни, та же частота касаний, M прогонов. По годам.

Данные: BTCUSDT 1h flow (есть volume). Запуск:
  venv/Scripts/python.exe research/daily_engine/etap_206_vwap_research.py
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
N_FRAC, N_LAST = 2, 10
HOLD_ATR, BREAK_ATR, FWD = 0.5, 0.5, 12   # 1h-бары вперёд для оценки реакции
COOLDOWN = 12                              # не считать повторные касания того же VWAP подряд


def load_1h():
    df = pd.read_csv(FLOW/"BTCUSDT_1h_flow.csv", parse_dates=["open_time"]).set_index("open_time")
    return df[["open","high","low","close","volume"]]


def daily_fractals(df1h):
    d = df1h.resample("1D",origin="epoch",label="left",closed="left").agg(
        {"open":"first","high":"max","low":"min","close":"last"}).dropna()
    H,L = d["high"].values, d["low"].values; idx=d.index
    fr=[]
    for i in range(N_FRAC,len(d)-N_FRAC):
        if all(H[i]>H[j] for j in range(i-N_FRAC,i)) and all(H[i]>H[j] for j in range(i+1,i+N_FRAC+1)):
            fr.append(("FH", idx[i], H[i]))
        elif all(L[i]<L[j] for j in range(i-N_FRAC,i)) and all(L[i]<L[j] for j in range(i+1,i+N_FRAC+1)):
            fr.append(("FL", idx[i], L[i]))
    # confirmed = подтверждён через N_FRAC+1 дней
    return [(k,t + pd.Timedelta(days=N_FRAC+1), t, p) for k,t,p in fr]  # (kind, confirm_t, anchor_t, price)


def atr1h(df, n=14):
    h,l,c=df["high"],df["low"],df["close"]
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/n,adjust=False).mean()


def main():
    df=load_1h()
    o,h,l,c,v=(df[x].values for x in ["open","high","low","close","volume"])
    ts=df.index; n=len(df); A=atr1h(df).values
    pv=np.concatenate([[0],np.cumsum(v*c)]); vv=np.concatenate([[0],np.cumsum(v)])
    def vwap(a,e): return (pv[e+1]-pv[a])/(vv[e+1]-vv[a]) if vv[e+1]-vv[a]>0 else np.nan
    # индекс 1h-бара по времени
    tdict = {t:i for i,t in enumerate(ts)}
    def idx_at(t):
        p=ts.searchsorted(t); return min(p,n-1)

    fracs = daily_fractals(df)
    # для каждого 1h-бара t: активные = 10 последних фракталов, ПОДТВЕРЖДЁННЫХ к моменту t
    conf_times = [f[1] for f in fracs]
    anchors_idx = [idx_at(f[2]) for f in fracs]   # индекс anchor-бара

    # --- сбор touch-событий по anchored-VWAP ---
    events=[]   # (bar_i, year, approach, hold_bool)
    last_touch={}  # anchor_j -> last bar touched (cooldown)
    # активные фракталы на бар i = подтверждённые (conf_time<=ts[i]), последние 10
    ci=0; active=[]   # list of fractal-indices in fracs, подтверждённые
    for i in range(50,n-FWD):
        while ci<len(fracs) and conf_times[ci]<=ts[i]:
            active.append(ci); ci+=1
        act=[j for j in active if anchors_idx[j]<=i][-N_LAST:]
        if not act: continue
        for j in act:
            V=vwap(anchors_idx[j], i)
            if not (l[i]<=V<=h[i]): continue            # касание
            if j in last_touch and i-last_touch[j]<COOLDOWN: continue
            last_touch[j]=i
            approach = "support" if c[i-1]>V else "resistance"
            thr_up=V+HOLD_ATR*A[i]; thr_dn=V-HOLD_ATR*A[i]
            hold=None
            for k in range(i+1,i+1+FWD):
                if approach=="support":
                    if h[k]>=thr_up: hold=True; break
                    if l[k]<=V-BREAK_ATR*A[i]: hold=False; break
                else:
                    if l[k]<=thr_dn: hold=True; break
                    if h[k]>=V+BREAK_ATR*A[i]: hold=False; break
            if hold is not None:
                events.append((i, ts[i].year, approach, hold, V, len(act)))
    ev=pd.DataFrame(events, columns=["i","year","approach","hold","V","n_active"])
    print(f"[VWAP-S/R] touch-событий: {len(ev)} | hold-rate ОБЩИЙ = {ev['hold'].mean():.3f}")
    print("  по годам:")
    for yr,g in ev.groupby("year"):
        if len(g)>30: print(f"   {yr}: hold {g['hold'].mean():.3f} (n={len(g)})")
    print(f"  support-касания: {ev[ev.approach=='support']['hold'].mean():.3f} | "
          f"resistance: {ev[ev.approach=='resistance']['hold'].mean():.3f}")

    # --- NULL: случайные горизонтальные уровни, та же логика/частота ---
    rng=np.random.default_rng(0); null_rates=[]
    n_touch=len(ev); M=30
    for m in range(M):
        cnt=hold_cnt=0; tries=0
        while cnt<n_touch and tries<n_touch*40:
            tries+=1
            i=int(rng.integers(50,n-FWD))
            # случайный уровень в пределах ±2 ATR от close — чтоб реально касался
            V=c[i]+ (rng.random()*4-2)*A[i]
            if not (l[i]<=V<=h[i]): continue
            cnt+=1
            approach="support" if c[i-1]>V else "resistance"
            hold=None
            for k in range(i+1,i+1+FWD):
                if approach=="support":
                    if h[k]>=V+HOLD_ATR*A[i]: hold=True; break
                    if l[k]<=V-BREAK_ATR*A[i]: hold=False; break
                else:
                    if l[k]<=V-HOLD_ATR*A[i]: hold=True; break
                    if h[k]>=V+BREAK_ATR*A[i]: hold=False; break
            if hold is not None: hold_cnt+=hold
        null_rates.append(hold_cnt/max(1,cnt))
    null_rates=np.array(null_rates)
    pval=(null_rates>=ev['hold'].mean()).mean()
    print(f"\n[NULL] случайные уровни M={M}: hold {null_rates.mean():.3f}±{null_rates.std():.3f} | "
          f"p-value(VWAP>=null)={pval:.3f}")

    # --- конфлюэнс: касание, когда ≥2 VWAP рядом (внутри 0.4·ATR) ---
    # пометим события, где в активном наборе ≥2 VWAP в пределах 0.4 ATR от V
    def confl(row):
        i=int(row.i); cnt=0
        act=[j for j in [x for x in range(len(fracs)) if anchors_idx[x]<=i and conf_times[x]<=ts[i]][-N_LAST:]]
        for j in act:
            Vj=vwap(anchors_idx[j],i)
            if abs(Vj-row.V)<=0.4*A[i]: cnt+=1
        return cnt>=2
    ev["confluence"]=ev.apply(confl,axis=1)
    cf=ev[ev.confluence]; nc=ev[~ev.confluence]
    print(f"\n[КОНФЛЮЭНС] ≥2 VWAP рядом: hold {cf['hold'].mean():.3f} (n={len(cf)}) | "
          f"одиночный: {nc['hold'].mean():.3f} (n={len(nc)})")

    # --- ТЕКУЩИЕ 10 VWAP (для нанесения на график) ---
    last10=[f for f in fracs if conf_times[fracs.index(f)]<=ts[-1]][-N_LAST:]
    print("\n=== ТЕКУЩИЕ 10 anchored-VWAP (BTC) ===")
    cur=[]
    for f in last10:
        ai=idx_at(f[2]); Vn=vwap(ai,n-1); d=(c[-1]-Vn)/Vn*100
        cur.append((f[0],f[2].date(),f[3],Vn,d))
        print(f"   {f[0]} {f[2].date()} (anchor {f[3]:.0f}): VWAP_now {Vn:.0f} ({d:+.1f}%)")
    print(f"   close: {c[-1]:.0f}")
    pd.DataFrame(cur,columns=["kind","anchor_date","anchor_price","vwap_now","dist_pct"]).to_csv(
        Path(__file__).resolve().parent/"output"/"etap206_current_vwaps.csv",index=False)
    print("\nВЕРДИКТ:")
    base=ev['hold'].mean()
    if pval<0.05 and base>null_rates.mean()+0.03:
        print(f"  VWAP-S/R РЕАЛЕН: hold {base:.3f} vs null {null_rates.mean():.3f} (p={pval:.3f}).")
    else:
        print(f"  VWAP-S/R НЕ бьёт случайный уровень значимо (hold {base:.3f} vs null {null_rates.mean():.3f}, p={pval:.3f}).")


if __name__ == "__main__":
    main()
