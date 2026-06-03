"""Backtest run_3candles_sweep на всех TF: 1h, 2h, 4h, 6h, 8h, 12h, D."""
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

last_ts = rows[-1][0]
window_start = last_ts - 6*365*24*3600*1000

def backtest_tf(tf_label, tfms, entry_timeout_bars=6, exit_timeout_bars=30):
    bars = agg(rows, tfms)
    cans = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars]
    # Detect
    patterns = []
    for i in range(2, len(bars)):
        if bars[i][0] < window_start: continue
        r = detect_run_3candles_sweep(cans[i-2], cans[i-1], cans[i])
        if r is None: continue
        patterns.append({"i":i, "result":r})
    # Simulate
    trades = []
    for p in patterns:
        r = p["result"]; ic3 = p["i"]
        entry, sl, tp = r.entry, r.sl, r.tp
        direction = r.direction
        fill_idx = None
        for j in range(ic3+1, min(ic3+1+entry_timeout_bars, len(bars))):
            bj = bars[j]
            if direction == "short":
                if bj[2] >= entry: fill_idx = j; break
            else:
                if bj[3] <= entry: fill_idx = j; break
        if fill_idx is None:
            trades.append({"status":"no_fill", "r_mult":0.0, "direction":direction})
            continue
        risk = abs(sl - entry); reward = abs(entry - tp)
        if risk == 0:
            trades.append({"status":"invalid", "r_mult":0.0, "direction":direction})
            continue
        status = "open"; r_mult = None
        for j in range(fill_idx, min(fill_idx+exit_timeout_bars, len(bars))):
            bj = bars[j]; bj_o = bj[1]
            if direction == "short":
                sl_hit = bj[2] >= sl; tp_hit = bj[3] <= tp
            else:
                sl_hit = bj[3] <= sl; tp_hit = bj[2] >= tp
            if sl_hit and tp_hit:
                if abs(bj_o - sl) < abs(bj_o - tp):
                    status = "loss"; r_mult = -1.0
                else:
                    status = "win"; r_mult = reward/risk
                break
            if sl_hit: status = "loss"; r_mult = -1.0; break
            if tp_hit: status = "win"; r_mult = reward/risk; break
        if status == "open":
            bj = bars[min(fill_idx+exit_timeout_bars-1, len(bars)-1)]
            if direction == "short": r_mult = (entry - bj[4]) / risk
            else: r_mult = (bj[4] - entry) / risk
            status = "timeout"
        trades.append({"status":status, "r_mult":r_mult, "direction":direction})
    return patterns, trades

print(f"\n{'='*100}")
print(f"{'TF':<5} {'patterns':>9} {'filled':>7} {'WR%':>6} {'TotR':>8} {'R/tr':>7}  | {'S WR%':>6} {'S TotR':>7} | {'L WR%':>6} {'L TotR':>7}")
print(f"{'='*100}")
TFS = [
    ("1h", 60*MS_M, 6),
    ("2h", 2*60*MS_M, 6),
    ("4h", 4*60*MS_M, 6),
    ("6h", 6*60*MS_M, 6),
    ("8h", 8*60*MS_M, 6),
    ("12h", 12*60*MS_M, 6),
    ("D", 24*60*MS_M, 6),
]
results = []
for tf_label, tfms, etb in TFS:
    patterns, trades = backtest_tf(tf_label, tfms, entry_timeout_bars=etb)
    filled = [t for t in trades if t["status"] not in ("no_fill","invalid")]
    if not filled:
        print(f"{tf_label:<5} {len(patterns):>9} {0:>7}"); continue
    wr = sum(1 for t in filled if t["status"]=="win")/len(filled)*100
    totr = sum(t["r_mult"] for t in filled)
    avg = totr/len(filled)
    short = [t for t in filled if t["direction"]=="short"]
    long_t = [t for t in filled if t["direction"]=="long"]
    swr = sum(1 for t in short if t["status"]=="win")/len(short)*100 if short else 0
    stot = sum(t["r_mult"] for t in short)
    lwr = sum(1 for t in long_t if t["status"]=="win")/len(long_t)*100 if long_t else 0
    ltot = sum(t["r_mult"] for t in long_t)
    print(f"{tf_label:<5} {len(patterns):>9} {len(filled):>7} {wr:>5.1f}% {totr:>+8.1f} {avg:>+7.3f}  | {swr:>5.1f}% {stot:>+7.1f} | {lwr:>5.1f}% {ltot:>+7.1f}")
    results.append((tf_label, len(filled), wr, totr, avg))

# Detail per TF
print(f"\n{'='*100}\nДеталь по топ TF (≥ 50 filled):\n{'='*100}")
for tf_label, n, wr, totr, avg in sorted(results, key=lambda x: -x[4]):
    if n < 50: continue
    print(f"  {tf_label}: n={n}, WR={wr:.1f}%, TotR={totr:+.1f}, R/tr={avg:+.3f}, freq/год={n/6:.1f}")
