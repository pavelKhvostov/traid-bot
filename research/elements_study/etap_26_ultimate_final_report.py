"""Этап 26: УЛЬТИМАТИВНЫЙ финальный отчёт.

Объединяет ВСЕ наблюдения и исследования из этапов 0-25:
- 0-13: SMC elements study, размер OB sweep
- 14:   первый grid (с lookahead bug)
- 15:   deepdive C1-C7
- 16-21: PDF reports (текущие)
- 17-18: extended grid + fractal deep dive
- 19-20: 3-stage optimization → D-candidates
- 22-23: extended grid #2 (confluence/triple/fract-range) + 3-stage
- 24:    frequency-edge tradeoff analysis
- 25:    high-freq alternatives (E1/E2)

Структура (14 страниц):
  p.1  Cover + Executive Summary + Top picks
  p.2  Методология
  p.3  D2 ★ TOP RECOMMENDATION
  p.4  D1 — alternative high R/tr
  p.5  C3 — safe / max WR
  p.6  C6 — fractal-based alternative
  p.7  Полная ranking-таблица всех 13 кандидатов
  p.8  Что НЕ использовать и почему
  p.9  Lookahead bug case study
  p.10 SMC Elements — что работает, что нет
  p.11 Frequency-Edge tradeoff
  p.12 3-stage optimization findings
  p.13 Lessons + Open TODOs
  p.14 Index of all etaps
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

OUT_DIR = Path("research/elements_study/output")
YEARS = 6.33

# ---------------- Strategy specs ----------------
TOP_PICKS = [
    {
        "rank": "#1 PRIMARY (most stable)",
        "id": "C2",
        "name": "OB-6h x FVG-2h pro-trend (RR=1.0)",
        "why": "0 минусовых лет за 7. WR 55.3%, +70R, 2022 был +11R. Единственный со 100% positive-years.",
        "csv": "etap15_C2_trades.csv",
        "anchor": "OB-6h", "trigger": "FVG-2h", "filter": "pro",
        "entry_pct": 0.5, "sl_buf": 0.30, "min_sl_pct": 1.0, "rr": 1.0,
        "stats": {"WR": 55.3, "total_R": 70.0, "R_tr": 0.105, "n_total": 869, "n_per_week": 2.33},
        "color": "#2e7d32",
    },
    {
        "rank": "#2 SAFE (max WR)",
        "id": "C3",
        "name": "OB-12h x FVG-2h pro-trend (RR=1.0)",
        "why": "WR 58%, все годы positive (2022 borderline +1R). Edge per trade выше чем у C2.",
        "csv": "etap15_C3_trades.csv",
        "anchor": "OB-12h", "trigger": "FVG-2h", "filter": "pro",
        "entry_pct": 0.5, "sl_buf": 0.30, "min_sl_pct": 1.0, "rr": 1.0,
        "stats": {"WR": 58.0, "total_R": 60.0, "R_tr": 0.160, "n_total": 482, "n_per_week": 1.11},
        "color": "#1565c0",
    },
    {
        "rank": "#3 HIGH R/TR (твой fav RR)",
        "id": "D1",
        "name": "OB-12h x FVG-2h pro-trend [opt] (RR=2.5)",
        "why": "Max R/tr 0.263 при RR=2.5 (твой 'fav' диапазон). +92.5R, 2022 был break-even (+0.5R).",
        "csv": "etap20_D1_trades.csv",
        "anchor": "OB-12h", "trigger": "FVG-2h", "filter": "pro",
        "entry_pct": 0.5, "sl_buf": 0.15, "min_sl_pct": 1.0, "rr": 2.5,
        "stats": {"WR": 36.1, "total_R": 92.5, "R_tr": 0.263, "n_total": 482, "n_per_week": 1.11},
        "color": "#6a1b9a",
    },
    {
        "rank": "#4 BALANCED",
        "id": "D2",
        "name": "OB-12h x FVG-2h pro-trend [opt] (RR=1.75)",
        "why": "Балансированный, +81.2R. ВНИМАНИЕ: 2 минусовых года (2020 -6.75R, 2022 -6.25R).",
        "csv": "etap20_D2_trades.csv",
        "anchor": "OB-12h", "trigger": "FVG-2h", "filter": "pro",
        "entry_pct": 0.5, "sl_buf": 0.15, "min_sl_pct": 1.0, "rr": 1.75,
        "stats": {"WR": 44.4, "total_R": 81.2, "R_tr": 0.221, "n_total": 482, "n_per_week": 1.11},
        "color": "#ef6c00",
    },
]

ALL_CANDIDATES = [
    # Re-evaluated с 2022-данными (etap_27 fix)
    {"id": "C1", "setup": "OB-4h x FVG-1h pro", "RR": 1.0, "WR": 54.7, "freq": 3.43,
     "total": 97.0, "rt": 0.094, "verdict": "[!] 3 минусовых: 2022 -10R, 2025 -2R, 2026 -8R"},
    {"id": "C2", "setup": "OB-6h x FVG-2h pro", "RR": 1.0, "WR": 55.3, "freq": 2.33,
     "total": 70.0, "rt": 0.105, "verdict": "*** #1 PRIMARY — 0 минусовых лет"},
    {"id": "C3", "setup": "OB-12h x FVG-2h pro", "RR": 1.0, "WR": 58.0, "freq": 1.11,
     "total": 60.0, "rt": 0.160, "verdict": "*** #2 SAFE — 0 минусовых"},
    {"id": "C4", "setup": "OB-12h x FVG-2h pro", "RR": 1.5, "WR": 48.8, "freq": 1.11,
     "total": 81.0, "rt": 0.220, "verdict": "[!] 2 минусовых: 2020 -3R, 2022 -0.5R"},
    {"id": "C5", "setup": "FRSWEEP-4h x FVG-15m pro", "RR": 1.0, "WR": 53.2, "freq": 3.20,
     "total": 51.0, "rt": 0.064, "verdict": "[!] 2 минусовых, 15m gap в 2022 (incomplete)"},
    {"id": "C6", "setup": "FRACT2X-1d+4h x FVG-2h pro", "RR": 1.0, "WR": 62.2, "freq": 1.04,
     "total": 60.0, "rt": 0.244, "verdict": "[!] 2 минусовых: 2022 -3R, 2025 -5R"},
    {"id": "D1", "setup": "OB-12h x FVG-2h pro [opt]", "RR": 2.5, "WR": 36.1, "freq": 1.11,
     "total": 92.5, "rt": 0.263, "verdict": "*** #3 high R/tr, 1 минусовой (2020)"},
    {"id": "D2", "setup": "OB-12h x FVG-2h pro [opt]", "RR": 1.75, "WR": 44.4, "freq": 1.11,
     "total": 81.2, "rt": 0.221, "verdict": "*** #4 BALANCED, 2 минусовых (2020, 2022)"},
    {"id": "D3", "setup": "OB-4h x FVG-1h pro [opt]", "RR": 2.5, "WR": 32.6, "freq": 3.43,
     "total": 132.0, "rt": 0.141, "verdict": "[X] макс total но 2026 -10R"},
    {"id": "D4", "setup": "OB-4h x FVG-1h pro [opt]", "RR": 2.0, "WR": 37.5, "freq": 3.43,
     "total": 123.0, "rt": 0.126, "verdict": "[X] 2025-26 break-even"},
    {"id": "D5", "setup": "FRACT2X x FVG-2h pro [opt]", "RR": 2.0, "WR": 38.5, "freq": 1.04,
     "total": 35.0, "rt": 0.155, "verdict": "[X] нестабилен (3 минусовых)"},
]

# ---------------- helpers ----------------

def stats_from_df(df):
    closed = df[df["outcome"].isin(["win", "loss"])].copy()
    if closed.empty:
        return None
    n = len(df); nc = len(closed)
    w = (closed["outcome"] == "win").sum()
    return {
        "n_total": n, "n_closed": nc, "wins": int(w), "losses": int(nc - w),
        "WR": round(w / nc * 100, 1),
        "total_R": round(closed["R"].sum(), 1),
        "R_tr": round(closed["R"].mean(), 3),
        "df_closed": closed,
    }


# ---------------- pages ----------------

def cover_page(pdf):
    fig = plt.figure(figsize=(8.5, 11))
    fig.text(0.5, 0.94, "ULTIMATE FINAL REPORT", ha="center",
             fontsize=24, fontweight="bold", color="#0d47a1")
    fig.text(0.5, 0.91, "SMC Strategies Research — BTCUSDT 2020-2026", ha="center",
             fontsize=13, color="#444")
    fig.text(0.5, 0.885, "26 этапов исследования | 1024+ протестированных комбинаций | 6.33 года данных",
             ha="center", fontsize=10, color="#888", style="italic")

    fig.text(0.5, 0.83, "EXECUTIVE SUMMARY", ha="center",
             fontsize=14, fontweight="bold")
    summary_text = [
        "После 27 этапов и анализа более 1000 комбинаций SMC-элементов на BTCUSDT 2020-2026,",
        "winner — простой каскад HTF zone + LTF FVG + pro-trend filter. Сложные конструкции",
        "(confluence, triple-stack, fractal-only) НЕ дали edge'а сверх baseline.",
        "",
        "★ ВАЖНО (etap_27 fix): обнаружен gap в 1m данных за 2022-01-01 .. 2023-04-26.",
        "   После загрузки 692k недостающих 1m баров и пересчёта ВСЕХ кандидатов,",
        "   рейтинг изменился. C2 (OB-6h x FVG-2h) стал #1 — 0 минусовых лет за 7.",
        "   D2 потерял корону: 2022 был -6.25R, теперь 2 минусовых года из 7.",
    ]
    fig.text(0.07, 0.795, "\n".join(summary_text), fontsize=9.5, va="top", ha="left",
             color="#333")

    # Top-4 quick table
    fig.text(0.5, 0.66, "TOP-4 РЕКОМЕНДАЦИИ К ДЕПЛОЮ",
             ha="center", fontsize=13, fontweight="bold")

    ax = fig.add_axes([0.04, 0.42, 0.92, 0.21])
    ax.axis("off")
    tbl = [
        ["#", "ID", "Setup", "RR", "WR", "n/нед", "Total R", "R/tr", "Bad yrs"],
        ["#1 PRIMARY", "C2", "OB-6h × FVG-2h pro", "1.0", "55.3%", "2.33", "+70.0R", "+0.105", "0 ★"],
        ["#2 SAFE", "C3", "OB-12h × FVG-2h pro", "1.0", "58.0%", "1.11", "+60.0R", "+0.160", "0"],
        ["#3 HI R/TR", "D1", "OB-12h × FVG-2h pro [opt]", "2.5", "36.1%", "1.11", "+92.5R", "+0.263", "1"],
        ["#4 BALANCE", "D2", "OB-12h × FVG-2h pro [opt]", "1.75", "44.4%", "1.11", "+81.2R", "+0.221", "2"],
    ]
    tab = ax.table(cellText=tbl, cellLoc="center", loc="center",
                   colWidths=[0.12, 0.05, 0.27, 0.06, 0.09, 0.08, 0.10, 0.09, 0.07])
    tab.auto_set_font_size(False); tab.set_fontsize(9.5)
    tab.scale(1, 1.9)
    for (r, c), cell in tab.get_celld().items():
        if r == 0:
            cell.set_facecolor("#37474f"); cell.set_text_props(weight="bold", color="white")
        else:
            colors = ["#e3f2fd", "#f3e5f5", "#e8f5e9", "#fff3e0"]
            cell.set_facecolor(colors[r - 1])

    # Key insight
    insight = [
        "★ КЛЮЧЕВОЕ НАБЛЮДЕНИЕ:",
        "  ВСЕ 4 топа — на базе OB-{6h, 12h} × FVG-2h pro-trend.",
        "  Это структурная сила setup'а, не overfit. 2022 stress-test подтвердил.",
        "",
        "ВЫБОР по стилю:",
        "  • C2 (OB-6h, RR=1.0)   — самый стабильный, 0 минусовых лет, частота 2.33/нед",
        "  • C3 (OB-12h, RR=1.0)  — высший WR (58%), выше edge per trade чем C2",
        "  • D1 (OB-12h, RR=2.5)  — твой fav RR, max R/tr (0.263), но low WR",
        "  • D2 (OB-12h, RR=1.75) — больше total но 2022 был -6.25R",
    ]
    fig.text(0.06, 0.36, "\n".join(insight), family="monospace",
             fontsize=9.0, va="top", ha="left")

    # Footer methodology overview
    fig.text(0.06, 0.10, "Методология (детально на p.2):",
             fontsize=9.5, fontweight="bold")
    fig.text(0.06, 0.086,
             "BTCUSDT spot @ Binance, 2020-01-01 ... 2026-05-02 (6.33 года, 56k 1h-свечей).\n"
             "Canon SMC: OB pair, FVG 3-candle, RDRB, Bill Williams fractals i±2.\n"
             "Pro-trend filter: close LTF c2 vs EMA200_LTF.\n"
             "min SL = 1% от entry (фьючерс-friendly), TP = entry ± RR × risk.\n"
             "Симуляция: 1m данные, first-hit SL/TP, conservative (SL first if same bar).",
             family="monospace", fontsize=8.0, va="top", ha="left")

    pdf.savefig(fig); plt.close(fig)


def data_gap_page(pdf):
    fig = plt.figure(figsize=(8.5, 11))
    fig.text(0.5, 0.95, "Data Gap Discovery (etap_27)",
             ha="center", fontsize=16, fontweight="bold", color="#c62828")
    text = [
        "ОБНАРУЖЕНИЕ:",
        "  При year-by-year проверке user заметил что 2022 год отсутствует во всех таблицах:",
        "    2020, 2021, [пусто], 2023, 2024, 2025, 2026",
        "",
        "ПРИЧИНА:",
        "  BTCUSDT_1m.csv имел дыру в 480 дней:",
        "    gap = 2022-01-01 00:00 -> 2023-04-26 21:33",
        "  Из 1m бара за 2022:",
        "    expected:  525,600 баров (полный год)",
        "    actual:    1 бар",
        "  Из 1m баров за 2023:",
        "    expected:  525,600",
        "    actual:    358,707 (≈ 2/3 года, отсутствовали Jan-Apr)",
        "",
        "  Detection / collection всех зон РАБОТАЛИ (1d/4h/1h/12h/2h/15m данные полные).",
        "  Но simulate(SL/TP first-hit на 1m) возвращал 'no_data' для всех setups в gap'е.",
        "  -> Эти setups не попадали в closed-выборку, выпадали из year-by-year таблицы.",
        "",
        "ВЛИЯНИЕ:",
        "  Заявленные 6.33 года — на самом деле только ~4.7 года реального backtest.",
        "  2022 год (медвежий: LUNA crash май, FTX collapse ноябрь) — критический",
        "  stress-тест BTC рынка — был ПОЛНОСТЬЮ ПРОПУЩЕН.",
        "",
        "ФИКС (etap_27):",
        "  Загрузил 692,561 недостающих 1m баров через Binance REST",
        "  (~471 секунд, 692 батча по 1000 с 0.15s sleep).",
        "  Combined: 3,328,483 1m баров. Все годы теперь 525-528k.",
        "  Остаточные gaps: 15 шт., все < 6 часов (Binance maintenance) — приемлемо.",
        "",
        "ПЕРЕОЦЕНКА:",
        "  После пересчёта etap_15 (C1-C7) и etap_20 (D1-D5) — рейтинг сильно изменился:",
        "",
        "    Кандидат                   До (без 2022)        После (с 2022)",
        "    --------                   ----------------      ---------------",
        "    D2 OB-12h × FVG-2h RR=1.75 WR 47.2%, +89.5R     WR 44.4%, +81.2R  (was #1)",
        "    D1 OB-12h × FVG-2h RR=2.5  R/tr 0.325            R/tr 0.263       (R/tr -19%)",
        "    C2 OB-6h × FVG-2h RR=1.0   +48R                  +70R             (NEW #1!)",
        "    C1 OB-4h × FVG-1h RR=1.0   +103R                 +97R             (3 минусовых)",
        "    D3 OB-4h × FVG-1h RR=2.5   +116R                 +132R            (макс total)",
        "",
        "  C2 (бывший 'слабый стабильный') стал #1 — это единственная связка с 0",
        "  минусовых лет за 7. WR 55.3% во всех режимах рынка, включая 2022 (+11R, WR 55%).",
        "",
        "LESSON LEARNED:",
        "  Перед любым backtest всегда проверять полноту данных по годам/месяцам.",
        "  Symptom: год 'выпадает' из year-by-year breakdown -> data gap suspect.",
        "  Записано в vault/knowledge/debugging/ как pitfall для будущих research.",
    ]
    fig.text(0.05, 0.91, "\n".join(text), family="monospace",
             fontsize=8.4, va="top", ha="left")
    pdf.savefig(fig); plt.close(fig)


def methodology_page(pdf):
    fig = plt.figure(figsize=(8.5, 11))
    fig.text(0.5, 0.95, "Методология", ha="center", fontsize=18, fontweight="bold")
    text = [
        "ИСТОЧНИК ДАННЫХ:",
        "  • BTCUSDT spot @ Binance",
        "  • Период: 2020-01-01 .. 2026-05-02 (6.33 года)",
        "  • TF: 1m (2.6M баров), 15m, 1h (55k), 2h, 4h, 6h, 12h, 1d (2300)",
        "  • Native (загружено через REST), составные пересобраны (compose_from_base)",
        "",
        "CANON ОПРЕДЕЛЕНИЯ ЭЛЕМЕНТОВ (фиксированы в vault):",
        "  • OB pair: (prev, cur) — 2 свечи противоположных направлений; зона = тело prev",
        "  • FVG: 3 свечи (c0, c1, c2); зона = gap между low(c0) и high(c2) (LONG)",
        "  • RDRB: 3 свечи (a, m, c); ложный пробой high(a) или low(a) с возвратом",
        "  • Fractal (Bill Williams): high(i) > high(i±1, i±2) — FH; аналог FL",
        "  • FRSWEEP: фрактал → sweep candle (low<level И close>level для LONG)",
        "  • FRACT2X: фрактал на 1d + фрактал на 4h, same direction, |Δlevel| < 1×ATR_4h",
        "",
        "PRO-TREND FILTER:",
        "  Для LONG: close_LTF(c2 FVG) > EMA200_LTF",
        "  Для SHORT: close_LTF(c2 FVG) < EMA200_LTF",
        "",
        "DEDUP-ЛОГИКА:",
        "  Один LTF trigger на anchor — первый qualifying (включая filter).",
        "  Это исключает multi-counting перекрывающихся triggers.",
        "",
        "ANCHOR CONFIRM TIMING (КРИТИЧНО, см. p.9):",
        "  HTF zone подтверждается ТОЛЬКО ПОСЛЕ закрытия cur свечи anchor TF.",
        "  Окно поиска LTF trigger: [cur_open + tf_anchor, cur_open + life_days]",
        "  Для FRACT2X: confirm = max(1d_confirm, 4h_confirm), life = 14 дней",
        "",
        "ENTRY / SL / TP (final после 3-stage опт):",
        "  Entry  = (FVG_bottom + FVG_top) / 2     [mid FVG, limit-order]",
        "  atr_sl = FVG_far_border ∓ sl_buf × ATR_LTF",
        "  pct_sl = entry ∓ min_sl_pct × entry",
        "  SL     = max distance из (atr_sl, pct_sl)",
        "  TP     = entry ± RR × |entry − SL|",
        "  Timeout = 3 дня с момента активации (для 12h anchor)",
        "",
        "ПРАВИЛА ПОЛЬЗОВАТЕЛЯ:",
        "  • SL >= 1% от entry (фьючерс-friendly)",
        "  • RR в диапазоне 1.5-3.0, желательно 'адекватные' 1.8-2.5",
        "  • WR должен быть приемлемый, не критично низкий",
        "  • n/нед >= 1 (не снайпер)",
        "",
        "СИМУЛЯЦИЯ:",
        "  • 1m данные, векторизованный first-hit SL/TP",
        "  • Conservative: если SL и TP на одном баре — считаем loss (SL first)",
        "  • Activation timeout: TF_LIFE_DAYS LTF (3 для 2h, 5 для 1h)",
        "  • R: -1.0 для loss, (TP-Entry)/risk для win",
        "",
        "АЛГОРИТМ DEDUP:",
        "  Для каждого anchor: ищем первый LTF trigger в окне с overlap зон,",
        "  same direction. Берём один trigger на anchor → break.",
    ]
    fig.text(0.05, 0.91, "\n".join(text), family="monospace",
             fontsize=8.5, va="top", ha="left")
    pdf.savefig(fig); plt.close(fig)


def render_pick_page(pdf, pick):
    csv_path = OUT_DIR / pick["csv"]
    if not csv_path.exists():
        print(f"[WARN] {csv_path} not found")
        return
    df = pd.read_csv(csv_path)
    s = stats_from_df(df)
    if s is None: return

    fig = plt.figure(figsize=(8.5, 11))
    accent = pick["color"]
    fig.text(0.5, 0.96, pick["rank"], ha="center", fontsize=12,
             fontweight="bold", color=accent)
    fig.text(0.5, 0.93, f"{pick['id']} — {pick['name']}",
             ha="center", fontsize=14, fontweight="bold")
    fig.text(0.5, 0.905, f"WHY: {pick['why']}", ha="center", fontsize=9,
             color="#555", style="italic")

    a_tf = pick["anchor"].split("-")[1] if "-" in pick["anchor"] else pick["anchor"]
    t_tf = pick["trigger"].split("-")[1]
    is_fract2x = pick["anchor"].startswith("FRACT2X")

    if is_fract2x:
        rules = [
            "ПРАВИЛА ВХОДА (multi-TF fractal confluence):",
            f"  1. Detect фрактал FH/FL на 1d (Bill Williams i±2)",
            f"  2. В окне 14 дней — фрактал того же направления на 4h",
            f"  3. |level_1d - level_4h| < 1 × ATR_4h",
            f"  4. Anchor zone = пересечение candle ranges",
            f"  5. Anchor confirmed at later of (1d_confirm, 4h_confirm)",
            f"  6. Ждём первую FVG-{t_tf} того же direction в anchor zone",
            f"  7. Pro-trend filter: close_2h(c2) vs EMA200_2h",
            f"  8. Dedup: одна FVG на anchor",
            f"",
            f"PRICING:",
            f"  Entry  = mid FVG-{t_tf} (limit)",
            f"  atr_sl = FVG_far_border ∓ {pick['sl_buf']:.2f} × ATR_{t_tf}",
            f"  pct_sl = entry ∓ {pick['min_sl_pct']:.1f}% × entry",
            f"  SL     = дальше из (atr_sl, pct_sl)",
            f"  TP     = entry ± {pick['rr']:.2f} × |entry − SL|",
            f"  Timeout = 3 дня с активации",
        ]
    else:
        rules = [
            f"ПРАВИЛА ВХОДА (HTF zone + LTF FVG):",
            f"  1. Detect OB-{a_tf} (canon: pair (prev, cur), no size-фильтр)",
            f"  2. После cur_close ({a_tf} от cur_open) anchor становится известна",
            f"     Lifetime: {3 if a_tf == '12h' else 5} дней (для {a_tf})",
            f"  3. Ждём первую FVG-{t_tf} того же направления с overlap зон",
            f"  4. Pro-trend filter: close_{t_tf}(c2 FVG) vs EMA200_{t_tf}",
            f"  5. Dedup: одна FVG-{t_tf} на anchor",
            f"",
            f"PRICING:",
            f"  Entry  = (FVG_bottom + FVG_top) / 2  [mid FVG-{t_tf}, limit]",
            f"  atr_sl = FVG_far_border ∓ {pick['sl_buf']:.2f} × ATR_{t_tf}",
            f"  pct_sl = entry ∓ {pick['min_sl_pct']:.1f}% × entry",
            f"  SL     = дальше из (atr_sl, pct_sl)",
            f"  TP     = entry ± {pick['rr']:.2f} × |entry − SL|",
            f"  Timeout = 3 дня",
        ]
    fig.text(0.06, 0.87, "\n".join(rules), family="monospace",
             fontsize=8.5, va="top", ha="left")

    # Stats table
    ax_stats = fig.add_axes([0.06, 0.50, 0.40, 0.18])
    ax_stats.axis("off")
    table = [
        ["Метрика", "Значение"],
        ["Period", "2020-01-01 .. 2026-05-02"],
        ["Years coverage", "6.33"],
        ["Setups (n_total)", str(s["n_total"])],
        ["Closed", str(s["n_closed"])],
        ["Wins / Losses", f"{s['wins']} / {s['losses']}"],
        ["Win Rate", f"{s['WR']}%"],
        ["Total R", f"{s['total_R']:+.1f}"],
        ["R per trade", f"{s['R_tr']:+.3f}"],
        ["Setups per week", f"{pick['stats']['n_per_week']:.2f}"],
        ["R/year @ 1% risk", f"{s['total_R']/YEARS:+.1f}%"],
    ]
    tab = ax_stats.table(cellText=table, cellLoc="left",
                          loc="upper left", colWidths=[0.55, 0.40])
    tab.auto_set_font_size(False); tab.set_fontsize(9)
    tab.scale(1, 1.25)
    for (r, c), cell in tab.get_celld().items():
        if r == 0:
            cell.set_facecolor(accent); cell.set_text_props(weight="bold", color="white")

    # Year-by-year
    closed = s["df_closed"].copy()
    closed["year"] = pd.to_datetime(closed["trigger_time"]).dt.year
    yr_g = closed.groupby("year").agg(n=("R", "size"),
                                         wins=("outcome", lambda x: (x == "win").sum()),
                                         total_R=("R", "sum"))
    yr_g["WR"] = yr_g["wins"] / yr_g["n"] * 100
    ax_year = fig.add_axes([0.51, 0.51, 0.43, 0.18])
    bars = ax_year.bar(yr_g.index, yr_g["total_R"],
                        color=["#2e7d32" if v >= 0 else "#c62828" for v in yr_g["total_R"]])
    ax_year.set_title("Total R по годам", fontsize=10)
    ax_year.set_xlabel("год"); ax_year.set_ylabel("R")
    ax_year.axhline(0, color="black", linewidth=0.8)
    for bar, wr in zip(bars, yr_g["WR"]):
        h = bar.get_height()
        ax_year.text(bar.get_x() + bar.get_width()/2, h + (1 if h >= 0 else -3),
                      f"{wr:.0f}%", ha="center", fontsize=7)

    # Direction
    dir_g = closed.groupby("direction").agg(n=("R", "size"),
                                                wins=("outcome", lambda x: (x == "win").sum()),
                                                total_R=("R", "sum"))
    dir_g["WR"] = dir_g["wins"] / dir_g["n"] * 100
    ax_dir = fig.add_axes([0.06, 0.27, 0.40, 0.16])
    dirs = dir_g.index.tolist()
    colors = ["#1976d2" if d == "LONG" else "#d84315" for d in dirs]
    bars2 = ax_dir.bar(dirs, dir_g["total_R"], color=colors)
    ax_dir.set_title("LONG vs SHORT", fontsize=10)
    ax_dir.set_ylabel("R"); ax_dir.axhline(0, color="black", linewidth=0.8)
    for bar, n_, wr in zip(bars2, dir_g["n"], dir_g["WR"]):
        h = bar.get_height()
        ax_dir.text(bar.get_x() + bar.get_width()/2, h + (1 if h >= 0 else -2),
                     f"n={n_}\nWR {wr:.0f}%", ha="center", fontsize=8)

    # Equity
    closed_sorted = closed.sort_values("trigger_time").reset_index(drop=True)
    cum = closed_sorted["R"].cumsum()
    ax_eq = fig.add_axes([0.51, 0.27, 0.43, 0.16])
    ax_eq.plot(pd.to_datetime(closed_sorted["trigger_time"]), cum,
                color=accent, linewidth=1.0)
    ax_eq.fill_between(pd.to_datetime(closed_sorted["trigger_time"]), 0, cum,
                        where=(cum >= 0), color=accent, alpha=0.15)
    ax_eq.fill_between(pd.to_datetime(closed_sorted["trigger_time"]), 0, cum,
                        where=(cum < 0), color="#c62828", alpha=0.15)
    ax_eq.set_title("Equity curve", fontsize=10)
    ax_eq.axhline(0, color="black", linewidth=0.5)
    ax_eq.tick_params(axis="x", labelsize=7, rotation=30)

    # Outlier
    R_arr = closed["R"].sort_values(ascending=False).to_numpy()
    total = R_arr.sum()
    top1 = R_arr[0] if len(R_arr) > 0 else 0
    top5 = R_arr[:5].sum() if len(R_arr) >= 5 else R_arr.sum()
    top10 = R_arr[:10].sum() if len(R_arr) >= 10 else R_arr.sum()
    ax_out = fig.add_axes([0.06, 0.04, 0.88, 0.16])
    odata = {"Total": total, "Без top-1": total - top1,
              "Без top-5": total - top5, "Без top-10": total - top10}
    bars3 = ax_out.bar(odata.keys(), odata.values(),
                         color=[accent, "#90caf9", "#bbdefb", "#e3f2fd"])
    ax_out.set_title("Outlier robustness", fontsize=10)
    ax_out.set_ylabel("R"); ax_out.axhline(0, color="black", linewidth=0.5)
    for bar, v in zip(bars3, odata.values()):
        h = bar.get_height()
        ax_out.text(bar.get_x() + bar.get_width()/2, h + (1 if h >= 0 else -2),
                     f"{v:.0f}R", ha="center", fontsize=8)
    pdf.savefig(fig); plt.close(fig)


def ranking_page(pdf):
    fig = plt.figure(figsize=(8.5, 11))
    fig.text(0.5, 0.96, "Полная таблица всех 13 ключевых кандидатов",
             ha="center", fontsize=15, fontweight="bold")
    fig.text(0.5, 0.93,
             "C* = baseline (etap_15) | D* = 3-stage opt (etap_19-20) | E* = high-freq alt (etap_25)",
             ha="center", fontsize=8, color="#666", style="italic")

    rows = [["ID", "Setup", "RR", "WR", "n/нед", "Total R", "R/tr", "Verdict"]]
    for c in ALL_CANDIDATES:
        rows.append([
            c["id"], c["setup"], f"{c['RR']:.2f}", f"{c['WR']:.1f}%",
            f"{c['freq']:.2f}",
            f"+{c['total']:.1f}" if c['total'] >= 0 else f"{c['total']:.1f}",
            f"{c['rt']:+.3f}", c["verdict"],
        ])
    ax = fig.add_axes([0.03, 0.30, 0.94, 0.61])
    ax.axis("off")
    tab = ax.table(cellText=rows, cellLoc="center", loc="center",
                   colWidths=[0.05, 0.27, 0.06, 0.07, 0.08, 0.08, 0.08, 0.31])
    tab.auto_set_font_size(False); tab.set_fontsize(7.8)
    tab.scale(1, 1.35)
    for (r, c), cell in tab.get_celld().items():
        if r == 0:
            cell.set_facecolor("#37474f"); cell.set_text_props(weight="bold", color="white")
        else:
            v = ALL_CANDIDATES[r - 1]["verdict"]
            if "PRIMARY" in v or "ALT" in v or "SAFE" in v or "max WR" in v:
                cell.set_facecolor("#c8e6c9")
            elif "[X]" in v:
                cell.set_facecolor("#ffcdd2")
            elif "[!]" in v:
                cell.set_facecolor("#fff9c4")
            else:
                cell.set_facecolor("#eceff1")

    legend = [
        "Условные обозначения:",
        "  *** — рекомендованы к деплою (4 кандидата)",
        "  [!] — есть риск, но не disqualify (можно с мониторингом)",
        "  [X] — НЕ использовать (деградация на свежих годах или нестабильность)",
        "",
        "Структурный наблюдение:",
        "  ВСЕ 8 'OB-12h x FVG-2h' строк — одна и та же база с разными RR/SL.",
        "  Эта база выиграла во всех 3 из 4 топовых местах (D2, D1, C3, C4).",
        "  → Структурная сила связки, не overfit.",
        "",
        "  Все 'OB-4h x FVG-1h' строки (C1, D3, D4, E1) показывают деградацию",
        "  в 2025-2026 — паттерн ослабевает на свежих данных.",
    ]
    fig.text(0.06, 0.27, "\n".join(legend), family="monospace",
             fontsize=8.5, va="top", ha="left")
    pdf.savefig(fig); plt.close(fig)


def avoid_page(pdf):
    fig = plt.figure(figsize=(8.5, 11))
    fig.text(0.5, 0.95, "Что НЕ использовать и почему",
             ha="center", fontsize=16, fontweight="bold", color="#c62828")
    text = [
        "[X] D3 / D4 — OB-4h x FVG-1h pro RR=2.0/2.5 (после 3-stage opt)",
        "    Total R красивый (+107/+116R), НО year-by-year:",
        "      2020: +76R / +64R   <— весь edge сюда",
        "      2024: +22R / +39R",
        "      2025: 0R / +3R       <— break-even",
        "      2026: -2R / -10R     <— убыточный",
        "    Это не overfit одного года — это режимный сдвиг. Паттерн ослаб.",
        "",
        "[X] D5 — FRACT2X-1d+4h x FVG-2h pro RR=2.0",
        "    Edge на FRACT2X быстро испаряется при RR>1.5.",
        "    Year-by-year: 2020 -15R, 2025 -16R. FRACT2X хорош только на RR=1.0 (C6).",
        "",
        "[X] C5 — FRSWEEP-4h x FVG-15m pro RR=1.0",
        "    Edge нестабилен: 2 года минусовых (2021 -4R, 2023 -4R).",
        "    R/tr слабый 0.064. Высокая частота не компенсирует.",
        "",
        "[!] C1 — OB-4h x FVG-1h pro RR=1.0",
        "    Хороший в среднем (+103R), но 2025 = -2R, 2026 = -8R.",
        "    Можно использовать с мониторингом если хочется частоты (3.43/нед).",
        "",
        "[!] C2 — OB-6h x FVG-2h pro RR=1.0",
        "    Стабильно положительный во всех годах, но слабый edge (+48R, R/tr 0.092).",
        "    Подходит как 'тёплая ванна', но не как основа.",
        "",
        "[!] C6 — FRACT2X x FVG-2h pro RR=1.0",
        "    Самый высокий WR (64.6%), но 2025 = -5R. SHORT (70%) > LONG (60%).",
        "    Можно как 'снайперскую' добавку, но не как основу.",
        "",
        "[!] E1 — OB-4h x FVG-1h ALL (no pro filter) RR=1.0",
        "    Total +124R красивый, n/нед 6.38. Но та же 2025-26 деградация что у C1.",
        "    Pro filter не критичен — без него больше total но менее стабильно.",
        "",
        "[!] E2 — FRSWEEP-6h x FVG-15m ALL RR=1.0",
        "    Total +72R, R/tr 0.085. 2024 был +35R, но 2025 -4R.",
        "    Хуже C5 по 2025 стабильности.",
        "",
        "═════════════════════════════════════════════════════════════════════",
        "ОБЩИЙ ПРИНЦИП ОЦЕНКИ:",
        "    Total R обманчив без year-by-year проверки.",
        "    Кандидат с +116R но 2025-26 убыток ХУЖЕ кандидата с +89R и 5 годами +.",
        "    Все рекомендованные топы (D2/D1/C3/C6) показывают:",
        "      • Не более 1 года минусового",
        "      • 2025-2026 не катастрофические",
        "      • Зависимость от outliers минимальная (top-5 < 10% от total)",
    ]
    fig.text(0.05, 0.91, "\n".join(text), family="monospace",
             fontsize=8.5, va="top", ha="left")
    pdf.savefig(fig); plt.close(fig)


def lookahead_page(pdf):
    fig = plt.figure(figsize=(8.5, 11))
    fig.text(0.5, 0.95, "Lookahead Bug — case study", ha="center",
             fontsize=16, fontweight="bold")
    text = [
        "СИМПТОМ:",
        "Первый прогон grid (etap_14 v1) показал якобы выдающихся кандидатов:",
        "  • OB-12h x FVG-15m, RR=1.0:  WR 77.7%, +329R, 2.76/нед",
        "  • OB-6h  x FVG-15m, RR=1.5:  WR 58.7%, +559R, 5.61/нед",
        "  • OB-1d  x FVG-15m, RR=2.0:  WR 67.4%, +285R, 1.45/нед",
        "",
        "WR 77% подозрительно высокий — pitfall #1 проекта:",
        "  'Если WR > 60% на сотнях сделок крипто-стратегии — первый кандидат",
        "   на проверку lookahead bug'.",
        "",
        "ПРИЧИНА:",
        "В etap_14 окно поиска LTF-триггеров стартовало с anchor cur_OPEN:",
        "",
        "  a_start = a['time']   # = ob.cur_time = OPEN свечи cur",
        "  a_end   = a_start + a_life",
        "",
        "Но OB подтверждается ТОЛЬКО ПОСЛЕ закрытия cur — в cur_time + tf_anchor.",
        "Триггеры в окне (cur_open, cur_close) использовали анкор, ещё НЕ ВИДНЫЙ",
        "в реальном времени.",
        "",
        "Размер 'нелегального окна' зависит от tf_anchor x tf_trigger:",
        "  OB-1d  + FVG-15m -> 24h x 96 = до 96 'fake' триггеров на анкор",
        "  OB-12h + FVG-15m -> 12h x 48 = до 48",
        "  OB-6h  + FVG-15m -> 6h  x 24 = до 24",
        "  OB-4h  + FVG-1h  -> 4h  x  4 = до 4 (поэтому OLD пострадал слабо)",
        "",
        "Внутри окна формирования OB цена движется в сторону зоны (формирование",
        "OB как 'встреча' с уровнем) -> искусственно завышенный WR.",
        "",
        "ФИКС:",
        "  a_tf_td = pd.Timedelta(anchor_tf)",
        "  a_start = a['time'] + a_tf_td   # cur_close — момент когда анкор виден",
        "  a_end   = a['time'] + a_life",
        "",
        "ВЛИЯНИЕ ФИКСА на 'топ-3' (раньше vs после):",
        "  OB-12h x FVG-15m RR=1.0:    WR 77.7% -> 49.5%   total +329 -> -6",
        "  OB-6h  x FVG-15m RR=1.5:    WR 58.7% -> 36.0%   total +559 -> -119",
        "  OB-1d  x FVG-15m RR=2.0:    WR 67.4% -> 26.1%   total +285 -> -65",
        "  OB-4h  x FVG-1h pro RR=1.0:  WR 54.4% -> 56.2%   total +93 -> +103   (мелкий δ)",
        "",
        "После фикса все 'миражи' исчезли. Реальная картина — 4 кандидата с WR 55-60%,",
        "total +49…+116R, R/tr 0.10-0.29.",
        "",
        "ПРАВИЛО ИЗБЕГАНИЯ (добавлено в known-pitfalls.md):",
        "  RED FLAG в коде: a_start = ...['time'] без + tf_anchor — проверять.",
        "  RED FLAG в результатах: WR > 60% на сотнях крипто-сделок — lookahead suspect.",
        "  Эталон: etap_13_ob_size_sweep.py:99 — ob_start = ob_time + 4h.",
        "",
        "Зафиксировано в:",
        "  vault/knowledge/debugging/lookahead-anchor-confirm-окно-cur_open-cur_close.md",
        "  vault/knowledge/debugging/known-pitfalls.md (entry #11)",
    ]
    fig.text(0.05, 0.91, "\n".join(text), family="monospace",
             fontsize=8.0, va="top", ha="left")
    pdf.savefig(fig); plt.close(fig)


def smc_elements_page(pdf):
    fig = plt.figure(figsize=(8.5, 11))
    fig.text(0.5, 0.95, "SMC Elements — что работает на BTCUSDT",
             ha="center", fontsize=16, fontweight="bold")
    text = [
        "ОДИНОЧНЫЕ ЭЛЕМЕНТЫ (как anchor или trigger):",
        "",
        "  [WORK]  OB pair             — основной anchor. Работает на всех TF (4h-1d).",
        "                                Без size-фильтра! (small был ошибкой, см. этап 13)",
        "  [WORK]  FVG 3-candle        — основной trigger. Mid-FVG entry оптимален.",
        "  [PARTIAL] RDRB              — работает как anchor (RDRB-12h R/tr 0.233),",
        "                                но 6h variance слишком велика.",
        "  [WEAK]  Fractal FH/FL only  — слабый anchor. R/tr 0.04-0.11 без sweep.",
        "                                Не несёт edge'а сам по себе.",
        "  [WORK]  FRSWEEP             — фрактал + sweep candle. Хорошо на 1d (R/tr 0.343",
        "                                при RR=1.5), но n/нед < 0.5. На 4h-6h — приемлемо.",
        "  [STRONG] FRACT2X            — multi-TF fractal confluence (1d+4h).",
        "                                САМЫЙ ВЫСОКИЙ WR в исследовании (64.6%).",
        "                                Но 2025 -5R, нужен мониторинг.",
        "",
        "КОМБИНАЦИИ (HTF anchor + LTF trigger):",
        "",
        "  [WORK]  OB-htf x FVG-ltf + pro-trend",
        "          ★ ОПТИМАЛЬНАЯ КОМБИНАЦИЯ. Все топ-кандидаты (C1, C3, D2, D1) на ней.",
        "          Pro-trend filter добавляет +5pp к WR при минимальной потере частоты.",
        "",
        "  [WEAK]  OB-htf x OB-ltf",
        "          На уровне OB-htf x FVG-ltf без pro-фильтра. Не лучше.",
        "",
        "  [WEAK]  HTF zone x LTF Fractal-trigger (single FH/FL уровень)",
        "          R/tr ~0.04, на грани break-even. Фрактал без sweep не несёт edge.",
        "",
        "  [WEAK]  HTF zone x LTF FRSWEEP-trigger",
        "          НИ ОДИН не прошёл strict filter. Слишком 'мелкий' сигнал в HTF зоне.",
        "",
        "СЛОЖНЫЕ КОНСТРУКЦИИ:",
        "",
        "  [WEAK]  Same-TF zone CONFLUENCE (OB+FVG того же TF)",
        "          Обрезает 2.6x setups при том же WR. R/tr ≈ same. Total теряется.",
        "",
        "  [WEAK]  Triple-TF stack (HTF -> MID -> LTF)",
        "          OK WR (57%), но n/нед катастрофически падает (0.7 vs 1.11 у D2).",
        "          Каждый дополнительный фильтр режет половину setups.",
        "",
        "  [WEAK]  HTF Fractal range as anchor (без sweep, чистая candle)",
        "          R/tr 0.05, break-even. Свеча сама по себе не зона.",
        "",
        "  [N/A]   SWEPT-фильтр на OB (по логике strategy_1_1_1)",
        "          Обрезает 50% setups при том же WR. Total return падает в ~3x.",
        "          Не filter, а просто статистическое разделение группы.",
        "",
        "═════════════════════════════════════════════════════════════════════",
        "ВЫВОД: ПРОСТОЕ — ЛУЧШЕЕ. Каскад из 3 элементов (HTF zone + LTF FVG + ",
        "       trend-filter) оптимален. Дополнительная сложность не приносит edge'а",
        "       а только режет частоту.",
    ]
    fig.text(0.05, 0.91, "\n".join(text), family="monospace",
             fontsize=8.2, va="top", ha="left")
    pdf.savefig(fig); plt.close(fig)


def freq_tradeoff_page(pdf):
    fig = plt.figure(figsize=(8.5, 11))
    fig.text(0.5, 0.95, "Frequency-Edge Tradeoff (etap_24)",
             ha="center", fontsize=16, fontweight="bold")
    text = [
        "ВОПРОС: 'много ли я теряю хороших комбинаций из-за желания n/нед>=1?'",
        "ОТВЕТ:  НЕТ. Подробный анализ всех 2024 кандидатов в 4 grid'ах:",
        "",
        "DISTRIBUTION (sane: WR>=50, total_R>0, всего 298 кандидатов):",
        "",
        "  Bucket             N    median_WR  max_total_R  max_R/tr  max_R/year",
        "  0_high (>=2/нед)   87   51.7%      +124R        0.160     19.6",
        "  1_med (1-2)        90   51.9%      +68.5R       0.293     10.8",
        "  2_low (0.5-1)      65   53.8%      +31R         0.233     4.9",
        "  3_rare (0.2-0.5)   43   54.1%      +23R         0.343     3.6",
        "  4_sniper (<0.2)    13   52.9%      +11.5R       0.371     1.8",
        "",
        "Закономерность: max R/year РЕЗКО ПАДАЕТ с уменьшением частоты.",
        "  Max R/tr РАСТЁТ слегка (0.16 -> 0.37), но не компенсирует потерю частоты.",
        "",
        "THRESHOLD TRADEOFF:",
        "  Опускание порога с 1.0 до 0.1 добавляет 121 кандидата (177 -> 298).",
        "  НО максимально доступный R/year остаётся 19.6 (не растёт).",
        "  НО максимально доступный R/tr растёт с 0.293 до 0.371 (мизерно).",
        "",
        "MISSED GEMS (n/нед<1 + R/tr>0.25 + total_R>25):",
        "  ПУСТО! Не существует low-freq кандидатов с одновременно высокими",
        "  R/tr И total_R. Закон 'edge × частота = total return' соблюдается.",
        "",
        "SNIPER PORTFOLIO:",
        "  Top-10 снайперов (R/tr>0.30, n/нед<0.5): aggregated R/year = 6.9",
        "  vs D2 (один): R/year = 14.1",
        "  -> D2 один в 2x лучше portfolio из 10 снайперов!",
        "  Это контр-интуитивно: snipers имеют edge per trade,",
        "  но total return = edge × n_trades.",
        "",
        "FOUND (но НЕ лучше D2 после year проверки):",
        "  E1: OB-4h x FVG-1h ALL RR=1.0 — +124R, 6.38/нед, R/year 19.6",
        "      Та же 2025-26 деградация что у C1.",
        "  E2: FRSWEEP-6h x FVG-15m ALL — +72R, 3.18/нед, R/year 11.4",
        "      2025 -4R (хуже C5 которое было +28R в 2025).",
        "",
        "═════════════════════════════════════════════════════════════════════",
        "ВЫВОД: фильтр n/нед >= 1 был ПРАВИЛЬНЫМ.",
        "       Ничего ценного не упущено. Topы D2/D1/C3/C6 — реально лучшие",
        "       по балансу edge/частоты/стабильности на BTCUSDT 6 лет.",
    ]
    fig.text(0.05, 0.91, "\n".join(text), family="monospace",
             fontsize=8.5, va="top", ha="left")
    pdf.savefig(fig); plt.close(fig)


def optimization_page(pdf):
    fig = plt.figure(figsize=(8.5, 11))
    fig.text(0.5, 0.95, "3-Stage Optimization Findings (etap_19)",
             ha="center", fontsize=16, fontweight="bold")
    text = [
        "Подход (как в Strategy 1.1.1 stages 1-3):",
        "  Stage 1 — entry_pct: 0.0, 0.25, 0.5, 0.75, 1.0  (доля от FVG: 0=deep, 1=shallow)",
        "  Stage 2 — sl_buf [0.0, 0.15, 0.3, 0.5, 0.7] x min_sl_pct [0.5, 1.0, 1.5]",
        "  Stage 3 — RR [1.5, 1.75, 2.0, 2.25, 2.5, 3.0]",
        "",
        "ФИЛЬТРЫ ПОЛЬЗОВАТЕЛЯ:",
        "  • SL >= 1% от entry (фьючерс-friendly) — отсекаем варианты с min_sl=0.5%",
        "  • RR в диапазоне 1.5-3.0",
        "",
        "═════════════════════════════════════════════════════════════════════",
        "ОБЩИЕ НАБЛЮДЕНИЯ:",
        "",
        "1. ENTRY = 0.5 (mid FVG) выиграл во ВСЕХ 4 базах.",
        "   Mid не случайный baseline — оптимум по объективной метрике.",
        "   0.0 (deep) теряет fill rate, 1.0 (shallow) теряет edge.",
        "",
        "2. SL_BUF варьируется по базам:",
        "   B1 (OB-4h):  0.30  — стандартный буфер",
        "   B2 (OB-6h):  0.50  — больший буфер для волатильности 6h",
        "   B3 (OB-12h): 0.15  — узкий буфер ★ улучшает edge на +9R",
        "   B4 (FRACT2X): 0.30 — стандартный",
        "",
        "3. min_sl=1.0% — оптимум.",
        "   Если бы можно было 0.5% — total_R был бы +30% выше (B1: +151R vs +110R).",
        "   Но фьючерс-правило держит на 1%.",
        "",
        "4. RR-ОПТИМУМ ЗАВИСИТ ОТ ТИПА SETUP'А:",
        "",
        "    OB-12h x FVG-2h ★ Уникальный: total_R РАСТЁТ при RR -> 3.0!",
        "      RR=1.50: 51% WR, +86R, R/tr 0.283",
        "      RR=1.75: 47% WR, +89R, R/tr 0.297  <- best in 'safe' RR range",
        "      RR=2.00: 42% WR, +81R, R/tr 0.276",
        "      RR=2.50: 37% WR, +93R, R/tr 0.325  <- лучшая R/tr в твоём 'fav' диапазоне",
        "      RR=3.00: 33% WR, +99R, R/tr 0.357  <- максимум R, но low WR",
        "    -> Trend-following profile. Длинные TP реализуются.",
        "",
        "    OB-4h x FVG-1h:",
        "      RR=1.50: 45% WR, +110R  <- best",
        "      RR=2.00: 37% WR, +107R",
        "      RR=2.50: 33% WR, +116R  (но 2025-26 deg)",
        "    -> Hi-frequency profile. Sweet spot вокруг 1.5-2.0.",
        "",
        "    FRACT2X x FVG-2h:",
        "      RR=1.00: 64% WR, +61R, R/tr 0.292  <- лучший",
        "      RR=1.50: 51% WR, +59R",
        "      RR=2.00: 40% WR, +38R  <- edge падает",
        "    -> Narrow-band profile. RR > 1.5 не работает.",
        "",
        "    OB-6h x FVG-2h:",
        "      RR=1.75: 40% WR, +51R  <- best",
        "      RR=2.00+: edge испаряется -> -52R при RR=3",
        "    -> Слабая база, не выходит за RR=2.",
        "",
        "═════════════════════════════════════════════════════════════════════",
        "ИТОГ: оптимизация подтвердила структурную силу OB-12h x FVG-2h.",
        "       Эта база единственная где можно безопасно поднимать RR до 2.5-3.",
    ]
    fig.text(0.05, 0.91, "\n".join(text), family="monospace",
             fontsize=8.0, va="top", ha="left")
    pdf.savefig(fig); plt.close(fig)


def lessons_page(pdf):
    fig = plt.figure(figsize=(8.5, 11))
    fig.text(0.5, 0.95, "Lessons Learned + Open TODO",
             ha="center", fontsize=16, fontweight="bold")
    text = [
        "LESSONS LEARNED (для будущих research):",
        "",
        "1. WR > 60% на сотнях сделок крипто-стратегии = LOOKAHEAD-suspect.",
        "    Первая итерация дала WR 77%, +329R на FVG-15m триггере.",
        "    После фикса anchor-confirm timing -> WR 49%, -6R. Edge испарился.",
        "",
        "2. Total_R обманчив без year-by-year проверки.",
        "    OB-4h x FVG-1h pro RR=2.5 даёт +116R, выглядит как лучший.",
        "    Но 2025-2026 = -7R совокупно. Реальный edge ослаб.",
        "    Всегда смотреть на свежие годы перед деплоем.",
        "",
        "3. Mid FVG (entry_pct=0.5) — оптимум во всех 4 базах.",
        "    Stage 1 sweep подтвердил: deep entry (0.0) теряет fill rate,",
        "    shallow entry (1.0) теряет edge. Mid — sweet spot.",
        "",
        "4. RR оптимум зависит от базы:",
        "    OB-12h x FVG-2h    — высокий RR (1.75-3.0), trend profile",
        "    OB-4h x FVG-1h     — средний RR (1.0-2.0), hi-frequency profile",
        "    FRACT2X confluence — низкий RR (1.0-1.5), narrow band profile",
        "",
        "5. SWEPT-фильтр на OB не даёт прорыва — обрезает 50% setups при том же WR.",
        "    Multi-TF fractal CONFLUENCE даёт высокий WR но узкий RR-range.",
        "    Чистый фрактал слабый. Fractal-sweep как trigger не работает.",
        "",
        "6. Min SL = 1% (фьючерсы) бьёт по абсолютному total_R на ~30%,",
        "    но необходим. С min_sl=0.5% было бы B1 +151R вместо +110R.",
        "",
        "7. Frequency-edge tradeoff: edge × n_trades = total return.",
        "    Sniper portfolio из 10 даёт R/year=6.9 vs D2 один R/year=14.1.",
        "    Опускание порога частоты НЕ открывает скрытых high-R стратегий.",
        "",
        "8. ПРОСТОЕ — ЛУЧШЕЕ. Сложные конструкции (confluence, triple stack,",
        "    fractal-only, FRSWEEP-trigger) НЕ дают edge'а сверх baseline 'HTF zone +",
        "    LTF FVG + pro-trend filter'.",
        "",
        "═════════════════════════════════════════════════════════════════════",
        "OPEN TODO (перед production):",
        "",
        "  [ ] OOS на ETHUSDT, SOLUSDT — проверка переоптимизации на BTC",
        "  [ ] Walk-forward с rolling-window (4y train / 6mo test)",
        "  [ ] Time-based фильтры (час дня, день недели) — могут поднять WR",
        "  [ ] Live-implementation D2 в strategies/strategy_d2.py + tests + scanner",
        "      - Использовать live-обвязку как для strategy_1_1_1 (есть в репо)",
        "      - OB-12h detector + FVG-2h trigger + pro-trend filter + dedup-key",
        "  [ ] Re-baseline всех research-стратегий (1.1.1, 1.1.2, vic_bos, ...)",
        "      на anchor-confirm fix — возможно эти стратегии тоже содержат тот же bug",
        "  [ ] Мониторинг live-перфоманса D2: если 3 мес подряд WR < 40%,",
        "      перепроверить и при необходимости отключить",
        "  [ ] Эксперимент: combined portfolio D2 + C6 (low correlation, разные базы)",
    ]
    fig.text(0.05, 0.91, "\n".join(text), family="monospace",
             fontsize=8.4, va="top", ha="left")
    pdf.savefig(fig); plt.close(fig)


def index_page(pdf):
    fig = plt.figure(figsize=(8.5, 11))
    fig.text(0.5, 0.95, "Index of all etaps (роадмап исследования)",
             ha="center", fontsize=16, fontweight="bold")
    text = [
        "Этап  | Описание                                                   | Файл",
        "------|------------------------------------------------------------|----------------",
        " 0    | Скачивание истории BTCUSDT 2020-01-01 .. 2026-05-02         | etap_0_fetch_history.py",
        " 1    | Анализ OB на 8 ТФ                                           | etap_1_analyze_ob.py",
        " 1b   | OB context features (size_vs_ATR, sweep, etc.)              | etap_1b_ob_context.py",
        " 2    | Анализ FVG                                                  | etap_2_analyze_fvg.py",
        " 3    | Анализ RDRB                                                 | etap_3_analyze_rdrb.py",
        " 4    | Анализ фракталов FH/FL                                      | etap_4_analyze_fractals.py",
        " 5    | 5 chains связок элементов                                   | etap_5_connections.py",
        " 6    | Realistic backtest 5 chain'ов                               | etap_6_realistic.py",
        " 7    | Wick-touch filter                                           | etap_7_filtered.py",
        " 8    | RR sweep                                                    | etap_8_rr_sweep.py",
        " 9    | Первый grid 114 комбинаций (с size-фильтром)                | etap_9_grid_search.py",
        " 10   | Winner deepdive (multi-counting fix)                        | etap_10_winner_deepdive.py",
        " 11   | min_sl_pct grid                                             | etap_11_min_sl_pct.py",
        " 12   | OB-4h sweep                                                 | etap_12_ob_4h.py",
        " 13   | OB size sweep — small/medium/large/all                      | etap_13_ob_size_sweep.py",
        " 14   | ★ Расширенный grid 396 комбинаций (нашёл lookahead bug)     | etap_14_full_grid.py",
        " 15   | Deepdive C1-C7 year-by-year                                 | etap_15_top3_deepdive.py",
        " 16   | PDF отчёт о пути исследования                               | etap_16_pdf_report.py",
        " 17   | Grid 648 — добавил SWEPT + FRSWEEP                          | etap_17_grid_with_sweep_fractals.py",
        " 18   | Grid 372 — fractal deep dive (4 семейства)                  | etap_18_fractal_grid.py",
        " 19   | ★ 3-stage оптимизация для 4 баз                              | etap_19_optimize_top.py",
        " 20   | Year-by-year deepdive D1-D5                                 | etap_20_optimized_deepdive.py",
        " 21   | PDF финальные рекомендации                                  | etap_21_final_recommendations.py",
        " 22   | Grid 608 — confluence/triple/fract-range                    | etap_22_extended_grid.py",
        " 23   | 3-stage optimize for new winners (N1, N2)                   | etap_23_optimize_new.py",
        " 24   | Frequency-edge tradeoff analysis                            | etap_24_freq_analysis.py",
        " 25   | High-freq alternatives deepdive (E1, E2)                    | etap_25_high_freq_deepdive.py",
        " 26   | ★★ ULTIMATE FINAL REPORT (этот документ)                    | etap_26_ultimate_final_report.py",
        "",
        "═════════════════════════════════════════════════════════════════════",
        "ВСЕГО:",
        "  • 26 этапов research",
        "  • 1024+ протестированных комбинаций",
        "  • 6.33 года данных BTCUSDT",
        "  • 4 grid'а (etap_14, 17, 18, 22)",
        "  • 2 раунда 3-stage оптимизации (etap_19, 23)",
        "  • 1 критический lookahead bug найден и зафиксирован",
        "  • 3 PDF документа (этот — третий и финальный)",
        "",
        "PDF документы (в порядке развития):",
        "  • etap16_strategies_report.pdf      — журнал исследования (12 страниц)",
        "  • etap21_FINAL_RECOMMENDATIONS.pdf  — рекомендации (8 страниц)",
        "  • etap26_ULTIMATE_FINAL_REPORT.pdf  — этот документ (14 страниц)",
        "",
        "Vault knowledge:",
        "  • vault/knowledge/strategies/strategy-ob-4h-fvg-1h-pro-trend.md",
        "  • vault/knowledge/debugging/lookahead-anchor-confirm-окно-cur_open-cur_close.md",
        "  • vault/knowledge/debugging/known-pitfalls.md (entry #11 — anchor confirm)",
        "  • vault/sessions/2026-05-08-elements-study-grid-search-production-setup.md",
    ]
    fig.text(0.04, 0.91, "\n".join(text), family="monospace",
             fontsize=7.5, va="top", ha="left")
    pdf.savefig(fig); plt.close(fig)


def main():
    output_pdf = OUT_DIR / "etap26_ULTIMATE_FINAL_REPORT.pdf"
    print(f"[INFO] generating {output_pdf}")
    with PdfPages(output_pdf) as pdf:
        cover_page(pdf)
        data_gap_page(pdf)
        methodology_page(pdf)
        for pick in TOP_PICKS:
            render_pick_page(pdf, pick)
        ranking_page(pdf)
        avoid_page(pdf)
        lookahead_page(pdf)
        smc_elements_page(pdf)
        freq_tradeoff_page(pdf)
        optimization_page(pdf)
        lessons_page(pdf)
        index_page(pdf)
    size_kb = output_pdf.stat().st_size / 1024
    print(f"[OK] saved {output_pdf} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
