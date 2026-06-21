"""Graal search v2 — continuous distance-to-magnet features.

Ключевые отличия от v1:
  1. dist_above_R / dist_below_R — расстояние от entry до ближайшего untouched HTF
     магнита (любой тип: bearish FVG above для LONG, bullish FVG below, marubozu open),
     в R-units. Asymmetry = dist_above − dist_below.
  2. pattern_at_HTF_fractal — pattern.low (LONG) на HTF FL ±0.3R.
  3. strict_sweep — HTF wick через FL/FH в последних 3 HTF барах с close-rejection.
  4. cascade_W_D_12h_4h — фрактальный trend на 4 ТФ включая W (Mon-anchor).
  5. r_atr — R / ATR(20) на 1h.
  6. pos_in_1D — позиция pattern.low в 1D candle (0=low, 1=high).
"""
from __future__ import annotations

import csv
import pathlib
import sys
import time
from datetime import datetime, timezone
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.i_rdrb.code import detect_i_rdrb
from elements.fvg.code import detect_fvg
from elements.marubozu.code import detect_marubozu
from elements.fractal.code import detect_fractal

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MS_HOUR = 3600_000
MAX_HOLD_MIN = 30 * 24 * 60

HTF_LIST = [("4h", 4 * MS_HOUR), ("6h", 6 * MS_HOUR), ("12h", 12 * MS_HOUR), ("1D", 24 * MS_HOUR)]
CASCADE_TFS = [("4h", 4 * MS_HOUR), ("12h", 12 * MS_HOUR), ("1D", 24 * MS_HOUR), ("W", 7 * 24 * MS_HOUR)]
SWEEP_LOOKBACK_BARS = 3

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
    """W = Mon 00:00 UTC anchor (TV-canon, see memory)."""
    # Monday 2017-01-02 00:00 UTC = 1483315200000 ms. Используем как baseline anchor.
    # Bucket = week_ms = 7 * 24 * 3600 * 1000.
    week_ms = 7 * 24 * 3600 * 1000
    mon_anchor = 1483315200000  # known Monday
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
print(f"  {len(data):,} 1m rows ({time.time()-t0:.1f}s)")

ts_arr = np.array([r[0] for r in data], dtype=np.int64)
lo_arr = np.array([r[3] for r in data], dtype=np.float64)
hi_arr = np.array([r[2] for r in data], dtype=np.float64)

candles_1h = aggregate_epoch(data, 60)
last_ts = data[-1][0]
window_start_ms = last_ts - 6 * 365 * 24 * 3600 * 1000
candles_1h_w = [c for c in candles_1h if c.open_time >= window_start_ms]

