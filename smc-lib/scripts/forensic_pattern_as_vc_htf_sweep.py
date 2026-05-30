"""Гипотеза: i-RDRB+FVG (1h) — это VC (как в стратегии 1.1.1).
Ему нужен C1 = sweep FH/FL на HTF ∈ {4h, 12h, 1d}, Williams N=2.

Sweep = свеча wick'ом пробивает unmitigated FH/FL и close-ит обратно
(close < FH для bearish sweep / close > FL для bullish sweep).

Направление: LONG i-RDRB ↔ свежий swept FL; SHORT ↔ swept FH.

Окна (sweep должен произойти):
  W0: внутри pattern (C1.open ≤ sweep_ts < C5.close)
  W1: внутри pattern OR ≤ N bars HTF до C1.open
"""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.i_rdrb.code import detect_i_rdrb
from elements.fvg.code import detect_fvg

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MS_HOUR = 3600_000
MAX_HOLD_MIN = 30 * 24 * 60

HTFS = [("4h", 240), ("12h", 720), ("1d", 1440)]
WILLIAMS_N = 2


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
    sk = idx_at(start_ms); ek = min(sk + MAX_HOLD_MIN, len(data))
    in_trade = False; fill_ms = None
    for k in range(sk, ek):
        ts, _, h_, l_, _, _ = data[k]
        if not in_trade:
            if side == "long":
                if l_ <= entry:
                    in_trade = True; fill_ms = ts
                    if l_ <= sl: return "loss", fill_ms
                    if h_ >= tp: return "win", fill_ms
            else:
                if h_ >= entry:
                    in_trade = True; fill_ms = ts
                    if h_ >= sl: return "loss", fill_ms
                    if l_ <= tp: return "win", fill_ms
        else:
            if side == "long":
                if l_ <= sl: return "loss", fill_ms
                if h_ >= tp: return "win", fill_ms
            else:
                if h_ >= sl: return "loss", fill_ms
                if l_ <= tp: return "win", fill_ms
    return "no_fill", fill_ms


# === Build HTF fractal sweep DB ===
print("Building HTF FH/FL sweep DB...")
# fh_sweeps[htf] = list of {"level", "formed_ts", "sweep_ts"} for sweep events
# fl_sweeps[htf] = same
sweep_db = {}  # (htf, dir) -> list of sweep events with sweep_ts
htf_data = {}

for name, tf_min in HTFS:
    cs = aggregate(data, tf_min)
    htf_data[name] = cs
    tf_ms = tf_min * 60_000
    fh_list = []  # unmitigated FHs, then we find sweeps
    fl_list = []
    n = WILLIAMS_N
    # Find Williams fractals N=2
    for i in range(n, len(cs) - n):
        # FH: high higher than n bars on each side
        h_center = cs[i].high
        if all(cs[i].high > cs[i + k].high for k in range(-n, n + 1) if k != 0):
            fh_list.append({"level": h_center, "formed_idx": i, "formed_ts": cs[i].open_time + tf_ms})
        l_center = cs[i].low
        if all(cs[i].low < cs[i + k].low for k in range(-n, n + 1) if k != 0):
            fl_list.append({"level": l_center, "formed_idx": i, "formed_ts": cs[i].open_time + tf_ms})

    # For each FH, find first sweep: candle j > formed_idx+n with high>level AND close<level
    fh_sweeps = []
    for f in fh_list:
        for j in range(f["formed_idx"] + n + 1, len(cs)):
            if cs[j].high > f["level"] and cs[j].close < f["level"]:
                fh_sweeps.append({"level": f["level"], "sweep_ts": cs[j].open_time,
                                  "sweep_close_ts": cs[j].open_time + tf_ms})
                break
    fl_sweeps = []
    for f in fl_list:
        for j in range(f["formed_idx"] + n + 1, len(cs)):
            if cs[j].low < f["level"] and cs[j].close > f["level"]:
                fl_sweeps.append({"level": f["level"], "sweep_ts": cs[j].open_time,
                                  "sweep_close_ts": cs[j].open_time + tf_ms})
                break
    sweep_db[(name, "FH")] = sorted(fh_sweeps, key=lambda x: x["sweep_ts"])
    sweep_db[(name, "FL")] = sorted(fl_sweeps, key=lambda x: x["sweep_ts"])
    print(f"  {name}: {len(fh_list)} FH ({len(fh_sweeps)} swept), {len(fl_list)} FL ({len(fl_sweeps)} swept)")


def has_sweep_in_window(htf, dir_, t_start_ms, t_end_ms):
    """Был ли sweep_close (полное подтверждение sweep на close HTF свечи)
    в [t_start_ms, t_end_ms]?"""
    for s in sweep_db[(htf, dir_)]:
        if s["sweep_close_ts"] < t_start_ms: continue
        if s["sweep_close_ts"] > t_end_ms: break
        return True
    return False


