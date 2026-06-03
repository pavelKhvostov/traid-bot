"""Graal search v3 — расширенный набор фичей + brute-force grid.

Новые фичи (anti-look-ahead):
  pos_5d   — pattern.low(high) в range последних 5 ПОЛНОСТЬЮ ЗАКРЫТЫХ daily candles
  pos_20d  — то же для 20 daily
  ema50_1h — distance entry to EMA50(1h) в R-units (signed: above/below)
  ema200_1h — то же для EMA200(1h)
  ema_trend_1d — EMA50_1d > EMA200_1d → uptrend
  atr_pct  — percentile-rank ATR(20,1h) на rolling 200 1h bars
  hour_msk — hour of c1 in MSK
  year     — год c1
  momentum_12h — кол-во consecutive same-color 12h baров перед c1
  momentum_4h  — то же для 4h

Brute-force: для каждой пары (feature_a, threshold_a, feature_b, threshold_b)
найти лучший subset с n_closed >= 80 и WR >= 65%.
"""
from __future__ import annotations

import csv
import pathlib
import sys
import time
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.i_rdrb.code import detect_i_rdrb
from elements.fvg.code import detect_fvg
from elements.fractal.code import detect_fractal

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MS_HOUR = 3600_000
MAX_HOLD_MIN = 30 * 24 * 60
MSK = timezone(timedelta(hours=3))

CASCADE_TFS = [("4h", 4 * MS_HOUR), ("12h", 12 * MS_HOUR), ("1D", 24 * MS_HOUR), ("W", 7 * 24 * MS_HOUR)]

t0 = time.time()


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    return rows


def aggregate_epoch(d, tf_min):
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


def aggregate_weekly_monday(d):
    week_ms = 7 * 24 * 3600 * 1000
    mon_anchor = 1483315200000
    out = []; cb = None; o = h = l = c = 0
    for ts, oo, hh, ll, cc in d:
        offset = (ts - mon_anchor) % week_ms
        bucket_open = ts - offset
        if bucket_open != cb:
            if cb is not None: out.append(Candle(open=o, high=h, low=l, close=c, open_time=cb))
            cb = bucket_open; o, h, l, c = oo, hh, ll, cc
        else:
            h = max(h, hh); l = min(l, ll); c = cc
    if cb is not None: out.append(Candle(open=o, high=h, low=l, close=c, open_time=cb))
    return out


print("Loading 1m...")
data = load_1m()
print(f"  {len(data):,} rows ({time.time()-t0:.1f}s)")

ts_arr = np.array([r[0] for r in data], dtype=np.int64)
lo_arr = np.array([r[3] for r in data], dtype=np.float64)
hi_arr = np.array([r[2] for r in data], dtype=np.float64)

candles_1h = aggregate_epoch(data, 60)
last_ts = data[-1][0]
window_start_ms = last_ts - 6 * 365 * 24 * 3600 * 1000
candles_1h_w = [c for c in candles_1h if c.open_time >= window_start_ms]

htf_candles = {"4h": aggregate_epoch(data, 240),
               "12h": aggregate_epoch(data, 720),
               "1D": aggregate_epoch(data, 1440),
               "W": aggregate_weekly_monday(data)}

# === 1h arrays + EMA + ATR ===
hi1h = np.array([c.high for c in candles_1h], dtype=np.float64)
lo1h = np.array([c.low for c in candles_1h], dtype=np.float64)
cl1h = np.array([c.close for c in candles_1h], dtype=np.float64)
ts1h = np.array([c.open_time for c in candles_1h], dtype=np.int64)
prev_cl = np.concatenate([[cl1h[0]], cl1h[:-1]])
tr = np.maximum.reduce([hi1h - lo1h, np.abs(hi1h - prev_cl), np.abs(lo1h - prev_cl)])
# rolling ATR(20)
atr20 = np.zeros_like(tr)
for i in range(len(tr)):
    if i < 19: atr20[i] = tr[:i+1].mean()
    else: atr20[i] = tr[i-19:i+1].mean()

# EMA
def ema(arr, n):
    a = 2 / (n + 1)
    out = np.zeros_like(arr)
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = a * arr[i] + (1 - a) * out[i-1]
    return out

