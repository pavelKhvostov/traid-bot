"""Бэктест с фильтром по направлению maxV (ASVK ViC).

Гипотеза: брать LONG только если maxV-направление BULL, SHORT — только BEAR.

Anchor maxV: 1m свеча с pattern_low (LONG) / pattern_high (SHORT).
Окно: anchor → C5 close (момент detection, до постановки лимитки).
Granularity: 1m (LTF auto для 1h chart, mlt=100).

maxV дирекция = BULL если max_bull_vol > max_bear_vol среди 1m в окне.
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

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MS_HOUR = 3600_000
MS_5M = 5 * 60_000
MAX_HOLD_MIN = 30 * 24 * 60


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return rows


def aggregate_1h(d):
    out = []; cb = None; o = h = l = c = 0
    for ts, oo, hh, ll, cc, _ in d:
        b = ts - (ts % MS_HOUR)
        if b != cb:
            if cb is not None: out.append(Candle(open=o, high=h, low=l, close=c, open_time=cb))
            cb = b; o, h, l, c = oo, hh, ll, cc
        else:
            h = max(h, hh); l = min(l, ll); c = cc
    if cb is not None: out.append(Candle(open=o, high=h, low=l, close=c, open_time=cb))
    return out


print("Loading 1m..."); data = load_1m(); ts_arr = [r[0] for r in data]
candles_1h = aggregate_1h(data); print(f"{len(data):,} 1m → {len(candles_1h):,} 1h")


def idx_at(ms):
    lo, hi = 0, len(ts_arr)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_arr[m] < ms: lo = m + 1
        else: hi = m
    return lo


def find_extreme_1m(s, e, side, val):
    for k in range(idx_at(s), idx_at(e)):
        if side == "long" and data[k][3] == val: return k
        if side == "short" and data[k][2] == val: return k
    return None


def maxv_direction(anchor_idx, end_idx):
    """Возвращает 'BULL' / 'BEAR' / 'NONE' направление maxV в [anchor, end] на 1m."""
    max_bull_v = 0.0; max_bear_v = 0.0; max_bull_close = None; max_bear_close = None
    for k in range(anchor_idx, end_idx):
        _, o, _, _, c, v = data[k]
        if c > o and v > max_bull_v:
            max_bull_v = v; max_bull_close = c
        elif c < o and v > max_bear_v:
            max_bear_v = v; max_bear_close = c
    if max_bull_v > max_bear_v: return "BULL", max_bull_close
    if max_bear_v > max_bull_v: return "BEAR", max_bear_close
    return "NONE", None


patterns = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None: continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != ir.direction: continue
    patterns.append((ir, c5))
print(f"{len(patterns)} patterns\n")

# Считаем maxV для каждого паттерна и собираем outcomes
records = []
for ir, c5 in patterns:
    side = ir.direction
    block_b, block_t = ir.rdrb.block
    entry = (block_b + block_t) / 2
    all5 = [ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]
    if side == "long":
        sl = min(c.low for c in all5)
    else:
        sl = max(c.high for c in all5)
    r_unit = (entry - sl) if side == "long" else (sl - entry)
    if r_unit <= 0: continue
    tp = entry + r_unit if side == "long" else entry - r_unit

    # Anchor 1m: pattern extreme
    anchor_k = find_extreme_1m(ir.rdrb.c1.open_time, c5.open_time + MS_HOUR, side, sl)
    if anchor_k is None: continue

    # maxV окно: anchor → C5 close
    c5_close_idx = idx_at(c5.open_time + MS_HOUR)
    maxv_dir, maxv_close = maxv_direction(anchor_k, c5_close_idx)

    # Backtest baseline (0.5 block + RR=1)
    start_k = c5_close_idx
    end_k = min(start_k + MAX_HOLD_MIN, len(data))
    in_trade = False; outcome = "no_fill"; r_val = 0.0
    for k in range(start_k, end_k):
        _, _, h_, l_, _, _ = data[k]
        if not in_trade:
            if side == "long" and l_ <= entry:
                in_trade = True
                if l_ <= sl: outcome = "loss"; r_val = -1.0; break
                if h_ >= tp: outcome = "win"; r_val = +1.0; break
            elif side == "short" and h_ >= entry:
                in_trade = True
                if h_ >= sl: outcome = "loss"; r_val = -1.0; break
                if l_ <= tp: outcome = "win"; r_val = +1.0; break
        else:
            if side == "long":
                if l_ <= sl: outcome = "loss"; r_val = -1.0; break
                if h_ >= tp: outcome = "win"; r_val = +1.0; break
            else:
                if h_ >= sl: outcome = "loss"; r_val = -1.0; break
                if l_ <= tp: outcome = "win"; r_val = +1.0; break
    if outcome not in ("win", "loss"):
        continue
    records.append({"side": side, "outcome": outcome, "r": r_val, "maxv_dir": maxv_dir})

print(f"Closed trades: {len(records)}\n")


def report(name, items):
    if not items:
        print(f"{name:<45} n=0"); return
    n = len(items); w = sum(1 for x in items if x["outcome"] == "win")
    sr = sum(x["r"] for x in items)
    wr = w / n * 100
    nl = sum(1 for x in items if x["side"] == "long")
    ns = sum(1 for x in items if x["side"] == "short")
    rl = sum(x["r"] for x in items if x["side"] == "long")
    rs = sum(x["r"] for x in items if x["side"] == "short")
    wrl = sum(1 for x in items if x["side"]=="long" and x["outcome"]=="win") / nl * 100 if nl else 0
    wrs = sum(1 for x in items if x["side"]=="short" and x["outcome"]=="win") / ns * 100 if ns else 0
    print(f"{name:<45} n={n:<5} WR={wr:5.2f}%  ΣR={sr:+7.1f}  L={nl}({wrl:.0f}%)/{rl:+.1f}R  S={ns}({wrs:.0f}%)/{rs:+.1f}R")


print(f"{'Filter':<45} {'Stats':<70}")
print("-" * 115)
report("BASELINE (all trades)", records)
print()
report("LONG+BULL maxV   /   SHORT+BEAR maxV (match)",
       [x for x in records if (x["side"]=="long" and x["maxv_dir"]=="BULL") or (x["side"]=="short" and x["maxv_dir"]=="BEAR")])
report("LONG+BEAR maxV   /   SHORT+BULL maxV (anti)",
       [x for x in records if (x["side"]=="long" and x["maxv_dir"]=="BEAR") or (x["side"]=="short" and x["maxv_dir"]=="BULL")])
report("maxV = NONE (нет volume)",
       [x for x in records if x["maxv_dir"] == "NONE"])
print()
report("LONG only,  maxV=BULL", [x for x in records if x["side"]=="long" and x["maxv_dir"]=="BULL"])
report("LONG only,  maxV=BEAR", [x for x in records if x["side"]=="long" and x["maxv_dir"]=="BEAR"])
report("SHORT only, maxV=BEAR", [x for x in records if x["side"]=="short" and x["maxv_dir"]=="BEAR"])
report("SHORT only, maxV=BULL", [x for x in records if x["side"]=="short" and x["maxv_dir"]=="BULL"])

# Distribution
n_bull = sum(1 for x in records if x["maxv_dir"]=="BULL")
n_bear = sum(1 for x in records if x["maxv_dir"]=="BEAR")
print(f"\nmaxV distribution: BULL={n_bull} ({n_bull/len(records)*100:.1f}%), BEAR={n_bear} ({n_bear/len(records)*100:.1f}%)")