# === Build trades + features ===
print("Building 1h trades...")
trades = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None: continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != ir.direction: continue
    side = ir.direction
    block_b, block_t = ir.rdrb.block
    entry = (block_b + block_t) / 2
    all5 = [c1, c2, c3, c4, c5]
    sl = min(c.low for c in all5) if side == "long" else max(c.high for c in all5)
    r_unit = abs(entry - sl)
    if r_unit <= 0: continue
    tp = entry + 2.2 * r_unit if side == "long" else entry - 2.2 * r_unit
    c1_open_ms = c1.open_time
    c5_close_ms = c5.open_time + MS_HOUR
    out, fill_ms = simulate(side, entry, sl, tp, c5_close_ms)
    if out not in ("win", "loss"): continue

    # Aligned sweep dir: LONG → swept FL; SHORT → swept FH
    sweep_dir = "FL" if side == "long" else "FH"
    aligned_sweeps = {}  # htf -> bool: sweep inside pattern
    aligned_sweeps_before = {}  # htf -> bool: sweep in last K HTF bars before C1
    for htf_name, tf_min in HTFS:
        # W0: внутри pattern
        w0 = has_sweep_in_window(htf_name, sweep_dir, c1_open_ms, c5_close_ms)
        aligned_sweeps[htf_name] = w0
        # W1: within last 5 HTF bars before C1 OR inside pattern
        lookback_ms = 5 * tf_min * 60_000
        wb = has_sweep_in_window(htf_name, sweep_dir, c1_open_ms - lookback_ms, c5_close_ms)
        aligned_sweeps_before[htf_name] = wb

    trades.append({
        "side": side, "outcome": out, "r_unit": r_unit,
        "c1_open_ms": c1_open_ms, "c5_close_ms": c5_close_ms, "fill_ms": fill_ms,
        "sw0": aligned_sweeps,         # in-pattern
        "sw1": aligned_sweeps_before,  # in-pattern + 5 HTF bars back
    })

n_all = len(trades)
w_all = sum(1 for t in trades if t["outcome"] == "win")
baseline_wr = w_all / n_all * 100
print(f"\nBaseline: n={n_all}, WR={baseline_wr:.2f}%\n")


def report(name, items):
    n = len(items)
    if n == 0: print(f"  {name:<60} n=0"); return
    w = sum(1 for x in items if x["outcome"] == "win")
    r = w * 2.2 - (n - w) * 1.0
    wr = w / n * 100
    print(f"  {name:<60} n={n:<4} WR={wr:5.2f}% (Δ{wr - baseline_wr:+5.2f}pp)  ΣR={r:+6.1f}  R/tr={r/n:+.3f}")


print("=" * 100)
print("=== W0: aligned HTF sweep ВНУТРИ pattern (C1.open ≤ sweep_close ≤ C5.close) ===\n")
for htf, _ in HTFS:
    sub = [t for t in trades if t["sw0"][htf]]
    report(f"in-pattern sweep on {htf}", sub)
union_w0 = [t for t in trades if any(t["sw0"][h] for h, _ in HTFS)]
inter_w0 = [t for t in trades if all(t["sw0"][h] for h, _ in HTFS)]
report("UNION (4h ∪ 12h ∪ 1d)", union_w0)
report("4h ∪ 12h", [t for t in trades if t["sw0"]["4h"] or t["sw0"]["12h"]])
report("12h ∪ 1d", [t for t in trades if t["sw0"]["12h"] or t["sw0"]["1d"]])
report("INTERSECT (4h ∩ 12h ∩ 1d)", inter_w0)
report("4h ∩ 12h", [t for t in trades if t["sw0"]["4h"] and t["sw0"]["12h"]])
report("12h ∩ 1d", [t for t in trades if t["sw0"]["12h"] and t["sw0"]["1d"]])

print("\n=== W1: aligned HTF sweep в pattern ИЛИ в последних 5 HTF bars ДО C1 ===\n")
for htf, _ in HTFS:
    sub = [t for t in trades if t["sw1"][htf]]
    report(f"in-window sweep on {htf}", sub)
union_w1 = [t for t in trades if any(t["sw1"][h] for h, _ in HTFS)]
report("UNION (4h ∪ 12h ∪ 1d) [W1]", union_w1)
report("4h ∪ 12h [W1]", [t for t in trades if t["sw1"]["4h"] or t["sw1"]["12h"]])
report("12h ∪ 1d [W1]", [t for t in trades if t["sw1"]["12h"] or t["sw1"]["1d"]])

print("\n=== NO sweep (anti-set): pattern без HTF sweep подтверждения ===\n")
none_w0 = [t for t in trades if not any(t["sw0"][h] for h, _ in HTFS)]
none_w1 = [t for t in trades if not any(t["sw1"][h] for h, _ in HTFS)]
report("NO sweep (W0)", none_w0)
report("NO sweep (W1)", none_w1)

print("\n=== By side ===\n")
for side in ("long", "short"):
    sub_w0 = [t for t in trades if t["side"] == side and any(t["sw0"][h] for h, _ in HTFS)]
    report(f"{side} + sweep UNION W0", sub_w0)