ema50_1h = ema(cl1h, 50)
ema200_1h = ema(cl1h, 200)

# ATR percentile (rolling 200 bars)
atr_pct = np.zeros_like(atr20)
for i in range(len(atr20)):
    lo_i = max(0, i - 199)
    window = atr20[lo_i:i+1]
    rank = (window < atr20[i]).sum() / len(window) if len(window) > 1 else 0.5
    atr_pct[i] = rank

# EMA on daily for trend regime
cl_d = np.array([c.close for c in htf_candles["1D"]], dtype=np.float64)
ema50_d = ema(cl_d, 50) if len(cl_d) >= 1 else cl_d
ema200_d = ema(cl_d, 200) if len(cl_d) >= 1 else cl_d

print(f"  1h arrays + EMA + ATR ready ({time.time()-t0:.1f}s)")


# === Daily array for pos_Nd ===
ts_d = np.array([c.open_time for c in htf_candles["1D"]], dtype=np.int64)
hi_d = np.array([c.high for c in htf_candles["1D"]], dtype=np.float64)
lo_d = np.array([c.low for c in htf_candles["1D"]], dtype=np.float64)


def idx_at(ms):
    return int(np.searchsorted(ts_arr, ms, side='left'))


def idx_1h_at(ms):
    return int(np.searchsorted(ts1h, ms, side='left'))


def idx_d_closed_at(ms):
    """Index of LAST 1D candle that closed by ms (i.e. open + 24h <= ms)."""
    # binary search for largest i with ts_d[i] + 24h <= ms
    n = len(ts_d)
    lo, hi = 0, n
    while lo < hi:
        m = (lo + hi) // 2
        if ts_d[m] + 24 * MS_HOUR <= ms:
            lo = m + 1
        else:
            hi = m
    return lo - 1  # last valid index


def simulate(side, entry, sl, tp, start_ms):
    sk = idx_at(start_ms); ek = min(sk + MAX_HOLD_MIN, len(data))
    in_trade = False
    for k in range(sk, ek):
        h_ = hi_arr[k]; l_ = lo_arr[k]
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


# === Fractals для cascade ===
htf_fracs = {}
for name, tf_ms in CASCADE_TFS:
    cs = htf_candles[name]
    fr = []
    for i in range(2, len(cs) - 2):
        f = detect_fractal(cs[i-2:i+3], n=2)
        if f is None: continue
        fr.append({"dir": f.direction, "level": f.level,
                   "confirm_ts": cs[i].open_time + 3 * tf_ms})
    htf_fracs[name] = fr


# === Detect setups ===
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
                       "c1_open": c1.open_time, "c5_open": c5.open_time,
                       "start_ms": c5.open_time + MS_HOUR})
    fvg_v2 = detect_fvg(c4, c5, c6)
    if fvg_v2 and fvg_v2.direction == ir.direction:
        pl = min(c.low for c in (c1, c2, c3, c4, c5, c6))
        ph = max(c.high for c in (c1, c2, c3, c4, c5, c6))
        setups.append({"ir": ir, "variant": "V2", "pl": pl, "ph": ph,
                       "c1_open": c1.open_time, "c5_open": c5.open_time,
                       "start_ms": c6.open_time + MS_HOUR})
print(f"Detected: {len(setups)} setups  ({time.time()-t0:.1f}s)")


