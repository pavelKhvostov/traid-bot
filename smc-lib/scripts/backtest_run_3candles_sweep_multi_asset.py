"""Backtest run_3candles_sweep на BTC + ETH + SOL, multi-TF.
6 лет окно (или столько сколько есть данных)."""
from __future__ import annotations
import csv, pathlib, sys
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle
from patterns.run_3candles_sweep.code import detect_run_3candles_sweep

MSK = timezone(timedelta(hours=3))
MS_M = 60_000
DATA_DIR = pathlib.Path.home() / "traid-bot/data"
ASSETS = [("BTC", "BTCUSDT_1m_vic_vadim.csv"),
          ("ETH", "ETHUSDT_1m_vic_vadim.csv"),
          ("SOL", "SOLUSDT_1m_vic_vadim.csv")]
WINDOW_YEARS = 6

def load(filename):
    rows = []
    with (DATA_DIR / filename).open() as f:
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

def bt(rows, tfms, etb=6, xtb=30):
    last_ts = rows[-1][0]
    window_start = last_ts - WINDOW_YEARS*365*24*3600*1000
    bars = agg(rows, tfms)
    cans = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars]
    trades = []
    for i in range(2, len(bars)):
        if bars[i][0] < window_start: continue
        r = detect_run_3candles_sweep(cans[i-2], cans[i-1], cans[i])
        if r is None: continue
        risk = abs(r.sl - r.entry); reward = abs(r.entry - r.tp)
        if risk == 0: continue
        planned_rr = reward / risk
        fill_idx = None
        for j in range(i+1, min(i+1+etb, len(bars))):
            bj = bars[j]
            if r.direction == 'short':
                if bj[2] >= r.entry: fill_idx = j; break
            else:
                if bj[3] <= r.entry: fill_idx = j; break
        if fill_idx is None:
            trades.append({'status':'no_fill', 'r_mult':0.0, 'direction':r.direction, 'planned_rr':planned_rr}); continue
        status=None; r_mult=None
        for j in range(fill_idx, min(fill_idx+xtb, len(bars))):
            bj = bars[j]
            if r.direction == 'short':
                sl_hit=bj[2]>=r.sl; tp_hit=bj[3]<=r.tp
            else:
                sl_hit=bj[3]<=r.sl; tp_hit=bj[2]>=r.tp
            if sl_hit and tp_hit:
                if abs(bj[1]-r.sl) < abs(bj[1]-r.tp):
                    status='loss'; r_mult=-1.0
                else:
                    status='win'; r_mult=planned_rr
                break
            if sl_hit: status='loss'; r_mult=-1.0; break
            if tp_hit: status='win'; r_mult=planned_rr; break
        if status is None:
            bj=bars[min(fill_idx+xtb-1, len(bars)-1)]
            if r.direction=='short': r_mult=(r.entry-bj[4])/risk
            else: r_mult=(bj[4]-r.entry)/risk
            status='timeout'
        trades.append({'status':status, 'r_mult':r_mult, 'direction':r.direction, 'planned_rr':planned_rr})
    return trades

TFS = [('1h',60*MS_M),('2h',2*60*MS_M),('4h',4*60*MS_M),('6h',6*60*MS_M),('8h',8*60*MS_M),('12h',12*60*MS_M),('D',24*60*MS_M)]

for asset, fn in ASSETS:
    print(f'\nLoading {asset} ({fn})...')
    rows = load(fn)
    first = datetime.fromtimestamp(rows[0][0]/1000, MSK).strftime('%Y-%m-%d')
    last  = datetime.fromtimestamp(rows[-1][0]/1000, MSK).strftime('%Y-%m-%d')
    win_start = rows[-1][0] - WINDOW_YEARS*365*24*3600*1000
    actual_start = max(rows[0][0], win_start)
    actual_start_dt = datetime.fromtimestamp(actual_start/1000, MSK).strftime('%Y-%m-%d')
    print(f'  Data range: {first} → {last}, window: {actual_start_dt} → {last}')
    print(f'\n  {asset} backtest run_3candles_sweep:')
    print(f'  {"TF":<4} {"Filled":>7} {"WR%":>6} {"avgRR(win)":>11} {"TotR":>8} {"R/tr":>7}')
    print(f'  {"-"*52}')
    for tf, tfms in TFS:
        trades = bt(rows, tfms)
        filled = [t for t in trades if t['status'] not in ('no_fill','invalid')]
        if len(filled) < 5:
            print(f'  {tf:<4} {len(filled):>7}  (insufficient)')
            continue
        wins = [t for t in filled if t['status']=='win']
        wr = len(wins)/len(filled)*100
        avg_rr_win = np.mean([t['planned_rr'] for t in wins]) if wins else 0
        totr = sum(t['r_mult'] for t in filled)
        avg = totr/len(filled)
        print(f'  {tf:<4} {len(filled):>7} {wr:>5.1f}% {avg_rr_win:>10.2f} {totr:>+8.1f} {avg:>+7.3f}')
