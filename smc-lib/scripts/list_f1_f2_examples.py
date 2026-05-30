"""Перечисляет 3 свежих примера сделок с фильтром F1 и 3 с F2."""
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
MSK = timezone(timedelta(hours=3))
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


def fmt(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%Y-%m-%d %H:%M')


print("Loading..."); data = load_1m()
candles_1h = aggregate(data, 60)
ts_1m = [r[0] for r in data]

htf_candles = {name: aggregate(data, ms // 60_000) for name, ms in HTF_LIST}

# HTF OBs (с деталями для отчёта)
htf_obs = {}
for name, cs in htf_candles.items():
    tf_ms = next(ms for n, ms in HTF_LIST if n == name)
    obs = []
    for i in range(len(cs) - 1):
        c, nxt = cs[i], cs[i + 1]
        if c.close < c.open and nxt.close > c.high:
            obs.append({"dir": "long", "open_ts": c.open_time, "end_ts": c.open_time + tf_ms,
                        "high": c.high, "low": c.low})
        elif c.close > c.open and nxt.close < c.low:
            obs.append({"dir": "short", "open_ts": c.open_time, "end_ts": c.open_time + tf_ms,
                        "high": c.high, "low": c.low})
    htf_obs[name] = obs

# HTF RDRBs
htf_rdrbs = {}
for name, cs in htf_candles.items():
    tf_ms = next(ms for n, ms in HTF_LIST if n == name)
    rdrbs = []
    for i in range(len(cs) - 2):
        r = detect_rdrb(cs[i], cs[i + 1], cs[i + 2])
        if r is None: continue
        rdrbs.append({"dir": r.direction, "c1_ts": cs[i].open_time,
                      "c3_end_ts": cs[i + 2].open_time + tf_ms,
                      "window_end_ts": cs[i].open_time + 3 * tf_ms,
                      "block": r.block, "variant": r.variant})
    htf_rdrbs[name] = rdrbs


def idx_at(ms):
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_1m[m] < ms: lo = m + 1
        else: hi = m
    return lo


def find_f1_match(pattern_candles, direction):
    """Возвращает (TF_name, OB_open_ts, OB.high, OB.low) или None."""
    for name, obs in htf_obs.items():
        for ob in obs:
            if ob["dir"] != direction: continue
            for c in pattern_candles:
                if ob["open_ts"] <= c.open_time < ob["end_ts"]:
                    return (name, ob["open_ts"], ob["high"], ob["low"])
    return None


def find_f2_match(pattern_candles, direction, fill_close_ms):
    htf_dir = "short" if direction == "long" else "long"
    for name, rdrbs in htf_rdrbs.items():
        for r in rdrbs:
            if r["dir"] != htf_dir: continue
            if r["c3_end_ts"] > fill_close_ms: continue
            for c in pattern_candles:
                if r["c1_ts"] <= c.open_time < r["window_end_ts"]:
                    return (name, r["c1_ts"], r["block"], r["variant"], r["dir"])
    return None


def simulate(side, entry, sl, tp, start_ms):
    sk = idx_at(start_ms); ek = min(sk + MAX_HOLD_MIN, len(data))
    in_trade = False; fill_ms = None; exit_ms = None
    for k in range(sk, ek):
        ts, _, h_, l_, _, _ = data[k]
        if not in_trade:
            if side == "long":
                if l_ <= entry:
                    in_trade = True; fill_ms = ts
                    if l_ <= sl: return "loss", fill_ms, ts
                    if h_ >= tp: return "win", fill_ms, ts
            else:
                if h_ >= entry:
                    in_trade = True; fill_ms = ts
                    if h_ >= sl: return "loss", fill_ms, ts
                    if l_ <= tp: return "win", fill_ms, ts
        else:
            if side == "long":
                if l_ <= sl: return "loss", fill_ms, ts
                if h_ >= tp: return "win", fill_ms, ts
            else:
                if h_ >= sl: return "loss", fill_ms, ts
                if l_ <= tp: return "win", fill_ms, ts
    return "no_fill", fill_ms, None


# Detect patterns + collect filtered with details
patterns = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None: continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != ir.direction: continue
    patterns.append((ir, c5))

f1_examples = []  # passes F1 (may or may not pass F2)
f2_examples = []
for ir, c5 in patterns:
    side = ir.direction
    block_b, block_t = ir.rdrb.block
    entry = (block_b + block_t) / 2
    all5 = [ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]
    sl = min(c.low for c in all5) if side == "long" else max(c.high for c in all5)
    r_unit = abs(entry - sl)
    if r_unit <= 0: continue
    tp = entry + r_unit if side == "long" else entry - r_unit
    c5_close_ms = c5.open_time + MS_HOUR
    out, fill_ms, exit_ms = simulate(side, entry, sl, tp, c5_close_ms)
    if out not in ("win", "loss"): continue

    fill_close_ms = (fill_ms or c5_close_ms) + MS_HOUR
    f1m = find_f1_match(all5, side)
    f2m = find_f2_match(all5, side, fill_close_ms)

    record = {
        "ir": ir, "c5": c5, "side": side,
        "entry": entry, "sl": sl, "tp": tp, "r_unit": r_unit,
        "outcome": out, "fill_ms": fill_ms, "exit_ms": exit_ms,
        "f1": f1m, "f2": f2m,
    }
    if f1m: f1_examples.append(record)
    if f2m: f2_examples.append(record)

# Сортируем по дате (новейшие первые) и берём по 3
f1_latest = sorted(f1_examples, key=lambda x: x["ir"].rdrb.c1.open_time, reverse=True)[:3]
f2_latest = sorted(f2_examples, key=lambda x: x["ir"].rdrb.c1.open_time, reverse=True)[:3]


def print_record(idx, r, filter_name):
    ir = r["ir"]; c5 = r["c5"]
    print(f"\n--- [{idx}] {filter_name}: {r['side'].upper()} {fmt(ir.rdrb.c1.open_time)} MSK ---")
    for label, c in [("C1", ir.rdrb.c1), ("C2", ir.rdrb.c2), ("C3", ir.rdrb.c3),
                      ("C4", ir.c4), ("C5", c5)]:
        d_ = "BULL" if c.close > c.open else ("BEAR" if c.close < c.open else "DOJI")
        print(f"  {label} {fmt(c.open_time):<17}: O={c.open:.2f} H={c.high:.2f} L={c.low:.2f} C={c.close:.2f} {d_}")
    print(f"  Pattern: Entry={r['entry']:.2f}, SL={r['sl']:.2f}, TP={r['tp']:.2f}, R_unit={r['r_unit']:.2f}")
    print(f"  Outcome: {r['outcome'].upper()}, Fill={fmt(r['fill_ms'])} MSK, Exit={fmt(r['exit_ms'])} MSK")
    if r["f1"]:
        name, ots, hi, lo = r["f1"]
        print(f"  F1 match: HTF {name} OB at {fmt(ots)} MSK, OB high={hi:.2f}, low={lo:.2f}")
    if r["f2"]:
        name, ots, block, variant, dir = r["f2"]
        print(f"  F2 match: HTF {name} RDRB ({variant}, dir={dir}) at {fmt(ots)} MSK, block={block}")


print("\n=== 3 свежих примера F1 (HTF Order Block) ===")
for i, r in enumerate(f1_latest, 1):
    print_record(i, r, "F1")

print("\n\n=== 3 свежих примера F2 (HTF RDRB) ===")
for i, r in enumerate(f2_latest, 1):
    print_record(i, r, "F2")