# === Features ===
results = []
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

    start_ms = s["start_ms"]
    c1_open = s["c1_open"]
    out = simulate(side, entry, sl, tp, start_ms)

    # === Position in N-day range (closed-only) ===
    di = idx_d_closed_at(c1_open)
    pos_5d = pos_20d = 0.5
    if di >= 4:
        rng_lo = lo_d[max(0, di-4):di+1].min()
        rng_hi = hi_d[max(0, di-4):di+1].max()
        if rng_hi > rng_lo:
            pos_5d = (pl - rng_lo) / (rng_hi - rng_lo) if side == "long" else (ph - rng_lo) / (rng_hi - rng_lo)
    if di >= 19:
        rng_lo = lo_d[di-19:di+1].min()
        rng_hi = hi_d[di-19:di+1].max()
        if rng_hi > rng_lo:
            pos_20d = (pl - rng_lo) / (rng_hi - rng_lo) if side == "long" else (ph - rng_lo) / (rng_hi - rng_lo)

    # === EMA distances (signed, в R) ===
    # use last fully closed 1h before c1_open
    i1 = idx_1h_at(c1_open) - 1
    if i1 < 0: i1 = 0
    cl_now = cl1h[i1]
    ema50_now = ema50_1h[i1]
    ema200_now = ema200_1h[i1]
    ema50_dist = (cl_now - ema50_now) / r_unit  # positive = price above EMA
    ema200_dist = (cl_now - ema200_now) / r_unit

    # ema_trend_d: EMA50_d > EMA200_d?
    di_close = idx_d_closed_at(c1_open)
    if di_close > 0 and di_close < len(ema50_d):
        ema_trend_d = 1 if ema50_d[di_close] > ema200_d[di_close] else -1
    else:
        ema_trend_d = 0

    # === ATR percentile and r_atr ===
    atr_now = atr20[i1] if atr20[i1] > 0 else 1e-9
    r_atr = r_unit / atr_now
    atr_p = atr_pct[i1]

    # === Cascade (fractal-based, как раньше) ===
    cascade = 0
    for name, _ in CASCADE_TFS:
        confirmed = [f for f in htf_fracs[name] if f["confirm_ts"] <= c1_open]
        fhs = [f for f in confirmed if f["dir"] == "high"]
        fls = [f for f in confirmed if f["dir"] == "low"]
        if len(fhs) < 2 or len(fls) < 2: continue
        up = (fhs[-1]["level"] > fhs[-2]["level"]) and (fls[-1]["level"] > fls[-2]["level"])
        down = (fhs[-1]["level"] < fhs[-2]["level"]) and (fls[-1]["level"] < fls[-2]["level"])
        match = (side == "long" and up) or (side == "short" and down)
        if match: cascade += 1

    # === HTF momentum (consecutive same-color before c1) ===
    def momentum(cs, cur_ts):
        cnt = 0
        last_dir = None
        for c in reversed(cs):
            if c.open_time >= cur_ts: continue
            d = "bull" if c.close > c.open else ("bear" if c.close < c.open else None)
            if d is None: break
            if last_dir is None:
                last_dir = d
                cnt = 1
            elif d == last_dir:
                cnt += 1
            else:
                break
        # signed by direction
        if last_dir == "bull": return cnt
        elif last_dir == "bear": return -cnt
        else: return 0

    mom_4h = momentum(htf_candles["4h"], c1_open)
    mom_12h = momentum(htf_candles["12h"], c1_open)

    # === Time-of-day in MSK + year ===
    dt = datetime.fromtimestamp(c1_open / 1000, tz=timezone.utc).astimezone(MSK)
    hour_msk = dt.hour
    year = dt.year
    weekday = dt.weekday()  # 0=Mon

    results.append({
        "side": side, "variant": s["variant"], "out": out,
        "pos_5d": pos_5d, "pos_20d": pos_20d,
        "ema50": ema50_dist, "ema200": ema200_dist, "ema_d": ema_trend_d,
        "r_atr": r_atr, "atr_p": atr_p,
        "cascade": cascade,
        "mom_4h": mom_4h, "mom_12h": mom_12h,
        "hour": hour_msk, "weekday": weekday, "year": year,
    })

print(f"Features done ({time.time()-t0:.1f}s)")


def stat(rows):
    w_ = sum(1 for r in rows if r["out"] == "win")
    l_ = sum(1 for r in rows if r["out"] == "loss")
    n = w_ + l_
    wr = w_ / n * 100 if n else 0
    sr = w_ - l_
    return n, wr, sr


def bk(name, rows, indent=0):
    n, wr, sr = stat(rows)
    rtr = sr / n if n else 0
    pre = " " * indent
    print(f"{pre}{name:<48} n_set={len(rows):>4}  cl={n:>4}  WR={wr:>5.2f}%  ΣR={sr:>+6.1f}  R/tr={rtr:+.3f}")


