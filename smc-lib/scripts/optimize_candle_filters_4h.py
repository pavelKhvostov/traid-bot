"""Подбор candle-параметров для улучшения run_3candles_sweep на BTC 4h.

Baseline (канон): n=89, WR=37.1%, R/tr=+0.302, R/yr=+4.48
Целимся в R/tr ≥ +0.50 без катастрофического падения n.

Фильтры (тестируем каждый отдельно, потом топ комбинации):
  F1. c2 opposite_wick ≤ X% c2_range   (чистое отвержение)
  F2. c2.body > c1.body                  (c2 сильнее c1)
  F3. c3.body > c2.body                  (c3 ускорение)
  F4. c3 close в N% extreme своего range (сильный close)
  F5. sweep_depth = (c2.high-c1.high)/c2.body ≥ X
  F6. c3.close beyond c1 extreme         (full continuation)
  F7. c2.body / c2.range ≥ X             (нормальное тело)
  F8. c1 body ≥ X% c1 range              (c1 не доджи)
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
TFMS = 4 * 60 * MS_M  # 4h
WICK_RATIO_CANON = 2.5
ENTRY_FRAC = 0.3
ENTRY_TIMEOUT_MIN = 6 * 240
EXIT_TIMEOUT_MIN = 30 * 240

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

print("Loading BTC...")
t0=time.time(); m1 = load(); m1_ts = [r[0] for r in m1]
last_ts = m1[-1][0]; win_start = last_ts - WINDOW_YEARS*365*24*3600*1000
bars = [b for b in agg(m1, TFMS) if b[0] >= win_start]
cans = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars]
print(f"  {len(bars)} 4h bars ({time.time()-t0:.1f}s)\n")

def sim_1m(direction, entry, sl, tp, start_idx):
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
    rr = reward / risk
    end_exit = min(fill_idx + EXIT_TIMEOUT_MIN, n)
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
    return ('timeout', (entry-bj[4])/risk if direction=='short' else (bj[4]-entry)/risk, rr)

# Собираем все сетапы канон wick>=2.5 + метрики свечей
setups = []
for i in range(2, len(cans)-1):
    c1, c2, c3 = cans[i-2], cans[i-1], cans[i]
    next_open_ms = bars[i][0] + TFMS
    start_1m = bisect.bisect_left(m1_ts, next_open_ms)
    if start_1m >= len(m1): continue
    # SHORT
    if c1.is_bear and c2.is_bear and c3.is_bear and c2.high > c1.high:
        wick = c2.high - max(c2.open, c2.close); body = abs(c2.open - c2.close)
        if body > 0 and wick >= WICK_RATIO_CANON*body:
            c2_range = c2.high - c2.low
            c1_range = c1.high - c1.low
            c3_range = c3.high - c3.low
            c1_body = abs(c1.open - c1.close); c3_body = abs(c3.open - c3.close)
            entry = max(c2.open, c2.close) + ENTRY_FRAC*wick
            sl = c2.high; tp = c3.low
            s, r, rr = sim_1m('short', entry, sl, tp, start_1m)
            setups.append({
                'dir':'short', 'status':s, 'r':r, 'rr':rr,
                'c2_opp_wick_pct': (min(c2.open,c2.close) - c2.low)/c2_range if c2_range>0 else 0,
                'c2_body_gt_c1': body > c1_body,
                'c3_body_gt_c2': c3_body > body,
                'c3_close_extreme_pct': (c3.close - c3.low)/c3_range if c3_range>0 else 0,  # 0..1, 0=low (хорошо для SHORT)
                'sweep_depth_b': (c2.high - c1.high)/body if body>0 else 0,
                'c3_below_c1_low': c3.close < c1.low,
                'c2_body_pct': body/c2_range if c2_range>0 else 0,
                'c1_body_pct': c1_body/c1_range if c1_range>0 else 0,
                'wick_body': wick/body,
            })
    # LONG mirror
    if c1.is_bull and c2.is_bull and c3.is_bull and c2.low < c1.low:
        wick = min(c2.open, c2.close) - c2.low; body = abs(c2.open - c2.close)
        if body > 0 and wick >= WICK_RATIO_CANON*body:
            c2_range = c2.high - c2.low; c1_range = c1.high - c1.low; c3_range = c3.high - c3.low
            c1_body = abs(c1.open - c1.close); c3_body = abs(c3.open - c3.close)
            entry = min(c2.open, c2.close) - ENTRY_FRAC*wick
            sl = c2.low; tp = c3.high
            s, r, rr = sim_1m('long', entry, sl, tp, start_1m)
            setups.append({
                'dir':'long', 'status':s, 'r':r, 'rr':rr,
                'c2_opp_wick_pct': (c2.high - max(c2.open,c2.close))/c2_range if c2_range>0 else 0,
                'c2_body_gt_c1': body > c1_body,
                'c3_body_gt_c2': c3_body > body,
                'c3_close_extreme_pct': (c3.high - c3.close)/c3_range if c3_range>0 else 0,  # 0=high (хорошо для LONG)
                'sweep_depth_b': (c1.low - c2.low)/body if body>0 else 0,
                'c3_above_c1_high': c3.close > c1.high,
                'c3_below_c1_low': c3.close > c1.high,  # для LONG = mirror; называем общий ключ
                'c2_body_pct': body/c2_range if c2_range>0 else 0,
                'c1_body_pct': c1_body/c1_range if c1_range>0 else 0,
                'wick_body': wick/body,
            })

print(f"Total setups (canon wick>=2.5): {len(setups)}")

def m(subset, label):
    filled = [t for t in subset if t['status'] not in ('no_fill','invalid')]
    if len(filled) < 5:
        print(f"  {label:<48}  n={len(filled)} (insufficient)")
        return None
    wins = sum(1 for t in filled if t['status']=='win')
    totr = sum(t['r'] for t in filled)
    print(f"  {label:<48}  n_set={len(subset):>3} filled={len(filled):>3}  WR={wins/len(filled)*100:>5.1f}%  R/tr={totr/len(filled):>+6.3f}  R/yr={totr/WINDOW_YEARS:>+5.2f}")
    return totr/len(filled)

print(f"\n{'='*100}\nBASELINE (канон оба, без доп-фильтров):\n{'='*100}")
m(setups, "BASELINE")

print(f"\n{'='*100}\nF1. c2 opposite-wick ≤ X%  (чистое wick-rejection):\n{'='*100}")
for thr in [0.40, 0.30, 0.20, 0.10, 0.05]:
    m([t for t in setups if t['c2_opp_wick_pct'] <= thr], f"c2_opp_wick ≤ {int(thr*100)}%")

print(f"\n{'='*100}\nF2. c2.body > c1.body:\n{'='*100}")
m([t for t in setups if t['c2_body_gt_c1']], "c2.body > c1.body")
m([t for t in setups if not t['c2_body_gt_c1']], "c2.body ≤ c1.body")

print(f"\n{'='*100}\nF3. c3.body > c2.body (c3 ускорение):\n{'='*100}")
m([t for t in setups if t['c3_body_gt_c2']], "c3.body > c2.body")
m([t for t in setups if not t['c3_body_gt_c2']], "c3.body ≤ c2.body")

print(f"\n{'='*100}\nF4. c3 close в N% extreme (сильный close):\n{'='*100}")
for thr in [0.50, 0.30, 0.20, 0.10]:
    m([t for t in setups if t['c3_close_extreme_pct'] <= thr], f"c3 close в нижних/верхних {int(thr*100)}% range")

print(f"\n{'='*100}\nF5. sweep_depth ≥ X тел c2:\n{'='*100}")
for thr in [0.5, 1.0, 1.5, 2.0, 3.0]:
    m([t for t in setups if t['sweep_depth_b'] >= thr], f"sweep_depth ≥ {thr}×body")

print(f"\n{'='*100}\nF6. c3 close beyond c1 low/high (full continuation):\n{'='*100}")
m([t for t in setups if t['dir']=='short' and t.get('c3_below_c1_low')] +
  [t for t in setups if t['dir']=='long' and t.get('c3_above_c1_high', False)],
  "c3 close beyond c1 extreme")

print(f"\n{'='*100}\nF7. c2.body / c2.range ≥ X (не fakeout):\n{'='*100}")
for thr in [0.05, 0.10, 0.15, 0.20, 0.30]:
    m([t for t in setups if t['c2_body_pct'] >= thr], f"c2_body/range ≥ {int(thr*100)}%")

print(f"\n{'='*100}\nF8. c1.body / c1.range ≥ X (c1 solid):\n{'='*100}")
for thr in [0.30, 0.50, 0.70]:
    m([t for t in setups if t['c1_body_pct'] >= thr], f"c1_body/range ≥ {int(thr*100)}%")

print(f"\n{'='*100}\nF9. wick/body bins:\n{'='*100}")
for lo, hi in [(2.5,3.5),(3.5,5.0),(5.0,8.0),(8.0,1e9)]:
    m([t for t in setups if lo <= t['wick_body'] < hi], f"wick/body ∈ [{lo}, {hi if hi<100 else '∞'})")

# Топ комбинации
print(f"\n{'='*100}\nКОМБИНАЦИИ топ-фильтров:\n{'='*100}")

def both(f):
    return [t for t in setups if f(t)]

combos = [
    ("c3 body > c2 body  +  sweep_depth ≥ 1", lambda t: t['c3_body_gt_c2'] and t['sweep_depth_b'] >= 1.0),
    ("c3 close в 30% extreme  +  c3 body > c2", lambda t: t['c3_close_extreme_pct'] <= 0.30 and t['c3_body_gt_c2']),
    ("c2 opp_wick ≤ 20%  +  sweep_depth ≥ 1", lambda t: t['c2_opp_wick_pct'] <= 0.20 and t['sweep_depth_b'] >= 1.0),
    ("c3 close в 30%  +  c2 opp_wick ≤ 20%", lambda t: t['c3_close_extreme_pct'] <= 0.30 and t['c2_opp_wick_pct'] <= 0.20),
    ("c3 body > c2  +  c3 close в 30%  +  c2_opp ≤ 30%",
     lambda t: t['c3_body_gt_c2'] and t['c3_close_extreme_pct'] <= 0.30 and t['c2_opp_wick_pct'] <= 0.30),
    ("c2_body/range ≥ 10%  +  c3 body > c2", lambda t: t['c2_body_pct'] >= 0.10 and t['c3_body_gt_c2']),
]
for label, f in combos:
    m(both(f), label)
