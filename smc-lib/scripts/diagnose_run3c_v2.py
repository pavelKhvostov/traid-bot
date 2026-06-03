"""Глубокая диагностика run_3candles_sweep v2 (next_open, TP 2R, wick≥3.5) на 1m.

Что считаем:
  1. Direction split: SHORT vs LONG отдельно
  2. Per-year P/L: стабильность во времени
  3. MAE / MFE distribution: какой TP реально оптимален?
  4. Hour-of-day: где edge концентрируется?
  5. Bars-to-exit: быстрые vs медленные сделки
  6. Wick-ratio dependence: bin'ы 2.5-3 / 3-4 / 4-6 / 6+
"""
from __future__ import annotations
import csv, pathlib, sys, bisect, time
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import numpy as np

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle

MSK = timezone(timedelta(hours=3))
UTC = timezone.utc
MS_M = 60_000
TF1H = 60*MS_M
DATA_DIR = pathlib.Path.home() / "traid-bot/data"
ASSETS = [("BTC", "BTCUSDT_1m_vic_vadim.csv"),
          ("ETH", "ETHUSDT_1m_vic_vadim.csv"),
          ("SOL", "SOLUSDT_1m_vic_vadim.csv")]
WINDOW_YEARS = 6
EXIT_TIMEOUT_MIN = 30 * 60
WICK_RATIO = 3.5
TP_R = 2.0

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

def simulate(direction, entry, sl, tp, start_idx, m1):
    """Returns: status, r_mult, mae_R, mfe_R, bars_to_exit."""
    n = len(m1)
    risk = abs(sl - entry); reward = abs(entry - tp)
    if risk == 0: return ('invalid', 0.0, 0.0, 0.0, 0)
    rr = reward / risk
    end = min(start_idx + EXIT_TIMEOUT_MIN, n)
    mae = 0.0; mfe = 0.0  # in R units, mae negative-favorable, mfe positive
    if direction == 'short':
        for j in range(start_idx, end):
            bj = m1[j]
            # adverse: цена поднялась; favorable: цена опустилась
            adv = (bj[2] - entry) / risk  # high движется к SL → положительное
            fav = (entry - bj[3]) / risk  # low ниже entry → положительное
            if adv > mae: mae = adv
            if fav > mfe: mfe = fav
            if bj[2] >= sl: return ('loss', -1.0, mae, mfe, j-start_idx+1)
            if bj[3] <= tp: return ('win', rr, mae, mfe, j-start_idx+1)
    else:
        for j in range(start_idx, end):
            bj = m1[j]
            adv = (entry - bj[3]) / risk
            fav = (bj[2] - entry) / risk
            if adv > mae: mae = adv
            if fav > mfe: mfe = fav
            if bj[3] <= sl: return ('loss', -1.0, mae, mfe, j-start_idx+1)
            if bj[2] >= tp: return ('win', rr, mae, mfe, j-start_idx+1)
    j = min(end-1, n-1); bj = m1[j]
    r = (entry - bj[4]) / risk if direction=='short' else (bj[4] - entry) / risk
    return ('timeout', r, mae, mfe, end-start_idx)

def scan(ad):
    bars = ad['bars1h']; m1 = ad['m1']; m1_ts = ad['m1_ts']
    cans = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars]
    trades = []
    for i in range(2, len(cans)-1):
        c1, c2, c3 = cans[i-2], cans[i-1], cans[i]
        next_open_ms = bars[i][0] + TF1H
        next_open_idx = bisect.bisect_left(m1_ts, next_open_ms)
        if next_open_idx >= len(m1): continue
        entry_px_open = m1[next_open_idx][1]
        hour_msk = datetime.fromtimestamp(next_open_ms/1000, MSK).hour
        year = datetime.fromtimestamp(bars[i][0]/1000, MSK).year
        # SHORT
        if c1.is_bear and c2.is_bear and c3.is_bear and c2.high > c1.high:
            wick = c2.high - max(c2.open, c2.close); body = abs(c2.open - c2.close)
            if body > 0 and wick >= WICK_RATIO*body:
                sl = c2.high
                entry = entry_px_open
                risk = sl - entry
                if risk > 0:
                    tp = entry - TP_R * risk
                    s, r, mae, mfe, bte = simulate('short', entry, sl, tp, next_open_idx, m1)
                    trades.append({'dir':'short', 'status':s, 'r':r, 'mae':mae, 'mfe':mfe,
                                   'bars':bte, 'hour':hour_msk, 'year':year,
                                   'wick_body':wick/body, 'risk':risk, 'entry_ms':next_open_ms})
        # LONG
        if c1.is_bull and c2.is_bull and c3.is_bull and c2.low < c1.low:
            wick = min(c2.open, c2.close) - c2.low; body = abs(c2.open - c2.close)
            if body > 0 and wick >= WICK_RATIO*body:
                sl = c2.low
                entry = entry_px_open
                risk = entry - sl
                if risk > 0:
                    tp = entry + TP_R * risk
                    s, r, mae, mfe, bte = simulate('long', entry, sl, tp, next_open_idx, m1)
                    trades.append({'dir':'long', 'status':s, 'r':r, 'mae':mae, 'mfe':mfe,
                                   'bars':bte, 'hour':hour_msk, 'year':year,
                                   'wick_body':wick/body, 'risk':risk, 'entry_ms':next_open_ms})
    return trades

