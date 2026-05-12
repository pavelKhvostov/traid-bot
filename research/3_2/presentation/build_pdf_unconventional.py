"""PDF презентация по нестандартным гипотезам N1-N11.
Каждая гипотеза = отдельный слайд с пояснением + результатами.
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

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyBboxPatch
import numpy as np
import pandas as pd

OUT_PDF = Path("research/3_2/presentation/3_2_unconventional_findings.pdf")
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


def _setup(fig):
    fig.patch.set_facecolor(BG)


def _title(fig, t, sub=None):
    fig.text(0.06, 0.93, t, color=TEXT, fontsize=22, fontweight="bold")
    if sub:
        fig.text(0.06, 0.88, sub, color=MUTED, fontsize=12)
    fig.text(0.06, 0.04, "Strategy 3.2 · Unconventional Hypotheses N1-N11",
             color=MUTED, fontsize=8)
    fig.text(0.94, 0.04, "2026-05-06", color=MUTED, fontsize=8, ha="right")


def _hyp_slide(pdf, nid, title, mechanic, why, result_rows, verdict, vc):
    fig = plt.figure(figsize=PAGE)
    _setup(fig)
    _title(fig, f"{nid} — {title}")

    ax_l = fig.add_axes([0.04, 0.10, 0.50, 0.78])
    ax_l.set_facecolor(BG)
    ax_l.axis("off")
    ax_l.set_xlim(0, 1)
    ax_l.set_ylim(0, 1)
    sections = [("МЕХАНИКА", mechanic, ACCENT), ("ЗАЧЕМ", why, YELLOW)]
    y = 0.95
    for header, body, color in sections:
        ax_l.text(0.0, y, header, color=color, fontsize=11, fontweight="bold")
        y -= 0.05
        for line in body.split("\n"):
            ax_l.text(0.02, y, line, color=TEXT, fontsize=10)
            y -= 0.045
        y -= 0.03

    ax_r = fig.add_axes([0.56, 0.10, 0.40, 0.78])
    ax_r.set_facecolor(PANEL)
    ax_r.axis("off")
    ax_r.set_xlim(0, 1)
    ax_r.set_ylim(0, 1)
    ax_r.add_patch(FancyBboxPatch((0.02, 0.02), 0.96, 0.96, boxstyle="round,pad=0.02",
                                   facecolor=PANEL, edgecolor="#3a4252", linewidth=1.0))
    ax_r.text(0.5, 0.92, "РЕЗУЛЬТАТЫ", color=TEXT, fontsize=12,
              fontweight="bold", ha="center")
    ax_r.text(0.5, 0.86, "(на 243 closed)", color=MUTED, fontsize=9, ha="center")

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

    ax_r.add_patch(FancyBboxPatch((0.05, 0.06), 0.90, 0.16, boxstyle="round,pad=0.02",
                                   facecolor=BG, edgecolor=vc, linewidth=1.5))
    ax_r.text(0.5, 0.18, "ВЕРДИКТ", color=vc, fontsize=10,
              fontweight="bold", ha="center")
    ax_r.text(0.5, 0.10, verdict, color=TEXT, fontsize=10, ha="center")
    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def slide_cover(pdf):
    fig = plt.figure(figsize=PAGE)
    _setup(fig)
    fig.text(0.5, 0.66, "Unconventional Hypotheses",
             color=TEXT, fontsize=38, fontweight="bold", ha="center")
    fig.text(0.5, 0.59, "Когда обычные подходы исчерпаны",
             color=ACCENT, fontsize=22, ha="center")
    fig.text(0.5, 0.48, "11 нестандартных идей · 245 сетапов 3.2 · BTCUSDT 3 года",
             color=MUTED, fontsize=14, ha="center")
    fig.text(0.5, 0.36, "★★★★★ N11 anti-edge · ★★★★ N9 contrarian sizing · ★★★ N2 session · N5 div age",
             color=GREEN, fontsize=11, ha="center")
    fig.text(0.5, 0.18, "Andrew · 2026-05-06", color=MUTED, fontsize=11, ha="center")
    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def slide_methodology(pdf):
    fig = plt.figure(figsize=PAGE)
    _setup(fig)
    _title(fig, "Зачем нестандартные гипотезы?",
           "Стандартные confluence-фильтры исчерпали edge на ~+90R. Что ещё?")
    ax = fig.add_axes([0.04, 0.16, 0.92, 0.72])
    ax.set_facecolor(BG)
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    items = [
        ("🎩 Трейдерская интуиция", "Кластеры, сессии, день недели, возраст FVG —\nживая статистика рынка, которую не считают backtests."),
        ("🔬 Исследовательская креативность", "Энтропийные меры, age дивергенций, ATR-нормировка —\nML-стат-арбитражные приёмы, редкие в SMC-комьюнити."),
        ("🌀 Переинтерпретация инструментов", "MF не как направление, а как «уверенность рынка».\nFailure-of-pattern как сигнал для следующей сделки."),
        ("🎯 Гибридные exit-механики", "50% фикс + 50% trailing — компромисс между\nстабильностью и хвостовыми выигрышами."),
        ("🪞 Reversed analysis", "Не «когда играть», а «когда НЕ играть»:\nперебор worst-категорий, anti-filter."),
    ]
    for i, (head, body) in enumerate(items):
        y = 0.92 - i * 0.18
        ax.text(0.02, y, head, color=YELLOW, fontsize=13, fontweight="bold")
        for j, line in enumerate(body.split("\n")):
            ax.text(0.04, y - 0.04 - j * 0.035, line, color=TEXT, fontsize=10)
    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def slide_n1(pdf):
    _hyp_slide(pdf, "N1", "Cluster vs Lone signals",
        "Считаем сетапы 3.2 в окне [signal_time-24h, signal_time).\n"
        "Кластер = 1+ предыдущих, Lone = 0.",
        "Если рынок генерирует подряд несколько сетапов, это\n"
        "признак волатильного состояния. Кластерные сетапы могут\n"
        "работать иначе чем lone (либо все в плюс, либо все в минус).",
        [
            ("Lone (0 prev-24h)", 203, "55.7%", "+0.113", MUTED),
            ("Cluster low (1-2)", 40, "52.5%", "+0.050", MUTED),
            ("<6h since last (very fast)", 6, "66.7%", "+0.333", GREEN),
            ("6-24h since last", 35, "48.6%", "−0.029", RED),
            (">=24h since last", 201, "55.7%", "+0.114", MUTED),
        ],
        "≈ слабый. Очень-fast (<6h) дают +0.333, но n=6 мал.\nMid-cluster (6-24h) — слегка отрицательно.",
        YELLOW)


def slide_n2(pdf):
    _hyp_slide(pdf, "N2", "Session & Day-of-Week (★★★)",
        "Разбиваем сетапы по сессии (UTC):\n"
        "  Asia 0-7, Europe 7-13, US 13-21, Late_US 21-24.\n"
        "И по дню недели.",
        "Crypto SMC игнорирует session-time. Институционалы — нет.\n"
        "Mean-reversion может работать по-разному в азии vs us.",
        [
            ("Asia session (0-7 UTC)", 70, "41.4%", "−0.171", RED),
            ("Europe session (7-13)", 38, "63.2%", "+0.263", GREEN),
            ("US session (13-21)", 104, "60.6%", "+0.212", GREEN),
            ("Late US (21-24)", 31, "58.1%", "+0.161", GREEN),
            ("Friday", 37, "67.6%", "+0.351", GREEN),
            ("Sunday", 30, "46.7%", "−0.067", RED),
            ("Saturday (n маловат)", 10, "80.0%", "+0.600", MUTED),
        ],
        "★★★ Asia session — катастрофа. Просто исключая Asia,\nubirаем основной источник потерь.",
        GREEN)


def slide_n3(pdf):
    _hyp_slide(pdf, "N3", "FVG Age & Size — гипотеза перевернулась",
        "Возраст FVG-4h в момент touch (часы) и относительный размер\n"
        "(top-bottom)/mid в %.",
        "Trade-интуиция: «свежие маленькие FVG лучше отрабатывают —\n"
        "цена их помнит». Реальность оказалась обратной.",
        [
            ("Fresh FVG (<24h)", 179, "52.5%", "+0.050", MUTED),
            ("Medium age (24-168h)", 39, "61.5%", "+0.231", GREEN),
            ("Old FVG (>=168h, >7d)", 25, "64.0%", "+0.280", GREEN),
            ("Old + Large", 10, "70.0%", "+0.400", GREEN),
            ("Fresh + Small (intuit.)", 50, "48.0%", "−0.040", RED),
        ],
        "★★ Гипотеза перевернулась. Старые большие FVG > свежие маленькие.\nReady-to-revisit зоны лучше чем «горячие».",
        GREEN)


def slide_n4(pdf):
    _hyp_slide(pdf, "N4", "Agreement Score (entropy of 8 flags)",
        "score = (aligned_flags - opposed_flags) / 8 ∈ [-1, +1].\n"
        "8 флагов = 4 ASVK + 4 MH (как в C3 8-флажном).",
        "Энтропийная мера согласия индикаторов. Гипотеза:\n"
        "WR sigmoid от агрегата согласия. Strong aligned →\n"
        "лучший edge.",
        [
            ("strong aligned (>=0.5)", 0, "—", "—", MUTED),
            ("mild aligned (0.05..0.5)", 68, "57.4%", "+0.147", MUTED),
            ("neutral (-0.05..0.05)", 72, "52.8%", "+0.056", MUTED),
            ("mild opposed", 48, "52.1%", "+0.042", MUTED),
            ("strong opposed", 53, "58.5%", "+0.170", YELLOW),
        ],
        "≈ слабо. На наших данных «сильно опасный сетап»\nи «сильно подтверждённый» дают похожие R/tr.",
        YELLOW)


def slide_n5(pdf):
    _hyp_slide(pdf, "N5", "Divergence Age (★★★)",
        "Часы между сигналом и последним подтверждением aligned-div\n"
        "на 1h ASVK. Срез: ≤6h = свежая, 6-30h = средняя, >30h = старая.",
        "Дивергенция = моментальный сигнал. Через 30+ часов её\n"
        "эффект уже отыгран. SMC-коммьюнити использует div как\n"
        "бинарный флаг, игнорируя возраст.",
        [
            ("Fresh aligned div (<=6h)", 36, "63.9%", "+0.278", GREEN),
            ("Medium age (6-30h)", 82, "47.6%", "−0.049", RED),
            ("Old (>30h)", 125, "57.6%", "+0.152", MUTED),
            ("No aligned div ever", 0, "—", "—", MUTED),
        ],
        "★★★ Свежие divergences (<=6h) дают +0.278.\nMid-age — зона потерь. Возраст важен!",
        GREEN)


def slide_n7(pdf):
    _hyp_slide(pdf, "N7", "|MF| as Confidence — U-shape",
        "|MF| (модуль Money Flow) на signal_time. Не направление,\n"
        "а уверенность рынка. Q1=низкая, Q4=высокая.",
        "Гипотеза: low |MF| (рынок не определился) → лучше для fade.\n"
        "Реальность оказалась U-shape — НЕ монотонная.",
        [
            ("Low |MF| Q1 (undecided)", 61, "62.3%", "+0.246", GREEN),
            ("Mid |MF| Q2-Q3", 121, "47.9%", "−0.041", RED),
            ("High |MF| Q4 (confident)", 61, "62.3%", "+0.246", GREEN),
            ("High |MF| LONG", 36, "61.1%", "+0.222", GREEN),
            ("High |MF| SHORT", 25, "64.0%", "+0.280", GREEN),
        ],
        "★★★ U-shape! Edge на КРАЯХ |MF|, mid — мусор.\nИсключая mid-Q2-Q3 (50%) ubiraем основные потери.",
        GREEN)


def slide_n8(pdf):
    _hyp_slide(pdf, "N8", "Failure-of-Pattern",
        "quick_failure = SL hit ≤2h после активации.\n"
        "Флаг: «предыдущий сетап был quick_failure?».",
        "Идея: если 3.2-сетап провалился очень быстро, значит\n"
        "тренд против mean-reversion набирает силу. Следующий\n"
        "сетап может тоже проиграть.",
        [
            ("After prev QF", 57, "50.9%", "+0.018", RED),
            ("Not after QF", 186, "56.5%", "+0.129", MUTED),
            ("Same direction after QF", 26, "57.7%", "+0.154", MUTED),
            ("Opposite direction after QF", 31, "45.2%", "−0.097", RED),
        ],
        "≈ слабый. Opposite direction после QF — антифильтр\n(имеет смысл скипать).",
        YELLOW)


def slide_n9(pdf):
    _hyp_slide(pdf, "N9", "Win/Loss-Streak Sizing (★★★★)",
        "win_streak_before = текущая серия побед перед сделкой.\n"
        "loss_streak_before = серия проигрышей.",
        "Стандарт: anti-martingale (растим после wins). На 3.2 этот\n"
        "подход НЕ работает. Нужен contrarian (сжать после wins,\n"
        "увеличить после losses).",
        [
            ("After 3+ wins", 33, "39.4%", "−0.212", RED),
            ("After 3+ losses", 12, "75.0%", "+0.500", GREEN),
            ("streak 2 losses → next", 32, "71.9%", "+0.438", GREEN),
            ("streak 3 losses → next", 9, "88.9%", "+0.778", GREEN),
            ("Anti-martingale k=1", "—", "—", "−4R", RED),
        ],
        "★★★★ Mean-reversion of mean-reversion. После 3+ wins\nмы переоцениваем edge — нужно СНИЖАТЬ size.",
        GREEN)


def slide_n6(pdf):
    _hyp_slide(pdf, "N6", "ATR-Normalized SL",
        "Modified SL = original_sl ± k × ATR(14).\n"
        "Перебор k ∈ {0, 0.5, 1.0, 1.5, 2.0}.",
        "ML-арбитражники нормируют SL на текущую волатильность,\n"
        "SMC ставит фикс «за пивот». Может, ATR-расширение даст\n"
        "robustness.",
        [
            ("k=0 (original)", 243, "55.1%", "+0.103", GREEN),
            ("k=0.5", 243, "52.7%", "+0.053", MUTED),
            ("k=1.0", 243, "52.3%", "+0.045", MUTED),
            ("k=1.5", 243, "47.7%", "−0.045", RED),
            ("k=2.0", 243, "49.0%", "−0.020", RED),
        ],
        "✗ Оригинальный SL (за c0) уже почти оптимален.\nATR-расширение только ухудшает edge.",
        RED)


def slide_n10(pdf):
    _hyp_slide(pdf, "N10", "Hybrid TP (50% fix + 50% dynamic)",
        "50% позиции exit при фикс RR=1.\n"
        "50% — dual-exit (NWE OR bw2-zero, как в C4).\n"
        "Если TP_fix хитнут, потом ловим хвост на оставшихся 50%.",
        "Гибрид «стабильность + хвост». В литературе экспозиция\n"
        "к runner'ам важна для long-term edge.",
        [
            ("Hybrid TP total", 245, "—", "+0.194", YELLOW),
            ("vs Baseline RR=1", "—", "—", "+0.103", MUTED),
            ("vs C4 dual-exit", "—", "—", "+0.370", GREEN),
            ("be (BE-стопы)", 18, "—", "—", MUTED),
        ],
        "≈ Лучше baseline, но ХУЖЕ C4. Гибрид не выгоден —\n100% dual-exit сильнее.",
        YELLOW)


def slide_n11(pdf):
    _hyp_slide(pdf, "N11", "Reversed Analysis — ★★★★★ ANTI-EDGE",
        "Brute-force поиск worst-комбинаций бинарных признаков\n"
        "(1, 2, 3 шт). Цель: «не торгуй когда X», anti-filter.",
        "Standard backtest ищет «когда играть». Reversed ищет\n"
        "«когда НЕ играть». Простое правило-исключение часто\n"
        "сильнее complex confluence-magic.",
        [
            ("Baseline 3.2", 243, "55.1%", "+0.103", MUTED),
            ("Без after_3+_wins", 210, "57.6%", "+0.152", YELLOW),
            ("Без + Asia session", 147, "64.6%", "+0.293", GREEN),
            ("Без + Sunday", 128, "65.6%", "+0.312", GREEN),
            ("SHORT+Asia+small_FVG (worst)", 11, "9.1%", "−0.818", RED),
            ("SHORT+Asia+grey_after_red", 13, "15.4%", "−0.692", RED),
            ("LONG+Asia+green_phase", 10, "20.0%", "−0.600", RED),
        ],
        "★★★★★ Простое 3-feature anti-rule даёт R/tr +0.312\nбез всякого complex confluence. Чистый edge.",
        GREEN)


def slide_summary_table(pdf):
    fig = plt.figure(figsize=PAGE)
    _setup(fig)
    _title(fig, "Все 11 нестандартных гипотез — сводка",
           "Сортировка по силе edge")

    rows = [
        ("N11", "Reversed: убрать Asia+Sunday+after_3wins", "128", "65.6%", 0.312, "★★★★★", GREEN, "anti-filter сильнее любого confluence"),
        ("N9-best", "После 3+ losses (contrarian)", "12", "75.0%", 0.500, "★★★★", GREEN, "Mean-rev of mean-rev"),
        ("N9-3", "После 3 losses (cumul)", "9", "88.9%", 0.778, "★★★★", GREEN, "Малый n, но огромный WR"),
        ("N3", "Old + Large FVG", "10", "70.0%", 0.400, "★★★", GREEN, "FVG-возраст играет"),
        ("N2", "Friday session", "37", "67.6%", 0.351, "★★★", GREEN, "Конец недели — хорошо"),
        ("N1", "<6h since last", "6", "66.7%", 0.333, "★★", YELLOW, "Hot zone, n маловат"),
        ("N5", "Fresh aligned div ≤6h", "36", "63.9%", 0.278, "★★★", GREEN, "Свежесть divergence важна"),
        ("N3", "Old FVG (>7d)", "25", "64.0%", 0.280, "★★", GREEN, "Контр-интуитивно"),
        ("N7", "Low \\|MF\\| (Q1)", "61", "62.3%", 0.246, "★★", GREEN, "Undecided market = fade ОК"),
        ("N7", "High \\|MF\\| (Q4)", "61", "62.3%", 0.246, "★★", GREEN, "Confident market — тоже работает"),
        ("N9-loss2", "After 2 losses", "32", "71.9%", 0.438, "★★★", GREEN, "Подтверждение N9 идеи"),
        ("N2-eu", "Europe session", "38", "63.2%", 0.263, "★★", GREEN, "EU работает"),
        ("N2-us", "US session", "104", "60.6%", 0.212, "★★", GREEN, "US — main edge"),
        ("N4", "Agreement entropy", "—", "—", 0.0, "≈", MUTED, "слабо различимо"),
        ("N8", "Failure-of-pattern", "57", "50.9%", 0.018, "≈", MUTED, "Same dir после QF — neutral"),
        ("N10", "Hybrid TP 50/50", "245", "—", 0.194, "≈", YELLOW, "хуже C4"),
        ("N6", "ATR-normalized SL", "243", "—", 0.045, "✗", RED, "оригинальный SL лучше"),
        ("N2-asia", "Asia session", "70", "41.4%", -0.171, "✗", RED, "АНТИФИЛЬТР — исключить"),
        ("N9-wins", "After 3+ wins", "33", "39.4%", -0.212, "✗", RED, "АНТИФИЛЬТР — skip"),
    ]
    ax = fig.add_axes([0.02, 0.05, 0.96, 0.81])
    ax.set_facecolor(PANEL)
    ax.set_xlim(0, 100)
    ax.set_ylim(-0.5, len(rows) + 0.5)
    ax.invert_yaxis()
    ax.axis("off")
    ax.text(2, -0.2, "ID", color=ACCENT, fontsize=9, fontweight="bold")
    ax.text(8, -0.2, "Сегмент", color=ACCENT, fontsize=9, fontweight="bold")
    ax.text(40, -0.2, "n", color=ACCENT, fontsize=9, fontweight="bold")
    ax.text(48, -0.2, "WR", color=ACCENT, fontsize=9, fontweight="bold")
    ax.text(58, -0.2, "R/tr", color=ACCENT, fontsize=9, fontweight="bold")
    ax.text(68, -0.2, "Edge", color=ACCENT, fontsize=9, fontweight="bold")
    ax.text(78, -0.2, "Заметка", color=ACCENT, fontsize=9, fontweight="bold")
    for i, (hid, name, n, wr, rt, mark, color, note) in enumerate(rows):
        bg = PANEL if i % 2 == 0 else "#1c2230"
        ax.add_patch(plt.Rectangle((0, i + 0.1), 100, 0.8, facecolor=bg, edgecolor="none"))
        ax.text(2, i + 0.5, hid, color=color, fontsize=9, fontweight="bold", va="center")
        ax.text(8, i + 0.5, name, color=TEXT, fontsize=9, va="center")
        ax.text(40, i + 0.5, n, color=TEXT, fontsize=9, va="center")
        ax.text(48, i + 0.5, wr, color=TEXT, fontsize=9, va="center")
        rt_color = (GREEN if rt > 0.20 else (YELLOW if rt > 0.10 else (RED if rt < 0 else MUTED)))
        ax.text(58, i + 0.5, f"{rt:+.3f}" if rt != 0 else "—",
                color=rt_color, fontsize=9, va="center", fontweight="bold")
        ax.text(68, i + 0.5, mark, color=color, fontsize=9, va="center")
        ax.text(78, i + 0.5, note, color=MUTED, fontsize=8, va="center")
    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def slide_production(pdf):
    fig = plt.figure(figsize=PAGE)
    _setup(fig)
    _title(fig, "Production-кандидат v3 (с anti-edge от N11)",
           "Самый чистый рецепт без сложного confluence")

    ax = fig.add_axes([0.06, 0.45, 0.88, 0.42])
    ax.set_facecolor(PANEL)
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.add_patch(FancyBboxPatch((0.02, 0.05), 0.96, 0.9, boxstyle="round,pad=0.02",
                                 facecolor=PANEL, edgecolor=GREEN, linewidth=2))
    ax.text(0.5, 0.92, "Финальный сетап (3 правила-исключения + sizing + dual-exit)",
            color=TEXT, fontsize=14, fontweight="bold", ha="center")
    lines = [
        "  Базовый детектор 3.2 (FVG-4h → 2-свечи rejection → FVG-1h)",
        "−  ИСКЛЮЧИТЬ: signal в Asia сессии (00:00-07:00 UTC)",
        "−  ИСКЛЮЧИТЬ: signal в Sunday",
        "−  ИСКЛЮЧИТЬ: после 3+ wins подряд",
        "+  position size = base × (1 + 0.5×loss_streak − 0.5×win_streak)   [N9 contr.]",
        "+  exit: SL OR ASVK ema_3 пересёк противопол. NWE OR MH bw2 cross 0   [C4]",
        "○  опционально: фильтр по N5 (свежая div ≤6h) или N7 (исключить mid-|MF|)",
    ]
    for i, line in enumerate(lines):
        y = 0.80 - i * 0.10
        c = GREEN if line.startswith("+") else (RED if line.startswith("−") else
              (YELLOW if line.startswith("○") else ACCENT))
        ax.text(0.04, y, line, color=c, fontsize=10, family="monospace")

    ax2 = fig.add_axes([0.06, 0.13, 0.42, 0.27])
    ax2.set_facecolor(PANEL)
    ax2.axis("off")
    ax2.set_xlim(0, 1)
    ax2.set_ylim(0, 1)
    ax2.add_patch(FancyBboxPatch((0.02, 0.05), 0.96, 0.9, boxstyle="round,pad=0.02",
                                  facecolor=PANEL, edgecolor=ACCENT, linewidth=1.2))
    ax2.text(0.5, 0.88, "Эволюция edge", color=TEXT, fontsize=12,
             fontweight="bold", ha="center")
    rows = [
        ("Baseline 3.2 RR=1", "+25R / 0.103"),
        ("+ H15 sized (4 ASVK flags)", "+51R / 0.210"),
        ("+ C4 dual-exit", "+91R / 0.370"),
        ("+ N11 anti-edge (3 правила)", "+40R / 0.312 на n=128"),
    ]
    for i, (k, v) in enumerate(rows):
        y = 0.72 - i * 0.13
        ax2.text(0.05, y, k, color=MUTED, fontsize=10)
        ax2.text(0.95, y, v, color=GREEN, fontsize=11, fontweight="bold", ha="right")

    ax3 = fig.add_axes([0.52, 0.13, 0.42, 0.27])
    ax3.set_facecolor(PANEL)
    ax3.axis("off")
    ax3.set_xlim(0, 1)
    ax3.set_ylim(0, 1)
    ax3.add_patch(FancyBboxPatch((0.02, 0.05), 0.96, 0.9, boxstyle="round,pad=0.02",
                                  facecolor=PANEL, edgecolor=YELLOW, linewidth=1.2))
    ax3.text(0.5, 0.88, "Что критично проверить", color=TEXT, fontsize=12,
             fontweight="bold", ha="center")
    steps = [
        "1. Asia provаl — overfit на BTC 2023-2026?",
        "2. Sunday-эффект — стабилен по годам?",
        "3. After-wins drop — есть на ETH/SOL?",
        "4. Live-доступность всех флагов в момент signal",
    ]
    for i, s in enumerate(steps):
        y = 0.72 - i * 0.13
        ax3.text(0.06, y, s, color=TEXT, fontsize=10)
    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def slide_summary(pdf):
    fig = plt.figure(figsize=PAGE)
    _setup(fig)
    _title(fig, "Итоги нестандартного исследования",
           "11 идей · 5 рабочих edge'ов · 3 опровергнутые · главный winner — N11")
    ax = fig.add_axes([0.06, 0.18, 0.88, 0.65])
    ax.set_facecolor(PANEL)
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.add_patch(FancyBboxPatch((0.02, 0.02), 0.96, 0.96, boxstyle="round,pad=0.02",
                                 facecolor=PANEL, edgecolor=ACCENT, linewidth=1.5))
    ax.text(0.5, 0.94, "Главные открытия", color=TEXT, fontsize=14,
             fontweight="bold", ha="center")
    items = [
        ("★", "N11 anti-edge: 3 правила «не играй когда X» = R/tr +0.312", GREEN),
        ("★", "N9 contrarian sizing: после 3+ wins СНИЖАТЬ позицию (anti-martingale)", GREEN),
        ("★", "N2 session: Asia катастрофа (-0.171), EU/US работают", GREEN),
        ("★", "N5 div age: свежие <=6h дают +0.278, старые >30h — только +0.152", GREEN),
        ("★", "N7 |MF| U-shape: edge на КРАЯХ, mid-quartile = мусор", GREEN),
        ("◉", "N3 FVG age: старые большие > свежие маленькие (контр-интуитивно)", YELLOW),
        ("◉", "N1 cluster: <6h since last = hot zone (n маловат)", YELLOW),
        ("✗", "N6 ATR-SL: оригинальный SL уже оптимален", RED),
        ("✗", "N10 hybrid TP: уступает чистому dual-exit C4", RED),
        ("?", "N4 entropy / N8 failure-of-pattern: слабо различимо", MUTED),
    ]
    for i, (icon, text, color) in enumerate(items):
        y = 0.84 - i * 0.075
        ax.text(0.05, y, icon, color=color, fontsize=14, fontweight="bold")
        ax.text(0.10, y, text, color=TEXT, fontsize=10)
    fig.text(0.5, 0.10,
             "Главный takeaway: иногда «когда НЕ торговать» сильнее «когда торговать».\n"
             "Anti-filter (N11) на 3-х простых правилах побеждает любой 8-флажный confluence.",
             color=YELLOW, fontsize=11, ha="center", style="italic")
    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def main():
    OUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    print(f"[INFO] building PDF: {OUT_PDF}")
    with PdfPages(OUT_PDF) as pdf:
        slide_cover(pdf)
        slide_methodology(pdf)
        slide_n1(pdf)
        slide_n2(pdf)
        slide_n3(pdf)
        slide_n4(pdf)
        slide_n5(pdf)
        slide_n6(pdf)
        slide_n7(pdf)
        slide_n8(pdf)
        slide_n9(pdf)
        slide_n10(pdf)
        slide_n11(pdf)
        slide_summary_table(pdf)
        slide_production(pdf)
        slide_summary(pdf)
    print(f"[OK] saved: {OUT_PDF}")
    print(f"  size: {OUT_PDF.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
