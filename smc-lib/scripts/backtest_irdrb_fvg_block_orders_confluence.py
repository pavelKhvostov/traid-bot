"""i-RDRB+FVG × block_orders confluence на 1h.

Для каждого из 1094 setups (V1+V2) на BTC 1h за 6y проверяем:
- Пересекаются ли свечи паттерна со свечами какого-либо block_orders на том же 1h
- Полностью / частично / нет
- Совпадение направления (block_orders LONG/SHORT vs i-RDRB+FVG LONG/SHORT)

Бэктест Combined D entry/SL + RR=1.0 для каждой подвыборки.
"""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.i_rdrb.code import detect_i_rdrb
from elements.fvg.code import detect_fvg
from elements.block_orders.code import detect_block_orders

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MS_HOUR = 3600_000
MAX_HOLD_MIN = 30 * 24 * 60


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]) if len(r) > 5 else 0.0))
    return rows


def aggregate(d, tf_min):
    bucket = tf_min * 60_000
    out = []; cb = None; o = h = l = c = 0
    for ts, oo, hh, ll, cc, _ in d:
        b = ts - (ts % bucket)
        if b != cb:
            if cb is not None: out.append(Candle(open=o, high=h, low=l, close=c, open_time=cb))
            cb = b; o, h, l, c = oo, hh, ll, cc
        else:
            h = max(h, hh); l = min(l, ll); c = cc
    if cb is not None: out.append(Candle(open=o, high=h, low=l, close=c, open_time=cb))
    return out


print("Loading 1m..."); data = load_1m()
candles_1h = aggregate(data, 60)
ts_1m = [r[0] for r in data]
last_ts = data[-1][0]
window_start_ms = last_ts - 6 * 365 * 24 * 3600 * 1000
candles_1h_w = [c for c in candles_1h if c.open_time >= window_start_ms]
print(f"  {len(candles_1h_w):,} 1h bars in 6y window")


def idx_at(ms):
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_1m[m] < ms: lo = m + 1
        else: hi = m
    return lo


def simulate(side, entry, sl, tp, start_ms):
    sk = idx_at(start_ms); ek = min(sk + MAX_HOLD_MIN, len(data))
    in_trade = False
    for k in range(sk, ek):
        _, _, h_, l_, _, _ = data[k]
        if not in_trade:
            if side == "long":
                if l_ <= entry:
                    in_trade = True
                    if l_ <= sl: return "loss"
                    if h_ >= tp: return "win"
            else:
                if h_ >= entry:
                    in_trade = True
                    if h_ >= sl: return "loss"
                    if l_ <= tp: return "win"
        else:
            if side == "long":
                if l_ <= sl: return "loss"
                if h_ >= tp: return "win"
            else:
                if h_ >= sl: return "loss"
                if l_ <= tp: return "win"
    return "no_fill"


# ===== Детект i-RDRB+FVG V1+V2 =====
setups = []   # list of (ir, variant, pattern_idx_range, pl, ph, start_ms)
for i in range(len(candles_1h_w) - 5):
    c1, c2, c3, c4, c5, c6 = candles_1h_w[i:i + 6]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None: continue

    fvg_v1 = detect_fvg(c3, c4, c5)
    if fvg_v1 and fvg_v1.direction == ir.direction:
        pl = min(c.low for c in (c1, c2, c3, c4, c5))
        ph = max(c.high for c in (c1, c2, c3, c4, c5))
        setups.append({
            'ir': ir, 'variant': 'V1',
            'idx_lo': i, 'idx_hi': i + 4,   # 5 свечей [i..i+4]
            'pl': pl, 'ph': ph,
            'start_ms': c5.open_time + MS_HOUR,
        })

    fvg_v2 = detect_fvg(c4, c5, c6)
    if fvg_v2 and fvg_v2.direction == ir.direction:
        pl = min(c.low for c in (c1, c2, c3, c4, c5, c6))
        ph = max(c.high for c in (c1, c2, c3, c4, c5, c6))
        setups.append({
            'ir': ir, 'variant': 'V2',
            'idx_lo': i, 'idx_hi': i + 5,   # 6 свечей [i..i+5]
            'pl': pl, 'ph': ph,
            'start_ms': c6.open_time + MS_HOUR,
        })

print(f"  Total setups V1+V2: {len(setups)}")

# ===== Детект block_orders на 1h =====
print("Scanning block_orders...")
bo_list = []   # list of (idx_lo, idx_hi, direction)
seen = set()
for end in range(2, len(candles_1h_w)):
    for start in range(max(0, end - 8), end - 1):   # шире скан
        slice_ = candles_1h_w[start:end + 1]
        r = detect_block_orders(slice_)
        if r:
            # candles_idx: preceding=start, initial=start+1..start+n_initial, counter=...
            # block candles: start+1 .. start+n_initial+n_counter
            block_lo = start + 1
            block_hi = start + r.n_initial + r.n_counter
            key = (block_lo, r.n_initial, r.n_counter)
            if key in seen: continue
            seen.add(key)
            bo_list.append({
                'idx_lo': block_lo, 'idx_hi': block_hi,
                'direction': r.direction,
                'n_initial': r.n_initial, 'n_counter': r.n_counter,
            })

