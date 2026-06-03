"""Оптимизация run_3candles_sweep на 1h поверх BTC + ETH + SOL.

Тестируем фильтры:
  - wick_ratio: 2.5 (canon), 3.0, 3.5, 4.0, 5.0
  - entry_fraction: 0.1, 0.2, 0.3 (canon), 0.4, 0.5
  - c2.body relative (минимальный)
  - c3 close_pos (close near low for SHORT)
  - direction-specific
"""
from __future__ import annotations
import csv, pathlib, sys
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

# Загрузка всех 3 активов
print("Loading data...")
asset_bars = {}
for asset, fn in ASSETS:
    rows = load(fn)
    bars = agg(rows, TF1H)
    last_ts = rows[-1][0]
    window_start = last_ts - WINDOW_YEARS*365*24*3600*1000
    bars = [b for b in bars if b[0] >= window_start]
    asset_bars[asset] = bars
    print(f"  {asset}: {len(bars)} 1h bars")

def scan(bars, wick_ratio=2.5, entry_fraction=0.3, min_body_pct=0.0, c3_close_pct_max=1.0):
    """Возвращает trade list для одной конфигурации."""
    cans = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars]
    trades = []
    for i in range(2, len(cans)):
        c1, c2, c3 = cans[i-2], cans[i-1], cans[i]
        for direction in ("short", "long"):
            if direction == "short":
                if not (c1.is_bear and c2.is_bear and c3.is_bear): continue
                if c2.high <= c1.high: continue
                upper_wick = c2.high - max(c2.open, c2.close)
                body = abs(c2.open - c2.close)
                if body == 0 or upper_wick < wick_ratio * body: continue
                c2_range = c2.high - c2.low
                if c2_range > 0 and body / c2_range < min_body_pct: continue
                c3_range = c3.high - c3.low
                if c3_range > 0:
                    c3_close_pct = (c3.close - c3.low) / c3_range
                    if c3_close_pct > c3_close_pct_max: continue
                entry = max(c2.open, c2.close) + entry_fraction * upper_wick
                sl = c2.high; tp = c3.low
            else:
                if not (c1.is_bull and c2.is_bull and c3.is_bull): continue
                if c2.low >= c1.low: continue
                lower_wick = min(c2.open, c2.close) - c2.low
                body = abs(c2.open - c2.close)
                if body == 0 or lower_wick < wick_ratio * body: continue
                c2_range = c2.high - c2.low
                if c2_range > 0 and body / c2_range < min_body_pct: continue
                c3_range = c3.high - c3.low
                if c3_range > 0:
                    c3_close_pct = (c3.high - c3.close) / c3_range  # = "distance from high"
                    if c3_close_pct > c3_close_pct_max: continue
                entry = min(c2.open, c2.close) - entry_fraction * lower_wick
                sl = c2.low; tp = c3.high
            risk = abs(sl - entry); reward = abs(entry - tp)
            if risk == 0: continue
            planned_rr = reward / risk
            # simulate
            fill_idx = None
            for j in range(i+1, min(i+1+6, len(bars))):
                bj = bars[j]
                if direction == 'short':
                    if bj[2] >= entry: fill_idx = j; break
                else:
                    if bj[3] <= entry: fill_idx = j; break
            if fill_idx is None:
                trades.append({'status':'no_fill', 'r_mult':0.0, 'direction':direction, 'planned_rr':planned_rr}); continue
            status=None; r_mult=None
            for j in range(fill_idx, min(fill_idx+30, len(bars))):
                bj = bars[j]
                if direction=='short':
                    sl_hit=bj[2]>=sl; tp_hit=bj[3]<=tp
                else:
                    sl_hit=bj[3]<=sl; tp_hit=bj[2]>=tp
                if sl_hit and tp_hit:
                    if abs(bj[1]-sl) < abs(bj[1]-tp): status='loss'; r_mult=-1.0
                    else: status='win'; r_mult=planned_rr
                    break
                if sl_hit: status='loss'; r_mult=-1.0; break
                if tp_hit: status='win'; r_mult=planned_rr; break
            if status is None:
                bj=bars[min(fill_idx+30-1, len(bars)-1)]
                if direction=='short': r_mult=(entry-bj[4])/risk
                else: r_mult=(bj[4]-entry)/risk
                status='timeout'
            trades.append({'status':status, 'r_mult':r_mult, 'direction':direction, 'planned_rr':planned_rr})
    return trades

def metrics(trades):
    filled = [t for t in trades if t['status'] not in ('no_fill','invalid')]
    if not filled: return None
    wins = sum(1 for t in filled if t['status']=='win')
    totr = sum(t['r_mult'] for t in filled)
    return {'n': len(filled), 'wr': wins/len(filled)*100, 'totr': totr, 'rpt': totr/len(filled)}

def cross_run(label, **kwargs):
    print(f"  {label}")
    print(f"    {'Asset':<6} {'n':>5} {'WR%':>6} {'TotR':>8} {'R/tr':>7}")
    avg_rpt = []
    for asset, bars in asset_bars.items():
        m = metrics(scan(bars, **kwargs))
        if m is None: continue
        print(f"    {asset:<6} {m['n']:>5} {m['wr']:>5.1f}% {m['totr']:>+8.1f} {m['rpt']:>+7.3f}")
        avg_rpt.append(m['rpt'])
    if avg_rpt:
        print(f"    avg R/tr: {np.mean(avg_rpt):+.3f}   min: {min(avg_rpt):+.3f}")
    print()

print(f"\n{'='*80}\nBaseline 1h (wick 2.5, entry 0.3):\n{'='*80}")
cross_run("baseline", wick_ratio=2.5, entry_fraction=0.3)

print(f"\n{'='*80}\nWick ratio scan:\n{'='*80}")
for wr in [3.0, 3.5, 4.0, 5.0]:
    cross_run(f"wick_ratio = {wr}", wick_ratio=wr)

print(f"\n{'='*80}\nEntry fraction scan (wick 2.5):\n{'='*80}")
for ef in [0.1, 0.2, 0.4, 0.5]:
    cross_run(f"entry_fraction = {ef}", entry_fraction=ef)

print(f"\n{'='*80}\nC3 close position filter (close near low for SHORT, near high for LONG):\n{'='*80}")
for cpct in [0.5, 0.3, 0.2]:
    cross_run(f"c3 close in bottom/top {int(cpct*100)}% of range", c3_close_pct_max=cpct)

print(f"\n{'='*80}\nMin c2 body % filter (c2.body / c2.range ≥ X):\n{'='*80}")
for bpct in [0.1, 0.2, 0.3]:
    cross_run(f"c2 body ≥ {int(bpct*100)}% range", min_body_pct=bpct)

print(f"\n{'='*80}\nКомбо: wick_ratio=3.0 + c3 close ≤ 30%:\n{'='*80}")
cross_run("wick 3.0 + c3 close bottom/top 30%", wick_ratio=3.0, c3_close_pct_max=0.3)

print(f"\n{'='*80}\nКомбо: wick_ratio=3.5 + entry_fraction=0.5:\n{'='*80}")
cross_run("wick 3.5 + entry 0.5", wick_ratio=3.5, entry_fraction=0.5)