def bk_ls(name, rows):
    bk(name, rows)
    for side in ("long", "short"):
        sub = [r for r in rows if r["side"] == side]
        if sub: bk(side.upper(), sub, indent=4)


print("\n" + "=" * 100)
print(" BASELINE")
print("=" * 100)
bk_ls("BASELINE", results)


def bin_cont(feat, bins):
    print(f"\n--- {feat} ---")
    for lo, hi in bins:
        sub = [r for r in results if lo <= r[feat] < hi]
        bk(f"[{lo:.2f}, {hi:.2f})", sub)
        for side in ("long", "short"):
            sub2 = [r for r in sub if r["side"] == side]
            if sub2: bk(side.upper(), sub2, indent=6)


print("\n" + "=" * 100)
print(" Continuous bins")
print("=" * 100)
bin_cont("pos_5d", [(0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)])
bin_cont("pos_20d", [(0, 0.1), (0.1, 0.3), (0.3, 0.7), (0.7, 0.9), (0.9, 1.01)])
bin_cont("ema50", [(-1e9, -1), (-1, 0), (0, 1), (1, 3), (3, 1e9)])
bin_cont("ema200", [(-1e9, -3), (-3, -1), (-1, 1), (1, 3), (3, 1e9)])
bin_cont("r_atr", [(0, 0.55), (0.55, 0.85), (0.85, 1.05), (1.05, 1e9)])
bin_cont("atr_p", [(0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.01)])


print("\n" + "=" * 100)
print(" Categorical / signed")
print("=" * 100)
for feat in ("ema_d",):
    for v in sorted(set(r[feat] for r in results)):
        bk_ls(f"{feat}={v}", [r for r in results if r[feat] == v])

# Momentum bins
print("\n--- mom_4h ---")
for lo, hi in [(-1e9, -3), (-3, -1), (-1, 1), (1, 3), (3, 1e9)]:
    sub = [r for r in results if lo <= r["mom_4h"] < hi]
    bk_ls(f"[{lo}, {hi})", sub)

print("\n--- mom_12h ---")
for lo, hi in [(-1e9, -2), (-2, -1), (-1, 1), (1, 2), (2, 1e9)]:
    sub = [r for r in results if lo <= r["mom_12h"] < hi]
    bk_ls(f"[{lo}, {hi})", sub)

# Hour and year
print("\n--- by hour MSK ---")
for h in range(24):
    sub = [r for r in results if r["hour"] == h]
    n, wr, sr = stat(sub)
    if n < 20: continue
    print(f"  h={h:>2}  n_set={len(sub):>4}  cl={n:>4}  WR={wr:>5.2f}%  ΣR={sr:>+5.1f}")

print("\n--- by year ---")
for y in sorted(set(r["year"] for r in results)):
    sub = [r for r in results if r["year"] == y]
    bk(f"{y}", sub)
    for side in ("long", "short"):
        bk(side.upper(), [r for r in sub if r["side"] == side], indent=6)