def summarize(trades, label):
    if not trades: return
    n = len(trades); wins = sum(1 for t in trades if t['status']=='win')
    losses = sum(1 for t in trades if t['status']=='loss')
    timeouts = sum(1 for t in trades if t['status']=='timeout')
    totr = sum(t['r'] for t in trades)
    print(f"{label:<24} n={n:>4}  W={wins:>3} L={losses:>3} T={timeouts:>3}  "
          f"WR={wins/n*100:>5.1f}%  R/tr={totr/n:>+.3f}  TotR={totr:>+7.1f}")

# ── 1. Cross-asset baseline (uses v2 canon) ────────────────────────────────────
print(f"\n{'='*90}\n1. BASELINE v2 (next_open + TP 2R + wick≥3.5)\n{'='*90}")
all_trades = {}
for asset, ad in asset_data.items():
    t = scan(ad); all_trades[asset] = t
    summarize(t, asset)

# ── 2. Direction split ─────────────────────────────────────────────────────────
print(f"\n{'='*90}\n2. DIRECTION SPLIT (SHORT vs LONG)\n{'='*90}")
for asset, t in all_trades.items():
    print(f"\n  {asset}:")
    summarize([x for x in t if x['dir']=='short'], '  SHORT')
    summarize([x for x in t if x['dir']=='long'],  '  LONG')

# ── 3. Per-year ────────────────────────────────────────────────────────────────
print(f"\n{'='*90}\n3. PER-YEAR P/L (стабильность edge во времени)\n{'='*90}")
years_set = sorted({t['year'] for tr in all_trades.values() for t in tr})
print(f"  {'Year':<6}", end='')
for a in all_trades: print(f"{a+' n/WR/R':<20}", end='')
print()
for y in years_set:
    print(f"  {y:<6}", end='')
    for asset, t in all_trades.items():
        yt = [x for x in t if x['year']==y]
        if yt:
            wr = sum(1 for x in yt if x['status']=='win')/len(yt)*100
            tot = sum(x['r'] for x in yt)
            print(f"{len(yt):>3} {wr:>4.0f}% {tot:>+6.1f}      ", end='')
        else:
            print(f"{'-':<20}", end='')
    print()

# ── 4. MAE / MFE distribution ─────────────────────────────────────────────────
print(f"\n{'='*90}\n4. MAE / MFE — какой TP оптимален?\n{'='*90}")
print("  MFE = how far in favor цена ушла. Если TP=N, то win всех trades с MFE≥N.")
print(f"\n  Распределение MFE (across all 3 assets, baseline pattern, no TP limit):")
all_mfe = [t['mfe'] for tr in all_trades.values() for t in tr]
all_mae = [t['mae'] for tr in all_trades.values() for t in tr]
print(f"    n={len(all_mfe)}")
print(f"    MFE pct: p25={np.percentile(all_mfe,25):.2f}R  p50={np.percentile(all_mfe,50):.2f}R  "
      f"p75={np.percentile(all_mfe,75):.2f}R  p90={np.percentile(all_mfe,90):.2f}R")
print(f"    MAE pct: p25={np.percentile(all_mae,25):.2f}R  p50={np.percentile(all_mae,50):.2f}R  "
      f"p75={np.percentile(all_mae,75):.2f}R")

