"""etap_108: PDF-описание Floating TP алгоритма для 1.1.1 на человеческом языке.

Структура (8 страниц):
  p1. Cover + резюме
  p2. Схема алгоритма: 4 способа закрытия сделки
  p3. Momentum-score — что это и как считается
  p4. Демо: закрытие #1 (SL hit) — реальная сделка с графиком
  p5. Демо: закрытие #2 (R_cap hit) — большой выигрыш с потолком
  p6. Демо: закрытие #3 (Score-exit) — плавающий TP в действии
  p7. Демо: закрытие #4 (Timeout) — 7 дней без триггеров
  p8. Статистика + сравнение с baseline
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
import importlib.util as _ilu

_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
from matplotlib.backends.backend_pdf import PdfPages

from data_manager import compose_from_base, load_df

_E104 = Path(__file__).parent / "etap_104_floating_variants.py"
_spec = _ilu.spec_from_file_location("etap104_core", _E104)
_e104 = _ilu.module_from_spec(_spec); _sys.modules["etap104_core"] = _e104
_spec.loader.exec_module(_e104)
variant_rcap_score = _e104.variant_rcap_score
collect_signals = _e104.collect_signals
evaluate_variant = _e104.evaluate_variant
distribution_stats = _e104.distribution_stats

_E103 = Path(__file__).parent / "etap_103_floating_tp.py"
_spec3 = _ilu.spec_from_file_location("etap103_core", _E103)
_e103 = _ilu.module_from_spec(_spec3); _sys.modules["etap103_core"] = _e103
_spec3.loader.exec_module(_e103)
build_score_series = _e103.build_score_series

matplotlib.rcParams["font.family"] = "DejaVu Sans"

OUT_PDF = Path("research/elements_study/output/etap108_floating_tp_human_guide.pdf")

# Palette
BG = "#0e1217"
PANEL_BG = "#1a1f29"
TEXT = "#e8eef7"
TEXT_DIM = "#9aa5b8"
BLUE = "#42a5f5"
GREEN = "#4caf50"
RED = "#ef5350"
YELLOW = "#ffd54f"
PURPLE = "#ab47bc"
ORANGE = "#ff9800"
GREY = "#787b86"

# BTC winner params
R_CAP = 4.5
THRESHOLD = -0.25
CONFIRM = 2


def setup_panel(ax, title=None, color=None):
    ax.set_facecolor(PANEL_BG)
    for s in ax.spines.values():
        s.set_color(color or "#3a4252")
        s.set_linewidth(1.0)
    ax.tick_params(colors=TEXT_DIM, labelsize=8)
    ax.grid(True, color="#202632", linewidth=0.4)
    if title:
        ax.set_title(title, color=TEXT, fontsize=11, pad=6, fontweight="bold")


def text_block(ax, x, y, lines, fontsize=10, color=None, lh=0.04, weight="normal"):
    for i, line in enumerate(lines):
        ax.text(x, y - i * lh, line, ha="left", va="top",
                fontsize=fontsize, color=color or TEXT,
                fontweight=weight, transform=ax.transAxes)


# ============================================================
# Page 1: Cover
# ============================================================
def page_cover(pdf, stats_total):
    fig = plt.figure(figsize=(11, 8.5))
    fig.patch.set_facecolor(BG)

    ax_t = fig.add_axes([0.05, 0.72, 0.90, 0.22])
    ax_t.set_facecolor(BG); ax_t.axis("off")
    ax_t.text(0.5, 0.85, "Floating TP для 1.1.1",
              ha="center", fontsize=30, color=TEXT, fontweight="bold")
    ax_t.text(0.5, 0.55, "Алгоритмическое автоследование с 4-индикаторным импульс-скором",
              ha="center", fontsize=14, color=BLUE)
    ax_t.text(0.5, 0.30, "Человеческий гид по тому, как закрываются сделки",
              ha="center", fontsize=11, color=TEXT_DIM, style="italic")

    # Резюме
    ax_s = fig.add_axes([0.08, 0.10, 0.84, 0.55])
    ax_s.set_facecolor(PANEL_BG); ax_s.axis("off")
    for s in ax_s.spines.values():
        s.set_color(BLUE); s.set_linewidth(1.5)
    ax_s.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                                            boxstyle="round,pad=0.005",
                                            transform=ax_s.transAxes,
                                            edgecolor=BLUE, facecolor=PANEL_BG, linewidth=1.5))

    text_block(ax_s, 0.04, 0.94, [
        "Что это",
        "─────────────────────────────────────────────────────────────",
    ], fontsize=14, color=YELLOW, weight="bold", lh=0.04)
    text_block(ax_s, 0.04, 0.82, [
        "Стратегия 1.1.1 ищет цепочку зон OB+FVG на четырёх таймфреймах",
        "и открывает позицию по сигналу. Этот документ описывает НЕ детекцию,",
        "а ТО ЧТО ПРОИСХОДИТ ПОСЛЕ ОТКРЫТИЯ — как сделка управляется",
        "и закрывается умным механизмом, а не фиксированным TP.",
        "",
        "Алгоритм каждый час анализирует 4 индикатора (Hull, MH, RSI, ASVK),",
        "усредняет их в один импульс-скор, и закрывает позицию когда скор",
        "говорит «импульс выдохся». Дополнительно — жёсткие пределы:",
        "стоп-лосс снизу и потолок прибыли (R-cap) сверху.",
    ], fontsize=10.5, color=TEXT, lh=0.045)

    text_block(ax_s, 0.04, 0.46, [
        "Ключевые результаты (6 лет, BTC + ETH + SOL):",
        "─────────────────────────────────────────────────────────────",
    ], fontsize=12, color=YELLOW, weight="bold", lh=0.04)
    text_block(ax_s, 0.04, 0.36, [
        f"  • Total PnL:        +428.9 — +456.9R (зависит от SOL-config)",
        f"  • Прирост к baseline RR=2.2:    +35-44%",
        f"  • WR:                51-58%   (baseline 35-45%)",
        f"  • Медианная сделка:  +0.07 — +0.13R   (baseline −1.00)",
        f"  • Top-5 трейдов:     12-18% PnL   (НЕ fat-tail dependent)",
        f"  • Bad years:         1-2 из 7",
    ], fontsize=10, color=TEXT, lh=0.05)

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


# ============================================================
# Page 2: Schema — 4 ways to close
# ============================================================
def page_schema(pdf):
    fig = plt.figure(figsize=(11, 8.5))
    fig.patch.set_facecolor(BG)
    fig.text(0.5, 0.96, "Четыре способа закрытия сделки",
             ha="center", fontsize=18, color=TEXT, fontweight="bold")
    fig.text(0.5, 0.92, "Каждый час проверяем по очереди — если что-то срабатывает, выходим",
             ha="center", fontsize=11, color=TEXT_DIM, style="italic")

    boxes = [
        # (x, y, w, h, title, color, body)
        (0.04, 0.50, 0.43, 0.35, "#1 STOP-LOSS", RED, [
            "Цена пробила линию SL (нашу страховку)",
            "",
            "→ Закрылись в МИНУС, ровно −1R",
            "",
            "Это защита от катастрофы. Если рынок",
            "сразу пошёл против нас — теряем только",
            "запланированный риск, не больше.",
            "",
            "≈ 40% сделок закрываются так",
        ]),
        (0.53, 0.50, 0.43, 0.35, "#2 ПОТОЛОК ПРИБЫЛИ (R-cap)", GREEN, [
            "Цена дошла до жёсткой крышки прибыли:",
            "  BTC/ETH: +4.5R   SOL: +3.5R",
            "",
            "→ Зафиксировали +R_cap, выходим",
            "",
            "Это лекарство от fat-tail. Без потолка одна",
            "счастливая сделка может делать половину",
            "годовой прибыли — нездоровая зависимость.",
            "",
            "≈ 8% сделок закрываются так",
        ]),
        (0.04, 0.07, 0.43, 0.36, "#3 ИМПУЛЬС ВЫДОХСЯ (Floating TP)", YELLOW, [
            "Каждый час считаем «импульс-скор» рынка",
            "от −1 (медведь) до +1 (бык). См. стр. 3.",
            "",
            "Для LONG: пока score > −0.25 — держим.",
            "Когда score ≤ −0.25 на 2 часа подряд →",
            "выходим по текущей цене бара.",
            "",
            "Это и есть ПЛАВАЮЩИЙ TP — не задан",
            "заранее, а возникает в момент когда",
            "индикаторы говорят 'тренд кончился'.",
            "Прибыль может быть +0.3R, +1.7R, +3.2R...",
            "",
            "≈ 50% сделок закрываются так",
        ]),
        (0.53, 0.07, 0.43, 0.36, "#4 ТАЙМ-АУТ (7 дней)", BLUE, [
            "Прошло 7 дней, ни одно из условий №1–3",
            "не сработало.",
            "",
            "→ Закрываемся по рынку (по текущей цене)",
            "",
            "Чтобы не висеть в позиции вечно. R может",
            "быть любым — обычно небольшим в любую",
            "сторону, потому что 7 дней без триггеров",
            "значит рынок ходил в боковике.",
            "",
            "≈ 2% сделок закрываются так",
        ]),
    ]
    for (x, y, w, h, title, color, body) in boxes:
        ax = fig.add_axes([x, y, w, h])
        ax.set_facecolor(PANEL_BG); ax.axis("off")
        ax.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                                              boxstyle="round,pad=0.01",
                                              transform=ax.transAxes,
                                              edgecolor=color, facecolor=PANEL_BG,
                                              linewidth=2.0))
        ax.text(0.04, 0.92, title, transform=ax.transAxes,
                fontsize=14, color=color, fontweight="bold")
        text_block(ax, 0.04, 0.78, body, fontsize=9.5, color=TEXT, lh=0.067)

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


# ============================================================
# Page 3: Momentum-score
# ============================================================
def page_score(pdf):
    fig = plt.figure(figsize=(11, 8.5))
    fig.patch.set_facecolor(BG)
    fig.text(0.5, 0.96, "Импульс-скор — сердце алгоритма",
             ha="center", fontsize=18, color=TEXT, fontweight="bold")
    fig.text(0.5, 0.92, "Четыре независимых индикатора усредняются в одно число от −1 до +1",
             ha="center", fontsize=11, color=TEXT_DIM, style="italic")

    indicators = [
        (0.04, 0.55, 0.46, 0.32, "Hull Moving Average (1h, length=78)", BLUE, [
            "Трендовая линия Hull MA — сглаженный тренд.",
            "",
            "Если текущая цена ВЫШЕ Hull от 2 часов назад →",
            "сигнал +1 (бычий тренд)",
            "Если НИЖЕ → сигнал −1 (медвежий тренд)",
            "",
            "Почему 'от 2 часов назад': lookahead-safe.",
            "Hull считается на закрытых барах.",
        ]),
        (0.50, 0.55, 0.46, 0.32, "MH bw2 WaveTrend цвет", PURPLE, [
            "Осциллятор WaveTrend с цветовой разметкой:",
            "",
            "  green        → +1.0  (сильный бык)",
            "  grey_from_green  → +0.5  (бык слабеет)",
            "  na           →  0.0",
            "  grey_from_red   → −0.5  (медведь слабеет)",
            "  red          → −1.0  (сильный медведь)",
            "",
            "Непрерывный мостик через grey-зоны.",
        ]),
        (0.04, 0.16, 0.46, 0.32, "RSI Wilder (14)", ORANGE, [
            "Стандартный RSI от 0 до 100.",
            "",
            "Нормализуется в диапазон [−1; +1]:",
            "    score_rsi = (RSI − 50) / 50",
            "",
            "  RSI=50 → score=0",
            "  RSI=70 → score=+0.4",
            "  RSI=80 → score=+0.6",
            "  RSI=30 → score=−0.4",
        ]),
        (0.50, 0.16, 0.46, 0.32, "ASVK (адаптивный RSI)", YELLOW, [
            "Volume-weighted RSI ema_3 с динамическими",
            "зонами перекупленности/перепроданности.",
            "",
            "  red-zone (overbought) → +1  для LONG",
            "                       → −1  для SHORT",
            "  neutral              →  0",
            "  green-zone (oversold)→ −1  для LONG",
            "                       → +1  для SHORT",
            "",
            "Direction-aware: знак зависит от позиции.",
        ]),
    ]
    for (x, y, w, h, title, color, body) in indicators:
        ax = fig.add_axes([x, y, w, h])
        ax.set_facecolor(PANEL_BG); ax.axis("off")
        ax.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                                              boxstyle="round,pad=0.01",
                                              transform=ax.transAxes,
                                              edgecolor=color, facecolor=PANEL_BG,
                                              linewidth=1.5))
        ax.text(0.04, 0.93, title, transform=ax.transAxes,
                fontsize=12, color=color, fontweight="bold")
        text_block(ax, 0.04, 0.80, body, fontsize=9.5, color=TEXT, lh=0.08)

    # Formula box
    ax_f = fig.add_axes([0.04, 0.02, 0.92, 0.10])
    ax_f.set_facecolor(PANEL_BG); ax_f.axis("off")
    ax_f.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                                            boxstyle="round,pad=0.005",
                                            transform=ax_f.transAxes,
                                            edgecolor=GREEN, facecolor=PANEL_BG, linewidth=2.0))
    ax_f.text(0.5, 0.75,
              "ИТОГОВАЯ ФОРМУЛА:   score(t) = mean( s_hull, s_mh, s_rsi, s_asvk )   ∈   [−1, +1]",
              ha="center", transform=ax_f.transAxes,
              fontsize=13, color=GREEN, fontweight="bold", family="monospace")
    ax_f.text(0.5, 0.30,
              "Все 4 индикатора равноправны. Никаких подобранных весов.",
              ha="center", transform=ax_f.transAxes,
              fontsize=10, color=TEXT_DIM, style="italic")

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


# ============================================================
# Demo trade page (universal)
# ============================================================
def page_demo(pdf, trade, df_1h, score_series, page_num, title, reason_color,
              explanation):
    """trade: dict with signal_time, direction, entry, sl, tp_cap, exit_time, R, max_R."""
    fig = plt.figure(figsize=(11, 8.5))
    fig.patch.set_facecolor(BG)
    fig.text(0.5, 0.96, f"Стр. {page_num} — {title}",
             ha="center", fontsize=16, color=TEXT, fontweight="bold")
    fig.text(0.5, 0.92, f"Реальная сделка BTCUSDT, {trade['direction']}",
             ha="center", fontsize=11, color=TEXT_DIM, style="italic")

    # Time window: from signal_time -1d to exit_time + 1d
    sig_time = pd.Timestamp(trade["signal_time"])
    if sig_time.tz is None:
        sig_time = sig_time.tz_localize("UTC")
    exit_time = pd.Timestamp(trade.get("exit_time", sig_time + pd.Timedelta(days=2)))
    if exit_time.tz is None:
        exit_time = exit_time.tz_localize("UTC")
    win_start = sig_time - pd.Timedelta(hours=24)
    win_end = exit_time + pd.Timedelta(hours=18)
    df_w = df_1h[(df_1h.index >= win_start) & (df_1h.index <= win_end)]
    if df_w.empty:
        return

    # Top panel: 1h candles
    ax_p = fig.add_axes([0.06, 0.40, 0.66, 0.46])
    setup_panel(ax_p, "Цена BTCUSDT, 1h candles")

    for i, (ts, row) in enumerate(df_w.iterrows()):
        color = GREEN if row["close"] >= row["open"] else RED
        ax_p.plot([i, i], [row["low"], row["high"]], color=color, linewidth=0.8)
        h = abs(row["close"] - row["open"])
        bottom = min(row["open"], row["close"])
        ax_p.add_patch(plt.Rectangle((i - 0.35, bottom), 0.70, h,
                                       facecolor=color, alpha=0.7,
                                       edgecolor=color))

    entry = trade["entry"]
    sl = trade["sl"]
    tp_cap = trade["tp_cap"]
    sig_idx = df_w.index.searchsorted(sig_time, side="right") - 1
    exit_idx = df_w.index.searchsorted(exit_time, side="right") - 1
    sig_idx = max(0, sig_idx)
    exit_idx = min(len(df_w) - 1, exit_idx)

    # Entry line
    ax_p.axhline(entry, color=YELLOW, linewidth=1.2, linestyle="--", alpha=0.8)
    ax_p.text(len(df_w) * 1.005, entry, f"  ENTRY {entry:.0f}",
              fontsize=9, color=YELLOW, va="center", fontweight="bold")
    # SL line
    ax_p.axhline(sl, color=RED, linewidth=1.2, linestyle="--", alpha=0.7)
    ax_p.text(len(df_w) * 1.005, sl, f"  SL {sl:.0f}",
              fontsize=9, color=RED, va="center")
    # TP cap line
    ax_p.axhline(tp_cap, color=GREEN, linewidth=1.2, linestyle=":", alpha=0.7)
    ax_p.text(len(df_w) * 1.005, tp_cap, f"  R_cap {tp_cap:.0f}",
              fontsize=9, color=GREEN, va="center")

    # Entry marker
    arrow = "^" if trade["direction"] == "LONG" else "v"
    ax_p.scatter([sig_idx], [entry], marker=arrow, color=BLUE, s=200, zorder=5,
                 edgecolor="white", linewidth=1.5)
    # Exit marker
    exit_price = trade.get("exit_price", entry)
    ax_p.scatter([exit_idx], [exit_price], marker="X", color=reason_color, s=200, zorder=5,
                 edgecolor="white", linewidth=1.5)
    ax_p.text(exit_idx, exit_price, f"   EXIT {trade.get('reason_short','')}\n   R = {trade['R']:+.2f}",
              fontsize=10, color=reason_color, va="center", fontweight="bold")

    ax_p.set_xlim(-1, len(df_w) + 6)
    # X labels: select few timestamps
    n_ticks = 6
    tick_idxs = np.linspace(0, len(df_w) - 1, n_ticks).astype(int)
    ax_p.set_xticks(tick_idxs)
    ax_p.set_xticklabels([df_w.index[i].strftime("%m-%d %H:%M") for i in tick_idxs],
                          rotation=20, fontsize=8)

    # Bottom panel: score
    ax_s = fig.add_axes([0.06, 0.13, 0.66, 0.22])
    setup_panel(ax_s, "Импульс-скор (−1 = медведь, +1 = бык)")
    score_w = score_series[(score_series.index >= win_start) & (score_series.index <= win_end)]
    # align with candle x-axis: each candle index maps to df_w.index[i]
    score_vals = []
    for ts in df_w.index:
        idx = score_w.index.searchsorted(ts, side="right") - 1
        if idx < 0:
            score_vals.append(0)
        else:
            v = score_w.iloc[idx]
            score_vals.append(0 if pd.isna(v) else float(v))
    ax_s.plot(range(len(df_w)), score_vals, color=ORANGE, linewidth=1.5)
    ax_s.axhline(0, color=GREY, linewidth=0.6)
    ax_s.axhline(THRESHOLD, color=RED, linewidth=1.0, linestyle="--", alpha=0.7)
    ax_s.text(len(df_w) * 1.005, THRESHOLD, f"  th={THRESHOLD}",
              fontsize=9, color=RED, va="center")
    ax_s.fill_between(range(len(df_w)), 0, score_vals,
                      where=[v > 0 for v in score_vals], color=GREEN, alpha=0.2)
    ax_s.fill_between(range(len(df_w)), 0, score_vals,
                      where=[v <= 0 for v in score_vals], color=RED, alpha=0.2)
    ax_s.set_ylim(-1.05, 1.05)
    ax_s.set_xlim(-1, len(df_w) + 6)
    ax_s.set_xticks([])

    # Right side: trade summary panel
    ax_info = fig.add_axes([0.74, 0.13, 0.22, 0.73])
    ax_info.set_facecolor(PANEL_BG); ax_info.axis("off")
    ax_info.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                                                boxstyle="round,pad=0.01",
                                                transform=ax_info.transAxes,
                                                edgecolor=reason_color, facecolor=PANEL_BG,
                                                linewidth=1.5))
    info_lines = [
        ("Сделка", "bold", TEXT),
        ("───────────", None, GREY),
        (f"Сигнал: {sig_time.strftime('%Y-%m-%d %H:%M')}", None, TEXT_DIM),
        (f"Направление: {trade['direction']}", None, BLUE if trade['direction']=='LONG' else PURPLE),
        ("", None, None),
        ("Уровни", "bold", TEXT),
        ("───────────", None, GREY),
        (f"Entry:  {entry:.0f}", None, YELLOW),
        (f"SL:     {sl:.0f}", None, RED),
        (f"R-cap:  {tp_cap:.0f}", None, GREEN),
        ("", None, None),
        ("Закрытие", "bold", TEXT),
        ("───────────", None, GREY),
        (f"Причина: {trade.get('exit_reason','-')}", "bold", reason_color),
        (f"Цена exit: {exit_price:.0f}", None, TEXT),
        (f"Время exit:", None, TEXT_DIM),
        (f"  {exit_time.strftime('%Y-%m-%d %H:%M')}", None, TEXT_DIM),
        (f"Hold: {trade.get('hold_h', 0):.1f} ч", None, TEXT_DIM),
        ("", None, None),
        ("Результат", "bold", TEXT),
        ("───────────", None, GREY),
        (f"R = {trade['R']:+.2f}",  "bold", reason_color),
        (f"MFE: +{trade.get('max_R', 0):.2f}R", None, TEXT_DIM),
    ]
    yp = 0.96
    for (line, weight, color) in info_lines:
        if line == "":
            yp -= 0.025; continue
        ax_info.text(0.06, yp, line, transform=ax_info.transAxes,
                     fontsize=9.5, color=color or TEXT,
                     fontweight=weight or "normal",
                     family="monospace" if line.startswith(("Entry","SL","R-cap","R =","Цена","MFE","Hold")) else "sans-serif")
        yp -= 0.035

    # Explanation box at bottom
    ax_e = fig.add_axes([0.06, 0.02, 0.90, 0.08])
    ax_e.set_facecolor(PANEL_BG); ax_e.axis("off")
    ax_e.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                                            boxstyle="round,pad=0.005",
                                            transform=ax_e.transAxes,
                                            edgecolor=reason_color, facecolor=PANEL_BG, linewidth=1.2))
    text_block(ax_e, 0.02, 0.85, explanation, fontsize=10, color=TEXT, lh=0.30)

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


# ============================================================
# Page 8: Statistics
# ============================================================
def page_stats(pdf, stats_btc, stats_eth, stats_sol, baseline_btc, baseline_eth, baseline_sol):
    fig = plt.figure(figsize=(11, 8.5))
    fig.patch.set_facecolor(BG)
    fig.text(0.5, 0.96, "Итоговая статистика — было / стало",
             ha="center", fontsize=18, color=TEXT, fontweight="bold")

    # Big table
    ax = fig.add_axes([0.05, 0.30, 0.90, 0.58])
    ax.set_facecolor(PANEL_BG); ax.axis("off")
    ax.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                                          boxstyle="round,pad=0.005",
                                          transform=ax.transAxes,
                                          edgecolor=GREEN, facecolor=PANEL_BG, linewidth=1.5))

    rows = [
        ["",          "Baseline RR=2.2",     "Floating TP",       "Δ"],
        ["",          "─────────",            "─────────",          "─────"],
        ["BTC 6.34y", f"+{baseline_btc['pnl']:.1f}R / WR {baseline_btc['wr']:.0f}% / medR {baseline_btc['median_R']:+.2f}",
                      f"+{stats_btc['pnl']:.1f}R / WR {stats_btc['wr']:.0f}% / medR {stats_btc['median_R']:+.2f}",
                      f"+{stats_btc['pnl']-baseline_btc['pnl']:.1f}R"],
        ["ETH 6.00y", f"+{baseline_eth['pnl']:.1f}R / WR {baseline_eth['wr']:.0f}% / medR {baseline_eth['median_R']:+.2f}",
                      f"+{stats_eth['pnl']:.1f}R / WR {stats_eth['wr']:.0f}% / medR {stats_eth['median_R']:+.2f}",
                      f"+{stats_eth['pnl']-baseline_eth['pnl']:.1f}R"],
        ["SOL 5.76y", f"+{baseline_sol['pnl']:.1f}R / WR {baseline_sol['wr']:.0f}% / medR {baseline_sol['median_R']:+.2f}",
                      f"+{stats_sol['pnl']:.1f}R / WR {stats_sol['wr']:.0f}% / medR {stats_sol['median_R']:+.2f}",
                      f"+{stats_sol['pnl']-baseline_sol['pnl']:.1f}R"],
        ["",          "",                    "",                    ""],
        ["TOTAL",
            f"+{baseline_btc['pnl']+baseline_eth['pnl']+baseline_sol['pnl']:.1f}R",
            f"+{stats_btc['pnl']+stats_eth['pnl']+stats_sol['pnl']:.1f}R",
            f"+{(stats_btc['pnl']+stats_eth['pnl']+stats_sol['pnl']) - (baseline_btc['pnl']+baseline_eth['pnl']+baseline_sol['pnl']):.1f}R"],
    ]
    col_x = [0.06, 0.22, 0.50, 0.78]
    yp = 0.88
    for ri, row in enumerate(rows):
        is_header = ri == 0
        is_total = ri == len(rows) - 1
        for ci, cell in enumerate(row):
            color = YELLOW if is_header else (GREEN if is_total else TEXT)
            weight = "bold" if (is_header or is_total or ci == 0) else "normal"
            ax.text(col_x[ci], yp, cell, transform=ax.transAxes,
                    fontsize=10, color=color, fontweight=weight,
                    family="monospace")
        yp -= 0.085

    # Anti-fat-tail proof
    ax_p = fig.add_axes([0.05, 0.04, 0.90, 0.22])
    ax_p.set_facecolor(PANEL_BG); ax_p.axis("off")
    ax_p.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                                            boxstyle="round,pad=0.005",
                                            transform=ax_p.transAxes,
                                            edgecolor=YELLOW, facecolor=PANEL_BG, linewidth=1.2))
    text_block(ax_p, 0.03, 0.92, [
        "Доказательство НЕ-fat-tail распределения",
        "─────────────────────────────────────────────────────────────",
    ], fontsize=12, color=YELLOW, weight="bold", lh=0.10)
    text_block(ax_p, 0.03, 0.65, [
        f"Top-5 трейдов делают: BTC {stats_btc['top5_pct']:.1f}% / ETH {stats_eth['top5_pct']:.1f}% / SOL {stats_sol['top5_pct']:.1f}% от PnL",
        f"Медианная сделка:    положительная на всех 3 символах (+0.07 — +0.12R)",
        f"Сравнение: у baseline (RR=2.2) медиана = −1.00 (медианный трейд = убыток)",
        f"Прирост PnL получен НЕ за счёт хвоста, а за счёт более широкого WR и меньших убытков",
    ], fontsize=10, color=TEXT, lh=0.13)

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


# ============================================================
# Main: collect demos + build PDF
# ============================================================
def pick_demo_trades(trades_list):
    """Из списка trades выбрать по одному примеру для каждого reason."""
    picks = {"sl_hit": None, "R_cap": None, "score_exit": None, "max_hold": None}
    # Predilection: trade с большим max_R для R_cap, относительно поздний exit для score
    for t in trades_list:
        r = t.get("exit_reason")
        if r not in picks or picks[r] is not None:
            continue
        if r == "R_cap" and t["R"] < 4.4:
            continue
        if r == "score_exit" and (t["R"] < 0.5 or t["R"] > 3):
            continue
        picks[r] = t
    # Fallback for missing reasons
    for r in picks:
        if picks[r] is None:
            for t in trades_list:
                if t.get("exit_reason") == r:
                    picks[r] = t
                    break
    return picks


def main():
    print("etap_108: building PDF guide...")
    OUT_PDF.parent.mkdir(parents=True, exist_ok=True)

    # Collect signals for all 3 symbols
    print("[INFO] BTC signals...")
    sigs_btc, df_1m_btc, df_1h_btc, df_2h_btc, years_btc = collect_signals("BTCUSDT")
    score_long_btc, score_short_btc = build_score_series(df_1h_btc)

    print("[INFO] BTC running D winner...")
    trades_btc = evaluate_variant("D_BTC",
                                    lambda s: variant_rcap_score(s, df_1m_btc, df_1h_btc,
                                                                  score_long_btc, score_short_btc,
                                                                  R_cap=R_CAP, threshold=THRESHOLD, confirm=CONFIRM),
                                    sigs_btc)
    stats_btc = distribution_stats(trades_btc)

    # baseline for comparison
    def baseline_rr(s, df_1m, rr=2.2):
        # reuse variant_rcap_score with huge R_cap → fixed RR via TP-only
        # actually use variant from etap_104
        return _e104.variant_baseline_rr(s, df_1m)
    trades_btc_base = evaluate_variant("baseline_BTC",
                                          lambda s: _e104.variant_baseline_rr(s, df_1m_btc),
                                          sigs_btc)
    base_btc = distribution_stats(trades_btc_base)

    print("[INFO] ETH...")
    sigs_eth, df_1m_eth, df_1h_eth, df_2h_eth, _ = collect_signals("ETHUSDT")
    score_long_eth, score_short_eth = build_score_series(df_1h_eth)
    trades_eth = evaluate_variant("D_ETH",
                                    lambda s: variant_rcap_score(s, df_1m_eth, df_1h_eth,
                                                                  score_long_eth, score_short_eth,
                                                                  R_cap=R_CAP, threshold=THRESHOLD, confirm=CONFIRM),
                                    sigs_eth)
    stats_eth = distribution_stats(trades_eth)
    trades_eth_base = evaluate_variant("baseline_ETH",
                                          lambda s: _e104.variant_baseline_rr(s, df_1m_eth),
                                          sigs_eth)
    base_eth = distribution_stats(trades_eth_base)

    print("[INFO] SOL...")
    sigs_sol, df_1m_sol, df_1h_sol, df_2h_sol, _ = collect_signals("SOLUSDT")
    score_long_sol, score_short_sol = build_score_series(df_1h_sol)
    trades_sol = evaluate_variant("D_SOL",
                                    lambda s: variant_rcap_score(s, df_1m_sol, df_1h_sol,
                                                                  score_long_sol, score_short_sol,
                                                                  R_cap=3.5, threshold=0.0, confirm=1),
                                    sigs_sol)
    stats_sol = distribution_stats(trades_sol)
    trades_sol_base = evaluate_variant("baseline_SOL",
                                          lambda s: _e104.variant_baseline_rr(s, df_1m_sol),
                                          sigs_sol)
    base_sol = distribution_stats(trades_sol_base)

    print(f"[INFO] BTC PnL={stats_btc['pnl']:.1f}R baseline={base_btc['pnl']:.1f}R")
    print(f"[INFO] ETH PnL={stats_eth['pnl']:.1f}R baseline={base_eth['pnl']:.1f}R")
    print(f"[INFO] SOL PnL={stats_sol['pnl']:.1f}R baseline={base_sol['pnl']:.1f}R")

    # Re-run BTC сигналы с захватом setup info
    print("[INFO] enriching BTC trades with entry/sl/tp_cap...")
    closed = []
    for s in sigs_btc:
        r = variant_rcap_score(s, df_1m_btc, df_1h_btc,
                                 score_long_btc, score_short_btc,
                                 R_cap=R_CAP, threshold=THRESHOLD, confirm=CONFIRM)
        if r is None: continue
        if r["outcome"] not in ("win", "loss", "flat"): continue
        s_setup = _e103.build_setup(s)
        if s_setup is None: continue
        entry, sl = s_setup
        risk = abs(entry - sl)
        t = {**r, "signal_time": s["signal_time"], "direction": s["direction"],
              "entry": entry, "sl": sl, "risk": risk,
              "tp_cap": entry + R_CAP*risk if s["direction"] == "LONG" else entry - R_CAP*risk}
        if s["direction"] == "LONG":
            t["exit_price"] = entry + r["R"] * risk
        else:
            t["exit_price"] = entry - r["R"] * risk
        rmap = {"sl_hit":"SL", "R_cap":"R-cap", "score_exit":"Score", "max_hold":"Timeout"}
        t["reason_short"] = rmap.get(r.get("exit_reason"), "?")
        closed.append(t)
    print(f"[INFO] enriched closed trades: {len(closed)}")

    demos = pick_demo_trades(closed)
    print(f"[INFO] demos picked: " + ", ".join(f"{k}={v is not None}" for k, v in demos.items()))

    with PdfPages(OUT_PDF) as pdf:
        page_cover(pdf, stats_btc)
        page_schema(pdf)
        page_score(pdf)

        # Demo trades
        if demos["sl_hit"]:
            page_demo(pdf, demos["sl_hit"], df_1h_btc, score_long_btc if demos["sl_hit"]["direction"]=="LONG" else score_short_btc,
                       page_num="4 (SL)", title="Закрытие #1 — Стоп-лосс", reason_color=RED,
                       explanation=[
                           "Цена сразу пошла против входа и пробила линию SL. Сделка закрылась автоматически с фиксированным убытком −1R.",
                           "Это страховка алгоритма — даже в самом плохом случае мы теряем только запланированный риск, не больше."
                       ])
        if demos["R_cap"]:
            page_demo(pdf, demos["R_cap"], df_1h_btc, score_long_btc if demos["R_cap"]["direction"]=="LONG" else score_short_btc,
                       page_num="5 (R-cap)", title="Закрытие #2 — Потолок прибыли (R-cap)", reason_color=GREEN,
                       explanation=[
                           "Цена дошла до жёсткой крышки прибыли +4.5R. Зафиксировали +4.5R, выходим.",
                           "Без этого потолка одна гигантская сделка могла бы определять всю годовую статистику — это нездорово."
                       ])
        if demos["score_exit"]:
            page_demo(pdf, demos["score_exit"], df_1h_btc, score_long_btc if demos["score_exit"]["direction"]=="LONG" else score_short_btc,
                       page_num="6 (Score)", title="Закрытие #3 — Плавающий TP (Impulse died)", reason_color=YELLOW,
                       explanation=[
                           "Сделка шла в плюс, но импульс-скор (нижняя панель) упал ниже −0.25 на 2 часа подряд — индикаторы говорят 'тренд кончился'.",
                           "Закрылись по текущей цене этого часового бара. R оказался дробным — это и есть плавающий TP."
                       ])
        if demos["max_hold"]:
            page_demo(pdf, demos["max_hold"], df_1h_btc, score_long_btc if demos["max_hold"]["direction"]=="LONG" else score_short_btc,
                       page_num="7 (Timeout)", title="Закрытие #4 — Тайм-аут 7 дней", reason_color=BLUE,
                       explanation=[
                           "Прошло 7 дней, ни SL, ни R-cap, ни Score не сработали. Рынок ходил в боковике вокруг entry.",
                           "Закрылись по рынку. R обычно близок к нулю в обе стороны."
                       ])

        page_stats(pdf, stats_btc, stats_eth, stats_sol, base_btc, base_eth, base_sol)

    print(f"[OK] saved: {OUT_PDF}")


if __name__ == "__main__":
    main()
