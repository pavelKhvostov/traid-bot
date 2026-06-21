"""Three BTC v3.3 trade visualizations with annotated markers:
① pattern born (ob_vc fired)
② entry filled (price touched entry)
③ exit (TP hit for winners / SL hit for losers)
"""
from __future__ import annotations
import csv, pathlib
from datetime import datetime, timezone, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.ticker import MultipleLocator
import pandas as pd


CSV1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
FEATURES = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v3/features_v33_picked.parquet")
OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts"
OUT.mkdir(parents=True, exist_ok=True)
MSK = timezone(timedelta(hours=3))
MS = 60_000
TF_MIN = 120  # 2h chart
TF_MS = TF_MIN * MS
WIN_DAYS_BEFORE = 5
WIN_DAYS_AFTER  = 15
RR = 2.0

BULL_COLOR = '#01a648'
BEAR_COLOR = '#131b1b'
DOJI_COLOR = '#888'
ENTRY_COL  = '#7e3c9e'  # purple (matches decision_window canon)
SL_COL     = '#d32f2f'
TP_COL     = '#2e7d32'
BORN_COL   = '#ff6f00'  # orange (canon for "ob_vc fired")
SHADE_PRE  = '#e3f2fd'  # pre-born
SHADE_WAIT = '#fff3cd'  # decision window
SHADE_POST = '#e8f5e9'  # post-entry


TRADES = [
    {
        "label": "W1 — LONG winner",
        "born_ms": 1742176800000,   # 2025-03-17 02:00 UTC
        "filename": "btc_v33_trade_W1_long_T1a_2025-03-17.png",
    },
    {
        "label": "W2 — SHORT winner",
        "born_ms": 1769976000000,   # 2026-02-01 20:00 UTC
        "filename": "btc_v33_trade_W2_short_T16_2026-02-01.png",
    },
    {
        "label": "L1 — LONG loser (high-proba)",
        "born_ms": 1722996000000,   # 2024-08-07 02:00 UTC
        "filename": "btc_v33_trade_L1_long_T4_2024-08-07.png",
    },
]

# y_true and proba from production CSV (already computed)
EXTRA = {
    1742176800000: {"y_true": 1, "proba": 0.9805},
    1769976000000: {"y_true": 1, "proba": 0.9386},
    1722996000000: {"y_true": 0, "proba": 0.9799},
}


def load_1m_dict():
    """Returns dict ts_ms → (o,h,l,c,v) for fast lookup."""
    bars = []
    with CSV1M.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            bars.append((int(t.timestamp()*1000),
                          float(r[1]), float(r[2]), float(r[3]),
                          float(r[4]), float(r[5])))
    return bars


def agg(d, tf_ms):
    out = []
    cb = None; o = h = l = c = 0.0; v = 0.0
    for ts, oo, hh, ll, cc, vv in d:
        b = ts - (ts % tf_ms)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v))
            cb = b; o, h, l, c, v = oo, hh, ll, cc, vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v += vv
    if cb is not None: out.append((cb, o, h, l, c, v))
    return out


def to_dt(ms): return datetime.fromtimestamp(ms/1000, MSK)


def find_exit_ms(bars_1m, start_ms, direction, sl, tp, max_days=14):
    """Find first 1m bar where TP or SL is touched. Returns (exit_ms, exit_type)."""
    end_ms = start_ms + max_days * 86400 * 1000
    for ts, o, h, l, c, v in bars_1m:
        if ts < start_ms or ts > end_ms:
            continue
        if direction == "long":
            if l <= sl: return ts, "sl"
            if h >= tp: return ts, "tp"
        else:
            if h >= sl: return ts, "sl"
            if l <= tp: return ts, "tp"
    return None, None


print("Loading 1m...")
m1 = load_1m_dict()
b2h_all = agg(m1, TF_MS)
print(f"Total 2h bars: {len(b2h_all)}")

print("Loading features...")
df = pd.read_parquet(FEATURES)
df_f = df[df.fill_touched & df.r_pct_pass].reset_index(drop=True)