# Reach-rates: какой % сделок дошли до X R
print(f"\n  Reach-rate (доля сделок где MFE ≥ TP) и hypothetical R/tr (assuming TP=X):")
print(f"    {'TP':>4} {'reach%':>7} {'hypothetical R/tr*':>20}")
for tp in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]:
    reached = [t for t in (x for tr in all_trades.values() for x in tr) if t['mfe'] >= tp]
    n_total = sum(len(v) for v in all_trades.values())
    pct = len(reached)/n_total*100
    # Hypothetical: assume TP=tp. Wins = MFE≥tp. Loss = MAE≥1 (hits SL).
    # But SL is fixed at 1R. Note: pessimistic — if both reached, count loss.
    # We approximate: if MFE≥tp AND MAE<1 → win tp. If MAE≥1 → loss 1.
    # Else timeout-like. (Caveat: order matters; this is upper bound for win-counted-first.)
    wins_h = 0; losses_h = 0; other_h = 0; tot_h = 0
    for x in (t for tr in all_trades.values() for t in tr):
        if x['mae'] >= 1.0 and x['mfe'] >= tp:
            # ambiguous; pessimistic loss
            losses_h += 1; tot_h -= 1
        elif x['mae'] >= 1.0:
            losses_h += 1; tot_h -= 1
        elif x['mfe'] >= tp:
            wins_h += 1; tot_h += tp
        else:
            other_h += 1; tot_h += x['r']  # actual timeout/partial — use observed
    avg = tot_h / n_total if n_total else 0
    print(f"    {tp:>4.1f}R {pct:>6.1f}% {avg:>+19.3f}")
print("    * pessimistic: ambiguous bars где MFE≥TP И MAE≥1 → засчитан loss.")

# ── 5. Hour-of-day ─────────────────────────────────────────────────────────────
print(f"\n{'='*90}\n5. HOUR-OF-DAY MSK (entry next bar open hour)\n{'='*90}")
print(f"  {'Hour':<5}", end='')
for a in all_trades: print(f"{a+' n/WR/R/tr':<18}", end='')
print()
for h in range(24):
    line = f"  {h:>02}   "
    has_any = False
    for asset, tr in all_trades.items():
        ht = [x for x in tr if x['hour']==h]
        if ht:
            wr = sum(1 for x in ht if x['status']=='win')/len(ht)*100
            r = sum(x['r'] for x in ht)/len(ht)
            line += f"{len(ht):>3} {wr:>4.0f}% {r:>+5.2f}    "
            has_any = True
        else:
            line += f"{'-':<18}"
    if has_any: print(line)

# ── 6. Wick-ratio bins ─────────────────────────────────────────────────────────
print(f"\n{'='*90}\n6. WICK/BODY RATIO BINS (where does edge live?)\n{'='*90}")
bins = [(3.5,4.0),(4.0,5.0),(5.0,7.0),(7.0,10.0),(10.0,1e9)]
print(f"  {'bin':<10}", end='')
for a in all_trades: print(f"{a+' n/WR/R/tr':<18}", end='')
print(f"{'ALL n/WR/R/tr':<18}")
for lo, hi in bins:
    line = f"  {lo:.1f}-{hi if hi<100 else '∞':<5}  "
    all_b = []
    for asset, tr in all_trades.items():
        bt = [x for x in tr if lo <= x['wick_body'] < hi]
        all_b.extend(bt)
        if bt:
            wr = sum(1 for x in bt if x['status']=='win')/len(bt)*100
            r = sum(x['r'] for x in bt)/len(bt)
            line += f"{len(bt):>3} {wr:>4.0f}% {r:>+5.2f}    "
        else:
            line += f"{'-':<18}"
    if all_b:
        wr = sum(1 for x in all_b if x['status']=='win')/len(all_b)*100
        r = sum(x['r'] for x in all_b)/len(all_b)
        line += f"{len(all_b):>3} {wr:>4.0f}% {r:>+5.2f}"
    print(line)

# ── 7. Time-to-exit ────────────────────────────────────────────────────────────
print(f"\n{'='*90}\n7. BARS-TO-EXIT (как быстро сделка закрывается?)\n{'='*90}")
for asset, tr in all_trades.items():
    wins = [x for x in tr if x['status']=='win']
    losses = [x for x in tr if x['status']=='loss']
    if wins: w_m = np.median([x['bars'] for x in wins])
    else: w_m = 0
    if losses: l_m = np.median([x['bars'] for x in losses])
    else: l_m = 0
    print(f"  {asset}:  median bars-to-WIN = {w_m:.0f}m,  median bars-to-LOSS = {l_m:.0f}m")
