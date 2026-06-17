"""etap_236 — ячейки направление×тип-дня для Strategy 1.1.2 (product-2 из v2.0).

Методика etap_231/232: для каждой закрытой сделки 1.1.2 берём 1h-бары дня
ТОЛЬКО до часа сигнала → day-type (движок etap_217, train BTC<2023) →
ячейки WR по (direction, dt_state) + shrunk-значения (ml-8) для signal_context.

Сделки: signals/analyze_1_1_2_extended_final.csv (BTC, 3y, entry=0.70 sl=0.35
RR=2.2, extended_macro_search=True). ЧЕСТНАЯ ОГОВОРКА: live S112 = baseline
(extended=False); формулы entry/SL идентичны, extended лишь добавляет больше
macro-кандидатов — ячейки структурно те же, смесь чуть шире (n 426 vs 241).

Запуск: venv/Scripts/python.exe research/daily_engine/etap_236_cells_112.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT))
import etap_217_daytype_layer as L

H1 = ROOT / "data" / "BTCUSDT_1h_orderflow.csv"
SIG = ROOT / "signals" / "analyze_1_1_2_extended_final.csv"
RR = 2.2
ALPHA = 10.0  # сила shrinkage-prior (как в signal_context.shrunk_rate)


def main():
    h1 = pd.read_csv(H1, index_col=0, parse_dates=True)
    if h1.index.tz is None: h1.index = h1.index.tz_localize("UTC")
    R = L.build(h1).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    M = L.fit_per_hour(R[R.day < L.CUTOFF])

    d = pd.read_csv(SIG)
    d["signal_time"] = pd.to_datetime(d["signal_time"], utc=True)
    closed = d[d.outcome.isin(["win", "loss"])].copy().reset_index(drop=True)
    # OOS-гигиена: все сделки должны быть >= cutoff движка
    assert closed.signal_time.min() >= L.CUTOFF, "сделки заходят в train движка!"
    print(f"1.1.2 (extended, BTC): закрытых {len(closed)} | "
          f"{closed.signal_time.min().date()}…{closed.signal_time.max().date()}")

    states = []
    for _, s in closed.iterrows():
        t = s.signal_time; day = t.normalize()
        bars = h1[(h1.index.normalize() == day) & (h1.index <= t)]
        if len(bars) < L.IB + 2:
            states.append("FORMING"); continue
        dec, _ = L.daytype_nowcast(bars, M)
        states.append(dec[-1][1])
    closed["dt_state"] = states

    def line(g):
        w = int((g.outcome == "win").sum()); l = int((g.outcome == "loss").sum())
        n = w + l
        return n, w, (w / n * 100 if n else 0), (w * RR - l)

    print("\n■ Ячейки направление × тип дня (сырые):")
    pooled_w = int((closed.outcome == "win").sum()); pooled_n = len(closed)
    prior = pooled_w / pooled_n
    cells = {}
    for (dr, st), g in closed.groupby(["direction", "dt_state"]):
        n, w, wr, pnl = line(g)
        shr = (w + prior * ALPHA) / (n + ALPHA) * 100
        cells[(dr, st)] = (n, wr, shr, pnl)
        print(f"  {dr:<5} {st:<11} n={n:>3}  WR={wr:>5.1f}%  shrunk={shr:>5.1f}%  PnL={pnl:>+7.1f}R")

    print(f"\n  база: WR {prior*100:.1f}% ({pooled_w}/{pooled_n}), PnL "
          f"{pooled_w*RR - (pooled_n-pooled_w):+.1f}R")

    ct = closed[((closed.direction == "LONG") & (closed.dt_state == "TREND_DOWN")) |
                ((closed.direction == "SHORT") & (closed.dt_state == "TREND_UP"))]
    co = closed[((closed.direction == "LONG") & (closed.dt_state == "TREND_UP")) |
                ((closed.direction == "SHORT") & (closed.dt_state == "TREND_DOWN"))]
    for lab, g in [("COUNTER-TREND в зону", ct), ("CONTINUATION", co)]:
        n, w, wr, pnl = line(g)
        print(f"  {lab:<22} n={n:>3}  WR={wr:>5.1f}%  PnL={pnl:>+7.1f}R")

    # годовая стабильность counter-trend эффекта (kill-критерий стен)
    print("\n■ Counter-trend vs остальное — по годам:")
    closed["year"] = closed.signal_time.dt.year
    closed["is_ct"] = (((closed.direction == "LONG") & (closed.dt_state == "TREND_DOWN")) |
                       ((closed.direction == "SHORT") & (closed.dt_state == "TREND_UP")))
    for y, g in closed.groupby("year"):
        a = g[g.is_ct]; b = g[~g.is_ct]
        wa = (a.outcome == "win").mean() * 100 if len(a) else float("nan")
        wb = (b.outcome == "win").mean() * 100 if len(b) else float("nan")
        print(f"  {y}: CT {wa:>5.1f}% (n={len(a):>3})  vs прочее {wb:>5.1f}% (n={len(b):>3})")

    out = HERE / "output" / "etap_236_cells_112.csv"
    closed.to_csv(out, index=False)
    print(f"\nSaved: {out}")
    print("\n# Для signal_context.CELL_STATS_112 (shrunk, n):")
    for (dr, st), (n, wr, shr, _) in sorted(cells.items()):
        if st in ("TREND_UP", "TREND_DOWN") and n >= 15:
            print(f'    ("{dr}", "{st}"): "~{shr:.0f}% WR (n={n}, сглаж.)",')


if __name__ == "__main__":
    main()
