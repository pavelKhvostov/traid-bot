"""Оптимизация run_3candles_sweep на 1h с симулятором на 1m intra-bar walk.

Изменения относительно предыдущей версии:
  - Fill и exit симулируются по 1m барам (а не по 1h).
  - В одном 1m баре проверяем sl_hit ПЕРЕД tp_hit (пессимистично).
  - Это устраняет фейковые WIN в часовых барах где SL и TP сидят оба.
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

ENTRY_TIMEOUT_MIN = 6 * 60      # 6 часов = 360 1m баров
EXIT_TIMEOUT_MIN  = 30 * 60     # 30 часов = 1800 1m баров

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

# ── Загрузка ─────────────────────────────────────────────────────────────────
print("Loading data (1m + aggregate 1h)...")
asset_data = {}
for asset, fn in ASSETS:
    t0 = time.time()
    m1 = load(fn)
    last_ts = m1[-1][0]
    win_start = last_ts - WINDOW_YEARS*365*24*3600*1000
    bars1h = [b for b in agg(m1, TF1H) if b[0] >= win_start]
    m1_ts = [r[0] for r in m1]
    asset_data[asset] = {'m1': m1, 'm1_ts': m1_ts, 'bars1h': bars1h, 'win_start': win_start}
    print(f"  {asset}: {len(m1)} 1m, {len(bars1h)} 1h bars  ({time.time()-t0:.1f}s)")

# ── Симулятор на 1m ──────────────────────────────────────────────────────────
def simulate_1m(direction, entry, sl, tp, start_idx, m1):
    n = len(m1)
    fill_idx = None
    end_fill = min(start_idx + ENTRY_TIMEOUT_MIN, n)
    if direction == 'short':
        for j in range(start_idx, end_fill):
            if m1[j][2] >= entry: fill_idx = j; break
    else:
        for j in range(start_idx, end_fill):
            if m1[j][3] <= entry: fill_idx = j; break
    if fill_idx is None: return ('no_fill', 0.0, 0.0)
    risk = abs(sl - entry); reward = abs(entry - tp)
    if risk == 0: return ('invalid', 0.0, 0.0)
    planned_rr = reward / risk
    end_exit = min(fill_idx + EXIT_TIMEOUT_MIN, n)
    if direction == 'short':
        for j in range(fill_idx, end_exit):
            bj = m1[j]
            if bj[2] >= sl: return ('loss', -1.0, planned_rr)   # SL first (пессимистично)
            if bj[3] <= tp: return ('win', planned_rr, planned_rr)
    else:
        for j in range(fill_idx, end_exit):
            bj = m1[j]
            if bj[3] <= sl: return ('loss', -1.0, planned_rr)
            if bj[2] >= tp: return ('win', planned_rr, planned_rr)
    j = min(end_exit-1, n-1); bj = m1[j]
    if direction == 'short': r = (entry - bj[4]) / risk
    else: r = (bj[4] - entry) / risk
    return ('timeout', r, planned_rr)

def scan(ad, wick_ratio=2.5, entry_fraction=0.3, min_body_pct=0.0, c3_close_pct_max=1.0):
    bars = ad['bars1h']; m1 = ad['m1']; m1_ts = ad['m1_ts']
    cans = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars]
    trades = []
    for i in range(2, len(cans)):
        c1, c2, c3 = cans[i-2], cans[i-1], cans[i]
        bar_open = bars[i][0]
        next_bar_open = bar_open + TF1H
        start_1m = bisect.bisect_left(m1_ts, next_bar_open)
        if start_1m >= len(m1): break
        for direction in ("short", "long"):
            if direction == "short":
                if not (c1.is_bear and c2.is_bear and c3.is_bear): continue
                if c2.high <= c1.high: continue
                wick = c2.high - max(c2.open, c2.close)
                body = abs(c2.open - c2.close)
                if body == 0 or wick < wick_ratio * body: continue
                c2_range = c2.high - c2.low
                if c2_range > 0 and body / c2_range < min_body_pct: continue
                c3_range = c3.high - c3.low
                if c3_range > 0:
                    c3_close_pct = (c3.close - c3.low) / c3_range
                    if c3_close_pct > c3_close_pct_max: continue
                entry = max(c2.open, c2.close) + entry_fraction * wick
                sl = c2.high; tp = c3.low
            else:
                if not (c1.is_bull and c2.is_bull and c3.is_bull): continue
                if c2.low >= c1.low: continue
                wick = min(c2.open, c2.close) - c2.low
                body = abs(c2.open - c2.close)
                if body == 0 or wick < wick_ratio * body: continue
                c2_range = c2.high - c2.low
                if c2_range > 0 and body / c2_range < min_body_pct: continue
                c3_range = c3.high - c3.low
                if c3_range > 0:
                    c3_close_pct = (c3.high - c3.close) / c3_range
                    if c3_close_pct > c3_close_pct_max: continue
                entry = min(c2.open, c2.close) - entry_fraction * wick
                sl = c2.low; tp = c3.high
            status, r_mult, planned = simulate_1m(direction, entry, sl, tp, start_1m, m1)
            trades.append({'status':status, 'r_mult':r_mult, 'planned_rr':planned, 'direction':direction})
    return trades

def metrics(trades):
    filled = [t for t in trades if t['status'] not in ('no_fill','invalid')]
    if not filled: return None
    wins = sum(1 for t in filled if t['status']=='win')
    totr = sum(t['r_mult'] for t in filled)
    return {'n': len(filled), 'wr': wins/len(filled)*100, 'totr': totr, 'rpt': totr/len(filled)}

def cross_run(label, **kw):
    print(f"  {label}")
    print(f"    {'Asset':<6} {'n':>5} {'WR%':>6} {'TotR':>8} {'R/tr':>7}")
    avg = []
    for asset, ad in asset_data.items():
        m = metrics(scan(ad, **kw))
        if m is None: continue
        print(f"    {asset:<6} {m['n']:>5} {m['wr']:>5.1f}% {m['totr']:>+8.1f} {m['rpt']:>+7.3f}")
        avg.append(m['rpt'])
    if avg:
        print(f"    avg R/tr: {np.mean(avg):+.3f}   min: {min(avg):+.3f}")
    print()

print(f"\n{'='*80}\nBaseline 1h (wick 2.5, entry 0.3) [1m simulator]:\n{'='*80}")
cross_run("baseline", wick_ratio=2.5, entry_fraction=0.3)

print(f"\n{'='*80}\nWick ratio scan:\n{'='*80}")
for wr in [3.0, 3.5, 4.0, 5.0]:
    cross_run(f"wick_ratio = {wr}", wick_ratio=wr)

print(f"\n{'='*80}\nEntry fraction scan (wick 2.5):\n{'='*80}")
for ef in [0.1, 0.2, 0.4, 0.5]:
    cross_run(f"entry_fraction = {ef}", entry_fraction=ef)

print(f"\n{'='*80}\nC3 close position filter:\n{'='*80}")
for cpct in [0.5, 0.3, 0.2]:
    cross_run(f"c3 close in {int(cpct*100)}% extreme", c3_close_pct_max=cpct)

print(f"\n{'='*80}\nКомбо: wick=3.5 + entry=0.5 (prev winner):\n{'='*80}")
cross_run("wick 3.5 + entry 0.5", wick_ratio=3.5, entry_fraction=0.5)

print(f"\n{'='*80}\nКомбо: wick=3.0 + c3 close 30%:\n{'='*80}")
cross_run("wick 3.0 + c3 close 30%", wick_ratio=3.0, c3_close_pct_max=0.3)

print(f"\n{'='*80}\nКомбо: wick=3.5 + entry=0.4:\n{'='*80}")
cross_run("wick 3.5 + entry 0.4", wick_ratio=3.5, entry_fraction=0.4)
