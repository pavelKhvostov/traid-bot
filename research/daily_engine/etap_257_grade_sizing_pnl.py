"""etap_257 - СКОЛЬКО ДЕНЕГ даёт грейд как правило размера (vs плоская ставка).

Та же дедуп-книга 1.1.1 SWEPT (BTC, fixed RR=2.2, approved live). Для каждой сделки
считаем signal_grade (signal_context) ПО ФИЧАМ НА ВХОДЕ и применяем правила размера:

  FLAT        : 1R риска на каждую сделку (как сейчас в live)
  SKIP_WEAK   : net>=0 -> 1R, net<0 -> пропуск (0)
  TIERED      : net>=1 -> 1.0R, net=0 -> 0.75R, net=-1 -> 0.5R, net<=-2 -> 0 (пропуск)

Метрики: ΣR, R/задействованную сделку, число сделок, equity-кривая в R, макс.
просадка (R), ΣR/maxDD, и по годам. Перевод в % к депозиту: при риске q% на 1R
прирост депозита ~ ΣR*q% (простая аппроксимация, без компаундинга).

ЧЕСТНЫЙ КАВЕАТ: грейд СКОНСТРУИРОВАН на этой же книге (etap_249), значит in-sample —
это ВЕРХНЯЯ ОЦЕНКА. Реальный тест — разбивка по годам (грейд = фикс-функция, не
переобучается, но его структуру выбирали, видя эти данные). BTC-only (на ETH/SOL не
переносится, etap_250).

Запуск: set PYTHONIOENCODING=utf-8
        venv/Scripts/python.exe research/daily_engine/etap_257_grade_sizing_pnl.py
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
from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1_floating import (detect_signals_111, check_swept,
                                                 build_entry_sl, simulate_floating,
                                                 build_score_series)
import etap_217_daytype_layer as L
from signal_context import signal_grade

RR = 2.2
RISK_PCT_PER_R = 1.0   # сколько % депозита рискуем на 1R (для перевода в %)


def load_book():
    df_1d = load_df("BTCUSDT", "1d"); df_4h = load_df("BTCUSDT", "4h"); df_1h = load_df("BTCUSDT", "1h")
    df_12h = compose_from_base(df_1h, "12h"); df_6h = compose_from_base(df_1h, "6h"); df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df("BTCUSDT", "15m"); df_1m = load_df("BTCUSDT", "1m"); df_20m = compose_from_base(df_1m, "20m")
    for d in (df_1h, df_1m):
        if d.index.tz is None: d.index = d.index.tz_localize("UTC")
    print("[detect] 1.1.1 + SWEPT (BTC)...")
    signals = detect_signals_111(df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m)
    swept = [s for s in signals if check_swept(s, df_1h, df_2h)]
    seen, dedup = set(), []
    for s in swept:
        k = (pd.Timestamp(s["signal_time"]).isoformat(), s["direction"], tuple(s["fvg_zone"]))
        if k in seen: continue
        seen.add(k); dedup.append(s)
    print(f"  raw {len(signals)} -> SWEPT {len(swept)} -> dedup {len(dedup)}")
    score_long, score_short = build_score_series(df_1h)
    daily = df_1h.resample("1D").agg({"open": "first", "high": "max", "low": "min"})
    dmed = ((daily.high - daily.low) / daily.open).rolling(20).median().shift(1)

    rows = []
    for s in dedup:
        res = simulate_floating(s, df_1m, df_1h, score_long, score_short,
                                R_cap=RR, threshold=-1e9, confirm=10**6, max_hold_days=3650)
        if res is None or res.outcome not in ("win", "loss"):
            continue
        t = pd.Timestamp(s["signal_time"]); t = t.tz_localize("UTC") if t.tz is None else t
        day = t.normalize(); direction = s["direction"]
        entry, sl = build_entry_sl(s) or (np.nan, np.nan)
        risk_pct = abs(entry - sl) / entry * 100 if entry else np.nan
        # day-type state + gauge считаем во ВТОРОМ проходе через единую модель
        rows.append(dict(t=t, day=day, direction=direction, win=int(res.outcome == "win"),
                         risk_pct=risk_pct, fvg_tf=s.get("fvg_tf"), hour=t.hour,
                         dmed=dmed.reindex([day]).iloc[0] if day in dmed.index else np.nan))
    # единая day-type модель + gauge (после сбора, чтобы не фитить в цикле)
    M = L.fit_per_hour(L.build(df_1h[df_1h.index < L.CUTOFF]).replace([np.inf, -np.inf], np.nan).fillna(0.0))
    out = []
    for r in rows:
        bars = df_1h[(df_1h.index.normalize() == r["day"]) & (df_1h.index <= r["t"])]
        state = "FORMING"
        if len(bars) >= L.IB + 2:
            dec, _ = L.daytype_nowcast(bars, M); state = dec[-1][1]
        gauge = np.nan
        if len(bars) and r["dmed"] and r["dmed"] > 0:
            gauge = (bars["high"].max() - bars["low"].min()) / bars["open"].iloc[0] / r["dmed"]
        g = signal_grade(r["direction"], state, r["risk_pct"], r["fvg_tf"], r["hour"], gauge)
        out.append(dict(t=r["t"], year=r["t"].year, win=r["win"], net=g["net"],
                        label=g["label"], state=state))
    return pd.DataFrame(out).sort_values("t").reset_index(drop=True)


def equity_stats(sizes, wins):
    """sizes, wins (0/1) -> (ΣR, n_deployed, R/deployed, maxDD_R)."""
    r = np.where(np.array(wins) == 1, RR, -1.0) * np.array(sizes, float)
    eq = np.cumsum(r)
    peak = np.maximum.accumulate(eq)
    dd = float((peak - eq).max()) if len(eq) else 0.0
    n_dep = int((np.array(sizes) > 0).sum())
    sr = float(r.sum())
    return sr, n_dep, (sr / n_dep if n_dep else 0.0), dd


def size_flat(net):    return 1.0
def size_skip(net):    return 1.0 if net >= 0 else 0.0
def size_tier(net):    return {1: 1.0, 0: 0.75, -1: 0.5}.get(net, 0.0) if net < 1 else 1.0


def main():
    book = load_book()
    n = len(book); w = book.win.sum()
    print(f"\nкнига: n={n}  WR {w/n*100:.1f}%  ({book.t.min().date()}..{book.t.max().date()})  BTC fixed RR=2.2")
    print("распределение грейда:", dict(book.net.value_counts().sort_index()))

    rules = [("FLAT (как сейчас)", size_flat), ("SKIP_WEAK (net>=0)", size_skip),
             ("TIERED (1/.75/.5/0)", size_tier)]
    print("\n" + "=" * 86)
    print(f"{'правило':<22}{'сделок':>8}{'ΣR':>9}{'R/сделку':>10}{'maxDD':>9}{'ΣR/DD':>8}{'~%депо@1%':>11}")
    print("-" * 86)
    base_sr = None
    for name, fn in rules:
        sizes = book.net.map(fn).values
        sr, ndep, rpt, dd = equity_stats(sizes, book.win.values)
        if base_sr is None: base_sr = sr
        print(f"{name:<22}{ndep:>8}{sr:>+9.1f}{rpt:>+10.3f}{dd:>+9.1f}{(sr/dd if dd>0 else float('nan')):>8.2f}"
              f"{sr*RISK_PCT_PER_R:>+10.1f}%")
    print("=" * 86)
    print(f"(ΣR FLAT = {base_sr:+.1f}R — текущий live. % к депо = ΣR при риске {RISK_PCT_PER_R:.0f}% на 1R, без компаундинга.)")

    print("\n--- ПО ГОДАМ (честная проверка in-sample грейда) ---")
    print(f"  {'год':>5}{'n':>5}{'WR':>7}   FLAT ΣR / SKIP ΣR / TIER ΣR   (skip-vs-flat)")
    for yr, gy in book.groupby("year"):
        wins = gy.win.values
        f_sr, *_ = equity_stats(gy.net.map(size_flat).values, wins)
        s_sr, sdep, *_ = equity_stats(gy.net.map(size_skip).values, wins)
        t_sr, *_ = equity_stats(gy.net.map(size_tier).values, wins)
        better = "+" if s_sr > f_sr else ("=" if abs(s_sr-f_sr) < 1e-9 else "-")
        print(f"  {yr:>5}{len(gy):>5}{wins.mean()*100:>6.0f}%   {f_sr:>+6.1f} / {s_sr:>+6.1f} / {t_sr:>+6.1f}   ({better})")

    # сколько сделок грейд ОТСЕКАЕТ и какой у них WR
    weak = book[book.net < 0]
    print(f"\n  net<0 (грейд советует пропуск): n={len(weak)}  WR {weak.win.mean()*100:.1f}%  "
          f"их вклад при FLAT: {equity_stats([1]*len(weak), weak.win.values)[0]:+.1f}R")
    strong = book[book.net >= 0]
    print(f"  net>=0 (торгуем): n={len(strong)}  WR {strong.win.mean()*100:.1f}%  "
          f"ΣR {equity_stats([1]*len(strong), strong.win.values)[0]:+.1f}R")


if __name__ == "__main__":
    main()
