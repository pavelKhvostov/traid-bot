"""BTC 1h за последнее время + паттерны ТА, размеченные нейро-модулем.

Свечи 1h (последние ~RECENT баров) + найденные архетипы: флагшток (чёрный),
линии коррекции (оранжевые/красные = against/with импульса), тип, measured-move
(пунктир — помечен честно: по валидатору континуация = фольклор).

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/plot_btc_1h_recent.py [RECENT_BARS]
Вывод: research/ta_laws/btc_1h_patterns.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import Rectangle

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import geometry as G  # noqa: E402

RECENT = int(sys.argv[1]) if len(sys.argv) > 1 else 600


def load_1h():
    df = pd.read_csv(ROOT / "data" / "BTCUSDT_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    df = df.sort_index()
    return df.resample("1h", origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])


def candles(ax, sub, x0):
    for i, (_, r) in enumerate(sub.iterrows()):
        x = x0 + i
        up = r["close"] >= r["open"]
        col = "#e8a33d" if up else "#222222"
        ax.plot([x, x], [r["low"], r["high"]], color=col, lw=0.6, zorder=2)
        a, b = sorted([r["open"], r["close"]])
        ax.add_patch(Rectangle((x - 0.32, a), 0.64, max(b - a, 1e-9), facecolor=col, edgecolor=col, zorder=3))


def clip_line(pts, lo, hi):
    """линию (x0,y0,x1,y1), заданную на [x0,x1], продлить/обрезать в [lo,hi] по наклону."""
    x0, y0, x1, y1 = pts
    if x1 == x0:
        return None
    m = (y1 - y0) / (x1 - x0)
    return (lo, y0 + m * (lo - x0), hi, y0 + m * (hi - x0))


def main():
    df = load_1h()
    n = len(df)
    start = max(n - RECENT, 0)
    arts = G.find_archetypes(df)
    # паттерны, чья коррекция завершается в окне
    inwin = [a for a in arts if a.correction.pivots[-1].conf_i >= start
             and a.correction.pivots[-1].conf_i < n]
    sub = df.iloc[start:]

    fig, ax = plt.subplots(figsize=(20, 10))
    candles(ax, sub, start)

    for a in inwin:
        d = a.impulse.direction
        # флагшток
        ax.plot([a.impulse.i0, a.impulse.i1], [a.impulse.p0, a.impulse.p1],
                color="#000000", lw=1.4, zorder=5)
        # линии коррекции — красные если against (флаг-ловушка), оранжевые если по тренду
        col = "#c0392b" if a.correction.against_impulse else "#f5a623"
        ce = a.correction.pivots[-1].i
        cu = clip_line(a.correction.upper, a.correction.pivots[0].i, ce)
        cl = clip_line(a.correction.lower, a.correction.pivots[0].i, ce)
        if cu:
            ax.plot([cu[0], cu[2]], [cu[1], cu[3]], color=col, lw=1.6, zorder=5)
        if cl:
            ax.plot([cl[0], cl[2]], [cl[1], cl[3]], color=col, lw=1.6, zorder=5)
        # measured-move (наивная цель) — пунктир
        ax.hlines(a.measured_move_tp, ce, min(ce + max(a.impulse.bars // 2, 6), n),
                  color="#888", lw=1.0, ls=":", zorder=4)
        # подпись типа
        ylab = a.impulse.p0 * (1.006 if d == "DOWN" else 0.994)
        tag = a.correction.kind + ("↯против" if a.correction.against_impulse else "")
        ax.text(a.impulse.i0, ylab, tag, fontsize=7, color=col, fontweight="bold",
                rotation=0, va="bottom" if d == "DOWN" else "top")

    ax.set_title(f"BTCUSDT 1h — паттерны ТА от нейро-модуля (последние {RECENT} баров, "
                 f"{sub.index[0]:%Y-%m-%d}..{sub.index[-1]:%m-%d})\n"
                 f"красные=коррекция против импульса (флаг-ловушка), оранжевые=по тренду; "
                 f"пунктир=measured-move (по валидатору континуация=ФОЛЬКЛОР, не прогноз)",
                 fontsize=10)
    ax.set_xlim(start - 2, n + max(20, RECENT // 20))
    ax.grid(alpha=0.15)
    xt = list(range(start, n, max((n - start) // 12, 1)))
    ax.set_xticks(xt)
    ax.set_xticklabels([df.index[t].strftime("%m-%d\n%H:%M") for t in xt], fontsize=7)
    ax.tick_params(labelsize=7)
    fig.tight_layout()
    out = HERE / "btc_1h_patterns.png"
    fig.savefig(out, dpi=120)
    print(f"saved {out}")
    print(f"BTC 1h: всего архетипов {len(arts)}, в окне последних {RECENT} баров: {len(inwin)}")
    for a in inwin[-12:]:
        t = df.index[a.correction.pivots[-1].conf_i]
        print(f"  {t:%Y-%m-%d %H:%M}  имп {a.impulse.direction} {a.impulse.atr_mag:.1f}ATR -> "
              f"{a.correction.kind}{' против' if a.correction.against_impulse else ''} "
              f"глубина {a.correction.depth_pct:.0f}%")


if __name__ == "__main__":
    main()
