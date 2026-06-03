"""Влияние FVG c1-c3 и FVG c2-c4 на канон run_3candles_sweep, BTC 1h.

FVG (3-bar gap):
  SHORT (bearish FVG): low прошлого > high следующего → gap
  LONG  (bullish FVG): high прошлого < low следующего → gap

c1-c3: gap прямо вокруг c2 (middle = c2)
  SHORT: c1.low > c3.high   →  gap [c3.high, c1.low]
  LONG:  c1.high < c3.low   →  gap [c1.high, c3.low]
  Известен в момент close c3.

c2-c4: gap вокруг c3 (middle = c3, нужен следующий бар c4)
  SHORT: c2.low > c4.high  →  gap [c4.high, c2.low]
  LONG:  c2.high < c4.low  →  gap [c2.high, c4.low]
  Известен в момент close c4 — entry сдвинется на 1 бар.
"""
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
WINDOW_YEARS = 6
ENTRY_TIMEOUT_MIN = 6*60
EXIT_TIMEOUT_MIN  = 30*60

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
win_start = last_ts - WINDOW_YEARS*365*24*3600*1000
bars = [b for b in agg(m1, TFMS) if b[0] >= win_start]
cans = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars]
print(f"BTC 1h bars 6y: {len(bars)}\n")

def sim_1m(direction, entry, sl, tp, start_idx):
    n = len(m1); fill_idx=None
    end_fill = min(start_idx + ENTRY_TIMEOUT_MIN, n)
    if direction == 'short':
        for j in range(start_idx, end_fill):
            if m1[j][2] >= entry: fill_idx = j; break
    else:
        for j in range(start_idx, end_fill):
            if m1[j][3] <= entry: fill_idx = j; break
    if fill_idx is None: return ('no_fill', 0.0)
    risk = abs(sl-entry); reward = abs(entry-tp); rr = reward/risk
    end_exit = min(fill_idx + EXIT_TIMEOUT_MIN, n)
    if direction == 'short':
        for j in range(fill_idx, end_exit):
            bj = m1[j]
            if bj[2] >= sl: return ('loss', -1.0)
            if bj[3] <= tp: return ('win', rr)
    else:
        for j in range(fill_idx, end_exit):
            bj = m1[j]
            if bj[3] <= sl: return ('loss', -1.0)
            if bj[2] >= tp: return ('win', rr)
    j = min(end_exit-1, n-1); bj = m1[j]
    return ('timeout', (entry-bj[4])/risk if direction=='short' else (bj[4]-entry)/risk)

# Собираем сетапы (канон оба) + FVG признаки + результат
setups = []
for i in range(2, len(cans)-1):  # -1 чтобы был c4
    c1, c2, c3 = cans[i-2], cans[i-1], cans[i]
    c4 = cans[i+1] if i+1 < len(cans) else None
    r = detect_run_3candles_sweep(c1, c2, c3)
    if r is None: continue
    # FVG c1-c3 (известен на close c3)
    if r.direction == 'short':
        fvg13 = c1.low > c3.high   # bearish FVG
        fvg13_size = (c1.low - c3.high) if fvg13 else 0
        fvg24 = (c4 is not None) and (c2.low > c4.high)
        fvg24_size = (c2.low - c4.high) if fvg24 else 0
    else:
        fvg13 = c1.high < c3.low   # bullish FVG
        fvg13_size = (c3.low - c1.high) if fvg13 else 0
        fvg24 = (c4 is not None) and (c2.high < c4.low)
        fvg24_size = (c4.low - c2.high) if fvg24 else 0
    # симуляция канона (entry/sl/tp как было)
    next_open_ms = bars[i][0] + TFMS
    start_1m = bisect.bisect_left(m1_ts, next_open_ms)
    if start_1m >= len(m1): continue
    s, rmult = sim_1m(r.direction, r.entry, r.sl, r.tp, start_1m)
    # для c2-c4 confluence: entry сдвигается на c5 open
    s24 = rmult24 = None
    if c4 is not None:
        c5_open_ms = bars[i+1][0] + TFMS  # = bars[i+2][0]
        start_1m_5 = bisect.bisect_left(m1_ts, c5_open_ms)
        if start_1m_5 < len(m1):
            s24, rmult24 = sim_1m(r.direction, r.entry, r.sl, r.tp, start_1m_5)
    setups.append({'dir':r.direction, 'fvg13':fvg13, 'fvg13_size':fvg13_size,
                   'fvg24':fvg24, 'fvg24_size':fvg24_size,
                   'status':s, 'r':rmult, 'status_24':s24, 'r_24':rmult24})

