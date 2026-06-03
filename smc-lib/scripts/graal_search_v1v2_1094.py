"""Поиск граалевых фильтров для i-RDRB+FVG V1+V2 = 1094 setups.

Подход: для каждого setup вычисляем набор features связанных с HTF зонами интереса
(untraded-magnet принцип). Затем стратифицируем WR/ΣR по каждой feature.

Все feature anti-look-ahead: zone formation_ts < start_ms, untouched check в окне
[formation_ts, start_ms).

Features:
  TP-path magnets (price goes from entry → TP):
    M_tp_any   — кол-во untouched HTF FVG (любой dir) с zone ∩ [entry, TP] ≠ ∅
    M_tp_same  — same-dir
    M_tp_opp   — opposite-dir
    M_tp_maru  — кол-во HTF marubozu с open ∈ [entry, TP], untouched
  SL-path magnets (price could drop entry → SL):
    M_sl_opp   — opposite-dir HTF FVG в [SL, entry] — "тянет к SL" (bad)
    M_sl_same  — same-dir HTF FVG в [SL, entry] — "поддержка" (good)
  Preceding institutional fuel:
    Sweep_HTF_opp — был ли в окне до C1 confirmed wick-sweep HTF fractal противоположного
                    (для long — FL; для short — FH) на любом HTF, формально:
                    HTF wick проходит через level fractal, body закрывается с rejection
    iFVG_same    — был ли confirmed iFVG-same-dir в окне K hours до C1
  Entry zone confluence:
    Entry_in_HTF_OB_same — entry-цена попадает в зону интереса HTF OB того же направления
    Entry_in_HTF_BO_same — то же для block_orders
  Cascade structure (через fractals):
    Cascade_score — кол-во HTFs (D, 12h, 4h) где локальный trend (последние 2 confirmed
                    fractals) совпадает с pattern.direction
"""
from __future__ import annotations

import csv
import pathlib
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.i_rdrb.code import detect_i_rdrb
from elements.fvg.code import detect_fvg, FVG
from elements.marubozu.code import detect_marubozu
from elements.fractal.code import detect_fractal
from elements.ob.code import detect_ob

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MS_HOUR = 3600_000
MAX_HOLD_MIN = 30 * 24 * 60

# HTFs для magnet/zone-confluence
HTF_LIST = [("4h", 4 * MS_HOUR), ("6h", 6 * MS_HOUR), ("12h", 12 * MS_HOUR), ("1D", 24 * MS_HOUR)]
# Cascade trend (через fractals) — на этих ТФ
CASCADE_TFS = [("4h", 4 * MS_HOUR), ("12h", 12 * MS_HOUR), ("1D", 24 * MS_HOUR)]
# Sweep / iFVG lookback (в часах до C1)
LOOKBACK_HOURS = 48

t0 = time.time()


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


print("Loading 1m...")
data = load_1m()
print(f"  {len(data):,} 1m rows ({time.time()-t0:.1f}s)")

candles_1h = aggregate(data, 60)
ts_1m = [r[0] for r in data]
last_ts = data[-1][0]
window_start_ms = last_ts - 6 * 365 * 24 * 3600 * 1000
candles_1h_w = [c for c in candles_1h if c.open_time >= window_start_ms]

htf_candles = {}
for name, ms in HTF_LIST + [(n, m) for n, m in CASCADE_TFS if n not in [x[0] for x in HTF_LIST]]:
    tf_min = ms // 60_000
    htf_candles[name] = aggregate(data, tf_min)


# === Pre-compute HTF zones with first_touch_idx ===
# Конвертируем 1m в numpy для быстрого скана
import numpy as np
ts_arr = np.array([r[0] for r in data], dtype=np.int64)
lo_arr = np.array([r[3] for r in data], dtype=np.float64)
hi_arr = np.array([r[2] for r in data], dtype=np.float64)

