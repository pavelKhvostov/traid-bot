"""run_3candles_sweep канон (твои настройки) на BTC, все TF.

SHORT: Entry = max(c2.o,c2.c) + 0.3 × upper_wick (pullback в wick)
       SL    = c2.high
       TP    = c3.low

LONG mirror.

Симулятор: 1m intra-bar (honest), pessimistic (SL раньше TP в баре).
Exit timeout = 30 баров своего TF.
Entry timeout = 6 баров своего TF (если не пришёл pullback — no_fill).
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
WICK_RATIO = 2.5          # канон
ENTRY_FRAC = 0.3          # канон: 0.3 × wick

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
t0 = time.time(); m1 = load(); m1_ts = [r[0] for r in m1]
last_ts = m1[-1][0]
win_start = last_ts - WINDOW_YEARS*365*24*3600*1000
print(f"  {len(m1)} 1m bars ({time.time()-t0:.1f}s)")

def simulate_1m(direction, entry, sl, tp, start_idx, m1, entry_timeout_min, exit_timeout_min):
    n = len(m1)
    fill_idx = None
    end_fill = min(start_idx + entry_timeout_min, n)
    if direction == 'short':
        for j in range(start_idx, end_fill):
            if m1[j][2] >= entry: fill_idx = j; break
    else:
        for j in range(start_idx, end_fill):
            if m1[j][3] <= entry: fill_idx = j; break
    if fill_idx is None: return ('no_fill', 0.0, 0.0)
    risk = abs(sl - entry); reward = abs(entry - tp)
    if risk == 0: return ('invalid', 0.0, 0.0)
    rr = reward / risk
    end_exit = min(fill_idx + exit_timeout_min, n)
    if direction == 'short':
        for j in range(fill_idx, end_exit):
            bj = m1[j]
            if bj[2] >= sl: return ('loss', -1.0, rr)
            if bj[3] <= tp: return ('win', rr, rr)
    else:
        for j in range(fill_idx, end_exit):
            bj = m1[j]
            if bj[3] <= sl: return ('loss', -1.0, rr)
            if bj[2] >= tp: return ('win', rr, rr)
    j = min(end_exit-1, n-1); bj = m1[j]
    r = (entry - bj[4])/risk if direction=='short' else (bj[4] - entry)/risk
    return ('timeout', r, rr)

def scan_tf(tfms, direction_filter=None):
    bars = [b for b in agg(m1, tfms) if b[0] >= win_start]
    cans = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars]
    tf_bars_per = tfms // MS_M
    exit_timeout_min = 30 * tf_bars_per
    entry_timeout_min = 6 * tf_bars_per
    trades = []
    for i in range(2, len(cans)-1):
        c1, c2, c3 = cans[i-2], cans[i-1], cans[i]
        next_open_ms = bars[i][0] + tfms
        start_1m = bisect.bisect_left(m1_ts, next_open_ms)
        if start_1m >= len(m1): continue
        for direction in ('short', 'long'):
            if direction_filter and direction != direction_filter: continue
            if direction == 'short':
                if not (c1.is_bear and c2.is_bear and c3.is_bear): continue
                if c2.high <= c1.high: continue
                wick = c2.high - max(c2.open, c2.close); body = abs(c2.open - c2.close)
                if body == 0 or wick < WICK_RATIO*body: continue
                entry = max(c2.open, c2.close) + ENTRY_FRAC * wick
                sl = c2.high; tp = c3.low
            else:
                if not (c1.is_bull and c2.is_bull and c3.is_bull): continue
                if c2.low >= c1.low: continue
                wick = min(c2.open, c2.close) - c2.low; body = abs(c2.open - c2.close)
                if body == 0 or wick < WICK_RATIO*body: continue
                entry = min(c2.open, c2.close) - ENTRY_FRAC * wick
                sl = c2.low; tp = c3.high
            risk = abs(sl - entry); reward = abs(entry - tp)
            if risk == 0: continue
            s, r, rr = simulate_1m(direction, entry, sl, tp, start_1m, m1, entry_timeout_min, exit_timeout_min)
            year = datetime.fromtimestamp(bars[i][0]/1000, MSK).year
            trades.append({'status':s, 'r':r, 'planned_rr':rr, 'dir':direction, 'year':year})
    return trades, len(bars)

TFS = [('1h',60),('2h',120),('4h',240),('6h',360),('8h',480),('12h',720),('D',1440)]

def report(title, direction_filter):
    print(f"\n{'='*100}\n{title}\n{'='*100}")
    print(f"{'TF':<5} {'setups':>7} {'filled':>7} {'no_fill':>8} {'WR%':>6} {'avgRR':>7} {'R/tr':>7} {'TotR':>8} {'freq/yr':>9} {'R/yr':>7}")
    print("-"*100)
    out = []
    for tf, mins in TFS:
        tfms = mins * MS_M
        trades, n_bars = scan_tf(tfms, direction_filter)
        if not trades:
            print(f"{tf:<5}  no setups"); continue
        n_total = len(trades)
        filled = [t for t in trades if t['status'] not in ('no_fill','invalid')]
        no_fill = sum(1 for t in trades if t['status']=='no_fill')
        if not filled:
            print(f"{tf:<5} {n_total:>7} {0:>7} {no_fill:>8}  (no fills)")
            continue
        wins = [t for t in filled if t['status']=='win']
        n_f = len(filled)
        wr = len(wins)/n_f*100
        avg_rr = np.mean([t['planned_rr'] for t in wins]) if wins else 0
        totr = sum(t['r'] for t in filled)
        rpt = totr/n_f
        freq = n_f/WINDOW_YEARS
        print(f"{tf:<5} {n_total:>7} {n_f:>7} {no_fill:>8} {wr:>5.1f}% {avg_rr:>6.2f} {rpt:>+7.3f} {totr:>+8.1f} {freq:>9.1f} {totr/WINDOW_YEARS:>+7.2f}")
        out.append((tf, trades, filled))
    return out

# ── BOTH directions (канон) ───────────────────────────────────────────────────
both = report("BTC канон (Entry=±0.3×wick, SL=C2 extreme, TP=C3 extreme, wick≥2.5) — ОБА направления", None)

# ── SHORT only ────────────────────────────────────────────────────────────────
shorts = report("BTC канон — ТОЛЬКО SHORT", 'short')

# ── LONG only ─────────────────────────────────────────────────────────────────
longs = report("BTC канон — ТОЛЬКО LONG", 'long')

# Per-year per TF (both directions)
print(f"\n{'='*100}\nPER-YEAR TotR (канон, оба направления):\n{'='*100}")
years = sorted({t['year'] for tf, trades, filled in both for t in filled})
print(f"  {'Year':<6}", end='')
for tf, _, _ in both: print(f"{tf:>11}", end='')
print()
for y in years:
    line = f"  {y:<6}"
    for tf, _, filled in both:
        yt = [t for t in filled if t['year']==y]
        if yt:
            n = len(yt); tot = sum(t['r'] for t in yt)
            line += f"  {n:>3}/{tot:>+5.1f}"
        else:
            line += f"  {'-':>9}"
    print(line)