print("\n--- by weekday ---")
for wd in range(7):
    sub = [r for r in results if r["weekday"] == wd]
    bk(["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][wd], sub)


# === Brute-force pairs ===
print("\n" + "=" * 100)
print(" Brute-force pair search (n_closed >= 80, WR >= 64%)")
print("=" * 100)

# Define candidate filters as predicates with names
candidates = []
for thr in [0.10, 0.20, 0.30]:
    candidates.append((f"pos_5d<{thr:.2f} (LONG) | pos_5d>{1-thr:.2f} (SHORT)",
                       lambda r, t=thr: (r["side"] == "long" and r["pos_5d"] < t) or (r["side"] == "short" and r["pos_5d"] > 1 - t)))
for thr in [0.10, 0.20, 0.30]:
    candidates.append((f"pos_20d<{thr:.2f}(L) | >{1-thr:.2f}(S)",
                       lambda r, t=thr: (r["side"] == "long" and r["pos_20d"] < t) or (r["side"] == "short" and r["pos_20d"] > 1 - t)))
for c in [0, 1, 2, 3, 4]:
    candidates.append((f"cascade=={c}", lambda r, c=c: r["cascade"] == c))
    candidates.append((f"cascade>={c}", lambda r, c=c: r["cascade"] >= c))
candidates.append(("ema_d=1 LONG | ema_d=-1 SHORT (trend align)",
                   lambda r: (r["side"] == "long" and r["ema_d"] == 1) or (r["side"] == "short" and r["ema_d"] == -1)))
candidates.append(("ema50>0 LONG | ema50<0 SHORT (above/below EMA)",
                   lambda r: (r["side"] == "long" and r["ema50"] > 0) or (r["side"] == "short" and r["ema50"] < 0)))
candidates.append(("ema50<0 LONG | ema50>0 SHORT (counter-trend bounce)",
                   lambda r: (r["side"] == "long" and r["ema50"] < 0) or (r["side"] == "short" and r["ema50"] > 0)))
for lo, hi in [(0.55, 0.85), (0.55, 1.05), (0.7, 1.05), (0.85, 1.3)]:
    candidates.append((f"r_atr in [{lo:.2f},{hi:.2f}]",
                       lambda r, l=lo, h=hi: l <= r["r_atr"] <= h))
for lo, hi in [(0, 0.25), (0.25, 0.75), (0.5, 1.01)]:
    candidates.append((f"atr_p in [{lo:.2f},{hi:.2f}]",
                       lambda r, l=lo, h=hi: l <= r["atr_p"] <= h))
candidates.append(("mom_4h same-dir>=2 LONG | <=-2 SHORT",
                   lambda r: (r["side"] == "long" and r["mom_4h"] >= 2) or (r["side"] == "short" and r["mom_4h"] <= -2)))
candidates.append(("mom_4h opp-dir<=-2 LONG | >=2 SHORT (counter)",
                   lambda r: (r["side"] == "long" and r["mom_4h"] <= -2) or (r["side"] == "short" and r["mom_4h"] >= 2)))
candidates.append(("hour MSK in [3..10] (Asia/Eu open)",
                   lambda r: 3 <= r["hour"] <= 10))
candidates.append(("hour MSK in [13..21] (US session)",
                   lambda r: 13 <= r["hour"] <= 21))

# Singles
single_results = []
for name, pred in candidates:
    sub = [r for r in results if pred(r)]
    n, wr, sr = stat(sub)
    if n >= 80:
        single_results.append((wr, sr, n, name, pred))

single_results.sort(key=lambda x: -x[0])
print("\n--- Top single filters (sorted by WR) ---")
for wr, sr, n, name, _ in single_results[:20]:
    rtr = sr / n
    print(f"  {name:<60} cl={n:>4}  WR={wr:>5.2f}%  ΣR={sr:>+6.1f}  R/tr={rtr:+.3f}")

print("\n--- Top pair filters (AND) ---")
pair_results = []
for i in range(len(candidates)):
    for j in range(i+1, len(candidates)):
        nm_a, pa = candidates[i]
        nm_b, pb = candidates[j]
        sub = [r for r in results if pa(r) and pb(r)]
        n, wr, sr = stat(sub)
        if n >= 80 and wr >= 63:
            pair_results.append((wr * 0.7 + (sr / n) * 30, wr, sr, n, f"{nm_a} & {nm_b}"))

pair_results.sort(key=lambda x: -x[0])
for sc, wr, sr, n, name in pair_results[:25]:
    rtr = sr / n
    print(f"  {name:<86} cl={n:>4}  WR={wr:>5.2f}%  ΣR={sr:>+5.1f}  R/tr={rtr:+.3f}")


# Save CSV
OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts/graal_v3_features_1094.csv"
with OUT.open('w', newline='') as f:
    w = csv.writer(f)
    cols = ["side", "variant", "out", "pos_5d", "pos_20d", "ema50", "ema200", "ema_d",
            "r_atr", "atr_p", "cascade", "mom_4h", "mom_12h", "hour", "weekday", "year"]
    w.writerow(cols)
    for r in results:
        w.writerow([r[c] for c in cols])
print(f"\nSaved → {OUT}")
print(f"Total: {time.time()-t0:.1f}s")