def first_touch_zone(zone_bot, zone_top, form_ts):
    """Returns 1m index of first candle that touches zone after form_ts, or len if never."""
    i0 = int(np.searchsorted(ts_arr, form_ts, side='left'))
    if i0 >= len(ts_arr): return len(ts_arr)
    # touch: lo_arr <= zone_top AND hi_arr >= zone_bot
    mask = (lo_arr[i0:] <= zone_top) & (hi_arr[i0:] >= zone_bot)
    nz = np.argmax(mask)  # first True
    if not mask[nz]:
        return len(ts_arr)
    return i0 + int(nz)


def first_touch_point(level, form_ts):
    i0 = int(np.searchsorted(ts_arr, form_ts, side='left'))
    if i0 >= len(ts_arr): return len(ts_arr)
    mask = (lo_arr[i0:] <= level) & (hi_arr[i0:] >= level)
    nz = np.argmax(mask)
    if not mask[nz]:
        return len(ts_arr)
    return i0 + int(nz)


# FVGs per HTF: {dir, top, bot, form_ts, first_touch_idx}
htf_fvgs = {}
for name, _ in HTF_LIST:
    cs = htf_candles[name]
    tf_ms = next(m for n, m in HTF_LIST if n == name)
    fvgs = []
    for i in range(len(cs) - 2):
        f = detect_fvg(cs[i], cs[i+1], cs[i+2])
        if f is None: continue
        bot, top = f.zone
        form_ts = cs[i+2].open_time + tf_ms
        fvgs.append({
            "dir": f.direction,
            "top": top, "bot": bot,
            "form_ts": form_ts,
            "first_touch": first_touch_zone(bot, top, form_ts),
        })
    htf_fvgs[name] = fvgs
print(f"HTF FVGs (with first_touch): " + ", ".join(f"{n}={len(htf_fvgs[n])}" for n, _ in HTF_LIST))

# Marubozu opens (with first_touch of open level)
htf_maru = {}
for name, _ in HTF_LIST:
    cs = htf_candles[name]
    tf_ms = next(m for n, m in HTF_LIST if n == name)
    ms_ = []
    for c in cs:
        m = detect_marubozu(c)
        if m is None: continue
        open_lvl = m.candle.open
        form_ts = c.open_time + tf_ms
        ms_.append({
            "dir": m.direction,
            "open": open_lvl,
            "form_ts": form_ts,
            "first_touch": first_touch_point(open_lvl, form_ts),
        })
    htf_maru[name] = ms_
print(f"HTF Marubozu: " + ", ".join(f"{n}={len(htf_maru[n])}" for n, _ in HTF_LIST))

# Fractals per HTF
htf_fracs = {}
for name, _ in HTF_LIST:
    cs = htf_candles[name]
    tf_ms = next(m for n, m in HTF_LIST if n == name)
    fr = []
    for i in range(2, len(cs) - 2):
        window = cs[i-2:i+3]
        f = detect_fractal(window, n=2)
        if f is None: continue
        # confirmed at center.open + 3*tf (n+1=3)
        fr.append({
            "dir": f.direction,  # "high" or "low"
            "level": f.level,
            "center_ts": cs[i].open_time,
            "confirm_ts": cs[i].open_time + 3 * tf_ms,
        })
    htf_fracs[name] = fr
print(f"HTF Fractals: " + ", ".join(f"{n}={len(htf_fracs[n])}" for n, _ in HTF_LIST))

# OB per HTF (для entry-zone confluence)
htf_obs = {}
for name, _ in HTF_LIST:
    cs = htf_candles[name]
    tf_ms = next(m for n, m in HTF_LIST if n == name)
    obs = []
    for i in range(len(cs) - 1):
        o = detect_ob(cs[i], cs[i+1])
        if o is None: continue
        obs.append({
            "dir": o.direction,
            "bot": o.zone[0], "top": o.zone[1],
            "form_ts": cs[i+1].open_time + tf_ms,
        })
    htf_obs[name] = obs
print(f"HTF OBs: " + ", ".join(f"{n}={len(htf_obs[n])}" for n, _ in HTF_LIST))
print(f"Pre-compute done: {time.time()-t0:.1f}s")


def idx_at(ms):
    return int(np.searchsorted(ts_arr, ms, side='left'))


def simulate(side, entry, sl, tp, start_ms):
    sk = idx_at(start_ms); ek = min(sk + MAX_HOLD_MIN, len(data))
    in_trade = False
    for k in range(sk, ek):
        _, _, h_, l_, _ = data[k]
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


