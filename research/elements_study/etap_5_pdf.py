"""PDF: 5 связок (А-Д) — описания + примеры на чартах."""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyBboxPatch, Rectangle
import numpy as np
import pandas as pd

from data_manager import load_df

OUT_PDF = Path("research/elements_study/output/connections_report.pdf")
SUMMARY_CSV = Path("research/elements_study/output/connections_summary.csv")

BG = "#0e1217"
PANEL = "#161b24"
TEXT = "#d6e0f0"
MUTED = "#7b8597"
ACCENT = "#2769b0"
GREEN = "#4caf4f"
RED = "#ff5252"
YELLOW = "#ffd54f"
PURPLE = "#9c27b0"
PAGE = (11.69, 8.27)

SYMBOL = "BTCUSDT"


def _setup(fig):
    fig.patch.set_facecolor(BG)


def _ax(fig, rect):
    ax = fig.add_axes(rect)
    ax.set_facecolor(PANEL)
    for s in ax.spines.values():
        s.set_color("#3a4252")
    ax.tick_params(colors=TEXT)
    ax.grid(True, color="#202632", linewidth=0.4)
    return ax


def _title(fig, t, sub=None):
    fig.text(0.06, 0.93, t, color=TEXT, fontsize=22, fontweight="bold")
    if sub:
        fig.text(0.06, 0.88, sub, color=MUTED, fontsize=12)
    fig.text(0.06, 0.04, "Connections research · BTCUSDT 2020-2026",
             color=MUTED, fontsize=8)
    fig.text(0.94, 0.04, "2026-05-07", color=MUTED, fontsize=8, ha="right")


def draw_candles(ax, df_window, color_up=GREEN, color_dn=RED):
    """1h candlesticks. Width auto from index spacing."""
    if len(df_window) < 2:
        return
    delta = (df_window.index[1] - df_window.index[0]).total_seconds()
    width = delta / 86400 * 0.6
    for ts, row in df_window.iterrows():
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        col = color_up if c >= o else color_dn
        ax.vlines(ts, l, h, color=col, linewidth=0.6, alpha=0.85)
        body_low = min(o, c)
        body_h = abs(c - o)
        if body_h < 0.01:
            body_h = 0.01
        rect = Rectangle((mdates.date2num(ts) - width / 2, body_low),
                         width, body_h, facecolor=col, edgecolor=col,
                         linewidth=0.4, alpha=0.85)
        ax.add_patch(rect)


# -------- Slides --------

