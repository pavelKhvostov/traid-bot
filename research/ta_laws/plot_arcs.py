"""Детекция арок на свежем BTC 1h — сверка детектора с паттерном-фото + чтение по условному закону.

Рисует параболу каждой найденной арки (купол/чаша), помечает силу (sagitta), apex и
вердикт mean-revert по условиям (изогнутость + apex + контекст).
Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/plot_arcs.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from matplotlib.patches import Rectangle

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import geometry as G  # noqa: E402
import curves as C    # noqa: E402


def fetch(sym, interval, limit):
    r = requests.get("https://api.binance.com/api/v3/klines",
                     params={"symbol": sym, "interval": interval, "limit": limit}, timeout=20)
    r.raise_for_status()
    d = r.json()
    df = pd.DataFrame(d, columns=["t", "open", "high", "low", "close", "v", "ct", "qv", "n", "tb", "tq", "ig"])
    df["open_time"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    return df.set_index("open_time")[["open", "high", "low", "close", "volume"]].rename(columns={"volume": "volume"}).astype(float) if False else \
        df.set_index("open_time")[["open", "high", "low", "close", "v"]].rename(columns={"v": "volume"}).astype(float)


def candles(ax, sub, x0):
    for i, (_, r) in enumerate(sub.iterrows()):
        x = x0 + i
        up = r["close"] >= r["open"]
        col = "#26a69a" if up else "#ef5350"
        ax.plot([x, x], [r["low"], r["high"]], color=col, lw=0.7, zorder=2)
        a, b = sorted([r["open"], r["close"]])
        ax.add_patch(Rectangle((x - 0.32, a), 0.64, max(b - a, 1e-9), facecolor=col, edgecolor=col, zorder=3))


def main():
    df = fetch("BTCUSDT", "1h", 1000)
    n = len(df); atr = G.compute_atr(df)
    arcs = C.find_arcs(df, atr=atr)
    start = max(n - 280, 0)
    # арки, видимые в окне
    vis = [a for a in arcs if a.i1 >= start and a.i0 >= start - 20]
    vis = sorted(vis, key=lambda a: a.sagitta_atr, reverse=True)[:5]

    fig, ax = plt.subplots(figsize=(18, 9))
    fig.patch.set_facecolor("#0e1116"); ax.set_facecolor("#0e1116")
    candles(ax, df.iloc[start:], start)
    for a in vis:
        aa, bb, cc = a.coeffs
        xs = np.arange(0, a.i1 - a.i0 + 1)
        ys = aa * xs * xs + bb * xs + cc
        gx = np.arange(a.i0, a.i1 + 1)
        col = "#ffd166" if a.kind == "ROUNDING_TOP" else "#06d6a0"
        ax.plot(gx, ys, color=col, lw=2.6, zorder=6)
        ax.scatter([a.apex_i], [a.apex_price], color=col, s=40, zorder=7)
        kindru = "КУПОЛ" if a.kind == "ROUNDING_TOP" else "ЧАША"
        apex_pos = (a.apex_i - a.i0) / max(a.i1 - a.i0, 1)
        revert = (2.5 <= a.sagitta_atr) and (apex_pos >= 0.4)
        tag = "→ склонность к развороту" if revert else "→ слабый/продолжение"
        ax.text(a.i0, a.p0, f" {kindru} sag {a.sagitta_atr:.1f}ATR, apex {apex_pos:.2f} {tag}",
                fontsize=8, color=col, fontweight="bold", zorder=8)
    ax.set_title(f"BTC 1h · детекция АРОК (parabola-fit) · {df.index[-1]:%Y-%m-%d %H:%M} UTC\n"
                 f"жёлтый=купол(ROUNDING_TOP) · зелёный=чаша(ROUNDING_BOTTOM) · точка=apex",
                 fontsize=11, color="#eee")
    ax.set_xlim(start - 2, n + 6)
    ax.grid(alpha=0.12, color="#888"); ax.tick_params(colors="#aaa", labelsize=7)
    xt = list(range(start, n, max((n - start) // 10, 1)))
    ax.set_xticks(xt); ax.set_xticklabels([df.index[t].strftime("%m-%d\n%H:%M") for t in xt])
    for sp in ax.spines.values():
        sp.set_color("#444")
    fig.tight_layout()
    out = HERE / "btc_arcs_detected.png"
    fig.savefig(out, dpi=120, facecolor=fig.get_facecolor())
    print(f"saved {out}; арок всего {len(arcs)}, в окне {len(vis)}")
    for a in vis:
        print(f"  {a.kind} {df.index[a.i0]:%m-%d %H:%M}->{df.index[a.i1]:%m-%d %H:%M} "
              f"sag {a.sagitta_atr:.1f}ATR depth {a.depth_atr:.1f} apex {(a.apex_i-a.i0)/(a.i1-a.i0):.2f}")


if __name__ == "__main__":
    main()
