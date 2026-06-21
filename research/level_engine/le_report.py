"""le_report — ВИЗУАЛЬНАЯ карта уровней + аргументация (PNG).

Слева: цена (12h) + полосы уровней, подписаны силой. Справа: панель аргументации —
по каждому уровню компактная строка-обоснование (конфлюэнс/TF/виды, R/B/F реакции,
магнит/ликвидность, дистанция). Внизу — полная аргументация ближайших уровней.

ОПИСАТЕЛЬНО (predicts_hold=False): сила = сводка структуры и прошлых реакций, не прогноз.

Запуск: set PYTHONIOENCODING=utf-8
        venv/Scripts/python.exe research/level_engine/le_report.py BTCUSDT
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parents[1]))
import le_engine as LE
import etap_225_dual_dashboard as D

COL = {"support": "#26a69a", "resistance": "#ef5350"}


def _hm(x):
    return f"{x/1000:.1f}k" if x >= 10000 else f"{x:,.0f}"


def _argline(L):
    kinds = "".join(c[0] for c in sorted(L["kinds"]))   # компактно: O F i R P V H L B S
    mag = "POC" if L["has_magnet"] else ""
    liq = "LIQ" if L["has_liquidity"] else ""
    tag = "+".join(x for x in (mag, liq) if x) or "-"
    return (f"{_hm(L['center']):>6} {L['side'][:3].upper()} {L['strength']}/10 | "
            f"{L['n_zones']:>3}з {len(L['tfs'])}TF [{kinds}] | "
            f"R{L['rejects']} B{L['breaks']} F{L['flips']} | {tag} | {L['dist_pct']:+.1f}%")


def render(snap, df1h, out: Path, window_usd=8000):
    price = snap["price"]
    lv = [L for L in snap["levels"] if abs(L["center"] - price) <= window_usd]
    lv.sort(key=lambda L: -L["center"])
    d12 = df1h.resample("12h").agg({"open": "first", "high": "max", "low": "min",
                                    "close": "last"}).dropna().tail(160)

    fig = plt.figure(figsize=(16, 10))
    axp = fig.add_axes([0.05, 0.06, 0.42, 0.88])
    axt = fig.add_axes([0.50, 0.06, 0.48, 0.88]); axt.axis("off")

    axp.plot(range(len(d12)), d12["close"].values, color="#222", lw=1.1, zorder=3)
    x1 = len(d12) - 1
    for L in lv:
        c = COL[L["side"]]
        a = 0.10 + 0.03 * (L["strength"] - 4)             # сильнее -> заметнее
        axp.add_patch(Rectangle((0, L["bottom"]), x1 + 6, L["top"] - L["bottom"],
                                color=c, alpha=max(0.06, a), zorder=1))
        axp.text(x1 + 6, L["center"], f" {L['strength']}/10 {L['side'][:3].upper()}",
                 va="center", fontsize=8, color=c, weight="bold")
    axp.axhline(price, color="#1565c0", lw=1.2, ls="--", zorder=4)
    axp.text(0, price, f" цена {_hm(price)} ", va="bottom", fontsize=9, color="#1565c0", weight="bold")
    axp.set_xlim(0, x1 + 60); axp.set_ylim(price - window_usd * 1.05, price + window_usd * 1.05)
    axp.set_title(f"BTC уровни (12h) · {snap['ref_time'][:16]} · descriptive (не прогноз)",
                  fontsize=11, weight="bold", loc="left")
    axp.grid(alpha=0.12)

    # правая панель: компактная аргументация по всем уровням окна
    axt.text(0, 1.0, "АРГУМЕНТАЦИЯ СИЛЫ (сводка структуры + прошлых реакций)",
             fontsize=10, weight="bold", va="top", family="monospace")
    axt.text(0, 0.965, "цена  side сила |  зон TF [виды] | реакции R/B/F | магнит/ликв | дист",
             fontsize=7.5, color="#555", va="top", family="monospace")
    y = 0.93
    for L in lv:
        axt.text(0, y, _argline(L), fontsize=8.0, va="top", family="monospace",
                 color=COL[L["side"]])
        y -= 0.022
    # легенда видов
    axt.text(0, y - 0.01, "виды: O=OB F=FVG i=iFVG R=RDRB P=POC V=VAH/VAL H=HVN/LVN B=BSL S=SSL",
             fontsize=7, color="#777", va="top", family="monospace")
    y -= 0.05
    # полная аргументация 3 ближайших к цене
    near = sorted(lv, key=lambda L: abs(L["center"] - price))[:3]
    axt.text(0, y, "── ПОЛНАЯ аргументация 3 ближайших уровней ──", fontsize=8.5,
             weight="bold", va="top", family="monospace"); y -= 0.026
    for L in near:
        axt.text(0, y, f"▸ {_hm(L['center'])} {L['side'].upper()} {L['strength']}/10:",
                 fontsize=8, weight="bold", va="top", family="monospace", color=COL[L["side"]])
        y -= 0.022
        for arg in L["args"]:
            axt.text(0.02, y, arg[:96], fontsize=7.2, va="top", family="monospace", color="#333")
            y -= 0.0175
        y -= 0.008

    fig.savefig(out, dpi=120); plt.close(fig)
    return out


def main():
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    df = D.fetch(sym, days=900)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    snap = LE.snapshot(df, df.index[-1])
    out = HERE / "output"; out.mkdir(exist_ok=True)
    p = render(snap, df, out / f"le_report_{sym}.png")
    print(f"saved {p}  (price {snap['price']:,.0f}, levels {snap['n_levels']})")


if __name__ == "__main__":
    main()