def plot_trade(t):
    born_ms = t["born_ms"]
    row = df_f[(df_f.asset == "BTC") & (df_f.born_ms == born_ms)].iloc[0]
    entry_fill_ms = int(row["entry_fill_ms"])
    entry = float(row["entry"])
    r_pct = float(row["r_pct"])
    direction = str(row["direction"])
    t_id = str(row["t_id"])
    n_comp = int(row["n_comp"])
    proba = EXTRA[born_ms]["proba"]
    y_true = EXTRA[born_ms]["y_true"]

    r_abs = entry * r_pct / 100
    if direction == "long":
        sl = entry - r_abs
        tp = entry + RR * r_abs
    else:
        sl = entry + r_abs
        tp = entry - RR * r_abs

    # For winners — TP hit time. For losers — SL hit time.
    # TBM: y_true=1 means MFE >= RR*R reached BEFORE sl_hit
    if y_true == 1:
        exit_ms, exit_type = find_exit_ms(m1, entry_fill_ms, direction, sl, tp)
        # For winner: prioritize TP — search again checking ONLY TP
        if exit_type == "sl":
            # rare: TBM allows TP after SL? actually no — but our model used MFE-based labels
            # so TP can be FIRST in the run even if SL is hit later
            pass
        # Force-find first TP touch
        end_ms = entry_fill_ms + 14 * 86400 * 1000
        for ts, o, h, l, c, v in m1:
            if ts < entry_fill_ms or ts > end_ms:
                continue
            if direction == "long" and h >= tp:
                exit_ms, exit_type = ts, "tp"; break
            if direction == "short" and l <= tp:
                exit_ms, exit_type = ts, "tp"; break
    else:
        # loser — find first SL touch
        end_ms = entry_fill_ms + 14 * 86400 * 1000
        exit_ms, exit_type = None, None
        for ts, o, h, l, c, v in m1:
            if ts < entry_fill_ms or ts > end_ms:
                continue
            if direction == "long" and l <= sl:
                exit_ms, exit_type = ts, "sl"; break
            if direction == "short" and h >= sl:
                exit_ms, exit_type = ts, "sl"; break

    # Born close price — close of the cur 2h bar at born_ms (use exact bar that closed)
    born_bar_close_ms = born_ms  # born_ms is bar close-aligned
    born_close = entry  # fallback
    for ts, o, h, l, c, v in m1:
        if ts == born_bar_close_ms - MS:  # last 1m of the closed 2h bar
            born_close = c
            break

    # Window
    win_start = born_ms - WIN_DAYS_BEFORE * 86400 * 1000
    win_end_ms = (exit_ms if exit_ms else (entry_fill_ms + 3 * 86400 * 1000))
    # extend window a bit past exit
    win_end_ms += 2 * 86400 * 1000
    bars = [b for b in b2h_all if win_start <= b[0] <= win_end_ms]
    if not bars:
        print(f"No bars in window for {t['label']}")
        return

    born_dt = to_dt(born_ms)
    entry_dt = to_dt(entry_fill_ms)
    exit_dt = to_dt(exit_ms) if exit_ms else None
    win_start_dt = to_dt(win_start)
    win_end_dt = to_dt(win_end_ms)

    fig, ax = plt.subplots(figsize=(22, 12))

    # Compute y-range with padding
    lows = [b[3] for b in bars]; highs = [b[2] for b in bars]
    ymin = min(min(lows), sl) * 0.992
    ymax = max(max(highs), tp) * 1.008

    # ─── 1. PRE-BORN shading ───
    ax.add_patch(Rectangle((win_start_dt, ymin), born_dt - win_start_dt, ymax - ymin,
                            facecolor=SHADE_PRE, edgecolor="none", alpha=0.30, zorder=1))
    ax.text(win_start_dt + (born_dt - win_start_dt) / 2, ymax - (ymax-ymin)*0.02,
            "PRE-BORN: контекст ДО ob_vc",
            ha="center", va="top", fontsize=11, color="#1565c0", style="italic", zorder=2)

    # ─── 2. WAIT WINDOW (decision phase) ───
    wait_min = (entry_fill_ms - born_ms) / 60000
    ax.add_patch(Rectangle((born_dt, ymin), entry_dt - born_dt, ymax - ymin,
                            facecolor=SHADE_WAIT, edgecolor="none", alpha=0.55, zorder=1))
    ax.text(born_dt + (entry_dt - born_dt) / 2, ymax - (ymax-ymin)*0.02,
            f"👁 DECISION WINDOW   ⏱ {wait_min:.0f} мин",
            ha="center", va="top", fontsize=11, fontweight="bold", color="#856404",
            bbox=dict(facecolor="#fff8e1", edgecolor="#b8860b",
                       boxstyle="round,pad=0.35", linewidth=1.2), zorder=2)

    # ─── 3. POST-ENTRY (TBM phase) ───
    if exit_dt:
        ax.add_patch(Rectangle((entry_dt, ymin), exit_dt - entry_dt, ymax - ymin,
                                facecolor=SHADE_POST, edgecolor="none", alpha=0.30, zorder=1))
        ax.text(entry_dt + (exit_dt - entry_dt) / 2, ymax - (ymax-ymin)*0.02,
                "POST-ENTRY: trade open",
                ha="center", va="top", fontsize=11, color="#2e7d32", style="italic", zorder=2)

    # ─── 4. Candles ───
    BAR_WIDTH_FRACTION = 0.55
    bar_w = (TF_MIN / 60) / 24 * BAR_WIDTH_FRACTION
    for b in bars:
        dt = to_dt(b[0])
        o, h_p, l_p, c = b[1], b[2], b[3], b[4]
        color = BULL_COLOR if c > o else (BEAR_COLOR if c < o else DOJI_COLOR)
        ax.vlines(dt, l_p, h_p, color=color, linewidth=1.0, zorder=3)
        ax.add_patch(Rectangle(
            (mdates.date2num(dt) - bar_w/2, min(o, c)),
            bar_w, max(abs(o - c), 0.01),
            facecolor=color, edgecolor=color, linewidth=1.0, zorder=3))

    # ─── 5. Levels (horizontal lines + right-side labels) ───
    for level, label, color, ls in [
        (entry, f"ENTRY {entry:,.1f}", ENTRY_COL, "-"),
        (sl,    f"SL {sl:,.1f}  ({-r_pct:+.2f}%)", SL_COL, "--"),
        (tp,    f"TP {tp:,.1f}  ({(r_pct*RR if direction=='long' else -r_pct*RR):+.2f}%)", TP_COL, "--"),
    ]:
        ax.axhline(level, color=color, ls=ls, lw=1.8, alpha=0.9, zorder=4)
        ax.text(win_end_dt + timedelta(hours=4), level, f" {label}",
                color=color, fontsize=11, va="center", ha="left", fontweight="bold",
                bbox=dict(facecolor="white", edgecolor=color, lw=1.2,
                          boxstyle="round,pad=0.3"), zorder=6)

    # ─── 6. MARKER ① — ob_vc СФОРМИРОВАЛСЯ ───
    ax.scatter([born_dt], [born_close], s=400, marker="*",
                color=BORN_COL, edgecolors="#7a3500", linewidths=2.5, zorder=8)
    ax.annotate(
        f"① ob_vc СФОРМИРОВАЛСЯ\n(born_ms — {born_dt.strftime('%d-%m %H:%M')} МСК)\n"
        f"close cur 2h-bar = ${born_close:,.0f}",
        xy=(born_dt, born_close),
        xytext=(born_dt - timedelta(days=2), born_close + (ymax - ymin) * 0.10
                  if direction == "short" else born_close - (ymax - ymin) * 0.12),
        fontsize=11, fontweight="bold", color="#7a3500",
        bbox=dict(facecolor="#fff3e0", edgecolor=BORN_COL, boxstyle="round,pad=0.4", lw=2),
        arrowprops=dict(arrowstyle="->", color="#7a3500", lw=2,
                          connectionstyle="arc3,rad=-0.2"),
        ha="center", va="center", zorder=9)

    # ─── 7. MARKER ② — ТОЧКА ВХОДА ───
    ax.scatter([entry_dt], [entry], s=420, marker="o",
                facecolor=ENTRY_COL, edgecolors="#4a2364", linewidths=3, zorder=8)
    ax.annotate(
        f"② ВХОД\n({entry_dt.strftime('%d-%m %H:%M')} МСК)\n"
        f"price touched entry @ ${entry:,.0f}",
        xy=(entry_dt, entry),
        xytext=(entry_dt + timedelta(days=1.5),
                  entry + (ymax - ymin) * 0.10 if direction == "short"
                  else entry - (ymax - ymin) * 0.10),
        fontsize=11, fontweight="bold", color="#4a2364",
        bbox=dict(facecolor="#f3e5f5", edgecolor=ENTRY_COL, boxstyle="round,pad=0.4", lw=2),
        arrowprops=dict(arrowstyle="->", color="#4a2364", lw=2,
                          connectionstyle="arc3,rad=0.25"),
        ha="center", va="center", zorder=9)

    # ─── 8. MARKER ③ — TP HIT / SL HIT ───
    if exit_dt:
        exit_price = tp if exit_type == "tp" else sl
        exit_color = TP_COL if exit_type == "tp" else SL_COL
        exit_color_dark = "#1b5e20" if exit_type == "tp" else "#7f0000"
        exit_face_bg = "#e8f5e9" if exit_type == "tp" else "#ffebee"
        exit_marker = "P" if exit_type == "tp" else "X"
        exit_label = "③ TP HIT" if exit_type == "tp" else "③ SL HIT"
        exit_R = "+2R" if exit_type == "tp" else "−1R"

        ax.scatter([exit_dt], [exit_price], s=420, marker=exit_marker,
                    facecolor=exit_color, edgecolors=exit_color_dark, linewidths=3, zorder=8)
        # Y position for annotation: для TP (up if long) / SL (down if long)
        if direction == "long" and exit_type == "tp":
            ann_y = exit_price + (ymax - ymin) * 0.05
        elif direction == "long" and exit_type == "sl":
            ann_y = exit_price - (ymax - ymin) * 0.05
        elif direction == "short" and exit_type == "tp":
            ann_y = exit_price - (ymax - ymin) * 0.05
        else:
            ann_y = exit_price + (ymax - ymin) * 0.05
        ax.annotate(
            f"{exit_label} {exit_R}\n({exit_dt.strftime('%d-%m %H:%M')} МСК)\n"
            f"@ ${exit_price:,.0f}",
            xy=(exit_dt, exit_price),
            xytext=(exit_dt - timedelta(days=1.5), ann_y),
            fontsize=11, fontweight="bold", color=exit_color_dark,
            bbox=dict(facecolor=exit_face_bg, edgecolor=exit_color,
                       boxstyle="round,pad=0.4", lw=2),
            arrowprops=dict(arrowstyle="->", color=exit_color_dark, lw=2,
                              connectionstyle="arc3,rad=0.2"),
            ha="center", va="center", zorder=9)

    # ─── 9. Outcome badge top-left ───
    outcome_text = "✓ WIN +2R" if y_true == 1 else "✗ LOSS −1R"
    outcome_col = TP_COL if y_true == 1 else SL_COL
    ax.text(0.013, 0.965, outcome_text, transform=ax.transAxes,
            fontsize=17, fontweight="bold", color="white",
            va="top", ha="left", zorder=10,
            bbox=dict(facecolor=outcome_col, edgecolor=outcome_col,
                       boxstyle="round,pad=0.5", lw=2))

    # ─── Title ───
    dir_arrow = "↑" if direction == "long" else "↓"
    fig.suptitle(
        f"{t['label']}  ·  BTC 2h  ·  v3.3 strategy  ·  "
        f"{dir_arrow} {direction.upper()} {t_id}  (n_FVG={n_comp})  "
        f"·  proba={proba:.3f}  ·  R%={r_pct:.2f}%  ·  RR={RR}",
        fontsize=14, fontweight="bold", y=0.985)
    fig.text(0.5, 0.948,
              f"born → entry delay = {wait_min:.0f} min   ·   "
              f"TP at {('+'+str(round(RR*r_pct,2))) if direction=='long' else ('-'+str(round(RR*r_pct,2)))}%   "
              f"/   SL at {-r_pct:.2f}%",
              ha="center", fontsize=11, color="#444", style="italic")

    # ─── Axis ───
    ax.set_xlim(win_start_dt - timedelta(hours=6), win_end_dt + timedelta(days=2))
    ax.set_ylim(ymin, ymax)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%m", tz=MSK))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position("right")
    step = 1000 if entry > 30000 else 500
    ax.yaxis.set_major_locator(MultipleLocator(step))
    ax.grid(False)

    plt.subplots_adjust(left=0.03, right=0.91, top=0.91, bottom=0.06)
    out_path = OUT / t["filename"]
    plt.savefig(out_path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}  (exit={exit_type} at {exit_dt})")


for t in TRADES:
    plot_trade(t)
