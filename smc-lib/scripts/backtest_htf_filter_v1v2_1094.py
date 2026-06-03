"""HTF фильтры (F1 = HTF OB overlap, F2_same = HTF RDRB membership) на V1+V2 = 1094.

Entry/SL = Combined D, TP = RR=1.0 (baseline из ночной сессии).
HTF: {4h, 6h, 8h, 12h, 1D}.

F1 (same-dir HTF OB overlap):
  Bullish OB: HTF candle bearish AND next HTF candle close > candle.high
  Bearish OB: HTF candle bullish AND next HTF candle close < candle.low
  Pass: хотя бы одна 1h-свеча паттерна (V1: C1..C5; V2: C1..C6) попадает в [OB.open, OB.open + TF)
  и OB.direction == 1h pattern direction.

F2_same (HTF RDRB membership, same effective direction):
  HTF RDRB: smc-lib detect_rdrb на 3 свечах HTF.
  Pass: хотя бы одна 1h-свеча паттерна попадает в [c1_HTF.open, c1_HTF.open + 3*TF)
  AND HTF RDRB c3 закрылся к моменту fill_close (fill+1h)
  AND HTF RDRB direction (smc-lib) совпадает с эффективным direction.
  Mapping: 1h i-RDRB LONG (bullish reversal) → HTF SHORT-shape RDRB (см. memory F2 определение).
"""
from __future__ import annotations

import csv
import pathlib
import sys
import time
from datetime import datetime, timezone

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
            rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    return rows


def aggregate(d, tf_min):
    bucket = tf_min * 60_000
    out = []; cb = None; o = h = l = c = 0
    for ts, oo, hh, ll, cc in d:
        b = ts - (ts % bucket)
        if b != cb:
            if cb is not None: out.append(Candle(open=o, high=h, low=l, close=c, open_time=cb))
            cb = b; o, h, l, c = oo, hh, ll, cc
        else:
            h = max(h, hh); l = min(l, ll); c = cc
    if cb is not None: out.append(Candle(open=o, high=h, low=l, close=c, open_time=cb))
    return out


print("Loading 1m..."); t0 = time.time()
data = load_1m()
print(f"  {len(data):,} 1m rows ({time.time()-t0:.1f}s)")

candles_1h = aggregate(data, 60)
ts_1m = [r[0] for r in data]

last_ts = data[-1][0]
window_start_ms = last_ts - 6 * 365 * 24 * 3600 * 1000
candles_1h_w = [c for c in candles_1h if c.open_time >= window_start_ms]
print(f"  6y 1h: {len(candles_1h_w):,} bars")

# HTF aggregates
htf_candles = {}
for name, ms in HTF_LIST:
    tf_min = ms // 60_000
    htf_candles[name] = aggregate(data, tf_min)
    print(f"  {name}: {len(htf_candles[name]):,}")

# HTF OBs (same as backtest_f1_f2_filter.py)
htf_obs = {}
for name, cs in htf_candles.items():
    tf_ms = next(ms for n, ms in HTF_LIST if n == name)
    obs = []
    for i in range(len(cs) - 1):
        c, nxt = cs[i], cs[i + 1]
        if c.close < c.open and nxt.close > c.high:
            obs.append({"dir": "long", "open_ts": c.open_time, "end_ts": c.open_time + tf_ms})
        elif c.close > c.open and nxt.close < c.low:
            obs.append({"dir": "short", "open_ts": c.open_time, "end_ts": c.open_time + tf_ms})
    htf_obs[name] = obs
print(f"\nHTF OBs total: {sum(len(v) for v in htf_obs.values()):,}")

# HTF RDRBs
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
            "c3_end_ts": cs[i + 2].open_time + tf_ms,
            "window_end_ts": cs[i].open_time + 3 * tf_ms,
        })
    htf_rdrbs[name] = rdrbs
print(f"HTF RDRBs total: {sum(len(v) for v in htf_rdrbs.values()):,}\n")


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
        ts, _, h_, l_, _ = data[k]
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


def check_f1(pattern_candles, direction):
    for name, obs in htf_obs.items():
        for ob in obs:
            if ob["dir"] != direction: continue
            for c in pattern_candles:
                if ob["open_ts"] <= c.open_time < ob["end_ts"]:
                    return True
    return False


def check_f2_same(pattern_candles, direction, fill_close_ms):
    """1h LONG → HTF SHORT-shape RDRB (memory convention)."""
    htf_dir = "short" if direction == "long" else "long"
    for name, rdrbs in htf_rdrbs.items():
        for r in rdrbs:
            if r["dir"] != htf_dir: continue
            if r["c3_end_ts"] > fill_close_ms: continue
            for c in pattern_candles:
                if r["c1_ts"] <= c.open_time < r["window_end_ts"]:
                    return True
    return False


