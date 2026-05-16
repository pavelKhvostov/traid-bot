"""etap_103: Algorithmic floating TP via momentum-score on Hull/MH/RSI/ASVK.

Дизайн (см. чат): каждый из 4 indicator → скалярный сигнал ∈ [-1, +1],
score = mean. Позиция LONG держится пока score(t) > 0; exit когда score ≤ 0
на 2 consecutive bars. SHORT mirror. Hard SL и max_hold=7d остаются.

Сравнение vs baseline (fixed RR=2.2) на 1.1.1 SWEPT setups, BTC/ETH/SOL 6y,
limit-fill entry, multi-shot без дедупа (как договорились).
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
import importlib.util as _ilu

_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    if _ROOT.parent == _ROOT:
        raise RuntimeError("repo root not found")
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df

_E98 = Path(__file__).parent / "etap_98_retry_after_sl_111.py"
_spec = _ilu.spec_from_file_location("etap98_core", _E98)
_e98 = _ilu.module_from_spec(_spec); _sys.modules["etap98_core"] = _e98
_spec.loader.exec_module(_e98)
detect_multi_signals = _e98.detect_multi_signals
check_swept = _e98.check_swept


# LIVE params
ENTRY_PCT = 0.80
SL_PCT = 0.35
RR_BASELINE = 2.2
MAX_HOLD_DAYS = 7
DAYS_BACK_TARGET = 2313
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
SCORE_THRESHOLD = 0.0  # exit when score ≤ 0 для LONG (= score ≥ 0 для SHORT)
CONFIRM_BARS = 2

# ============================================================
# Indicators (из etap_41, lookahead-safe — все на closed 1h bars)
# ============================================================

def wma_fast(arr, period):
    period = max(int(period), 1)
    weights = np.arange(1, period + 1, dtype=float)
    weights /= weights.sum()
    out = np.full_like(arr, np.nan, dtype=float)
    if len(arr) < period: return out
    valid = np.convolve(arr, weights[::-1], mode="valid")
    out[period - 1:] = valid
    return out


def hull_ma(close, length=78):
    arr = close.to_numpy(dtype=float)
    half = max(int(length / 2), 1)
    sqrt_len = max(int(round(np.sqrt(length))), 1)
    raw = 2.0 * wma_fast(arr, half) - wma_fast(arr, length)
    hull = wma_fast(np.where(np.isnan(raw), 0.0, raw), sqrt_len)
    hull[:length + sqrt_len] = np.nan
    return pd.Series(hull, index=close.index)


def hull_signal(close, length=78):
    """+1 если close[i] > hull[i-2], -1 если ниже, 0 если nan.
    Использует hull от 2 бар назад — lookahead-safe."""
    hull = hull_ma(close, length)
    out = np.zeros(len(close), dtype=float)
    arr_c = close.values; arr_h = hull.values
    for i in range(len(close)):
        if i < 2 or pd.isna(arr_h[i - 2]):
            out[i] = 0
        else:
            out[i] = 1.0 if arr_c[i] > arr_h[i - 2] else -1.0
    return pd.Series(out, index=close.index)


def mh_bw2(df):
    hlc3 = (df["high"] + df["low"] + df["close"]) / 3
    esa = hlc3.ewm(span=9, adjust=False).mean()
    d = (hlc3 - esa).abs().ewm(span=9, adjust=False).mean()
    ci = (hlc3 - esa) / (0.015 * d.replace(0, np.nan))
    wt1 = ci.ewm(span=12, adjust=False).mean()
    wt2 = wt1.rolling(4, min_periods=4).mean()
    sma14 = wt2.rolling(14, min_periods=14).mean()
    return wt2, sma14


def mh_signal(df):
    """green→+1, grey_from_green→+0.5, na→0, grey_from_red→-0.5, red→-1"""
    bw2, sma14 = mh_bw2(df)
    out = np.zeros(len(df), dtype=float)
    for i in range(len(df)):
        v = bw2.iloc[i]; s = sma14.iloc[i]
        if pd.isna(v) or pd.isna(s):
            out[i] = 0
        elif v > 0:
            out[i] = 1.0 if v >= s else 0.5
        elif v < 0:
            out[i] = -1.0 if v <= s else -0.5
        else:
            out[i] = 0
    return pd.Series(out, index=df.index)


def rsi_wilder(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0.0); loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def rsi_signal(close, period=14):
    """clip((rsi - 50) / 50, -1, +1)"""
    rsi = rsi_wilder(close, period)
    norm = ((rsi - 50.0) / 50.0).clip(-1, 1)
    return norm.fillna(0)


def asvk_adjusted_rsi(close):
    rsi = rsi_wilder(close, 14)
    ema_for_coef = rsi.ewm(span=5, adjust=False).mean()
    coef = pd.Series(np.where(rsi >= 50, 1.2, 0.8), index=rsi.index)
    coefficient = (rsi * coef) / ema_for_coef.replace(0, np.nan)
    adj = rsi * coefficient
    return adj.ewm(span=5, adjust=False).mean()


def asvk_dynamic_levels(ema_3, lookback=200):
    n = len(ema_3)
    above = np.full(n, np.nan); below = np.full(n, np.nan)
    arr = ema_3.to_numpy()
    for i in range(lookback - 1, n):
        win = arr[i - lookback + 1: i + 1]
        win = win[~np.isnan(win)]
        if len(win) < 10: continue
        m = win > 50; z = m.sum()
        if z > 0:
            y = win[m].mean()
            c1 = 100/y; c2 = 50/y; c3 = c1-c2
            c5 = (c3/lookback)*z + c3
            above[i] = c5 * y
        m = win < 50; z = m.sum()
        if z > 0:
            y = win[m].mean()
            c1 = 50/y; c2 = 1/y; c3 = c1-c2
            c5 = (c3/lookback)*z + c3
            below[i] = 100 - (c5 * y)
    return pd.Series(above, index=ema_3.index), pd.Series(below, index=ema_3.index)


def asvk_signal_direction_aware(close):
    """Возвращает (signal_long, signal_short) — по 1 серии:
       red zone = sustained move up: +1 LONG / -1 SHORT
       green zone = sustained move down: -1 LONG / +1 SHORT
       neutral = 0 для обоих.
    Это direction-aware: red-zone signal зависит от позиции.
    Для simplicity вернём raw zone label ∈ {-1, 0, +1} где +1 = red, -1 = green.
    Для LONG: use raw. Для SHORT: negate.
    """
    ema_3 = asvk_adjusted_rsi(close)
    above, below = asvk_dynamic_levels(ema_3, lookback=200)
    out = np.zeros(len(close), dtype=float)
    for i in range(len(close)):
        e = ema_3.iloc[i]; a = above.iloc[i]; b = below.iloc[i]
        if pd.isna(e) or pd.isna(a) or pd.isna(b):
            out[i] = 0
        elif e > a:
            out[i] = 1.0  # red (overbought)
        elif e < b:
            out[i] = -1.0  # green (oversold)
        else:
            out[i] = 0
    return pd.Series(out, index=close.index)


def build_score_series(df_1h):
    """Возвращает (s_long, s_short) — composite score для каждого 1h closed bar.
    s_long для LONG позиции, s_short для SHORT.
    Для всех индикаторов кроме ASVK: s_short = -s_long.
    Для ASVK: direction-aware (red zone = +1 для LONG-направления, -1 для SHORT).
    """
    s_hull = hull_signal(df_1h["close"])
    s_mh = mh_signal(df_1h)
    s_rsi = rsi_signal(df_1h["close"])
    s_asvk = asvk_signal_direction_aware(df_1h["close"])

    # composite, equal weight
    s_long = (s_hull + s_mh + s_rsi + s_asvk) / 4.0
    # для SHORT: hull/mh/rsi негируем, asvk тоже (because red-zone = bullish, anti-SHORT)
    s_short = -(s_hull + s_mh + s_rsi + s_asvk) / 4.0
    return s_long, s_short


# ============================================================
# Setup builder (LIVE params)
# ============================================================

def build_setup(sig):
    direction = sig["direction"]
    fb, ft = sig["fvg_zone"]
    obb, obt = sig["ob_htf_zone"]
    fw = ft - fb
    if direction == "LONG":
        entry = fb + ENTRY_PCT * fw
        sl = obb + SL_PCT * (fb - obb)
        if sl >= entry: return None
    else:
        entry = ft - ENTRY_PCT * fw
        sl = obt - SL_PCT * (obt - ft)
        if sl <= entry: return None
    return float(entry), float(sl)


# ============================================================
# Simulators
# ============================================================

def simulate_baseline(sig, df_1m, rr=RR_BASELINE):
    """Realistic limit-fill + fixed RR=2.2. Из etap_99 logic."""
    setup = build_setup(sig)
    if setup is None:
        return None
    entry, sl = setup
    direction = sig["direction"]
    risk = abs(entry - sl)
    if risk <= 0: return None
    tp = entry + rr*risk if direction == "LONG" else entry - rr*risk
    tf_min = 15 if sig["fvg_tf"] == "15m" else 20
    fill_start = sig["signal_time"] + pd.Timedelta(minutes=tf_min)
    forward = df_1m[df_1m.index >= fill_start]
    if forward.empty:
        return {"outcome": "nf", "R": 0.0, "exit_time": None, "hold_h": 0}
    h = forward["high"].values.astype(np.float64)
    l = forward["low"].values.astype(np.float64)
    ts = forward.index
    n = len(h)
    if direction == "LONG":
        ent_idxs = np.where(l <= entry)[0]
        tp_pre = np.where(h >= tp)[0]
    else:
        ent_idxs = np.where(h >= entry)[0]
        tp_pre = np.where(l <= tp)[0]
    ent_i = int(ent_idxs[0]) if ent_idxs.size else n + 1
    tp_pre_i = int(tp_pre[0]) if tp_pre.size else n + 1
    if tp_pre_i < ent_i:
        return {"outcome": "no_entry", "R": 0.0, "exit_time": None, "hold_h": 0}
    if ent_i >= n:
        return {"outcome": "nf", "R": 0.0, "exit_time": None, "hold_h": 0}
    activation = ts[ent_i]
    post_l = l[ent_i:]; post_h = h[ent_i:]; post_ts = ts[ent_i:]
    if direction == "LONG":
        sl_m = post_l <= sl; tp_m = post_h >= tp
    else:
        sl_m = post_h >= sl; tp_m = post_l <= tp
    sl_f = int(np.argmax(sl_m)) if sl_m.any() else -1
    tp_f = int(np.argmax(tp_m)) if tp_m.any() else -1
    if sl_f == -1 and tp_f == -1:
        return {"outcome": "open", "R": 0.0, "exit_time": None,
                 "hold_h": (post_ts[-1] - activation).total_seconds()/3600}
    if sl_f == -1:
        return {"outcome": "win", "R": rr, "exit_time": post_ts[tp_f],
                 "hold_h": (post_ts[tp_f] - activation).total_seconds()/3600}
    if tp_f == -1:
        return {"outcome": "loss", "R": -1.0, "exit_time": post_ts[sl_f],
                 "hold_h": (post_ts[sl_f] - activation).total_seconds()/3600}
    if tp_f < sl_f:
        return {"outcome": "win", "R": rr, "exit_time": post_ts[tp_f],
                 "hold_h": (post_ts[tp_f] - activation).total_seconds()/3600}
    return {"outcome": "loss", "R": -1.0, "exit_time": post_ts[sl_f],
             "hold_h": (post_ts[sl_f] - activation).total_seconds()/3600}


def simulate_floating(sig, df_1m, df_1h, score_long, score_short,
                       max_hold_days=MAX_HOLD_DAYS,
                       threshold=SCORE_THRESHOLD, confirm=CONFIRM_BARS):
    """Floating TP: hard SL + exit когда score ≤ threshold confirm_bars подряд.
    Honoring no_entry filter (TP_proxy = entry + RR_BASELINE × risk достигнут
    до entry → отмена, как в baseline — для apples-to-apples comparison).
    """
    setup = build_setup(sig)
    if setup is None: return None
    entry, sl = setup
    direction = sig["direction"]
    risk = abs(entry - sl)
    if risk <= 0: return None
    score_series = score_long if direction == "LONG" else score_short
    # tp_proxy used ONLY для no_entry check, не для exit
    tp_proxy = entry + RR_BASELINE * risk if direction == "LONG" else entry - RR_BASELINE * risk

    tf_min = 15 if sig["fvg_tf"] == "15m" else 20
    fill_start = sig["signal_time"] + pd.Timedelta(minutes=tf_min)
    forward = df_1m[df_1m.index >= fill_start]
    if forward.empty:
        return {"outcome": "nf", "R": 0.0, "exit_time": None,
                 "exit_reason": "no_data", "hold_h": 0, "max_R": 0}

    # waiting for limit fill, с no_entry проверкой (TP_proxy до entry)
    h = forward["high"].values.astype(np.float64)
    l = forward["low"].values.astype(np.float64)
    ts = forward.index
    n = len(h)
    if direction == "LONG":
        ent_idxs = np.where(l <= entry)[0]
        tp_pre = np.where(h >= tp_proxy)[0]
    else:
        ent_idxs = np.where(h >= entry)[0]
        tp_pre = np.where(l <= tp_proxy)[0]
    ent_i = int(ent_idxs[0]) if ent_idxs.size else n + 1
    tp_pre_i = int(tp_pre[0]) if tp_pre.size else n + 1
    if tp_pre_i < ent_i:
        return {"outcome": "no_entry", "R": 0.0, "exit_time": None,
                 "exit_reason": "tp_proxy_before_entry", "hold_h": 0, "max_R": 0}
    if ent_i >= n:
        return {"outcome": "nf", "R": 0.0, "exit_time": None,
                 "exit_reason": "no_fill", "hold_h": 0, "max_R": 0}
    activation = ts[ent_i]
    end_time = activation + pd.Timedelta(days=max_hold_days)
    et64 = np.datetime64(activation.tz_localize(None) if activation.tz else activation)
    ee64 = np.datetime64(end_time.tz_localize(None) if end_time.tz else end_time)
    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0:
        return {"outcome": "nf", "R": 0.0, "exit_time": None,
                 "exit_reason": "no_post_data", "hold_h": 0, "max_R": 0}
    post_h = df_1m["high"].values[i0:i1].astype(np.float64)
    post_l = df_1m["low"].values[i0:i1].astype(np.float64)
    post_c = df_1m["close"].values[i0:i1].astype(np.float64)
    post_ts = df_1m.index[i0:i1]

    # 1h checkpoints в окне [activation, end_time]
    h1_after = df_1h.index.searchsorted(activation, side="right")
    h1_end = df_1h.index.searchsorted(end_time, side="right")
    if h1_after >= h1_end:
        return {"outcome": "open", "R": 0.0, "exit_time": None,
                 "exit_reason": "no_1h_checkpoints", "hold_h": 0, "max_R": 0}
    checkpoints = df_1h.index[h1_after:h1_end]
    closes_1h = df_1h["close"].values

    # SL/floating exit walk
    consec_low_score = 0
    sl_exit_idx = None
    floating_exit_idx = None
    floating_exit_price = None
    floating_exit_time = None
    max_R = 0.0
    prev_post_idx = 0
    for cp in checkpoints:
        cp64 = np.datetime64(cp.tz_localize(None) if cp.tz else cp)
        cur_post_idx = np.searchsorted(post_ts.values, cp64)
        # SL check в window [prev_post_idx, cur_post_idx]
        if cur_post_idx > prev_post_idx:
            window_l = post_l[prev_post_idx:cur_post_idx]
            window_h = post_h[prev_post_idx:cur_post_idx]
            if direction == "LONG":
                # track max favorable
                mfe_idx = int(np.argmax(window_h)) + prev_post_idx
                max_R = max(max_R, (post_h[mfe_idx] - entry) / risk)
                if (window_l <= sl).any():
                    sl_exit_idx = prev_post_idx + int(np.argmax(window_l <= sl))
                    break
            else:
                mfe_idx = int(np.argmin(window_l)) + prev_post_idx
                max_R = max(max_R, (entry - post_l[mfe_idx]) / risk)
                if (window_h >= sl).any():
                    sl_exit_idx = prev_post_idx + int(np.argmax(window_h >= sl))
                    break
        prev_post_idx = cur_post_idx

        # score check на бaru ДО cp (последний закрытый 1h)
        score_idx = score_series.index.searchsorted(cp, side="right") - 1
        if score_idx < 0: continue
        s = score_series.iloc[score_idx]
        if pd.isna(s): continue
        if s <= threshold:
            consec_low_score += 1
        else:
            consec_low_score = 0
        if consec_low_score >= confirm:
            # exit at cp close price (1h close)
            cp_close_idx = df_1h.index.searchsorted(cp, side="right") - 2
            if cp_close_idx >= 0:
                floating_exit_price = float(closes_1h[cp_close_idx])
                floating_exit_time = cp
                break

    # finalize
    if sl_exit_idx is not None:
        return {"outcome": "loss", "R": -1.0,
                 "exit_time": post_ts[sl_exit_idx],
                 "exit_reason": "sl_hit",
                 "hold_h": (post_ts[sl_exit_idx] - activation).total_seconds()/3600,
                 "max_R": max_R}
    if floating_exit_price is not None:
        if direction == "LONG":
            R = (floating_exit_price - entry) / risk
        else:
            R = (entry - floating_exit_price) / risk
        return {"outcome": "win" if R > 0 else ("loss" if R < 0 else "flat"),
                 "R": float(R),
                 "exit_time": floating_exit_time,
                 "exit_reason": "score_exit",
                 "hold_h": (floating_exit_time - activation).total_seconds()/3600,
                 "max_R": max_R}
    # max hold reached без exit
    last_close = float(post_c[-1])
    if direction == "LONG":
        R = (last_close - entry) / risk
    else:
        R = (entry - last_close) / risk
    return {"outcome": "win" if R > 0 else ("loss" if R < 0 else "flat"),
             "R": float(R),
             "exit_time": post_ts[-1],
             "exit_reason": "max_hold",
             "hold_h": (post_ts[-1] - activation).total_seconds()/3600,
             "max_R": max_R}


# ============================================================
# Run experiment
# ============================================================

def run_signals(groups, df_1m, df_1h, df_2h, score_long, score_short):
    baseline_trades = []
    floating_trades = []
    for gid, gsigs in groups.items():
        gsigs_sorted = sorted(gsigs, key=lambda x: x["fvg_c2_time"])
        # Берём каждый сигнал зоны (multi-shot без дедупа, как договорились)
        for s in gsigs_sorted:
            if check_swept(s, df_1h, df_2h) is not True:
                continue
            r_base = simulate_baseline(s, df_1m)
            r_float = simulate_floating(s, df_1m, df_1h, score_long, score_short)
            if r_base is None or r_float is None:
                continue
            baseline_trades.append({**s, **r_base})
            floating_trades.append({**s, **r_float})
    return baseline_trades, floating_trades


def summarize(trades, label, rr_fixed=None):
    closed = [t for t in trades if t["outcome"] in ("win", "loss", "flat")]
    W = sum(1 for t in closed if t["R"] > 0)
    L = sum(1 for t in closed if t["R"] < 0)
    flat = sum(1 for t in closed if t["R"] == 0)
    n = W + L + flat
    wr = (W / n * 100) if n else 0.0
    pnl = sum(t["R"] for t in closed)
    r_per = pnl / n if n else 0
    holds = [t["hold_h"] for t in closed if t.get("hold_h", 0) > 0]
    avg_hold = np.mean(holds) if holds else 0
    yearly = defaultdict(lambda: [0, 0, 0.0])
    for t in closed:
        y = pd.Timestamp(t["signal_time"]).year
        if t["R"] > 0: yearly[y][0] += 1
        elif t["R"] < 0: yearly[y][1] += 1
        yearly[y][2] += t["R"]
    bad = sum(1 for y in yearly if yearly[y][2] < 0)
    print(f"  {label:<30}: n={n:3d} W={W:3d} L={L:3d} flat={flat:2d}  "
          f"WR={wr:5.1f}%  PnL={pnl:+7.1f}R  R/tr={r_per:+.3f}  "
          f"avg_hold={avg_hold:.1f}h  bad_yrs={bad}/{len(yearly)}")
    return {"n": n, "W": W, "L": L, "wr": wr, "pnl": pnl, "r_per": r_per,
             "bad": bad, "yearly": dict(yearly), "avg_hold": avg_hold,
             "trades": trades}


def run_symbol(symbol):
    print(f"\n{'#'*72}\n#  {symbol}\n{'#'*72}")
    df_1d = load_df(symbol, "1d")
    df_4h = load_df(symbol, "4h")
    df_1h = load_df(symbol, "1h")
    df_15m = load_df(symbol, "15m")
    df_1m = load_df(symbol, "1m")
    if any(df.empty for df in (df_1d, df_4h, df_1h, df_15m, df_1m)):
        return None
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_20m = compose_from_base(df_1m, "20m")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = max(today - pd.Timedelta(days=DAYS_BACK_TARGET), df_1m.index[0])
    actual_days = (today-cutoff).days
    print(f"  cutoff: {cutoff.date()} ({actual_days}d = {actual_days/365:.2f}y)")
    df_1d_f = df_1d[df_1d.index >= cutoff]
    df_12h_f = df_12h[df_12h.index >= cutoff]

    print("  computing indicators on 1h...")
    score_long, score_short = build_score_series(df_1h)

    groups = detect_multi_signals(df_1d_f, df_12h_f, df_4h, df_6h,
                                    df_1h, df_2h, df_15m, df_20m)
    print(f"  zones={len(groups)}, total signals={sum(len(g) for g in groups.values())}")

    baseline, floating = run_signals(groups, df_1m, df_1h, df_2h,
                                       score_long, score_short)
    print()
    bs = summarize(baseline, "BASELINE (fixed RR=2.2)", rr_fixed=RR_BASELINE)
    fs = summarize(floating, "FLOATING (momentum exit)")

    # Distribution analysis
    closed_float = [t for t in floating if t["outcome"] in ("win", "loss", "flat")]
    if closed_float:
        Rs = sorted([t["R"] for t in closed_float])
        max_R = max(Rs)
        wins_R = [r for r in Rs if r > 0]
        avg_win_R = np.mean(wins_R) if wins_R else 0
        # avg max_R during hold (MFE)
        mfes = [t.get("max_R", 0) for t in closed_float]
        avg_mfe = np.mean(mfes) if mfes else 0
        print(f"\n  Floating distribution:")
        print(f"    Max R single trade: {max_R:+.2f}")
        print(f"    Avg win R: {avg_win_R:+.2f}")
        print(f"    Avg MFE during hold: {avg_mfe:+.2f}")

        # Exit reasons
        reasons = defaultdict(int)
        for t in floating:
            r = t.get("exit_reason", "unknown")
            reasons[r] += 1
        print(f"    Exit reasons: {dict(reasons)}")

    return {"symbol": symbol, "years": actual_days/365,
             "baseline": bs, "floating": fs}


def main():
    print(f"etap_103: Algorithmic Floating TP via Hull/MH/RSI/ASVK momentum score")
    print(f"params: entry={ENTRY_PCT}, sl={SL_PCT} sym, threshold={SCORE_THRESHOLD}, "
          f"confirm={CONFIRM_BARS} bars, max_hold={MAX_HOLD_DAYS}d")
    print(f"Baseline: fixed RR={RR_BASELINE}, limit-fill, multi-shot no dedup")
    results = []
    for sym in SYMBOLS:
        r = run_symbol(sym)
        if r is not None:
            results.append(r)

    print()
    print("=" * 96)
    print("FINAL: floating TP vs baseline RR=2.2")
    print("=" * 96)
    print(f"{'sym':<8} {'years':>5} {'mode':<10} {'n':>4} {'WR':>6} {'PnL':>9} "
          f"{'R/t':>7} {'hold':>7} {'bad':>4}")
    print("-" * 80)
    total_b = 0; total_f = 0; total_bn = 0; total_fn = 0
    for r in results:
        b = r["baseline"]; f = r["floating"]
        print(f"{r['symbol']:<8} {r['years']:>5.2f} {'baseline':<10} "
              f"{b['n']:>4d} {b['wr']:>5.1f}% {b['pnl']:>+8.1f}R "
              f"{b['r_per']:>+6.3f} {b['avg_hold']:>5.1f}h {b['bad']:>4d}")
        print(f"{'':<8} {'':>5} {'floating':<10} "
              f"{f['n']:>4d} {f['wr']:>5.1f}% {f['pnl']:>+8.1f}R "
              f"{f['r_per']:>+6.3f} {f['avg_hold']:>5.1f}h {f['bad']:>4d}")
        print(f"{'':<8} {'':>5} {'  delta':<10} "
              f"{f['n']-b['n']:>+4d} {f['wr']-b['wr']:>+5.1f}pp "
              f"{f['pnl']-b['pnl']:>+8.1f}R {f['r_per']-b['r_per']:>+6.3f}")
        print()
        total_b += b['pnl']; total_f += f['pnl']
        total_bn += b['n']; total_fn += f['n']
    print("-" * 80)
    print(f"TOTAL:  baseline n={total_bn} PnL={total_b:+.1f}R")
    print(f"        floating n={total_fn} PnL={total_f:+.1f}R")
    print(f"        delta {total_f-total_b:+.1f}R ({(total_f-total_b)/total_b*100 if total_b else 0:+.1f}%)")


if __name__ == "__main__":
    main()
