"""Воронка количеств: 3-same-direction → +sweep → +wick фильтр.

Для BTC 6 лет, все TF, обе направления + раздельно.
"""
from __future__ import annotations
import csv, pathlib, sys, time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle

MSK = timezone(timedelta(hours=3))
MS_M = 60_000
DATA = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
WINDOW_YEARS = 6

def load():
    rows = []
    with DATA.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp()*1000), float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    return rows

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

print("Loading BTC 1m...")
t0=time.time(); m1 = load()
last_ts = m1[-1][0]
win_start = last_ts - WINDOW_YEARS*365*24*3600*1000
print(f"  ({time.time()-t0:.1f}s)\n")

TFS = [('1h',60),('2h',120),('4h',240),('6h',360),('8h',480),('12h',720),('D',1440)]

def funnel(tfms):
    bars = [b for b in agg(m1, tfms) if b[0] >= win_start]
    cans = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars]
    counts = {'bars': len(bars),
              's_3bear': 0, 's_3bear_sweep': 0,
              's_wick25': 0, 's_wick35': 0, 's_wick50': 0,
              'l_3bull': 0, 'l_3bull_sweep': 0,
              'l_wick25': 0, 'l_wick35': 0, 'l_wick50': 0}
    for i in range(2, len(cans)):
        c1, c2, c3 = cans[i-2], cans[i-1], cans[i]
        # SHORT (3 bear)
        if c1.is_bear and c2.is_bear and c3.is_bear:
            counts['s_3bear'] += 1
            if c2.high > c1.high:
                counts['s_3bear_sweep'] += 1
                wick = c2.high - max(c2.open, c2.close)
                body = abs(c2.open - c2.close)
                if body > 0:
                    r = wick/body
                    if r >= 2.5: counts['s_wick25'] += 1
                    if r >= 3.5: counts['s_wick35'] += 1
                    if r >= 5.0: counts['s_wick50'] += 1
        # LONG (3 bull)
        if c1.is_bull and c2.is_bull and c3.is_bull:
            counts['l_3bull'] += 1
            if c2.low < c1.low:
                counts['l_3bull_sweep'] += 1
                wick = min(c2.open, c2.close) - c2.low
                body = abs(c2.open - c2.close)
                if body > 0:
                    r = wick/body
                    if r >= 2.5: counts['l_wick25'] += 1
                    if r >= 3.5: counts['l_wick35'] += 1
                    if r >= 5.0: counts['l_wick50'] += 1
    return counts

print(f"BTC 6 лет — воронка фильтров (SHORT side, 3 bear):\n")
print(f"{'TF':<5} {'bars':>7} {'3bear':>6} {'+sweep':>7} {'+wick2.5':>9} {'+wick3.5':>9} {'+wick5.0':>9}")
print('-'*60)
results = {}
for tf, mins in TFS:
    c = funnel(mins * MS_M); results[tf] = c
    print(f"{tf:<5} {c['bars']:>7} {c['s_3bear']:>6} {c['s_3bear_sweep']:>7} {c['s_wick25']:>9} {c['s_wick35']:>9} {c['s_wick50']:>9}")

print(f"\nBTC 6 лет — воронка фильтров (LONG side, 3 bull):\n")
print(f"{'TF':<5} {'bars':>7} {'3bull':>6} {'+sweep':>7} {'+wick2.5':>9} {'+wick3.5':>9} {'+wick5.0':>9}")
print('-'*60)
for tf, mins in TFS:
    c = results[tf]
    print(f"{tf:<5} {c['bars']:>7} {c['l_3bull']:>6} {c['l_3bull_sweep']:>7} {c['l_wick25']:>9} {c['l_wick35']:>9} {c['l_wick50']:>9}")

print(f"\nBTC 6 лет — ВСЕГО (SHORT+LONG):\n")
print(f"{'TF':<5} {'bars':>7} {'3-same':>7} {'+sweep':>7} {'+wick2.5':>9} {'+wick3.5':>9} {'+wick5.0':>9} {'/год wick2.5':>12}")
print('-'*72)
for tf, mins in TFS:
    c = results[tf]
    total_3 = c['s_3bear'] + c['l_3bull']
    total_sweep = c['s_3bear_sweep'] + c['l_3bull_sweep']
    total_25 = c['s_wick25'] + c['l_wick25']
    total_35 = c['s_wick35'] + c['l_wick35']
    total_50 = c['s_wick50'] + c['l_wick50']
    per_year = total_25 / WINDOW_YEARS
    print(f"{tf:<5} {c['bars']:>7} {total_3:>7} {total_sweep:>7} {total_25:>9} {total_35:>9} {total_50:>9} {per_year:>11.1f}")
