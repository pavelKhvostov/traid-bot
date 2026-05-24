"""F1 ∪ F2_same фильтр для i-RDRB+FVG (BTC 1h).

F1 — HTF Order Block overlap (same direction)
  HTF: {4h, 6h, 8h, 12h, 1D}
  Bullish OB: HTF candle bearish AND next HTF candle close > candle high
  Bearish OB: HTF candle bullish AND next HTF candle close < candle low
  Pass: хотя бы одна 1h свеча из C1..C5 попадает во временной диапазон OB.

F2_same — HTF RDRB membership (same direction)
  HTF RDRB: 3 свечи по smc-lib detect_rdrb
  Pass: хотя бы одна 1h свеча из C1..C5 попадает в [c1.open, c1.open + 3*TF)
        AND HTF RDRB c3 закрылся к моменту fill candle close
  Direction matching: smc-lib direction of HTF RDRB == direction of 1h i-RDRB

Применяется к baseline (entry=mid, SL=pl, TP=baseline) для прямого сравнения с памятью.
"""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.rdrb.code import detect_rdrb
from elements.i_rdrb.code import detect_i_rdrb
from elements.fvg.code import detect_fvg

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MS_HOUR = 3600_000
MAX_HOLD_MIN = 30 * 24 * 60
HTF_LIST = [("4h", 4 * MS_HOUR), ("6h", 6 * MS_HOUR), ("8h", 8 * MS_HOUR),
            ("12h", 12 * MS_HOUR), ("1D", 24 * MS_HOUR)]


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

# Aggregate HTF candles
htf_candles = {}
for name, ms in HTF_LIST:
    tf_min = ms // 60_000
    htf_candles[name] = aggregate(data, tf_min)
    print(f"  {name}: {len(htf_candles[name])} candles")


# Detect HTF Order Blocks
htf_obs = {}  # name → list of (direction, open_ts, ts_end, high, low)
for name, cs in htf_candles.items():
    tf_ms = next(ms for n, ms in HTF_LIST if n == name)
    obs = []
    for i in range(len(cs) - 1):
        c, nxt = cs[i], cs[i + 1]
        if c.close < c.open and nxt.close > c.high:  # bullish OB (bear candle + next close above high)
            obs.append({"dir": "long", "open_ts": c.open_time, "end_ts": c.open_time + tf_ms})
        elif c.close > c.open and nxt.close < c.low:  # bearish OB
            obs.append({"dir": "short", "open_ts": c.open_time, "end_ts": c.open_time + tf_ms})
    htf_obs[name] = obs
print(f"\nHTF Order Blocks: {sum(len(v) for v in htf_obs.values())} total")


# Detect HTF RDRBs
htf_rdrbs = {}
for name, cs in htf_candles.items():
    tf_ms = next(ms for n, ms in HTF_LIST if n == name)
    rdrbs = []
    for i in range(len(cs) - 2):
        r = detect_rdrb(cs[i], cs[i + 1], cs[i + 2])
        if r is None: continue
        rdrbs.append({
            "dir": r.direction,
            "c1_ts": cs[i].open_time,
            "c3_end_ts": cs[i + 2].open_time + tf_ms,  # c3 close time
            "window_end_ts": cs[i].open_time + 3 * tf_ms,  # = c3 close
        })
    htf_rdrbs[name] = rdrbs
print(f"HTF RDRBs: {sum(len(v) for v in htf_rdrbs.values())} total")


def idx_at(ms):
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_1m[m] < ms: lo = m + 1
        else: hi = m
    return lo


def simulate(entry, sl, tp, side, start_ms):
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


# Pattern detection
patterns = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None: continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != ir.direction: continue
    patterns.append((ir, c5))
print(f"\n{len(patterns)} i-RDRB+FVG patterns ({sum(1 for p in patterns if p[0].direction=='long')} LONG, {sum(1 for p in patterns if p[0].direction=='short')} SHORT)")


def check_f1(pattern_candles, direction):
    """Хотя бы одна 1h-свеча в окне OB того же направления."""
    for name, obs in htf_obs.items():
        for ob in obs:
            if ob["dir"] != direction: continue
            for c in pattern_candles:
                if ob["open_ts"] <= c.open_time < ob["end_ts"]:
                    return True
    return False


