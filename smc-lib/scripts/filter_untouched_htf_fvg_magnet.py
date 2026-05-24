"""Фильтр магнит: на C5 close должен существовать UNTOUCHED 4h/6h FVG
в TP-направлении (выше entry для LONG, ниже для SHORT).

Untouched = цена ещё ни разу не входила в зону FVG с момента формирования.
- Bullish FVG считается touched если low <= FVG.top (касание сверху)
- Bearish FVG считается touched если high >= FVG.bottom (касание снизу)

Применяется к 506 trades (F1 ∪ F2).
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
FVG_TFS = [("4h", 4 * MS_HOUR), ("6h", 6 * MS_HOUR)]


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

htf_candles = {name: aggregate(data, ms // 60_000) for name, ms in HTF_LIST}

htf_obs = {}; htf_rdrbs = {}
for name, cs in htf_candles.items():
    tf_ms = next(ms for n, ms in HTF_LIST if n == name)
    obs = []; rdrbs = []
    for i in range(len(cs) - 1):
        c, nxt = cs[i], cs[i + 1]
        if c.close < c.open and nxt.close > c.high:
            obs.append({"dir": "long", "open_ts": c.open_time, "end_ts": c.open_time + tf_ms})
        elif c.close > c.open and nxt.close < c.low:
            obs.append({"dir": "short", "open_ts": c.open_time, "end_ts": c.open_time + tf_ms})
    htf_obs[name] = obs
    for i in range(len(cs) - 2):
        r = detect_rdrb(cs[i], cs[i + 1], cs[i + 2])
        if r is None: continue
        rdrbs.append({"dir": r.direction, "c1_ts": cs[i].open_time,
                      "c3_end_ts": cs[i + 2].open_time + tf_ms,
                      "window_end_ts": cs[i].open_time + 3 * tf_ms})
    htf_rdrbs[name] = rdrbs

# FVGs с mitigation
fvg_pools = {}
for name, tf_ms in FVG_TFS:
    cs = htf_candles[name]
    fvgs = []
    for i in range(len(cs) - 2):
        c1, c3 = cs[i], cs[i + 2]
        if c1.high < c3.low:  # bullish
            f = {"dir": "bull", "formed_ts": c3.open_time + tf_ms,
                 "top": c3.low, "bottom": c1.high}
            f["mit_ts"] = None
            for j in range(i + 3, len(cs)):
                if cs[j].low <= f["top"]: f["mit_ts"] = cs[j].open_time; break
            fvgs.append(f)
        elif c1.low > c3.high:  # bearish
            f = {"dir": "bear", "formed_ts": c3.open_time + tf_ms,
                 "top": c1.low, "bottom": c3.high}
            f["mit_ts"] = None
            for j in range(i + 3, len(cs)):
                if cs[j].high >= f["bottom"]: f["mit_ts"] = cs[j].open_time; break
            fvgs.append(f)
    fvg_pools[name] = fvgs


def idx_at(ms):
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_1m[m] < ms: lo = m + 1
        else: hi = m
    return lo


def check_f1(pattern_candles, direction):
    for name, obs in htf_obs.items():
        for ob in obs:
            if ob["dir"] != direction: continue
            for c in pattern_candles:
                if ob["open_ts"] <= c.open_time < ob["end_ts"]: return True
    return False


def check_f2_same(pattern_candles, direction, fill_close_ms):
    htf_dir = "short" if direction == "long" else "long"
    for name, rdrbs in htf_rdrbs.items():
        for r in rdrbs:
            if r["dir"] != htf_dir: continue
            if r["c3_end_ts"] > fill_close_ms: continue
            for c in pattern_candles:
                if r["c1_ts"] <= c.open_time < r["window_end_ts"]: return True
    return False


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


def has_untouched_target_fvg(side, entry, c5_close_ms, max_distance_r=None, r_unit=None):
    """Есть ли untouched 4h/6h FVG в TP-направлении на C5 close?
    Для LONG: FVG.bottom > entry (целиком выше entry), не митигирован к C5 close.
    Для SHORT: FVG.top < entry (целиком ниже entry), не митигирован.
    """
    for name, fvgs in fvg_pools.items():
        for f in fvgs:
            if f["formed_ts"] > c5_close_ms: continue
            if f["mit_ts"] is not None and f["mit_ts"] <= c5_close_ms: continue
            if side == "long":
                if f["bottom"] <= entry: continue
                if max_distance_r is not None and r_unit:
                    if (f["bottom"] - entry) / r_unit > max_distance_r: continue
            else:
                if f["top"] >= entry: continue
                if max_distance_r is not None and r_unit:
                    if (entry - f["top"]) / r_unit > max_distance_r: continue
            return True
    return False


# Pattern detection + filter
patterns = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None: continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != ir.direction: continue
    patterns.append((ir, c5))


filtered_506 = []
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
    out, fill_ms = simulate(side, entry, sl, tp, c5_close_ms)
    if out not in ("win", "loss"): continue
    fill_close_ms = (fill_ms or c5_close_ms) + MS_HOUR
    if not (check_f1(all5, side) or check_f2_same(all5, side, fill_close_ms)): continue
    filtered_506.append({"side": side, "entry": entry, "sl": sl, "tp": tp, "r_unit": r_unit,
                         "c5_close_ms": c5_close_ms, "fill_ms": fill_ms, "outcome": out})

print(f"F1 ∪ F2: {len(filtered_506)} trades\n")


def report(name, items):
    n = len(items)
    if n == 0: print(f"  {name:<60} n=0"); return
    w = sum(1 for x in items if x["outcome"] == "win")
    r = w - (n - w)
    print(f"  {name:<60} n={n:<4} W={w:<4} L={n-w:<4} WR={w/n*100:5.2f}%  ΣR={r:+5d}  R/tr={r/n:+.3f}")


print("=== Фильтр untouched 4h/6h FVG (любого направления) в TP-направлении ===\n")

has_magnet = [t for t in filtered_506 if has_untouched_target_fvg(t["side"], t["entry"], t["c5_close_ms"])]
no_magnet = [t for t in filtered_506 if not has_untouched_target_fvg(t["side"], t["entry"], t["c5_close_ms"])]

report("F1 ∪ F2 (baseline)", filtered_506)
report("WITH untouched HTF FVG magnet (любое расстояние)", has_magnet)
report("WITHOUT untouched HTF FVG magnet", no_magnet)

print()
print("=== Distance constraint (untouched FVG в ≤ X R от entry) ===\n")
for max_d in (1.0, 2.0, 3.0, 5.0):
    sub = [t for t in filtered_506
           if has_untouched_target_fvg(t["side"], t["entry"], t["c5_close_ms"], max_distance_r=max_d, r_unit=t["r_unit"])]
    report(f"WITH untouched HTF FVG ≤ {max_d}R над entry", sub)

print("\n=== TP sweep на WITH-magnet (any distance) ===")
for rr in (1.0, 1.4, 2.0, 2.5, 2.9):
    n_w = 0; n_l = 0; total_r = 0.0
    for t in has_magnet:
        new_tp = t["entry"] + rr * t["r_unit"] if t["side"] == "long" else t["entry"] - rr * t["r_unit"]
        out2, _ = simulate(t["side"], t["entry"], t["sl"], new_tp, t["c5_close_ms"])
        if out2 == "win": n_w += 1; total_r += rr
        elif out2 == "loss": n_l += 1; total_r -= 1
    n = n_w + n_l
    print(f"  RR={rr}  n={n}  WR={n_w/n*100:5.2f}%  ΣR={total_r:+.1f}  R/tr={total_r/n:+.3f}")
