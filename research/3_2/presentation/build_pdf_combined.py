"""PDF-презентация по комбинированным гипотезам ASVK + Money Hands.
Для каждой гипотезы — пояснение (что делает, зачем, как считается) + результаты.
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

OUT_PDF = Path("research/3_2/presentation/3_2_combined_findings.pdf")
ASVK_IMG = Path("research/asvk_rsi/asvk_rsi_BTCUSDT_1h.png")
MH_IMG = Path("research/money_hands/money_hands_BTCUSDT_1h.png")

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


def _setup(fig):
    fig.patch.set_facecolor(BG)


def _title(fig, t, sub=None):
    fig.text(0.06, 0.93, t, color=TEXT, fontsize=22, fontweight="bold")
    if sub:
        fig.text(0.06, 0.88, sub, color=MUTED, fontsize=12)
    fig.text(0.06, 0.04, "ASVK RSI x Money Hands · 10 combined hypotheses",
             color=MUTED, fontsize=8)
    fig.text(0.94, 0.04, "2026-05-06", color=MUTED, fontsize=8, ha="right")


def _ax(fig, rect):
    ax = fig.add_axes(rect)
    ax.set_facecolor(PANEL)
    for s in ax.spines.values():
        s.set_color("#3a4252")
    ax.tick_params(colors=TEXT)
    return ax


def _hypothesis_slide(pdf, hid, title, mechanic, why, formula,
                      result_rows, verdict, verdict_color):
    """Универсальный слайд гипотезы:
    - mechanic: краткий механизм (1-2 строки)
    - why: зачем (1-2 строки)
    - formula: точная формула/условие
    - result_rows: list of (label, n, wr, r_per_trade, color)
    - verdict: одна строка резюме (★★★★ работает / ✗ опровергнута / etc)
    """
    fig = plt.figure(figsize=PAGE)
    _setup(fig)
    _title(fig, f"{hid} — {title}")

    # Левая колонка: пояснения
    ax_l = fig.add_axes([0.04, 0.10, 0.50, 0.78])
    ax_l.set_facecolor(BG)
    ax_l.axis("off")
    ax_l.set_xlim(0, 1)
    ax_l.set_ylim(0, 1)

    sections = [
        ("МЕХАНИКА", mechanic, ACCENT),
        ("ЗАЧЕМ", why, YELLOW),
        ("УСЛОВИЕ", formula, GREEN),
    ]
    y_cur = 0.95
    for header, body, color in sections:
        ax_l.text(0.0, y_cur, header, color=color, fontsize=11, fontweight="bold")
        y_cur -= 0.04
        for line in body.split("\n"):
            ax_l.text(0.02, y_cur, line, color=TEXT, fontsize=10)
            y_cur -= 0.038
        y_cur -= 0.025

    # Правая колонка: результаты
    ax_r = fig.add_axes([0.56, 0.10, 0.40, 0.78])
    ax_r.set_facecolor(PANEL)
    ax_r.axis("off")
    ax_r.set_xlim(0, 1)
    ax_r.set_ylim(0, 1)
    ax_r.add_patch(FancyBboxPatch((0.02, 0.02), 0.96, 0.96,
                                   boxstyle="round,pad=0.02",
                                   facecolor=PANEL, edgecolor="#3a4252",
                                   linewidth=1.0))
    ax_r.text(0.5, 0.92, "РЕЗУЛЬТАТЫ", color=TEXT, fontsize=12,
              fontweight="bold", ha="center")
    ax_r.text(0.5, 0.85, "(на 243 closed сделках)", color=MUTED, fontsize=9, ha="center")

    # Header
    ax_r.text(0.05, 0.77, "Сегмент", color=ACCENT, fontsize=9, fontweight="bold")
    ax_r.text(0.55, 0.77, "n", color=ACCENT, fontsize=9, fontweight="bold")
    ax_r.text(0.65, 0.77, "WR", color=ACCENT, fontsize=9, fontweight="bold")
    ax_r.text(0.85, 0.77, "R/tr", color=ACCENT, fontsize=9, fontweight="bold")

    for i, (label, n, wr, rt, color) in enumerate(result_rows):
        y = 0.71 - i * 0.06
        ax_r.text(0.05, y, label, color=TEXT, fontsize=9)
        ax_r.text(0.55, y, str(n), color=TEXT, fontsize=9)
        ax_r.text(0.65, y, wr, color=TEXT, fontsize=9)
        ax_r.text(0.85, y, rt, color=color, fontsize=10, fontweight="bold")

    # Verdict
    ax_r.add_patch(FancyBboxPatch((0.05, 0.06), 0.90, 0.16,
                                   boxstyle="round,pad=0.02",
                                   facecolor=BG, edgecolor=verdict_color,
                                   linewidth=1.5))
    ax_r.text(0.5, 0.18, "ВЕРДИКТ", color=verdict_color, fontsize=10,
              fontweight="bold", ha="center")
    ax_r.text(0.5, 0.10, verdict, color=TEXT, fontsize=10, ha="center")

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


# -------- SLIDES --------

def slide_cover(pdf):
    fig = plt.figure(figsize=PAGE)
    _setup(fig)
    fig.text(0.5, 0.66, "ASVK RSI × Money Hands",
             color=TEXT, fontsize=40, fontweight="bold", ha="center")
    fig.text(0.5, 0.59, "Combined Hypotheses · Strategy 3.2",
             color=ACCENT, fontsize=22, ha="center")
    fig.text(0.5, 0.48, "10 ортогональных комбинаций · 245 сетапов · BTCUSDT 3 года",
             color=MUTED, fontsize=14, ha="center")

    # Strip showing hypothesis verdicts
    ax = fig.add_axes([0.15, 0.30, 0.7, 0.04])
    ax.axis("off")
    fig.text(0.5, 0.36, "10 проверок:", color=MUTED, fontsize=10, ha="center")
    fig.text(0.18, 0.30, "★★★★★ C4", color=GREEN, fontsize=11, fontweight="bold")
    fig.text(0.32, 0.30, "★★★ C2", color=GREEN, fontsize=11)
    fig.text(0.42, 0.30, "★★★ C8", color=GREEN, fontsize=11)
    fig.text(0.52, 0.30, "★★ C3", color=YELLOW, fontsize=11)
    fig.text(0.60, 0.30, "★ C10", color=YELLOW, fontsize=11)
    fig.text(0.70, 0.30, "≈ C5", color=MUTED, fontsize=11)
    fig.text(0.78, 0.30, "✗ C1 C6 C7 C9", color=RED, fontsize=11)

    fig.text(0.5, 0.18, "Andrew · 2026-05-06", color=MUTED, fontsize=11, ha="center")
    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def slide_methodology(pdf):
    fig = plt.figure(figsize=PAGE)
    _setup(fig)
    _title(fig, "Зачем комбинировать ASVK и Money Hands?",
           "Идея: индикаторы меряют РАЗНЫЕ вещи — confluence их сигналов сильнее")

    ax = fig.add_axes([0.04, 0.16, 0.92, 0.72])
    ax.set_facecolor(BG)
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    # Comparison table
    ax.text(0.20, 0.92, "ASVK Custom RSI", color=ACCENT, fontsize=14,
            fontweight="bold", ha="center")
    ax.text(0.70, 0.92, "Money Hands", color=PURPLE, fontsize=14,
            fontweight="bold", ha="center")

    rows = [
        ("Что меряет", "Accelerator на raw RSI", "WaveTrend (двойное сглаживание)"),
        ("Уровни OB/OS", "Адаптивные (зависят от режима)", "Фиксированные ±60/±75"),
        ("Дополнительный канал", "Гауссов (NWE) — стат. границы", "Цветовая state machine (4 фазы)"),
        ("Дивергенции", "range 4-100 баров", "range 5-60 баров"),
        ("Структурный взгляд", "EMA(50) локальных экстремумов", "Money Flow по Heikin Ashi"),
        ("Multi-TF", "z_above (rolling count)", "Двойной Stoch (40/81)"),
    ]
    for i, (k, a, b) in enumerate(rows):
        y = 0.83 - i * 0.10
        ax.text(0.02, y, k, color=YELLOW, fontsize=10, fontweight="bold")
        ax.text(0.20, y, a, color=TEXT, fontsize=10, ha="center")
        ax.text(0.70, y, b, color=TEXT, fontsize=10, ha="center")
        ax.plot([0.02, 0.98], [y - 0.03, y - 0.03], color="#2a3142", linewidth=0.5)

    ax.text(0.5, 0.16,
            "Гипотеза: confluence двух разных «линз» = более чистый сигнал.\n"
            "Тест: 10 способов скомбинировать признаки.",
            color=GREEN, fontsize=11, ha="center", style="italic")
    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def slide_indicators_visual(pdf):
    fig = plt.figure(figsize=PAGE)
    _setup(fig)
    _title(fig, "Два индикатора — на одном графике BTC 1h",
           "Слева: ASVK RSI · Справа: Money Hands")
    if ASVK_IMG.exists():
        ax1 = fig.add_axes([0.03, 0.10, 0.46, 0.78])
        ax1.imshow(mpimg.imread(ASVK_IMG))
        ax1.axis("off")
        ax1.set_title("ASVK RSI", color=ACCENT, fontsize=11, pad=8)
    if MH_IMG.exists():
        ax2 = fig.add_axes([0.51, 0.10, 0.46, 0.78])
        ax2.imshow(mpimg.imread(MH_IMG))
        ax2.axis("off")
        ax2.set_title("Money Hands", color=PURPLE, fontsize=11, pad=8)
    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


# -------- C1 .. C10 --------

def slide_c1(pdf):
    _hypothesis_slide(
        pdf, "C1", "Двойная дивергенция (ASVK И MH-bw2)",
        mechanic="Если в окне [touch-6h, signal_time] есть aligned-див\nна ОБОИХ индикаторах одновременно — взять сделку.",
        why="ASVK div ловит длинные паттерны (range 4-100),\nMH-bw2 div — короткие (range 5-60). Разные источники\n→ confluence должен усилить сигнал.",
        formula="LONG: bull/h_bull на ASVK И bull/h_bull на bw2\nSHORT: bear/h_bear на ASVK И bear/h_bear на bw2",
        result_rows=[
            ("BOTH ASVK + MH div", 12, "50.0%", "+0.000", MUTED),
            ("ASVK only (без MH)", 39, "66.7%", "+0.333", GREEN),
            ("MH-bw2 only", 11, "36.4%", "−0.273", RED),
            ("Neither", 181, "54.1%", "+0.083", MUTED),
        ],
        verdict="✗ ОПРОВЕРГНУТА. MH div размывает чистый сигнал ASVK.\nИспользуем ТОЛЬКО ASVK дивергенции.",
        verdict_color=RED,
    )


def slide_c2(pdf):
    _hypothesis_slide(
        pdf, "C2", "Phase-aware extreme (ASVK extreme + MH grey-after-color)",
        mechanic="LONG: ASVK ema_3 ниже dynamic_below (адаптивный OS)\nИ bw2 в фазе ⚪ серая-после-🔴 (медв импульс выдыхается).\nSHORT: симметрично.",
        why="ASVK говорит «цена в перепроданности», MH говорит\n«импульс вниз заканчивается». Два независимых факта\nсогласны на разворот.",
        formula="LONG: ema_3 < below_dyn AND bw2_color == 'grey_after_red'\nSHORT: ema_3 > above_dyn AND bw2_color == 'grey_after_green'",
        result_rows=[
            ("LONG strict (оба)", 0, "—", "—", MUTED),
            ("SHORT strict (оба)", 2, "50.0%", "+0.000", MUTED),
            ("ALL strict combined", 2, "50.0%", "+0.000", MUTED),
            ("MH phase ONLY (без ASVK extreme)", 15, "73.3%", "+0.467", GREEN),
            ("ASVK extreme only (без MH phase)", 17, "52.9%", "+0.059", MUTED),
        ],
        verdict="★★★ MH фаза САМА ПО СЕБЕ — мощный фильтр.\n«Серый-после-противоположного цвета» = разворот близко.",
        verdict_color=GREEN,
    )


def slide_c3(pdf):
    _hypothesis_slide(
        pdf, "C3", "8-флажный confluence sizing (4 ASVK + 4 MH)",
        mechanic="Размер позиции = 1.0 + 0.25 × score, где score = сумма\n8 бинарных флагов (4 от ASVK, 4 от MH). max 3.0×.",
        why="Расширение H15 (4 флага → 8). Гипотеза: больше степеней\nградации даст более точную привязку размера к качеству.",
        formula="ASVK флаги: aligned_div, side_50, deep_div, pct_extreme\nMH флаги: bw2_color OK, MF знак, bw2 в OB/OS на touch,\n          bw1/bw2 cross в окне",
        result_rows=[
            ("score>=2 sized", 155, "55.5%", "+0.205", YELLOW),
            ("score>=3 sized", 62, "64.5%", "+0.536", GREEN),
            ("score>=4 sized", 21, "66.7%", "+0.667", GREEN),
            ("Sized total (все)", 243, "55.1%", "+0.171", YELLOW),
            ("[H15 для сравнения]", 60, "63.3%", "+0.583", ACCENT),
        ],
        verdict="★★ slabe чем H15 (sized total +41R vs H15 +51R).\nMH флаги размывают чистоту ASVK score.",
        verdict_color=YELLOW,
    )


def slide_c4(pdf):
    _hypothesis_slide(
        pdf, "C4", "DUAL-EXIT (NWE-cross OR bw2 cross zero) ★★★★★",
        mechanic="Выход по самому раннему из трёх событий:\n• SL hit (1m)\n• ASVK ema_3 пересёк противоположный край NWE (1h)\n• MH bw2 пересёк 0 в противоположную сторону (1h)",
        why="H12 NWE-only сработал на LONG (+45R), но провалился\nна SHORT (−37R) — цена в bull-market редко доходит\nдо NWE-Lower. bw2-zero пересекается чаще → даёт\nSHORT-сделкам шанс закрыть с прибылью.",
        formula="LONG exit: ema_3 > NWE_upper OR bw2 < 0\nSHORT exit: ema_3 < NWE_lower OR bw2 > 0\nfallback: SL or 14d timeout",
        result_rows=[
            ("ALL 245 сделок", 245, "42.0%", "+0.370", GREEN),
            ("LONG (vs H12 +0.364)", 123, "43.9%", "+0.199", YELLOW),
            ("SHORT (vs H12 -0.307)", 122, "40.0%", "+0.542", GREEN),
            ("vs H12 SHORT swing", "—", "—", "+103R", GREEN),
            ("Total PnL +90.7R", "—", "—", "—", GREEN),
        ],
        verdict="★★★★★ САМОЕ БОЛЬШОЕ ОТКРЫТИЕ. SHORT превратился из\nкатастрофы в +66R. Симметричный exit для обоих направлений.",
        verdict_color=GREEN,
    )


def slide_c5(pdf):
    _hypothesis_slide(
        pdf, "C5", "Cross-acceleration (ASVK vorticity + MH phase)",
        mechanic="LONG: ASVK delta_ema3 > 0 (RSI ускоряется вверх)\n      AND bw2 в 🟢 зелёной фазе.\nSHORT: симметрично.",
        why="ASVK даёт «скорость», MH — «состояние». Соединение\n«направление + ускорение» должно усиливать pro-trend\nсигналы.",
        formula="LONG: rsi_velocity > 0 AND bw2_color == 'green'\nSHORT: rsi_velocity < 0 AND bw2_color == 'red'",
        result_rows=[
            ("LONG aligned", 17, "52.9%", "+0.059", MUTED),
            ("SHORT aligned", 16, "62.5%", "+0.250", YELLOW),
            ("ALL c5 aligned", 33, "57.6%", "+0.152", YELLOW),
            ("ALL non-aligned", 210, "54.8%", "+0.095", MUTED),
        ],
        verdict="≈ слабый edge. SHORT-half работает (+0.250),\nLONG-half не даёт ничего. Не рекомендую как фильтр.",
        verdict_color=YELLOW,
    )


def slide_c6_c7(pdf):
    fig = plt.figure(figsize=PAGE)
    _setup(fig)
    _title(fig, "C6, C7 — обе ОПРОВЕРГНУТЫ",
           "Идеи на «двойные паттерны» сошли с дистанции из-за малой выборки или слабого сигнала")

    # C6 box
    ax1 = fig.add_axes([0.04, 0.40, 0.92, 0.42])
    ax1.set_facecolor(PANEL)
    ax1.axis("off")
    ax1.set_xlim(0, 1)
    ax1.set_ylim(0, 1)
    ax1.add_patch(FancyBboxPatch((0.01, 0.01), 0.98, 0.98,
                                  boxstyle="round,pad=0.02",
                                  facecolor=PANEL, edgecolor=YELLOW, linewidth=1.2))
    ax1.text(0.03, 0.85, "C6 — Hidden-pair (trend continuation)",
             color=YELLOW, fontsize=13, fontweight="bold")
    ax1.text(0.03, 0.70,
             "Идея: hidden bull/bear на ОБОИХ индикаторах = двойное\n"
             "подтверждение продолжения тренда.",
             color=TEXT, fontsize=10)
    ax1.text(0.03, 0.45,
             "Условие: h_bull/h_bear divergence в окне [touch-6h, signal]\n"
             "ОДНОВРЕМЕННО на ASVK ema_3 И на MH bw2.",
             color=MUTED, fontsize=9)
    ax1.text(0.03, 0.18,
             "Результат: ALL hidden-pair n=3 (всего 3 сделки за 3 года!)\n"
             "Hidden ASVK only n=28 WR=64.3% R/tr=+0.286 — лучший вариант.",
             color=TEXT, fontsize=9)
    ax1.text(0.5, 0.06,
             "ВЕРДИКТ: статистически пусто (n=3). Hidden ASVK работает один.",
             color=YELLOW, fontsize=10, ha="center", fontweight="bold")

    # C7 box
    ax2 = fig.add_axes([0.04, 0.06, 0.92, 0.30])
    ax2.set_facecolor(PANEL)
    ax2.axis("off")
    ax2.set_xlim(0, 1)
    ax2.set_ylim(0, 1)
    ax2.add_patch(FancyBboxPatch((0.01, 0.01), 0.98, 0.98,
                                  boxstyle="round,pad=0.02",
                                  facecolor=PANEL, edgecolor=RED, linewidth=1.2))
    ax2.text(0.03, 0.78, "C7 — Disagreement Inverse",
             color=RED, fontsize=13, fontweight="bold")
    ax2.text(0.03, 0.55,
             "Идея: opposite-divergence на ОБОИХ → перевернуть сделку.\n"
             "(H18 одиночный провалился, может двойной anti-signal сработает?)",
             color=TEXT, fontsize=10)
    ax2.text(0.03, 0.20,
             "Результат: Both opposite n=15 WR 46.7% R/tr −0.067 — даже хуже baseline.",
             color=TEXT, fontsize=9)
    ax2.text(0.5, 0.06,
             "ВЕРДИКТ: ✗ ОПРОВЕРГНУТА. Двойной anti-signal тоже не работает.",
             color=RED, fontsize=10, ha="center", fontweight="bold")

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def slide_c8(pdf):
    _hypothesis_slide(
        pdf, "C8", "Volatility-regime фильтр (Narrow NWE)",
        mechanic="Изначально: MH серый цвет + ASVK NWE-канал узкий.\n→ market в тихой фазе → mean-reversion плохо.\n\nНаходка: NWE narrow САМ ПО СЕБЕ — отличный фильтр.",
        why="Узкий NWE-канал = малая историческая волатильность RSI.\nЭто значит, рынок «накапливал» движение, и FVG-зона на 4h\nбудет более точной (нет резких выбросов).",
        formula="ASVK NWE-канал ширина = nwe_upper − nwe_lower\nNarrow = bottom 30% по этой метрике (≤33.4 на нашей выборке)",
        result_rows=[
            ("Quiet (grey + narrow NWE)", 36, "58.3%", "+0.167", YELLOW),
            ("MH grey only", 99, "53.5%", "+0.071", MUTED),
            ("Narrow NWE only ★", 73, "61.6%", "+0.233", GREEN),
            ("NOT quiet (active phase)", 207, "54.6%", "+0.092", MUTED),
        ],
        verdict="★★★ Narrow NWE-канал — независимый фильтр.\n73 сделки, R/tr +0.233 — почти 2× baseline.",
        verdict_color=GREEN,
    )


def slide_c9_c10(pdf):
    fig = plt.figure(figsize=PAGE)
    _setup(fig)
    _title(fig, "C9, C10 — exit-фильтры на дне результатов",
           "Ни MF-фильтр для H11, ни Stoch-cross exit не превзошли C4")

    # C9
    ax1 = fig.add_axes([0.04, 0.50, 0.92, 0.32])
    ax1.set_facecolor(PANEL)
    ax1.axis("off")
    ax1.set_xlim(0, 1)
    ax1.set_ylim(0, 1)
    ax1.add_patch(FancyBboxPatch((0.01, 0.01), 0.98, 0.98,
                                  boxstyle="round,pad=0.02",
                                  facecolor=PANEL, edgecolor=RED, linewidth=1.2))
    ax1.text(0.03, 0.85, "C9 — H11 + MF знак (антифильтр)",
             color=RED, fontsize=13, fontweight="bold")
    ax1.text(0.03, 0.65,
             "Идея: H11 (LONG bars_since_OB > 100) + Money Flow > 0\n→ деньги текут вверх + RSI давно не был перегрет",
             color=TEXT, fontsize=10)
    ax1.text(0.03, 0.30,
             "H11 only n=58 WR 60.3% R/tr +0.207\n"
             "C9 ALL n=26 WR 53.8% R/tr +0.077 (хуже)\n"
             "H11 with MF DISALIGNED n=32 WR 65.6% R/tr +0.312 (лучше!)",
             color=TEXT, fontsize=9)
    ax1.text(0.5, 0.07,
             "✗ MF-знак РЕЖЕТ выигрышные сделки. Не использовать.",
             color=RED, fontsize=10, ha="center", fontweight="bold")

    # C10
    ax2 = fig.add_axes([0.04, 0.10, 0.92, 0.36])
    ax2.set_facecolor(PANEL)
    ax2.axis("off")
    ax2.set_xlim(0, 1)
    ax2.set_ylim(0, 1)
    ax2.add_patch(FancyBboxPatch((0.01, 0.01), 0.98, 0.98,
                                  boxstyle="round,pad=0.02",
                                  facecolor=PANEL, edgecolor=YELLOW, linewidth=1.2))
    ax2.text(0.03, 0.88, "C10 — Stoch-cross exit для SHORT",
             color=YELLOW, fontsize=13, fontweight="bold")
    ax2.text(0.03, 0.72,
             "Идея: для SHORT exit когда rsiMod пересёк stcRsiMod снизу↑\n(bull cross на двух Stoch = short-momentum закончился)",
             color=TEXT, fontsize=10)
    ax2.text(0.03, 0.40,
             "SHORT (Stoch cross) n=122 WR 25.0% R/tr +0.463\n"
             "SHORT (RR=1 фикс) n=122 WR 53% R/tr +0.066\n"
             "SHORT (C4 dual-exit) n=122 WR 40% R/tr +0.542 ← лучше всех",
             color=TEXT, fontsize=9)
    ax2.text(0.5, 0.07,
             "★ Лучше фикс RR=1, но проигрывает C4. C4 — победитель.",
             color=YELLOW, fontsize=10, ha="center", fontweight="bold")

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def slide_summary_table(pdf):
    fig = plt.figure(figsize=PAGE)
    _setup(fig)
    _title(fig, "Все 10 комбинированных гипотез — сводка",
           "Сортировка по силе edge")

    rows = [
        ("C4",  "Dual-exit (NWE+bw2 zero)",       "245", "42.0%", 0.370, "★★★★★", GREEN, "Total +90R; SHORT перевернулся"),
        ("C4-S","C4 на SHORT-сегменте",           "122", "40.0%", 0.542, "★★★★",  GREEN, "vs H12 −0.307: разница +103R"),
        ("C2",  "MH phase ONLY",                  "15",  "73.3%", 0.467, "★★★",   GREEN, "grey-после-противоположного"),
        ("C10", "Stoch-cross exit (SHORT)",       "122", "25.0%", 0.463, "★",     YELLOW,"лучше фикс, хуже C4"),
        ("C8",  "Narrow NWE only",                "73",  "61.6%", 0.233, "★★★",   GREEN, "узкий канал ASVK — фильтр"),
        ("C3",  "8-flag score>=4 sized",          "21",  "66.7%", 0.667, "★★",    YELLOW,"sizing работает, но H15 чище"),
        ("C5",  "Cross-acceleration",             "33",  "57.6%", 0.152, "≈",     MUTED, "слабый edge"),
        ("C9",  "H11 + MF knack",                 "26",  "53.8%", 0.077, "✗",     RED,   "MF режет H11 — антифильтр"),
        ("C1",  "Двойная divergence",             "12",  "50.0%", 0.000, "✗",     RED,   "MH div размывает ASVK"),
        ("C6",  "Hidden-pair",                    "3",   "—",     0.0,   "n маловат", MUTED, "статистики недостаточно"),
        ("C7",  "Both opposite-div inverse",      "15",  "46.7%", -0.067,"✗",     RED,   "двойной anti-signal не работает"),
        ("—",   "BASELINE 3.2 RR=1",              "243", "55.1%", 0.103, "",      MUTED, "для сравнения"),
    ]

    ax = fig.add_axes([0.02, 0.08, 0.96, 0.78])
    ax.set_facecolor(PANEL)
    ax.set_xlim(0, 100)
    ax.set_ylim(-0.5, len(rows) + 0.5)
    ax.invert_yaxis()
    ax.axis("off")
    ax.text(2, -0.2, "ID", color=ACCENT, fontsize=9, fontweight="bold")
    ax.text(7, -0.2, "Гипотеза", color=ACCENT, fontsize=9, fontweight="bold")
    ax.text(40, -0.2, "n", color=ACCENT, fontsize=9, fontweight="bold")
    ax.text(48, -0.2, "WR", color=ACCENT, fontsize=9, fontweight="bold")
    ax.text(58, -0.2, "R/tr", color=ACCENT, fontsize=9, fontweight="bold")
    ax.text(68, -0.2, "Edge", color=ACCENT, fontsize=9, fontweight="bold")
    ax.text(80, -0.2, "Заметка", color=ACCENT, fontsize=9, fontweight="bold")

    for i, (hid, name, n, wr, rt, mark, color, note) in enumerate(rows):
        bg = PANEL if i % 2 == 0 else "#1c2230"
        ax.add_patch(plt.Rectangle((0, i + 0.1), 100, 0.8, facecolor=bg, edgecolor="none"))
        ax.text(2, i + 0.5, hid, color=color, fontsize=9, fontweight="bold", va="center")
        ax.text(7, i + 0.5, name, color=TEXT, fontsize=9, va="center")
        ax.text(40, i + 0.5, n, color=TEXT, fontsize=9, va="center")
        ax.text(48, i + 0.5, wr, color=TEXT, fontsize=9, va="center")
        rt_color = (GREEN if rt > 0.20 else (YELLOW if rt > 0.10 else (RED if rt < 0 else MUTED)))
        ax.text(58, i + 0.5, f"{rt:+.3f}" if rt != 0 else "—",
                color=rt_color, fontsize=9, va="center", fontweight="bold")
        ax.text(68, i + 0.5, mark, color=color, fontsize=9, va="center")
        ax.text(80, i + 0.5, note, color=MUTED, fontsize=8, va="center")

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def slide_production(pdf):
    fig = plt.figure(figsize=PAGE)
    _setup(fig)
    _title(fig, "Production-кандидат v2 (с учётом combined)",
           "Главное обновление: dual-exit C4 решает проблему SHORT")

    ax = fig.add_axes([0.06, 0.55, 0.88, 0.32])
    ax.set_facecolor(PANEL)
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.add_patch(FancyBboxPatch((0.02, 0.05), 0.96, 0.9,
                                 boxstyle="round,pad=0.02",
                                 facecolor=PANEL, edgecolor=GREEN, linewidth=2))
    ax.text(0.5, 0.88, "Финальный сетап (combined)", color=TEXT, fontsize=14,
            fontweight="bold", ha="center")
    lines = [
        "  Базовый детектор 3.2",
        "+ confluence_score >= 1 от H15 (4 ASVK флага)  [убрать score=0]",
        "+ position_size = 1.0 + 0.5 × score   (max 3.0R)",
        "+ exit: SL OR (ASVK ema_3 пересёк противоположный NWE)",
        "        OR (MH bw2 пересёк 0 в противоположную сторону)   [C4]",
        "+ опциональный фильтр: Narrow NWE (нижние 30% ширины)   [C8]",
    ]
    for i, line in enumerate(lines):
        y = 0.74 - i * 0.10
        c = GREEN if line.startswith("+") else ACCENT
        ax.text(0.04, y, line, color=c, fontsize=10, family="monospace")

    # In-sample expected
    ax2 = fig.add_axes([0.06, 0.18, 0.42, 0.30])
    ax2.set_facecolor(PANEL)
    ax2.axis("off")
    ax2.set_xlim(0, 1)
    ax2.set_ylim(0, 1)
    ax2.add_patch(FancyBboxPatch((0.02, 0.05), 0.96, 0.9, boxstyle="round,pad=0.02",
                                  facecolor=PANEL, edgecolor=ACCENT, linewidth=1.2))
    ax2.text(0.5, 0.88, "In-sample expected", color=TEXT, fontsize=12,
             fontweight="bold", ha="center")
    rows = [
        ("Базовый 3.2 RR=1", "+25R / 0.103"),
        ("3.2 + H15 sized (только ASVK)", "+51R / 0.210"),
        ("3.2 + dual-exit C4 (без фильтров)", "+91R / 0.370"),
        ("3.2 + Narrow NWE + dual-exit", "≈ +60R / 0.50+"),
    ]
    for i, (k, v) in enumerate(rows):
        y = 0.72 - i * 0.13
        ax2.text(0.05, y, k, color=MUTED, fontsize=10)
        ax2.text(0.95, y, v, color=GREEN, fontsize=11, fontweight="bold", ha="right")

    # Next steps
    ax3 = fig.add_axes([0.52, 0.18, 0.42, 0.30])
    ax3.set_facecolor(PANEL)
    ax3.axis("off")
    ax3.set_xlim(0, 1)
    ax3.set_ylim(0, 1)
    ax3.add_patch(FancyBboxPatch((0.02, 0.05), 0.96, 0.9, boxstyle="round,pad=0.02",
                                  facecolor=PANEL, edgecolor=YELLOW, linewidth=1.2))
    ax3.text(0.5, 0.88, "Что проверить", color=TEXT, fontsize=12,
             fontweight="bold", ha="center")
    steps = [
        "1. ETH / SOL out-of-sample",
        "2. Walk-forward по годам",
        "3. Robustness к bw2 параметрам",
        "4. Live-prefill: bw2/NWE доступны на signal_time",
    ]
    for i, s in enumerate(steps):
        y = 0.72 - i * 0.13
        ax3.text(0.06, y, s, color=TEXT, fontsize=10)

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def slide_summary(pdf):
    fig = plt.figure(figsize=PAGE)
    _setup(fig)
    _title(fig, "Итоги combined-исследования",
           "10 гипотез · 3 рабочих edge'а · главный winner — C4")

    ax = fig.add_axes([0.06, 0.18, 0.88, 0.65])
    ax.set_facecolor(PANEL)
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.add_patch(FancyBboxPatch((0.02, 0.02), 0.96, 0.96,
                                 boxstyle="round,pad=0.02",
                                 facecolor=PANEL, edgecolor=ACCENT, linewidth=1.5))
    ax.text(0.5, 0.92, "Ключевые открытия", color=TEXT, fontsize=14,
             fontweight="bold", ha="center")

    items = [
        ("★", "C4 dual-exit — переворот для SHORT (+103R vs H12)", GREEN),
        ("★", "C2: MH цвет «grey-after-opposite» = WR 73% (15 сделок)", GREEN),
        ("★", "C8: узкий NWE-канал ASVK = +0.233 R/tr на 73 сделках", GREEN),
        ("◉", "C3 8-флажный score: sized +41R, но H15 чище (+51R)", YELLOW),
        ("◉", "C10 Stoch-cross exit для SHORT: лучше фикс, хуже C4", YELLOW),
        ("✗", "C1 двойная div: MH режет ASVK сигнал", RED),
        ("✗", "C7 inverse на двойной opposite-div: WR 46.7%", RED),
        ("✗", "C9 H11+MF: MF-знак — антифильтр", RED),
        ("?", "C6 hidden-pair: n=3, статистически пусто", MUTED),
    ]
    for i, (icon, text, color) in enumerate(items):
        y = 0.82 - i * 0.08
        ax.text(0.05, y, icon, color=color, fontsize=14, fontweight="bold")
        ax.text(0.10, y, text, color=TEXT, fontsize=10)

    fig.text(0.5, 0.10,
             "Главный takeaway: ASVK дивергенции > MH дивергенции,\n"
             "но MH bw2 как exit-trigger для SHORT — это game-changer.",
             color=YELLOW, fontsize=11, ha="center", style="italic")

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def main():
    OUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    print(f"[INFO] building PDF: {OUT_PDF}")
    with PdfPages(OUT_PDF) as pdf:
        slide_cover(pdf)
        slide_methodology(pdf)
        slide_indicators_visual(pdf)
        slide_c1(pdf)
        slide_c2(pdf)
        slide_c3(pdf)
        slide_c4(pdf)
        slide_c5(pdf)
        slide_c6_c7(pdf)
        slide_c8(pdf)
        slide_c9_c10(pdf)
        slide_summary_table(pdf)
        slide_production(pdf)
        slide_summary(pdf)
    print(f"[OK] saved: {OUT_PDF}")
    print(f"  size: {OUT_PDF.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
