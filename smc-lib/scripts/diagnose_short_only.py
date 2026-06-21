"""SHORT-only deep dive + per-year + scale-out test."""
from __future__ import annotations
import csv, pathlib, sys, bisect, time
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle

MSK = timezone(timedelta(hours=3))
MS_M = 60_000; TF1H = 60*MS_M
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
    t0=time.time(); m1 = load(fn)
    last_ts = m1[-1][0]
    win_start = last_ts - WINDOW_YEARS*365*24*3600*1000
    bars1h = [b for b in agg(m1, TF1H) if b[0] >= win_start]
    m1_ts = [r[0] for r in m1]
    asset_data[asset] = {'m1': m1, 'm1_ts': m1_ts, 'bars1h': bars1h}
    print(f"  {asset}: {len(bars1h)} 1h ({time.time()-t0:.1f}s)")

def simulate_short_scaleout(entry, sl, tp1, tp2, w1, w2, start_idx, m1):
    """w1 на TP1, w2 на TP2. Если TP1 hit — w1 закрыт; SL передвигается на breakeven."""
    n = len(m1)
    risk = sl - entry
    if risk <= 0: return ('invalid', 0.0)
    r1 = (entry - tp1)/risk  # положительное
    r2 = (entry - tp2)/risk
    end = min(start_idx + EXIT_TIMEOUT_MIN, n)
    tp1_hit = False; current_sl = sl
    realized = 0.0
    for j in range(start_idx, end):
        bj = m1[j]
        # check SL first
        if bj[2] >= current_sl:
            if not tp1_hit:
                return ('loss', -1.0)  # full loss
            else:
                # tp1 уже взят (w1 × r1), остаток w2 при BE
                return ('partial_be', w1*r1 + 0.0)  # remaining at BE = 0
        # check TP1 if not hit yet
        if not tp1_hit and bj[3] <= tp1:
            tp1_hit = True
            current_sl = entry  # breakeven для оставшегося
            realized += w1 * r1
            # check TP2 in same bar
            if bj[3] <= tp2:
                return ('win_full', realized + w2*r2)
            continue
        # check TP2 after tp1 hit
        if tp1_hit and bj[3] <= tp2:
            return ('win_full', realized + w2*r2)
    # timeout
    j = min(end-1, n-1); bj = m1[j]
    open_pnl = (entry - bj[4]) / risk
    if tp1_hit:
        return ('timeout_partial', realized + w2*open_pnl)
    else:
        return ('timeout', 1.0 * open_pnl)

def simulate_short_simple(entry, sl, tp, start_idx, m1):
    """Стандартный single TP."""
    n = len(m1)
    risk = sl - entry
    if risk <= 0: return ('invalid', 0.0)
    rr = (entry - tp)/risk
    end = min(start_idx + EXIT_TIMEOUT_MIN, n)
    for j in range(start_idx, end):
        bj = m1[j]
        if bj[2] >= sl: return ('loss', -1.0)
        if bj[3] <= tp: return ('win', rr)
    j = min(end-1, n-1); bj = m1[j]
    return ('timeout', (entry - bj[4]) / risk)

def collect_shorts(ad, wick_min=3.5, wick_max=1e9):
    bars = ad['bars1h']; m1 = ad['m1']; m1_ts = ad['m1_ts']
    cans = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars]
    items = []
    for i in range(2, len(cans)-1):
        c1, c2, c3 = cans[i-2], cans[i-1], cans[i]
        if not (c1.is_bear and c2.is_bear and c3.is_bear and c2.high > c1.high): continue
        wick = c2.high - max(c2.open, c2.close); body = abs(c2.open - c2.close)
        if body == 0: continue
        wb = wick/body
        if wb < wick_min or wb >= wick_max: continue
        next_open_ms = bars[i][0] + TF1H
        next_open_idx = bisect.bisect_left(m1_ts, next_open_ms)
        if next_open_idx >= len(m1): continue
        entry = m1[next_open_idx][1]
        sl = c2.high
        if sl <= entry: continue
        year = datetime.fromtimestamp(bars[i][0]/1000, MSK).year
        items.append({'entry':entry, 'sl':sl, 'idx':next_open_idx, 'm1':m1,
                      'year':year, 'wick_body':wb, 'risk':sl-entry})
    return items

# ── A. Single TP 2R (SHORT-only) ──────────────────────────────────────────────
print(f"\n{'='*90}\nA. SHORT-only baseline (TP=2R, wick≥3.5):\n{'='*90}")
for asset, ad in asset_data.items():
    items = collect_shorts(ad, wick_min=3.5)
    trades = []
    for it in items:
        risk = it['risk']; tp = it['entry'] - 2.0 * risk
        s, r = simulate_short_simple(it['entry'], it['sl'], tp, it['idx'], it['m1'])
        trades.append({'status':s, 'r':r, 'year':it['year'], 'wick_body':it['wick_body']})
    n = len(trades); wins = sum(1 for t in trades if t['status']=='win')
    totr = sum(t['r'] for t in trades)
    print(f"  {asset}: n={n}  WR={wins/n*100:.1f}%  R/tr={totr/n:+.3f}  TotR={totr:+.1f}")

