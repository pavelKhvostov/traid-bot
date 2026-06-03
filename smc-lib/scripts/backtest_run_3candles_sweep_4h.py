"""Backtest run_3candles_sweep на BTC 4h.

Алгоритм:
1. Detect pattern на close c3 (triple bear или triple bull).
2. Place limit order на entry-уровень после c3 close.
3. Wait до ENTRY_TIMEOUT_BARS 4h-баров для fill (цена должна вернуться в wick c2).
4. Если fill — открываем позицию. SL и TP оба статичны.
5. На каждом баре после fill: если SL hit → loss; если TP hit → win.
6. На баре где оба уровня в range → тай-брейк по distance to open (тот ближе исполнится первым).
   Если open уже за SL/TP → instant exit на open.

Метрики: trades, wins, losses, expired, WR, total R, R/trade.
"""
from __future__ import annotations
import csv, pathlib, sys
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle
from patterns.run_3candles_sweep.code import detect_run_3candles_sweep

CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
MS_M = 60_000
TF4H = 4*60*MS_M
ENTRY_TIMEOUT_BARS = 6     # 6 × 4h = 24h на pullback fill
EXIT_TIMEOUT_BARS = 30     # 30 × 4h = 5 дней на TP/SL

print("Loading 1m...")
rows = []
with CSV.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = datetime.fromisoformat(r[0])
        rows.append((int(t.timestamp()*1000), float(r[1]), float(r[2]), float(r[3]), float(r[4])))

def agg(d, tfms):
    out=[]; cb=None; o=h=l=c=0.0
    for ts,oo,hh,ll,cc in d:
        b = ts - (ts % tfms)
        if b != cb:
            if cb is not None: out.append((cb,o,h,l,c))
            cb=b; o,h,l,c=oo,hh,ll,cc
        else:
            h=max(h,hh); l=min(l,ll); c=cc
    if cb is not None: out.append((cb,o,h,l,c))
    return out

bars4 = agg(rows, TF4H)
print(f"  4h bars: {len(bars4)} (за всю историю)")

# Restrict to last 6y
last_ts = rows[-1][0]
window_start = last_ts - 6*365*24*3600*1000
bars4_w = [(i,b) for i,b in enumerate(bars4) if b[0] >= window_start]
print(f"  4h bars в окне 6y: {len(bars4_w)}")

cans = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars4]

# Detect patterns
patterns = []
for i in range(2, len(bars4)):
    if bars4[i][0] < window_start: continue
    r = detect_run_3candles_sweep(cans[i-2], cans[i-1], cans[i])
    if r is None: continue
    patterns.append({"i":i, "result":r})
print(f"\nDetected patterns: {len(patterns)}")
n_short = sum(1 for p in patterns if p["result"].direction == "short")
n_long  = sum(1 for p in patterns if p["result"].direction == "long")
print(f"  SHORT: {n_short}, LONG: {n_long}")