def slide_cover(pdf):
    fig = plt.figure(figsize=PAGE)
    _setup(fig)
    fig.text(0.5, 0.65, "5 Связок (Connections)", color=TEXT, fontsize=38,
             fontweight="bold", ha="center")
    fig.text(0.5, 0.58, "OB · FVG · RDRB · Fractal — синтез паттернов",
             color=ACCENT, fontsize=20, ha="center")
    fig.text(0.5, 0.48, "5 цепочек элементов · 6.4 года BTC · simple-outcome backtest",
             color=MUTED, fontsize=14, ha="center")
    fig.text(0.5, 0.36,
             "Только Связка Б показала уверенный edge\n+0.254 R/trade · 12 сделок/год",
             color=GREEN, fontsize=13, ha="center", style="italic")
    fig.text(0.5, 0.20, "Andrew · 2026-05-07", color=MUTED, fontsize=11, ha="center")
    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def slide_methodology(pdf):
    fig = plt.figure(figsize=PAGE)
    _setup(fig)
    _title(fig, "Методология",
           "Как тестируются связки и какие выводы делаем")
    ax = fig.add_axes([0.04, 0.08, 0.92, 0.78])
    ax.set_facecolor(BG)
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    items = [
        ("Что такое связка?",
         "Несколько SMC-элементов, образующих условие entry в одной зоне.\n"
         "Каждая связка задаёт детектор → entry/SL/TP → outcome.",
         ACCENT),
        ("Базовые элементы",
         "OB · FVG · RDRB — зоны с canon-формулами (vault/knowledge/smc/).\n"
         "Fractal — уровень i±2. Все детекторы импортируются из проекта.",
         YELLOW),
        ("Outcome backtest",
         "Activation: первое касание entry на 1m.\n"
         "Exit: первый из (SL, TP). Простая mean-reversion симуляция.",
         GREEN),
        ("Метрики",
         "n setups, n/year, n/2weeks (рассчёт частоты),\n"
         "WR%, total R (с учётом RR>1), mean R (R/trade).",
         PURPLE),
        ("Размер позиции и SL",
         "RR=3 для связок А/Б/В (уверенные сетапы), RR=2 для Г/Д.\n"
         "SL расширенный: за trigger-свечу + 0.3-0.5·ATR (не за zone-границу).",
         RED),
    ]
    for i, (head, body, col) in enumerate(items):
        y = 0.92 - i * 0.18
        ax.text(0.02, y, head, color=col, fontsize=13, fontweight="bold")
        for j, line in enumerate(body.split("\n")):
            ax.text(0.04, y - 0.04 - j * 0.035, line, color=TEXT, fontsize=10)
    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def slide_summary_table(pdf):
    fig = plt.figure(figsize=PAGE)
    _setup(fig)
    _title(fig, "Сводка 5 связок",
           "Сортировка по mean R/trade")
    s = pd.read_csv(SUMMARY_CSV)
    s = s.sort_values("mean_R", ascending=False)

    ax = fig.add_axes([0.04, 0.16, 0.92, 0.68])
    ax.set_facecolor(PANEL)
    ax.set_xlim(0, 100)
    ax.set_ylim(-0.5, len(s) + 0.5)
    ax.invert_yaxis()
    ax.axis("off")

    headers = ["ID", "Связка (название)", "n", "n/yr", "WR%", "total_R", "R/tr"]
    xs = [3, 12, 50, 60, 70, 80, 90]
    for h, x in zip(headers, xs):
        ax.text(x, -0.2, h, color=ACCENT, fontsize=10, fontweight="bold")

    names = {
        "A": "OB-1d small + RDRB-4h в зоне",
        "B": "FVG-1d med + sweep fractal-1h в зоне",
        "V": "Triple: OB-1d + FVG-4h + RDRB-1h",
        "G": "Counter-FVG + Counter-RDRB на 1h",
        "D": "Fractal-4h sweep + new OB-1h",
    }

    for i, (_, row) in enumerate(s.iterrows()):
        bg = PANEL if i % 2 == 0 else "#1c2230"
        ax.add_patch(plt.Rectangle((0, i + 0.1), 100, 0.8, facecolor=bg, edgecolor="none"))
        mean_r = float(row["mean_R"])
        c = GREEN if mean_r >= 0.15 else (YELLOW if mean_r > 0 else RED)
        ax.text(3, i + 0.5, str(row["connection"]), color=c, fontsize=11,
                fontweight="bold", va="center")
        ax.text(12, i + 0.5, names.get(row["connection"], ""),
                color=TEXT, fontsize=10, va="center")
        ax.text(50, i + 0.5, str(row["n_total"]), color=TEXT, fontsize=10, va="center")
        ax.text(60, i + 0.5, f"{row['n_per_year']}", color=TEXT, fontsize=10, va="center")
        ax.text(70, i + 0.5, f"{row['WR%']}", color=TEXT, fontsize=10, va="center")
        ax.text(80, i + 0.5, f"{row['total_R']:+.1f}", color=c, fontsize=10,
                fontweight="bold", va="center")
        ax.text(90, i + 0.5, f"{mean_r:+.3f}", color=c, fontsize=11,
                fontweight="bold", va="center")

    fig.text(0.06, 0.10,
             "Только Б (FVG-1d + sweep fractal) даёт уверенный edge: +17R, R/tr +0.254 на 67 сделках.\n"
             "А — слабо положительная (близко к шуму).\n"
             "В/Г/Д — отрицательно. Triple-confluence НЕ работает на наших данных.",
             color=MUTED, fontsize=10, style="italic")

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def _slide_connection_text(pdf, hid, name, mechanic, why, formula, results, verdict, vc):
    fig = plt.figure(figsize=PAGE)
    _setup(fig)
    _title(fig, f"Связка {hid} — {name}")

    ax_l = fig.add_axes([0.04, 0.10, 0.50, 0.78])
    ax_l.set_facecolor(BG)
    ax_l.axis("off")
    ax_l.set_xlim(0, 1)
    ax_l.set_ylim(0, 1)
    sections = [("МЕХАНИКА", mechanic, ACCENT),
                ("ЗАЧЕМ", why, YELLOW),
                ("УСЛОВИЯ", formula, GREEN)]
    y = 0.95
    for header, body, color in sections:
        ax_l.text(0.0, y, header, color=color, fontsize=11, fontweight="bold")
        y -= 0.04
        for line in body.split("\n"):
            ax_l.text(0.02, y, line, color=TEXT, fontsize=9)
            y -= 0.035
        y -= 0.025

    ax_r = fig.add_axes([0.56, 0.10, 0.40, 0.78])
    ax_r.set_facecolor(PANEL)
    ax_r.axis("off")
    ax_r.set_xlim(0, 1)
    ax_r.set_ylim(0, 1)
    ax_r.add_patch(FancyBboxPatch((0.02, 0.02), 0.96, 0.96, boxstyle="round,pad=0.02",
                                   facecolor=PANEL, edgecolor="#3a4252", linewidth=1.0))
    ax_r.text(0.5, 0.92, "РЕЗУЛЬТАТЫ", color=TEXT, fontsize=12,
              fontweight="bold", ha="center")
    for i, (k, v, c) in enumerate(results):
        y = 0.80 - i * 0.07
        ax_r.text(0.06, y, k, color=MUTED, fontsize=10)
        ax_r.text(0.94, y, v, color=c, fontsize=11, fontweight="bold", ha="right")

    ax_r.add_patch(FancyBboxPatch((0.05, 0.06), 0.90, 0.16, boxstyle="round,pad=0.02",
                                   facecolor=BG, edgecolor=vc, linewidth=1.5))
    ax_r.text(0.5, 0.18, "ВЕРДИКТ", color=vc, fontsize=10,
              fontweight="bold", ha="center")
    ax_r.text(0.5, 0.10, verdict, color=TEXT, fontsize=10, ha="center")
    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def slide_example_setup(pdf, df_1h, setup, hid, name):
    """Один слайд-пример со свечным графиком 1h вокруг сетапа."""
    fig = plt.figure(figsize=PAGE)
    _setup(fig)
    direction = setup["direction"]
    color_dir = GREEN if direction == "LONG" else RED
    arrow = "▲" if direction == "LONG" else "▼"

    fig.text(0.06, 0.93, f"Связка {hid} — Пример сделки", color=TEXT,
             fontsize=18, fontweight="bold")
    fig.text(0.06, 0.89, f"{arrow} {direction} BTCUSDT  ·  {name}",
             color=color_dir, fontsize=12, fontweight="bold")

    # Определить временное окно
    times_keys = [k for k in setup if k.endswith("_time") and setup.get(k)]
    times = []
    for k in times_keys:
        try:
            ts = pd.Timestamp(setup[k], tz="UTC")
            times.append(ts)
        except Exception:
            pass
    if setup.get("activation_time"):
        try:
            times.append(pd.Timestamp(setup["activation_time"], tz="UTC"))
        except Exception:
            pass
    if setup.get("exit_time"):
        try:
            times.append(pd.Timestamp(setup["exit_time"], tz="UTC"))
        except Exception:
            pass
    if not times:
        plt.close(fig)
        return
    win_start = min(times) - pd.Timedelta(hours=24)
    win_end = max(times) + pd.Timedelta(hours=24)
    df_w = df_1h[(df_1h.index >= win_start) & (df_1h.index <= win_end)]
    if len(df_w) < 5:
        plt.close(fig)
        return

    ax = _ax(fig, [0.04, 0.10, 0.92, 0.74])
    draw_candles(ax, df_w)

    entry = float(setup["entry"])
    sl = float(setup["sl"])
    tp = float(setup["tp"])
    y_min = min(df_w["low"].min(), sl, tp, entry) * 0.998
    y_max = max(df_w["high"].max(), sl, tp, entry) * 1.002
    ax.set_ylim(y_min, y_max)
    ax.set_xlim(df_w.index[0], df_w.index[-1])

    # Entry / SL / TP
    ax.axhline(entry, color=YELLOW, linewidth=1.4, alpha=0.9)
    ax.text(df_w.index[-1], entry, f" Entry {entry:.0f}",
            color=YELLOW, fontsize=9, fontweight="bold", va="center")
    ax.axhline(sl, color=RED, linewidth=1.2, alpha=0.9, linestyle="--")
    ax.text(df_w.index[-1], sl, f" SL {sl:.0f}",
            color=RED, fontsize=9, fontweight="bold", va="center")
    ax.axhline(tp, color=GREEN, linewidth=1.2, alpha=0.9, linestyle=":")
    ax.text(df_w.index[-1], tp, f" TP {tp:.0f}",
            color=GREEN, fontsize=9, fontweight="bold", va="center")

    # Маркеры элементов связки
    for k, c, mk in [
        ("ob_1d_time", PURPLE, "OB-1d"),
        ("fvg_1d_c2_time", "#42a5f5", "FVG-1d"),
        ("fvg_4h_time", "#26a69a", "FVG-4h"),
        ("fvg_1h_time", "#80cbc4", "FVG-1h"),
        ("rdrb_4h_time", ACCENT, "RDRB-4h"),
        ("rdrb_1h_time", "#7986cb", "RDRB-1h"),
        ("fractal_1h_time", "#ffb74d", "Fractal-1h"),
        ("fractal_4h_time", "#ff8a65", "Fractal-4h"),
        ("sweep_1h_time", "#ec407a", "Sweep-1h"),
        ("ob_1h_time", "#ce93d8", "OB-1h"),
    ]:
        if not setup.get(k):
            continue
        try:
            ts = pd.Timestamp(setup[k], tz="UTC")
        except Exception:
            continue
        if ts < df_w.index[0] or ts > df_w.index[-1]:
            continue
        ax.axvline(ts, color=c, linewidth=0.8, alpha=0.6, linestyle="-.")
        ax.text(ts, y_max - (y_max - y_min) * 0.04, mk, color=c,
                fontsize=7, ha="center", rotation=90, alpha=0.85, va="top")

    # Активация и exit маркеры
    if setup.get("activation_time"):
        try:
            ts = pd.Timestamp(setup["activation_time"], tz="UTC")
            if df_w.index[0] <= ts <= df_w.index[-1]:
                ax.scatter(ts, entry, marker="o", color=YELLOW, s=80, zorder=5,
                           edgecolors=BG, linewidths=1.2)
        except Exception:
            pass
    if setup.get("exit_time"):
        try:
            ts = pd.Timestamp(setup["exit_time"], tz="UTC")
            if df_w.index[0] <= ts <= df_w.index[-1]:
                price = tp if setup["outcome"] == "win" else sl
                color_e = GREEN if setup["outcome"] == "win" else RED
                marker_e = "*" if setup["outcome"] == "win" else "X"
                ax.scatter(ts, price, marker=marker_e, color=color_e, s=200,
                           zorder=6, edgecolors=TEXT, linewidths=1)
                ax.text(ts, price, f"  {setup['outcome'].upper()} {setup['R']:+.1f}R",
                        color=color_e, fontsize=10, fontweight="bold", va="center")
        except Exception:
            pass

    ax.set_ylabel("Price", color=TEXT)
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=8))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    ax.set_title(f"1h candles · {direction} setup · outcome: {setup.get('outcome','?').upper()}",
                 color=TEXT, fontsize=10, pad=8)
    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def slide_summary_takeaways(pdf):
    fig = plt.figure(figsize=PAGE)
    _setup(fig)
    _title(fig, "Главные выводы", "Что нашли, что развенчали")
    ax = fig.add_axes([0.06, 0.10, 0.88, 0.78])
    ax.set_facecolor(PANEL)
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.add_patch(FancyBboxPatch((0.02, 0.02), 0.96, 0.96, boxstyle="round,pad=0.02",
                                 facecolor=PANEL, edgecolor=ACCENT, linewidth=1.5))
    ax.text(0.5, 0.94, "Что показали 5 связок", color=TEXT, fontsize=14,
            fontweight="bold", ha="center")
    items = [
        ("★", "Связка Б — FVG-1d + sweep fractal-1h: +17R, R/tr +0.254", GREEN),
        ("◉", "Связка А — OB-1d + RDRB-4h: близко к шуму (+0.077)", YELLOW),
        ("✗", "Связка В (Triple) — не работает (n=23, R/tr -0.37)", RED),
        ("✗", "Связка Г (Counter+Counter на 1h) — отрицательно (-50R)", RED),
        ("✗", "Связка Д (Fractal-sweep + new OB) — отрицательно (-129R)", RED),
        ("?", "Triple-confluence (Б+RDRB+OB) НЕ улучшает edge — миф", MUTED),
        ("?", "Counter-trend на 1h-уровне ловит проигрышные moves", MUTED),
        ("!", "Размер пробы — 1 winner из 5 (20%) — реалистично", YELLOW),
    ]
    for i, (icon, text, color) in enumerate(items):
        y = 0.84 - i * 0.085
        ax.text(0.05, y, icon, color=color, fontsize=14, fontweight="bold")
        ax.text(0.10, y, text, color=TEXT, fontsize=11)
    fig.text(0.5, 0.05,
             "Главный takeaway: «многоступенчатая confluence» НЕ всегда сильнее «двух согласованных элементов».\n"
             "Простая связка Б (FVG-1d magnet + sweep-fractal trigger) — лучше triple-stack'а.",
             color=YELLOW, fontsize=10, ha="center", style="italic")
    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def main():
    OUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    print(f"[INFO] загрузка BTCUSDT 1h для примеров")
    df_1h = load_df(SYMBOL, "1h")
    df_1h = df_1h[df_1h.index >= pd.Timestamp("2020-01-01", tz="UTC")]

    print(f"[INFO] building PDF: {OUT_PDF}")
    with PdfPages(OUT_PDF) as pdf:
        slide_cover(pdf)
        slide_methodology(pdf)
        slide_summary_table(pdf)

        # Связка А
        _slide_connection_text(
            pdf, "А", "OB-1d small + RDRB-4h в зоне",
            mechanic="1. Detect small OB на 1d (size < 0.3·ATR_1d)\n"
                     "2. В окне 30 дней после OB найти первый RDRB-4h того же\n"
                     "   направления, чья зона пересекается с OB-1d\n"
                     "3. Entry = mid(RDRB), SL = trigger.low - 0.5·ATR_4h, TP=RR·3",
            why="OB-1d задаёт макро-зону «памяти рынка», RDRB-4h — точный\n"
                "тригер false-breakout с очень компактной зоной (0.07%).\n"
                "Тонкая зона + макро-контекст = высокая reliability при entry.",
            formula="OB.size/ATR_1d < 0.3\n"
                    "RDRB-4h direction == OB direction\n"
                    "RDRB.zone overlap OB.zone\n"
                    "RR_target = 3.0",
            results=[
                ("n setups", "30", TEXT),
                ("в год", "4.7", TEXT),
                ("в две недели", "0.18", TEXT),
                ("WR", "26.9%", YELLOW),
                ("Total R", "+2.0R", YELLOW),
                ("R/trade", "+0.077", YELLOW),
            ],
            verdict="◉ Близко к шуму. WR низкий из-за RR=3.\nЕдинственный edge — частота попадает в задачу (1/2.5мес).",
            vc=YELLOW)

        df_a = pd.read_csv("research/elements_study/output/connection_A.csv")
        wins_a = df_a[df_a["outcome"] == "win"].sort_values("R", ascending=False)
        if len(wins_a):
            slide_example_setup(pdf, df_1h, wins_a.iloc[0].to_dict(),
                                 "А", "OB-1d + RDRB-4h")

        # Связка Б — winner
        _slide_connection_text(
            pdf, "Б", "FVG-1d med + sweep fractal-1h в зоне  ★",
            mechanic="1. Detect FVG-1d medium size (0.3 ≤ size/ATR < 1.0)\n"
                     "2. В зоне FVG найти fractal-1h (LL для LONG, HH для SHORT)\n"
                     "3. Дождаться sweep'а: close 1h за уровнем фрактала\n"
                     "4. Дождаться возврата: следующая 1h close обратно за level\n"
                     "5. Entry = level фрактала, SL = sweep.low/high ± 0.3·ATR",
            why="FVG-1d — мощная макро-зона (магнит). Sweep fractal-1h —\n"
                "это «маленький RDRB» внутри зоны: ложный пробой уровня с\n"
                "возвратом. Двойное подтверждение от элементов разной\n"
                "природы (gap + pivot).",
            formula="FVG.size/ATR_1d ∈ [0.3, 1.0]\n"
                    "Fractal level ∈ FVG zone\n"
                    "Sweep: close[k] за уровнем\n"
                    "Return: close[k+1] обратно",
            results=[
                ("n setups", "74", TEXT),
                ("в год", "11.7", TEXT),
                ("в две недели", "0.45", TEXT),
                ("WR", "31.3%", YELLOW),
                ("Total R", "+17.0R", GREEN),
                ("R/trade", "+0.254", GREEN),
            ],
            verdict="★ ЕДИНСТВЕННЫЙ уверенный winner.\n+17R на 67 сделках, R/tr 0.254 — реальный edge.",
            vc=GREEN)

        df_b = pd.read_csv("research/elements_study/output/connection_B.csv")
        wins_b = df_b[df_b["outcome"] == "win"].sort_values("R", ascending=False)
        if len(wins_b):
            slide_example_setup(pdf, df_1h, wins_b.iloc[0].to_dict(),
                                 "Б", "FVG-1d + sweep fractal-1h")

        # Связка В
        _slide_connection_text(
            pdf, "В", "Triple: OB-1d + FVG-4h + RDRB-1h",
            mechanic="1. small OB-1d (size/ATR < 0.3)\n"
                     "2. FVG-4h того же направления в зоне OB\n"
                     "3. RDRB-1h того же направления в зоне FVG ∩ OB\n"
                     "4. Entry = mid(RDRB-1h), SL расширенный, RR=3",
            why="«Чем больше confluence — тем сильнее сетап» — классическая\n"
                "гипотеза SMC. Три независимых сигнала на трёх ТФ.",
            formula="all 3 элемента align (direction, zone overlap)\n"
                    "RR_target = 3.0",
            results=[
                ("n setups", "23", TEXT),
                ("в год", "3.6", TEXT),
                ("WR", "15.8%", RED),
                ("Total R", "−7.0R", RED),
                ("R/trade", "−0.368", RED),
            ],
            verdict="✗ ОПРОВЕРГНУТА. Triple-confluence НЕ работает.\nWR 15.8% катастрофически ниже даже Б.",
            vc=RED)

        # Связка Г
        _slide_connection_text(
            pdf, "Г", "Counter-FVG + Counter-RDRB на 1h",
            mechanic="1. На 1h FVG counter-trend (LONG в bear EMA200 / SHORT в bull)\n"
                     "2. RDRB того же направления в зоне FVG в окне 50 баров\n"
                     "3. Entry = mid(RDRB), SL за trigger, RR=2",
            why="Идея reversal: оба элемента указывают против тренда —\n"
                "сильный сигнал смены. На FVG counter > pro по R-data.\n"
                "Если оба согласны — должно работать.",
            formula="Direction OPPOSITE EMA200 regime\n"
                    "FVG-RDRB zone overlap\n"
                    "RR_target = 2.0",
            results=[
                ("n setups", "515", TEXT),
                ("в год", "81.3", TEXT),
                ("WR", "29.7%", RED),
                ("Total R", "−50.0R", RED),
                ("R/trade", "−0.108", RED),
            ],
            verdict="✗ ОПРОВЕРГНУТА. Counter-trend на 1h ловит много loose-moves.\nЧастота высокая, но WR не вытягивает RR=2.",
            vc=RED)

        # Связка Д
        _slide_connection_text(
            pdf, "Д", "Fractal-4h sweep + new OB-1h",
            mechanic="1. Fractal-4h (HH/LL) sweep'нут на 1h (close за level)\n"
                     "2. На свече sweep_1h или соседней — формируется OB-1h\n"
                     "   того же направления что post-sweep tradeция\n"
                     "3. Entry = mid(OB), SL = bottom-0.3·ATR, RR=2",
            why="Sweep-fractal — классический snipe-сетап. После sweep'а\n"
                "часто формируется OB как «зона возврата». Идея — ловить\n"
                "его прямо на 1h без ожидания confluence старшего ТФ.",
            formula="Fractal-4h sweep on 1h\n"
                    "OB-1h на свече sweep_idx или sweep_idx+5\n"
                    "RR_target = 2.0",
            results=[
                ("n setups", "1287", TEXT),
                ("в год", "203", TEXT),
                ("WR", "29.5%", RED),
                ("Total R", "−129.0R", RED),
                ("R/trade", "−0.114", RED),
            ],
            verdict="✗ ОПРОВЕРГНУТА. Слишком много шума.\nMRR 1.5 не вытягивает 30% WR. Нужны фильтры или skip.",
            vc=RED)

        slide_summary_takeaways(pdf)

    print(f"[OK] saved: {OUT_PDF}")
    print(f"  size: {OUT_PDF.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