print(f"Total setups: {len(setups)}\n")
print(f"FVG c1-c3 присутствует: {sum(1 for x in setups if x['fvg13'])} ({sum(1 for x in setups if x['fvg13'])/len(setups)*100:.1f}%)")
print(f"FVG c2-c4 присутствует: {sum(1 for x in setups if x['fvg24'])} ({sum(1 for x in setups if x['fvg24'])/len(setups)*100:.1f}%)")
print(f"Оба:                    {sum(1 for x in setups if x['fvg13'] and x['fvg24'])} ({sum(1 for x in setups if x['fvg13'] and x['fvg24'])/len(setups)*100:.1f}%)\n")

def m(sub, label, use24=False):
    key_status = 'status_24' if use24 else 'status'
    key_r = 'r_24' if use24 else 'r'
    filled = [t for t in sub if t[key_status] is not None and t[key_status] not in ('no_fill','invalid')]
    if len(filled) < 5:
        print(f"  {label:<55}  n={len(filled)} (insufficient)")
        return
    wins = sum(1 for t in filled if t[key_status]=='win')
    totr = sum(t[key_r] for t in filled)
    print(f"  {label:<55}  n={len(filled):>3}  WR={wins/len(filled)*100:>5.1f}%  R/tr={totr/len(filled):>+6.3f}  R/yr={totr/WINDOW_YEARS:>+5.2f}")

print(f"{'='*100}\nBASELINE и FVG c1-c3 (entry канон):\n{'='*100}")
m(setups, "BASELINE (все)")
m([x for x in setups if x['fvg13']], "+ FVG c1-c3 ПРИСУТСТВУЕТ")
m([x for x in setups if not x['fvg13']], "+ FVG c1-c3 ОТСУТСТВУЕТ")

print(f"\n{'='*100}\nFVG c2-c4 (entry сдвинут на c5 open):\n{'='*100}")
m(setups, "BASELINE (все, entry c5 open)", use24=True)
m([x for x in setups if x['fvg24']], "+ FVG c2-c4 ПРИСУТСТВУЕТ", use24=True)
m([x for x in setups if not x['fvg24']], "+ FVG c2-c4 ОТСУТСТВУЕТ", use24=True)

print(f"\n{'='*100}\nКомбо (entry c5 open):\n{'='*100}")
m([x for x in setups if x['fvg13'] and x['fvg24']], "FVG c1-c3 И FVG c2-c4", use24=True)
m([x for x in setups if x['fvg13'] and not x['fvg24']], "FVG c1-c3, но НЕТ c2-c4", use24=True)
m([x for x in setups if not x['fvg13'] and x['fvg24']], "Нет c1-c3, есть c2-c4", use24=True)
m([x for x in setups if not x['fvg13'] and not x['fvg24']], "Нет ни одного FVG", use24=True)

print(f"\n{'='*100}\nDirection split + FVG (entry канон):\n{'='*100}")
for d in ('short','long'):
    print(f"\n  {d.upper()}:")
    m([x for x in setups if x['dir']==d], f"  baseline {d}")
    m([x for x in setups if x['dir']==d and x['fvg13']], f"  {d} + FVG c1-c3")
    m([x for x in setups if x['dir']==d and not x['fvg13']], f"  {d} БЕЗ FVG c1-c3")

print(f"\n{'='*100}\nDirection split + FVG c2-c4 (entry сдвиг c5):\n{'='*100}")
for d in ('short','long'):
    print(f"\n  {d.upper()}:")
    m([x for x in setups if x['dir']==d], f"  baseline {d}", use24=True)
    m([x for x in setups if x['dir']==d and x['fvg24']], f"  {d} + FVG c2-c4", use24=True)
    m([x for x in setups if x['dir']==d and not x['fvg24']], f"  {d} БЕЗ FVG c2-c4", use24=True)
