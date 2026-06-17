"""Чистые картинки анализа BTC + ETH (matplotlib) — надёжно, без TV-глюков.
Простой язык. BTC из локального CSV, ETH дотягиваем с Binance."""
import sys, time
from pathlib import Path
import numpy as np, pandas as pd, requests
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

OUT = Path(__file__).resolve().parent / "output"
BTC = Path(__file__).resolve().parent.parent.parent / "data" / "BTCUSDT_1h_orderflow.csv"


def fetch(sym, days=36):
    end = int(time.time()*1000); cur = end - days*24*3600*1000; rows = []
    while cur < end:
        r = requests.get("https://api.binance.com/api/v3/klines",
                         params=dict(symbol=sym, interval="1h", startTime=cur, limit=1000), timeout=20)
        d = r.json()
        if not d: break
        rows += d; cur = d[-1][0] + 3600_000
    df = pd.DataFrame(rows, columns=["t","open","high","low","close","v","ct","qv","n","tb","tq","ig"])
    df["t"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    for c in ["open","high","low","close"]: df[c] = pd.to_numeric(df[c])
    return df.set_index("t")[["open","high","low","close"]]


def to4h(df):
    return df.resample("4h").agg({"open":"first","high":"max","low":"min","close":"last"}).dropna()


def candles(ax, df):
    t = mdates.date2num(df.index.tz_localize(None))
    w = (t[1]-t[0])*0.7 if len(t)>1 else 0.1
    for x,o,h,l,c in zip(t, df.open, df.high, df.low, df.close):
        col = "#26a69a" if c>=o else "#ef5350"
        ax.plot([x,x],[l,h], color=col, lw=0.7, zorder=2)
        ax.add_patch(plt.Rectangle((x-w/2, min(o,c)), w, abs(c-o)+1e-9, color=col, zorder=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    return t


def panel(ax, df, title, boxes, lines, note):
    t = candles(ax, df)
    x0, x1 = t[0], t[-1]
    for lo, hi, col, lab in boxes:
        ax.axhspan(lo, hi, color=col, alpha=0.13, zorder=1)
        ax.text(x1, (lo+hi)/2, "  "+lab, va="center", ha="left", fontsize=9, color=col, weight="bold")
    for y, col, ls, lab in lines:
        ax.axhline(y, color=col, lw=1.6, ls=ls, zorder=1)
        ax.text(x1, y, "  "+lab, va="center", ha="left", fontsize=9, color=col, weight="bold")
    ax.set_title(title, fontsize=13, loc="left", weight="bold")
    ax.text(0.012, 0.04, note, transform=ax.transAxes, fontsize=10.5, va="bottom",
            bbox=dict(boxstyle="round", fc="white", ec="#bbb", alpha=0.92))
    ax.set_xlim(x0, x1 + (x1-x0)*0.22)
    ax.grid(alpha=0.15)


def main():
    print("BTC из CSV, ETH с Binance...")
    btc = pd.read_csv(BTC, index_col=0, parse_dates=True)
    if btc.index.tz is None: btc.index = btc.index.tz_localize("UTC")
    btc = to4h(btc[["open","high","low","close"]].iloc[-36*24:])
    eth = to4h(fetch("ETHUSDT"))
    bp, ep = btc.close.iloc[-1], eth.close.iloc[-1]
    print(f"  BTC {bp:,.0f} | ETH {ep:,.0f}")

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(15, 13))

    panel(a1, btc, f"BTC ${bp:,.0f} — РЕЖИМ: рост (пробили утренний коридор вверх)",
        boxes=[(64800,66200,"#d32f2f","64.8-66.2k зона продаж"),(59500,61100,"#2e7d32","59.5-61.1k зона покупок")],
        lines=[(67900,"#7b1fa2","-","67.9k сильная цель сверху"),(64200,"#1565c0","--","64.2k ближняя цель"),
               (62700,"#6a1b9a","-","62.7k опора (вернулись выше)"),(61000,"#ef6c00","--","61.0k главная опора"),
               (59100,"#e65100","-","59.1k дно")],
        note="BTC: сегодня растём (+3%).\n▲ Пока выше 61.0k → цель 64.2k → 64.8-66.2k → 67.9k\n▼ Ниже 61.0k → разворот вниз, к 59.5-59.1k\nКуда пойдёт — заранее не угадать. Это карта уровней, не прогноз.")

    panel(a2, eth, f"ETH ${ep:,.0f} — слабее BTC, упёрся в зону продаж",
        boxes=[(1690,1722,"#d32f2f","1690-1722 зона продаж (цена тут)"),(1650,1690,"#0097a7","1650-1690 опора"),
               (1505,1560,"#2e7d32","1505-1560 зона покупок")],
        lines=[(1722,"#1565c0","--","1722 цель сверху"),(1603,"#ef6c00","-","1603 главная опора"),
               (1505,"#e65100","-","1505 дно")],
        note="ETH: подрос, но слабее BTC (ниже максимумы).\n▲ Пробьём 1722 → выше, к 1760-1850\n▼ Оттолкнёт вниз → к 1650, потом 1603 (ниже 1603 → к 1505)\nКуда пойдёт — заранее не угадать. Это карта уровней, не прогноз.")

    fig.tight_layout()
    OUT.mkdir(exist_ok=True)
    p = OUT / "etap_223_btc_eth.png"; fig.savefig(p, dpi=110)
    print(f"Saved: {p}")


if __name__ == "__main__":
    main()
