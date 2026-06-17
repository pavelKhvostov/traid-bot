"""etap_224 — ЖИВОЙ ДАШБОРД дня: визуализирует ВСЕ нововведения в одной картинке.
Контраст с «нарисовал зоны и угадал»: видно, как режим и вероятность ЖИВУТ по часам.

3 панели (общая ось — час дня):
  A) цена 1h + Initial Balance + зоны + ФОН по режиму (зелёный=TREND_UP / серый=ROTATION / красный=DOWN)
  B) калиброванная P(зелёный): сырая + сглаженная + мёртвая зона + call (LONG/SHORT/HOLD)
  C) gauge «% ожидаемого хода уже выбрано» (vol-нормировка)

Запуск: venv/Scripts/python.exe research/daily_engine/etap_224_live_dashboard.py
"""
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

DATA = HERE.parent.parent / "data" / "BTCUSDT_1h_orderflow.csv"
COL = {"TREND_UP": "#2e7d32", "TREND_DOWN": "#c62828", "ROTATION": "#9e9e9e", "FORMING": "#cfcfcf"}


def main():
    df = pd.read_csv(DATA, index_col=0, parse_dates=True)
    if df.index.tz is None: df.index = df.index.tz_localize("UTC")
    M = L.fit_per_hour(L.build(df).replace([np.inf, -np.inf], np.nan).fillna(0.0))

    day = df.index.normalize().unique()[-1]
    g = df[df.index.normalize() == day]
    o = g["open"].iloc[0]; c = g["close"].values; H = g["high"].values; Lo = g["low"].values
    dec, flips = L.daytype_nowcast(g, M)        # (k, state, p, p_sm, mode, call)
    ks = [d[0] for d in dec]; states = [d[1] for d in dec]
    praw = [d[2] for d in dec]; psm = [d[3] for d in dec]; calls = [d[5] for d in dec]

    # ожидаемый дневной ход (медиана за 20 дней) для gauge
    daily = df.resample("1D").agg({"open": "first", "high": "max", "low": "min"})
    exp = ((daily.high - daily.low) / daily.open).rolling(20).median().shift(1).reindex([day]).iloc[0]
    hi = np.maximum.accumulate(H); lo = np.minimum.accumulate(Lo)
    up_used = (hi / o - 1) / exp; dn_used = (o / lo - 1) / exp
    net_used = up_used - dn_used

    fig, (a, b, cc) = plt.subplots(3, 1, figsize=(14, 12), height_ratios=[3, 2, 1.3], sharex=True)
    cur = dec[-1]
    fig.suptitle(f"BTC · ЖИВОЙ ДВИЖОК дня {pd.Timestamp(day).date()}   "
                 f"СЕЙЧАС: {cur[1]} | P(вверх)={cur[2]:.0%} | {cur[4]}/{cur[5]} | смен мнения: {flips}",
                 fontsize=14, weight="bold")

    # A) цена + IB + зоны + фон режима
    for k in ks:
        a.axvspan(k-0.5, k+0.5, color=COL[states[k]], alpha=0.13, zorder=0)
    w = 0.6
    for k in ks:
        col = "#26a69a" if c[k] >= (o if k == 0 else c[k-1]) else "#ef5350"
        a.plot([k, k], [Lo[k], H[k]], color=col, lw=1, zorder=3)
        a.add_patch(Rectangle((k-w/2, min(g['open'].values[k], c[k])), w,
                              abs(c[k]-g['open'].values[k])+1, color=col, zorder=4))
    ib_h, ib_l = H[:L.IB].max(), Lo[:L.IB].min()
    a.add_patch(Rectangle((-0.5, ib_l), L.IB, ib_h-ib_l, fill=False, ec="#1565c0", lw=1.5, ls="--", zorder=5))
    a.text(L.IB-0.5, ib_h, " Initial Balance (утр. коридор)", color="#1565c0", fontsize=9, va="bottom")
    for y, lab in [(61000, "61.0k опора"), (62700, "62.7k VAL"), (64200, "64.2k цель")]:
        if lo.min() < y < hi.max()*1.01:
            a.axhline(y, color="#7b1fa2", lw=1, ls=":", alpha=0.7); a.text(ks[-1], y, f" {lab}", color="#7b1fa2", fontsize=8, va="center")
    a.set_ylabel("цена"); a.set_title("① Цена + Initial Balance + ЗОНЫ + фон = режим дня (зел=тренд↑ / сер=ротация / крас=тренд↓)", loc="left", fontsize=11)
    a.grid(alpha=0.15)

    # B) калиброванная вероятность
    b.axhspan(0.43, 0.57, color="#bdbdbd", alpha=0.3, zorder=0, label="мёртвая зона (HOLD)")
    b.axhline(0.5, color="#888", lw=0.8)
    b.plot(ks, praw, color="#90a4ae", lw=1, label="P сырая (час)")
    b.plot(ks, psm, color="#1a1a1a", lw=2.4, label="P сглаженная")
    for k in ks:
        cl = {"LONG": "#2e7d32", "SHORT": "#c62828", "HOLD": "#9e9e9e"}[calls[k]]
        b.scatter(k, psm[k], color=cl, s=45, zorder=5)
    b.set_ylim(0, 1); b.set_ylabel("P(день зелёный)")
    b.set_title("② Калиброванная вероятность: живёт по часам, но стабильна (точки = решение LONG/SHORT/HOLD)", loc="left", fontsize=11)
    b.legend(loc="upper left", fontsize=8, ncol=4); b.grid(alpha=0.15)

    # C) gauge % ожидаемого хода
    cc.bar(ks, net_used, color=["#2e7d32" if x > 0 else "#c62828" for x in net_used], alpha=0.7)
    cc.axhline(0, color="#888", lw=0.8)
    for thr in [0.5, -0.5]:
        cc.axhline(thr, color="#bbb", lw=0.8, ls="--")
    cc.set_ylabel("% ожид. хода"); cc.set_xlabel("час дня (UTC)")
    cc.set_title("③ Vol-gauge: сколько ожидаемого дневного хода уже выбрано (нормировано на режим)", loc="left", fontsize=11)
    cc.grid(alpha=0.15)

    fig.tight_layout(rect=[0, 0, 1, 0.97])
    p = HERE / "output" / "etap_224_dashboard.png"; fig.savefig(p, dpi=115)
    print(f"СЕЙЧАС: {cur[1]} P={cur[2]:.2f} {cur[5]} | смен мнения {flips}")
    print(f"Saved: {p}")


if __name__ == "__main__":
    main()
