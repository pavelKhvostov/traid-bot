"""run_3candles_sweep с немедленным входом (без pullback-лимита).

Тестируем:
  ENTRY:
    A. Market на C3.close (момент формирования паттерна)
    B. Open next bar (более реалистично — у нас есть бар после C3 close)
    C. Canon pullback (для сравнения)

  TP:
    T1. fixed RR = 1.0R
    T2. fixed RR = 1.5R
    T3. fixed RR = 2.0R
    T4. fixed RR = 3.0R
    T5. extension: |C2.high − C3.low| проекция от entry

  SL: всегда C2 extreme (high для SHORT, low для LONG)

Симулятор: 1m intra-bar, pessimistic (SL раньше TP в баре).
"""
from __future__ import annotations
import csv, pathlib, sys, bisect, time
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle

MSK = timezone(timedelta(hours=3))
MS_M = 60_000
TF1H = 60*MS_M
DATA_DIR = pathlib.Path.home() / "traid-bot/data"
ASSETS = [("BTC", "BTCUSDT_1m_vic_vadim.csv"),
          ("ETH", "ETHUSDT_1m_vic_vadim.csv"),
          ("SOL", "SOLUSDT_1m_vic_vadim.csv")]
WINDOW_YEARS = 6
EXIT_TIMEOUT_MIN = 30 * 60

def load(fn):
    rows = []
    with (DATA_DIR / fn).open() as f:
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

print("Loading...")
asset_data = {}
for asset, fn in ASSETS:
    t0 = time.time()
    m1 = load(fn)
    last_ts = m1[-1][0]
    win_start = last_ts - WINDOW_YEARS*365*24*3600*1000
    bars1h = [b for b in agg(m1, TF1H) if b[0] >= win_start]
    m1_ts = [r[0] for r in m1]
    asset_data[asset] = {'m1': m1, 'm1_ts': m1_ts, 'bars1h': bars1h}
    print(f"  {asset}: {len(m1)} 1m, {len(bars1h)} 1h ({time.time()-t0:.1f}s)")

# Уже-в-позиции симулятор (entry уже выполнен; check SL/TP)
def walk_after_fill(direction, entry, sl, tp, start_idx, m1):
    n = len(m1)
    risk = abs(sl - entry); reward = abs(entry - tp)
    if risk == 0: return ('invalid', 0.0, 0.0)
    rr = reward / risk
    end = min(start_idx + EXIT_TIMEOUT_MIN, n)
    if direction == 'short':
        for j in range(start_idx, end):
            bj = m1[j]
            if bj[2] >= sl: return ('loss', -1.0, rr)
            if bj[3] <= tp: return ('win', rr, rr)
    else:
        for j in range(start_idx, end):
            bj = m1[j]
            if bj[3] <= sl: return ('loss', -1.0, rr)
            if bj[2] >= tp: return ('win', rr, rr)
    j = min(end-1, n-1); bj = m1[j]
    r = (entry - bj[4]) / risk if direction=='short' else (bj[4] - entry) / risk
    return ('timeout', r, rr)

