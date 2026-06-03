"""F3 поиск через индикаторы — должно убрать #27, #53 без потерь 18 imp.

Индикаторы:
  - VIC ASVK на 12h: maxV(i), norm(i), maxV position в pivot bar (upper wick / body / lower wick)
  - RSI ASVK ema_3 на 1h, 2h, 3h в момент i.close (last completed bar)
  - VWAP anchored от prev opposite fractal
"""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.fractal.code import detect_fractal
from indicators.vic_asvk import calculate_vic_bar
from indicators.rsi_asvk import adjusted_rsi, asvk_zone
from indicators.vwap_anchored import anchored_vwap

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
TF12_MS = 12 * 3600_000
TF1H_MS = 3600_000
START_MS = int(datetime(2026, 2, 4, 0, 0, tzinfo=MSK).timestamp() * 1000)
IMPORTANT = {1, 3, 4, 5, 9, 10, 11, 14, 15, 20, 23, 26, 29, 40, 41, 42, 47, 48}
TO_REMOVE = {27, 53}


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000),
                         float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return rows


def aggregate(d, tf_ms):
    out = []; cb = None; o = h = l = c = v = 0.0
    for ts, oo, hh, ll, cc, vv in d:
        b = ts - (ts % tf_ms)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v))
            cb = b; o, h, l, c, v = oo, hh, ll, cc, vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v += vv
    if cb is not None: out.append((cb, o, h, l, c, v))
    return out


print("Loading...")
data = load_1m()

# 12h
bars12 = aggregate(data, TF12_MS)
# 1h/2h/3h for RSI ASVK
bars1h = aggregate(data, TF1H_MS)
bars2h = aggregate(data, 2 * TF1H_MS)
bars3h = aggregate(data, 3 * TF1H_MS)


print("Computing RSI ASVK on 1h/2h/3h (cached if exists)...")
tfs_for_rsi = {"1h": bars1h, "2h": bars2h, "3h": bars3h}
rsi_data = {}
for tf, bars in tfs_for_rsi.items():
    closes = [b[4] for b in bars]
    res = adjusted_rsi(closes, period=14)
    res["ts_open"] = [b[0] for b in bars]
    res["tf_ms"] = TF1H_MS if tf == "1h" else (2 * TF1H_MS if tf == "2h" else 3 * TF1H_MS)
    rsi_data[tf] = res
    print(f"  {tf}: {len(bars)} bars")


# Aggregate 1m → 12h with LTF composition for maxV
print("Computing VIC ASVK 12h with maxV...")
ltf_per_12h = {}
cb = None; co = ch = cl = cc = cv = 0.0; cltf = []
for ts, o, h, l, c, v in data:
    b = ts - (ts % TF12_MS)
    if b != cb:
        if cb is not None:
            ltf_per_12h[cb] = cltf
        cb = b; cltf = [(ts, o, h, l, c, v)]
    else:
        cltf.append((ts, o, h, l, c, v))
if cb is not None:
    ltf_per_12h[cb] = cltf

vic_per_12h = {}
for b in bars12:
    vic = calculate_vic_bar(ltf_per_12h.get(b[0], []))
    if vic is not None:
        vic_per_12h[b[0]] = vic
print(f"  VIC 12h ready: {len(vic_per_12h)} bars")


# Detect fractals
candles12 = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars12]
fractals = []
for i in range(2, len(candles12) - 2):
    f = detect_fractal(candles12[i-2:i+3], n=2)
    if f is None: continue
    if candles12[i].open_time < START_MS: continue
    fractals.append({"dir": f.direction, "level": f.level, "idx": i,
                     "center_ts": candles12[i].open_time,
                     "pivot_low": candles12[i].low, "pivot_high": candles12[i].high})


def color(b):
    if b[4] > b[1]: return "bull"
    if b[4] < b[1]: return "bear"
    return "doji"


def left_ext_5(f):
    bidx = f["idx"]
    win_lo = max(0, bidx - 5); win_hi = bidx
    slice_ = bars12[win_lo:win_hi]
    if not slice_: return True
    if f["dir"] == "high":
        return f["level"] > max(b[2] for b in slice_)
    else:
        return f["level"] < min(b[3] for b in slice_)


def f2_pass(f):
    bidx = f["idx"]
    c0, c1, c2 = color(bars12[bidx]), color(bars12[bidx-1]), color(bars12[bidx-2])
    opp = c0 != c1 and "doji" not in (c0, c1)
    three = c0 == c1 == c2 and c0 != "doji"
    return opp or three


for n, f in enumerate(fractals, 1):
    f["num"] = n
    f["is_important"] = (n in IMPORTANT)
    f["F1_pass"] = left_ext_5(f)
    f["F2_pass"] = f2_pass(f) if f["F1_pass"] else False


post_F1F2 = [f for f in fractals if f["F1_pass"] and f["F2_pass"]]


def htf_idx_at(ts_list, query_ts, tf_ms):
    """Last bar with open_time + tf_ms <= query_ts."""
    n = len(ts_list)
    lo, hi = 0, n
    while lo < hi:
        m = (lo + hi) // 2
        if ts_list[m] + tf_ms <= query_ts:
            lo = m + 1
        else:
            hi = m
    return lo - 1


