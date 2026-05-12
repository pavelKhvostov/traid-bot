"""Сборка PDF-презентации по главным открытиям 3.2 + ASVK RSI.

10 слайдов в стиле dark-theme. Использует уже посчитанные CSV-результаты
из research/3_2/.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    if _ROOT.parent == _ROOT:
        raise RuntimeError("repo root not found")
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from pathlib import Path

import matplotlib.image as mpimg
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyBboxPatch
import numpy as np
import pandas as pd

OUT_PDF = Path("research/3_2/presentation/3_2_asvk_findings.pdf")
ASVK_IMG = Path("research/asvk_rsi/asvk_rsi_BTCUSDT_1h.png")
H15_CSV = Path("signals/strategy_3_2_h15.csv")

# Color palette (dark theme)
BG = "#0e1217"
PANEL = "#161b24"
TEXT = "#d6e0f0"
MUTED = "#7b8597"
ACCENT = "#2769b0"
GREEN = "#4caf4f"
RED = "#ff5252"
YELLOW = "#ffd54f"
PURPLE = "#9c27b0"
ORANGE = "#ff9800"

PAGE_SIZE = (11.69, 8.27)  # A4 landscape


def _setup_page(fig):
    fig.patch.set_facecolor(BG)


def _title(fig, text, sub=None):
    fig.text(0.06, 0.93, text, color=TEXT, fontsize=22, fontweight="bold")
    if sub:
        fig.text(0.06, 0.88, sub, color=MUTED, fontsize=12)
    fig.text(0.06, 0.04, "Strategy 3.2 + ASVK RSI · BTCUSDT 3y",
             color=MUTED, fontsize=8)
    fig.text(0.94, 0.04, "2026-05-06", color=MUTED, fontsize=8, ha="right")


def _ax(fig, rect):
    ax = fig.add_axes(rect)
    ax.set_facecolor(PANEL)
    for s in ax.spines.values():
        s.set_color("#3a4252")
    ax.tick_params(colors=TEXT)
    return ax


# -------- SLIDE 1: COVER --------

def slide_cover(pdf):
    fig = plt.figure(figsize=PAGE_SIZE)
    _setup_page(fig)
    fig.text(0.5, 0.62, "Strategy 3.2 + ASVK RSI",
             color=TEXT, fontsize=44, fontweight="bold", ha="center")
    fig.text(0.5, 0.55, "Research Summary",
             color=ACCENT, fontsize=24, ha="center")
    fig.text(0.5, 0.43, "11 гипотез · 245 сигналов · BTCUSDT 3 года",
             color=MUTED, fontsize=14, ha="center")
    fig.text(0.5, 0.38, "1d-fractal → FVG-4h → FVG-1h",
             color=MUTED, fontsize=12, ha="center", style="italic")

    # decorative bar
    ax = fig.add_axes([0.15, 0.22, 0.7, 0.03])
    ax.set_facecolor(BG)
    ax.barh([0], [10], color=ACCENT, height=0.6)
    ax.barh([0], [3], color=GREEN, left=10, height=0.6)
    ax.barh([0], [2], color=YELLOW, left=13, height=0.6)
    ax.barh([0], [4], color=RED, left=15, height=0.6)
    ax.set_xlim(0, 19)
    ax.axis("off")
    fig.text(0.15, 0.27, "edge ★★★★", color=ACCENT, fontsize=9)
    fig.text(0.4, 0.27, "★★★", color=GREEN, fontsize=9)
    fig.text(0.55, 0.27, "★★", color=YELLOW, fontsize=9)
    fig.text(0.7, 0.27, "✗ не работает", color=RED, fontsize=9)

    fig.text(0.5, 0.12,
             "Andrew · 2026-05-06",
             color=MUTED, fontsize=11, ha="center")
    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


# -------- SLIDE 2: STRATEGY 3.2 --------

def slide_strategy(pdf):
    fig = plt.figure(figsize=PAGE_SIZE)
    _setup_page(fig)
    _title(fig, "Strategy 3.2 — Логика",
           "Mean-reversion от FVG-4h, подтверждение через FVG-1h в 8h окне")

    # Funnel diagram
    ax = _ax(fig, [0.06, 0.22, 0.55, 0.6])
    stages = [
        ("FVG-4h детектирован", 1217, ACCENT),
        ("Цена коснулась зоны (touch)", 1174, ACCENT),
        ("2 свечи rejection прошли", 467, YELLOW),
        ("Найдена FVG-1h в 8h окне\n→ SIGNAL", 245, GREEN),
    ]
    y_pos = list(range(len(stages)))
    widths = [s[1] for s in stages]
    colors = [s[2] for s in stages]
    bars = ax.barh(y_pos, widths, color=colors, height=0.6, alpha=0.85)
    for i, (label, val, _) in enumerate(stages):
        ax.text(val + 30, i, f"{val}", color=TEXT, fontsize=12, va="center", fontweight="bold")
    ax.set_yticks(y_pos)
    ax.set_yticklabels([s[0] for s in stages], color=TEXT, fontsize=10)
    ax.invert_yaxis()
    ax.set_xlim(0, 1400)
    ax.set_xlabel("количество сетапов за 3 года", color=MUTED, fontsize=9)
    ax.grid(axis="x", color="#202632", linewidth=0.5)
    ax.set_title("Воронка отсева", color=TEXT, fontsize=12, pad=10)

    # Right: baseline metrics
    ax2 = _ax(fig, [0.66, 0.22, 0.28, 0.6])
    ax2.axis("off")
    ax2.set_xlim(0, 1)
    ax2.set_ylim(0, 1)

    box = FancyBboxPatch((0.05, 0.05), 0.9, 0.9, boxstyle="round,pad=0.02",
                         facecolor=PANEL, edgecolor=ACCENT, linewidth=1.5)
    ax2.add_patch(box)
    ax2.text(0.5, 0.88, "Baseline RR=1.0", color=TEXT, fontsize=14,
             fontweight="bold", ha="center")
    ax2.text(0.5, 0.78, "(245 closed)", color=MUTED, fontsize=9, ha="center")

    metrics = [
        ("Win Rate", "55.1%", GREEN),
        ("PnL", "+25.0R", GREEN),
        ("R/trade", "+0.103", ACCENT),
        ("LONG", "57% / +17R", GREEN),
        ("SHORT", "53% / +8R", YELLOW),
    ]
    for i, (k, v, c) in enumerate(metrics):
        y = 0.66 - i * 0.11
        ax2.text(0.10, y, k, color=MUTED, fontsize=10)
        ax2.text(0.90, y, v, color=c, fontsize=12, fontweight="bold", ha="right")

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


# -------- SLIDE 3: ASVK RSI INDICATOR --------

def slide_asvk(pdf):
    fig = plt.figure(figsize=PAGE_SIZE)
    _setup_page(fig)
    _title(fig, "ASVK Custom RSI",
           "Amplified RSI + адаптивные OB/OS + NWE-канал + 4 типа дивергенций")

    # Embed image
    if ASVK_IMG.exists():
        ax = fig.add_axes([0.06, 0.20, 0.6, 0.7])
        img = mpimg.imread(ASVK_IMG)
        ax.imshow(img)
        ax.axis("off")

    # Components panel
    ax2 = fig.add_axes([0.7, 0.20, 0.25, 0.7])
    ax2.set_facecolor(PANEL)
    ax2.axis("off")
    ax2.set_xlim(0, 1)
    ax2.set_ylim(0, 1)
    ax2.text(0.5, 0.95, "Компоненты", color=TEXT, fontsize=13,
             fontweight="bold", ha="center")
    items = [
        (ACCENT, "Adjusted RSI (ema_3)", "rsi² × coef / EMA5"),
        (PURPLE, "NWE-канал", "Гаусс smoothing"),
        (RED, "Overbought (dyn)", "(z+200)/4"),
        (GREEN, "Oversold (dyn)", "100−49(z+200)/200"),
        (YELLOW, "Дивергенции", "regular/hidden ×2"),
        (TEXT, "Структурные ▲▼", "EMA50 локальных"),
    ]
    for i, (c, name, desc) in enumerate(items):
        y = 0.85 - i * 0.13
        ax2.add_patch(mpatches.Circle((0.08, y + 0.02), 0.02, color=c))
        ax2.text(0.16, y + 0.025, name, color=TEXT, fontsize=10, fontweight="bold")
        ax2.text(0.16, y - 0.02, desc, color=MUTED, fontsize=8)

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


# -------- SLIDE 4: TOP FINDING #1 — H15 SIZING --------

def slide_h15(pdf):
    df = pd.read_csv(H15_CSV)
    closed = df[df["outcome"].isin(["win", "loss"])]

    by_score = closed.groupby("confluence_score").agg(
        n=("outcome", "size"),
        wins=("outcome", lambda s: (s == "win").sum()),
    )
    by_score["losses"] = by_score["n"] - by_score["wins"]
    by_score["WR"] = by_score["wins"] / by_score["n"] * 100
    by_score["fixedR"] = by_score["wins"] - by_score["losses"]
    by_score["pos_mult"] = 1.0 + 0.5 * by_score.index
    by_score["sizedR"] = by_score["fixedR"] * by_score["pos_mult"]

    fig = plt.figure(figsize=PAGE_SIZE)
    _setup_page(fig)
    _title(fig, "★★★★ H15 — Confluence Sizing",
           "PnL множитель 2.04× при том же количестве сделок")

    # Left: bar chart sizedR per score
    ax = _ax(fig, [0.06, 0.20, 0.55, 0.65])
    scores = by_score.index.tolist()
    colors = []
    for fr in by_score["fixedR"]:
        colors.append(GREEN if fr > 0 else (RED if fr < 0 else MUTED))
    bars = ax.bar([f"score={s}" for s in scores],
                  by_score["sizedR"],
                  color=colors, edgecolor="#3a4252", linewidth=0.8)
    for bar, n, wr, sized, fixedr in zip(bars, by_score["n"], by_score["WR"],
                                         by_score["sizedR"], by_score["fixedR"]):
        h = bar.get_height()
        offset = 1.5 if h >= 0 else -1.5
        va = "bottom" if h >= 0 else "top"
        ax.text(bar.get_x() + bar.get_width() / 2, h + offset,
                f"{sized:+.0f}R\nn={n} · WR {wr:.0f}%",
                ha="center", va=va, color=TEXT, fontsize=9, fontweight="bold")
    ax.axhline(0, color="#3a4252", linewidth=0.8)
    ax.set_ylabel("PnL после sizing (R)", color=TEXT, fontsize=11)
    ax.set_title("Score 0 — антифильтр (-5R) · Score 2-4 — сильный edge",
                 color=TEXT, fontsize=11, pad=10)
    ax.grid(axis="y", color="#202632", linewidth=0.5)

    # Right: comparison panel
    ax2 = fig.add_axes([0.66, 0.20, 0.28, 0.65])
    ax2.set_facecolor(PANEL)
    ax2.axis("off")
    ax2.set_xlim(0, 1)
    ax2.set_ylim(0, 1)
    box = FancyBboxPatch((0.04, 0.04), 0.92, 0.92, boxstyle="round,pad=0.02",
                         facecolor=PANEL, edgecolor=GREEN, linewidth=1.5)
    ax2.add_patch(box)
    ax2.text(0.5, 0.88, "Итого", color=TEXT, fontsize=14,
             fontweight="bold", ha="center")
    ax2.text(0.5, 0.78, "All 245 signals", color=MUTED, fontsize=9, ha="center")

    rows = [
        ("Fixed 1R", "+25R", "0.103", ACCENT),
        ("Sized", "+51R", "0.210", GREEN),
        ("Score>=1", "+30R", "0.221", GREEN),
        ("Score>=1 sized", "+56R", "0.412", GREEN),
        ("Score>=2 sized", "+35R", "0.583", GREEN),
    ]
    for i, (k, v1, v2, c) in enumerate(rows):
        y = 0.65 - i * 0.10
        ax2.text(0.08, y, k, color=MUTED, fontsize=10)
        ax2.text(0.55, y, v1, color=c, fontsize=11, fontweight="bold", ha="right")
        ax2.text(0.92, y, f"R/tr {v2}", color=c, fontsize=9, ha="right")
    ax2.text(0.5, 0.10, "→ Score 0 (107 сделок)\nрежем в первую очередь",
             color=YELLOW, fontsize=9, ha="center", style="italic")

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


# -------- SLIDE 5: TOP #2 — H1 + RR SWEEP --------

def slide_h1_rr(pdf):
    fig = plt.figure(figsize=PAGE_SIZE)
    _setup_page(fig)
    _title(fig, "★★★ H1 — Divergence + RR-sweep",
           "Aligned div в окне [touch-6h, signal] позволяет тянуть RR до 1.75")

    rrs = [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]
    baseline_rt = [0.103, 0.111, 0.132, 0.132, 0.074, 0.051, 0.053]
    h1_rt = [0.255, 0.324, 0.373, 0.402, 0.235, 0.098, 0.098]
    h1_an2_rt = [0.250, 0.266, 0.328, 0.289, 0.406, 0.203, 0.250]

    ax = _ax(fig, [0.08, 0.22, 0.55, 0.62])
    ax.plot(rrs, baseline_rt, "-o", color=MUTED, linewidth=2,
            markersize=7, label="Baseline (n=243)")
    ax.plot(rrs, h1_rt, "-o", color=GREEN, linewidth=2.5,
            markersize=9, label="H1 aligned div (n=51)")
    ax.plot(rrs, h1_an2_rt, "-o", color=ORANGE, linewidth=2,
            markersize=7, label="H1 ∩ no-SHORT-range (n=32)")

    # Annotate peak
    peak_h1 = h1_rt.index(max(h1_rt))
    ax.scatter([rrs[peak_h1]], [h1_rt[peak_h1]], s=200,
               facecolors="none", edgecolors=YELLOW, linewidth=2.5, zorder=5)
    ax.annotate(f"peak R/tr = {h1_rt[peak_h1]:.3f}\nat RR={rrs[peak_h1]}",
                xy=(rrs[peak_h1], h1_rt[peak_h1]),
                xytext=(rrs[peak_h1] + 0.1, h1_rt[peak_h1] + 0.05),
                color=YELLOW, fontsize=10, fontweight="bold",
                arrowprops=dict(arrowstyle="->", color=YELLOW))

    ax.axhline(0.103, color=MUTED, linewidth=0.7, linestyle="--", alpha=0.5)
    ax.text(2.95, 0.105, "baseline RR=1", color=MUTED, fontsize=8, ha="right")

    ax.set_xlabel("RR ratio", color=TEXT, fontsize=11)
    ax.set_ylabel("R / trade", color=TEXT, fontsize=11)
    ax.set_title("R/trade vs RR — фильтр позволяет тянуть выше RR",
                 color=TEXT, fontsize=11, pad=10)
    ax.grid(True, color="#202632", linewidth=0.5)
    ax.legend(facecolor=PANEL, edgecolor="#3a4252", labelcolor=TEXT, fontsize=10)
    ax.set_xticks(rrs)

    # Right summary
    ax2 = fig.add_axes([0.68, 0.22, 0.27, 0.62])
    ax2.set_facecolor(PANEL)
    ax2.axis("off")
    ax2.set_xlim(0, 1)
    ax2.set_ylim(0, 1)
    box = FancyBboxPatch((0.04, 0.04), 0.92, 0.92, boxstyle="round,pad=0.02",
                         facecolor=PANEL, edgecolor=GREEN, linewidth=1.5)
    ax2.add_patch(box)
    ax2.text(0.5, 0.92, "H1 best @ RR=1.75", color=TEXT, fontsize=13,
             fontweight="bold", ha="center")
    rows = [
        ("n", "51 (21% от 243)"),
        ("WR", "51.0%"),
        ("PnL", "+20.5R"),
        ("R/trade", "+0.402"),
        ("vs baseline", "3.9× edge"),
    ]
    for i, (k, v) in enumerate(rows):
        y = 0.78 - i * 0.10
        ax2.text(0.10, y, k, color=MUTED, fontsize=10)
        ax2.text(0.92, y, v, color=GREEN, fontsize=11, fontweight="bold", ha="right")
    ax2.text(0.5, 0.18,
             "Чем строже фильтр\nна качество — тем выше RR",
             color=YELLOW, fontsize=9, ha="center", style="italic")

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


# -------- SLIDE 6: TOP #3 — H12 NWE TP ASYMMETRY --------

def slide_h12(pdf):
    fig = plt.figure(figsize=PAGE_SIZE)
    _setup_page(fig)
    _title(fig, "★★★ H12 — NWE-TP: асимметричный edge",
           "TP по пробою NWE-канала работает ТОЛЬКО для LONG")

    # Bar chart LONG vs SHORT
    ax = _ax(fig, [0.10, 0.22, 0.40, 0.62])
    cats = ["LONG\n(n=123)", "SHORT\n(n=122)", "ALL\n(n=245)"]
    values = [44.8, -37.5, 7.3]
    colors = [GREEN, RED, MUTED]
    bars = ax.bar(cats, values, color=colors, edgecolor="#3a4252")
    for bar, v in zip(bars, values):
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width() / 2,
                h + (3 if h >= 0 else -3),
                f"{v:+.1f}R",
                ha="center", va=("bottom" if h >= 0 else "top"),
                color=TEXT, fontsize=13, fontweight="bold")
    ax.axhline(0, color="#3a4252", linewidth=0.8)
    ax.set_ylabel("Total PnL R (3 года)", color=TEXT, fontsize=11)
    ax.set_title("NWE-TP PnL по направлению", color=TEXT, fontsize=11, pad=10)
    ax.grid(axis="y", color="#202632", linewidth=0.5)

    # Right: stats table
    ax2 = fig.add_axes([0.55, 0.22, 0.40, 0.62])
    ax2.set_facecolor(PANEL)
    ax2.axis("off")
    ax2.set_xlim(0, 1)
    ax2.set_ylim(0, 1)

    box = FancyBboxPatch((0.04, 0.04), 0.92, 0.92, boxstyle="round,pad=0.02",
                         facecolor=PANEL, edgecolor=GREEN, linewidth=1.5)
    ax2.add_patch(box)

    ax2.text(0.5, 0.92, "LONG NWE-TP детали", color=TEXT, fontsize=14,
             fontweight="bold", ha="center")

    rows = [
        ("WR", "28.5%", YELLOW),
        ("Wins", "35", GREEN),
        ("Losses", "88", RED),
        ("avg Win", "+3.79R", GREEN),
        ("R/trade", "+0.364", GREEN),
        ("vs fixed RR=1", "3.5× edge", GREEN),
    ]
    for i, (k, v, c) in enumerate(rows):
        y = 0.78 - i * 0.10
        ax2.text(0.10, y, k, color=MUTED, fontsize=11)
        ax2.text(0.92, y, v, color=c, fontsize=12, fontweight="bold", ha="right")

    ax2.text(0.5, 0.10,
             "Низкий WR компенсируется\nбольшими выигрышами\n(BTC 3y bull market)",
             color=YELLOW, fontsize=9, ha="center", style="italic")

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


# -------- SLIDE 7: ALL HYPOTHESES TABLE --------

def slide_all_table(pdf):
    fig = plt.figure(figsize=PAGE_SIZE)
    _setup_page(fig)
    _title(fig, "Все 11 гипотез — итоговая таблица",
           "Сортировка по силе edge")

    rows = [
        ("H15", "Confluence sizing (score≥2)",      60, "63.3%", 0.583, "★★★★", GREEN),
        ("H1",  "Aligned div + RR=1.75",            51, "51.0%", 0.402, "★★★",  GREEN),
        ("H12", "NWE-TP LONG only",                123, "28.5%", 0.364, "★★★",  GREEN),
        ("H8",  "DEEP divergence (top 50%)",        26, "65.4%", 0.308, "★★",   ACCENT),
        ("H17", "Counter-trend pct extremum",       34, "61.8%", 0.235, "★★",   ACCENT),
        ("H2",  "no-SHORT-range + RR=2.5",         156, "35.3%", 0.234, "★★",   ACCENT),
        ("H9",  "4h-RSI side-of-50",                80, "60.0%", 0.200, "★★",   ACCENT),
        ("H10", "RSI vorticity (LONG)",             67, "59.7%", 0.194, "★",    YELLOW),
        ("H16", "div OR NWE-extreme",               56, "62.5%", 0.250, " ",    MUTED),
        ("H11", "bars-since-OB > 100 (LONG)",       18, "66.7%", 0.333, " ",    MUTED),
        ("H14", "NWE cancellation",                245, "57.5%", 0.106, "≈",    MUTED),
        ("H3",  "1h OB/OS at signal_time",          19, "52.6%", 0.053, "✗",    RED),
        ("H4",  "1h NWE extreme",                    5, "60.0%", 0.200, "✗",    RED),
        ("H5",  "structure shift in window",       239, "55.2%", 0.105, "≈",    MUTED),
        ("H13", "trailing opp-divergence",         245, "54.7%", 0.078, "✗",    RED),
        ("H18", "INVERSE setup",                   245, "17.6%",-0.649, "✗",    RED),
    ]
    rows.append(("—",   "BASELINE 3.2 RR=1.0",     243, "55.1%", 0.103, " ",    MUTED))

    ax = fig.add_axes([0.04, 0.10, 0.92, 0.78])
    ax.set_facecolor(PANEL)
    ax.set_xlim(0, 100)
    ax.set_ylim(-0.5, len(rows) + 0.5)
    ax.invert_yaxis()
    ax.axis("off")

    # Column headers
    ax.text(2, -0.2, "ID",      color=ACCENT, fontsize=10, fontweight="bold")
    ax.text(8, -0.2, "Сегмент", color=ACCENT, fontsize=10, fontweight="bold")
    ax.text(54, -0.2, "n",       color=ACCENT, fontsize=10, fontweight="bold")
    ax.text(64, -0.2, "WR",      color=ACCENT, fontsize=10, fontweight="bold")
    ax.text(78, -0.2, "R/trade", color=ACCENT, fontsize=10, fontweight="bold")
    ax.text(94, -0.2, "Edge",    color=ACCENT, fontsize=10, fontweight="bold")

    for i, (hid, name, n, wr, rt, mark, color) in enumerate(rows):
        bg = PANEL if i % 2 == 0 else "#1c2230"
        ax.add_patch(plt.Rectangle((0, i + 0.1), 100, 0.8, facecolor=bg,
                                   edgecolor="none"))
        ax.text(2, i + 0.5, hid, color=color, fontsize=10, fontweight="bold",
                va="center")
        ax.text(8, i + 0.5, name, color=TEXT, fontsize=10, va="center")
        ax.text(54, i + 0.5, str(n), color=TEXT, fontsize=10, va="center")
        ax.text(64, i + 0.5, wr, color=TEXT, fontsize=10, va="center")
        rt_color = GREEN if rt > 0.15 else (YELLOW if rt > 0.10 else (RED if rt < 0 else MUTED))
        ax.text(78, i + 0.5, f"{rt:+.3f}", color=rt_color, fontsize=10, va="center",
                fontweight="bold")
        ax.text(94, i + 0.5, mark, color=color, fontsize=11, va="center", ha="center")

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


# -------- SLIDE 8: WHAT DOESN'T WORK --------

def slide_failed(pdf):
    fig = plt.figure(figsize=PAGE_SIZE)
    _setup_page(fig)
    _title(fig, "Что НЕ работает — закрытые гипотезы",
           "Опровергнутые и нейтральные — тоже результат")

    cases = [
        ("H18 — Inverse setup",
         "Если есть opposite-div → перевернуть направление.",
         "WR падает до 17-23% во ВСЕХ сегментах. Opposite-div НЕ\n"
         "предсказывает разворот — 3.2 валидно работает как rejection.",
         "−0.649", RED),
        ("H13 — Trailing на opp-div",
         "Закрывать сделку при появлении противоположной дивергенции.",
         "27 exits снижают R/trade с 0.103 до 0.078. Trailing\n"
         "режет winning trades слишком рано.",
         "+0.078", RED),
        ("H4 — 1h NWE-extreme на signal_time",
         "ema_3 пробил NWE-канал в момент signal_time.",
         "n=5 — недостаточная статистика. После c2 FVG-1h ema_3\n"
         "редко в крайностях.",
         "n=5", YELLOW),
        ("H3 — 1h OB/OS на signal_time",
         "ema_3 < below_dyn (LONG) или > above_dyn (SHORT).",
         "n=19, R/trade 0.053. Аналог H4 — экстремум на signal_time\n"
         "не дискриминирует.",
         "+0.053", YELLOW),
        ("H14 — Cancellation лимита",
         "Отмена лимита если ema_3 пробивает противоположный NWE\n"
         "между signal_time и activation_time.",
         "Удаляет 69 сетапов (28%), R/trade с 0.103 → 0.106. Нейтрально:\n"
         "вычёрквает и хорошее, и плохое поровну.",
         "+0.106", MUTED),
    ]

    box_h = 0.13
    for i, (title, hyp, finding, rt, color) in enumerate(cases):
        y = 0.78 - i * 0.14
        ax = fig.add_axes([0.04, y, 0.92, 0.12])
        ax.set_facecolor(PANEL)
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 1)
        ax.axis("off")
        ax.add_patch(plt.Rectangle((0, 0), 100, 1, facecolor=PANEL,
                                   edgecolor=color, linewidth=1.2))
        ax.text(2, 0.78, title, color=color, fontsize=11, fontweight="bold")
        ax.text(2, 0.5, hyp, color=MUTED, fontsize=9)
        ax.text(2, 0.18, finding, color=TEXT, fontsize=9)
        ax.text(96, 0.5, rt, color=color, fontsize=14, fontweight="bold",
                ha="right", va="center")

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


# -------- SLIDE 9: PRODUCTION CANDIDATE --------

def slide_production(pdf):
    fig = plt.figure(figsize=PAGE_SIZE)
    _setup_page(fig)
    _title(fig, "Production-кандидат",
           "Финальная формула из лучших edge'ов")

    # Big formula box
    ax = fig.add_axes([0.06, 0.50, 0.88, 0.32])
    ax.set_facecolor(PANEL)
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    box = FancyBboxPatch((0.02, 0.05), 0.96, 0.9, boxstyle="round,pad=0.02",
                         facecolor=PANEL, edgecolor=GREEN, linewidth=2)
    ax.add_patch(box)
    ax.text(0.5, 0.85, "Финальный сетап", color=TEXT, fontsize=15,
            fontweight="bold", ha="center")
    formula_lines = [
        "  Базовый детектор 3.2: FVG-4h → 2 свечи rejection → FVG-1h в 8h",
        "+ confluence_score >= 2 (из 4 флагов: H1 div · H9 4h-side · H8 deep · H17 pct)",
        "+ position_size = 1.0 + 0.5 × confluence_score   (max 3.0R)",
        "+ для LONG: TP = NWE-Upper cross (или fallback RR=1.75)",
        "+ для SHORT: TP = RR=1.75 фикс",
    ]
    for i, line in enumerate(formula_lines):
        y = 0.65 - i * 0.10
        c = GREEN if line.startswith("+") else ACCENT
        ax.text(0.05, y, line, color=c, fontsize=11, family="monospace")

    # Expected metrics
    ax2 = fig.add_axes([0.06, 0.18, 0.42, 0.27])
    ax2.set_facecolor(PANEL)
    ax2.axis("off")
    ax2.set_xlim(0, 1)
    ax2.set_ylim(0, 1)
    ax2.add_patch(FancyBboxPatch((0.02, 0.05), 0.96, 0.9, boxstyle="round,pad=0.02",
                                 facecolor=PANEL, edgecolor=ACCENT, linewidth=1.2))
    ax2.text(0.5, 0.85, "Ожидаемые цифры (in-sample)",
             color=TEXT, fontsize=12, fontweight="bold", ha="center")
    rows = [
        ("n", "60 сделок"),
        ("WR", "63.3%"),
        ("PnL fixed-1R", "+16R"),
        ("PnL sized", "+35R"),
        ("R/trade", "+0.583"),
    ]
    for i, (k, v) in enumerate(rows):
        y = 0.70 - i * 0.13
        ax2.text(0.10, y, k, color=MUTED, fontsize=11)
        ax2.text(0.92, y, v, color=GREEN, fontsize=12, fontweight="bold", ha="right")

    # Next steps
    ax3 = fig.add_axes([0.52, 0.18, 0.42, 0.27])
    ax3.set_facecolor(PANEL)
    ax3.axis("off")
    ax3.set_xlim(0, 1)
    ax3.set_ylim(0, 1)
    ax3.add_patch(FancyBboxPatch((0.02, 0.05), 0.96, 0.9, boxstyle="round,pad=0.02",
                                 facecolor=PANEL, edgecolor=YELLOW, linewidth=1.2))
    ax3.text(0.5, 0.85, "Что нужно проверить", color=TEXT, fontsize=12,
             fontweight="bold", ha="center")
    steps = [
        "1. ETH / SOL — out-of-sample валидация",
        "2. Walk-forward по годам (2023→2024→2025)",
        "3. Robustness к параметрам (k_after, RR threshold)",
        "4. Live-prefill: что флаги доступны в момент signal",
    ]
    for i, s in enumerate(steps):
        y = 0.70 - i * 0.13
        ax3.text(0.06, y, s, color=TEXT, fontsize=10)

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


# -------- SLIDE 10: SUMMARY --------

def slide_summary(pdf):
    fig = plt.figure(figsize=PAGE_SIZE)
    _setup_page(fig)
    _title(fig, "Сводка исследования",
           "11 гипотез · 6 партий · 4 рабочих edge'а")

    # Pie of hypothesis outcomes
    ax = _ax(fig, [0.06, 0.30, 0.30, 0.55])
    sizes = [4, 4, 5, 4]
    labels = ["Strong edge\n(R/tr > 0.20)", "Moderate edge\n(0.10-0.20)",
              "Neutral", "Failed/Inverse"]
    colors = [GREEN, YELLOW, MUTED, RED]
    explode = [0.05, 0, 0, 0]
    ax.pie(sizes, labels=labels, colors=colors, autopct="%1.0f",
           startangle=90, explode=explode,
           textprops={"color": TEXT, "fontsize": 9},
           wedgeprops={"edgecolor": BG, "linewidth": 2})
    ax.set_title("Распределение 17 проверенных сегментов",
                 color=TEXT, fontsize=11, pad=10)

    # Key takeaways panel
    ax2 = fig.add_axes([0.42, 0.20, 0.54, 0.65])
    ax2.set_facecolor(PANEL)
    ax2.axis("off")
    ax2.set_xlim(0, 1)
    ax2.set_ylim(0, 1)
    ax2.add_patch(FancyBboxPatch((0.02, 0.02), 0.96, 0.96, boxstyle="round,pad=0.02",
                                 facecolor=PANEL, edgecolor=ACCENT, linewidth=1.5))

    ax2.text(0.5, 0.93, "Ключевые выводы", color=TEXT, fontsize=14,
             fontweight="bold", ha="center")

    takeaways = [
        ("★", "Position sizing по confluence — 2× PnL без новых сделок", GREEN),
        ("★", "Чем строже фильтр — тем выше можно тянуть RR", GREEN),
        ("★", "LONG и SHORT имеют разные оптимумы: NWE-TP только для LONG", GREEN),
        ("◉", "Глубина дивергенции > сам факт дивергенции", YELLOW),
        ("◉", "Multi-TF подтверждение (1h+4h) усиливает сигнал", YELLOW),
        ("✗", "Trailing на opp-div режет winners — не работает", RED),
        ("✗", "Inverse-setup на opposite-div — гипотеза опровергнута", RED),
        ("?", "Нужен out-of-sample на ETH/SOL для валидации", MUTED),
    ]
    for i, (icon, text, color) in enumerate(takeaways):
        y = 0.82 - i * 0.09
        ax2.text(0.05, y, icon, color=color, fontsize=14, fontweight="bold")
        ax2.text(0.10, y, text, color=TEXT, fontsize=10)

    fig.text(0.5, 0.10,
             "Все CSV и скрипты — в research/3_2/ ; финальный детектор — TODO",
             color=MUTED, fontsize=10, ha="center", style="italic")

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def main():
    OUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    print(f"[INFO] building PDF: {OUT_PDF}")
    with PdfPages(OUT_PDF) as pdf:
        slide_cover(pdf)
        slide_strategy(pdf)
        slide_asvk(pdf)
        slide_h15(pdf)
        slide_h1_rr(pdf)
        slide_h12(pdf)
        slide_all_table(pdf)
        slide_failed(pdf)
        slide_production(pdf)
        slide_summary(pdf)
    print(f"[OK] saved: {OUT_PDF}")
    print(f"  size: {OUT_PDF.stat().st_size / 1024:.1f} KB · 10 slides")


if __name__ == "__main__":
    main()