def scan(ad, entry_mode, tp_mode, wick_ratio=2.5):
    """entry_mode in {'close', 'next_open'},  tp_mode = float (RR) или 'ext' """
    bars = ad['bars1h']; m1 = ad['m1']; m1_ts = ad['m1_ts']
    cans = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars]
    trades = []
    for i in range(2, len(cans)-1):
        c1, c2, c3 = cans[i-2], cans[i-1], cans[i]
        next_open_ms = bars[i][0] + TF1H
        # SHORT
        ok_s = c1.is_bear and c2.is_bear and c3.is_bear and c2.high > c1.high
        if ok_s:
            wick = c2.high - max(c2.open, c2.close); body = abs(c2.open - c2.close)
            if body == 0 or wick < wick_ratio*body: ok_s = False
        if ok_s:
            sl = c2.high
            if entry_mode == 'close':
                entry = c3.close
                start_idx = bisect.bisect_left(m1_ts, next_open_ms)
            else:
                # next_open: смотрим открытие бара i+1
                if i+1 >= len(bars): continue
                next_open_idx = bisect.bisect_left(m1_ts, next_open_ms)
                if next_open_idx >= len(m1): continue
                entry = m1[next_open_idx][1]  # open of 1m bar = open of 1h bar
                start_idx = next_open_idx
            risk = sl - entry
            if risk > 0:
                if tp_mode == 'ext':
                    proj = c2.high - c3.low
                    tp = entry - proj
                else:
                    tp = entry - tp_mode * risk
                status, r_mult, rr = walk_after_fill('short', entry, sl, tp, start_idx, m1)
                trades.append({'status':status, 'r_mult':r_mult, 'planned_rr':rr, 'dir':'short'})
        # LONG
        ok_l = c1.is_bull and c2.is_bull and c3.is_bull and c2.low < c1.low
        if ok_l:
            wick = min(c2.open, c2.close) - c2.low; body = abs(c2.open - c2.close)
            if body == 0 or wick < wick_ratio*body: ok_l = False
        if ok_l:
            sl = c2.low
            if entry_mode == 'close':
                entry = c3.close
                start_idx = bisect.bisect_left(m1_ts, next_open_ms)
            else:
                if i+1 >= len(bars): continue
                next_open_idx = bisect.bisect_left(m1_ts, next_open_ms)
                if next_open_idx >= len(m1): continue
                entry = m1[next_open_idx][1]
                start_idx = next_open_idx
            risk = entry - sl
            if risk > 0:
                if tp_mode == 'ext':
                    proj = c3.high - c2.low
                    tp = entry + proj
                else:
                    tp = entry + tp_mode * risk
                status, r_mult, rr = walk_after_fill('long', entry, sl, tp, start_idx, m1)
                trades.append({'status':status, 'r_mult':r_mult, 'planned_rr':rr, 'dir':'long'})
    return trades

def metrics(trades):
    f = [t for t in trades if t['status'] not in ('no_fill','invalid')]
    if not f: return None
    wins = sum(1 for t in f if t['status']=='win')
    totr = sum(t['r_mult'] for t in f)
    return {'n':len(f),'wr':wins/len(f)*100,'totr':totr,'rpt':totr/len(f)}

def cross(label, **kw):
    print(f"  {label}")
    print(f"    {'Asset':<6} {'n':>5} {'WR%':>6} {'TotR':>8} {'R/tr':>7}")
    avgs = []
    for asset, ad in asset_data.items():
        m = metrics(scan(ad, **kw))
        if m is None: continue
        print(f"    {asset:<6} {m['n']:>5} {m['wr']:>5.1f}% {m['totr']:>+8.1f} {m['rpt']:>+7.3f}")
        avgs.append(m['rpt'])
    if avgs: print(f"    avg R/tr: {np.mean(avgs):+.3f}   min: {min(avgs):+.3f}")
    print()

print(f"\n{'='*80}\nA. Entry на C3.close (market):\n{'='*80}")
for rr in [1.0, 1.5, 2.0, 3.0]:
    cross(f"close + TP {rr}R", entry_mode='close', tp_mode=rr)
cross("close + TP extension (|C2-C3|)", entry_mode='close', tp_mode='ext')

print(f"\n{'='*80}\nB. Entry next bar open (более реалистично):\n{'='*80}")
for rr in [1.0, 1.5, 2.0, 3.0]:
    cross(f"next_open + TP {rr}R", entry_mode='next_open', tp_mode=rr)
cross("next_open + TP extension (|C2-C3|)", entry_mode='next_open', tp_mode='ext')

print(f"\n{'='*80}\nC. С фильтром wick≥3.5:\n{'='*80}")
for rr in [1.5, 2.0]:
    cross(f"next_open + TP {rr}R + wick≥3.5", entry_mode='next_open', tp_mode=rr, wick_ratio=3.5)