# Simulate trades
trades = []
for p in patterns:
    r = p["result"]; ic3 = p["i"]
    entry = r.entry; sl = r.sl; tp = r.tp
    direction = r.direction
    # 1) Wait for entry fill within ENTRY_TIMEOUT_BARS bars after c3
    fill_idx = None
    for j in range(ic3+1, min(ic3+1+ENTRY_TIMEOUT_BARS, len(bars4))):
        bj = bars4[j]
        if direction == "short":
            # entry below high (above current price); fill if price rises to entry
            if bj[2] >= entry:
                fill_idx = j; break
        else:
            # entry above low; fill if price drops to entry
            if bj[3] <= entry:
                fill_idx = j; break
    if fill_idx is None:
        trades.append({"pattern_idx":ic3, "direction":direction, "status":"no_fill",
                       "entry":entry, "sl":sl, "tp":tp, "r_mult":0.0})
        continue
    # 2) Check if SL or TP hit on the fill bar OR subsequent bars
    risk = abs(sl - entry)
    reward = abs(entry - tp)
    status = "open"; r_mult = None
    for j in range(fill_idx, min(fill_idx+EXIT_TIMEOUT_BARS, len(bars4))):
        bj = bars4[j]; bj_lo, bj_hi = bj[3], bj[2]
        if direction == "short":
            sl_hit = bj_hi >= sl
            tp_hit = bj_lo <= tp
        else:
            sl_hit = bj_lo <= sl
            tp_hit = bj_hi >= tp
        if sl_hit and tp_hit:
            # both in range — нужен тай-брейк. Берём ближайший к open бара
            bj_o = bj[1]
            if direction == "short":
                if abs(bj_o - sl) < abs(bj_o - tp):
                    status = "loss"; r_mult = -1.0
                else:
                    status = "win"; r_mult = reward / risk
            else:
                if abs(bj_o - sl) < abs(bj_o - tp):
                    status = "loss"; r_mult = -1.0
                else:
                    status = "win"; r_mult = reward / risk
            break
        if sl_hit:
            status = "loss"; r_mult = -1.0; break
        if tp_hit:
            status = "win"; r_mult = reward / risk; break
    if status == "open":
        # Timeout — close на last bar's close
        bj = bars4[min(fill_idx+EXIT_TIMEOUT_BARS-1, len(bars4)-1)]
        if direction == "short":
            r_mult = (entry - bj[4]) / risk
        else:
            r_mult = (bj[4] - entry) / risk
        status = "timeout"
    trades.append({"pattern_idx":ic3, "direction":direction, "status":status,
                   "entry":entry, "sl":sl, "tp":tp, "r_mult":r_mult})

# Stats
n = len(trades)
n_filled = sum(1 for t in trades if t["status"] != "no_fill")
wins = [t for t in trades if t["status"] == "win"]
losses = [t for t in trades if t["status"] == "loss"]
tmouts = [t for t in trades if t["status"] == "timeout"]
n_no_fill = sum(1 for t in trades if t["status"] == "no_fill")
total_r = sum(t["r_mult"] for t in trades)
wr = len(wins)/n_filled*100 if n_filled else 0
avg_r = total_r / n_filled if n_filled else 0

print(f"\n{'='*80}\nBacktest run_3candles_sweep на BTC 4h (6y)\n{'='*80}")
print(f"  Patterns detected:  {n}")
print(f"  Filled trades:      {n_filled}")
print(f"  No-fill (timeout):  {n_no_fill}")
print(f"  Wins:               {len(wins)}")
print(f"  Losses:             {len(losses)}")
print(f"  Timeouts (open):    {len(tmouts)}")
print(f"\n  WR (filled):        {wr:.1f}%")
print(f"  Total R:            {total_r:+.2f}")
print(f"  R / trade (filled): {avg_r:+.3f}")

# По направлениям
for dir_ in ["short", "long"]:
    sub = [t for t in trades if t["direction"] == dir_ and t["status"] != "no_fill"]
    if not sub: continue
    w = sum(1 for t in sub if t["status"]=="win")
    l = sum(1 for t in sub if t["status"]=="loss")
    tm = sum(1 for t in sub if t["status"]=="timeout")
    tot = sum(t["r_mult"] for t in sub)
    print(f"\n  {dir_.upper():>6}: filled={len(sub)} win={w} loss={l} timeout={tm} WR={w/len(sub)*100:.1f}% totalR={tot:+.2f}")

# Распределение r_mult
filled = [t["r_mult"] for t in trades if t["status"] != "no_fill"]
if filled:
    print(f"\n  R distribution: mean={np.mean(filled):+.3f}  median={np.median(filled):+.3f}  std={np.std(filled):.3f}")
    print(f"    min={min(filled):+.2f}  max={max(filled):+.2f}")

# Per year
print(f"\n  Patterns per year:")
patterns_by_year = {}
for p in patterns:
    yr = datetime.fromtimestamp(bars4[p["i"]][0]/1000, MSK).year
    patterns_by_year[yr] = patterns_by_year.get(yr, 0) + 1
for yr in sorted(patterns_by_year):
    print(f"    {yr}: {patterns_by_year[yr]}")
