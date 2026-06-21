"""Floating TP simulator на 387 setups (top per-type HMA filter basket).

Per setup:
  - Entry: 0.80 deep top FVG (n_FVG≥2) или 0.20 deep (n_FVG=1)
  - SL: drop_lo (LONG) / drop_hi (SHORT)
  - Float TP: 4 exit methods (SL / R_cap / score / 7d timeout)
  - Score: 4-indicator composite (Hull/MH/RSI/ASVK) on 1h

Config (BTC):
  R_cap = 4.5
  threshold = -0.25
  confirm = 2 bars
  max_hold = 7 days

Output: total R, WR, avg/median R per trade, breakdown per year × per type.
"""
import sys, pathlib, csv, time
import numpy as np
import pandas as pd
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import agg, aggregate_all_tfs, to_candles, MONDAY_USER_ANCHOR_MS

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from indicators.trend_line_asvk import hma

CSV_1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
TF_2H = 2 * 3600 * 1000

# Floating TP config (BTC)
R_CAP = 4.5
THRESHOLD = -0.25
CONFIRM = 2
MAX_HOLD_DAYS = 7

t0 = time.time()

# Load 1m as DataFrame for floating sim
print("Loading 1m...")
rows = []
with CSV_1M.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
        if t < START_MS: continue
        rows.append((t, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
ts_1m = np.array([r[0] for r in rows], dtype=np.int64)
h_1m_arr = np.array([r[2] for r in rows], dtype=np.float64)
l_1m_arr = np.array([r[3] for r in rows], dtype=np.float64)
c_1m_arr = np.array([r[4] for r in rows], dtype=np.float64)
print(f"  {len(rows):,} bars")

# Aggregate 1h for score
print("Aggregating 1h for indicator score...")
rows_ohlc = [(r[0], r[1], r[2], r[3], r[4]) for r in rows]
bars_1h = agg(rows_ohlc, 3600 * 1000, anchor=0)
df_1h = pd.DataFrame(bars_1h, columns=["ts_ms", "open", "high", "low", "close"]).set_index(
    pd.to_datetime([b[0] for b in bars_1h], unit="ms", utc=True))
print(f"  1h bars: {len(df_1h):,}")


# ─── 4-indicator score on 1h ─────────────────────────────
def _wma_fast(arr, period):
    period = max(int(period), 1)
    weights = np.arange(1, period + 1, dtype=float); weights /= weights.sum()
    out = np.full_like(arr, np.nan, dtype=float)
    if len(arr) < period: return out
    valid = np.convolve(arr, weights[::-1], mode="valid")
    out[period - 1:] = valid
    return out


def _hull_ma(close, length=78):
    arr = close.to_numpy(dtype=float)
    half = max(int(length / 2), 1)
    sqrt_len = max(int(round(np.sqrt(length))), 1)
    raw = 2.0 * _wma_fast(arr, half) - _wma_fast(arr, length)
    hull = _wma_fast(np.where(np.isnan(raw), 0.0, raw), sqrt_len)
    hull[:length + sqrt_len] = np.nan
    return pd.Series(hull, index=close.index)


def hull_signal(close, length=78):
    h = _hull_ma(close, length)
    out = np.zeros(len(close))
    arr_c = close.values; arr_h = h.values
    for i in range(len(close)):
        if i < 2 or pd.isna(arr_h[i-2]): out[i] = 0
        else: out[i] = 1.0 if arr_c[i] > arr_h[i-2] else -1.0
    return pd.Series(out, index=close.index)


def _mh_bw2(df):
    hlc3 = (df["high"] + df["low"] + df["close"]) / 3
    esa = hlc3.ewm(span=9, adjust=False).mean()
    d = (hlc3 - esa).abs().ewm(span=9, adjust=False).mean()
    ci = (hlc3 - esa) / (0.015 * d.replace(0, np.nan))
    wt1 = ci.ewm(span=12, adjust=False).mean()
    wt2 = wt1.rolling(4, min_periods=4).mean()
    sma14 = wt2.rolling(14, min_periods=14).mean()
    return wt2, sma14


def mh_signal(df):
    bw2, sma14 = _mh_bw2(df)
    out = np.zeros(len(df))
    for i in range(len(df)):
        v = bw2.iloc[i]; s = sma14.iloc[i]
        if pd.isna(v) or pd.isna(s): out[i] = 0
        elif v > 0: out[i] = 1.0 if v >= s else 0.5
        elif v < 0: out[i] = -1.0 if v <= s else -0.5
        else: out[i] = 0
    return pd.Series(out, index=df.index)


def _rsi_wilder(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0.0); loss = (-delta).clip(lower=0.0)
    avg_g = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_l = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_g / avg_l
    return 100 - (100 / (1 + rs))


def rsi_signal(close, period=14):
    return ((_rsi_wilder(close, period) - 50.0) / 50.0).clip(-1, 1).fillna(0)


def _asvk_adj_rsi(close):
    rsi = _rsi_wilder(close, 14)
    ema_for_coef = rsi.ewm(span=5, adjust=False).mean()
    coef = pd.Series(np.where(rsi >= 50, 1.2, 0.8), index=rsi.index)
    coefficient = (rsi * coef) / ema_for_coef.replace(0, np.nan)
    return (rsi * coefficient).ewm(span=5, adjust=False).mean()


def _asvk_levels(ema_3, lookback=200):
    n = len(ema_3); above = np.full(n, np.nan); below = np.full(n, np.nan)
    arr = ema_3.to_numpy()
    for i in range(lookback-1, n):
        win = arr[i-lookback+1:i+1]; win = win[~np.isnan(win)]
        if len(win) < 10: continue
        m = win > 50; z = m.sum()
        if z > 0:
            y = win[m].mean(); c1=100/y; c2=50/y; c3=c1-c2; c5=(c3/lookback)*z+c3
            above[i] = c5 * y
        m = win < 50; z = m.sum()
        if z > 0:
            y = win[m].mean(); c1=50/y; c2=1/y; c3=c1-c2; c5=(c3/lookback)*z+c3
            below[i] = 100 - (c5 * y)
    return pd.Series(above, index=ema_3.index), pd.Series(below, index=ema_3.index)


def asvk_signal(close):
    ema_3 = _asvk_adj_rsi(close)
    above, below = _asvk_levels(ema_3, 200)
    out = np.zeros(len(close))
    for i in range(len(close)):
        e = ema_3.iloc[i]; a = above.iloc[i]; b = below.iloc[i]
        if pd.isna(e) or pd.isna(a) or pd.isna(b): out[i] = 0
        elif e > a: out[i] = 1.0
        elif e < b: out[i] = -1.0
        else: out[i] = 0
    return pd.Series(out, index=close.index)


print("Computing 4-indicator score on 1h...")
s_hull = hull_signal(df_1h["close"])
s_mh = mh_signal(df_1h)
s_rsi = rsi_signal(df_1h["close"])
s_asvk = asvk_signal(df_1h["close"])
score_long = (s_hull + s_mh + s_rsi + s_asvk) / 4.0
score_short = -score_long
print(f"  Score series computed. Elapsed: {time.time()-t0:.1f}s")

ts_1h = df_1h.index.values.astype("datetime64[ns]")
sl_arr = score_long.values
ss_arr = score_short.values


# ─── Floating TP simulator ─────────────────────────────
def floating_tp(entry, sl, born_ms, direction):
    """4 exit methods. Returns (R, exit_reason, hold_h, max_R)."""
    if direction == "long" and entry <= sl: return None
    if direction == "short" and entry >= sl: return None
    risk = abs(entry - sl)
    if risk <= 0: return None

    # Fill at born_ms
    i_fill = int(np.searchsorted(ts_1m, born_ms, side="left"))
    # Find first 1m where price reaches entry
    if direction == "long":
        fill_idx_rel = np.argmax(l_1m_arr[i_fill:] <= entry) if (l_1m_arr[i_fill:] <= entry).any() else -1
    else:
        fill_idx_rel = np.argmax(h_1m_arr[i_fill:] >= entry) if (h_1m_arr[i_fill:] >= entry).any() else -1
    if fill_idx_rel == -1: return None  # no fill
    fill_idx = i_fill + int(fill_idx_rel)
    fill_ts = int(ts_1m[fill_idx])

    # End: fill + 7 days
    end_ts = fill_ts + MAX_HOLD_DAYS * 24 * 3600 * 1000
    i_end = int(np.searchsorted(ts_1m, end_ts, side="right"))

    # Post-fill window (1m)
    post_l = l_1m_arr[fill_idx:i_end]
    post_h = h_1m_arr[fill_idx:i_end]
    post_c = c_1m_arr[fill_idx:i_end]
    post_ts_arr = ts_1m[fill_idx:i_end]
    if len(post_l) == 0: return None

    # Cap and SL levels
    if direction == "long":
        cap_price = entry + R_CAP * risk
    else:
        cap_price = entry - R_CAP * risk

    # 1h checkpoints in [fill, end]
    fill_dt64 = np.datetime64(fill_ts, "ms").astype("datetime64[ns]")
    end_dt64 = np.datetime64(end_ts, "ms").astype("datetime64[ns]")
    cp_lo = int(np.searchsorted(ts_1h, fill_dt64, side="right"))
    cp_hi = int(np.searchsorted(ts_1h, end_dt64, side="right"))
    if cp_lo >= cp_hi: return None

    score_arr = sl_arr if direction == "long" else ss_arr
    max_R = 0.0
    consec_low = 0
    sl_idx = None
    cap_idx = None
    float_exit_R = None
    prev_post = 0

    for cp_idx in range(cp_lo, cp_hi):
        cp_ts = int(ts_1h[cp_idx].astype("int64") // 1_000_000)  # back to ms
        cur_post = int(np.searchsorted(post_ts_arr, cp_ts))

        if cur_post > prev_post:
            win_l = post_l[prev_post:cur_post]
            win_h = post_h[prev_post:cur_post]
            if direction == "long":
                if len(win_h) > 0:
                    mfe = (win_h.max() - entry) / risk
                    if mfe > max_R: max_R = mfe
                if (win_l <= sl).any():
                    sl_idx = prev_post + int(np.argmax(win_l <= sl)); break
                if (win_h >= cap_price).any():
                    cap_idx = prev_post + int(np.argmax(win_h >= cap_price)); break
            else:
                if len(win_l) > 0:
                    mfe = (entry - win_l.min()) / risk
                    if mfe > max_R: max_R = mfe
                if (win_h >= sl).any():
                    sl_idx = prev_post + int(np.argmax(win_h >= sl)); break
                if (win_l <= cap_price).any():
                    cap_idx = prev_post + int(np.argmax(win_l <= cap_price)); break
        prev_post = cur_post

        # Score check
        s = score_arr[cp_idx]
        if np.isnan(s): continue
        if s <= THRESHOLD: consec_low += 1
        else: consec_low = 0
        if consec_low >= CONFIRM:
            # Exit at close of THIS 1h bar
            exit_price = float(df_1h.iloc[cp_idx].close)
            if direction == "long":
                float_exit_R = (exit_price - entry) / risk
            else:
                float_exit_R = (entry - exit_price) / risk
            return float_exit_R, "score_exit", (cp_ts - fill_ts) / 3600000, max_R

    if sl_idx is not None:
        return -1.0, "sl_hit", (post_ts_arr[sl_idx] - fill_ts) / 3600000, max_R
    if cap_idx is not None:
        return R_CAP, "cap_hit", (post_ts_arr[cap_idx] - fill_ts) / 3600000, max_R
    # Max hold timeout: M2M
    if direction == "long":
        m2m_R = (post_c[-1] - entry) / risk
    else:
        m2m_R = (entry - post_c[-1]) / risk
    return m2m_R, "max_hold", (post_ts_arr[-1] - fill_ts) / 3600000, max_R


# ─── Load 4036 + apply per-type filter to get 387 ────────
print("\nLoading hma_all4036 data and filtering to 387 basket...")
df = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/hma_all4036.parquet")
print(f"All decisive: {len(df)}")

# Per-type best filters (from previous analysis)
BEST_FILTERS = {
    # LONG
    "T2":   ("long", "==", 3),
    "T1a":  ("long", "==", 4),
    "T5a":  ("long", "==", 4),
    "T4":   ("long", "==", 9),
    "T8":   ("long", "==", 8),
    "T3a":  ("long", "==", 1),
    "T7b":  ("long", "==", 3),
    "T1b":  ("long", "==", 4),
    "T7a":  ("long", "==", 5),
    # SHORT
    "T10":  ("short", "==", 3),
    "T11a": ("short", "==", 8),
    "T11b": ("short", ">=", 7),
    "T12":  ("short", "==", 4),
    "T14":  ("short", "==", 6),
    "T15a": ("short", "==", 4),
    "T15b": ("short", "==", 3),
    "T9a":  ("short", "==", 4),
    "T9b":  ("short", ">=", 6),
}

masks = []
for t_id, (dirn, op, k) in BEST_FILTERS.items():
    if op == "==":
        m = (df.t_id == t_id) & (df.direction == dirn) & (df.aligned_count == k)
    else:
        m = (df.t_id == t_id) & (df.direction == dirn) & (df.aligned_count >= k)
    masks.append(m)
basket = df[np.any(masks, axis=0)].copy()
print(f"Basket: {len(basket)}")
print(f"  LONG: {(basket.direction=='long').sum()}")
print(f"  SHORT: {(basket.direction=='short').sum()}")

# Need entry/SL — re-load from Phase 1.5
src = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")
g2h = src[src.htf == "2h"].copy()
g2h["has_15m"] = g2h.groupby(["direction","ob_cur_open_ms"])["ltf"].transform(lambda x: "15m" in set(x))
mask_lt = ((g2h.has_15m & (g2h.ltf=="15m")) | (~g2h.has_15m & (g2h.ltf=="20m")))
g2h = g2h[mask_lt].copy()

# Per (direction, born_ms) get entry/SL
setups_dict = {}
for (d, co), sub in g2h.groupby(["direction","ob_cur_open_ms"]):
    born = int(sub.iloc[0].born_ms)
    nc = len(sub)
    if d == "long":
        cf = sub.sort_values("fvg_zone_hi", ascending=False).iloc[0]
        drop_lo = float(cf.drop_lo)
        fvg_hi = float(cf.fvg_zone_hi); fvg_lo = float(cf.fvg_zone_lo)
        dp = 0.8 if nc >= 2 else 0.2
        entry = fvg_hi - dp * (fvg_hi - fvg_lo); sl = drop_lo
    else:
        cf = sub.sort_values("fvg_zone_lo", ascending=True).iloc[0]
        drop_hi = float(cf.drop_hi)
        fvg_hi = float(cf.fvg_zone_hi); fvg_lo = float(cf.fvg_zone_lo)
        dp = 0.8 if nc >= 2 else 0.2
        entry = fvg_lo + dp * (fvg_hi - fvg_lo); sl = drop_hi
    setups_dict[(d, born)] = (entry, sl)

# Apply Floating TP
print(f"\nSimulating Floating TP on {len(basket)} setups...")
results = []
for _, r in basket.iterrows():
    born = int(r.born_ms); d = r.direction
    key = (d, born)
    if key not in setups_dict: continue
    entry, sl = setups_dict[key]
    out = floating_tp(entry, sl, born, d)
    if out is None: continue
    R, reason, hold_h, max_R = out
    results.append({
        "born_ms": born, "direction": d, "t_id": r.t_id,
        "entry": entry, "sl": sl,
        "R": R, "exit_reason": reason, "hold_h": hold_h, "max_R": max_R,
    })

res = pd.DataFrame(results)
print(f"Trades executed: {len(res)}")

# ─── Report ──────────────────────────────────────────
print(f"\n{'='*100}")
print(f"FLOATING TP RESULTS — basket of 387 (per-type HMA filter, FULL 6y)")
print(f"{'='*100}")
total_R = res.R.sum()
n = len(res)
wr = (res.R > 0).mean() * 100
avg_R = res.R.mean()
med_R = res.R.median()
print(f"Total trades:  {n}")
print(f"Total R:       {total_R:+.1f}R")
print(f"WR (R>0):      {wr:.1f}%")
print(f"Avg R/trade:   {avg_R:+.3f}R")
print(f"Median R:      {med_R:+.3f}R")
print(f"Σ R per year:  {total_R/6.5:+.1f}R")

# Exit reason breakdown
print(f"\nExit reasons:")
for r, c in res.exit_reason.value_counts().items():
    sub_r = res[res.exit_reason == r]
    avg = sub_r.R.mean()
    print(f"  {r:<14} N={c:>4}  avg R={avg:+.3f}  ΣR={sub_r.R.sum():+.1f}")

# Per year breakdown
res["year"] = pd.to_datetime(res.born_ms, unit="ms", utc=True).dt.year
print(f"\n{'='*100}")
print(f"BREAKDOWN BY YEAR")
print(f"{'='*100}")
print(f"{'Year':<6} {'N':>4} {'WR':>6} {'ΣR':>8} {'avg':>8} {'med':>8}  exits")
for y, g in res.groupby("year"):
    wr_y = (g.R > 0).mean() * 100
    ex = g.exit_reason.value_counts().to_dict()
    print(f"{y:<6} {len(g):>4} {wr_y:>5.1f}% {g.R.sum():>+7.1f}R {g.R.mean():>+7.3f} {g.R.median():>+7.3f}  {ex}")

# Per direction × year
print(f"\n{'='*100}")
print(f"BY DIRECTION × YEAR")
print(f"{'='*100}")
for dirn in ["long", "short"]:
    sub_d = res[res.direction == dirn]
    print(f"\n{dirn.upper()}:")
    print(f"{'Year':<6} {'N':>4} {'WR':>6} {'ΣR':>8} {'avg':>8} {'med':>8}")
    for y, g in sub_d.groupby("year"):
        wr_y = (g.R > 0).mean() * 100
        print(f"{y:<6} {len(g):>4} {wr_y:>5.1f}% {g.R.sum():>+7.1f}R {g.R.mean():>+7.3f} {g.R.median():>+7.3f}")

# Per type
print(f"\n{'='*100}")
print(f"BY TYPE")
print(f"{'='*100}")
print(f"{'Type':<5} {'dir':<6} {'N':>4} {'WR':>6} {'ΣR':>8} {'avg':>8} {'med':>8}")
for (t, d), g in res.groupby(["t_id","direction"]):
    wr_t = (g.R > 0).mean() * 100
    print(f"{t:<5} {d:<6} {len(g):>4} {wr_t:>5.1f}% {g.R.sum():>+7.1f}R {g.R.mean():>+7.3f} {g.R.median():>+7.3f}")

# Save
res.to_parquet(pathlib.Path(__file__).parent.parent / "data/floating_tp_387.parquet")
print(f"\nSaved. Elapsed: {time.time()-t0:.1f}s")
