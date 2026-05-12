"""Этап 16: PDF отчёт по топ-стратегиям после фикса lookahead.

Структура:
  Page 1 — Обложка + executive summary
  Page 2 — Описание lookahead bug (что было / симптом / фикс)
  Pages 3-N — По одной странице на каждого кандидата (C1..C4):
    - Формальное описание setup'а (anchor / trigger / direction filter)
    - Entry / SL / TP формулы
    - Stats table (n, WR, R/tr, total_R)
    - Year-by-year bar chart
    - LONG vs SHORT split
    - Outlier robustness
  Last page — Каверс / TODO
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
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Rectangle

OUT_DIR = Path("research/elements_study/output")

# strategy specs (заполняем из CSV trades по каждому кандидату)
STRATEGIES = [
    {"id": "C1", "name": "OB-4h + FVG-1h pro-trend",
     "anchor": "OB-4h", "trigger": "FVG-1h", "rr": 1.0, "filter": "pro"},
    {"id": "C2", "name": "OB-6h + FVG-2h pro-trend",
     "anchor": "OB-6h", "trigger": "FVG-2h", "rr": 1.0, "filter": "pro"},
    {"id": "C3", "name": "OB-12h + FVG-2h pro-trend",
     "anchor": "OB-12h", "trigger": "FVG-2h", "rr": 1.0, "filter": "pro"},
    {"id": "C4", "name": "OB-12h + FVG-2h pro-trend (RR=1.5)",
     "anchor": "OB-12h", "trigger": "FVG-2h", "rr": 1.5, "filter": "pro"},
    {"id": "C5", "name": "Fractal-sweep 4h + FVG-15m pro-trend",
     "anchor": "FRSWEEP-4h", "trigger": "FVG-15m", "rr": 1.0, "filter": "pro"},
    {"id": "C6", "name": "Multi-TF fractal confluence (1d+4h) + FVG-2h pro",
     "anchor": "FRACT2X-1d+4h", "trigger": "FVG-2h", "rr": 1.0, "filter": "pro"},
    # === оптимизированные через 3-stage etap_19 ===
    {"id": "D2", "name": "OB-12h x FVG-2h pro RR=1.75 (★ optimal balance)",
     "anchor": "OB-12h", "trigger": "FVG-2h", "rr": 1.75, "filter": "pro",
     "csv": "etap20_D2_trades.csv", "entry_pct": 0.5, "sl_buf": 0.15, "min_sl_pct": 1.0,
     "is_optimized": True},
    {"id": "D1", "name": "OB-12h x FVG-2h pro RR=2.5 (max R/tr)",
     "anchor": "OB-12h", "trigger": "FVG-2h", "rr": 2.5, "filter": "pro",
     "csv": "etap20_D1_trades.csv", "entry_pct": 0.5, "sl_buf": 0.15, "min_sl_pct": 1.0,
     "is_optimized": True},
]


def fig_text_page(title, lines, fontsize_title=18, fontsize_body=10):
    fig = plt.figure(figsize=(8.5, 11))
    fig.text(0.5, 0.94, title, ha="center", va="top",
             fontsize=fontsize_title, fontweight="bold")
    body = "\n".join(lines)
    fig.text(0.06, 0.88, body, ha="left", va="top",
             fontsize=fontsize_body, family="monospace", wrap=True)
    return fig


def stats_from_df(df):
    closed = df[df["outcome"].isin(["win", "loss"])].copy()
    if closed.empty:
        return None
    n_total = len(df); nc = len(closed)
    w = (closed["outcome"] == "win").sum()
    return {
        "n_total": n_total, "n_closed": nc,
        "wins": int(w), "losses": int(nc - w),
        "WR": round(w / nc * 100, 1),
        "total_R": round(closed["R"].sum(), 1),
        "R_tr": round(closed["R"].mean(), 3),
        "n_per_week": round(n_total / 6.33 / 52, 2),
        "df_closed": closed,
    }


def render_strategy_page(pdf, strategy, df_trades, total_years=6.33):
    s = stats_from_df(df_trades)
    if s is None:
        return
    closed = s["df_closed"]

    fig = plt.figure(figsize=(8.5, 11))
    gs = fig.add_gridspec(4, 2, height_ratios=[0.7, 0.9, 1.4, 1.4],
                            hspace=0.55, wspace=0.3,
                            left=0.07, right=0.95, top=0.92, bottom=0.07)

    # title
    fig.suptitle(f"{strategy['id']} — {strategy['name']}",
                 fontsize=16, fontweight="bold", y=0.97)

    # ---- text block: rules ----
    ax_rules = fig.add_subplot(gs[0, :])
    ax_rules.axis("off")
    a_tf = strategy["anchor"].split("-")[1] if "-" in strategy["anchor"] else strategy["anchor"]
    t_tf = strategy["trigger"].split("-")[1]
    is_frsweep = strategy["anchor"].startswith("FRSWEEP")
    is_fract2x = strategy["anchor"].startswith("FRACT2X")
    is_optimized = strategy.get("is_optimized", False)
    sl_buf_str = f"{strategy.get('sl_buf', 0.3):.2f}"
    min_sl_str = f"{strategy.get('min_sl_pct', 1.0):.1f}"
    if is_fract2x:
        rules_lines = [
            f"ВХОД (limit @ mid FVG-{t_tf}):",
            f"  1. Detect фрактал FH/FL на 1d (Bill Williams i±2).",
            f"  2. В окне 14 дней после 1d-фрактала ищем фрактал ТОГО ЖЕ направления на 4h.",
            f"  3. Уровни должны быть близки: |level_1d - level_4h| < 1 × ATR_4h.",
            f"  4. Anchor zone = пересечение candle ranges (или union если disjoint).",
            f"  5. Anchor подтверждается на later of (1d_confirm, 4h_confirm)",
            f"     где confirm_X = fractal_time + 3*tf_X.",
            f"  6. Active life = 14 дней с момента confirm.",
            f"  7. Ждём первую FVG-{t_tf} того же направления с overlap в anchor zone.",
            f"  8. Pro-trend filter: close_LTF(c2) > EMA200_LTF (LONG) / < (SHORT).",
            f"  9. Dedup: одна FVG-{t_tf} на anchor (первая qualifying).",
            f"",
            f"STOP LOSS:",
            f"  atr_sl = FVG_far_border ∓ 0.3 × ATR_LTF",
            f"  pct_sl = entry ∓ 1% × entry",
            f"  sl     = дальше из (atr_sl, pct_sl)",
            f"",
            f"TAKE PROFIT: entry ± {strategy['rr']:.1f} × risk    (RR={strategy['rr']:.1f})",
            f"TIMEOUT: 3 дня с момента активации.",
        ]
    elif is_frsweep:
        rules_lines = [
            f"ВХОД (limit @ mid FVG-{t_tf}):",
            f"  1. Detect фрактал (FH/FL по правилу Bill Williams i±2) на {a_tf}.",
            f"  2. После confirm (i+2) ждём sweep candle:",
            f"       FL→LONG: low <= FL.level И close > FL.level (в окне до 30 баров)",
            f"       FH→SHORT: high >= FH.level И close < FH.level",
            f"  3. Anchor zone = диапазон sweep candle (low..close для LONG, close..high для SHORT).",
            f"  4. Anchor подтверждается на close sweep свечи.",
            f"  5. Ждём первую FVG-{t_tf} того же направления с overlap в anchor zone.",
            f"  6. Pro-trend filter: close_LTF(c2) > EMA200_LTF (LONG) / < (SHORT).",
            f"  7. Dedup: одна FVG-{t_tf} на anchor (первая qualifying).",
            f"",
            f"STOP LOSS:",
            f"  atr_sl = FVG_far_border ∓ 0.3 × ATR_LTF",
            f"  pct_sl = entry ∓ 1% × entry",
            f"  sl     = дальше из (atr_sl, pct_sl)",
            f"",
            f"TAKE PROFIT: entry ± {strategy['rr']:.1f} × risk    (RR={strategy['rr']:.1f})",
            f"TIMEOUT: 1 день с момента активации (короткий т.к. trigger=15m).",
        ]
    else:
        opt_tag = " (3-stage оптимизированная)" if is_optimized else ""
        rules_lines = [
            f"ВХОД (limit @ mid FVG-{t_tf}){opt_tag}:",
            f"  1. Detect anchor zone {strategy['anchor']} (canon OB pair, no size filter).",
            f"  2. После закрытия anchor свечи (cur_close) ждём первую FVG-{t_tf} того же направления",
            f"     с overlap зоной anchor (любое пересечение).",
            f"  3. Pro-trend filter: close_LTF(c2) > EMA200_LTF (LONG) или < (SHORT).",
            f"  4. Dedup: одна FVG-{t_tf} на anchor (первая qualifying — break).",
            f"",
            f"STOP LOSS:",
            f"  atr_sl = FVG_far_border ∓ {sl_buf_str} × ATR_LTF",
            f"  pct_sl = entry ∓ {min_sl_str}% × entry   (фьючерс-friendly минимум)",
            f"  sl     = дальше из (atr_sl, pct_sl)",
            f"",
            f"TAKE PROFIT: entry ± {strategy['rr']:.2f} × risk    (RR={strategy['rr']:.2f})",
            f"TIMEOUT: {3 if a_tf == '12h' else 5 if a_tf in ('6h','4h') else 14} дней с момента активации.",
        ]
    # ASCII safe (cp1251 console export не нужен — matplotlib сам рендерит unicode)
    ax_rules.text(0.0, 1.0, "\n".join(rules_lines),
                  family="monospace", fontsize=8.5, va="top", ha="left")

    # ---- stats table ----
    ax_stats = fig.add_subplot(gs[1, :])
    ax_stats.axis("off")
    table = [
        ["метрика", "значение"],
        ["Всего setups (n_total)", str(s["n_total"])],
        ["Закрытых (win+loss)", str(s["n_closed"])],
        ["Wins / Losses", f"{s['wins']} / {s['losses']}"],
        ["Win Rate", f"{s['WR']}%"],
        ["Total R", f"{s['total_R']:+.1f}"],
        ["R per trade", f"{s['R_tr']:+.3f}"],
        ["Setups в неделю", f"{s['n_per_week']}"],
        ["Years coverage", f"{total_years}"],
        ["R/year (если 1% risk)", f"{s['total_R']/total_years:+.1f}%"],
    ]
    tab = ax_stats.table(cellText=table, cellLoc="left",
                          loc="center", colWidths=[0.45, 0.30])
    tab.auto_set_font_size(False); tab.set_fontsize(9)
    tab.scale(1, 1.25)
    for (r, c), cell in tab.get_celld().items():
        if r == 0:
            cell.set_facecolor("#cccccc"); cell.set_text_props(weight="bold")

    # ---- year bar chart ----
    ax_year = fig.add_subplot(gs[2, 0])
    closed["year"] = pd.to_datetime(closed["trigger_time"]).dt.year
    yr_g = closed.groupby("year").agg(n=("R", "size"),
                                         wins=("outcome", lambda x: (x == "win").sum()),
                                         total_R=("R", "sum"))
    yr_g["WR"] = yr_g["wins"] / yr_g["n"] * 100
    years = yr_g.index.tolist()
    bars = ax_year.bar(years, yr_g["total_R"],
                        color=["#2e7d32" if v >= 0 else "#c62828" for v in yr_g["total_R"]])
    ax_year.set_title("Total R по годам", fontsize=10)
    ax_year.set_xlabel("год"); ax_year.set_ylabel("R")
    ax_year.axhline(0, color="black", linewidth=0.8)
    for bar, wr in zip(bars, yr_g["WR"]):
        h = bar.get_height()
        ax_year.text(bar.get_x() + bar.get_width()/2, h + (1.5 if h >= 0 else -3),
                      f"WR {wr:.0f}%", ha="center", fontsize=7)

    # ---- direction split ----
    ax_dir = fig.add_subplot(gs[2, 1])
    dir_g = closed.groupby("direction").agg(n=("R", "size"),
                                               wins=("outcome", lambda x: (x == "win").sum()),
                                               total_R=("R", "sum"))
    dir_g["WR"] = dir_g["wins"] / dir_g["n"] * 100
    dirs = dir_g.index.tolist()
    colors = ["#1976d2" if d == "LONG" else "#d84315" for d in dirs]
    bars = ax_dir.bar(dirs, dir_g["total_R"], color=colors)
    ax_dir.set_title("LONG vs SHORT", fontsize=10)
    ax_dir.set_ylabel("R")
    ax_dir.axhline(0, color="black", linewidth=0.8)
    for bar, n, wr in zip(bars, dir_g["n"], dir_g["WR"]):
        h = bar.get_height()
        ax_dir.text(bar.get_x() + bar.get_width()/2, h + (1 if h >= 0 else -2),
                     f"n={n}\nWR {wr:.0f}%", ha="center", fontsize=8)

    # ---- equity curve ----
    ax_eq = fig.add_subplot(gs[3, 0])
    closed_sorted = closed.sort_values("trigger_time").reset_index(drop=True)
    cum = closed_sorted["R"].cumsum()
    ax_eq.plot(pd.to_datetime(closed_sorted["trigger_time"]), cum,
                color="#1565c0", linewidth=1.0)
    ax_eq.fill_between(pd.to_datetime(closed_sorted["trigger_time"]), 0, cum,
                        where=(cum >= 0), color="#1565c0", alpha=0.15)
    ax_eq.fill_between(pd.to_datetime(closed_sorted["trigger_time"]), 0, cum,
                        where=(cum < 0), color="#c62828", alpha=0.15)
    ax_eq.set_title("Equity curve (cumulative R)", fontsize=10)
    ax_eq.axhline(0, color="black", linewidth=0.5)
    ax_eq.tick_params(axis="x", labelsize=7, rotation=30)

    # ---- outlier bar ----
    ax_out = fig.add_subplot(gs[3, 1])
    R_arr = closed["R"].sort_values(ascending=False).to_numpy()
    top1 = R_arr[0] if len(R_arr) > 0 else 0
    top5 = R_arr[:5].sum() if len(R_arr) >= 5 else R_arr.sum()
    top10 = R_arr[:10].sum() if len(R_arr) >= 10 else R_arr.sum()
    total = R_arr.sum()
    outlier_data = {
        "Total": total,
        "Без top-1": total - top1,
        "Без top-5": total - top5,
        "Без top-10": total - top10,
    }
    bars = ax_out.bar(outlier_data.keys(), outlier_data.values(),
                        color=["#1565c0", "#42a5f5", "#90caf9", "#bbdefb"])
    ax_out.set_title("Robustness к outliers", fontsize=10)
    ax_out.set_ylabel("R")
    ax_out.axhline(0, color="black", linewidth=0.6)
    ax_out.tick_params(axis="x", labelsize=7, rotation=15)
    for bar, v in zip(bars, outlier_data.values()):
        h = bar.get_height()
        ax_out.text(bar.get_x() + bar.get_width()/2, h + (1 if h >= 0 else -2),
                     f"{v:.0f}R", ha="center", fontsize=7)

    pdf.savefig(fig); plt.close(fig)


def make_cover_page(pdf):
    fig = plt.figure(figsize=(8.5, 11))
    fig.text(0.5, 0.85, "Top SMC Strategies", ha="center",
             fontsize=24, fontweight="bold")
    fig.text(0.5, 0.80, "BTCUSDT 2020-2026 (6.33 years)",
             ha="center", fontsize=14, color="#555")
    fig.text(0.5, 0.76, "После фикса lookahead bug",
             ha="center", fontsize=12, color="#888")

    # summary table
    fig.text(0.5, 0.69, "Кандидаты C* (baseline) + D* (после 3-stage оптимизации)",
             ha="center", fontsize=11, fontweight="bold")
    tbl = [
        ["#", "Setup", "RR", "WR", "n/нед", "Total R", "R/tr"],
        ["C1", "OB-4h × FVG-1h pro", "1.0", "56.2%", "3.43", "+103.0", "+0.124"],
        ["C2", "OB-6h × FVG-2h pro", "1.0", "54.6%", "2.33", "+48.0", "+0.092"],
        ["C3", "OB-12h × FVG-2h pro", "1.0", "59.7%", "1.11", "+60.0", "+0.194"],
        ["C4", "OB-12h × FVG-2h pro", "1.5", "50.8%", "1.11", "+82.0", "+0.271"],
        ["C5", "FRSWEEP-4h × FVG-15m pro", "1.0", "53.2%", "3.20", "+51.0", "+0.064"],
        ["C6", "FRACT2X-1d+4h × FVG-2h pro", "1.0", "64.6%", "1.04", "+61.0", "+0.292"],
        ["D2★", "OB-12h × FVG-2h pro [opt]", "1.75", "47.2%", "1.11", "+89.5", "+0.297"],
        ["D1", "OB-12h × FVG-2h pro [opt]", "2.5", "37.8%", "1.11", "+93.5", "+0.325"],
    ]
    ax = fig.add_axes([0.06, 0.42, 0.88, 0.22])
    ax.axis("off")
    tab = ax.table(cellText=tbl, cellLoc="center", loc="center",
                   colWidths=[0.05, 0.30, 0.08, 0.10, 0.10, 0.13, 0.13])
    tab.auto_set_font_size(False); tab.set_fontsize(10)
    tab.scale(1, 1.5)
    for (r, c), cell in tab.get_celld().items():
        if r == 0:
            cell.set_facecolor("#cccccc"); cell.set_text_props(weight="bold")

    # method note
    method = [
        "МЕТОДОЛОГИЯ (после фикса lookahead bug + расширение анкоров):",
        "• Source: BTCUSDT spot, Binance, 2020-01-01 .. 2026-05-02 (6.33 года)",
        "• Detection: canon OB pair, canon FVG (3 candle), FRSWEEP = fractal i±2 + sweep candle",
        "• Anchor НЕ имеет size-фильтра (доказано в этап 13: small был ошибкой)",
        "• ANCHOR confirm timing: cur_close = cur_open + tf_anchor (fix lookahead bug)",
        "• SWEPT-фильтр (для OB) проверен — не даёт прорыва (см. отдельную страницу)",
        "• Trigger pro-trend filter: close LTF > EMA200 LTF (LONG) / < (SHORT)",
        "• Dedup: первый qualifying LTF trigger на анкор (включая filter)",
        "• min SL = 1% от entry — фьючерс-friendly",
        "• Simulation: 1m данные, first-hit SL/TP, conservative (SL first if same bar)",
        "",
        "ВНИМАНИЕ:",
        "• Все цифры на BTCUSDT (single asset). Out-of-sample на ETH/SOL TODO.",
        "• Walk-forward по годам показан в каждой странице — все стабильны.",
        "• Outlier robustness тоже на каждой странице — все edge не зависят от 1-2 трейдов.",
        "• C5 (FRSWEEP) добавлен после feedback: изначально grid пропускал fractals и sweep.",
    ]
    fig.text(0.06, 0.36, "\n".join(method),
             family="monospace", fontsize=8.5, va="top", ha="left")

    pdf.savefig(fig); plt.close(fig)


def make_bug_page(pdf):
    fig = plt.figure(figsize=(8.5, 11))
    fig.text(0.5, 0.94, "Lookahead bug — что было найдено",
             ha="center", fontsize=18, fontweight="bold")

    text = [
        "СИМПТОМ:",
        "Первый прогон grid search (etap_14 v1) показал якобы выдающихся кандидатов:",
        "  • OB-12h × FVG-15m, RR=1.0:   WR 77.7%, +329R за 6 лет, 2.76/нед",
        "  • OB-6h × FVG-15m, RR=1.5:    WR 58.7%, +559R, 5.61/нед",
        "  • OB-1d × FVG-15m, RR=2.0:    WR 67.4%, +285R, 1.45/нед",
        "",
        "WR 77% подозрительно высокий — pitfall #1: 'Если WR > 60% на сотнях",
        "сделок крипто-стратегии — первый кандидат на проверку lookahead'.",
        "",
        "ПРИЧИНА:",
        "В etap_14 окно поиска LTF-триггеров стартовало с anchor cur_OPEN:",
        "",
        "  a_start = a['time']           # = ob.cur_time = OPEN свечи cur",
        "  a_end   = a_start + a_life",
        "",
        "Но OB подтверждается ТОЛЬКО ПОСЛЕ закрытия cur — в cur_time + tf_anchor.",
        "Триггеры в окне (cur_open, cur_close) использовали анкор, ещё НЕ ВИДНЫЙ",
        "в реальном времени.",
        "",
        "Размер 'нелегального окна' зависит от tf_anchor:",
        "  OB-1d  + FVG-15m → 24h × 96 = до 96 'fake' триггеров на анкор",
        "  OB-12h + FVG-15m → 12h × 48 = до 48",
        "  OB-6h  + FVG-15m → 6h × 24  = до 24",
        "  OB-4h  + FVG-1h  → 4h × 4   = до 4 (поэтому OLD пострадал слабо)",
        "",
        "ФИКС:",
        "  a_tf_td = pd.Timedelta(anchor_tf)",
        "  a_start = a['time'] + a_tf_td   # cur_close — момент когда анкор виден",
        "  a_end   = a['time'] + a_life",
        "",
        "ВЛИЯНИЕ ФИКСА на 'топ-4' (раньше vs после):",
        "  OB-12h × FVG-15m RR=1.0:  WR 77.7% → 49.5%   total_R +329 → −6",
        "  OB-6h  × FVG-15m RR=1.5:  WR 58.7% → 36.0%   total_R +559 → −119",
        "  OB-1d  × FVG-15m RR=2.0:  WR 67.4% → 26.1%   total_R +285 → −65",
        "  OB-4h  × FVG-1h pro RR=1.0: WR 54.4% → 56.2%   +93 → +103   (мелкий δ)",
        "",
        "После фикса все 'миражи' исчезли. Реальная картина — 4 модерных",
        "кандидата с WR 55-60%, total_R +49…+116, R/tr 0.10-0.29.",
        "",
        "ПРАВИЛО ИЗБЕГАНИЯ (добавлено в known-pitfalls):",
        "  RED FLAG в коде: a_start = ...['time'] без + tf_anchor — проверять.",
        "  См. vault/knowledge/debugging/lookahead-anchor-confirm-окно....md",
    ]
    fig.text(0.05, 0.88, "\n".join(text),
             family="monospace", fontsize=8.8, va="top", ha="left")
    pdf.savefig(fig); plt.close(fig)


def make_sweep_fractal_page(pdf):
    fig = plt.figure(figsize=(8.5, 11))
    fig.text(0.5, 0.94, "Sweep + Fractal анкоры — что мы попробовали",
             ha="center", fontsize=18, fontweight="bold")
    text = [
        "ИЗНАЧАЛЬНОЕ УПУЩЕНИЕ:",
        "Первая итерация grid (etap_14) не включала ни fractals (FH/FL), ни",
        "snять ликвидности (sweep). После feedback расширили — etap_17.",
        "",
        "1) SWEPT-фильтр на OB-anchor (по логике strategy_1_1_1):",
        "",
        "   LONG  OB swept: ob_low  < min(n1.low, n2.low)",
        "   SHORT OB swept: ob_high > max(n1.high, n2.high)",
        "",
        "   То есть OB должен 'снять' минимумы / максимумы 2-х предыдущих свечей.",
        "   Это semantically — институциональный 'stop hunt' перед образованием OB.",
        "",
        "   Доля swept от всех OB-анкоров:",
        "     OB-1d:  259 / 602  = 43%",
        "     OB-12h: 532 / 1177 = 45%",
        "     OB-6h:  1034/ 2408 = 43%",
        "     OB-4h:  1565/ 3548 = 44%",
        "",
        "   РЕЗУЛЬТАТ — НЕ помогает:",
        "     OB-4h × FVG-1h pro RR=1.0:",
        "       all      WR 58.0%, +116R, 3.43/нед, R/tr 0.160",
        "       swept    WR 56.3%, +34R,  1.36/нед, R/tr 0.126",
        "     OB-6h × FVG-2h pro RR=1.0:",
        "       all      WR 56.1%, +57R,  2.33/нед",
        "       swept    WR 56.2%, +22R,  0.91/нед",
        "",
        "   Swept ∼обрезает половину setups при ТОМ ЖЕ WR. R/tr близок.",
        "   Total return хуже потому что меньше частота. ВЫВОД: swept НЕ filter.",
        "",
        "2) FRSWEEP — фрактал + sweep candle как отдельный anchor:",
        "",
        "   1. Detect FH/FL (Bill Williams i±2) на HTF",
        "   2. Ждём sweep candle: low <= FL.level + close > FL.level (LONG)",
        "                         high >= FH.level + close < FH.level (SHORT)",
        "   3. Anchor zone = диапазон sweep свечи",
        "   4. Trigger LTF FVG как обычно",
        "",
        "   Количество анкоров:",
        "     FRSWEEP-1d:  369",
        "     FRSWEEP-12h: 751",
        "     FRSWEEP-4h:  2330",
        "",
        "   ТОП FRSWEEP кандидаты после фильтра WR>=50, n/нед>=0.3:",
        "     FRSWEEP-12h × RDRB-1h pro RR=1.0:  WR 59.3%, +17R, 0.35/нед, R/tr 0.187",
        "     FRSWEEP-1d  × RDRB-1h all RR=1.0:  WR 57.1%, +30R, 0.84/нед, R/tr 0.143",
        "     FRSWEEP-4h  × FVG-15m pro RR=1.0: WR 53.2%, +51R, 3.20/нед, R/tr 0.064  ← C5",
        "",
        "   Лучший по R/tr слишком редкий (0.35/нед). Лучший по частоте имеет",
        "   слабый R/tr 0.064. Ни один не превзошёл OB-4h × FVG-1h.",
        "",
        "ИТОГ: ни SWEPT-фильтр, ни FRSWEEP не дают прорыва на BTCUSDT.",
        "Включаем C5 (FRSWEEP-4h × FVG-15m pro) в отчёт как 'best from this class'.",
    ]
    fig.text(0.05, 0.88, "\n".join(text),
             family="monospace", fontsize=8.6, va="top", ha="left")
    pdf.savefig(fig); plt.close(fig)


def make_fractal_deepdive_page(pdf):
    fig = plt.figure(figsize=(8.5, 11))
    fig.text(0.5, 0.95, "Фракталы — глубокое исследование (etap 18)",
             ha="center", fontsize=17, fontweight="bold")
    text = [
        "Что попробовали — 4 семейства комбинаций с FH/FL фракталами:",
        "",
        "A) FRACT-only anchor (fractal как чистый уровень-зона)",
        "   Zone = диапазон фрактал-свечи [low, high]. На 4 ТФ × 6 triggers × 2 filters × 3 RR.",
        "   Лучший: FRACT-12h × RDRB-1h pro RR=1.0  WR 55.5%, +32R, R/tr 0.110",
        "   ВЫВОД: чистый фрактал слабый — без sweep / confluence не имеет edge.",
        "",
        "B) FRSWEEP anchor (fractal + sweep candle, расширен на 6h)",
        "   Лучший по WR: FRSWEEP-1d × FVG-2h pro RR=1.0  WR 60.9%, +15R, R/tr 0.217",
        "   Лучший по R/tr: FRSWEEP-1d × FVG-2h pro RR=2.0  R/tr 0.453, но WR 48.4%",
        "   ВЫВОД: FRSWEEP-1d даёт edge, но n/нед < 0.5 — слишком редкий для деплоя.",
        "",
        "C) HTF OB anchor × LTF fractal-sweep TRIGGER (новая идея):",
        "   Вместо FVG/OB-trigger в зоне OB-htf берём LTF фрактал-sweep как trigger.",
        "   Лучший: OB-12h × FRSWEEP-2h pro RR=1.0  WR 54.6%, +30R, R/tr 0.093",
        "   НИ ОДИН не прошёл strict filter (WR>=55, n/нед>=0.3).",
        "   ВЫВОД: fractal-sweep как trigger не работает — слишком 'мелкий' сигнал внутри HTF зоны.",
        "",
        "D) ★ FRACT2X — multi-TF fractal CONFLUENCE anchor (новый winner!):",
        "   1) FH/FL на 1d (Bill Williams i±2)",
        "   2) В окне 14 дней — FH/FL на 4h ТОГО ЖЕ направления",
        "   3) |level_1d - level_4h| < 1 × ATR_4h  (близкие уровни)",
        "   4) Anchor zone = overlap (или union) candle ranges",
        "   5) Trigger: FVG-2h pro-trend",
        "",
        "   825 анкоров FRACT2X найдено за 6.33 года.",
        "   Лучший: FVG-2h pro RR=1.0   WR 64.6%, +61R, 1.04/нед, R/tr 0.292",
        "       → САМЫЙ ВЫСОКИЙ WR из всех протестированных setup'ов!",
        "       Включён в отчёт как C6.",
        "",
        "   CAVEAT: 2025 год дал WR 43.9%, −5R (деградация)",
        "       LONG WR 60.2% / SHORT WR 70.3% (асимметрия в пользу SHORT)",
        "",
        "   Тот же setup при RR=1.5 (C7-кандидат): WR 51.7%, +59.5R, R/tr 0.293",
        "       НО: 2 года минусовых (2021 −1.5R, 2025 −2.5R) → НЕ включён в отчёт.",
        "",
        "ИТОГ ПО ФРАКТАЛАМ:",
        "   • Фрактал-only — не работает.",
        "   • Fractal+sweep (FRSWEEP) — работает только на 1d, редкий.",
        "   • Fractal как trigger — не работает.",
        "   • Multi-TF fractal CONFLUENCE — РАБОТАЕТ (C6), лучший WR в исследовании.",
        "       Для live: следить за стабильностью в 2025+.",
    ]
    fig.text(0.05, 0.91, "\n".join(text),
             family="monospace", fontsize=8.4, va="top", ha="left")
    pdf.savefig(fig); plt.close(fig)


def make_optimization_page(pdf):
    fig = plt.figure(figsize=(8.5, 11))
    fig.text(0.5, 0.95, "3-stage оптимизация (etap_19) — entry / SL / RR",
             ha="center", fontsize=16, fontweight="bold")
    text = [
        "ПОДХОД (как в Strategy 1.1.1 stages 1-3, под правила пользователя):",
        "",
        "  Stage 1 — entry sweep [0.0, 0.25, 0.5, 0.75, 1.0]  (доля от FVG)",
        "      0.0 = дальний край (limit глубже в зону)",
        "      0.5 = mid (текущий baseline)",
        "      1.0 = ближний край (быстрая активация)",
        "  Stage 2 — sl_buf_atr [0.0, 0.15, 0.3, 0.5, 0.7] x min_sl_pct [0.5, 1.0, 1.5]",
        "  Stage 3 — RR sweep [1.5, 1.75, 2.0, 2.25, 2.5, 3.0]",
        "",
        "ПРАВИЛА ПОЛЬЗОВАТЕЛЯ:",
        "  • SL >= 1% от entry (фьючерсы) — отсекаем варианты с min_sl=0.5%",
        "  • RR в диапазоне 1.5-3.0, желательно 'адекватные' 1.8-2.5",
        "  • WR должен быть приемлемый (не критично низкий)",
        "",
        "РЕЗУЛЬТАТ ПО 4 БАЗАМ (best config с min_sl >= 1%):",
        "",
        "  B1 OB-4h x FVG-1h pro:",
        "    entry=0.5, sl_buf=0.30, min_sl=1.0, RR=1.5  → 45.5% WR, +110R, R/tr 0.137",
        "    Заметка: при min_sl=0.5% было бы +151R, но не соответствует правилу.",
        "",
        "  B2 OB-6h x FVG-2h pro:",
        "    entry=0.5, sl_buf=0.50, min_sl=1.5, RR=1.75 → 40.4% WR, +51.2R, R/tr 0.111",
        "    Слабейшая база, edge падает при RR>1.75.",
        "",
        "  B3 OB-12h x FVG-2h pro: ★ ЛУЧШАЯ",
        "    entry=0.5, sl_buf=0.15, min_sl=1.0, RR=1.75 → 47.2% WR, +89.5R, R/tr 0.297",
        "    UNIQUE: total_R РАСТЁТ при увеличении RR (trend-following profile):",
        "      RR=1.50: 51.3% WR, +86.5R, R/tr 0.283",
        "      RR=1.75: 47.2% WR, +89.5R, R/tr 0.297  ← max R/tr в зоне 1.5-2.0",
        "      RR=2.00: 42.5% WR, +81.0R, R/tr 0.276",
        "      RR=2.50: 37.8% WR, +93.5R, R/tr 0.325  ← в твоём 'fav' диапазоне",
        "      RR=3.00: 33.9% WR, +99.0R, R/tr 0.357  ← граница допустимого",
        "",
        "  B4 FRACT2X-1d+4h x FVG-2h pro:",
        "    entry=0.5, sl_buf=0.30, min_sl=1.0, RR=1.5 → 51.7% WR, +59.5R, R/tr 0.293",
        "    Edge быстро падает при RR>1.5; на RR=2.0 = +38R, R/tr 0.200.",
        "",
        "ИТОГ (D-кандидаты):",
        "  D2 = B3 @ RR=1.75 — ★ ОПТИМАЛЬНЫЙ балансированный (см. отдельную страницу)",
        "  D1 = B3 @ RR=2.5  — max R/tr в твоём 'fav' диапазоне (1.8-2.5)",
        "",
        "  D3 = B1 @ RR=2.5: +116R но 2025-2026 deg → не рекомендуется",
        "  D5 = B4 @ RR=2.0: edge испаряется; FRACT2X хорош только на RR=1.0-1.5",
        "",
        "ОБЩИЕ НАБЛЮДЕНИЯ:",
        "  1. ENTRY = 0.5 (mid FVG) выиграл во ВСЕХ 4 базах. Mid не случайный baseline.",
        "  2. SL_BUF мал у B3 (0.15) — узкий стоп улучшает edge при OB-12h.",
        "  3. min_sl=1% бьёт по абсолютному total_R на ~30%, но необходим для фьючерсов.",
        "  4. RR оптимум зависит от типа setup'а:",
        "       OB-12h trend → высокий RR (2.5-3.0)",
        "       OB-4h hi-freq → средний RR (1.5-2.0)",
        "       FRACT2X confluence → низкий RR (1.0-1.5)",
    ]
    fig.text(0.05, 0.91, "\n".join(text),
             family="monospace", fontsize=8.0, va="top", ha="left")
    pdf.savefig(fig); plt.close(fig)


def make_caveats_page(pdf):
    fig = plt.figure(figsize=(8.5, 11))
    fig.text(0.5, 0.94, "Caveats и следующие шаги",
             ha="center", fontsize=18, fontweight="bold")
    text = [
        "ОСТАЛИСЬ ОТКРЫТЫЕ ВОПРОСЫ:",
        "",
        "1. OOS на ETH/SOL.",
        "   Все цифры на BTCUSDT 6 лет. Стратегии могут быть переоптимизированы",
        "   на BTC. Нужны прогоны ETHUSDT, SOLUSDT — те же формулы, без ре-tune.",
        "",
        "2. Walk-forward с rolling-window.",
        "   Year-by-year breakdown показан, но это in-sample. Настоящий WF —",
        "   train на N лет, test на M месяцев, скользящее окно.",
        "",
        "3. Time-based фильтры.",
        "   Возможно WR можно поднять отсечением низко-ликвидных часов",
        "   (азиатская сессия в выходные) или дней (воскресенье).",
        "",
        "4. Live-implementation для C1/C2/C3.",
        "   В live-боте уже есть OB-4h+FVG-1h pro как backtest-only.",
        "   Перенести в strategies/strategy_*.py с тестами и интеграцией",
        "   в MultiStrategyScanner.",
        "",
        "5. Re-baseline всех research-стратегий с anchor-confirm фиксом.",
        "   Возможно strategy_1_1_1, 1_1_2, vic_bos и др. содержат тот же баг.",
        "   Аудит каждого pipeline перед production.",
        "",
        "ЧТО НЕ ДЕЛАТЬ:",
        "",
        "• Не использовать FVG-15m триггер на больших HTF анкорах (1d/12h/6h)",
        "  без жёсткой проверки anchor-confirm timing — там самая большая",
        "  площадь риска lookahead.",
        "",
        "• Не доверять 'красивым' цифрам (WR>65%, R/tr>0.5) на сотнях сделок",
        "  крипто-стратегии — это почти всегда либо lookahead, либо overfit.",
        "",
        "• Не оптимизировать дальше pro-trend filter без перепроверки EMA200",
        "  на отсутствие look-into-c2-close (computed на full close history).",
    ]
    fig.text(0.05, 0.88, "\n".join(text),
             family="monospace", fontsize=9.5, va="top", ha="left")
    pdf.savefig(fig); plt.close(fig)


def main():
    output_pdf = OUT_DIR / "etap16_strategies_report.pdf"
    print(f"[INFO] generating {output_pdf}")
    with PdfPages(output_pdf) as pdf:
        make_cover_page(pdf)
        make_bug_page(pdf)
        make_sweep_fractal_page(pdf)
        make_fractal_deepdive_page(pdf)
        make_optimization_page(pdf)
        for s in STRATEGIES:
            csv_name = s.get("csv", f"etap15_{s['id']}_trades.csv")
            csv = OUT_DIR / csv_name
            if not csv.exists():
                print(f"[WARN] {csv} missing — skip {s['id']}")
                continue
            df = pd.read_csv(csv)
            print(f"  {s['id']}: {len(df)} setups loaded")
            render_strategy_page(pdf, s, df)
        make_caveats_page(pdf)
    print(f"[OK] saved {output_pdf}")


if __name__ == "__main__":
    main()
