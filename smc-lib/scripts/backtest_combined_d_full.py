"""Combined upgrade D — full coverage (LONG + SHORT mirror).

LONG:
  entry = block.top
  SL = pattern_low + 0.1 × (block.bottom − pattern_low)
  TP = baseline TP price (entry_baseline + (entry_baseline − pattern_low))

SHORT (mirror):
  entry = block.bottom
  SL = pattern_high − 0.1 × (pattern_high − block.top)
  TP = baseline TP price (entry_baseline − (pattern_high − entry_baseline))
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
MAX_HOLD_MIN = 30 * 24 * 60


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
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


print("Loading..."); data = load_1m()
candles_1h = aggregate(data, 60)
ts_1m = [r[0] for r in data]


def idx_at(ms):
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_1m[m] < ms: lo = m + 1
        else: hi = m
    return lo


def simulate(side, entry, sl, tp, start_ms):
    """LONG: SL below entry, TP above. SHORT: SL above, TP below."""
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


# Detect patterns
patterns_long = []; patterns_short = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None: continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != ir.direction: continue
    if ir.direction == "long":
        patterns_long.append((ir, c5))
    else:
        patterns_short.append((ir, c5))


def run_strategy(name, entry_fn, sl_fn):
    """Принимает entry_fn(side, bb, bt, pl, ph), sl_fn(side, bb, bt, pl, ph)."""
    stats = {"long": {"win": 0, "loss": 0, "nf": 0, "tr_new": 0.0, "tr_base": 0.0, "rrs": []},
             "short": {"win": 0, "loss": 0, "nf": 0, "tr_new": 0.0, "tr_base": 0.0, "rrs": []}}
    for side, pats in [("long", patterns_long), ("short", patterns_short)]:
        for ir, c5 in pats:
            block_b, block_t = ir.rdrb.block
            all5 = [ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]
            pl = min(c.low for c in all5)
            ph = max(c.high for c in all5)
            entry_base = (block_b + block_t) / 2
            if side == "long":
                r_unit_base = entry_base - pl
                tp_abs = entry_base + r_unit_base
            else:
                r_unit_base = ph - entry_base
                tp_abs = entry_base - r_unit_base
            if r_unit_base <= 0: continue

            entry = entry_fn(side, block_b, block_t, pl, ph)
            sl = sl_fn(side, block_b, block_t, pl, ph)
            if side == "long":
                if entry <= sl or entry >= tp_abs: continue
                r_unit_new = entry - sl
                rr_new = (tp_abs - entry) / r_unit_new
            else:
                if entry >= sl or entry <= tp_abs: continue
                r_unit_new = sl - entry
                rr_new = (entry - tp_abs) / r_unit_new

            c5_close_ms = c5.open_time + MS_HOUR
            out = simulate(side, entry, sl, tp_abs, c5_close_ms)
            s = stats[side]
            if out == "win":
                s["win"] += 1
                s["tr_new"] += rr_new
                if side == "long":
                    s["tr_base"] += (tp_abs - entry) / r_unit_base
                else:
                    s["tr_base"] += (entry - tp_abs) / r_unit_base
                s["rrs"].append(rr_new)
            elif out == "loss":
                s["loss"] += 1
                s["tr_new"] -= 1.0
                if side == "long":
                    s["tr_base"] += (sl - entry) / r_unit_base
                else:
                    s["tr_base"] += (entry - sl) / r_unit_base
            else:
                s["nf"] += 1

    tw = stats["long"]["win"] + stats["short"]["win"]
    tl = stats["long"]["loss"] + stats["short"]["loss"]
    tnf = stats["long"]["nf"] + stats["short"]["nf"]
    tr_new_total = stats["long"]["tr_new"] + stats["short"]["tr_new"]
    tr_base_total = stats["long"]["tr_base"] + stats["short"]["tr_base"]
    print(f"\n=== {name} ===")
    print(f"{'Side':<8} {'n':<6} {'WIN':<6} {'LOSS':<6} {'NoFill':<8} {'WR':<8} {'ΣR_new':<10} {'ΣR_base':<10} {'avg_RR':<8}")
    for side in ("long", "short"):
        s = stats[side]
        n = s["win"] + s["loss"]
        wr = s["win"] / n * 100 if n else 0
        avg = sum(s["rrs"]) / len(s["rrs"]) if s["rrs"] else 0
        print(f"{side.upper():<8} {n:<6} {s['win']:<6} {s['loss']:<6} {s['nf']:<8} {wr:<7.2f}% {s['tr_new']:<+10.1f} {s['tr_base']:<+10.1f} {avg:<8.2f}")
    n_t = tw + tl
    wr_t = tw / n_t * 100 if n_t else 0
    print(f"{'TOTAL':<8} {n_t:<6} {tw:<6} {tl:<6} {tnf:<8} {wr_t:<7.2f}% {tr_new_total:<+10.1f} {tr_base_total:<+10.1f}")
    return tr_new_total, tr_base_total, n_t, tw, tl


# Strategy A: baseline (entry=mid, SL=extreme)
def entry_baseline(side, bb, bt, pl, ph):
    return (bb + bt) / 2

def sl_baseline(side, bb, bt, pl, ph):
    return pl if side == "long" else ph

# Strategy D: entry=block edge, SL=0.1 from extreme
def entry_d(side, bb, bt, pl, ph):
    return bt if side == "long" else bb

def sl_d(side, bb, bt, pl, ph):
    if side == "long":
        return pl + 0.1 * (bb - pl)
    else:
        return ph - 0.1 * (ph - bt)

print(f"\n{len(patterns_long)} LONG + {len(patterns_short)} SHORT patterns")

a_n, a_b, _, _, _ = run_strategy("A baseline (entry=midpoint, SL=extreme)", entry_baseline, sl_baseline)
d_n, d_b, _, _, _ = run_strategy("D combined (entry=block edge, SL=0.1 offset)", entry_d, sl_d)

print(f"\n=== Δ vs baseline ===")
print(f"ΣR_new:   {d_n - a_n:+.1f}R")
print(f"ΣR_base:  {d_b - a_b:+.1f}R")
