"""Decision window visualization for T1a canon example.

Highlights the visible chart between born_ms and entry_fill_ms — this is the
window where ML must make the final entry decision (NOT at born_ms).

Show 15m candles from ~3h before born to ~1h after entry.
"""
from __future__ import annotations
import sys, pathlib
from datetime import datetime, timezone, timedelta
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyBboxPatch

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib/projects/ob-vc/scripts"))
from _lib import load_1m, aggregate_all_tfs


MSK = timezone(timedelta(hours=3))

# ─── Canon T1a timestamps ─────────────────────────────
BORN_MS = int(datetime(2026, 6, 6, 1, 0, tzinfo=MSK).timestamp() * 1000)
ENTRY_TOUCH_MS = int(datetime(2026, 6, 6, 7, 6, tzinfo=MSK).timestamp() * 1000)
TP1R_HIT_MS = int(datetime(2026, 6, 7, 7, 55, tzinfo=MSK).timestamp() * 1000)

# Window — focus tightly on decision phase
WIN_S = int(datetime(2026, 6, 5, 18, 0, tzinfo=MSK).timestamp() * 1000)   # 7h before born
WIN_E = int(datetime(2026, 6, 6, 11, 0, tzinfo=MSK).timestamp() * 1000)   # 4h after entry

# ─── Trade levels ────────────────────────────────────
ENTRY = 60510.0
SL = 59131.0
R = ENTRY - SL
TP1R = ENTRY + R

# OB / FVG / drop area
OB_CUR_OPEN = int(datetime(2026, 6, 5, 23, 0, tzinfo=MSK).timestamp() * 1000)
OB_CUR_CLOSE = OB_CUR_OPEN + 2 * 3600 * 1000
DROP_AREA = (59131.0, 60814.0)
TOP_FVG_15M_ZONE = (60459.4, 60713.6)


# ─── Load 15m bars ─────────────────────────────────
rows = load_1m()
bars = aggregate_all_tfs(rows)
b15 = bars["15m"]
bars_win = [b for b in b15 if WIN_S <= b[0] < WIN_E]
print(f"15m bars in window: {len(bars_win)}")


def to_dt(ms):
    return datetime.fromtimestamp(int(ms) / 1000, MSK)


# ─── Chart ─────────────────────────────────────────
BULL = "#01a648"; BEAR = "#131b1b"
fig, ax = plt.subplots(figsize=(22, 11))
TF_MIN = 15
bar_w = TF_MIN / (60 * 24) * 0.6

for b in bars_win:
    ts_ms, o, h, l, c = b
    dt = to_dt(ts_ms)
    color = BULL if c >= o else BEAR
    ax.plot([dt, dt], [l, h], color=color, lw=1, alpha=0.85, zorder=3)
    body_lo = min(o, c); body_hi = max(o, c)
    body_h = max(body_hi - body_lo, 0.5)
    ax.add_patch(Rectangle(
        (dt - timedelta(minutes=TF_MIN * 0.35), body_lo), timedelta(minutes=TF_MIN * 0.7),
        body_h, facecolor=color, edgecolor=color, linewidth=0.5, zorder=3))


# ─── 1. WAIT WINDOW (decision phase) — shaded box ───
ymin, ymax = 58500, 63000
born_dt = to_dt(BORN_MS)
entry_dt = to_dt(ENTRY_TOUCH_MS)
ax.add_patch(Rectangle(
    (born_dt, ymin), entry_dt - born_dt, ymax - ymin,
    facecolor="#fff3cd", edgecolor="none", alpha=0.55, zorder=1))

ax.text(born_dt + (entry_dt - born_dt) / 2, ymax - 200,
        "👁 ВИДИМЫЙ УЧАСТОК ГРАФИКА ДЛЯ РЕШЕНИЯ\n(между ob_vc fired и entry fill)",
        ha="center", va="top", fontsize=14, fontweight="bold", color="#856404",
        bbox=dict(facecolor="#fff8e1", edgecolor="#b8860b", boxstyle="round,pad=0.5",
                  linewidth=1.5))

ax.text(born_dt + (entry_dt - born_dt) / 2, ymin + 200,
        f"⏱ длительность = {(ENTRY_TOUCH_MS - BORN_MS) / 60_000:.0f} минут",
        ha="center", va="bottom", fontsize=11, color="#856404", style="italic")