print(f"  Total block_orders 1h 6y: {len(bo_list)}")

# ===== Classify each setup by overlap =====
def overlap_class(setup, bo_list):
    """Returns (overlap_type, dir_match)
       overlap_type: 'full' / 'partial' / 'none'
       dir_match: 'same' / 'opposite' / 'none' (if no overlap)
    """
    s_lo, s_hi = setup['idx_lo'], setup['idx_hi']
    s_dir = setup['ir'].direction
    full_overlap_dir = None
    partial_overlap_dir = None
    for bo in bo_list:
        b_lo, b_hi = bo['idx_lo'], bo['idx_hi']
        if b_hi < s_lo or b_lo > s_hi: continue   # no overlap
        # есть пересечение
        bo_dir = bo['direction']
        if b_lo <= s_lo and b_hi >= s_hi:
            # block_orders полностью покрывает паттерн
            full_overlap_dir = bo_dir
        else:
            if partial_overlap_dir is None:
                partial_overlap_dir = bo_dir

    if full_overlap_dir is not None:
        return 'full', ('same' if full_overlap_dir == s_dir else 'opposite')
    if partial_overlap_dir is not None:
        return 'partial', ('same' if partial_overlap_dir == s_dir else 'opposite')
    return 'none', 'none'


print("Classifying setups by block_orders overlap...")
buckets = {}
for s in setups:
    ov, dm = overlap_class(s, bo_list)
    key = (ov, dm)
    buckets.setdefault(key, []).append(s)

print(f"\n  Распределение setups по overlap:")
for k, v in sorted(buckets.items()):
    print(f"    {k[0]:<8} / {k[1]:<8}: {len(v):>4}")


# ===== Backtest каждой bucket =====
def trade_setup(setup):
    """Returns (outcome, rr)."""
    side = setup['ir'].direction
    bb, bt = setup['ir'].rdrb.block
    pl, ph = setup['pl'], setup['ph']

    if side == "long":
        entry = bt
        sl = pl + 0.1 * (bb - pl)
        r_unit = entry - sl
        if r_unit <= 0: return None
        tp = entry + 1.0 * r_unit
    else:
        entry = bb
        sl = ph - 0.1 * (ph - bt)
        r_unit = sl - entry
        if r_unit <= 0: return None
        tp = entry - 1.0 * r_unit

    outcome = simulate(side, entry, sl, tp, setup['start_ms'])
    return outcome


def run_bucket(name, setups_list):
    win = loss = nf = 0
    long_win = long_loss = short_win = short_loss = 0
    sr = 0.0
    for s in setups_list:
        out = trade_setup(s)
        if out is None: continue
        if out == "win":
            win += 1; sr += 1.0
            if s['ir'].direction == 'long': long_win += 1
            else: short_win += 1
        elif out == "loss":
            loss += 1; sr -= 1.0
            if s['ir'].direction == 'long': long_loss += 1
            else: short_loss += 1
        else: nf += 1
    n = win + loss
    wr = win / n * 100 if n else 0
    rper = sr / n if n else 0
    l_n = long_win + long_loss; s_n = short_win + short_loss
    wr_l = long_win/l_n*100 if l_n else 0
    wr_s = short_win/s_n*100 if s_n else 0
    return {'name': name, 'total': len(setups_list), 'n': n, 'nf': nf, 'win': win, 'loss': loss,
            'wr': wr, 'sr': sr, 'rper': rper,
            'l_n': l_n, 'l_w': long_win, 'l_wr': wr_l,
            's_n': s_n, 's_w': short_win, 's_wr': wr_s}


print("\nBacktesting buckets...")
results = []
order_keys = [
    (('full', 'same'),     'FULL overlap · SAME dir'),
    (('full', 'opposite'), 'FULL overlap · OPPOSITE dir'),
    (('partial', 'same'),     'PARTIAL overlap · SAME dir'),
    (('partial', 'opposite'), 'PARTIAL overlap · OPPOSITE dir'),
    (('none', 'none'),     'NO overlap (no block_orders)'),
]
for key, name in order_keys:
    if key not in buckets: continue
    results.append(run_bucket(name, buckets[key]))

# Total
all_setups = [s for k, lst in buckets.items() for s in lst]
results.append(run_bucket('TOTAL (V1+V2)', all_setups))

# Print
print(f"\n{'='*92}")
print(f"{'Bucket':<32} {'setups':>6} {'closed':>6} {'WR':>7} {'ΣR':>8} {'R/tr':>7}  {'LONG WR':>8} {'SHORT WR':>9}")
print(f"{'-'*92}")
for r in results:
    print(f"{r['name']:<32} {r['total']:>6} {r['n']:>6} {r['wr']:>6.2f}% {r['sr']:>+8.1f} {r['rper']:>+7.3f}  {r['l_w']:>3}/{r['l_n']:<3} {r['l_wr']:>5.1f}%  {r['s_w']:>3}/{r['s_n']:<3} {r['s_wr']:>5.1f}%")
