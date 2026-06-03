"""run_3candles_sweep v3 (SHORT-only, wick≥3.5, TP=2.25R, entry=next_open) на BTC, все TF.

Exit timeout = 30 баров своего TF (т.е. ~30 часов на 1h, 30 дней на D).
Симулятор: 1m intra-bar, pessimistic.
"""
from __future__ import annotations
import csv, pathlib, sys, bisect, time
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle

MSK = timezone(timedelta(hours=3))
MS_M = 60_000
DATA = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
WINDOW_YEARS = 6
WICK_RATIO = 3.5
TP_R = 2.25

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
t0 = time.time()
m1 = load()
m1_ts = [r[0] for r in m1]
last_ts = m1[-1][0]
win_start = last_ts - WINDOW_YEARS*365*24*3600*1000
print(f"  {len(m1)} 1m bars, окно {WINDOW_YEARS}y ({time.time()-t0:.1f}s)")

def simulate_short(entry, sl, tp, start_idx, m1, exit_timeout_min):
    n = len(m1)
    risk = sl - entry
    if risk <= 0: return ('invalid', 0.0, 0.0, 0.0, 0)
    rr = (entry - tp) / risk
    end = min(start_idx + exit_timeout_min, n)
    mae = 0.0; mfe = 0.0
    for j in range(start_idx, end):
        bj = m1[j]
        adv = (bj[2] - entry) / risk
        fav = (entry - bj[3]) / risk
        if adv > mae: mae = adv
        if fav > mfe: mfe = fav
        if bj[2] >= sl: return ('loss', -1.0, mae, mfe, j-start_idx+1)
        if bj[3] <= tp: return ('win', rr, mae, mfe, j-start_idx+1)
    j = min(end-1, n-1); bj = m1[j]
    return ('timeout', (entry - bj[4])/risk, mae, mfe, end-start_idx)

def scan_tf(tfms):
    bars = [b for b in agg(m1, tfms) if b[0] >= win_start]
    cans = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars]
    exit_timeout_min = 30 * (tfms // MS_M)  # 30 баров на ТФ
    trades = []
    for i in range(2, len(cans)-1):
        c1, c2, c3 = cans[i-2], cans[i-1], cans[i]
        if not (c1.is_bear and c2.is_bear and c3.is_bear and c2.high > c1.high): continue
        wick = c2.high - max(c2.open, c2.close); body = abs(c2.open - c2.close)
        if body == 0: continue
        wb = wick/body
        if wb < WICK_RATIO: continue
        next_open_ms = bars[i][0] + tfms
        next_open_idx = bisect.bisect_left(m1_ts, next_open_ms)
        if next_open_idx >= len(m1): continue
        entry = m1[next_open_idx][1]
        sl = c2.high
        if sl <= entry: continue
        risk = sl - entry
        tp = entry - TP_R * risk
        year = datetime.fromtimestamp(bars[i][0]/1000, MSK).year
        s, r, mae, mfe, bars_to = simulate_short(entry, sl, tp, next_open_idx, m1, exit_timeout_min)
        trades.append({'status':s, 'r':r, 'mae':mae, 'mfe':mfe, 'bars':bars_to,
                       'year':year, 'wick_body':wb,
                       'entry_ms':next_open_ms, 'entry':entry, 'sl':sl, 'tp':tp})
    return trades, len(bars)

TFS = [('1h',60),('2h',120),('4h',240),('6h',360),('8h',480),('12h',720),('D',1440)]

print(f"\n{'='*95}")
print(f"BTC v3 SHORT-only (wick≥3.5, TP=2.25R, next_open):")
print(f"{'='*95}")
print(f"{'TF':<5} {'n_bars':>8} {'setups':>8} {'wins':>5} {'losses':>7} {'TO':>4} {'WR%':>6} {'R/tr':>7} {'TotR':>8} {'freq/yr':>9} {'R/yr':>7}")
print("-"*95)
results = []
for tf, mins in TFS:
    tfms = mins * MS_M
    trades, n_bars = scan_tf(tfms)
    if not trades:
        print(f"{tf:<5} {n_bars:>8}  (no setups)")
        continue
    n = len(trades)
    wins = sum(1 for t in trades if t['status']=='win')
    losses = sum(1 for t in trades if t['status']=='loss')
    timeouts = sum(1 for t in trades if t['status']=='timeout')
    totr = sum(t['r'] for t in trades)
    rpt = totr/n
    freq_yr = n / WINDOW_YEARS
    print(f"{tf:<5} {n_bars:>8} {n:>8} {wins:>5} {losses:>7} {timeouts:>4} {wins/n*100:>5.1f}% {rpt:>+7.3f} {totr:>+8.1f} {freq_yr:>9.1f} {totr/WINDOW_YEARS:>+7.2f}")
    results.append((tf, trades, n, wins, losses, totr, rpt))

# Per-year per TF
print(f"\n{'='*95}\nPER-YEAR TotR по TF (стабильность edge):\n{'='*95}")
years = sorted({t['year'] for tf, trades, *_ in results for t in trades})
print(f"  {'Year':<6}", end='')
for tf, *_ in results: print(f"{tf:>10}", end='')
print()
for y in years:
    line = f"  {y:<6}"
    for tf, trades, *_ in results:
        yt = [t for t in trades if t['year']==y]
        if yt:
            n = len(yt)
            tot = sum(t['r'] for t in yt)
            line += f"  {n:>2}/{tot:>+5.1f}"
        else:
            line += f"  {'-':>8}"
    print(line)

# MFE distribution per TF
print(f"\n{'='*95}\nMFE percentile по TF (где доходит выгодная цена?):\n{'='*95}")
print(f"  {'TF':<5} {'p25':>6} {'p50':>6} {'p75':>6} {'p90':>6} {'mean':>6} {'reach 2R %':>11} {'reach 3R %':>11}")
for tf, trades, *_ in results:
    mfes = [t['mfe'] for t in trades]
    p25, p50, p75, p90 = np.percentile(mfes, [25,50,75,90])
    r2 = sum(1 for t in trades if t['mfe']>=2.0)/len(trades)*100
    r3 = sum(1 for t in trades if t['mfe']>=3.0)/len(trades)*100
    print(f"  {tf:<5} {p25:>5.2f}R {p50:>5.2f}R {p75:>5.2f}R {p90:>5.2f}R {np.mean(mfes):>5.2f}R {r2:>10.1f}% {r3:>10.1f}%")

# TP scan на HTF — может другой TP лучше?
print(f"\n{'='*95}\nTP scan по TF (R/tr):\n{'='*95}")
print(f"  {'TF':<5}", end='')
for tp_r in [1.5, 2.0, 2.25, 2.5, 3.0, 4.0]:
    print(f"  TP{tp_r:>4}", end='')
print()
for tf, trades, *_ in results:
    line = f"  {tf:<5}"
    for tp_r in [1.5, 2.0, 2.25, 2.5, 3.0, 4.0]:
        # пересчёт каждой сделки по новому TP с тем же MAE/MFE логикой неточно;
        # делаем upper-bound: win if MFE≥tp_r and MAE<1, loss if MAE≥1, else timeout.r
        # Это та же pessimistic-приближение что раньше.
        n = len(trades); tot = 0.0
        for t in trades:
            if t['mae'] >= 1.0:
                tot -= 1.0
            elif t['mfe'] >= tp_r:
                tot += tp_r
            else:
                tot += t['r']  # actual timeout R
        line += f" {tot/n:>+7.3f}"
    print(line)