# Untouched-at(start_ms) = first_touch_idx > idx_at(start_ms)
# При form_ts >= start_ms зона ещё не сформирована — недопустима (отсев в основном цикле).


# === Detect setups & compute features ===
print("\nDetecting setups + computing features (this is the slow part)...")
setups = []
for i in range(len(candles_1h_w) - 5):
    c1, c2, c3, c4, c5, c6 = candles_1h_w[i:i + 6]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None: continue
    c1_open = c1.open_time

    fvg_v1 = detect_fvg(c3, c4, c5)
    if fvg_v1 and fvg_v1.direction == ir.direction:
        pl = min(c.low for c in (c1, c2, c3, c4, c5))
        ph = max(c.high for c in (c1, c2, c3, c4, c5))
        setups.append({"ir": ir, "variant": "V1", "pl": pl, "ph": ph,
                       "c1_open": c1_open,
                       "start_ms": c5.open_time + MS_HOUR})

    fvg_v2 = detect_fvg(c4, c5, c6)
    if fvg_v2 and fvg_v2.direction == ir.direction:
        pl = min(c.low for c in (c1, c2, c3, c4, c5, c6))
        ph = max(c.high for c in (c1, c2, c3, c4, c5, c6))
        setups.append({"ir": ir, "variant": "V2", "pl": pl, "ph": ph,
                       "c1_open": c1_open,
                       "start_ms": c6.open_time + MS_HOUR})

print(f"  {len(setups)} setups detected ({time.time()-t0:.1f}s)")


def overlap(a_bot, a_top, b_bot, b_top):
    return max(a_bot, b_bot) <= min(a_top, b_top)


