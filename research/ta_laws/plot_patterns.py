"""Отрисовка найденных архетипов (импульс+коррекция+measured-move) — для сверки геометрии.

Та же нотация, что на пользовательских графиках: чёрный флагшток, оранжевые линии коррекции,
красная measured-move TP + стрелка. Прогон на BTC/ETH/SOL 4h.

Запуск: set PYTHONIOENCODING=utf-8
        venv/Scripts/python.exe research/ta_laws/plot_patterns.py [TF]
Вывод: research/ta_laws/patterns_<TF>.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import geometry as G  # noqa: E402

TF = sys.argv[1] if len(sys.argv) > 1 else "4h"
FREQ = {"1h": "1h", "2h": "2h", "4h": "4h", "12h": "12h"}[TF]
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def load_tf(sym):
    df = pd.read_csv(ROOT / "data" / f"{sym}_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    df = df.sort_index()
    return df.resample(FREQ, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])


def candles(ax, sub, x0):
    for i, (_, r) in enumerate(sub.iterrows()):
        x = x0 + i
        up = r["close"] >= r["open"]
        col = "#e8a33d" if up else "#222222"   # как на фото: orange/black
        ax.plot([x, x], [r["low"], r["high"]], color=col, linewidth=0.7, zorder=2)
        a, b = sorted([r["open"], r["close"]])
        ax.add_patch(Rectangle((x - 0.3, a), 0.6, max(b - a, 1e-12), facecolor=col, edgecolor=col, zorder=3))


def panel(ax, df, a, sym):
    proj = max(a.impulse.bars // 2, 10)
    left = max(a.impulse.i0 - 6, 0)
    right = min(a.correction.pivots[-1].i + proj + 4, len(df) - 1)
    sub = df.iloc[left:right + 1]
    candles(ax, sub, left)

    # импульс (флагшток) — чёрный
    ax.plot([a.impulse.i0, a.impulse.i1], [a.impulse.p0, a.impulse.p1],
            color="#000000", lw=1.6, zorder=5)
    # линии коррекции — оранжевые
    up = a.correction.upper; lo = a.correction.lower
    ax.plot([up[0], up[2]], [up[1], up[3]], color="#f5a623", lw=2.0, zorder=5)
    ax.plot([lo[0], lo[2]], [lo[1], lo[3]], color="#f5a623", lw=2.0, zorder=5)
    # measured-move TP — красная линия + стрелка
    ce = a.correction.pivots[-1].i
    tp = a.measured_move_tp
    ax.hlines(tp, ce + proj - 6, ce + proj + 2, color="#c0392b", lw=2.5, zorder=6)
    ax.annotate("", xy=(ce + proj, tp), xytext=(ce, a.breakout_level),
                arrowprops=dict(arrowstyle="-|>", color="#f5a623", lw=2.2,
                                connectionstyle="arc3,rad=-0.25"), zorder=6)
    ax.text(ce + proj - 6, tp, f" TP {tp:.4g}", color="#c0392b", fontsize=8, va="bottom", fontweight="bold")

    c = a.correction
    ax.set_title(f"{sym} {TF}  |  импульс {a.impulse.direction} {a.impulse.atr_mag:.1f}ATR "
                 f"-> {c.kind}{' (против)' if c.against_impulse else ''}  глубина {c.depth_pct:.0f}%",
                 fontsize=9, fontweight="bold")
    ax.set_xlim(left - 1, ce + proj + 6)
    ax.grid(alpha=0.15)
    ax.tick_params(labelsize=6)
    xt = list(range(left, right + 1, max((right - left) // 5, 1)))
    ax.set_xticks(xt)
    ax.set_xticklabels([df.index[t].strftime("%m-%d") for t in xt], fontsize=6)


def main():
    fig, axes = plt.subplots(3, 1, figsize=(15, 12))
    summary = []
    for ax, sym in zip(axes, SYMBOLS):
        df = load_tf(sym)
        arts = G.find_archetypes(df)
        kinds = {}
        for a in arts:
            kinds[a.correction.kind] = kinds.get(a.correction.kind, 0) + 1
        summary.append((sym, len(arts), kinds))
        if arts:
            panel(ax, df, arts[-1], sym)   # самый свежий архетип
        else:
            ax.set_title(f"{sym} {TF}: архетипов не найдено"); ax.axis("off")
    fig.suptitle(f"ТА-геометрия: импульс + коррекция + measured-move (последний архетип, {TF})",
                 fontsize=12, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    out = HERE / f"patterns_{TF}.png"
    fig.savefig(out, dpi=110)
    print(f"saved {out}\n")
    print("=== Сводка архетипов по символам (вся история) ===")
    for sym, n, kinds in summary:
        ks = ", ".join(f"{k}:{v}" for k, v in sorted(kinds.items(), key=lambda x: -x[1]))
        print(f"  {sym:8} всего={n:3}  | {ks}")


if __name__ == "__main__":
    main()
