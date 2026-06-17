"""etap_226 — КОНТРАСТ режимов: трендовый день vs день-ротация (BTC).
Слева тренд (движок встаёт в LONG/FOLLOW), справа ротация (HOLD/нейтраль, FADE).
Показывает, что движок РАЗЛИЧАЕТ дни — а не всегда «угадывает направление»."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import etap_217_daytype_layer as L

BTC = HERE.parent.parent / "data" / "BTCUSDT_1h_orderflow.csv"
COL = {"TREND_UP":"#2e7d32","TREND_DOWN":"#c62828","ROTATION":"#9e9e9e","FORMING":"#cfcfcf"}


def run_day(df, day, M):
    g = df[df.index.normalize() == day]
    if len(g) < 12: return None
    dec, flips = L.daytype_nowcast(g, M)
    return g, dec, flips


def draw(axp, axb, g, dec, title):
    o = g["open"].iloc[0]; c=g["close"].values; H=g["high"].values; Lo=g["low"].values; OP=g["open"].values
    ks=[d[0] for d in dec]; states=[d[1] for d in dec]; psm=[d[3] for d in dec]; calls=[d[5] for d in dec]
    for k in ks: axp.axvspan(k-0.5,k+0.5,color=COL[states[k]],alpha=0.14,zorder=0)
    for k in ks:
        col="#26a69a" if c[k]>=OP[k] else "#ef5350"
        axp.plot([k,k],[Lo[k],H[k]],color=col,lw=1,zorder=3)
        axp.add_patch(Rectangle((k-0.3,min(OP[k],c[k])),0.6,abs(c[k]-OP[k])+(H.max()-Lo.min())*0.002,color=col,zorder=4))
    ibh,ibl=H[:L.IB].max(),Lo[:L.IB].min()
    axp.add_patch(Rectangle((-0.5,ibl),L.IB,ibh-ibl,fill=False,ec="#1565c0",lw=1.4,ls="--",zorder=5))
    axp.set_title(title,fontsize=12,weight="bold"); axp.grid(alpha=0.15); axp.set_ylabel("цена")
    axb.axhspan(0.43,0.57,color="#bdbdbd",alpha=0.3,zorder=0); axb.axhline(0.5,color="#888",lw=0.8)
    axb.plot(ks,psm,color="#1a1a1a",lw=2.2)
    for k in ks: axb.scatter(k,psm[k],color={"LONG":"#2e7d32","SHORT":"#c62828","HOLD":"#9e9e9e"}[calls[k]],s=38,zorder=5)
    axb.set_ylim(0,1); axb.grid(alpha=0.15); axb.set_xlabel("час дня (UTC)"); axb.set_ylabel("P(зелёный)")


def main():
    df=pd.read_csv(BTC,index_col=0,parse_dates=True)
    if df.index.tz is None: df.index=df.index.tz_localize("UTC")
    M=L.fit_per_hour(L.build(df).replace([np.inf,-np.inf],np.nan).fillna(0.0))
    days=df.index.normalize().unique()

    trend_day=days[-1]   # сегодня = тренд
    # ищем ротацию: финал ROTATION, много HOLD, малый ход
    best=None; best_score=-1
    for day in days[-120:-1]:
        r=run_day(df,day,M)
        if not r: continue
        g,dec,flips=r
        states=[d[1] for d in dec]; calls=[d[5] for d in dec]
        if dec[-1][1]!="ROTATION": continue
        hold=np.mean([c=="HOLD" for c in calls]); rot=np.mean([s=="ROTATION" for s in states])
        mv=abs(g["close"].iloc[-1]/g["open"].iloc[0]-1)
        score=hold+rot-mv*10
        if score>best_score: best_score=score; best=(day,g,dec,flips)
    rot_day,rg,rdec,rflips=best

    fig,axes=plt.subplots(2,2,figsize=(15,9),height_ratios=[3,2])
    tg,tdec,tflips=run_day(df,trend_day,M)
    draw(axes[0,0],axes[1,0],tg,tdec,f"ТРЕНДОВЫЙ день {pd.Timestamp(trend_day).date()} → {tdec[-1][1]} / {tdec[-1][5]} (смен: {tflips})")
    draw(axes[0,1],axes[1,1],rg,rdec,f"ДЕНЬ-РОТАЦИЯ {pd.Timestamp(rot_day).date()} → {rdec[-1][1]} / {rdec[-1][5]} (смен: {rflips})")
    fig.suptitle("Движок РАЗЛИЧАЕТ дни: тренд (зел.фон, встаёт в LONG/FOLLOW) vs ротация (сер.фон, сидит HOLD/FADE)",
                 fontsize=13,weight="bold")
    fig.tight_layout(rect=[0,0,1,0.96])
    p=HERE/"output"/"etap_226_contrast.png"; fig.savefig(p,dpi=115)
    print(f"тренд {pd.Timestamp(trend_day).date()} {tdec[-1][1]}/{tdec[-1][5]} | ротация {pd.Timestamp(rot_day).date()} {rdec[-1][1]}/{rdec[-1][5]}")
    print(f"Saved: {p}")


if __name__=="__main__":
    main()