# ─── 2. PRE-BORN window (historical context) ───
ax.add_patch(Rectangle(
    (to_dt(WIN_S), ymin), born_dt - to_dt(WIN_S), ymax - ymin,
    facecolor="#e3f2fd", edgecolor="none", alpha=0.30, zorder=1))
ax.text(to_dt(WIN_S) + (born_dt - to_dt(WIN_S)) / 2, ymax - 300,
        "PRE-BORN: контекст ДО ob_vc",
        ha="center", va="top", fontsize=11, color="#1565c0", style="italic")


# ─── 3. POST-ENTRY (TBM phase) ───
ax.add_patch(Rectangle(
    (entry_dt, ymin), to_dt(WIN_E) - entry_dt, ymax - ymin,
    facecolor="#e8f5e9", edgecolor="none", alpha=0.30, zorder=1))
ax.text(entry_dt + (to_dt(WIN_E) - entry_dt) / 2, ymax - 300,
        "POST-ENTRY: TBM фаза (label measurement)",
        ha="center", va="top", fontsize=11, color="#2e7d32", style="italic")


# ─── 4. Key vertical lines ───
ax.axvline(born_dt, color="#d32f2f", lw=2.5, ls="--", zorder=5,
            label=f"ob_vc fired (born_ms) — 01:00 МСК 06-06")
ax.axvline(entry_dt, color="#1976d2", lw=2.5, ls="--", zorder=5,
            label=f"entry fill (touch) — 07:06 МСК 06-06")
ax.axvline(to_dt(OB_CUR_OPEN), color="#888", lw=1, ls=":", zorder=4, alpha=0.6)
ax.text(to_dt(OB_CUR_OPEN), ymin + 100, "cur 2h opens 23:00 МСК",
        ha="left", va="bottom", fontsize=8, color="#666", rotation=90)


# ─── 5. Price levels with strong markers ───
ax.axhline(ENTRY, color="#7e3c9e", lw=2.5, alpha=0.9, zorder=4)
ax.text(to_dt(WIN_E) + timedelta(minutes=30), ENTRY,
        f" Entry = ${ENTRY:,.0f}",
        ha="left", va="center", fontsize=12, fontweight="bold", color="#7e3c9e",
        bbox=dict(facecolor="white", edgecolor="#7e3c9e", boxstyle="round,pad=0.3", lw=1.5))

ax.axhline(SL, color="#d32f2f", lw=2.5, alpha=0.9, zorder=4)
ax.text(to_dt(WIN_E) + timedelta(minutes=30), SL,
        f" 🛑 SL = ${SL:,.0f}\n  (low_OB_VC)",
        ha="left", va="center", fontsize=12, fontweight="bold", color="#d32f2f",
        bbox=dict(facecolor="white", edgecolor="#d32f2f", boxstyle="round,pad=0.3", lw=1.5))

ax.axhline(TP1R, color="#2e7d32", lw=2, ls=":", alpha=0.7, zorder=4)
ax.text(to_dt(WIN_E) + timedelta(minutes=30), TP1R,
        f" TP +1R = ${TP1R:,.0f}",
        ha="left", va="center", fontsize=11, fontweight="bold", color="#2e7d32")


# ─── 5b. MARKER 1: где сформировался ob_vc (born point) ───
# Marker at cur 2h close = born_ms на close price ~ 61670
BORN_PRICE = 61670   # cur 2h close
ax.scatter([born_dt], [BORN_PRICE], s=350, marker="*",
            color="#ff6f00", edgecolors="#bf4d00", linewidths=2.5, zorder=7)
ax.annotate(
    "① ob_vc СФОРМИРОВАЛСЯ\n(born_ms — 01:00 МСК)\nпо закрытию cur 2h-бара",
    xy=(born_dt, BORN_PRICE),
    xytext=(born_dt - timedelta(hours=2.5), 62700),
    fontsize=11, fontweight="bold", color="#bf4d00",
    bbox=dict(facecolor="#fff3e0", edgecolor="#ff6f00",
              boxstyle="round,pad=0.45", lw=2),
    arrowprops=dict(arrowstyle="->", color="#bf4d00", lw=2,
                     connectionstyle="arc3,rad=-0.2"),
    ha="center", va="center", zorder=8)


# ─── 5c. MARKER 2: где была ТОЧКА ВХОДА ───
# Entry touch happens at price ENTRY at entry_dt
ax.scatter([entry_dt], [ENTRY], s=400, marker="o",
            facecolor="#7e3c9e", edgecolors="#4a2364", linewidths=3, zorder=7)