# ── B. Per-year SHORT-only ────────────────────────────────────────────────────
print(f"\n{'='*90}\nB. PER-YEAR (SHORT-only, TP=2R):\n{'='*90}")
all_short = {}
for asset, ad in asset_data.items():
    items = collect_shorts(ad, wick_min=3.5)
    trades = []
    for it in items:
        risk = it['risk']; tp = it['entry'] - 2.0 * risk
        s, r = simulate_short_simple(it['entry'], it['sl'], tp, it['idx'], it['m1'])
        trades.append({'status':s, 'r':r, 'year':it['year']})
    all_short[asset] = trades

years = sorted({t['year'] for tr in all_short.values() for t in tr})
print(f"  {'Year':<6} {'BTC n/WR/R':<18} {'ETH n/WR/R':<18} {'SOL n/WR/R':<18}")
for y in years:
    line = f"  {y:<6}"
    for asset, tr in all_short.items():
        yt = [x for x in tr if x['year']==y]
        if yt:
            wr = sum(1 for x in yt if x['status']=='win')/len(yt)*100
            r = sum(x['r'] for x in yt)
            line += f"{len(yt):>3} {wr:>4.0f}% {r:>+6.1f}     "
        else:
            line += f"{'-':<18}"
    print(line)

# ── C. Scale-out test (50% на 1R, 50% на 2R, BE для второй) ──────────────────
print(f"\n{'='*90}\nC. SCALE-OUT (50% TP=1R, 50% TP=2R, после 1R стоп→BE):\n{'='*90}")
for asset, ad in asset_data.items():
    items = collect_shorts(ad, wick_min=3.5)
    trades = []
    for it in items:
        risk = it['risk']
        tp1 = it['entry'] - 1.0*risk
        tp2 = it['entry'] - 2.0*risk
        s, r = simulate_short_scaleout(it['entry'], it['sl'], tp1, tp2, 0.5, 0.5, it['idx'], it['m1'])
        trades.append({'status':s, 'r':r})
    n = len(trades)
    full_wins = sum(1 for t in trades if t['status']=='win_full')
    losses = sum(1 for t in trades if t['status']=='loss')
    partial_be = sum(1 for t in trades if t['status']=='partial_be')
    timeout_partial = sum(1 for t in trades if t['status']=='timeout_partial')
    totr = sum(t['r'] for t in trades)
    print(f"  {asset}: n={n}  fullW={full_wins} L={losses} partBE={partial_be} TOpart={timeout_partial} "
          f"TotR={totr:+.1f}  R/tr={totr/n:+.3f}")

# ── D. Scan TP single (SHORT-only) на нескольких уровнях ──────────────────────
print(f"\n{'='*90}\nD. Single-TP scan (SHORT-only, wick≥3.5):\n{'='*90}")
print(f"  {'TP':<5} {'BTC R/tr':<11} {'ETH R/tr':<11} {'SOL R/tr':<11} {'avg':<9} {'min':<9}")
for tp_r in [1.0, 1.5, 1.75, 2.0, 2.25, 2.5]:
    line = f"  {tp_r:<5}"
    rpts = []
    for asset, ad in asset_data.items():
        items = collect_shorts(ad, wick_min=3.5)
        trades = []
        for it in items:
            tp = it['entry'] - tp_r * it['risk']
            s, r = simulate_short_simple(it['entry'], it['sl'], tp, it['idx'], it['m1'])
            trades.append({'status':s, 'r':r})
        rpt = sum(t['r'] for t in trades)/len(trades) if trades else 0
        rpts.append(rpt)
        line += f"{rpt:>+9.3f}  "
    line += f"{np.mean(rpts):>+8.3f} {min(rpts):>+8.3f}"
    print(line)

# ── E. Wick-body bin (SHORT-only) ────────────────────────────────────────────
print(f"\n{'='*90}\nE. WICK/BODY bin (SHORT-only, TP=2R):\n{'='*90}")
bins = [(3.5,4.5),(4.5,6.0),(6.0,8.0),(8.0,12.0),(12.0,1e9)]
print(f"  {'bin':<10} {'BTC n/WR/R/tr':<20} {'ETH n/WR/R/tr':<20} {'SOL n/WR/R/tr':<20} {'ALL avg':<12}")
for lo, hi in bins:
    line = f"  {lo:.1f}-{hi if hi<100 else '∞':<5} "
    all_rpt = []
    for asset, ad in asset_data.items():
        items = collect_shorts(ad, wick_min=lo, wick_max=hi)
        trades = []
        for it in items:
            tp = it['entry'] - 2.0 * it['risk']
            s, r = simulate_short_simple(it['entry'], it['sl'], tp, it['idx'], it['m1'])
            trades.append({'status':s, 'r':r})
        if trades:
            wr = sum(1 for t in trades if t['status']=='win')/len(trades)*100
            rpt = sum(t['r'] for t in trades)/len(trades)
            line += f"{len(trades):>3} {wr:>4.0f}% {rpt:>+6.3f}     "
            all_rpt.append(rpt)
        else:
            line += f"{'-':<20}"
    if all_rpt: line += f"{np.mean(all_rpt):>+8.3f}"
    print(line)