# === Process each setup ===
results = []
for idx_s, s in enumerate(setups):
    if idx_s % 200 == 0:
        print(f"  ... {idx_s}/{len(setups)} ({time.time()-t0:.0f}s)")

    ir, pl, ph = s["ir"], s["pl"], s["ph"]
    side = ir.direction
    bb, bt = ir.rdrb.block
    if side == "long":
        entry = bt
        sl = pl + 0.1 * (bb - pl)
        if entry <= sl: continue
        r_unit = entry - sl
        tp = entry + r_unit
        tp_path = (entry, tp)         # bot, top
        sl_path = (sl, entry)
    else:
        entry = bb
        sl = ph - 0.1 * (ph - bt)
        if entry >= sl: continue
        r_unit = sl - entry
        tp = entry - r_unit
        tp_path = (tp, entry)
        sl_path = (entry, sl)

    start_ms = s["start_ms"]
    c1_open = s["c1_open"]
    lookback_ms = c1_open - LOOKBACK_HOURS * MS_HOUR
    start_idx = idx_at(start_ms)

    out = simulate(side, entry, sl, tp, start_ms)

    # === Features ===
    tp_b, tp_t = tp_path
    sl_b, sl_t = sl_path

    M_tp_any = M_tp_same = M_tp_opp = 0
    M_sl_same = M_sl_opp = 0
    M_tp_maru = 0
    Sweep_HTF_opp = False
    iFVG_same = False  # placeholder, skipped (computationally heavy)
    Entry_in_HTF_OB_same = False

    same_fvg_dir = "long" if side == "long" else "short"
    opp_fvg_dir = "short" if side == "long" else "long"

    for name, _ in HTF_LIST:
        # FVG checks
        for f in htf_fvgs[name]:
            if f["form_ts"] >= start_ms: continue
            if f["first_touch"] <= start_idx: continue  # already filled before start
            # TP path
            if overlap(f["bot"], f["top"], tp_b, tp_t):
                M_tp_any += 1
                if f["dir"] == same_fvg_dir: M_tp_same += 1
                else: M_tp_opp += 1
            # SL path
            elif overlap(f["bot"], f["top"], sl_b, sl_t):
                if f["dir"] == same_fvg_dir: M_sl_same += 1
                else: M_sl_opp += 1

        # Marubozu opens in TP path
        for m in htf_maru[name]:
            if m["form_ts"] >= start_ms: continue
            if m["first_touch"] <= start_idx: continue
            if tp_b <= m["open"] <= tp_t:
                M_tp_maru += 1

        # Entry inside HTF OB / BO of same direction
        for o in htf_obs[name]:
            if o["form_ts"] >= start_ms: continue
            if o["dir"] != side: continue
            if o["bot"] <= entry <= o["top"]:
                Entry_in_HTF_OB_same = True
                break

        # Preceding sweep HTF fractal opposite to side
        # For LONG: ищем sweep FL (low fractal) в окне [lookback_ms, c1_open)
        # = HTF candle wick проходит через level FL (low ≤ level), но close > level (rejection)
        target_dir = "low" if side == "long" else "high"
        for fr in htf_fracs[name]:
            if fr["dir"] != target_dir: continue
            if fr["confirm_ts"] > c1_open: continue
            if fr["confirm_ts"] < lookback_ms: continue
            # check sweep on HTF candles between confirm_ts and c1_open
            cs = htf_candles[name]
            tf_ms = next(m_ for n_, m_ in HTF_LIST if n_ == name)
            level = fr["level"]
            i0 = next((j for j, c in enumerate(cs) if c.open_time >= fr["confirm_ts"]), None)
            if i0 is None: continue
            for j in range(i0, len(cs)):
                if cs[j].open_time >= c1_open: break
                c = cs[j]
                if side == "long":
                    if c.low < level and c.close > level:
                        Sweep_HTF_opp = True
                        break
                else:
                    if c.high > level and c.close < level:
                        Sweep_HTF_opp = True
                        break
            if Sweep_HTF_opp: break

    # Cascade score (D, 12h, 4h trend через последние 2 confirmed fractals)
    cascade_score = 0
    for name, tf_ms in CASCADE_TFS:
        # последние 2 confirmed fractals до c1_open
        confirmed = [f for f in htf_fracs[name] if f["confirm_ts"] <= c1_open]
        if len(confirmed) < 4: continue
        # ищем последний FH и предпоследний FH; то же для FL
        fhs = [f for f in confirmed if f["dir"] == "high"]
        fls = [f for f in confirmed if f["dir"] == "low"]
        if len(fhs) < 2 or len(fls) < 2: continue
        last_fh, prev_fh = fhs[-1]["level"], fhs[-2]["level"]
        last_fl, prev_fl = fls[-1]["level"], fls[-2]["level"]
        # uptrend = HH + HL
        up = (last_fh > prev_fh) and (last_fl > prev_fl)
        down = (last_fh < prev_fh) and (last_fl < prev_fl)
        if side == "long" and up: cascade_score += 1
        if side == "short" and down: cascade_score += 1

    results.append({
        "side": side, "variant": s["variant"], "out": out,
        "M_tp_any": M_tp_any, "M_tp_same": M_tp_same, "M_tp_opp": M_tp_opp,
        "M_sl_same": M_sl_same, "M_sl_opp": M_sl_opp,
        "M_tp_maru": M_tp_maru,
        "Sweep": int(Sweep_HTF_opp),
        "OB_in": int(Entry_in_HTF_OB_same),
        "Cascade": cascade_score,
    })

print(f"\nDone simulating + features ({time.time()-t0:.1f}s)")

# === Save raw to CSV ===
OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts/graal_features_1094.csv"
with OUT.open('w', newline='') as f:
    w = csv.writer(f)
    cols = ["side", "variant", "out", "M_tp_any", "M_tp_same", "M_tp_opp",
            "M_sl_same", "M_sl_opp", "M_tp_maru", "Sweep", "OB_in", "Cascade"]
    w.writerow(cols)
    for r in results:
        w.writerow([r[c] for c in cols])
print(f"Saved features → {OUT}\n")


# === Stratify ===
def stat(rows):
    w_ = sum(1 for r in rows if r["out"] == "win")
    l_ = sum(1 for r in rows if r["out"] == "loss")
    nf = sum(1 for r in rows if r["out"] == "no_fill")
    n = w_ + l_
    wr = w_ / n * 100 if n else 0
    sr = w_ - l_
    rtr = sr / n if n else 0
    return len(rows), n, w_, l_, nf, wr, sr, rtr