htf_candles = {}
for name, ms in HTF_LIST:
    htf_candles[name] = aggregate_epoch(data, ms // 60_000)
# Cascade extras
for name, ms in CASCADE_TFS:
    if name in htf_candles: continue
    if name == "W":
        htf_candles[name] = aggregate_weekly_monday(data)
    else:
        htf_candles[name] = aggregate_epoch(data, ms // 60_000)
print(f"HTF candles: " + ", ".join(f"{n}={len(htf_candles[n])}" for n, _ in HTF_LIST + [("W", 0)]))


# === Pre-compute magnets per HTF ===
# Магнит = (level / zone, form_ts, first_touch_idx, dir_relative_to_price_at_form)
# Для каждой 1h-candle нам потребуется быстро найти ближайший магнит выше / ниже определённого уровня (entry).

def first_touch_zone(zone_bot, zone_top, form_ts):
    i0 = int(np.searchsorted(ts_arr, form_ts, side='left'))
    if i0 >= len(ts_arr): return len(ts_arr)
    mask = (lo_arr[i0:] <= zone_top) & (hi_arr[i0:] >= zone_bot)
    nz = int(np.argmax(mask))
    if not mask[nz]: return len(ts_arr)
    return i0 + nz


def first_touch_point(level, form_ts):
    i0 = int(np.searchsorted(ts_arr, form_ts, side='left'))
    if i0 >= len(ts_arr): return len(ts_arr)
    mask = (lo_arr[i0:] <= level) & (hi_arr[i0:] >= level)
    nz = int(np.argmax(mask))
    if not mask[nz]: return len(ts_arr)
    return i0 + nz


# Магниты: для каждого HTF собираем список с центральным level магнита.
# Тип: "fvg_bear" (bearish FVG = магнит выше при formation; используем zone)
#      "fvg_bull" (bullish FVG = магнит ниже)
#      "maru_bear_open" (bear marubozu open at high = магнит выше)
#      "maru_bull_open" (bull marubozu open at low = магнит ниже)
htf_magnets = {}  # name → list of {"type", "level_lo", "level_hi", "form_ts", "first_touch"}
for name, _ in HTF_LIST:
    cs = htf_candles[name]
    tf_ms = next(m for n, m in HTF_LIST if n == name)
    ms_list = []
    # FVG
    for i in range(len(cs) - 2):
        f = detect_fvg(cs[i], cs[i+1], cs[i+2])
        if f is None: continue
        bot, top = f.zone
        form_ts = cs[i+2].open_time + tf_ms
        ms_list.append({
            "type": "fvg_bear" if f.direction == "short" else "fvg_bull",
            "level_lo": bot, "level_hi": top,
            "form_ts": form_ts,
            "first_touch": first_touch_zone(bot, top, form_ts),
        })
    # Marubozu opens (points)
    for c in cs:
        m = detect_marubozu(c)
        if m is None: continue
        form_ts = c.open_time + tf_ms
        open_lvl = c.open
        ms_list.append({
            "type": "maru_bear_open" if m.direction == "short" else "maru_bull_open",
            "level_lo": open_lvl, "level_hi": open_lvl,
            "form_ts": form_ts,
            "first_touch": first_touch_point(open_lvl, form_ts),
        })
    htf_magnets[name] = ms_list
print(f"HTF magnets: " + ", ".join(f"{n}={len(htf_magnets[n])}" for n, _ in HTF_LIST) + f"  ({time.time()-t0:.1f}s)")

# Fractals per HTF (для cascade и для pattern.low ≈ HTF FL)
htf_fracs = {}
for name, _ in CASCADE_TFS:
    cs = htf_candles[name]
    tf_ms = next(m for n, m in CASCADE_TFS if n == name)
    fr = []
    for i in range(2, len(cs) - 2):
        f = detect_fractal(cs[i-2:i+3], n=2)
        if f is None: continue
        fr.append({
            "dir": f.direction,
            "level": f.level,
            "center_ts": cs[i].open_time,
            "confirm_ts": cs[i].open_time + 3 * tf_ms,
            "first_touch": first_touch_point(f.level, cs[i].open_time + 3 * tf_ms),
        })
    htf_fracs[name] = fr
print(f"HTF fractals: " + ", ".join(f"{n}={len(htf_fracs[n])}" for n, _ in CASCADE_TFS))


def idx_at(ms):
    return int(np.searchsorted(ts_arr, ms, side='left'))


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


# === ATR(20) на 1h ===
# precompute
hi1h = np.array([c.high for c in candles_1h], dtype=np.float64)
lo1h = np.array([c.low for c in candles_1h], dtype=np.float64)
cl1h = np.array([c.close for c in candles_1h], dtype=np.float64)
ts1h = np.array([c.open_time for c in candles_1h], dtype=np.int64)
tr = np.maximum.reduce([hi1h - lo1h,
                        np.abs(hi1h - np.concatenate([[cl1h[0]], cl1h[:-1]])),
                        np.abs(lo1h - np.concatenate([[cl1h[0]], cl1h[:-1]]))])
# rolling mean 20
atr20 = np.zeros_like(tr)
for i in range(len(tr)):
    if i < 19: atr20[i] = tr[:i+1].mean()
    else: atr20[i] = tr[i-19:i+1].mean()


def idx_1h_at(ms):
    return int(np.searchsorted(ts1h, ms, side='left'))


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
print(f"\nDetected: {len(setups)} setups  ({time.time()-t0:.1f}s)")


# === Compute features per setup ===
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
    start_idx = idx_at(start_ms)
    c1_open = s["c1_open"]
    out = simulate(side, entry, sl, tp, start_ms)

    # === Magnet distances (in R-units) ===
    # nearest untouched magnet ABOVE entry, BELOW entry
    nearest_above = float('inf')
    nearest_below = float('inf')
    for name, _ in HTF_LIST:
        for m in htf_magnets[name]:
            if m["form_ts"] >= start_ms: continue
            if m["first_touch"] <= start_idx: continue
            # центр магнита: для FVG = mid zone, для marubozu = open level
            mid = (m["level_lo"] + m["level_hi"]) / 2
            if mid > entry:
                d = (mid - entry) / r_unit
                if d < nearest_above: nearest_above = d
            elif mid < entry:
                d = (entry - mid) / r_unit
                if d < nearest_below: nearest_below = d

    # === Cascade (W, D, 12h, 4h) ===
    cascade = 0
    cascade_W = 0
    for name, tf_ms in CASCADE_TFS:
        confirmed = [f for f in htf_fracs[name] if f["confirm_ts"] <= c1_open]
        fhs = [f for f in confirmed if f["dir"] == "high"]
        fls = [f for f in confirmed if f["dir"] == "low"]
        if len(fhs) < 2 or len(fls) < 2: continue
        up = (fhs[-1]["level"] > fhs[-2]["level"]) and (fls[-1]["level"] > fls[-2]["level"])
        down = (fhs[-1]["level"] < fhs[-2]["level"]) and (fls[-1]["level"] < fls[-2]["level"])
        match = (side == "long" and up) or (side == "short" and down)
        if match:
            cascade += 1
            if name == "W": cascade_W = 1

    # === Pattern.low(high) at HTF fractal (within 0.3R) ===
    pat_at_FL = 0
    pat_at_FH = 0
    for name, _ in CASCADE_TFS:
        for f in htf_fracs[name]:
            if f["confirm_ts"] > c1_open: continue
            if f["first_touch"] != len(ts_arr) and f["first_touch"] < idx_at(c1_open):
                continue  # уже swept до C1
            if f["dir"] == "low":
                if abs(pl - f["level"]) / r_unit <= 0.3:
                    pat_at_FL = 1
                    break
            else:
                if abs(ph - f["level"]) / r_unit <= 0.3:
                    pat_at_FH = 1
                    break
        if (side == "long" and pat_at_FL) or (side == "short" and pat_at_FH): break

    # === Strict sweep: HTF wick через FL/FH в последних 3 HTF барах с close-rejection ===
    strict_sweep = 0
    for name, tf_ms in HTF_LIST:
        cs = htf_candles[name]
        # последние 3 HTF бара перед c1_open
        end_idx_htf = next((j for j, c in enumerate(cs) if c.open_time >= c1_open), len(cs))
        sw_window = cs[max(0, end_idx_htf - SWEEP_LOOKBACK_BARS):end_idx_htf]
        # Найти ближайший unswept HTF fractal противоположного направления
        target_dir = "low" if side == "long" else "high"
        for f in htf_fracs.get(name, []):
            if f["confirm_ts"] > c1_open: continue
            if f["dir"] != target_dir: continue
            lvl = f["level"]
            for c in sw_window:
                if side == "long":
                    # wick прошёл ≥ 0.3R за level (low < level - 0.3R), close > level
                    if c.low < lvl - 0.3 * r_unit and c.close > lvl:
                        strict_sweep = 1; break
                else:
                    if c.high > lvl + 0.3 * r_unit and c.close < lvl:
                        strict_sweep = 1; break
            if strict_sweep: break
        if strict_sweep: break

    # === R/ATR(20) ===
    c5_idx = idx_1h_at(s["c5_open"])
    atr = atr20[min(c5_idx, len(atr20) - 1)]
    r_atr = r_unit / atr if atr > 0 else 0

    # === Position in PREVIOUS fully-closed 1D candle (no look-ahead) ===
    cs_d = htf_candles["1D"]
    tf_d_ms = 24 * MS_HOUR
    pos_d = 0.5
    # Last 1D candle whose CLOSE (open+24h) ≤ c1_open
    for c in reversed(cs_d):
        if c.open_time + tf_d_ms <= c1_open:
            rng = c.high - c.low
            if rng > 0:
                pos_d = (pl - c.low) / rng if side == "long" else (ph - c.low) / rng
            break

    # === Position in PREVIOUS closed 4h candle (proxy for intraday context) ===
    cs_4h = htf_candles["4h"]
    tf_4h_ms = 4 * MS_HOUR
    pos_4h = 0.5
    for c in reversed(cs_4h):
        if c.open_time + tf_4h_ms <= c1_open:
            rng = c.high - c.low
            if rng > 0:
                pos_4h = (pl - c.low) / rng if side == "long" else (ph - c.low) / rng
            break

    # === Position in PREVIOUS closed 12h candle ===
    cs_12h = htf_candles["12h"]
    tf_12h_ms = 12 * MS_HOUR
    pos_12h = 0.5
    for c in reversed(cs_12h):
        if c.open_time + tf_12h_ms <= c1_open:
            rng = c.high - c.low
            if rng > 0:
                pos_12h = (pl - c.low) / rng if side == "long" else (ph - c.low) / rng
            break

    results.append({
        "side": side, "variant": s["variant"], "out": out,
        "above_R": nearest_above, "below_R": nearest_below,
        "cascade": cascade, "cascade_W": cascade_W,
        "pat_FL": pat_at_FL, "pat_FH": pat_at_FH,
        "strict_sweep": strict_sweep,
        "r_atr": r_atr, "pos_d": pos_d, "pos_4h": pos_4h, "pos_12h": pos_12h,
    })

print(f"Computed features for {len(results)} setups  ({time.time()-t0:.1f}s)")


def stat(rows):
    w_ = sum(1 for r in rows if r["out"] == "win")
    l_ = sum(1 for r in rows if r["out"] == "loss")
    n = w_ + l_
    wr = w_ / n * 100 if n else 0
    sr = w_ - l_
    rtr = sr / n if n else 0
    return len(rows), n, w_, l_, wr, sr, rtr


def bk(name, rows):
    nset, n, w, l, wr, sr, rtr = stat(rows)
    print(f"  {name:<46} n_set={nset:>4}  cl={n:>4}  WR={wr:>5.2f}%  ΣR={sr:>+6.1f}  R/tr={rtr:+.3f}")


def bk_ls(name, rows):
    bk(name, rows)
    for side in ("long", "short"):
        sub = [r for r in rows if r["side"] == side]
        if not sub: continue
        _, n, w, l, wr, sr, rtr = stat(sub)
        print(f"      {side.upper():<6} n_set={len(sub):>4}  cl={n:>4}  WR={wr:>5.2f}%  ΣR={sr:>+5.1f}  R/tr={rtr:+.3f}")


print("\n" + "=" * 96)
print(" BASELINE")
print("=" * 96)
bk_ls("BASELINE", results)


print("\n" + "=" * 96)
print(" Continuous features — binning")
print("=" * 96)

# above_R / below_R distribution + WR by bin
def bin_continuous(feat, bins):
    print(f"\n--- {feat} bins ---")
    for lo, hi in bins:
        sub = [r for r in results if lo <= r[feat] < hi]
        bk_ls(f"  [{lo:.2f}, {hi:.2f})", sub)

bin_continuous("above_R", [(0, 1), (1, 2), (2, 4), (4, 8), (8, 1e9)])
bin_continuous("below_R", [(0, 1), (1, 2), (2, 4), (4, 8), (8, 1e9)])
bin_continuous("r_atr", [(0, 0.4), (0.4, 0.7), (0.7, 1.0), (1.0, 1.5), (1.5, 1e9)])
bin_continuous("pos_d", [(0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)])
bin_continuous("pos_4h", [(-1, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 2)])
bin_continuous("pos_12h", [(-1, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 2)])


print("\n" + "=" * 96)
print(" Asymmetry (above_R / below_R)")
print("=" * 96)
# asym = below_R - above_R: positive = magnet ahead is closer than magnet behind (good for LONG TP)
for label, lo, hi in [
    ("asym ≤ -2", -1e9, -2),
    ("-2 < asym ≤ 0", -2, 0),
    ("0 < asym ≤ 2", 0, 2),
    ("2 < asym", 2, 1e9),
]:
    sub = [r for r in results if lo < (r["below_R"] - r["above_R"]) <= hi]
    bk_ls(label, sub)


print("\n" + "=" * 96)
print(" Boolean features")
print("=" * 96)
for feat in ["cascade", "cascade_W", "pat_FL", "pat_FH", "strict_sweep"]:
    print(f"\n--- {feat} ---")
    for v in sorted(set(r[feat] for r in results)):
        sub = [r for r in results if r[feat] == v]
        bk_ls(f"  ={v}", sub)


print("\n" + "=" * 96)
print(" Combos")
print("=" * 96)
for name, cond in [
    ("above_R < 2 (магнит-вперёд близко)", lambda r: r["above_R"] < 2),
    ("above_R < 2 AND cascade≥1", lambda r: r["above_R"] < 2 and r["cascade"] >= 1),
    ("above_R < below_R (магнит-вперёд ближе)", lambda r: r["above_R"] < r["below_R"]),
    ("above_R < below_R AND cascade≥1", lambda r: r["above_R"] < r["below_R"] and r["cascade"] >= 1),
    ("above_R < below_R AND r_atr ∈ [0.55, 1.05]", lambda r: r["above_R"] < r["below_R"] and 0.55 <= r["r_atr"] <= 1.05),
    ("(pat_FL or pat_FH same side)", lambda r: (r["side"] == "long" and r["pat_FL"]) or (r["side"] == "short" and r["pat_FH"])),
    ("pat_F* AND cascade≥1", lambda r: ((r["side"] == "long" and r["pat_FL"]) or (r["side"] == "short" and r["pat_FH"])) and r["cascade"] >= 1),
    ("pat_F* AND above_R < below_R", lambda r: ((r["side"] == "long" and r["pat_FL"]) or (r["side"] == "short" and r["pat_FH"])) and r["above_R"] < r["below_R"]),
    ("strict_sweep AND above_R<2", lambda r: r["strict_sweep"] and r["above_R"] < 2),
    ("cascade_W=1", lambda r: r["cascade_W"] == 1),
    ("cascade_W=1 AND cascade≥2", lambda r: r["cascade_W"] == 1 and r["cascade"] >= 2),
    ("EXCLUDE: above_R > below_R AND cascade=0 (бесперспективные)", lambda r: not (r["above_R"] > r["below_R"] and r["cascade"] == 0)),
]:
    print(f"\n--- {name} ---")
    bk_ls("", [r for r in results if cond(r)])


# Save raw CSV
OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts/graal_v2_features_1094.csv"
with OUT.open('w', newline='') as f:
    w = csv.writer(f)
    cols = ["side", "variant", "out", "above_R", "below_R", "cascade", "cascade_W",
            "pat_FL", "pat_FH", "strict_sweep", "r_atr", "pos_d", "pos_4h", "pos_12h"]
    w.writerow(cols)
    for r in results:
        # cap infinities
        vals = [r[c] if not isinstance(r[c], float) or r[c] < 1e8 else 999.0 for c in cols]
        w.writerow(vals)
print(f"\nSaved → {OUT}")
print(f"Total: {time.time()-t0:.1f}s")