# Pre-compute 1m arrays for anchored VWAP
ts_arr = np.array([r[0] for r in data], dtype=np.int64)
hi_arr = np.array([r[2] for r in data], dtype=np.float64)
lo_arr = np.array([r[3] for r in data], dtype=np.float64)
cl_arr = np.array([r[4] for r in data], dtype=np.float64)
vol_arr = np.array([r[5] for r in data], dtype=np.float64)
tp_arr = (hi_arr + lo_arr + cl_arr) / 3.0
pv_cumsum = np.cumsum(tp_arr * vol_arr)
v_cumsum = np.cumsum(vol_arr)


def anchored_vwap_at(anchor_ts, query_ts):
    if query_ts < anchor_ts: return None
    i0 = int(np.searchsorted(ts_arr, anchor_ts, side='left'))
    i1 = int(np.searchsorted(ts_arr, query_ts, side='right')) - 1
    if i1 < i0 or i0 >= len(ts_arr): return None
    pv = pv_cumsum[i1] - (pv_cumsum[i0-1] if i0 > 0 else 0)
    vv = v_cumsum[i1] - (v_cumsum[i0-1] if i0 > 0 else 0)
    return pv / vv if vv > 0 else None


# Compute features
print("Computing indicators per fractal...")
for f in post_F1F2:
    bidx = f["idx"]
    b = bars12[bidx]
    open_, high, low, close = b[1], b[2], b[3], b[4]
    pivot_close_ts = b[0] + TF12_MS

    # VIC maxV
    vic = vic_per_12h.get(b[0])
    if vic and vic.maxV is not None:
        maxv = vic.maxV
        f["maxV"] = maxv
        # Position in pivot bar
        body_top = max(open_, close); body_bot = min(open_, close)
        if maxv > body_top:
            f["maxV_pos"] = "upper_wick"
        elif maxv < body_bot:
            f["maxV_pos"] = "lower_wick"
        else:
            f["maxV_pos"] = "body"
        # Distance from pivot.level (relevant extreme)
        f["maxV_distance_pct"] = abs(maxv - f["level"]) / f["level"] * 100
        f["maxV_norm"] = vic.norm  # bull/bear delta normalized
    else:
        f["maxV"] = None; f["maxV_pos"] = "n/a"; f["maxV_distance_pct"] = 0; f["maxV_norm"] = 0

    # RSI ASVK zone at i.close moment on 1h, 2h, 3h
    for tf in ("1h", "2h", "3h"):
        rs = rsi_data[tf]
        idx = htf_idx_at(rs["ts_open"], pivot_close_ts, rs["tf_ms"])
        if idx < 0:
            f[f"rsi_{tf}_zone"] = "n/a"
            f[f"rsi_{tf}_ema3"] = None
        else:
            f[f"rsi_{tf}_zone"] = asvk_zone(
                rs["ema_3"][idx], rs["above"][idx], rs["below"][idx],
                rs["nwe_upper"][idx], rs["nwe_lower"][idx])
            f[f"rsi_{tf}_ema3"] = rs["ema_3"][idx]

    # VWAP anchored from prev opposite fractal
    prev_opp = None
    for p in reversed(fractals[:f["num"] - 1]):
        if p["dir"] != f["dir"]:
            prev_opp = p; break
    if prev_opp:
        vwap_val = anchored_vwap_at(prev_opp["center_ts"], pivot_close_ts - 60_000)
        if vwap_val is not None:
            f["vwap_opp"] = vwap_val
            f["vwap_opp_diff_pct"] = (close - vwap_val) / vwap_val * 100  # %
            # for FL: close should be below vwap (bearish move sustained)? Or above?
            # для FH: pivot above vwap = bull regime
            # для FL: pivot below vwap = bear regime
            if f["dir"] == "high":
                f["vwap_align"] = close > vwap_val
            else:
                f["vwap_align"] = close < vwap_val
        else:
            f["vwap_opp"] = None; f["vwap_opp_diff_pct"] = 0; f["vwap_align"] = False
    else:
        f["vwap_opp"] = None; f["vwap_opp_diff_pct"] = 0; f["vwap_align"] = False


# Print table
print(f"\n{'='*180}")
print(f" Indicator state at i.close (35 post-F1∩F2)")
print(f"{'='*180}")
print(f"  {'#':>3} {'★':>1} {'tag':>5} {'tp':>3} {'level':>6}  "
      f"{'maxV_pos':>10} {'mV_d%':>5} {'mV_nm':>5}  "
      f"{'rsi1h':>9} {'rsi2h':>9} {'rsi3h':>9}  "
      f"{'vwap_d%':>7} {'vAln':>4}")
