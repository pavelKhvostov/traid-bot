"""Combined upgrade: Entry = block.top, SL = pattern_low + 0.1×(block.bottom − pattern_low),
TP = baseline TP price (unchanged).

LONG only. Сравнение с baseline и отдельными upgrades.
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


def simulate(entry, sl, tp, start_ms):
    sk = idx_at(start_ms); ek = min(sk + MAX_HOLD_MIN, len(data))
    in_trade = False
    for k in range(sk, ek):
        _, _, h_, l_, _, _ = data[k]
        if not in_trade:
            if l_ <= entry:
                in_trade = True
                if l_ <= sl: return "loss"
                if h_ >= tp: return "win"
        else:
            if l_ <= sl: return "loss"
            if h_ >= tp: return "win"
    return "no_fill"


patterns = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None or ir.direction != "long": continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != "long": continue
    patterns.append((ir, c5))


def run(name, entry_fn, sl_fn):
    n_w = 0; n_l = 0; n_nf = 0; n_skip = 0
    tr_new = 0.0; tr_base = 0.0
    rrs = []
    for ir, c5 in patterns:
        block_b, block_t = ir.rdrb.block
        all5 = [ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]
        pl = min(c.low for c in all5)
        entry_base = (block_b + block_t) / 2
        r_unit_base = entry_base - pl
        if r_unit_base <= 0: n_skip += 1; continue
        tp_abs = entry_base + r_unit_base

        entry = entry_fn(block_b, block_t, pl)
        sl = sl_fn(block_b, block_t, pl)
        if entry <= sl or entry >= tp_abs: n_skip += 1; continue
        r_unit_new = entry - sl
        rr_new = (tp_abs - entry) / r_unit_new
        c5_close_ms = c5.open_time + MS_HOUR
        out = simulate(entry, sl, tp_abs, c5_close_ms)
        if out == "win":
            n_w += 1
            tr_new += rr_new
            tr_base += (tp_abs - entry) / r_unit_base
            rrs.append(rr_new)
        elif out == "loss":
            n_l += 1
            tr_new -= 1.0
            tr_base += (sl - entry) / r_unit_base
        else:
            n_nf += 1
    nf = n_w + n_l
    wr = n_w / nf * 100 if nf else 0
    avg = sum(rrs) / len(rrs) if rrs else 0
    print(f"{name:<55} n={nf:<5} W={n_w:<5} L={n_l:<5} WR={wr:<7.2f}% ΣR_new={tr_new:<+8.1f} ΣR_base={tr_base:<+8.1f} avg_RR={avg:.2f}")
    return {"n": nf, "win": n_w, "loss": n_l, "tr_new": tr_new, "tr_base": tr_base, "avg_rr": avg, "wr": wr}


print(f"\n{len(patterns)} LONG patterns")
print()
print(f"{'Strategy':<55} {'n':<6} {'WIN':<6} {'LOSS':<6} {'WR':<10} {'ΣR_new':<11} {'ΣR_base':<11} {'avg_RR':<8}")
print("-" * 130)

base = run("A baseline (entry=midpoint, SL=pl)",
           lambda bb, bt, pl: (bb + bt) / 2,
           lambda bb, bt, pl: pl)

opt1 = run("B entry=block.top, SL=pl",
           lambda bb, bt, pl: bt,
           lambda bb, bt, pl: pl)

opt2 = run("C entry=midpoint, SL=pl+0.1×(bb-pl)",
           lambda bb, bt, pl: (bb + bt) / 2,
           lambda bb, bt, pl: pl + 0.1 * (bb - pl))

opt3 = run("D entry=block.top, SL=pl+0.1×(bb-pl) [combined]",
           lambda bb, bt, pl: bt,
           lambda bb, bt, pl: pl + 0.1 * (bb - pl))

# дополнительно sweep SL для entry = block.top
print()
for sl_off in (0.0, 0.1, 0.2, 0.3, 0.5):
    sl_desc = f"pl+{sl_off:.1f}×(bb-pl)" if sl_off > 0 else "pl"
    run(f"  E entry=block.top, SL={sl_desc}",
        lambda bb, bt, pl: bt,
        lambda bb, bt, pl, off=sl_off: pl + off * (bb - pl))

print(f"\n=== Сравнение ===")
print(f"Baseline (A):                        ΣR_new={base['tr_new']:+.1f}, ΣR_base={base['tr_base']:+.1f}, WR={base['wr']:.2f}%")
print(f"D (combined entry=bt + SL=0.1):      ΣR_new={opt3['tr_new']:+.1f}, ΣR_base={opt3['tr_base']:+.1f}, WR={opt3['wr']:.2f}%")
print(f"Δ vs baseline:                        ΣR_new={opt3['tr_new']-base['tr_new']:+.1f}, ΣR_base={opt3['tr_base']-base['tr_base']:+.1f}, WR={opt3['wr']-base['wr']:+.2f}pp")
