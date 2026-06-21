"""3 крайних setups канона run_3candles_sweep на BTC 1h."""
from __future__ import annotations
import csv, pathlib, sys, bisect
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle
from patterns.run_3candles_sweep.code import detect_run_3candles_sweep

MSK = timezone(timedelta(hours=3))
MS_M = 60_000
TFMS = 60*MS_M
DATA = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
ENTRY_TIMEOUT_MIN = 6*60
EXIT_TIMEOUT_MIN = 30*60

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

m1 = load(); m1_ts = [r[0] for r in m1]
last_ts = m1[-1][0]
bars = agg(m1, TFMS)
cans = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars]

def fmt(ms): return datetime.fromtimestamp(ms/1000, MSK).strftime('%Y-%m-%d %H:%M MSK')

def sim_1m(direction, entry, sl, tp, start_idx):
    n = len(m1); fill_idx=None
    end_fill = min(start_idx + ENTRY_TIMEOUT_MIN, n)
    if direction == 'short':
        for j in range(start_idx, end_fill):
            if m1[j][2] >= entry: fill_idx = j; break
    else:
        for j in range(start_idx, end_fill):
            if m1[j][3] <= entry: fill_idx = j; break
    if fill_idx is None: return ('no_fill', None, None, None)
    risk = abs(sl-entry); reward = abs(entry-tp); rr = reward/risk
    end_exit = min(fill_idx + EXIT_TIMEOUT_MIN, n)
    if direction == 'short':
        for j in range(fill_idx, end_exit):
            bj = m1[j]
            if bj[2] >= sl: return ('loss', fill_idx, j, sl)
            if bj[3] <= tp: return ('win', fill_idx, j, tp)
    else:
        for j in range(fill_idx, end_exit):
            bj = m1[j]
            if bj[3] <= sl: return ('loss', fill_idx, j, sl)
            if bj[2] >= tp: return ('win', fill_idx, j, tp)
    j = min(end_exit-1, n-1)
    return ('timeout', fill_idx, j, m1[j][4])

setups = []
for i in range(2, len(cans)):
    c1, c2, c3 = cans[i-2], cans[i-1], cans[i]
    r = detect_run_3candles_sweep(c1, c2, c3)
    if r is None: continue
    next_open_ms = bars[i][0] + TFMS
    start_1m = bisect.bisect_left(m1_ts, next_open_ms)
    if start_1m >= len(m1): continue
    s, fill_idx, exit_idx, exit_px = sim_1m(r.direction, r.entry, r.sl, r.tp, start_1m)
    setups.append({'pat':r, 'c1':c1, 'c2':c2, 'c3':c3,
                   'status':s, 'fill_idx':fill_idx, 'exit_idx':exit_idx, 'exit_px':exit_px})

print(f"Всего setups канона на BTC 1h: {len(setups)}, показываем 3 последних\n")

def show(s, idx):
    p = s['pat']; c1, c2, c3 = s['c1'], s['c2'], s['c3']
    print(f"{'='*78}")
    print(f"  #{idx}  {p.direction.upper()}   статус: {s['status'].upper()}")
    print(f"{'='*78}")
    print(f"  C1 {fmt(c1.open_time)}   O={c1.open:>10.2f}  H={c1.high:>10.2f}  L={c1.low:>10.2f}  C={c1.close:>10.2f}")
    print(f"  C2 {fmt(c2.open_time)}   O={c2.open:>10.2f}  H={c2.high:>10.2f}  L={c2.low:>10.2f}  C={c2.close:>10.2f}")
    print(f"  C3 {fmt(c3.open_time)}   O={c3.open:>10.2f}  H={c3.high:>10.2f}  L={c3.low:>10.2f}  C={c3.close:>10.2f}")
    if p.direction == 'short':
        wick = c2.high - max(c2.open, c2.close); body = abs(c2.open-c2.close)
        c2_range = c2.high - c2.low
        print(f"\n  C2: upper_wick={wick:.2f}, body={body:.2f}, ratio={wick/body:.2f}×, body/range={body/c2_range*100:.1f}%")
        print(f"  Sweep: C2.high {c2.high:.2f} > C1.high {c1.high:.2f}  (+{c2.high-c1.high:.2f})")
    else:
        wick = min(c2.open,c2.close) - c2.low; body = abs(c2.open-c2.close)
        c2_range = c2.high - c2.low
        print(f"\n  C2: lower_wick={wick:.2f}, body={body:.2f}, ratio={wick/body:.2f}×, body/range={body/c2_range*100:.1f}%")
        print(f"  Sweep: C2.low {c2.low:.2f} < C1.low {c1.low:.2f}  ({c2.low-c1.low:+.2f})")
    risk = abs(p.sl - p.entry); reward = abs(p.entry - p.tp)
    print(f"\n  Setup:")
    print(f"    Entry = {p.entry:>10.2f}    SL = {p.sl:>10.2f}  (risk {risk:.2f})")
    print(f"    TP    = {p.tp:>10.2f}                          (reward {reward:.2f})    RR = 1:{reward/risk:.2f}")
    if s['fill_idx'] is not None:
        print(f"\n  Fill: {fmt(m1[s['fill_idx']][0])}    Exit: {fmt(m1[s['exit_idx']][0])} @ {s['exit_px']:.2f}")
    else:
        print(f"\n  Fill: НЕ СОСТОЯЛСЯ за 6 часов после C3 close")
    print()

for idx, s in enumerate(setups[-3:], start=len(setups)-2):
    show(s, idx)
