"""PDF презентация по C4 dual-exit с разбором конкретных сетапов на BTC 1h.

Берём топ-N сделок из combined_part2 CSV, для каждой:
  - заново симулируем C4 exit (получаем exit_time, exit_price)
  - рисуем 1h-чарт с overlay (FVG-4h, touch свечи, FVG-1h, entry/SL/exit)
  - под ним: bw2 histogram + ema_3 ASVK + NWE bands
  - собираем в один PDF
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
_RSI_DIR = _ROOT / "research" / "asvk_rsi"
_MH_DIR = _ROOT / "research" / "money_hands"
for d in (_RSI_DIR, _MH_DIR):
    if str(d) not in _sys.path:
        _sys.path.insert(0, str(d))

from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyBboxPatch, Rectangle
import numpy as np
import pandas as pd

from data_manager import load_df
from plot_asvk_rsi import (
    NWE_BANDWIDTH, NWE_BAR, NWE_MULTIPLIER,
    adjusted_rsi, nwe_bands,
)
from plot_money_hands import BW2_SMA_LEN, WT_N1, WT_N2, sma, wavetrend_blueWaves

OUT_PDF = Path("research/3_2/presentation/3_2_c4_setups.pdf")
INPUT_CSV = Path("signals/strategy_3_2_combined_part2.csv")
SYMBOL = "BTCUSDT"
TIMEOUT_DAYS = 14

# Colors
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
PAGE = (11.69, 8.27)


def parse_utc3(s):
    if pd.isna(s) or s == "":
        return None
    return pd.Timestamp(s, tz="UTC") - pd.Timedelta(hours=3)


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


def find_c4_exit(sig, df_1m, df_1h, ema_3, upper, lower, bw2):
    """Снова находим момент C4-exit (для рисования)."""
    if sig["outcome"] == "not_filled":
        return None, None, "not_filled"
    activation = parse_utc3(sig["activation_time"])
    if activation is None:
        return None, None, "not_filled"
    direction = sig["direction"]
    entry = float(sig["entry"])
    sl = float(sig["sl"])
    timeout = activation + pd.Timedelta(days=TIMEOUT_DAYS)

    sim_1m = df_1m[(df_1m.index >= activation) & (df_1m.index <= timeout)]
    sl_t = None
    for ts, c in sim_1m.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction == "LONG" and l <= sl:
            sl_t = ts
            break
        if direction == "SHORT" and h >= sl:
            sl_t = ts
            break

    sim_1h = df_1h[(df_1h.index >= activation) & (df_1h.index <= timeout)]
    nwe_t, nwe_p = None, None
    bw2_t, bw2_p = None, None
    for ts in sim_1h.index:
        em = ema_3.loc[ts] if ts in ema_3.index else None
        up = upper.loc[ts] if ts in upper.index else None
        lo = lower.loc[ts] if ts in lower.index else None
        b = bw2.loc[ts] if ts in bw2.index else None
        if em is None or up is None or lo is None or b is None:
            continue
        if not (np.isnan(em) or np.isnan(up) or np.isnan(lo)):
            if direction == "LONG" and em > up and nwe_t is None:
                nwe_t = ts
                nwe_p = float(sim_1h.loc[ts, "close"])
            if direction == "SHORT" and em < lo and nwe_t is None:
                nwe_t = ts
                nwe_p = float(sim_1h.loc[ts, "close"])
        if not np.isnan(b):
            if direction == "LONG" and b < 0 and bw2_t is None:
                bw2_t = ts
                bw2_p = float(sim_1h.loc[ts, "close"])
            if direction == "SHORT" and b > 0 and bw2_t is None:
                bw2_t = ts
                bw2_p = float(sim_1h.loc[ts, "close"])

    candidates = []
    if sl_t:
        candidates.append((sl_t, sl, "sl"))
    if nwe_t:
        candidates.append((nwe_t, nwe_p, "nwe"))
    if bw2_t:
        candidates.append((bw2_t, bw2_p, "bw2_zero"))
    if not candidates:
        return None, None, "timeout"
    candidates.sort(key=lambda x: x[0])
    return candidates[0][0], candidates[0][1], candidates[0][2]


def draw_candles(ax, df_window, color_up=GREEN, color_dn=RED):
    """Простая отрисовка свечей (1h)."""
    width = pd.Timedelta(hours=1).total_seconds() / 86400 * 0.6
    for ts, row in df_window.iterrows():
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        col = color_up if c >= o else color_dn
        # Фитиль
        ax.vlines(ts, l, h, color=col, linewidth=0.8, alpha=0.9)
        # Тело
        body_low = min(o, c)
        body_height = abs(c - o)
        if body_height < 0.01:
            body_height = 0.01
        rect = Rectangle((mdates.date2num(ts) - width / 2, body_low),
                         width, body_height,
                         facecolor=col, edgecolor=col, linewidth=0.5, alpha=0.85)
        ax.add_patch(rect)


def draw_setup_slide(pdf, sig, df_1h, df_1m, ema_3, upper, lower, bw2, bw2_sma14,
                     setup_num, total_setups):
    """Один слайд с разобранным сетапом."""
    direction = sig["direction"]
    signal_time = parse_utc3(sig["signal_time"])
    touch_time = parse_utc3(sig["touch_time"])
    fvg4h_c2 = parse_utc3(sig["fvg_4h_c2_time"])
    fvg1h_c0 = parse_utc3(sig["fvg_1h_c0_time"])
    fvg1h_c2 = parse_utc3(sig["fvg_1h_c2_time"])
    activation_time = parse_utc3(sig["activation_time"])
    fvg_4h_bot = float(sig["fvg_4h_bottom"])
    fvg_4h_top = float(sig["fvg_4h_top"])
    fvg_1h_bot = float(sig["fvg_1h_bottom"])
    fvg_1h_top = float(sig["fvg_1h_top"])
    entry = float(sig["entry"])
    sl = float(sig["sl"])
    c4_R = float(sig["c4_R"])
    c4_exit = sig["c4_exit"]

    # Найти exit_time/price
    exit_time, exit_price, exit_kind = find_c4_exit(
        sig, df_1m, df_1h, ema_3, upper, lower, bw2,
    )

    # Окно: от touch - 12h до exit + 6h (или signal + 5d если exit None)
    win_start = touch_time - pd.Timedelta(hours=12)
    win_end = (exit_time + pd.Timedelta(hours=6)) if exit_time is not None \
              else (signal_time + pd.Timedelta(days=5))

    df_w = df_1h[(df_1h.index >= win_start) & (df_1h.index <= win_end)]
    if len(df_w) < 5:
        return  # пропускаем
    ema_w = ema_3.loc[df_w.index]
    bw2_w = bw2.loc[df_w.index]
    bw2_sma_w = bw2_sma14.loc[df_w.index]
    upper_w = upper.loc[df_w.index]
    lower_w = lower.loc[df_w.index]

    fig = plt.figure(figsize=PAGE)
    _setup(fig)

    # Header
    arrow = "▲" if direction == "LONG" else "▼"
    arrow_color = GREEN if direction == "LONG" else RED
    fig.text(0.06, 0.93, f"Setup #{setup_num} of {total_setups}",
             color=TEXT, fontsize=18, fontweight="bold")
    fig.text(0.06, 0.89,
             f"{arrow} {direction} BTCUSDT · {signal_time.strftime('%Y-%m-%d %H:%M')} UTC",
             color=arrow_color, fontsize=13, fontweight="bold")
    fig.text(0.40, 0.93,
             f"C4 result: {c4_R:+.2f}R   ·   exit: {c4_exit}",
             color=GREEN if c4_R > 0 else RED, fontsize=12, fontweight="bold")
    fig.text(0.40, 0.89,
             f"Original 3.2 outcome (RR=1): {sig['outcome']}",
             color=MUTED, fontsize=10)

    # Top: candles + zones + entry/SL/exit
    ax_p = _ax(fig, [0.06, 0.46, 0.88, 0.40])
    draw_candles(ax_p, df_w)

    # Жёстко устанавливаем ylim, иначе overlay'и могут растянуть ось.
    y_min = float(min(df_w["low"].min(), sl, fvg_4h_bot, fvg_1h_bot))
    y_max = float(max(df_w["high"].max(), entry, fvg_4h_top, fvg_1h_top))
    y_pad = (y_max - y_min) * 0.05
    ax_p.set_ylim(y_min - y_pad, y_max + y_pad)
    ax_p.set_xlim(df_w.index[0], df_w.index[-1] + pd.Timedelta(hours=4))

    # FVG-4h zone (full window)
    fvg_color = GREEN if direction == "LONG" else RED
    ax_p.axhspan(fvg_4h_bot, fvg_4h_top, alpha=0.10, color=fvg_color, zorder=0)
    ax_p.text(df_w.index[0], (fvg_4h_bot + fvg_4h_top) / 2, " FVG-4h",
              color=fvg_color, fontsize=9, va="center", alpha=0.95, fontweight="bold")

    # Touch candles highlight через axvspan (auto-fit по Y)
    if touch_time is not None:
        tp1_time = touch_time + pd.Timedelta(hours=4)
        for tt, label in [(touch_time, "touch"), (tp1_time, "touch+1")]:
            ax_p.axvspan(tt, tt + pd.Timedelta(hours=4),
                         alpha=0.10, color=YELLOW, zorder=0)
            ax_p.text(tt + pd.Timedelta(hours=2), y_max + y_pad * 0.4, label,
                      color=YELLOW, fontsize=8, ha="center", alpha=0.85,
                      fontweight="bold")

    # FVG-1h zone (от c0 до signal+1h примерно)
    if fvg1h_c0 is not None and fvg1h_c2 is not None:
        ax_p.axhspan(fvg_1h_bot, fvg_1h_top, alpha=0.20, color=ACCENT, zorder=0)
        # Подпись
        ax_p.text(fvg1h_c0, (fvg_1h_bot + fvg_1h_top) / 2, " FVG-1h",
                  color=ACCENT, fontsize=8, va="center", alpha=1.0)

    # Entry / SL horizontal lines (подписи справа во внеoceaнном padding)
    label_x = df_w.index[-1] + pd.Timedelta(hours=1)
    ax_p.axhline(entry, color=YELLOW, linewidth=1.5, alpha=0.9, linestyle="-")
    ax_p.text(label_x, entry, f" Entry {entry:.1f}",
              color=YELLOW, fontsize=9, va="center", fontweight="bold")
    ax_p.axhline(sl, color=RED, linewidth=1.2, alpha=0.9, linestyle="--")
    ax_p.text(label_x, sl, f" SL {sl:.1f}",
              color=RED, fontsize=9, va="center", fontweight="bold")

    # Activation marker
    if activation_time is not None and activation_time >= df_w.index[0]:
        ax_p.scatter(activation_time, entry, marker="o",
                     color=YELLOW, s=80, zorder=5, edgecolors=BG, linewidths=1.5)
        ax_p.text(activation_time, entry + y_pad * 0.3, " ACT",
                  color=YELLOW, fontsize=8, va="bottom", fontweight="bold")

    # Exit marker — подпись СВЕРХУ или СНИЗУ от точки, не справа (чтоб не пересекать Entry/SL)
    if exit_time is not None and exit_price is not None:
        exit_color = GREEN if c4_R > 0 else RED
        marker = "*" if exit_kind != "sl" else "X"
        ax_p.scatter(exit_time, exit_price, marker=marker,
                     color=exit_color, s=250, zorder=6,
                     edgecolors=TEXT, linewidths=1.2)
        # Лейбл сверху (для LONG win) или снизу (для SHORT win), чтоб ушло в свободное место.
        is_above = (direction == "LONG" and c4_R > 0) or (direction == "SHORT" and c4_R < 0)
        dy = y_pad * 1.2 if is_above else -y_pad * 1.2
        va = "bottom" if is_above else "top"
        ax_p.text(exit_time, exit_price + dy,
                  f"{exit_kind.upper()}\n{c4_R:+.2f}R",
                  color=exit_color, fontsize=9, va=va, ha="center",
                  fontweight="bold",
                  bbox=dict(facecolor=BG, edgecolor=exit_color, boxstyle="round,pad=0.3",
                            linewidth=1.0))

    ax_p.set_ylabel("Price USDT", color=TEXT, fontsize=10)
    ax_p.set_title("Price chart · 1h candles", color=TEXT, fontsize=10, pad=8)

    # Bottom: indicators
    ax_i = _ax(fig, [0.06, 0.10, 0.88, 0.28])
    # bw2 histogram
    width = pd.Timedelta(hours=1).total_seconds() / 86400 * 0.85
    colors_bw = []
    for v, sm in zip(bw2_w, bw2_sma_w):
        if pd.isna(v) or pd.isna(sm):
            colors_bw.append(MUTED)
        elif v > 0:
            colors_bw.append(GREEN if v >= sm else MUTED)
        elif v < 0:
            colors_bw.append(RED if v <= sm else MUTED)
        else:
            colors_bw.append(MUTED)
    ax_i.bar(df_w.index, bw2_w, width=width, color=colors_bw,
             edgecolor="none", alpha=0.7, label="bw2 (MH)")
    ax_i.plot(df_w.index, bw2_sma_w, color=YELLOW, linewidth=1.0,
              label="bw2 SMA(14)", alpha=0.9)
    ax_i.axhline(0, color="#5a6373", linewidth=0.8)

    # Right axis для ASVK ema_3 + NWE
    ax_i2 = ax_i.twinx()
    ax_i2.set_facecolor("none")
    ax_i2.tick_params(colors=PURPLE)
    ax_i2.plot(df_w.index, ema_w, color=PURPLE, linewidth=1.3, label="ASVK ema_3")
    ax_i2.plot(df_w.index, upper_w, color=PURPLE, linewidth=0.7,
               linestyle=":", alpha=0.6)
    ax_i2.plot(df_w.index, lower_w, color=PURPLE, linewidth=0.7,
               linestyle=":", alpha=0.6)

    # Активация и exit на индикаторах
    if activation_time is not None:
        ax_i.axvline(activation_time, color=YELLOW, linewidth=0.8, alpha=0.6,
                     linestyle="--")
    if exit_time is not None:
        ax_i.axvline(exit_time, color=GREEN if c4_R > 0 else RED,
                     linewidth=1.2, alpha=0.8)

    ax_i.set_ylabel("bw2", color=TEXT)
    ax_i2.set_ylabel("ASVK ema_3 (purple)", color=PURPLE)
    ax_i.legend(loc="upper left", facecolor="#1a1f29",
                edgecolor="#3a4252", labelcolor=TEXT, fontsize=7)
    ax_i2.legend(loc="upper right", facecolor="#1a1f29",
                 edgecolor="#3a4252", labelcolor=PURPLE, fontsize=7)
    ax_i.set_title("Indicators · ASVK ema_3 (purple) + Money Hands bw2 (histogram)",
                   color=TEXT, fontsize=10, pad=8)

    # X-axis format
    ax_i.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=8))
    ax_i.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    plt.setp(ax_i.xaxis.get_majorticklabels(), rotation=0, ha="center", fontsize=8)
    ax_p.tick_params(axis="x", labelbottom=False)

    fig.text(0.06, 0.04, "C4 dual-exit · BTCUSDT 1h", color=MUTED, fontsize=8)
    fig.text(0.94, 0.04, "2026-05-07", color=MUTED, fontsize=8, ha="right")
    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def slide_cover(pdf):
    fig = plt.figure(figsize=PAGE)
    _setup(fig)
    fig.text(0.5, 0.65, "Strategy 3.2 + C4 Dual-Exit",
             color=TEXT, fontsize=36, fontweight="bold", ha="center")
    fig.text(0.5, 0.58, "Best setups walkthrough",
             color=ACCENT, fontsize=22, ha="center")
    fig.text(0.5, 0.46, "Реальные сделки на BTCUSDT 1h за 3 года",
             color=MUTED, fontsize=14, ha="center")
    fig.text(0.5, 0.38,
             "Топ-выигрышные C4-сделки · разбор entry/exit/триггеров на чарте",
             color=MUTED, fontsize=12, ha="center")
    fig.text(0.5, 0.18, "Andrew · 2026-05-07", color=MUTED, fontsize=11, ha="center")
    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def slide_legend(pdf):
    fig = plt.figure(figsize=PAGE)
    _setup(fig)
    fig.text(0.06, 0.93, "Как читать графики", color=TEXT, fontsize=22,
             fontweight="bold")
    fig.text(0.06, 0.88, "Краткая легенда elements", color=MUTED, fontsize=12)

    items = [
        (GREEN, "■ Зелёная зона на цене", "FVG-4h LONG (бычий гэп)"),
        (RED, "■ Красная зона на цене", "FVG-4h SHORT (медвежий гэп)"),
        (ACCENT, "■ Синяя зона", "FVG-1h — где образовалась маленькая дыра, mid = entry"),
        (YELLOW, "── Жёлтая горизонталь", "Entry-цена (середина FVG-1h)"),
        (RED, "-- Красная пунктирная", "Stop Loss (low/high c0_1h)"),
        (YELLOW, "● Жёлтый круг 'ACT'", "Activation — момент срабатывания лимит-ордера"),
        (GREEN, "★ Звезда", "Exit с прибылью (по C4 триггеру)"),
        (RED, "✕ Крест", "Exit по SL"),
        (PURPLE, "── Фиолетовая линия", "ASVK ema_3 (правая шкала)"),
        (PURPLE, "·· Фиолет точки", "ASVK NWE upper/lower (Гауссов канал)"),
        (GREEN, "▲ Зелёные столбики", "bw2 > 0 и >= SMA14 (бычий импульс растёт)"),
        (RED, "▼ Красные столбики", "bw2 < 0 и <= SMA14 (медвежий импульс растёт)"),
        (MUTED, "■ Серые столбики", "bw2 слабее SMA14 (импульс затухает)"),
        (YELLOW, "── Жёлтая линия снизу", "bw2 SMA(14)"),
    ]
    for i, (col, sym, desc) in enumerate(items):
        y = 0.83 - i * 0.052
        fig.text(0.10, y, sym, color=col, fontsize=12, fontweight="bold")
        fig.text(0.32, y, "—", color=MUTED, fontsize=10)
        fig.text(0.36, y, desc, color=TEXT, fontsize=10)

    fig.text(0.06, 0.06,
             "На каждом слайде: верх — цена с зонами и entry/SL/exit; низ — индикаторы.",
             color=MUTED, fontsize=10)
    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def slide_overview(pdf, top_setups):
    fig = plt.figure(figsize=PAGE)
    _setup(fig)
    fig.text(0.06, 0.93, "Что такое C4 dual-exit",
             color=TEXT, fontsize=22, fontweight="bold")
    fig.text(0.06, 0.88, "Краткое напоминание перед примерами",
             color=MUTED, fontsize=12)

    # Левый блок: вход
    ax_l = fig.add_axes([0.06, 0.46, 0.42, 0.36])
    ax_l.set_facecolor(PANEL)
    ax_l.axis("off")
    ax_l.set_xlim(0, 1)
    ax_l.set_ylim(0, 1)
    ax_l.add_patch(FancyBboxPatch((0.02, 0.05), 0.96, 0.9,
                                   boxstyle="round,pad=0.02",
                                   facecolor=PANEL, edgecolor=ACCENT, linewidth=1.2))
    ax_l.text(0.5, 0.88, "Вход (без изменений vs 3.2)", color=TEXT,
              fontsize=12, fontweight="bold", ha="center")
    lines_l = [
        "1. FVG-4h обнаружена",
        "2. Цена коснулась зоны",
        "3. 2 свечи rejection прошли",
        "4. FVG-1h в 8h-окне найдена",
        "→ entry = mid FVG-1h (limit)",
        "→ SL = low/high c0_1h",
    ]
    for i, line in enumerate(lines_l):
        ax_l.text(0.06, 0.74 - i * 0.10, line, color=TEXT, fontsize=10)

    # Правый блок: выход
    ax_r = fig.add_axes([0.52, 0.46, 0.42, 0.36])
    ax_r.set_facecolor(PANEL)
    ax_r.axis("off")
    ax_r.set_xlim(0, 1)
    ax_r.set_ylim(0, 1)
    ax_r.add_patch(FancyBboxPatch((0.02, 0.05), 0.96, 0.9,
                                   boxstyle="round,pad=0.02",
                                   facecolor=PANEL, edgecolor=GREEN, linewidth=1.5))
    ax_r.text(0.5, 0.88, "Выход (3 параллельных триггера)",
              color=TEXT, fontsize=12, fontweight="bold", ha="center")
    triggers = [
        ("1. SL hit", "стоп выбит на 1m → loss −1R", RED),
        ("2. NWE-cross", "ASVK ema_3 пробил противоположный край NWE → exit", PURPLE),
        ("3. bw2 zero", "MH bw2 пересёк 0 в противоположную сторону → exit", YELLOW),
    ]
    for i, (head, body, col) in enumerate(triggers):
        ax_r.text(0.06, 0.72 - i * 0.18, head, color=col, fontsize=11,
                  fontweight="bold")
        ax_r.text(0.06, 0.65 - i * 0.18, body, color=TEXT, fontsize=9)

    # Stats
    ax_s = fig.add_axes([0.06, 0.10, 0.88, 0.30])
    ax_s.set_facecolor(PANEL)
    ax_s.axis("off")
    ax_s.set_xlim(0, 1)
    ax_s.set_ylim(0, 1)
    ax_s.add_patch(FancyBboxPatch((0.02, 0.05), 0.96, 0.9,
                                   boxstyle="round,pad=0.02",
                                   facecolor=PANEL, edgecolor="#3a4252", linewidth=1.0))
    ax_s.text(0.5, 0.88, "Cтатистика на 3-летнем BTC и план презентации",
              color=TEXT, fontsize=12, fontweight="bold", ha="center")
    rows = [
        ("Total trades", "245", "WR 42.0%, +90.7R, R/tr +0.370"),
        ("LONG", "123", "WR 43.9%, +24.5R, R/tr +0.199"),
        ("SHORT", "122", "WR 40.0%, +66.2R, R/tr +0.542"),
        ("bw2-zero exits", "160", "65% всех exit'ов, средн. R +0.94"),
        ("NWE exits", "4", "редкие, средн. R +4.74 (жирные)"),
        ("SL exits", "79", "32% всех, − 1R"),
    ]
    for i, (k, v, note) in enumerate(rows):
        y = 0.72 - i * 0.10
        ax_s.text(0.05, y, k, color=ACCENT, fontsize=10, fontweight="bold")
        ax_s.text(0.20, y, v, color=GREEN, fontsize=10, fontweight="bold")
        ax_s.text(0.30, y, note, color=TEXT, fontsize=9)

    fig.text(0.06, 0.05,
             f"Далее — {len(top_setups)} реальных сетапов из топ по R/trade.",
             color=MUTED, fontsize=10)
    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def main():
    OUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    print(f"[INFO] загрузка {INPUT_CSV}")
    df = pd.read_csv(INPUT_CSV)
    print(f"  rows: {len(df)}")

    print(f"[INFO] загрузка {SYMBOL} 1m, 1h")
    df_1m = load_df(SYMBOL, "1m")
    df_1h = load_df(SYMBOL, "1h")

    print("[INFO] ASVK + MH series")
    ema_3 = adjusted_rsi(df_1h["close"])
    _, upper, lower = nwe_bands(ema_3, NWE_BAR, NWE_BANDWIDTH, NWE_MULTIPLIER)
    hlc3 = (df_1h["high"] + df_1h["low"] + df_1h["close"]) / 3
    bw1, bw2, _ = wavetrend_blueWaves(hlc3, WT_N1, WT_N2)
    bw2_sma14 = sma(bw2, BW2_SMA_LEN)

    # Отбор топ-сетапов
    closed = df[df["c4_outcome"].isin(["win", "loss"])].copy()
    # Топ-3 LONG-winners, топ-3 SHORT-winners + 1 NWE-exit special если есть
    longs = closed[(closed["direction"] == "LONG") & (closed["c4_R"] > 0)].nlargest(2, "c4_R")
    shorts = closed[(closed["direction"] == "SHORT") & (closed["c4_R"] > 0)].nlargest(2, "c4_R")
    nwe_winners = closed[(closed["c4_exit"] == "nwe") & (closed["c4_R"] > 0)].nlargest(1, "c4_R")
    # Хотя бы один пример SHORT-save (где orig outcome='loss', а C4='win')
    shorts_saved = closed[(closed["direction"] == "SHORT")
                           & (closed["c4_outcome"] == "win")
                           & (closed["outcome"] == "loss")].nlargest(1, "c4_R")
    setups = pd.concat([longs, shorts, nwe_winners, shorts_saved]).drop_duplicates(
        subset="signal_time", keep="first"
    ).reset_index(drop=True)
    print(f"[INFO] отобрано сетапов для PDF: {len(setups)}")
    for i, r in setups.iterrows():
        print(f"  #{i+1}: {r['direction']} {r['signal_time']} R={r['c4_R']:+.2f} exit={r['c4_exit']}")

    print(f"[INFO] building PDF: {OUT_PDF}")
    with PdfPages(OUT_PDF) as pdf:
        slide_cover(pdf)
        slide_overview(pdf, setups)
        slide_legend(pdf)
        for i, sig in setups.iterrows():
            print(f"  rendering setup #{i+1}/{len(setups)}: "
                  f"{sig['direction']} @ {sig['signal_time']}")
            draw_setup_slide(pdf, sig, df_1h, df_1m, ema_3, upper, lower, bw2,
                             bw2_sma14, i + 1, len(setups))
    print(f"[OK] saved: {OUT_PDF}  size: {OUT_PDF.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