ax.annotate(
    f"② ТОЧКА ВХОДА\n(07:06 МСК)\nprice touched entry @ ${ENTRY:,.0f}",
    xy=(entry_dt, ENTRY),
    xytext=(entry_dt + timedelta(hours=2.5), 61500),
    fontsize=11, fontweight="bold", color="#4a2364",
    bbox=dict(facecolor="#f3e5f5", edgecolor="#7e3c9e",
              boxstyle="round,pad=0.45", lw=2),
    arrowprops=dict(arrowstyle="->", color="#4a2364", lw=2,
                     connectionstyle="arc3,rad=0.25"),
    ha="center", va="center", zorder=8)


# ─── 5d. MARKER 3: SL level — где стоп ───
ax.scatter([entry_dt + timedelta(hours=1)], [SL], s=350, marker="X",
            facecolor="#d32f2f", edgecolors="#7f0000", linewidths=2.5, zorder=7)
ax.annotate(
    f"③ STOP-LOSS\n@ ${SL:,.0f}\n(low_OB_VC)\nR = ${R:,.0f}",
    xy=(entry_dt + timedelta(hours=1), SL),
    xytext=(entry_dt + timedelta(hours=3), 58950),
    fontsize=11, fontweight="bold", color="#7f0000",
    bbox=dict(facecolor="#ffebee", edgecolor="#d32f2f",
              boxstyle="round,pad=0.45", lw=2),
    arrowprops=dict(arrowstyle="->", color="#7f0000", lw=2,
                     connectionstyle="arc3,rad=-0.2"),
    ha="center", va="center", zorder=8)


# ─── 6. Drop area shading ───
ax.add_patch(Rectangle(
    (to_dt(OB_CUR_OPEN), DROP_AREA[0]), to_dt(WIN_E) - to_dt(OB_CUR_OPEN),
    DROP_AREA[1] - DROP_AREA[0],
    facecolor="#ffd180", edgecolor="none", alpha=0.20, zorder=2))


# ─── 7. Top FVG zone ───
fvg_lo, fvg_hi = TOP_FVG_15M_ZONE
ax.add_patch(Rectangle(
    (to_dt(OB_CUR_OPEN + 1800_000), fvg_lo),
    to_dt(WIN_E) - to_dt(OB_CUR_OPEN + 1800_000), fvg_hi - fvg_lo,
    facecolor="#3498db", edgecolor="#1a5490", alpha=0.32, lw=1.5, zorder=2))
ax.text(to_dt(OB_CUR_OPEN + 1800_000) + timedelta(minutes=30), (fvg_lo + fvg_hi) / 2,
        "Top 15m FVG", ha="left", va="center",
        fontsize=10, fontweight="bold", color="#1a5490")


# ─── 8. Annotations: what's in decision window ───
ax.annotate("ML видит ЭТУ серию баров\nи решает: входить или нет",
             xy=(born_dt + (entry_dt - born_dt) / 2, 60800),
             xytext=(born_dt + (entry_dt - born_dt) / 2, 62500),
             ha="center", va="bottom", fontsize=11.5, fontweight="bold",
             color="#5d3a00",
             bbox=dict(facecolor="white", edgecolor="#b8860b",
                       boxstyle="round,pad=0.4", linewidth=1.5),
             arrowprops=dict(arrowstyle="->", color="#5d3a00", lw=1.5))


# ─── Format ───
ax.set_xlim(to_dt(WIN_S), to_dt(WIN_E) + timedelta(hours=4))
ax.set_ylim(ymin, ymax)
ax.set_ylabel("BTC price (USD)", fontsize=12)
ax.set_title(
    "T1a Example — Decision Window Visibility (BTC LONG ob_vc 2026-06-05/06)\n"
    "👁 Между born и entry_fill ML видит ~6 часов 15m-баров — все они должны участвовать в решении",
    fontsize=13.5, fontweight="bold", pad=15)

ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%m %H:%M", tz=MSK))
ax.xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 4, 8, 12, 16, 20]))
plt.setp(ax.xaxis.get_majorticklabels(), rotation=20, ha="right", fontsize=10)
ax.grid(True, alpha=0.25, zorder=0)
ax.legend(loc="lower right", fontsize=10, framealpha=0.92)

plt.tight_layout()
out = pathlib.Path.home() / "Desktop/i-rdrb-charts/decision_window_t1a.png"
out.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(out, dpi=110, bbox_inches="tight")
print(f"Saved: {out}")
