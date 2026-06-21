"""Демо работы Вадима на графике: зона-ландшафт его канон-движка (через smc_adapter) на BTC.

Показывает, ЧТО даёт его работа (не прогноз направления, а контекст/фильтр/цель/инвалидация):
  - активные канон-зоны у цены, КАУЗАЛЬНО (snapshot на последнем баре), цвет по РОЛИ
    (⛽ liquidity / 🧲 inefficiency / 🎯 block), подпись TF·тип·митигация;
  - magnet/clear-path для LONG и SHORT (его «зоны=магниты»);
  - realistic-TP = ближайший магнит вверх/вниз;
  - мульти-ТФ контекст (1h/4h/1d).
Выход: research/ta_laws/demo_vadim_zones.png
Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/demo_vadim_zones.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import geometry as G  # noqa: E402
from research.smc_adapter import (precompute_zone_events, snapshot_from_events,  # noqa: E402
                                  zone_confluence, ROLE, ZTYPES_FAST)

ROLE_COL = {"block": "#3aa0ff", "inefficiency": "#ff8c42", "liquidity": "#ffd23f"}
ROLE_RU = {"block": "блок 🎯реакция", "inefficiency": "неэфф 🧲магнит", "liquidity": "ликвид ⛽топливо"}


def load_1m(sym):
    df = pd.read_csv(ROOT / "data" / f"{sym}_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def rs(df, freq):
    return df.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])


def trend(s, ts, td):
    a = s.asof(ts); b = s.asof(ts - td)
    return "UP" if (pd.notna(a) and pd.notna(b) and a > b) else "DOWN"


def candles(ax, sub, x0):
    for i, (_, r) in enumerate(sub.iterrows()):
        x = x0 + i; up = r["close"] >= r["open"]
        col = "#26a69a" if up else "#ef5350"
        ax.plot([x, x], [r["low"], r["high"]], color=col, lw=0.7, zorder=3)
        a, b = sorted([r["open"], r["close"]])
        ax.add_patch(Rectangle((x - 0.32, a), 0.64, max(b - a, 1e-9), facecolor=col, edgecolor=col, zorder=4))


def main():
    sym = "BTCUSDT"
    d1 = load_1m(sym)
    d1 = d1.loc[d1.index >= d1.index[-1] - pd.Timedelta(days=130)]
    h1 = rs(d1, "1h")
    c4 = rs(d1, "4h")["close"]; c1d = rs(d1, "1d")["close"]; c1h = h1["close"]
    ev, resampled = precompute_zone_events(d1, tfs=("4h", "12h", "1d"), types=ZTYPES_FAST)
    ts = h1.index[-1] + pd.Timedelta(minutes=1)
    price = float(c1h.iloc[-1])
    zones = snapshot_from_events(ev, resampled, d1, ts)
    near = [z for z in zones if z.distance_pct <= 7.0]
    near = sorted(near, key=lambda z: z.distance_pct)[:14]

    # контекст
    t1 = trend(c1h, h1.index[-1], pd.Timedelta(hours=10))
    t4 = trend(c4, h1.index[-1], pd.Timedelta(hours=40))
    td = trend(c1d, h1.index[-1], pd.Timedelta(days=10))
    arr = lambda t: "▲" if t == "UP" else "▼"
    mag_long = zone_confluence(zones, price, "UP")["score"]
    mag_short = zone_confluence(zones, price, "DOWN")["score"]
    # realistic-TP = ближайшая зона вверх/вниз
    ups = [(z.lo - price, z.lo) for z in near if z.lo > price]
    dns = [(price - z.hi, z.hi) for z in near if z.hi < price]
    tp_up = min(ups)[1] if ups else None
    tp_dn = max(dns)[1] if dns else None

    n = len(h1); start = max(n - 200, 0); xr = n + 30
    fig, ax = plt.subplots(figsize=(19, 9.5))
    fig.patch.set_facecolor("#0e1116"); ax.set_facecolor("#0e1116")
    candles(ax, h1.iloc[start:], start)
    ax.hlines(price, start, xr, color="#ddd", lw=0.9, ls=":", zorder=6)
    ax.text(xr, price, f" ${price:,.0f}", color="#ddd", fontsize=8, va="center")

    for z in near:
        role = ROLE.get(z.type, "block"); col = ROLE_COL[role]
        bx = h1.index.searchsorted(z.born_ts, side="left")
        x0 = max(bx, start)
        ax.add_patch(Rectangle((x0, z.lo), xr - x0, max(z.hi - z.lo, price * 1e-4),
                               facecolor=col, alpha=0.16, edgecolor=col, lw=0.8, zorder=2))
        lab = f"{z.tf}·{z.type}·{z.mitigation_model.split('-')[0]}"
        ax.text(xr, (z.lo + z.hi) / 2, f" {lab}", color=col, fontsize=6.5, va="center", zorder=7)

    # realistic-TP маркеры
    if tp_up:
        ax.hlines(tp_up, n - 6, xr, color="#1db954", lw=1.4, zorder=6)
        ax.text(n - 6, tp_up, "realistic-TP↑ ", color="#1db954", fontsize=7, ha="right", va="center")
    if tp_dn:
        ax.hlines(tp_dn, n - 6, xr, color="#ef5350", lw=1.4, zorder=6)
        ax.text(n - 6, tp_dn, "realistic-TP↓ ", color="#ef5350", fontsize=7, ha="right", va="center")

    nb = sum(1 for z in near if ROLE.get(z.type) == "block")
    ni = sum(1 for z in near if ROLE.get(z.type) == "inefficiency")
    nl = sum(1 for z in near if ROLE.get(z.type) == "liquidity")
    leg = [f"КОНТЕКСТ 1h{arr(t1)} 4h{arr(t4)} 1d{arr(td)}",
           f"зон у цены: {len(near)}  (синий блок {nb} · оранж неэфф {ni} · жёлтый ликвид {nl})",
           f"магнит ПРОТИВ LONG (снизу): {mag_long:.0f}   ПРОТИВ SHORT (сверху): {mag_short:.0f}",
           f"clear-path: {'LONG' if mag_long < mag_short else 'SHORT'} чище  -> ФИЛЬТР, не прогноз",
           "цвет=РОЛЬ: синий блок=реакция · оранж неэфф=магнит-заполнить · жёлтый ликвид=топливо/стопы"]
    ax.text(0.012, 0.985, "\n".join(leg), transform=ax.transAxes, fontsize=8.5, color="#eee",
            va="top", ha="left", zorder=9, family="monospace",
            bbox=dict(boxstyle="round,pad=0.6", fc="#161b22", ec="#30363d"))

    ax.set_title("Работа Вадима на графике BTC — зона-ландшафт его канон-движка (smc_adapter, КАУЗАЛЬНО)\n"
                 "что даёт: КАРТА зон + ФИЛЬТР (магнит/clear-path) + ЦЕЛЬ (realistic-TP) + роли. НЕ прогноз направления",
                 fontsize=11, color="#eee")
    ax.set_xlim(start - 2, xr + 6); ax.grid(alpha=0.10, color="#888"); ax.tick_params(colors="#aaa", labelsize=7)
    xt = list(range(start, n, max((n - start) // 10, 1)))
    ax.set_xticks(xt); ax.set_xticklabels([h1.index[t].strftime("%m-%d\n%H:%M") for t in xt])
    for sp in ax.spines.values():
        sp.set_color("#444")
    fig.tight_layout()
    out = HERE / "demo_vadim_zones.png"
    fig.savefig(out, dpi=120, facecolor=fig.get_facecolor())
    print(f"saved {out}; зон активных {len(zones)}, показано {len(near)}; "
          f"snapshot {h1.index[-1]}; magnet L/S {mag_long:.0f}/{mag_short:.0f}")
    for z in near[:10]:
        print(f"  {z.tf:>3} {z.type:<9} {ROLE.get(z.type):<12} {z.side:<6} dist {z.distance_pct:5.2f}% "
              f"[{z.lo:,.0f}–{z.hi:,.0f}] mit {z.mitigation_model}")


if __name__ == "__main__":
    main()