def check_f2_same(pattern_candles, direction, fill_close_ms):
    """HTF RDRB same direction (как в памяти: old-convention same shape).

    Memory's "long pattern" = bullish reversal = new LONG i-RDRB.
    Memory's "LONG-shape HTF RDRB" = C2 bear = smc-lib SHORT RDRB.
    So 1h LONG → HTF SHORT, 1h SHORT → HTF LONG (под-RDRB shape).
    """
    htf_dir_target = "short" if direction == "long" else "long"
    for name, rdrbs in htf_rdrbs.items():
        for r in rdrbs:
            if r["dir"] != htf_dir_target: continue
            if r["c3_end_ts"] > fill_close_ms: continue  # c3 не закрылся к fill close
            for c in pattern_candles:
                if r["c1_ts"] <= c.open_time < r["window_end_ts"]:
                    return True
    return False


# Backtest baseline + filter
stats = {
    "baseline": {"long": {"w": 0, "l": 0, "tr": 0.0}, "short": {"w": 0, "l": 0, "tr": 0.0}},
    "f1_only":  {"long": {"w": 0, "l": 0, "tr": 0.0}, "short": {"w": 0, "l": 0, "tr": 0.0}},
    "f2_only":  {"long": {"w": 0, "l": 0, "tr": 0.0}, "short": {"w": 0, "l": 0, "tr": 0.0}},
    "f1_or_f2": {"long": {"w": 0, "l": 0, "tr": 0.0}, "short": {"w": 0, "l": 0, "tr": 0.0}},
    "f1_and_f2":{"long": {"w": 0, "l": 0, "tr": 0.0}, "short": {"w": 0, "l": 0, "tr": 0.0}},
}

for ir, c5 in patterns:
    side = ir.direction
    block_b, block_t = ir.rdrb.block
    entry = (block_b + block_t) / 2
    all5 = [ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]
    if side == "long":
        sl_extreme = min(c.low for c in all5)
    else:
        sl_extreme = max(c.high for c in all5)
    r_unit_base = abs(entry - sl_extreme)
    if r_unit_base <= 0: continue
    tp = entry + r_unit_base if side == "long" else entry - r_unit_base
    c5_close_ms = c5.open_time + MS_HOUR

    out, fill_ms = simulate(entry, sl_extreme, tp, side, c5_close_ms)
    if out not in ("win", "loss"): continue

    fill_close_ms = (fill_ms or c5_close_ms) + MS_HOUR

    f1 = check_f1(all5, side)
    f2 = check_f2_same(all5, side, fill_close_ms)
    r_val = 1.0 if out == "win" else -1.0

    # baseline
    s = stats["baseline"][side]
    s["w" if out == "win" else "l"] += 1
    s["tr"] += r_val

    if f1:
        s = stats["f1_only"][side]
        s["w" if out == "win" else "l"] += 1
        s["tr"] += r_val

    if f2:
        s = stats["f2_only"][side]
        s["w" if out == "win" else "l"] += 1
        s["tr"] += r_val

    if f1 or f2:
        s = stats["f1_or_f2"][side]
        s["w" if out == "win" else "l"] += 1
        s["tr"] += r_val

    if f1 and f2:
        s = stats["f1_and_f2"][side]
        s["w" if out == "win" else "l"] += 1
        s["tr"] += r_val


print(f"\n{'Strategy':<24} {'Side':<7} {'n':<5} {'WIN':<5} {'LOSS':<5} {'WR%':<8} {'ΣR':<8} {'R/tr':<8}")
print("-" * 80)
for name, sides in stats.items():
    for side in ("long", "short"):
        s = sides[side]
        n = s["w"] + s["l"]
        wr = s["w"] / n * 100 if n else 0
        rtr = s["tr"] / n if n else 0
        print(f"{name:<24} {side:<7} {n:<5} {s['w']:<5} {s['l']:<5} {wr:<7.2f}% {s['tr']:<+8.1f} {rtr:<+8.3f}")
    # total
    tw = sum(sides[s]["w"] for s in ("long", "short"))
    tl = sum(sides[s]["l"] for s in ("long", "short"))
    tr = sum(sides[s]["tr"] for s in ("long", "short"))
    n = tw + tl
    wr = tw / n * 100 if n else 0
    rtr = tr / n if n else 0
    print(f"{name:<24} {'TOTAL':<7} {n:<5} {tw:<5} {tl:<5} {wr:<7.2f}% {tr:<+8.1f} {rtr:<+8.3f}")
    print()
