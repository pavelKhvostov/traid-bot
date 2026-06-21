"""Найти и показать пример сделки run_3candles_sweep (1h, опт wick 3.5 + entry 0.5)."""
from __future__ import annotations
import csv, pathlib, sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle

MSK = timezone(timedelta(hours=3))
MS_M = 60_000
TF1H = 60*MS_M
DATA = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"

def load(fn):
    rows = []
    with fn.open() as f:
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

print("Load + aggregate...")
rows = load(DATA)
bars = agg(rows, TF1H)
print(f"  {len(bars)} 1h bars")

WICK_RATIO = 3.5
ENTRY_FRAC = 0.5
WIN_FROM = bars[-1][0] - 90*24*3600*1000  # последние 90 дней

cans = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars]

results = []
for i in range(2, len(cans)):
    if bars[i][0] < WIN_FROM: continue
    c1, c2, c3 = cans[i-2], cans[i-1], cans[i]
    for direction in ("short", "long"):
        if direction == "short":
            if not (c1.is_bear and c2.is_bear and c3.is_bear): continue
            if c2.high <= c1.high: continue
            wick = c2.high - max(c2.open, c2.close)
            body = abs(c2.open - c2.close)
            if body == 0 or wick < WICK_RATIO*body: continue
            entry = max(c2.open, c2.close) + ENTRY_FRAC * wick
            sl = c2.high; tp = c3.low
        else:
            if not (c1.is_bull and c2.is_bull and c3.is_bull): continue
            if c2.low >= c1.low: continue
            wick = min(c2.open, c2.close) - c2.low
            body = abs(c2.open - c2.close)
            if body == 0 or wick < WICK_RATIO*body: continue
            entry = min(c2.open, c2.close) - ENTRY_FRAC * wick
            sl = c2.low; tp = c3.high
        risk = abs(sl - entry); reward = abs(entry - tp)
        if risk == 0: continue
        planned_rr = reward / risk
        # simulate fill + exit
        fill_idx = None
        for j in range(i+1, min(i+1+6, len(bars))):
            bj = bars[j]
            if direction == "short":
                if bj[2] >= entry: fill_idx = j; break
            else:
                if bj[3] <= entry: fill_idx = j; break
        if fill_idx is None:
            results.append({'i':i, 'dir':direction, 'c1':c1, 'c2':c2, 'c3':c3, 'entry':entry, 'sl':sl, 'tp':tp,
                            'status':'no_fill', 'r_mult':0.0, 'planned_rr':planned_rr, 'fill_idx':None, 'exit_idx':None, 'exit_px':None})
            continue
        status=None; r_mult=None; exit_idx=None; exit_px=None
        for j in range(fill_idx, min(fill_idx+30, len(bars))):
            bj = bars[j]
            if direction=='short':
                sl_hit=bj[2]>=sl; tp_hit=bj[3]<=tp
            else:
                sl_hit=bj[3]<=sl; tp_hit=bj[2]>=tp
            if sl_hit and tp_hit:
                if abs(bj[1]-sl) < abs(bj[1]-tp): status='loss'; r_mult=-1.0; exit_px=sl
                else: status='win'; r_mult=planned_rr; exit_px=tp
                exit_idx=j; break
            if sl_hit: status='loss'; r_mult=-1.0; exit_px=sl; exit_idx=j; break
            if tp_hit: status='win'; r_mult=planned_rr; exit_px=tp; exit_idx=j; break
        if status is None:
            j = min(fill_idx+30-1, len(bars)-1)
            bj=bars[j]
            if direction=='short': r_mult=(entry-bj[4])/risk
            else: r_mult=(bj[4]-entry)/risk
            status='timeout'; exit_idx=j; exit_px=bj[4]
        results.append({'i':i, 'dir':direction, 'c1':c1, 'c2':c2, 'c3':c3, 'entry':entry, 'sl':sl, 'tp':tp,
                        'status':status, 'r_mult':r_mult, 'planned_rr':planned_rr,
                        'fill_idx':fill_idx, 'exit_idx':exit_idx, 'exit_px':exit_px})

wins = [r for r in results if r['status']=='win']
print(f"\nЗа последние 90 дней (1h BTC, опт wick 3.5 + entry 0.5):")
print(f"  Всего сетапов: {len(results)}, win: {len(wins)}, loss: {sum(1 for r in results if r['status']=='loss')}, "
      f"timeout: {sum(1 for r in results if r['status']=='timeout')}, no_fill: {sum(1 for r in results if r['status']=='no_fill')}")

def fmt_ts(ms):
    return datetime.fromtimestamp(ms/1000, MSK).strftime('%Y-%m-%d %H:%M MSK')

def show(label, r):
    print(f"\n{'='*70}\n{label}\n{'='*70}")
    print(f"  Direction: {r['dir'].upper()}")
    print(f"  C1 {fmt_ts(r['c1'].open_time):<24} O={r['c1'].open:>10.2f} H={r['c1'].high:>10.2f} L={r['c1'].low:>10.2f} C={r['c1'].close:>10.2f}")
    print(f"  C2 {fmt_ts(r['c2'].open_time):<24} O={r['c2'].open:>10.2f} H={r['c2'].high:>10.2f} L={r['c2'].low:>10.2f} C={r['c2'].close:>10.2f}")
    print(f"  C3 {fmt_ts(r['c3'].open_time):<24} O={r['c3'].open:>10.2f} H={r['c3'].high:>10.2f} L={r['c3'].low:>10.2f} C={r['c3'].close:>10.2f}")
    if r['dir']=='short':
        wick = r['c2'].high - max(r['c2'].open, r['c2'].close)
    else:
        wick = min(r['c2'].open, r['c2'].close) - r['c2'].low
    body = abs(r['c2'].open - r['c2'].close)
    print(f"  C2 wick: {wick:.2f}, body: {body:.2f}, ratio: {wick/body:.2f}× (требование ≥3.5×)")
    risk = abs(r['sl']-r['entry']); reward = abs(r['entry']-r['tp'])
    print(f"\n  Setup:")
    print(f"    Entry = {r['entry']:.2f}  (= max(o,c) + 0.5×wick)")
    print(f"    SL    = {r['sl']:.2f}  (риск {risk:.2f})")
    print(f"    TP    = {r['tp']:.2f}  (reward {reward:.2f})")
    print(f"    Planned RR = 1:{r['planned_rr']:.2f}")
    if r['fill_idx'] is not None:
        print(f"\n  Execution:")
        print(f"    Fill: {fmt_ts(bars[r['fill_idx']][0])}")
        print(f"    Exit: {fmt_ts(bars[r['exit_idx']][0])} @ {r['exit_px']:.2f} → {r['status'].upper()}, R = {r['r_mult']:+.2f}")

# 1 win, 1 loss, 1 свежий
if wins:
    show("ПРИМЕР WIN (последний из 90д)", wins[-1])
losses = [r for r in results if r['status']=='loss']
if losses:
    show("ПРИМЕР LOSS (последний из 90д)", losses[-1])
print(f"\n\nВсе сетапы за последние 90 дней:")
print(f"  {'#':<3} {'dir':<6} {'C3 close time':<22} {'status':<10} {'R':>+7} {'RR plan':>8}")
for k, r in enumerate(results[-30:], start=max(1, len(results)-30+1)):
    print(f"  {k:<3} {r['dir']:<6} {fmt_ts(r['c3'].open_time):<22} {r['status']:<10} {r['r_mult']:>+7.2f} {r['planned_rr']:>8.2f}")
