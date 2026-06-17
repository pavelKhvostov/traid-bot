"""etap_239 — liq-3 pd_sweep_state: снятие вчерашних H/L × ячейки 1.1.1 (research-bet v2.0).

ГИПОТЕЗА (ICT/SMC + наша победа SWEPT): reversal-вход 1.1.1 сильнее, когда
дневная ликвидность уже снята: SHORT после свипа PDH (стоп-ран сверху сделан),
LONG после свипа PDL. Если ликвидность НЕ снята — цена может ещё сходить за ней
против позиции.

СТРОГИЙ ПРОТОКОЛ (ужесточение vs etap_231/232):
  - момент решения = signal_time + 15m (закрытие c2 entry-FVG);
  - 1h-бары дня: только ЗАКРЫТЫЕ к решению (open+1h <= decision) — в etap_232
    включался текущий формирующийся час (до 15 мин будущего!);
  - 15m-бары: open+15m <= decision;
  - PDH/PDL: вчерашний ЗАКРЫТЫЙ день (resample 1h, день < дня сигнала).

ЗАОДНО: перепроверка ячеек etap_232 под строгим протоколом (integrity-check).

KILL-КРИТЕРИИ (заранее):
  1) |эффект| свипа < 5пп WR между состояниями ИЛИ инверсия знака по годам → kill;
  2) пересечение со state-ячейками: если свип не добавляет к day-type → не в продукт.

Запуск: venv/Scripts/python.exe research/daily_engine/etap_239_pd_sweep_state.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
import etap_217_daytype_layer as L

H1 = ROOT / "data" / "BTCUSDT_1h_orderflow.csv"
M15 = ROOT / "data" / "BTCUSDT_15m.csv"
TRADES = HERE / "output" / "etap_232_daytype_filter_on_111_floating.csv"


def wr_line(g, rcol="R"):
    n = len(g); w = int((g[rcol] > 0).sum())
    pnl = float(g[rcol].sum())
    return f"n={n:>3} WR={w/max(n,1)*100:>5.1f}% PnL={pnl:>+7.1f}R"


def main():
    h1 = pd.read_csv(H1, index_col=0, parse_dates=True)
    if h1.index.tz is None: h1.index = h1.index.tz_localize("UTC")
    m15 = pd.read_csv(M15, index_col=0, parse_dates=True)
    if m15.index.tz is None: m15.index = m15.index.tz_localize("UTC")
    R = L.build(h1).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    M = L.fit_per_hour(R[R.day < L.CUTOFF])

    daily = h1.resample("1D").agg({"high": "max", "low": "min"})
    pdh = daily["high"].shift(1); pdl = daily["low"].shift(1)   # вчерашние H/L

    d = pd.read_csv(TRADES, parse_dates=["signal_time"])
    print(f"Сделок 1.1.1 floating OOS: {len(d)} | 15m покрытие с {m15.index.min().date()}")

    states_strict, sweeps = [], []
    for _, s in d.iterrows():
        t = s.signal_time; day = t.normalize()
        decision = t + pd.Timedelta(minutes=15)
        # day-state СТРОГО по закрытым 1h
        bars = h1[(h1.index.normalize() == day) & (h1.index + pd.Timedelta(hours=1) <= decision)]
        if len(bars) < L.IB + 2:
            st = "FORMING"
        else:
            dec, _ = L.daytype_nowcast(bars, M); st = dec[-1][1]
        states_strict.append(st)
        # sweep-state по закрытым 15m
        b15 = m15[(m15.index.normalize() == day) & (m15.index + pd.Timedelta(minutes=15) <= decision)]
        PH, PL = pdh.get(day, np.nan), pdl.get(day, np.nan)
        if len(b15) == 0 or PH != PH:
            sweeps.append("NA"); continue
        hi, lo, cl = b15["high"].max(), b15["low"].min(), b15["close"].iloc[-1]
        if s.direction == "SHORT":
            sw = "no_sweep" if hi <= PH else ("swept_rejected" if cl < PH else "swept_above")
        else:
            sw = "no_sweep" if lo >= PL else ("swept_reclaimed" if cl > PL else "swept_below")
        sweeps.append(sw)
    d["st_strict"] = states_strict
    d["sweep"] = sweeps
    d["year"] = d.signal_time.dt.year

    # ---------- 0. Integrity: ячейки etap_232 под строгим протоколом ----------
    print("\n" + "=" * 74)
    print("0. INTEGRITY: ячейки direction×day-type под СТРОГИМ протоколом (vs etap_232)")
    print("=" * 74)
    agree = (d.st_strict == d.dt_state).mean()
    print(f"  совпадение state strict vs old: {agree*100:.0f}%")
    for (dr, st), g in d.groupby(["direction", "st_strict"]):
        if st in ("TREND_UP", "TREND_DOWN") and len(g) >= 5:
            print(f"  {dr:<5} {st:<11} {wr_line(g)}")
    ct = d[((d.direction == "LONG") & (d.st_strict == "TREND_DOWN")) |
           ((d.direction == "SHORT") & (d.st_strict == "TREND_UP"))]
    print(f"  COUNTER-TREND строгий: {wr_line(ct)}  (etap_232 было: n=88 72.7% +59.9R)")

    # ---------- 1. Ячейки по sweep-state ----------
    print("\n" + "=" * 74)
    print("1. ЯЧЕЙКИ ПО SWEEP-STATE (вчерашние H/L)")
    print("=" * 74)
    for dr in ("SHORT", "LONG"):
        sub = d[d.direction == dr]
        print(f"  {dr} (ликвидность {'PDH сверху' if dr=='SHORT' else 'PDL снизу'}):")
        for sw, g in sub.groupby("sweep"):
            print(f"    {sw:<16} {wr_line(g)}")

    # ---------- 2. Годовая стабильность главного контраста ----------
    print("\n2. Свип сделан (любое swept_*) vs no_sweep — по годам:")
    d["swept_any"] = d.sweep.str.startswith("swept")
    for y, g in d.groupby("year"):
        a, b = g[g.swept_any], g[~g.swept_any & (g.sweep != "NA")]
        wa = (a.R > 0).mean() * 100 if len(a) else float("nan")
        wb = (b.R > 0).mean() * 100 if len(b) else float("nan")
        print(f"  {y}: swept {wa:>5.1f}% (n={len(a):>3}) | no_sweep {wb:>5.1f}% (n={len(b):>3})")

    # ---------- 3. Пересечение с day-type ячейками ----------
    print("\n3. Пересечение: counter-trend ячейка × sweep:")
    for sw, g in ct.groupby("sweep"):
        print(f"    CT × {sw:<16} {wr_line(g)}")

    out = HERE / "output" / "etap_239_pd_sweep.csv"
    d.to_csv(out, index=False)
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