def print_bucket(name, rows):
    nset, n, w, l, nf, wr, sr, rtr = stat(rows)
    print(f"  {name:<42} n_set={nset:>4}  closed={n:>4}  WR={wr:>5.2f}%  ΣR={sr:>+6.1f}  R/tr={rtr:+.3f}")


def print_long_short(name, rows):
    """Дополнительно по сторонам."""
    print_bucket(name, rows)
    for side in ("long", "short"):
        sub = [r for r in rows if r["side"] == side]
        if not sub: continue
        _, n, w, l, _, wr, sr, rtr = stat(sub)
        print(f"      {side.upper():<6} n_set={len(sub):>4}  closed={n:>4}  WR={wr:>5.2f}%  ΣR={sr:>+5.1f}  R/tr={rtr:+.3f}")


print("=" * 90)
print(f" Baseline: {len(results)} setups")
print("=" * 90)
print_long_short("BASELINE", results)

print("\n" + "=" * 90)
print(" Feature stratification (univariate)")
print("=" * 90)

for feat, op_name, threshold in [
    ("M_tp_any", "≥1", 1), ("M_tp_any", "≥2", 2),
    ("M_tp_same", "≥1", 1), ("M_tp_same", "≥2", 2),
    ("M_tp_opp", "≥1", 1), ("M_tp_opp", "≥2", 2),
    ("M_sl_same", "≥1", 1), ("M_sl_opp", "≥1", 1),
    ("M_tp_maru", "≥1", 1),
    ("Sweep", "=1", 1), ("OB_in", "=1", 1),
    ("Cascade", "≥1", 1), ("Cascade", "≥2", 2), ("Cascade", "=3", 3),
]:
    sub_yes = [r for r in results if r[feat] >= threshold]
    sub_no = [r for r in results if r[feat] < threshold]
    print(f"\n--- {feat} {op_name} ---")
    print_long_short(f"  YES", sub_yes)
    print_bucket(f"  NO ", sub_no)

# === Try anti-filter combinations ===
print("\n" + "=" * 90)
print(" Anti-filters (exclude bad subsets)")
print("=" * 90)
for name, cond in [
    ("Exclude M_tp_opp≥1", lambda r: r["M_tp_opp"] < 1),
    ("Exclude M_tp_opp≥2", lambda r: r["M_tp_opp"] < 2),
    ("Exclude M_sl_opp≥1", lambda r: r["M_sl_opp"] < 1),
    ("Exclude (M_tp_opp≥1 OR M_sl_opp≥1)", lambda r: r["M_tp_opp"] < 1 and r["M_sl_opp"] < 1),
    ("Cascade=0 + M_tp_opp≥1 exclude", lambda r: not (r["Cascade"] == 0 and r["M_tp_opp"] >= 1)),
]:
    sub = [r for r in results if cond(r)]
    print(f"\n--- {name} ---")
    print_long_short("", sub)

# === Stack best signals ===
print("\n" + "=" * 90)
print(" Stacked positive signals")
print("=" * 90)
for name, cond in [
    ("M_tp_same≥1 AND M_tp_opp=0", lambda r: r["M_tp_same"] >= 1 and r["M_tp_opp"] == 0),
    ("M_tp_any≥1 AND Sweep=1", lambda r: r["M_tp_any"] >= 1 and r["Sweep"] == 1),
    ("Sweep=1 AND Cascade≥1", lambda r: r["Sweep"] == 1 and r["Cascade"] >= 1),
    ("OB_in=1", lambda r: r["OB_in"] == 1),
    ("OB_in=1 AND Sweep=1", lambda r: r["OB_in"] == 1 and r["Sweep"] == 1),
    ("M_tp_same≥1 AND Sweep=1 AND M_tp_opp=0", lambda r: r["M_tp_same"] >= 1 and r["Sweep"] == 1 and r["M_tp_opp"] == 0),
]:
    sub = [r for r in results if cond(r)]
    print(f"\n--- {name} ---")
    print_long_short("", sub)

print(f"\nTotal time: {time.time()-t0:.1f}s")