# === Detect V1 + V2 setups ===
setups = []
for i in range(len(candles_1h_w) - 5):
    c1, c2, c3, c4, c5, c6 = candles_1h_w[i:i + 6]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None: continue

    fvg_v1 = detect_fvg(c3, c4, c5)
    if fvg_v1 and fvg_v1.direction == ir.direction:
        pl = min(c.low for c in (c1, c2, c3, c4, c5))
        ph = max(c.high for c in (c1, c2, c3, c4, c5))
        setups.append({"ir": ir, "variant": "V1", "pl": pl, "ph": ph,
                       "start_ms": c5.open_time + MS_HOUR,
                       "pattern_candles": [c1, c2, c3, c4, c5]})

    fvg_v2 = detect_fvg(c4, c5, c6)
    if fvg_v2 and fvg_v2.direction == ir.direction:
        pl = min(c.low for c in (c1, c2, c3, c4, c5, c6))
        ph = max(c.high for c in (c1, c2, c3, c4, c5, c6))
        setups.append({"ir": ir, "variant": "V2", "pl": pl, "ph": ph,
                       "start_ms": c6.open_time + MS_HOUR,
                       "pattern_candles": [c1, c2, c3, c4, c5, c6]})
print(f"Detected V1+V2 setups: {len(setups):,}")


# === Run backtest ===
results = []   # per-setup: dict
for s in setups:
    ir, pl, ph = s["ir"], s["pl"], s["ph"]
    side = ir.direction
    bb, bt = ir.rdrb.block
    if side == "long":
        entry = bt
        sl = pl + 0.1 * (bb - pl)
        if entry <= sl: continue
        r_unit = entry - sl
        tp = entry + r_unit
    else:
        entry = bb
        sl = ph - 0.1 * (ph - bt)
        if entry >= sl: continue
        r_unit = sl - entry
        tp = entry - r_unit

    out, fill_ms = simulate(side, entry, sl, tp, s["start_ms"])
    fill_close = (fill_ms or s["start_ms"]) + MS_HOUR

    f1 = check_f1(s["pattern_candles"], side)
    f2 = check_f2_same(s["pattern_candles"], side, fill_close)

    results.append({"side": side, "variant": s["variant"], "out": out,
                    "f1": f1, "f2": f2})

print(f"Simulated: {len(results):,}\n")


# === Stats ===
def stats(rows):
    n_l = sum(1 for r in rows if r["out"] == "loss")
    n_w = sum(1 for r in rows if r["out"] == "win")
    n_nf = sum(1 for r in rows if r["out"] == "no_fill")
    n = n_w + n_l
    wr = n_w / n * 100 if n else 0
    sr = n_w - n_l
    rtr = sr / n if n else 0
    return n, n_w, n_l, n_nf, wr, sr, rtr


def print_bucket(name, rows):
    n, w, l, nf, wr, sr, rtr = stats(rows)
    n_long = sum(1 for r in rows if r["side"] == "long")
    n_short = sum(1 for r in rows if r["side"] == "short")
    _, w_l, l_l, _, wr_l, sr_l, _ = stats([r for r in rows if r["side"] == "long"])
    _, w_s, l_s, _, wr_s, sr_s, _ = stats([r for r in rows if r["side"] == "short"])
    print(f"  {name:<32} n={len(rows):>4}  closed={n:>4}  NF={nf:>3}  "
          f"WR={wr:>5.2f}%  ΣR={sr:>+6.1f}  R/tr={rtr:+.3f}")
    print(f"    LONG  n={n_long:>4}  W={w_l:>3}/L={l_l:>3}  WR={wr_l:>5.2f}%  ΣR={sr_l:+5.1f}")
    print(f"    SHORT n={n_short:>4}  W={w_s:>3}/L={l_s:>3}  WR={wr_s:>5.2f}%  ΣR={sr_s:+5.1f}")


print("=" * 78)
print(" HTF filters on V1+V2 = 1094 (Combined D, RR=1.0)")
print("=" * 78)
print_bucket("Baseline (all)", results)

print()
print_bucket("F1 (HTF OB overlap)", [r for r in results if r["f1"]])
print_bucket("¬F1 (no HTF OB overlap)", [r for r in results if not r["f1"]])

print()
print_bucket("F2 (HTF RDRB member)", [r for r in results if r["f2"]])
print_bucket("¬F2", [r for r in results if not r["f2"]])

print()
print_bucket("F1 ∪ F2", [r for r in results if r["f1"] or r["f2"]])
print_bucket("F1 ∩ F2", [r for r in results if r["f1"] and r["f2"]])
print_bucket("¬(F1 ∪ F2)", [r for r in results if not (r["f1"] or r["f2"])])

# По variant
print()
for variant in ("V1", "V2"):
    print(f"---- {variant} only ----")
    rows = [r for r in results if r["variant"] == variant]
    print_bucket(f"{variant} baseline", rows)
    print_bucket(f"{variant} F1∪F2", [r for r in rows if r["f1"] or r["f2"]])

# Save per-setup CSV
OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts/htf_f1f2_v1v2_1094.csv"
with OUT.open('w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['side', 'variant', 'out', 'f1', 'f2'])
    for r in results:
        w.writerow([r['side'], r['variant'], r['out'], int(r['f1']), int(r['f2'])])
print(f"\nSaved per-setup → {OUT}")
print(f"Total: {time.time()-t0:.1f}s")
