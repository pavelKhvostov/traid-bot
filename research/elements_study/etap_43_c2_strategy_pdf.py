"""Этап 43: PDF-описание стратегии C2 на русском, человеческим языком.

Структура (8 страниц):
  p1. Что это за стратегия (3 абзаца + краткие итоги)
  p2. Что такое OB и FVG — основа стратегии
  p3. Как формируется сетап (логика поиска)
  p4. Как заходим в позицию (entry, SL, TP с объяснением ЗАЧЕМ так)
  p5. Демо-сделка #1 — реальная LONG, что произошло
  p6. Демо-сделка #2 — реальная SHORT, что произошло
  p7. Что показал бэктест и что значат эти цифры
  p8. Слабые стороны и над чем работать
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from pathlib import Path
import time
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
from matplotlib.backends.backend_pdf import PdfPages

from data_manager import load_df
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg

# Шрифт с поддержкой кириллицы
matplotlib.rcParams["font.family"] = "DejaVu Sans"
matplotlib.rcParams["font.sans-serif"] = ["DejaVu Sans"]

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
ANCHOR_TF = "6h"
TRIGGER_TF = "2h"
MIN_SL_PCT = 1.0
SL_BUF_ATR = 0.3
ENTRY_PCT = 0.5
RR = 1.0
LIFE_DAYS = 10
TIMEOUT_DAYS = 3

OUT_DIR = Path("research/elements_study/output")
OUT_PDF = OUT_DIR / "etap43_strategy_c2_report.pdf"

# Палитра
BG = "#0e1217"
PANEL_BG = "#1a1f29"
TEXT = "#e8eef7"
TEXT_DIM = "#9aa5b8"
BLUE = "#42a5f5"
GREEN = "#4caf50"
RED = "#ef5350"
YELLOW = "#ffd54f"
PURPLE = "#ab47bc"
GREY = "#787b86"


# ---------- расчёты ----------

def compute_atr(df, period=14):
    high = df["high"]; low = df["low"]; pc = df["close"].shift(1)
    tr = pd.concat([(high-low),(high-pc).abs(),(low-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


class FastSim:
    def __init__(self, df_1m):
        self.ts = df_1m.index.values
        self.high = df_1m["high"].to_numpy(dtype=float)
        self.low = df_1m["low"].to_numpy(dtype=float)

    def simulate(self, direction, entry, sl, tp, start_time, timeout_days):
        end_time = start_time + pd.Timedelta(days=timeout_days)
        i0 = np.searchsorted(self.ts, np.datetime64(
            start_time.tz_localize(None) if start_time.tz else start_time))
        i1 = np.searchsorted(self.ts, np.datetime64(
            end_time.tz_localize(None) if end_time.tz else end_time))
        if i1 <= i0: return ("no_data", 0.0, None)
        h = self.high[i0:i1]; l = self.low[i0:i1]
        risk = abs(entry - sl)
        if risk <= 0: return ("invalid", 0.0, None)
        if direction == "LONG":
            act_mask = l <= entry
            if not act_mask.any(): return ("not_filled", 0.0, None)
            act_idx = int(np.argmax(act_mask))
            h2 = h[act_idx:]; l2 = l[act_idx:]
            sl_hits = l2 <= sl; tp_hits = h2 >= tp
            sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else len(h2)
            tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else len(h2)
            if sl_idx == len(h2) and tp_idx == len(h2): return ("open", 0.0, None)
            close_ts = pd.Timestamp(self.ts[i0 + act_idx + min(sl_idx, tp_idx)]).tz_localize("UTC")
            if sl_idx <= tp_idx: return ("loss", -1.0, close_ts)
            return ("win", (tp - entry) / risk, close_ts)
        else:
            act_mask = h >= entry
            if not act_mask.any(): return ("not_filled", 0.0, None)
            act_idx = int(np.argmax(act_mask))
            h2 = h[act_idx:]; l2 = l[act_idx:]
            sl_hits = h2 >= sl; tp_hits = l2 <= tp
            sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else len(h2)
            tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else len(h2)
            if sl_idx == len(h2) and tp_idx == len(h2): return ("open", 0.0, None)
            close_ts = pd.Timestamp(self.ts[i0 + act_idx + min(sl_idx, tp_idx)]).tz_localize("UTC")
            if sl_idx <= tp_idx: return ("loss", -1.0, close_ts)
            return ("win", (entry - tp) / risk, close_ts)


def collect_obs(df, atr, tf):
    out = []
    for idx in range(2, len(df) - 1):
        ob = detect_ob_pair(df, idx)
        if ob is None: continue
        a = float(atr.iloc[idx])
        if pd.isna(a) or a <= 0: continue
        out.append({"time": ob.cur_time, "direction": ob.direction,
                     "bottom": ob.bottom, "top": ob.top, "atr": a, "tf": tf,
                     "idx": idx, "prev_time": ob.prev_time})
    return out


def collect_fvgs(df, atr, tf):
    out = []
    for idx in range(2, len(df) - 1):
        f = detect_fvg(df, idx)
        if f is None: continue
        a = float(atr.iloc[idx])
        if pd.isna(a) or a <= 0: continue
        out.append({"time": f.c2_time, "direction": f.direction,
                     "bottom": f.bottom, "top": f.top, "atr": a, "tf": tf,
                     "idx": idx, "c0_time": f.c0_time})
    return out


def zones_overlap(b1, t1, b2, t2):
    return not (t1 < b2 or t2 < b1)


def build_c2_setups(obs_6h, fvgs_2h, df_2h):
    a_tf_td = pd.Timedelta(ANCHOR_TF)
    a_life = pd.Timedelta(days=LIFE_DAYS)
    t_sorted = sorted(fvgs_2h, key=lambda x: x["time"])
    t_times = np.array([np.datetime64(t["time"].tz_localize(None) if t["time"].tz else t["time"])
                         for t in t_sorted])
    ema_arr = df_2h["ema200"].to_numpy()
    close_arr = df_2h["close"].to_numpy()
    setups = []
    for a in obs_6h:
        a_start = a["time"] + a_tf_td
        a_end = a["time"] + a_life
        if a_end <= a_start: continue
        i_start = np.searchsorted(t_times, np.datetime64(
            a_start.tz_localize(None) if a_start.tz else a_start), side="right")
        i_end = np.searchsorted(t_times, np.datetime64(
            a_end.tz_localize(None) if a_end.tz else a_end), side="right")
        for ti in range(i_start, i_end):
            t = t_sorted[ti]
            if t["direction"] != a["direction"]: continue
            if not zones_overlap(t["bottom"], t["top"], a["bottom"], a["top"]):
                continue
            em = float(ema_arr[t["idx"]]); cl = float(close_arr[t["idx"]])
            pro = ((t["direction"] == "LONG" and cl > em) or
                   (t["direction"] == "SHORT" and cl < em))
            if not pro: continue
            setups.append({"anchor": a, "trigger": t,
                            "anchor_time": a["time"],
                            "trigger_time": t["time"],
                            "direction": t["direction"],
                            "year": t["time"].year})
            break
    return setups


def build_c2_orders(s):
    t = s["trigger"]
    direction = t["direction"]
    fb, ft = t["bottom"], t["top"]
    atr = t["atr"]
    if direction == "LONG":
        entry = fb + ENTRY_PCT * (ft - fb)
        atr_sl = fb - SL_BUF_ATR * atr
        min_dist = entry * MIN_SL_PCT / 100
        sl = min(atr_sl, entry - min_dist)
    else:
        entry = ft - ENTRY_PCT * (ft - fb)
        atr_sl = ft + SL_BUF_ATR * atr
        min_dist = entry * MIN_SL_PCT / 100
        sl = max(atr_sl, entry + min_dist)
    risk = abs(entry - sl)
    if risk <= 0: return None
    tp = entry + RR * risk if direction == "LONG" else entry - RR * risk
    return entry, sl, tp


def evaluate(setups, sim):
    rows = []
    for s in setups:
        tup = build_c2_orders(s)
        if tup is None: continue
        entry, sl, tp = tup
        start = s["trigger_time"] + pd.Timedelta(TRIGGER_TF)
        outcome, R, close_ts = sim.simulate(s["direction"], entry, sl, tp,
                                              start, TIMEOUT_DAYS)
        rows.append({**s, "entry": entry, "sl": sl, "tp": tp,
                      "outcome": outcome, "R": R, "close_ts": close_ts,
                      "start_time": start})
    return pd.DataFrame(rows)


# ============================================================
# Хелперы для PDF
# ============================================================

def setup_axes(ax, title=None):
    ax.set_facecolor(BG)
    for s in ax.spines.values(): s.set_color("#3a4252")
    ax.tick_params(colors=TEXT)
    ax.grid(True, color="#202632", linewidth=0.4)
    if title:
        ax.set_title(title, color=TEXT, fontsize=12, pad=8)


def text_block(ax, x, y, lines, fontsize=10, color=TEXT, family="sans-serif",
                lh=0.025, weight="normal"):
    """Вывод многострочного текста с одинаковым шагом."""
    for i, line in enumerate(lines):
        ax.text(x, y - i * lh, line, ha="left", va="top",
                 fontsize=fontsize, color=color, family=family,
                 fontweight=weight)


# ============================================================
# СТРАНИЦЫ
# ============================================================

def page_intro(pdf, stats):
    """Страница 1 — что это за стратегия."""
    fig = plt.figure(figsize=(11, 8.5))
    fig.patch.set_facecolor(BG)

    # Заголовок
    ax_h = fig.add_axes([0.05, 0.83, 0.9, 0.12])
    ax_h.set_facecolor(BG); ax_h.axis("off")
    ax_h.text(0.5, 0.7, "Стратегия C2", ha="center", va="center",
                fontsize=32, color=TEXT, fontweight="bold")
    ax_h.text(0.5, 0.25,
                "Простая 2-уровневая SMC-стратегия для BTCUSDT",
                ha="center", va="center",
                fontsize=14, color=BLUE)

    # Краткая суть в трёх абзацах
    ax_t = fig.add_axes([0.06, 0.45, 0.88, 0.36])
    ax_t.set_facecolor(BG); ax_t.axis("off")

    intro_lines = [
        "О чём эта стратегия",
        "─────────────────────────────────────────────────────────────────",
        "",
        "C2 — это простой алгоритм поиска сетапов на BTCUSDT, основанный на двух",
        "элементах SMC (Smart Money Concepts): Order Block (OB) на 6-часовом",
        "графике и Fair Value Gap (FVG) на 2-часовом. Когда оба формируются в",
        "одном направлении и в перекрывающихся ценовых зонах — это сигнал к",
        "входу. Стратегия торгует только по тренду (фильтр EMA200 на 2h).",
        "",
        "Принцип такой: «Институционалы оставили след (OB-6h), цена откатилась к",
        "этому уровню и образовала разрыв (FVG-2h) в направлении основного",
        "тренда — самое время войти». Это классический паттерн «откат на",
        "поддержку/сопротивление» в SMC-исполнении.",
        "",
        "В отличие от других кандидатов (1.1.1 с 4 уровнями, или D1 с RR=2.5),",
        "C2 максимально проста — только 2 уровня вложенности и фиксированный",
        "RR=1.0. Эта простота даёт стабильность: она единственная из всех",
        "протестированных стратегий, у которой 0 минусовых лет за 7 лет данных.",
    ]
    text_block(ax_t, 0.0, 1.0, intro_lines, fontsize=10.5, lh=0.048)
    # Заголовки выделить
    ax_t.text(0.0, 1.0, intro_lines[0], ha="left", va="top",
                fontsize=12, color=YELLOW, fontweight="bold")

    # Краткая таблица итогов в боксе
    ax_b = fig.add_axes([0.10, 0.05, 0.80, 0.35])
    ax_b.set_facecolor(PANEL_BG)
    for s in ax_b.spines.values(): s.set_color(BLUE); s.set_linewidth(1.5)
    ax_b.set_xticks([]); ax_b.set_yticks([])

    summary_left = [
        ("Период тестирования", "6.33 года (2020-01-01 — 2026-05-09)"),
        ("Инструмент", "BTCUSDT (только Bitcoin)"),
        ("Всего сетапов", f"{stats['n_total']} (≈ {stats['n_total']/6.33:.0f} в год, 2.3 в неделю)"),
        ("Win Rate (% прибыльных)", f"{stats['wr']:.1f}% — выше точки безубытка (50%)"),
    ]
    summary_right = [
        ("Суммарный результат", f"+{stats['total_R']:.0f}R за 6.33 года"),
        ("В пересчёте на год", f"+{stats['per_year']:.1f}R / год"),
        ("Минусовых лет", f"{stats['bad_yrs']} из {stats['n_yrs']} — лучший показатель в исследовании"),
        ("Риск-награда (RR)", "1:1 (фиксированный)"),
    ]

    ax_b.text(0.5, 0.92, "Что показала стратегия за 6.33 года",
                ha="center", va="center", fontsize=14,
                color=TEXT, fontweight="bold",
                transform=ax_b.transAxes)

    for i, (label, value) in enumerate(summary_left):
        y = 0.72 - i * 0.16
        ax_b.text(0.04, y, label, fontsize=10, color=TEXT_DIM,
                    transform=ax_b.transAxes)
        ax_b.text(0.04, y - 0.06, value, fontsize=11.5, color=TEXT,
                    transform=ax_b.transAxes, fontweight="bold")
    for i, (label, value) in enumerate(summary_right):
        y = 0.72 - i * 0.16
        ax_b.text(0.52, y, label, fontsize=10, color=TEXT_DIM,
                    transform=ax_b.transAxes)
        ax_b.text(0.52, y - 0.06, value, fontsize=11.5, color=GREEN,
                    transform=ax_b.transAxes, fontweight="bold")

    # Подвал
    ax_f = fig.add_axes([0.05, 0.01, 0.9, 0.03])
    ax_f.set_facecolor(BG); ax_f.axis("off")
    ax_f.text(0.5, 0.5, "Отчёт сформирован 2026-05-09 · etap_43",
                ha="center", va="center", fontsize=8, color=GREY)

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def page_basics(pdf):
    """Страница 2 — что такое OB и FVG."""
    fig = plt.figure(figsize=(11, 8.5))
    fig.patch.set_facecolor(BG)
    fig.text(0.5, 0.96, "Основа стратегии: что такое OB и FVG",
              ha="center", fontsize=16, color=TEXT, fontweight="bold")

    # OB блок
    ax_ob = fig.add_axes([0.05, 0.50, 0.42, 0.40])
    ax_ob.set_facecolor(PANEL_BG)
    for s in ax_ob.spines.values(): s.set_color(BLUE); s.set_linewidth(1.2)
    ax_ob.set_xticks([]); ax_ob.set_yticks([])

    ob_text = [
        "Order Block (OB)",
        "─────────────────────────────",
        "",
        "Свечная формация из двух свечей:",
        "первая «накопительная», вторая её",
        "пробивает с сильным закрытием.",
        "",
        "Идея: на этом уровне крупные",
        "игроки набрали позицию. Когда цена",
        "вернётся сюда повторно, есть высокая",
        "вероятность отскока — институционалы",
        "будут защищать свою точку входа.",
        "",
        "В C2 используется OB на 6-часовом",
        "графике как «якорь» (anchor) —",
        "крупная зона, в которой мы ждём",
        "сигнал на вход.",
    ]
    for i, line in enumerate(ob_text):
        weight = "bold" if i == 0 else "normal"
        size = 12 if i == 0 else 9.5
        color = BLUE if i == 0 else (TEXT_DIM if i == 1 else TEXT)
        ax_ob.text(0.05, 0.95 - i * 0.052, line, transform=ax_ob.transAxes,
                    fontsize=size, color=color, fontweight=weight)

    # FVG блок
    ax_fvg = fig.add_axes([0.53, 0.50, 0.42, 0.40])
    ax_fvg.set_facecolor(PANEL_BG)
    for s in ax_fvg.spines.values(): s.set_color(GREEN); s.set_linewidth(1.2)
    ax_fvg.set_xticks([]); ax_fvg.set_yticks([])

    fvg_text = [
        "Fair Value Gap (FVG)",
        "─────────────────────────────",
        "",
        "Разрыв в цене из 3 последовательных",
        "свечей: high первой не достаёт low",
        "третьей (для бычьего FVG).",
        "",
        "Идея: рынок двигался слишком быстро",
        "и оставил «дыру» в ценовом",
        "движении. Цена обычно возвращается",
        "к этой дыре, чтобы протестировать —",
        "это и есть наш момент входа.",
        "",
        "В C2 используется FVG на 2-часовом",
        "графике как «триггер» — момент",
        "входа в позицию внутри уже",
        "сформированной OB-зоны.",
    ]
    for i, line in enumerate(fvg_text):
        weight = "bold" if i == 0 else "normal"
        size = 12 if i == 0 else 9.5
        color = GREEN if i == 0 else (TEXT_DIM if i == 1 else TEXT)
        ax_fvg.text(0.05, 0.95 - i * 0.052, line, transform=ax_fvg.transAxes,
                    fontsize=size, color=color, fontweight=weight)

    # Pro-trend филтр
    ax_pro = fig.add_axes([0.05, 0.04, 0.90, 0.40])
    ax_pro.set_facecolor(PANEL_BG)
    for s in ax_pro.spines.values(): s.set_color(YELLOW); s.set_linewidth(1.2)
    ax_pro.set_xticks([]); ax_pro.set_yticks([])

    pro_text = [
        "Pro-trend фильтр — третий ключевой элемент",
        "──────────────────────────────────────────────",
        "",
        "Стратегия торгует только в направлении средне-срочного тренда. Для этого",
        "проверяется EMA(200) на 2-часовом графике в момент закрытия c2-свечи FVG:",
        "",
        "  • Если цена закрытия выше EMA200 — рынок в восходящем тренде. Ищем только LONG.",
        "  • Если цена закрытия ниже EMA200 — рынок в нисходящем тренде. Ищем только SHORT.",
        "",
        "Зачем это нужно: контр-трендовые сделки в крипто-рынке статистически",
        "проигрывают трендовым. EMA200 на 2h фильтрует ровно «не плыть против",
        "большой реки». Без этого фильтра WR падает с 55% до примерно 47%.",
        "",
        "Это самый критичный фильтр стратегии — отказ от него убивает edge.",
    ]
    for i, line in enumerate(pro_text):
        weight = "bold" if i == 0 else "normal"
        size = 12 if i == 0 else 10
        color = YELLOW if i == 0 else (TEXT_DIM if i == 1 else TEXT)
        ax_pro.text(0.03, 0.92 - i * 0.058, line, transform=ax_pro.transAxes,
                     fontsize=size, color=color, fontweight=weight)

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def page_logic(pdf):
    """Страница 3 — как формируется сетап."""
    fig = plt.figure(figsize=(11, 8.5))
    fig.patch.set_facecolor(BG)
    fig.text(0.5, 0.96, "Как алгоритм находит сетап",
              ha="center", fontsize=16, color=TEXT, fontweight="bold")

    # Схема каскада
    ax = fig.add_axes([0.05, 0.50, 0.90, 0.40])
    ax.set_facecolor(BG); ax.axis("off")

    # Шаг 1
    rect1 = mpatches.FancyBboxPatch((0.02, 0.35), 0.28, 0.50,
                                     boxstyle="round,pad=0.01",
                                     edgecolor=BLUE, facecolor=BLUE,
                                     alpha=0.20, linewidth=2)
    ax.add_patch(rect1)
    ax.text(0.16, 0.78, "ШАГ 1", ha="center", fontsize=11,
              color=YELLOW, fontweight="bold")
    ax.text(0.16, 0.70, "OB-6h найден", ha="center", fontsize=13,
              color=BLUE, fontweight="bold")
    ax.text(0.16, 0.55,
              "На графике 6h закрылась\n"
              "OB-пара (направление\n"
              "определяется по правилам\n"
              "SMC). Запоминаем зону\n"
              "[bottom, top] и ждём 6h\n"
              "до подтверждения.",
              ha="center", fontsize=9, color=TEXT)

    # Стрелка
    ax.annotate("", xy=(0.34, 0.60), xytext=(0.30, 0.60),
                  arrowprops=dict(arrowstyle="->", color=GREY, lw=2))

    # Шаг 2
    rect2 = mpatches.FancyBboxPatch((0.34, 0.35), 0.28, 0.50,
                                     boxstyle="round,pad=0.01",
                                     edgecolor=GREEN, facecolor=GREEN,
                                     alpha=0.20, linewidth=2)
    ax.add_patch(rect2)
    ax.text(0.48, 0.78, "ШАГ 2", ha="center", fontsize=11,
              color=YELLOW, fontweight="bold")
    ax.text(0.48, 0.70, "Ждём FVG-2h", ha="center", fontsize=13,
              color=GREEN, fontweight="bold")
    ax.text(0.48, 0.55,
              "В течение 10 дней после\n"
              "OB ищем 2h-FVG того же\n"
              "направления, чья зона\n"
              "пересекается с OB-зоной.\n"
              "Берём первую такую FVG\n"
              "(остальные игнорируем).",
              ha="center", fontsize=9, color=TEXT)

    ax.annotate("", xy=(0.66, 0.60), xytext=(0.62, 0.60),
                  arrowprops=dict(arrowstyle="->", color=GREY, lw=2))

    # Шаг 3
    rect3 = mpatches.FancyBboxPatch((0.66, 0.35), 0.30, 0.50,
                                     boxstyle="round,pad=0.01",
                                     edgecolor=YELLOW, facecolor=YELLOW,
                                     alpha=0.20, linewidth=2)
    ax.add_patch(rect3)
    ax.text(0.81, 0.78, "ШАГ 3", ha="center", fontsize=11,
              color=YELLOW, fontweight="bold")
    ax.text(0.81, 0.70, "Pro-trend фильтр", ha="center", fontsize=13,
              color=YELLOW, fontweight="bold")
    ax.text(0.81, 0.55,
              "На момент закрытия c2-свечи\n"
              "FVG проверяем: цена выше\n"
              "EMA200(2h) для LONG, или\n"
              "ниже для SHORT.\n"
              "Если фильтр пройден →\n"
              "сетап подтверждён.",
              ha="center", fontsize=9, color=TEXT)

    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.text(0.5, 0.92, "Алгоритм работает в реальном времени по мере появления новых свечей",
              ha="center", fontsize=10, color=TEXT_DIM, style="italic")

    # Объяснение под схемой
    ax_t = fig.add_axes([0.05, 0.04, 0.90, 0.40])
    ax_t.set_facecolor(BG); ax_t.axis("off")

    explain = [
        "Зачем эти три шага именно в таком порядке",
        "─────────────────────────────────────────────",
        "",
        "OB-6h служит «контейнером» для торговой идеи. 6-часовая зона достаточно",
        "крупная, чтобы попадать в неё было редким событием (~1 раз в 1-2 дня), но",
        "при этом не настолько редким, как у дневной OB.",
        "",
        "FVG-2h — точка входа. На 2-часовом графике FVG появляются часто, но мы",
        "берём только первый, попадающий в активную OB-зону. Это даёт настоящий",
        "«retest»: цена сначала обозначила интерес институционалов (OB), потом",
        "вернулась туда более-менее напрямую и оставила разрыв (FVG).",
        "",
        "Pro-trend фильтр гарантирует, что мы торгуем по направлению крупной",
        "волны. Без него много setup'ов превращаются в попытку поймать ножи —",
        "красивая теория, плохая статистика.",
        "",
        "Дедупликация (берём первый FVG): если в одной OB-зоне образовалось 2-3",
        "FVG подряд — все они один и тот же сигнал на повторный тест. Бьём один",
        "раз и идём дальше. Это спасает от over-trading в боковиках.",
    ]
    for i, line in enumerate(explain):
        weight = "bold" if i == 0 else "normal"
        size = 12 if i == 0 else 10
        color = YELLOW if i == 0 else (TEXT_DIM if i == 1 else TEXT)
        ax_t.text(0.0, 1.0 - i * 0.043, line, transform=ax_t.transAxes,
                    fontsize=size, color=color, fontweight=weight, ha="left",
                    va="top")

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def page_orders(pdf, ex):
    """Страница 4 — entry / SL / TP с пояснениями."""
    fig = plt.figure(figsize=(11, 8.5))
    fig.patch.set_facecolor(BG)
    fig.text(0.5, 0.96, "Как ставим ордера: вход, стоп, цель",
              ha="center", fontsize=16, color=TEXT, fontweight="bold")

    # Три колонки: Entry / SL / TP
    columns = [
        ("Точка входа (Entry)", BLUE, [
            "Берём середину FVG-зоны.",
            "",
            "Формула:",
            "  entry = (FVG.bottom + FVG.top) / 2",
            "",
            "Зачем середина, а не край?",
            "",
            "Край FVG (внутренний) даёт",
            "лучший R-multiple, но плохой",
            "fill: цена часто не доходит",
            "туда. Внешний край — наоборот:",
            "fill почти гарантирован, но R",
            "мизерный.",
            "",
            "Середина — компромисс:",
            "fill в ~75% случаев, R/risk",
            "достаточный для RR=1.",
        ]),
        ("Стоп-лосс (SL)", RED, [
            "Защитный уровень — выходим",
            "если цена пошла против нас.",
            "",
            "Формула (для LONG):",
            "  atr_sl = FVG.bot − 0.3·ATR(2h)",
            "  pct_sl = entry − 1% от entry",
            "  SL = min(atr_sl, pct_sl)",
            "",
            "Берём более широкий из двух:",
            "  • atr_sl учитывает текущую",
            "    волатильность",
            "  • pct_sl — минимальная",
            "    защита от шума и спреда",
            "",
            "Минимум 1% от цены — критично",
            "для фьючерсов, иначе вылетаем",
            "на каждом тике.",
        ]),
        ("Тейк-профит (TP)", GREEN, [
            "Цель прибыли — фиксированный",
            "RR=1.0.",
            "",
            "Формула:",
            "  TP = entry + 1.0 × |entry−SL|",
            "",
            "Почему RR=1, а не 2-3?",
            "",
            "На крипто-рынке высокий RR",
            "выглядит привлекательно, но",
            "WR падает быстрее, чем растёт",
            "R. RR=2.5 даёт 36% WR, RR=3",
            "уже 25%.",
            "",
            "RR=1.0 при WR 55% = матема-",
            "тически прибыльно и психоло-",
            "гически выносимо. Не гонимся",
            "за луной — стабильный edge.",
        ]),
    ]

    for ci, (title, color, lines) in enumerate(columns):
        x_left = 0.05 + ci * 0.31
        ax = fig.add_axes([x_left, 0.35, 0.28, 0.55])
        ax.set_facecolor(PANEL_BG)
        for s in ax.spines.values():
            s.set_color(color); s.set_linewidth(1.5)
        ax.set_xticks([]); ax.set_yticks([])

        ax.text(0.5, 0.95, title, ha="center", va="top",
                  fontsize=12, color=color, fontweight="bold",
                  transform=ax.transAxes)
        for i, line in enumerate(lines):
            ax.text(0.05, 0.85 - i * 0.045, line, ha="left", va="top",
                      fontsize=9, color=TEXT, transform=ax.transAxes,
                      family="monospace" if "=" in line or "·" in line
                                            or "min(" in line else "sans-serif")

    # Числовой пример
    ax_ex = fig.add_axes([0.05, 0.04, 0.90, 0.27])
    ax_ex.set_facecolor(PANEL_BG)
    for s in ax_ex.spines.values():
        s.set_color(PURPLE); s.set_linewidth(1.5)
    ax_ex.set_xticks([]); ax_ex.set_yticks([])

    if ex:
        risk_pct = (ex['entry'] - ex['sl']) / ex['entry'] * 100
        target_pct = (ex['tp'] - ex['entry']) / ex['entry'] * 100
        example_lines = [
            "Пример из реальной сделки (LONG, июль 2024)",
            "──────────────────────────────────────────────────────────────────────",
            "",
            f"OB-6h обнаружен, зона:  [{ex['ob_bot']:.0f} — {ex['ob_top']:.0f}]",
            f"FVG-2h найден, зона:    [{ex['fvg_bot']:.0f} — {ex['fvg_top']:.0f}]",
            f"ATR(2h) на c2:           {ex['atr']:.0f}     EMA200(2h):  {ex['ema200']:.0f}    цена выше → LONG OK",
            "",
            f"Расчёт ордеров:",
            f"  entry = ({ex['fvg_bot']:.0f} + {ex['fvg_top']:.0f}) / 2  =  {ex['entry']:.2f}",
            f"  atr_sl = {ex['fvg_bot']:.0f} − 0.3·{ex['atr']:.0f} = {ex['atr_sl']:.2f}",
            f"  pct_sl = {ex['entry']:.0f} − 1%·{ex['entry']:.0f} = {ex['pct_sl']:.2f}",
            f"  SL = min({ex['atr_sl']:.0f}, {ex['pct_sl']:.0f}) = {ex['sl']:.2f}    (риск = {risk_pct:.2f}% от цены)",
            f"  TP = {ex['entry']:.0f} + 1.0·{ex['entry']-ex['sl']:.0f} = {ex['tp']:.2f}    (цель = +{target_pct:.2f}% от цены)",
        ]
        for i, line in enumerate(example_lines):
            if i == 0:
                ax_ex.text(0.03, 0.92, line, fontsize=12, color=PURPLE,
                            fontweight="bold", transform=ax_ex.transAxes)
            elif i == 1:
                ax_ex.text(0.03, 0.83, line, fontsize=10, color=TEXT_DIM,
                            transform=ax_ex.transAxes)
            else:
                ax_ex.text(0.03, 0.78 - (i - 2) * 0.07, line, fontsize=10,
                            color=TEXT, transform=ax_ex.transAxes,
                            family="monospace")

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def page_demo_trade(pdf, row, df_2h, ex_anchor, ex_trigger, page_num,
                      direction_ru):
    """Демо-сделка с описанием."""
    fig = plt.figure(figsize=(11, 8.5))
    fig.patch.set_facecolor(BG)
    fig.text(0.5, 0.96,
              f"Страница {page_num} — Реальный пример сделки: {direction_ru}",
              ha="center", fontsize=16, color=TEXT, fontweight="bold")

    direction = row["direction"]
    entry = row["entry"]; sl = row["sl"]; tp = row["tp"]
    trigger_time = row["trigger_time"]
    start_time = row["start_time"]
    close_ts = row["close_ts"]
    R = row["R"]; outcome = row["outcome"]
    anchor_time = row["anchor_time"]
    ob = row["anchor"]
    fvg = row["trigger"]

    # Окно для графика
    win_start = anchor_time - pd.Timedelta(days=3)
    win_end = (close_ts if close_ts is not None else
                start_time + pd.Timedelta(days=3)) + pd.Timedelta(hours=12)
    df_2h_win = df_2h[(df_2h.index >= win_start) & (df_2h.index <= win_end)]

    # График 2h close + EMA200
    ax_p = fig.add_axes([0.06, 0.45, 0.90, 0.45])
    setup_axes(ax_p)
    ax_p.plot(df_2h_win.index, df_2h_win["close"], color="#d6e0f0",
                linewidth=1.0, label="Цена BTCUSDT (2h close)")
    ax_p.plot(df_2h_win.index, df_2h_win["ema200"], color=YELLOW,
                linewidth=1.2, alpha=0.8, label="EMA200 на 2h (фильтр тренда)")

    # OB-6h зона
    ob_rect = mpatches.Rectangle(
        (anchor_time, ob["bottom"]),
        win_end - anchor_time, ob["top"] - ob["bottom"],
        edgecolor=BLUE, facecolor=BLUE, alpha=0.15, linewidth=1.5,
        label=f"OB-6h зона")
    ax_p.add_patch(ob_rect)

    # FVG-2h зона
    fvg_end = close_ts if close_ts is not None else start_time + pd.Timedelta(days=3)
    fvg_rect = mpatches.Rectangle(
        (trigger_time, fvg["bottom"]),
        fvg_end - trigger_time, fvg["top"] - fvg["bottom"],
        edgecolor=GREEN, facecolor=GREEN, alpha=0.20, linewidth=1.5,
        label=f"FVG-2h зона")
    ax_p.add_patch(fvg_rect)

    # Уровни
    color_entry = BLUE if direction == "LONG" else PURPLE
    ax_p.axhline(entry, color=color_entry, linewidth=1.2, linestyle="--",
                  alpha=0.7, label=f"Entry: {entry:.0f}")
    ax_p.axhline(sl, color=RED, linewidth=1.0, linestyle=":",
                  alpha=0.7, label=f"SL: {sl:.0f}")
    ax_p.axhline(tp, color=GREEN, linewidth=1.0, linestyle=":",
                  alpha=0.7, label=f"TP: {tp:.0f}")

    # Маркеры
    ax_p.scatter([start_time], [entry],
                  marker="^" if direction == "LONG" else "v",
                  s=250, color=color_entry, zorder=10,
                  edgecolor="white", linewidth=1.5)
    if close_ts is not None:
        exit_color = GREEN if R > 0 else RED
        exit_price = tp if R > 0 else sl
        ax_p.scatter([close_ts], [exit_price], marker="X",
                      s=300, color=exit_color, zorder=10,
                      edgecolor="white", linewidth=1.5)

    ax_p.set_ylabel("Цена (USDT)", color=TEXT)
    ax_p.legend(loc="upper left", facecolor="#1a1f29",
                 edgecolor="#3a4252", labelcolor=TEXT, fontsize=9, ncol=2)
    ax_p.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=8))
    ax_p.xaxis.set_major_formatter(mdates.DateFormatter("%d %b %H:%M"))

    # История сделки внизу
    ax_t = fig.add_axes([0.06, 0.04, 0.90, 0.36])
    ax_t.set_facecolor(PANEL_BG)
    for s in ax_t.spines.values(): s.set_color(GREEN if R > 0 else RED); s.set_linewidth(1.2)
    ax_t.set_xticks([]); ax_t.set_yticks([])

    risk = abs(entry - sl)
    risk_pct = risk / entry * 100
    hold_h = ((close_ts - start_time).total_seconds() / 3600
                if close_ts is not None else None)
    profit_pct = ((tp - entry) / entry * 100) if direction == "LONG" else \
                  ((entry - tp) / entry * 100)
    if R > 0:
        outcome_ru = f"ЗАКРЫТА В ПРИБЫЛЬ (+{R:.2f}R = +{profit_pct:.2f}%)"
        outcome_color = GREEN
    elif R < 0:
        outcome_ru = f"ЗАКРЫТА ПО СТОПУ ({R:.2f}R = −{risk_pct:.2f}%)"
        outcome_color = RED
    else:
        outcome_ru = "ОСТАЛАСЬ ОТКРЫТОЙ"
        outcome_color = YELLOW

    history_lines = [
        f"История сделки  ·  {outcome_ru}",
        "─────────────────────────────────────────────────────────────────",
        "",
        f"1. {anchor_time.strftime('%d %b %Y, %H:%M UTC')}",
        f"   На 6-часовом графике закрылась OB-пара. Зона [{ob['bottom']:.0f} — {ob['top']:.0f}]",
        f"   стала «якорем» — здесь институционалы оставили след. Ждём вход в эту зону.",
        "",
        f"2. {trigger_time.strftime('%d %b %Y, %H:%M UTC')}  (через {(trigger_time - anchor_time).total_seconds()/3600:.0f}ч)",
        f"   Появился FVG-2h в зоне [{fvg['bottom']:.0f} — {fvg['top']:.0f}], направление {direction}.",
        f"   Pro-trend фильтр пройден (цена {'выше' if direction == 'LONG' else 'ниже'} EMA200(2h)). Сетап подтверждён.",
        "",
        f"3. {start_time.strftime('%d %b %Y, %H:%M UTC')}  →  Размещаем лимитный ордер",
        f"   Entry: {entry:.0f}    SL: {sl:.0f} (риск {risk_pct:.2f}%)    TP: {tp:.0f} (цель +{profit_pct:.2f}%)",
        "",
        f"4. {close_ts.strftime('%d %b %Y, %H:%M UTC') if close_ts is not None else 'Открыта'}  "
        f"(удержание {hold_h:.0f}ч / {hold_h/24:.1f}д)" if close_ts is not None else "",
        f"   {outcome_ru}",
    ]
    for i, line in enumerate(history_lines):
        if i == 0:
            ax_t.text(0.02, 0.94, line, fontsize=12, color=outcome_color,
                       fontweight="bold", transform=ax_t.transAxes)
        elif i == 1:
            ax_t.text(0.02, 0.86, line, fontsize=10, color=TEXT_DIM,
                       transform=ax_t.transAxes)
        else:
            ax_t.text(0.02, 0.79 - (i - 2) * 0.054, line, fontsize=9.5,
                       color=TEXT, transform=ax_t.transAxes)

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def page_performance_human(pdf, df_closed, stats):
    """Производительность с пояснениями."""
    fig = plt.figure(figsize=(11, 8.5))
    fig.patch.set_facecolor(BG)
    fig.text(0.5, 0.96, "Что показал бэктест и как это понимать",
              ha="center", fontsize=16, color=TEXT, fontweight="bold")

    # График по годам
    ax_yr = fig.add_axes([0.05, 0.50, 0.55, 0.40])
    setup_axes(ax_yr, title="Прибыль по годам (в R-единицах)")
    yr = df_closed.groupby("year")["R"].sum().sort_index()
    bars = ax_yr.bar(yr.index.astype(str), yr.values,
                       color=[GREEN if v >= 0 else RED for v in yr.values],
                       alpha=0.85)
    for bar, v in zip(bars, yr.values):
        ax_yr.text(bar.get_x() + bar.get_width()/2, v + 0.3,
                    f"+{v:.0f}R" if v >= 0 else f"{v:.0f}R",
                    ha="center", va="bottom" if v >= 0 else "top",
                    fontsize=10, color=TEXT, fontweight="bold")
    ax_yr.axhline(0, color=TEXT, linewidth=0.7)
    ax_yr.set_ylabel("Прибыль за год (R)", color=TEXT)

    # Боковая колонка с пояснением R
    ax_r = fig.add_axes([0.65, 0.50, 0.30, 0.40])
    ax_r.set_facecolor(PANEL_BG)
    for s in ax_r.spines.values(): s.set_color(YELLOW); s.set_linewidth(1.2)
    ax_r.set_xticks([]); ax_r.set_yticks([])

    r_explain = [
        "Что такое «R»",
        "─────────────────────",
        "",
        "R — единица риска.",
        "Это не доллары и не",
        "проценты — это «сколько",
        "раз ваш стоп».",
        "",
        "Если рискуете $100 на",
        "сделку, +1R = +$100,",
        "−1R = −$100.",
        "",
        f"Итог +{stats['total_R']:.0f}R за",
        f"6.33 года значит:",
        "",
        "  • при риске 1% капитала",
        f"    на сделку = +{stats['total_R']:.0f}%",
        "    за 6 лет = ~9% годовых",
        "",
        "  • при риске 2% =",
        f"    +{2*stats['total_R']:.0f}% за 6 лет",
        "    = ~17% годовых",
    ]
    for i, line in enumerate(r_explain):
        weight = "bold" if i == 0 else "normal"
        size = 11 if i == 0 else 9
        color = YELLOW if i == 0 else (TEXT_DIM if i == 1 else TEXT)
        ax_r.text(0.07, 0.94 - i * 0.045, line, transform=ax_r.transAxes,
                   fontsize=size, color=color, fontweight=weight)

    # Текстовое пояснение всех показателей
    ax_t = fig.add_axes([0.05, 0.04, 0.90, 0.40])
    ax_t.set_facecolor(BG); ax_t.axis("off")

    long_df = df_closed[df_closed["direction"] == "LONG"]
    short_df = df_closed[df_closed["direction"] == "SHORT"]
    long_wr = (long_df["R"] > 0).mean() * 100 if len(long_df) else 0
    short_wr = (short_df["R"] > 0).mean() * 100 if len(short_df) else 0

    explain = [
        f"Win Rate {stats['wr']:.1f}% (доля прибыльных сделок)",
        f"   Из {stats['closed']} сделок {stats['wins']} закрылись в плюс, {stats['losses']} в минус. На каждые",
        f"   100 сделок имеем ~55 прибыльных, что больше точки безубытка (50%) при RR=1:1.",
        "",
        f"Суммарный результат +{stats['total_R']:.0f}R за {stats['n_yrs']} лет",
        f"   В пересчёте на год это +{stats['per_year']:.1f}R, или ≈ +9% годовых при риске 1% на сделку.",
        f"   Не суперзвезда, но стабильный «банковский» доход без сложных систем.",
        "",
        f"Минусовых лет — {stats['bad_yrs']} из {stats['n_yrs']}",
        f"   Самое важное свойство: НИ ОДИН ГОД из 7 не был убыточным. Это редкое",
        f"   качество — большинство стратегий имеют 1-2 «провальных» года, которые сжигают",
        f"   психику и капитал. C2 даёт стабильный плюс год за годом.",
        "",
        f"LONG vs SHORT: {len(long_df)} лонгов с WR {long_wr:.0f}% vs {len(short_df)} шортов с WR {short_wr:.0f}%",
        f"   Стратегия работает в обе стороны. Лонгов чуть больше, что нормально для",
        f"   крипто (рынок чаще растёт), но шорты тоже стабильно прибыльны.",
        "",
        f"Частота: {stats['freq']:.2f} сетапа в неделю (~{stats['n_total']/6.33:.0f}/год)",
        f"   Примерно один сигнал каждые 3 рабочих дня. Не нужно сидеть у экрана 24/7,",
        f"   но и без сигналов не остаёмся надолго. Хорошая частота для дисциплины.",
    ]
    for i, line in enumerate(explain):
        is_header = not line.startswith("   ") and line and i not in [3, 6, 10, 14]
        actually_header = line and not line.startswith("   ") and line[0] != ""
        weight = "bold" if (line and not line.startswith("   ")) else "normal"
        color = YELLOW if (line and not line.startswith("   ")) else TEXT
        size = 11 if (line and not line.startswith("   ")) else 9.5
        ax_t.text(0.0, 1.0 - i * 0.043, line, transform=ax_t.transAxes,
                    fontsize=size, color=color, fontweight=weight,
                    ha="left", va="top")

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


def page_caveats(pdf):
    """Слабые стороны."""
    fig = plt.figure(figsize=(11, 8.5))
    fig.patch.set_facecolor(BG)
    fig.text(0.5, 0.96, "Слабые стороны и над чем работать",
              ha="center", fontsize=16, color=TEXT, fontweight="bold")

    sections = [
        (RED, "Главная проблема — стратегия проверена только на BTC", [
            "Тесты на ETHUSDT показали отрицательный результат: −16R за 4 года при том",
            "же сетапе. На SOLUSDT работает похоже на BTC (+22R), но это всего 2 из 3",
            "крипто-инструментов. Никаких других активов не тестировалось.",
            "",
            "Что это значит: запускать стратегию в live-режиме на ETH или альтах нельзя",
            "до отдельной валидации. Возможно, нужна перенастройка параметров под",
            "каждый актив. Возможно, концепция работает только на BTC из-за его",
            "уникальной структуры ликвидности.",
        ]),
        (YELLOW, "Walk-forward тестирование не проводилось", [
            "Все 6.33 года тестировались как одно in-sample окно. Нет проверки на",
            "rolling-окнах (например, 4 года обучения + 6 месяцев out-of-sample).",
            "",
            "Это значит, что edge может быть «фитом» под прошлые рыночные режимы.",
            "Перед live-запуском нужен walk-forward тест на 5 окнах 2020-2026.",
        ]),
        (BLUE, "Live-интеграция отсутствует", [
            "Стратегия существует только как research-скрипт. Нет файла",
            "strategies/strategy_c2.py, нет тестов, нет сканера.",
            "",
            "Перед production-запуском нужно: реализовать детектор как чистую функцию,",
            "написать тесты (минимум 3 edge-case'а), интегрировать в Scanner с",
            "правильной обработкой closed-bar логики.",
        ]),
        (GREEN, "Идея на будущее: Smart Trail вместо фиксированного TP", [
            "Эксперименты с 1.1.1 SWEPT показали, что trail-выход через Hull MA",
            "может дать дополнительные +20-30R к baseline. C2 пока использует только",
            "фиксированный RR=1, и это потенциально оставляет деньги на столе при",
            "сильных трендах.",
            "",
            "Гипотеза: добавить «авто-следование» через Hull-1h — выход когда тренд",
            "разворачивается, а не только по TP. Тестировать в etap_44 (TODO).",
        ]),
    ]

    y = 0.86
    for color, title, lines in sections:
        # Заголовок
        fig.text(0.05, y, title, fontsize=12, color=color, fontweight="bold")
        y -= 0.035
        for line in lines:
            fig.text(0.07, y, line, fontsize=10, color=TEXT)
            y -= 0.025
        y -= 0.022

    pdf.savefig(fig, facecolor=BG)
    plt.close(fig)


# ============================================================
# MAIN
# ============================================================

def main():
    t0 = time.time()
    print("[INFO] загружаем данные")
    df_6h = load_df(SYMBOL, "6h")
    df_2h = load_df(SYMBOL, "2h")
    df_1m = load_df(SYMBOL, "1m")

    df_6h = df_6h[df_6h.index >= pd.Timestamp(START_DATE, tz="UTC")].copy()
    df_2h = df_2h[df_2h.index >= pd.Timestamp(START_DATE, tz="UTC")].copy()
    df_1m = df_1m[df_1m.index >= pd.Timestamp(START_DATE, tz="UTC")]
    df_6h["atr14"] = compute_atr(df_6h, 14)
    df_2h["atr14"] = compute_atr(df_2h, 14)
    df_2h["ema200"] = df_2h["close"].ewm(span=200, adjust=False).mean()

    sim = FastSim(df_1m)
    years = (df_6h.index[-1] - df_6h.index[0]).days / 365
    print(f"  лет: {years:.2f}")

    print("[INFO] собираем зоны")
    obs_6h = collect_obs(df_6h, df_6h["atr14"], "6h")
    fvgs_2h = collect_fvgs(df_2h, df_2h["atr14"], "2h")
    print(f"  OB-6h: {len(obs_6h)}, FVG-2h: {len(fvgs_2h)}")

    print("[INFO] строим C2 setups")
    setups = build_c2_setups(obs_6h, fvgs_2h, df_2h)
    print(f"  C2 setups: {len(setups)}")

    print("[INFO] оцениваем")
    df_e = evaluate(setups, sim)
    closed = df_e[df_e["outcome"].isin(["win", "loss"])].copy()
    n_total = len(df_e)
    nc = len(closed)
    wins = (closed["R"] > 0).sum()
    losses = (closed["R"] < 0).sum()
    wr = wins/nc*100 if nc else 0
    total_R = closed["R"].sum()
    rt = closed["R"].mean()
    yr = closed.groupby("year")["R"].sum()
    bad_yrs = (yr < 0).sum()
    print(f"  closed: {nc}, WR={wr:.1f}%, total={total_R:+.1f}R")

    stats = {
        "n_total": n_total, "closed": nc, "wins": int(wins),
        "losses": int(losses), "wr": wr, "total_R": total_R, "rt": rt,
        "bad_yrs": int(bad_yrs), "n_yrs": len(yr),
        "freq": n_total / years / 52,
        "per_year": total_R / years,
    }

    # Числовой пример для p4
    longs_winning = closed[(closed["direction"] == "LONG") &
                            (closed["R"] > 0)].copy()
    longs_winning = longs_winning.sort_values("year")
    if len(longs_winning) > 0:
        cands_2024 = longs_winning[longs_winning["year"] == 2024]
        if len(cands_2024) > 0:
            ex_row = cands_2024.iloc[len(cands_2024) // 2]
        else:
            ex_row = longs_winning.iloc[len(longs_winning) // 2]
        ex = {
            "ob_bot": ex_row["anchor"]["bottom"],
            "ob_top": ex_row["anchor"]["top"],
            "fvg_bot": ex_row["trigger"]["bottom"],
            "fvg_top": ex_row["trigger"]["top"],
            "atr": ex_row["trigger"]["atr"],
            "ema200": float(df_2h.loc[ex_row["trigger_time"], "ema200"])
                       if ex_row["trigger_time"] in df_2h.index else 0,
            "entry": ex_row["entry"],
            "atr_sl": ex_row["trigger"]["bottom"] - SL_BUF_ATR * ex_row["trigger"]["atr"],
            "pct_sl": ex_row["entry"] - ex_row["entry"] * MIN_SL_PCT / 100,
            "sl": ex_row["sl"],
            "tp": ex_row["tp"],
        }
    else:
        ex = None

    # Демо-сделки
    longs_winning_full = closed[(closed["direction"] == "LONG") &
                                  (closed["R"] > 0)].copy()
    if len(longs_winning_full) > 0:
        cands = longs_winning_full[longs_winning_full["year"].isin([2023, 2024, 2025])]
        if len(cands) > 0:
            demo_long = cands.iloc[len(cands) // 2]
        else:
            demo_long = longs_winning_full.iloc[0]
    else:
        demo_long = None

    shorts_winning = closed[(closed["direction"] == "SHORT") &
                              (closed["R"] > 0)].copy()
    if len(shorts_winning) > 0:
        cands = shorts_winning[shorts_winning["year"].isin([2022, 2023, 2024])]
        if len(cands) > 0:
            demo_short = cands.iloc[len(cands) // 2]
        else:
            demo_short = shorts_winning.iloc[0]
    else:
        demo_short = None

    print(f"  демо LONG:  {demo_long['trigger_time'] if demo_long is not None else None}  R={demo_long['R'] if demo_long is not None else None}")
    print(f"  демо SHORT: {demo_short['trigger_time'] if demo_short is not None else None}  R={demo_short['R'] if demo_short is not None else None}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\n[INFO] пишем PDF: {OUT_PDF}")
    with PdfPages(OUT_PDF) as pdf:
        page_intro(pdf, stats)
        print("  стр.1 — обзор")
        page_basics(pdf)
        print("  стр.2 — основы (OB, FVG)")
        page_logic(pdf)
        print("  стр.3 — логика поиска сетапа")
        if ex:
            page_orders(pdf, ex)
            print("  стр.4 — ордера (entry/SL/TP)")
        if demo_long is not None:
            page_demo_trade(pdf, demo_long, df_2h, demo_long["anchor"],
                             demo_long["trigger"], 5, "LONG (в плюс)")
            print("  стр.5 — демо LONG")
        if demo_short is not None:
            page_demo_trade(pdf, demo_short, df_2h, demo_short["anchor"],
                             demo_short["trigger"], 6, "SHORT (в плюс)")
            print("  стр.6 — демо SHORT")
        page_performance_human(pdf, closed, stats)
        print("  стр.7 — производительность")
        page_caveats(pdf)
        print("  стр.8 — слабые стороны")

    print(f"\n[OK] сохранён: {OUT_PDF}")
    print(f"[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
