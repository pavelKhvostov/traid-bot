"""Чистый график последних i-RDRB+FVG сетапов: свечи + block + FVG + entry/SL/TP позиция.

Рисует 4 панели (SHORT #1, LONG #2/#3/#5) с position-боксами (risk red / reward green).
Запуск: set PYTHONIOENCODING=utf-8
        venv/Scripts/python.exe research/i_rdrb_fvg/plot_setups.py
Вывод: research/i_rdrb_fvg/last_setups.png
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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from strategies.strategy_i_rdrb_fvg import detect_all_i_rdrb_fvg  # noqa: E402

RR = 2.0
SYM = "BTCUSDT"


def load_tf():
    df = pd.read_csv(ROOT / "data" / f"{SYM}_1m.csv",
                     parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    df = df.sort_index()
    return df.resample("1h", origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])


def outcome(df, c5_idx, s, tp):
    """Грубая симуляция на 1h: fill limit@entry с c5+1, потом SL/TP."""
    hi = df["high"].values; lo = df["low"].values
    n = len(df)
    filled = None
    for k in range(c5_idx + 1, min(c5_idx + 400, n)):
        if filled is None:
            if (s.direction == "LONG" and lo[k] <= s.entry) or \
               (s.direction == "SHORT" and hi[k] >= s.entry):
                filled = k
                continue
        else:
            if s.direction == "LONG":
                if lo[k] <= s.sl: return "LOSS", filled, k
                if hi[k] >= tp: return "WIN", filled, k
            else:
                if hi[k] >= s.sl: return "LOSS", filled, k
                if lo[k] <= tp: return "WIN", filled, k
    return ("OPEN" if filled else "NOFILL"), filled, None


def candles(ax, sub, x0):
    for i, (_, r) in enumerate(sub.iterrows()):
        x = x0 + i
        up = r["close"] >= r["open"]
        col = "#26a69a" if up else "#ef5350"
        ax.plot([x, x], [r["low"], r["high"]], color=col, linewidth=0.8, zorder=2)
        lo_b, hi_b = sorted([r["open"], r["close"]])
        ax.add_patch(Rectangle((x - 0.3, lo_b), 0.6, max(hi_b - lo_b, 1e-9),
                               facecolor=col, edgecolor=col, zorder=3))


def panel(ax, df, s, idx_map):
    c1_idx = idx_map[s.c1_time]
    c5_idx = c1_idx + 4
    tp = s.entry + RR * s.risk if s.direction == "LONG" else s.entry - RR * s.risk
    res, fill_k, end_k = outcome(df, c5_idx, s, tp)
    left = max(c1_idx - 12, 0)
    right = min((end_k or c5_idx + 40) + 6, len(df) - 1)
    sub = df.iloc[left:right + 1]
    candles(ax, sub, left)

    # зона блока (вход) над паттерном C1..C5
    bb, bt = s.block
    ax.add_patch(Rectangle((c1_idx - 0.4, bb), (c5_idx - c1_idx) + 0.8, bt - bb,
                           facecolor="#42a5f5", alpha=0.35, edgecolor="#1565c0",
                           lw=1.2, zorder=4, label="block (вход-зона)"))
    # FVG зона (C3..C5)
    fb, ft = s.fvg_zone
    ax.add_patch(Rectangle((c1_idx + 1.6, fb), (c5_idx - (c1_idx + 2)) + 0.8, ft - fb,
                           facecolor="#ffa726", alpha=0.30, edgecolor="#e65100",
                           lw=1.0, zorder=4, label="FVG"))
    # позиция: risk (red) и reward (green) от c5 вправо
    box_l = c5_idx + 0.5
    box_r = (end_k if end_k else c5_idx + 36)
    lo_r, hi_r = sorted([s.entry, s.sl])
    ax.add_patch(Rectangle((box_l, lo_r), box_r - box_l, hi_r - lo_r,
                           facecolor="#ef5350", alpha=0.16, edgecolor="none", zorder=1))
    lo_g, hi_g = sorted([s.entry, tp])
    ax.add_patch(Rectangle((box_l, lo_g), box_r - box_l, hi_g - lo_g,
                           facecolor="#26a69a", alpha=0.16, edgecolor="none", zorder=1))
    for y, c, lab in [(s.entry, "#000000", f"ВХОД {s.entry:,.0f}"),
                      (s.sl, "#d32f2f", f"СТОП {s.sl:,.0f}"),
                      (tp, "#2e7d32", f"TP {tp:,.0f}")]:
        ax.axhline(y, xmin=0, xmax=1, color=c, lw=1.0,
                   ls=("-" if c == "#000000" else "--"), zorder=5)
        ax.text(box_r + 0.5, y, lab, color=c, fontsize=8, va="center", fontweight="bold")
    if fill_k:
        ax.axvline(fill_k, color="#555", lw=0.8, ls=":", zorder=2)
        ax.text(fill_k, sub["high"].max(), "fill", fontsize=7, color="#555", ha="center")

    rr_col = {"WIN": "#2e7d32", "LOSS": "#d32f2f"}.get(res, "#888")
    ax.set_title(f"{s.direction} i-RDRB+FVG  C5={s.c5_time:%m-%d %H:%M}  "
                 f"risk={s.risk:,.0f}  ->  {res}",
                 fontsize=9, color=rr_col, fontweight="bold")
    ax.set_xlim(left - 1, box_r + 9)
    ax.grid(alpha=0.15)
    ax.tick_params(labelsize=7)
    xt = list(range(left, right + 1, max((right - left) // 5, 1)))
    ax.set_xticks(xt)
    ax.set_xticklabels([df.index[t].strftime("%m-%d\n%H:%M") for t in xt], fontsize=6)


def main():
    df = load_tf()
    idx_map = {t: i for i, t in enumerate(df.index)}
    sigs = detect_all_i_rdrb_fvg(df)
    last5 = sigs[-5:]
    chosen = [last5[0], last5[1], last5[2], last5[4]]  # SHORT #1, #2, #3, #5

    fig, axes = plt.subplots(2, 2, figsize=(16, 9))
    for ax, s in zip(axes.flat, chosen):
        panel(ax, df, s, idx_map)
    h, l = axes.flat[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", ncol=2, fontsize=9)
    fig.suptitle("i-RDRB+FVG — последние сетапы на BTCUSDT 1h (вход=block edge, SL=Combined-D, TP=RR2)",
                 fontsize=12, fontweight="bold", y=0.995)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    out = ROOT / "research" / "i_rdrb_fvg" / "last_setups.png"
    fig.savefig(out, dpi=110)
    print(f"saved {out}")


if __name__ == "__main__":
    main()
