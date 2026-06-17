"""etap_258 - переносится ли ГРЕЙД (и его sizing) на 1.1.2? Честный тест.

Грейд валидирован ТОЛЬКО на 1.1.1 (etap_249). Закон проекта: фильтры НЕ переносятся
между семействами (etap_236: для 1.1.2 counter-trend 52.4% vs continuation 58.3% —
ИНВЕРСИЯ относительно 1.1.1). Значит грейд-маркер «фейд в зону» для 1.1.2 может быть
МИНУСОВЫМ. Проверяем на книге 1.1.2 (positions_1_1_2_extended_final, 425 closed,
2023-2026, fixed RR=2.2): даёт ли грейд денежный сплит, и переносится ли отдельно
carrier «ширина SL».

Запуск: set PYTHONIOENCODING=utf-8
        venv/Scripts/python.exe research/daily_engine/etap_258_grade_on_112.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT))
import etap_217_daytype_layer as L
from signal_context import signal_grade, RISK_P33, RISK_P67

RR = 2.2
H1 = ROOT / "data" / "BTCUSDT_1h_orderflow.csv"
SIG = ROOT / "signals" / "positions_1_1_2_extended_final.csv"


def equity_stats(sizes, wins):
    r = np.where(np.array(wins) == 1, RR, -1.0) * np.array(sizes, float)
    eq = np.cumsum(r); peak = np.maximum.accumulate(eq)
    dd = float((peak - eq).max()) if len(eq) else 0.0
    n_dep = int((np.array(sizes) > 0).sum())
    return float(r.sum()), n_dep, (float(r.sum()) / n_dep if n_dep else 0.0), dd


def size_flat(net): return 1.0
def size_skip(net): return 1.0 if net >= 0 else 0.0
def size_tier(net): return {1: 1.0, 0: 0.75, -1: 0.5}.get(net, 0.0) if net < 1 else 1.0


def main():
    h1 = pd.read_csv(H1, index_col=0, parse_dates=True)
    if h1.index.tz is None: h1.index = h1.index.tz_localize("UTC")
    M = L.fit_per_hour(L.build(h1[h1.index < L.CUTOFF]).replace([np.inf, -np.inf], np.nan).fillna(0.0))
    daily = h1.resample("1D").agg({"open": "first", "high": "max", "low": "min"})
    dmed = ((daily.high - daily.low) / daily.open).rolling(20).median().shift(1)

    d = pd.read_csv(SIG)
    d["signal_time"] = pd.to_datetime(d["signal_time"], utc=True)
    d = d[d.outcome.isin(["win", "loss"])].copy()
    d = d.drop_duplicates(subset=["signal_time", "direction", "fvg_top", "fvg_bottom"]).reset_index(drop=True)

    rows = []
    for _, s in d.iterrows():
        t = s.signal_time; day = t.normalize()
        bars = h1[(h1.index.normalize() == day) & (h1.index <= t)]
        state = "FORMING"
        if len(bars) >= L.IB + 2:
            dec, _ = L.daytype_nowcast(bars, M); state = dec[-1][1]
        gauge = np.nan
        dm = dmed.reindex([day]).iloc[0] if day in dmed.index else np.nan
        if len(bars) and dm and dm > 0:
            gauge = (bars["high"].max() - bars["low"].min()) / bars["open"].iloc[0] / dm
        g = signal_grade(s.direction, state, float(s.risk_pct), s.fvg_tf, t.hour, gauge)
        rows.append(dict(t=t, year=t.year, win=int(s.outcome == "win"), net=g["net"],
                         state=state, risk_pct=float(s.risk_pct), direction=s.direction))
    b = pd.DataFrame(rows).sort_values("t").reset_index(drop=True)
    n = len(b); w = b.win.sum()
    print(f"\n1.1.2 книга: n={n}  WR {w/n*100:.1f}%  ({b.t.min().date()}..{b.t.max().date()})  fixed RR=2.2")
    print("распределение грейда:", dict(b.net.value_counts().sort_index()))

    print("\n" + "=" * 78)
    print(f"{'правило':<22}{'сделок':>8}{'SR':>9}{'R/сд':>9}{'maxDD':>9}{'SR/DD':>8}")
    print("-" * 78)
    for name, fn in [("FLAT", size_flat), ("SKIP (net>=0)", size_skip), ("TIERED", size_tier)]:
        sr, ndep, rpt, dd = equity_stats(b.net.map(fn).values, b.win.values)
        print(f"{name:<22}{ndep:>8}{sr:>+9.1f}{rpt:>+9.3f}{dd:>+9.1f}{(sr/dd if dd>0 else float('nan')):>8.2f}")
    print("=" * 78)

    # ключевой честный сплит: грейд net>=0 vs net<0 для 1.1.2
    hi = b[b.net >= 0]; lo = b[b.net < 0]
    print(f"\nГрейд-сплит 1.1.2:  net>=0  n={len(hi)} WR {hi.win.mean()*100:.1f}%   "
          f"net<0  n={len(lo)} WR {lo.win.mean()*100:.1f}%   "
          f"(для 1.1.1 было 60% vs 30%)")

    print("\n--- по годам (net>=0 WR vs net<0 WR; нужно стабильное >=) ---")
    for yr, gy in b.groupby("year"):
        a = gy[gy.net >= 0]; c = gy[gy.net < 0]
        print(f"  {yr}: n={len(gy):>3}  net>=0 {a.win.mean()*100 if len(a) else float('nan'):>5.1f}% (n={len(a):>3})  "
              f"net<0 {c.win.mean()*100 if len(c) else float('nan'):>5.1f}% (n={len(c):>3})")

    # отдельно: переносится ли carrier «ширина SL» (главный драйвер 1.1.1)?
    print("\n--- carrier 'ширина SL' на 1.1.2 (терцили 1.1.1: <=%.3f / >=%.3f) ---" % (RISK_P33, RISK_P67))
    for lab, mask in [("узкий SL", b.risk_pct <= RISK_P33),
                      ("средний SL", (b.risk_pct > RISK_P33) & (b.risk_pct < RISK_P67)),
                      ("широкий SL", b.risk_pct >= RISK_P67)]:
        g = b[mask]
        if len(g):
            yr = g.groupby("year").win.mean()
            print(f"  {lab:<11} n={len(g):>3}  WR {g.win.mean()*100:>5.1f}%  по годам {[round(x*100) for x in yr]}")


if __name__ == "__main__":
    main()
