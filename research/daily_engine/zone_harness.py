"""Общий честный харнесс для zone-reaction стратегий (breaker / naked POC / vol-gate).

Один и тот же протокол судит все блоки одинаково:
  - вход = ЛИМИТ на уровне entry; активация = первый бар СТРОГО ПОСЛЕ time, где цена
    дотянулась до entry (LONG: low<=entry; SHORT: high>=entry), в пределах wait_bars
  - после активации гонка SL/TP вперёд (hold_bars); если в одном баре оба — SL ПЕРВЫМ
    (консервативно, без оптимистичного lookahead)
  - fixed RR: win=+RR, loss=-1; breakeven WR = 1/(1+RR) (для RR=2.2 -> 31.25%)

Отчёт: n, WR vs breakeven, ΣR, R/сделку, maxDD(R), ΣR/DD, по годам (ΣR>0 и
WR>breakeven в скольких годах) — год-стабильность как у 1.1.x.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def simulate(signals, df_exec, rr=2.2, wait_bars=240, hold_bars=720, entry_type="limit"):
    """signals: list dict(time, direction in {LONG,SHORT}, entry, sl, sym?).
    df_exec: OHLC с DatetimeIndex (UTC) — таймфрейм исполнения.
    entry_type: 'limit' (вход на возврате: LONG low<=entry / SHORT high>=entry) или
                'stop' (пробой: LONG high>=entry / SHORT low<=entry).
    Возврат DataFrame: time, direction, year, outcome(win/loss/no_fill/open), R."""
    if df_exec.index.tz is None:
        df_exec = df_exec.tz_localize("UTC")
    idx = df_exec.index
    H = df_exec["high"].values; Lo = df_exec["low"].values
    rows = []
    for s in signals:
        t = pd.Timestamp(s["time"])
        if t.tz is None: t = t.tz_localize("UTC")
        direction = s["direction"]; entry = float(s["entry"]); sl = float(s["sl"])
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        tp = entry + rr * risk if direction == "LONG" else entry - rr * risk
        start = int(np.searchsorted(idx.values, np.datetime64(t), side="right"))
        # активация (лимит = возврат к уровню; стоп = пробой уровня)
        act = None
        for j in range(start, min(start + wait_bars, len(df_exec))):
            if entry_type == "limit":
                hit = (Lo[j] <= entry) if direction == "LONG" else (H[j] >= entry)
            else:
                hit = (H[j] >= entry) if direction == "LONG" else (Lo[j] <= entry)
            if hit:
                act = j; break
        if act is None:
            rows.append(dict(time=t, direction=direction, year=t.year, outcome="no_fill", R=0.0))
            continue
        # гонка SL/TP
        outcome = "open"; R = 0.0
        for j in range(act, min(act + hold_bars, len(df_exec))):
            hi, lo = H[j], Lo[j]
            if direction == "LONG":
                if lo <= sl: outcome, R = "loss", -1.0; break
                if hi >= tp: outcome, R = "win", rr; break
            else:
                if hi >= sl: outcome, R = "loss", -1.0; break
                if lo <= tp: outcome, R = "win", rr; break
        rows.append(dict(time=t, direction=direction, year=t.year, outcome=outcome, R=R))
    return pd.DataFrame(rows)


def report(book, rr=2.2, title="", min_year_n=8):
    be = 1.0 / (1.0 + rr) * 100   # breakeven WR
    closed = book[book.outcome.isin(["win", "loss"])].copy()
    n = len(closed)
    print("\n" + "=" * 76)
    print(f"  {title}")
    print("=" * 76)
    nf = int((book.outcome == "no_fill").sum()); op = int((book.outcome == "open").sum())
    if n == 0:
        print(f"  закрытых 0 (no_fill {nf}, open {op})"); return None
    wr = closed.R.eq(rr).mean() * 100
    sr = closed.R.sum(); rpt = sr / n
    eq = np.cumsum(closed.sort_values("time").R.values)
    dd = float((np.maximum.accumulate(eq) - eq).max()) if len(eq) else 0.0
    print(f"  закрытых {n}  (no_fill {nf}, open {op})  | breakeven WR={be:.1f}%")
    print(f"  WR {wr:.1f}%  | SR {sr:+.1f}R  | R/сделку {rpt:+.3f}  | maxDD {dd:.1f}R  | "
          f"SR/DD {(sr/dd if dd>0 else float('nan')):.2f}")
    # по годам
    yrs = []
    print(f"  {'год':>6}{'n':>5}{'WR':>7}{'ΣR':>8}")
    for yr, g in closed.groupby("year"):
        if len(g) < min_year_n:
            continue
        ywr = g.R.eq(rr).mean() * 100; ysr = g.R.sum()
        yrs.append((ywr > be, ysr > 0))
        print(f"  {yr:>6}{len(g):>5}{ywr:>6.1f}%{ysr:>+7.1f}")
    if yrs:
        pos_sr = sum(1 for _, p in yrs if p); pos_wr = sum(1 for p, _ in yrs if p)
        print(f"  год-стаб: ΣR>0 в {pos_sr}/{len(yrs)} лет · WR>breakeven в {pos_wr}/{len(yrs)} лет")
    verdict = "KEEP-кандидат" if (rpt > 0.05 and n >= 30) else "слабо/KILL"
    print(f"  -> {verdict} (R/сделку {rpt:+.3f}, n={n})")
    return dict(n=n, wr=wr, sr=sr, rpt=rpt, dd=dd, years=yrs)
