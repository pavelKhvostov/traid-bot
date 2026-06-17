"""etap_225 — живые дашборды дня для BTC И ETH (движок обучен на BTC, применён к обоим).
Каждый = режим(фон) + Initial Balance + зоны + калиброванная P по часам + vol-gauge."""
import sys, time
from pathlib import Path
import numpy as np, pandas as pd, requests
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import etap_217_daytype_layer as L

BTC = HERE.parent.parent / "data" / "BTCUSDT_1h_orderflow.csv"
OUT = HERE / "output"
COL = {"TREND_UP": "#2e7d32", "TREND_DOWN": "#c62828", "ROTATION": "#9e9e9e", "FORMING": "#cfcfcf"}


def fetch(sym, days=30):
    end = int(time.time()*1000); cur = end - days*24*3600*1000; rows = []
    while cur < end:
        d = requests.get("https://api.binance.com/api/v3/klines",
                         params=dict(symbol=sym, interval="1h", startTime=cur, limit=1000), timeout=20).json()
        if not d: break
        rows += d; cur = d[-1][0] + 3600_000
    df = pd.DataFrame(rows, columns=["t","open","high","low","close","v","ct","qv","n","tb","tq","ig"])
    df["t"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    for c in ["open","high","low","close","v"]: df[c] = pd.to_numeric(df[c])
    return df.set_index("t").rename(columns={"v":"volume"})[["open","high","low","close","volume"]]


SHAPE_RU = {"rev_up": "разворот вверх", "rev_down": "разворот вниз",
            "trend_up": "тренд вверх", "trend_down": "тренд вниз", "range": "боковик"}


def dashboard(symbol, df, M, lines, fmt, exp_pct=None, rev_day=None):
    day = df.index.normalize().unique()[-1]
    g = df[df.index.normalize() == day]
    o = g["open"].iloc[0]; c = g["close"].values; H = g["high"].values; Lo = g["low"].values; OP = g["open"].values
    dec, flips = L.daytype_nowcast(g, M)
    ks = [d[0] for d in dec]; states=[d[1] for d in dec]; praw=[d[2] for d in dec]; psm=[d[3] for d in dec]; calls=[d[5] for d in dec]
    # Gauge 2.0: знаменатель из range-модели (etap_237), если передан; иначе rolling-медиана
    if exp_pct and exp_pct > 0:
        exp = exp_pct
    else:
        daily = df.resample("1D").agg({"open":"first","high":"max","low":"min"})
        exp = ((daily.high-daily.low)/daily.open).rolling(20).median().shift(1).reindex([day]).iloc[0]
    hi=np.maximum.accumulate(H); lo=np.minimum.accumulate(Lo)
    net_used = (hi/o-1)/exp - (o/lo-1)/exp

    fig,(a,b,cc)=plt.subplots(3,1,figsize=(13,11),height_ratios=[3,2,1.2],sharex=True)
    cur=dec[-1]
    fig.suptitle(f"{symbol} · ЖИВОЙ ДВИЖОК {pd.Timestamp(day).date()}   "
                 f"СЕЙЧАС: {cur[1]} | P(вверх)={cur[2]:.0%} | {cur[4]}/{cur[5]} | смен мнения: {flips}",
                 fontsize=13, weight="bold")
    for k in ks: a.axvspan(k-0.5,k+0.5,color=COL[states[k]],alpha=0.13,zorder=0)
    for k in ks:
        col="#26a69a" if c[k]>=OP[k] else "#ef5350"
        a.plot([k,k],[Lo[k],H[k]],color=col,lw=1,zorder=3)
        a.add_patch(Rectangle((k-0.3,min(OP[k],c[k])),0.6,abs(c[k]-OP[k])+(H.max()-Lo.min())*0.001,color=col,zorder=4))
    ibh,ibl=H[:L.IB].max(),Lo[:L.IB].min()
    a.add_patch(Rectangle((-0.5,ibl),L.IB,ibh-ibl,fill=False,ec="#1565c0",lw=1.5,ls="--",zorder=5))
    a.text(L.IB-0.5,ibh," утренний коридор",color="#1565c0",fontsize=9,va="bottom")
    # ТОЧКА РАЗВОРОТА дня (etap_255, reversal.classify_day) — описательно, без прогноза
    if rev_day and rev_day.get("shape") in ("rev_up", "rev_down"):
        ph = rev_day.get("pivot_hour"); pp = rev_day.get("pivot_price")
        if ph is not None and pp is not None:
            up = rev_day["shape"] == "rev_up"; span = H.max() - Lo.min()
            a.scatter([ph], [pp], marker="^" if up else "v", s=150, color="#6a1b9a",
                      zorder=7, edgecolor="white", linewidth=1.2)
            a.annotate("разворот" + (" вверх" if up else " вниз"), xy=(ph, pp),
                       xytext=(ph, pp - span * 0.12 if up else pp + span * 0.12),
                       ha="center", fontsize=9, color="#6a1b9a", weight="bold",
                       arrowprops=dict(arrowstyle="->", color="#6a1b9a", lw=1.4), zorder=7)
    for y,lab in lines:
        if lo.min()*0.999<y<hi.max()*1.001:
            a.axhline(y,color="#7b1fa2",lw=1,ls=":",alpha=0.7); a.text(ks[-1],y,f" {lab}",color="#7b1fa2",fontsize=8,va="center")
    a.set_ylabel("цена"); a.set_title("① ЦЕНА: фон-настроение дня — зелёный=растёт / серый=боковик / красный=падает",loc="left",fontsize=10)
    if rev_day:
        is_rev = rev_day["shape"] in ("rev_up", "rev_down")
        a.text(0.005, 0.97, f"форма дня: {SHAPE_RU.get(rev_day['shape'], '')}",
               transform=a.transAxes, ha="left", va="top", fontsize=10,
               weight="bold", color="#6a1b9a" if is_rev else "#555",
               bbox=dict(boxstyle="round,pad=0.25", fc="#f3e5f5" if is_rev else "#eeeeee",
                         ec="#6a1b9a" if is_rev else "#bdbdbd", alpha=0.9))
    a.grid(alpha=0.15)
    b.axhspan(0.43,0.57,color="#bdbdbd",alpha=0.3,zorder=0,label="мёртвая зона (ждём)")
    b.axhline(0.5,color="#888",lw=0.8); b.plot(ks,praw,color="#90a4ae",lw=1,label="по часу")
    b.plot(ks,psm,color="#1a1a1a",lw=2.4,label="сглаженная")
    for k in ks: b.scatter(k,psm[k],color={"LONG":"#2e7d32","SHORT":"#c62828","HOLD":"#9e9e9e"}[calls[k]],s=42,zorder=5)
    b.set_ylim(0,1); b.set_ylabel("шанс роста")
    b.set_title("② ШАНС, что день закроется ростом (точки: зел=лонг / крас=шорт / сер=ждать)",loc="left",fontsize=10)
    b.legend(loc="upper left",fontsize=8,ncol=3); b.grid(alpha=0.15)
    cc.bar(ks,net_used,color=["#2e7d32" if x>0 else "#c62828" for x in net_used],alpha=0.7)
    cc.axhline(0,color="#888",lw=0.8); cc.set_ylabel("× дн.хода"); cc.set_xlabel("час дня (UTC)")
    cc.set_title("③ СКОЛЬКО обычного дневного хода уже пройдено (1.0 = как в обычный день, выше = ход почти выбран)",loc="left",fontsize=9.5); cc.grid(alpha=0.15)
    fig.tight_layout(rect=[0,0,1,0.97])
    p=OUT/f"etap_225_{symbol}.png"; fig.savefig(p,dpi=115)
    print(f"{symbol}: {cur[1]} P={cur[2]:.2f} {cur[5]} смен={flips} → {p.name}")
    return p


def main():
    btc=pd.read_csv(BTC,index_col=0,parse_dates=True)
    if btc.index.tz is None: btc.index=btc.index.tz_localize("UTC")
    M=L.fit_per_hour(L.build(btc).replace([np.inf,-np.inf],np.nan).fillna(0.0))
    print("Движок обучен на BTC. Строю дашборды...")
    dashboard("BTC", btc, M, [(61000,"61.0k опора"),(62700,"62.7k VAL"),(64200,"64.2k цель")], "{:,.0f}")
    eth=fetch("ETHUSDT")
    dashboard("ETH", eth, M, [(1603,"1603 опора"),(1650,"1650"),(1690,"1690 продажи"),(1722,"1722 цель")], "{:,.0f}")


if __name__=="__main__":
    main()