print("-" * 180)
for f in sorted(post_F1F2, key=lambda x: x["num"]):
    star = "★" if f["is_important"] else " "
    glyph = "FH" if f["dir"] == "high" else "FL"
    tag = "RMV" if f["num"] in TO_REMOVE else ("imp" if f["is_important"] else "nse")
    print(f"  {f['num']:>3} {star:>1} {tag:>5} {glyph:>3} {f['level']:>6.0f}  "
          f"{f['maxV_pos']:>10} {f['maxV_distance_pct']:>4.1f}% {f['maxV_norm']:>+4.2f}  "
          f"{f['rsi_1h_zone']:>9} {f['rsi_2h_zone']:>9} {f['rsi_3h_zone']:>9}  "
          f"{f['vwap_opp_diff_pct']:>+6.2f}% {'Y' if f['vwap_align'] else '·':>4}")


# Specifically compare #27, #53 vs imp 3-same
print(f"\n{'='*120}")
print(f" Direct compare: #27, #53 (TO REMOVE) vs important 3-same continuation")
print(f"{'='*120}")
focus_nums = {10, 11, 14, 23, 27, 40, 53}  # 5 imp 3-same + 2 to-remove
for f in sorted(post_F1F2, key=lambda x: x["num"]):
    if f["num"] not in focus_nums: continue
    star = "★ IMP" if f["is_important"] else "✗ RMV"
    glyph = "FH" if f["dir"] == "high" else "FL"
    print(f"  {f['num']:>3} {star} {glyph} {f['level']:>6.0f}: "
          f"maxV={f['maxV_pos']}({f['maxV_distance_pct']:.1f}%, norm={f['maxV_norm']:+.2f})  "
          f"RSI 1h/2h/3h: {f['rsi_1h_zone']}/{f['rsi_2h_zone']}/{f['rsi_3h_zone']}  "
          f"vwap_d={f['vwap_opp_diff_pct']:+.2f}% align={f['vwap_align']}")


# Look for separator
def eval_filter(name, pred):
    kept = [f for f in post_F1F2 if pred(f)]
    imp = sum(1 for f in kept if f["is_important"])
    lost = 18 - imp
    keeps_27 = any(f["num"] == 27 and pred(f) for f in post_F1F2)
    keeps_53 = any(f["num"] == 53 and pred(f) for f in post_F1F2)
    noise = len(kept) - imp
    print(f"  {name:<60} keep={len(kept):>3}  imp={imp:>2}/18  noise={noise:>3}  "
          f"#27={'KEEP' if keeps_27 else 'CUT '}  #53={'KEEP' if keeps_53 else 'CUT '}")
    if lost > 0 and lost <= 5:
        lost_ids = [f["num"] for f in post_F1F2 if f["is_important"] and not pred(f)]
        print(f"      lost imp: {lost_ids}")


print(f"\n{'='*120}")
print(f" Candidate F3 filters")
print(f"{'='*120}")
# RSI ASVK based
for tf in ("1h", "2h", "3h"):
    eval_filter(f"FH: rsi_{tf} red/y_ob; FL: rsi_{tf} green/y_os",
                lambda f, t=tf: (f["dir"]=="high" and f[f"rsi_{t}_zone"] in ("red", "yellow_ob"))
                              or (f["dir"]=="low" and f[f"rsi_{t}_zone"] in ("green", "yellow_os")))
print()

# multi-TF sync: at least 2 TFs in OS for FL / OB for FH
def multi_tf_sync(f, k):
    if f["dir"] == "high":
        cnt = sum(1 for tf in ("1h","2h","3h") if f[f"rsi_{tf}_zone"] in ("red","yellow_ob"))
    else:
        cnt = sum(1 for tf in ("1h","2h","3h") if f[f"rsi_{tf}_zone"] in ("green","yellow_os"))
    return cnt >= k

eval_filter("RSI ASVK ≥1 TF in extreme (1h/2h/3h)", lambda f: multi_tf_sync(f, 1))
eval_filter("RSI ASVK ≥2 TF in extreme", lambda f: multi_tf_sync(f, 2))
eval_filter("RSI ASVK 3 TF in extreme", lambda f: multi_tf_sync(f, 3))
print()

# VIC maxV position
eval_filter("FH: maxV in upper_wick; FL: maxV in lower_wick",
            lambda f: (f["dir"]=="high" and f["maxV_pos"]=="upper_wick")
                   or (f["dir"]=="low" and f["maxV_pos"]=="lower_wick"))
eval_filter("FH: maxV NOT in body; FL: maxV NOT in body",
            lambda f: f["maxV_pos"] != "body")
print()

# VIC norm
for thr in [0.3, 0.5, 0.7]:
    eval_filter(f"FH: norm > +{thr}; FL: norm < -{thr}",
                lambda f, t=thr: (f["dir"]=="high" and f["maxV_norm"] > t)
                              or (f["dir"]=="low" and f["maxV_norm"] < -t))
print()

# VWAP align
eval_filter("vwap_align (FH above prev-opp VWAP / FL below)", lambda f: f["vwap_align"])

# Distance to maxV
for thr in [0.5, 1.0, 2.0, 3.0]:
    eval_filter(f"maxV_distance < {thr}% (close cluster)",
                lambda f, t=thr: f["maxV_distance_pct"] < t)
