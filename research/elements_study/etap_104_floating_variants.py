"""etap_104: 6 вариантов автоследования + анализ распределения R.

Цель: не fat-tail. Метрики:
  - Total PnL
  - WR
  - Max R single trade (low = good)
  - Top-5 contribution % (low = good, threshold ≤ 30%)
  - Median R per trade (positive = good)
  - Avg loss

Все варианты применяются к одним и тем же 1.1.1 SWEPT signals (BTC 6.34y).
Лучшие 2-3 потом проверяются на ETH/SOL.
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

_E103 = Path(__file__).parent / "etap_103_floating_tp.py"
_spec3 = _ilu.spec_from_file_location("etap103_core", _E103)
_e103 = _ilu.module_from_spec(_spec3); _sys.modules["etap103_core"] = _e103
_spec3.loader.exec_module(_e103)
build_setup = _e103.build_setup
build_score_series = _e103.build_score_series

ENTRY_PCT = 0.80
SL_PCT = 0.35
RR_BASELINE = 2.2
MAX_HOLD_DAYS = 7
DAYS_BACK_TARGET = 2313


def compute_atr_1h(df_1h, period=14):
    high = df_1h["high"]; low = df_1h["low"]; pc = df_1h["close"].shift(1)
    tr = pd.concat([(high-low), (high-pc).abs(), (low-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def find_entry_fill(sig, df_1m, entry, direction):
    """Возвращает (activation_idx, activation_time, no_entry_or_nf_reason).
    Включает no_entry filter (TP_proxy = entry + RR_BASELINE × risk до entry)."""
    risk = abs(entry - sig.get("_sl", 0))
    tf_min = 15 if sig["fvg_tf"] == "15m" else 20
    fill_start = sig["signal_time"] + pd.Timedelta(minutes=tf_min)
    forward = df_1m[df_1m.index >= fill_start]
    if forward.empty:
        return None, None, "no_data"
    h = forward["high"].values.astype(np.float64)
    l = forward["low"].values.astype(np.float64)
    ts = forward.index
    n = len(h)
    # no_entry check
    tp_proxy = entry + RR_BASELINE * risk if direction == "LONG" else entry - RR_BASELINE * risk
    if direction == "LONG":
        ent_idxs = np.where(l <= entry)[0]
        tp_pre = np.where(h >= tp_proxy)[0]
    else:
        ent_idxs = np.where(h >= entry)[0]
        tp_pre = np.where(l <= tp_proxy)[0]
    ent_i = int(ent_idxs[0]) if ent_idxs.size else n + 1
    tp_pre_i = int(tp_pre[0]) if tp_pre.size else n + 1
    if tp_pre_i < ent_i:
        return None, None, "no_entry"
    if ent_i >= n:
        return None, None, "nf"
    return ent_i, ts[ent_i], None


def _walk_to_end(df_1m, activation_time, max_hold_days):
    end_time = activation_time + pd.Timedelta(days=max_hold_days)
    et64 = np.datetime64(activation_time.tz_localize(None) if activation_time.tz else activation_time)
    ee64 = np.datetime64(end_time.tz_localize(None) if end_time.tz else end_time)
    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0:
        return None
    post_h = df_1m["high"].values[i0:i1].astype(np.float64)
    post_l = df_1m["low"].values[i0:i1].astype(np.float64)
    post_c = df_1m["close"].values[i0:i1].astype(np.float64)
    post_ts = df_1m.index[i0:i1]
    return post_h, post_l, post_c, post_ts, end_time


# ============================================================
# Variant A: score-exit (baseline floating из etap_103)
# ============================================================
def variant_score(sig, df_1m, df_1h, score_long, score_short,
                   threshold=0.0, confirm=2):
    setup = build_setup(sig)
    if setup is None: return None
    entry, sl = setup
    sig["_sl"] = sl
    direction = sig["direction"]
    risk = abs(entry - sl)
    if risk <= 0: return None
    ent_i, activation, err = find_entry_fill(sig, df_1m, entry, direction)
    if err is not None:
        return {"outcome": "skip", "R": 0.0, "exit_reason": err, "hold_h": 0, "max_R": 0}
    score_series = score_long if direction == "LONG" else score_short
    walk = _walk_to_end(df_1m, activation, MAX_HOLD_DAYS)
    if walk is None:
        return {"outcome": "skip", "R": 0.0, "exit_reason": "no_data", "hold_h": 0, "max_R": 0}
    post_h, post_l, post_c, post_ts, end_time = walk

    h1_after = df_1h.index.searchsorted(activation, side="right")
    h1_end = df_1h.index.searchsorted(end_time, side="right")
    if h1_after >= h1_end:
        return {"outcome": "open", "R": 0.0, "exit_reason": "no_cps", "hold_h": 0, "max_R": 0}
    checkpoints = df_1h.index[h1_after:h1_end]
    closes_1h = df_1h["close"].values

    consec = 0
    sl_exit_idx = None
    floating_price = None; floating_time = None
    max_R = 0.0
    prev_post_idx = 0
    for cp in checkpoints:
        cp64 = np.datetime64(cp.tz_localize(None) if cp.tz else cp)
        cur_post_idx = np.searchsorted(post_ts.values, cp64)
        if cur_post_idx > prev_post_idx:
            w_l = post_l[prev_post_idx:cur_post_idx]
            w_h = post_h[prev_post_idx:cur_post_idx]
            if direction == "LONG":
                max_R = max(max_R, (max(w_h) - entry) / risk)
                if (w_l <= sl).any():
                    sl_exit_idx = prev_post_idx + int(np.argmax(w_l <= sl))
                    break
            else:
                max_R = max(max_R, (entry - min(w_l)) / risk)
                if (w_h >= sl).any():
                    sl_exit_idx = prev_post_idx + int(np.argmax(w_h >= sl))
                    break
        prev_post_idx = cur_post_idx
        score_idx = score_series.index.searchsorted(cp, side="right") - 1
        if score_idx < 0: continue
        s = score_series.iloc[score_idx]
        if pd.isna(s): continue
        if s <= threshold: consec += 1
        else: consec = 0
        if consec >= confirm:
            cp_close_idx = df_1h.index.searchsorted(cp, side="right") - 2
            if cp_close_idx >= 0:
                floating_price = float(closes_1h[cp_close_idx])
                floating_time = cp
                break

    return _finalize(direction, entry, sl, risk, sl_exit_idx, post_ts, post_c,
                      activation, floating_price, floating_time, max_R,
                      exit_reason_for_score="score_exit")


def _finalize(direction, entry, sl, risk, sl_exit_idx, post_ts, post_c,
                activation, floating_price, floating_time, max_R,
                exit_reason_for_score):
    if sl_exit_idx is not None:
        return {"outcome": "loss", "R": -1.0,
                "exit_time": post_ts[sl_exit_idx],
                "exit_reason": "sl_hit",
                "hold_h": (post_ts[sl_exit_idx] - activation).total_seconds()/3600,
                "max_R": max_R}
    if floating_price is not None:
        if direction == "LONG":
            R = (floating_price - entry) / risk
        else:
            R = (entry - floating_price) / risk
        outc = "win" if R > 0 else ("loss" if R < 0 else "flat")
        return {"outcome": outc, "R": float(R),
                "exit_time": floating_time,
                "exit_reason": exit_reason_for_score,
                "hold_h": (floating_time - activation).total_seconds()/3600,
                "max_R": max_R}
    last_close = float(post_c[-1])
    R = (last_close - entry) / risk if direction == "LONG" else (entry - last_close) / risk
    outc = "win" if R > 0 else ("loss" if R < 0 else "flat")
    return {"outcome": outc, "R": float(R),
            "exit_time": post_ts[-1], "exit_reason": "max_hold",
            "hold_h": (post_ts[-1] - activation).total_seconds()/3600,
            "max_R": max_R}


# ============================================================
# Variant B: ATR trail
# ============================================================
def variant_atr_trail(sig, df_1m, df_1h, atr_1h, K=2.0):
    setup = build_setup(sig)
    if setup is None: return None
    entry, sl = setup
    sig["_sl"] = sl
    direction = sig["direction"]
    risk = abs(entry - sl)
    if risk <= 0: return None
    ent_i, activation, err = find_entry_fill(sig, df_1m, entry, direction)
    if err is not None:
        return {"outcome": "skip", "R": 0.0, "exit_reason": err, "hold_h": 0, "max_R": 0}
    # ATR от bar's last close ≤ activation
    atr_idx = atr_1h.index.searchsorted(activation, side="right") - 1
    if atr_idx < 0 or pd.isna(atr_1h.iloc[atr_idx]):
        return {"outcome": "skip", "R": 0.0, "exit_reason": "no_atr", "hold_h": 0, "max_R": 0}
    atr_value = float(atr_1h.iloc[atr_idx])
    if atr_value <= 0:
        return {"outcome": "skip", "R": 0.0, "exit_reason": "bad_atr", "hold_h": 0, "max_R": 0}

    walk = _walk_to_end(df_1m, activation, MAX_HOLD_DAYS)
    if walk is None:
        return {"outcome": "skip", "R": 0.0, "exit_reason": "no_data", "hold_h": 0, "max_R": 0}
    post_h, post_l, post_c, post_ts, end_time = walk

    trail_offset = K * atr_value
    # MFE-based trail
    if direction == "LONG":
        mfe = entry
        for i in range(len(post_h)):
            mfe = max(mfe, post_h[i])
            trail_price = mfe - trail_offset
            if post_l[i] <= sl:
                return _make_loss(entry, sl, risk, post_ts[i], activation, mfe, "sl_hit", direction)
            if post_l[i] <= trail_price and i > 0:  # don't exit on entry bar
                exit_price = trail_price
                R = (exit_price - entry) / risk
                return _make_result(R, post_ts[i], activation, mfe, "atr_trail", entry, risk, direction)
        # max_hold
        max_R = (mfe - entry) / risk
        return _make_close_at_end(direction, entry, risk, post_c[-1], post_ts[-1], activation, max_R)
    else:
        mfe = entry
        for i in range(len(post_l)):
            mfe = min(mfe, post_l[i])
            trail_price = mfe + trail_offset
            if post_h[i] >= sl:
                return _make_loss(entry, sl, risk, post_ts[i], activation, mfe, "sl_hit", direction)
            if post_h[i] >= trail_price and i > 0:
                exit_price = trail_price
                R = (entry - exit_price) / risk
                return _make_result(R, post_ts[i], activation, mfe, "atr_trail", entry, risk, direction)
        max_R = (entry - mfe) / risk
        return _make_close_at_end(direction, entry, risk, post_c[-1], post_ts[-1], activation, max_R)


def _make_loss(entry, sl, risk, exit_t, activation, mfe, reason, direction):
    max_R = (mfe - entry) / risk if direction == "LONG" else (entry - mfe) / risk
    return {"outcome": "loss", "R": -1.0, "exit_time": exit_t,
            "exit_reason": reason,
            "hold_h": (exit_t - activation).total_seconds()/3600, "max_R": max_R}


def _make_result(R, exit_t, activation, mfe, reason, entry, risk, direction):
    max_R = (mfe - entry) / risk if direction == "LONG" else (entry - mfe) / risk
    outc = "win" if R > 0 else ("loss" if R < 0 else "flat")
    return {"outcome": outc, "R": float(R), "exit_time": exit_t,
            "exit_reason": reason,
            "hold_h": (exit_t - activation).total_seconds()/3600, "max_R": max_R}


def _make_close_at_end(direction, entry, risk, close, exit_t, activation, max_R):
    R = (close - entry)/risk if direction == "LONG" else (entry - close)/risk
    outc = "win" if R > 0 else ("loss" if R < 0 else "flat")
    return {"outcome": outc, "R": float(R), "exit_time": exit_t,
            "exit_reason": "max_hold",
            "hold_h": (exit_t - activation).total_seconds()/3600, "max_R": max_R}


# ============================================================
# Variant C: MFE retrace %
# ============================================================
def variant_mfe_retrace(sig, df_1m, df_1h, retrace_pct=0.33, min_mfe_R=0.5):
    setup = build_setup(sig)
    if setup is None: return None
    entry, sl = setup
    sig["_sl"] = sl
    direction = sig["direction"]
    risk = abs(entry - sl)
    if risk <= 0: return None
    ent_i, activation, err = find_entry_fill(sig, df_1m, entry, direction)
    if err is not None:
        return {"outcome": "skip", "R": 0.0, "exit_reason": err, "hold_h": 0, "max_R": 0}
    walk = _walk_to_end(df_1m, activation, MAX_HOLD_DAYS)
    if walk is None:
        return {"outcome": "skip", "R": 0.0, "exit_reason": "no_data", "hold_h": 0, "max_R": 0}
    post_h, post_l, post_c, post_ts, end_time = walk

    if direction == "LONG":
        mfe_price = entry
        for i in range(len(post_h)):
            mfe_price = max(mfe_price, post_h[i])
            mfe_R = (mfe_price - entry) / risk
            if post_l[i] <= sl:
                return _make_loss(entry, sl, risk, post_ts[i], activation, mfe_price, "sl_hit", direction)
            if mfe_R >= min_mfe_R:
                trail_R = mfe_R * (1 - retrace_pct)
                trail_price = entry + trail_R * risk
                if post_l[i] <= trail_price and i > 0:
                    R = (trail_price - entry) / risk
                    return _make_result(R, post_ts[i], activation, mfe_price, "mfe_retrace", entry, risk, direction)
        max_R = (mfe_price - entry) / risk
        return _make_close_at_end(direction, entry, risk, post_c[-1], post_ts[-1], activation, max_R)
    else:
        mfe_price = entry
        for i in range(len(post_l)):
            mfe_price = min(mfe_price, post_l[i])
            mfe_R = (entry - mfe_price) / risk
            if post_h[i] >= sl:
                return _make_loss(entry, sl, risk, post_ts[i], activation, mfe_price, "sl_hit", direction)
            if mfe_R >= min_mfe_R:
                trail_R = mfe_R * (1 - retrace_pct)
                trail_price = entry - trail_R * risk
                if post_h[i] >= trail_price and i > 0:
                    R = (entry - trail_price) / risk
                    return _make_result(R, post_ts[i], activation, mfe_price, "mfe_retrace", entry, risk, direction)
        max_R = (entry - mfe_price) / risk
        return _make_close_at_end(direction, entry, risk, post_c[-1], post_ts[-1], activation, max_R)


# ============================================================
# Variant D: R-cap + score exit
# ============================================================
def variant_rcap_score(sig, df_1m, df_1h, score_long, score_short,
                        R_cap=3.0, threshold=0.0, confirm=2):
    setup = build_setup(sig)
    if setup is None: return None
    entry, sl = setup
    sig["_sl"] = sl
    direction = sig["direction"]
    risk = abs(entry - sl)
    if risk <= 0: return None
    tp_cap = entry + R_cap * risk if direction == "LONG" else entry - R_cap * risk
    ent_i, activation, err = find_entry_fill(sig, df_1m, entry, direction)
    if err is not None:
        return {"outcome": "skip", "R": 0.0, "exit_reason": err, "hold_h": 0, "max_R": 0}
    score_series = score_long if direction == "LONG" else score_short
    walk = _walk_to_end(df_1m, activation, MAX_HOLD_DAYS)
    if walk is None:
        return {"outcome": "skip", "R": 0.0, "exit_reason": "no_data", "hold_h": 0, "max_R": 0}
    post_h, post_l, post_c, post_ts, end_time = walk

    h1_after = df_1h.index.searchsorted(activation, side="right")
    h1_end = df_1h.index.searchsorted(end_time, side="right")
    checkpoints = df_1h.index[h1_after:h1_end]
    closes_1h = df_1h["close"].values

    consec = 0
    sl_exit_idx = None; cap_hit_idx = None
    floating_price = None; floating_time = None
    max_R = 0.0
    prev_post_idx = 0
    for cp in checkpoints:
        cp64 = np.datetime64(cp.tz_localize(None) if cp.tz else cp)
        cur_post_idx = np.searchsorted(post_ts.values, cp64)
        if cur_post_idx > prev_post_idx:
            w_l = post_l[prev_post_idx:cur_post_idx]
            w_h = post_h[prev_post_idx:cur_post_idx]
            # Bug fix: SL и TP_cap могут оба сработать в одном hour-window
            # (60 1m-баров). Раньше всегда брали SL — bias to losses.
            # Теперь сравниваем first-hit indices, выбираем earlier.
            if direction == "LONG":
                max_R = max(max_R, (max(w_h) - entry) / risk)
                sl_mask = w_l <= sl
                tp_mask = w_h >= tp_cap
            else:
                max_R = max(max_R, (entry - min(w_l)) / risk)
                sl_mask = w_h >= sl
                tp_mask = w_l <= tp_cap
            sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
            tp_first = int(np.argmax(tp_mask)) if tp_mask.any() else -1
            if sl_first >= 0 and tp_first >= 0:
                if sl_first <= tp_first:
                    sl_exit_idx = prev_post_idx + sl_first; break
                else:
                    cap_hit_idx = prev_post_idx + tp_first; break
            elif sl_first >= 0:
                sl_exit_idx = prev_post_idx + sl_first; break
            elif tp_first >= 0:
                cap_hit_idx = prev_post_idx + tp_first; break
        prev_post_idx = cur_post_idx
        score_idx = score_series.index.searchsorted(cp, side="right") - 1
        if score_idx < 0: continue
        s = score_series.iloc[score_idx]
        if pd.isna(s): continue
        if s <= threshold: consec += 1
        else: consec = 0
        if consec >= confirm:
            cp_close_idx = df_1h.index.searchsorted(cp, side="right") - 2
            if cp_close_idx >= 0:
                floating_price = float(closes_1h[cp_close_idx])
                floating_time = cp
                break

    if cap_hit_idx is not None:
        return {"outcome": "win", "R": R_cap,
                "exit_time": post_ts[cap_hit_idx], "exit_reason": "R_cap",
                "hold_h": (post_ts[cap_hit_idx] - activation).total_seconds()/3600,
                "max_R": max_R}
    return _finalize(direction, entry, sl, risk, sl_exit_idx, post_ts, post_c,
                      activation, floating_price, floating_time, max_R,
                      exit_reason_for_score="score_exit")


# ============================================================
# Variant E: BE-ratchet
# ============================================================
def variant_be_ratchet(sig, df_1m, df_1h, step_R=1.0):
    setup = build_setup(sig)
    if setup is None: return None
    entry, sl = setup
    sig["_sl"] = sl
    direction = sig["direction"]
    risk = abs(entry - sl)
    if risk <= 0: return None
    ent_i, activation, err = find_entry_fill(sig, df_1m, entry, direction)
    if err is not None:
        return {"outcome": "skip", "R": 0.0, "exit_reason": err, "hold_h": 0, "max_R": 0}
    walk = _walk_to_end(df_1m, activation, MAX_HOLD_DAYS)
    if walk is None:
        return {"outcome": "skip", "R": 0.0, "exit_reason": "no_data", "hold_h": 0, "max_R": 0}
    post_h, post_l, post_c, post_ts, end_time = walk

    current_sl = sl
    achieved_R_step = -1  # ladder: 0 = BE (after +1R), 1 = +1R (after +2R), ...
    if direction == "LONG":
        mfe_price = entry
        for i in range(len(post_h)):
            mfe_price = max(mfe_price, post_h[i])
            mfe_R = (mfe_price - entry) / risk
            new_step = int(mfe_R // step_R) - 1  # +1R MFE → step 0 = BE
            if new_step > achieved_R_step:
                achieved_R_step = new_step
                if achieved_R_step == 0:
                    current_sl = entry
                else:
                    current_sl = entry + achieved_R_step * step_R * risk
            if post_l[i] <= current_sl and i > 0:
                exit_price = current_sl
                R = (exit_price - entry) / risk
                outc = "win" if R > 0 else ("loss" if R < 0 else "flat")
                return {"outcome": outc, "R": float(R),
                        "exit_time": post_ts[i], "exit_reason": "be_ratchet",
                        "hold_h": (post_ts[i] - activation).total_seconds()/3600,
                        "max_R": (mfe_price - entry) / risk}
        max_R = (mfe_price - entry) / risk
        return _make_close_at_end(direction, entry, risk, post_c[-1], post_ts[-1], activation, max_R)
    else:
        mfe_price = entry
        for i in range(len(post_l)):
            mfe_price = min(mfe_price, post_l[i])
            mfe_R = (entry - mfe_price) / risk
            new_step = int(mfe_R // step_R) - 1
            if new_step > achieved_R_step:
                achieved_R_step = new_step
                if achieved_R_step == 0:
                    current_sl = entry
                else:
                    current_sl = entry - achieved_R_step * step_R * risk
            if post_h[i] >= current_sl and i > 0:
                exit_price = current_sl
                R = (entry - exit_price) / risk
                outc = "win" if R > 0 else ("loss" if R < 0 else "flat")
                return {"outcome": outc, "R": float(R),
                        "exit_time": post_ts[i], "exit_reason": "be_ratchet",
                        "hold_h": (post_ts[i] - activation).total_seconds()/3600,
                        "max_R": (entry - mfe_price) / risk}
        max_R = (entry - mfe_price) / risk
        return _make_close_at_end(direction, entry, risk, post_c[-1], post_ts[-1], activation, max_R)


# ============================================================
# Variant F: Time-decay score (threshold rises linearly)
# ============================================================
def variant_time_decay_score(sig, df_1m, df_1h, score_long, score_short,
                              start_threshold=-0.5, end_threshold=+0.5,
                              confirm=2):
    setup = build_setup(sig)
    if setup is None: return None
    entry, sl = setup
    sig["_sl"] = sl
    direction = sig["direction"]
    risk = abs(entry - sl)
    if risk <= 0: return None
    ent_i, activation, err = find_entry_fill(sig, df_1m, entry, direction)
    if err is not None:
        return {"outcome": "skip", "R": 0.0, "exit_reason": err, "hold_h": 0, "max_R": 0}
    score_series = score_long if direction == "LONG" else score_short
    walk = _walk_to_end(df_1m, activation, MAX_HOLD_DAYS)
    if walk is None:
        return {"outcome": "skip", "R": 0.0, "exit_reason": "no_data", "hold_h": 0, "max_R": 0}
    post_h, post_l, post_c, post_ts, end_time = walk

    h1_after = df_1h.index.searchsorted(activation, side="right")
    h1_end = df_1h.index.searchsorted(end_time, side="right")
    checkpoints = df_1h.index[h1_after:h1_end]
    closes_1h = df_1h["close"].values
    total_hours = MAX_HOLD_DAYS * 24

    consec = 0
    sl_exit_idx = None
    floating_price = None; floating_time = None
    max_R = 0.0
    prev_post_idx = 0
    for cp in checkpoints:
        elapsed_h = (cp - activation).total_seconds() / 3600
        t = min(elapsed_h / total_hours, 1.0)
        threshold = start_threshold + (end_threshold - start_threshold) * t
        cp64 = np.datetime64(cp.tz_localize(None) if cp.tz else cp)
        cur_post_idx = np.searchsorted(post_ts.values, cp64)
        if cur_post_idx > prev_post_idx:
            w_l = post_l[prev_post_idx:cur_post_idx]
            w_h = post_h[prev_post_idx:cur_post_idx]
            if direction == "LONG":
                max_R = max(max_R, (max(w_h) - entry) / risk)
                if (w_l <= sl).any():
                    sl_exit_idx = prev_post_idx + int(np.argmax(w_l <= sl)); break
            else:
                max_R = max(max_R, (entry - min(w_l)) / risk)
                if (w_h >= sl).any():
                    sl_exit_idx = prev_post_idx + int(np.argmax(w_h >= sl)); break
        prev_post_idx = cur_post_idx
        score_idx = score_series.index.searchsorted(cp, side="right") - 1
        if score_idx < 0: continue
        s = score_series.iloc[score_idx]
        if pd.isna(s): continue
        if s <= threshold: consec += 1
        else: consec = 0
        if consec >= confirm:
            cp_close_idx = df_1h.index.searchsorted(cp, side="right") - 2
            if cp_close_idx >= 0:
                floating_price = float(closes_1h[cp_close_idx])
                floating_time = cp
                break

    return _finalize(direction, entry, sl, risk, sl_exit_idx, post_ts, post_c,
                      activation, floating_price, floating_time, max_R,
                      exit_reason_for_score="time_decay_score")


# ============================================================
# Baseline RR=2.2 fixed
# ============================================================
def variant_baseline_rr(sig, df_1m, rr=RR_BASELINE):
    setup = build_setup(sig)
    if setup is None: return None
    entry, sl = setup
    sig["_sl"] = sl
    direction = sig["direction"]
    risk = abs(entry - sl)
    if risk <= 0: return None
    tp = entry + rr*risk if direction == "LONG" else entry - rr*risk
    ent_i, activation, err = find_entry_fill(sig, df_1m, entry, direction)
    if err is not None:
        return {"outcome": "skip", "R": 0.0, "exit_reason": err, "hold_h": 0, "max_R": 0}
    walk = _walk_to_end(df_1m, activation, MAX_HOLD_DAYS)
    if walk is None:
        return {"outcome": "skip", "R": 0.0, "exit_reason": "no_data", "hold_h": 0, "max_R": 0}
    post_h, post_l, post_c, post_ts, end_time = walk

    if direction == "LONG":
        sl_m = post_l <= sl; tp_m = post_h >= tp
        mfe = max(post_h)
        max_R = (mfe - entry) / risk
    else:
        sl_m = post_h >= sl; tp_m = post_l <= tp
        mfe = min(post_l)
        max_R = (entry - mfe) / risk

    sl_f = int(np.argmax(sl_m)) if sl_m.any() else -1
    tp_f = int(np.argmax(tp_m)) if tp_m.any() else -1
    if sl_f == -1 and tp_f == -1:
        R = (post_c[-1] - entry) / risk if direction == "LONG" else (entry - post_c[-1]) / risk
        outc = "win" if R > 0 else ("loss" if R < 0 else "flat")
        return {"outcome": outc, "R": float(R), "exit_time": post_ts[-1],
                "exit_reason": "max_hold",
                "hold_h": (post_ts[-1]-activation).total_seconds()/3600,
                "max_R": max_R}
    if sl_f == -1:
        return {"outcome": "win", "R": rr, "exit_time": post_ts[tp_f],
                "exit_reason": "tp_fixed",
                "hold_h": (post_ts[tp_f]-activation).total_seconds()/3600, "max_R": max_R}
    if tp_f == -1:
        return {"outcome": "loss", "R": -1.0, "exit_time": post_ts[sl_f],
                "exit_reason": "sl_hit",
                "hold_h": (post_ts[sl_f]-activation).total_seconds()/3600, "max_R": max_R}
    if tp_f < sl_f:
        return {"outcome": "win", "R": rr, "exit_time": post_ts[tp_f],
                "exit_reason": "tp_fixed",
                "hold_h": (post_ts[tp_f]-activation).total_seconds()/3600, "max_R": max_R}
    return {"outcome": "loss", "R": -1.0, "exit_time": post_ts[sl_f],
            "exit_reason": "sl_hit",
            "hold_h": (post_ts[sl_f]-activation).total_seconds()/3600, "max_R": max_R}


# ============================================================
# Run + analyze
# ============================================================
def collect_signals(symbol):
    df_1d = load_df(symbol, "1d")
    df_4h = load_df(symbol, "4h")
    df_1h = load_df(symbol, "1h")
    df_15m = load_df(symbol, "15m")
    df_1m = load_df(symbol, "1m")
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_20m = compose_from_base(df_1m, "20m")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = max(today - pd.Timedelta(days=DAYS_BACK_TARGET), df_1m.index[0])
    df_1d_f = df_1d[df_1d.index >= cutoff]
    df_12h_f = df_12h[df_12h.index >= cutoff]
    groups = detect_multi_signals(df_1d_f, df_12h_f, df_4h, df_6h,
                                    df_1h, df_2h, df_15m, df_20m)
    sigs = []
    for gid, gsigs in groups.items():
        for s in sorted(gsigs, key=lambda x: x["fvg_c2_time"]):
            if check_swept(s, df_1h, df_2h) is True:
                sigs.append(s)
    return sigs, df_1m, df_1h, df_2h, (today-cutoff).days/365


def evaluate_variant(label, simulate_fn, signals, *args):
    trades = []
    for s in signals:
        r = simulate_fn(s, *args)
        if r is None: continue
        trades.append({"signal_time": s["signal_time"],
                        "direction": s["direction"], **r})
    return trades


def distribution_stats(trades):
    closed = [t for t in trades if t["outcome"] in ("win", "loss", "flat")]
    if not closed:
        return None
    Rs = sorted([t["R"] for t in closed], reverse=True)
    n = len(closed)
    W = sum(1 for r in Rs if r > 0)
    L = sum(1 for r in Rs if r < 0)
    wr = W/n*100
    pnl = sum(Rs)
    median_R = float(np.median(Rs))
    max_R = max(Rs)
    min_R = min(Rs)
    top5 = sum(Rs[:5])
    top5_pct = top5/pnl*100 if pnl > 0 else 0
    top10pct_n = max(1, n // 10)
    top10pct_sum = sum(Rs[:top10pct_n])
    top10pct_pct = top10pct_sum/pnl*100 if pnl > 0 else 0
    avg_win = np.mean([r for r in Rs if r > 0]) if W else 0
    avg_loss = np.mean([r for r in Rs if r < 0]) if L else 0
    return {
        "n": n, "W": W, "L": L, "wr": wr, "pnl": pnl, "r_per": pnl/n,
        "median_R": median_R, "max_R": max_R, "min_R": min_R,
        "top5_pct": top5_pct, "top10pct_pct": top10pct_pct,
        "avg_win": avg_win, "avg_loss": avg_loss,
    }


def main():
    symbol = "BTCUSDT"
    print(f"etap_104: 6 variants на {symbol} 6.34y")
    print()
    print(f"Loading data and detecting signals...")
    sigs, df_1m, df_1h, df_2h, years = collect_signals(symbol)
    print(f"  signals (swept): {len(sigs)}, years={years:.2f}")

    score_long, score_short = build_score_series(df_1h)
    atr_1h = compute_atr_1h(df_1h)

    variants = [
        ("BASELINE RR=2.2",        lambda s: variant_baseline_rr(s, df_1m)),
        ("A: Score-exit (th=0)",   lambda s: variant_score(s, df_1m, df_1h, score_long, score_short)),
        ("B: ATR-trail K=1.5",     lambda s: variant_atr_trail(s, df_1m, df_1h, atr_1h, K=1.5)),
        ("B: ATR-trail K=2.0",     lambda s: variant_atr_trail(s, df_1m, df_1h, atr_1h, K=2.0)),
        ("B: ATR-trail K=2.5",     lambda s: variant_atr_trail(s, df_1m, df_1h, atr_1h, K=2.5)),
        ("C: MFE-retrace 25%",     lambda s: variant_mfe_retrace(s, df_1m, df_1h, retrace_pct=0.25)),
        ("C: MFE-retrace 33%",     lambda s: variant_mfe_retrace(s, df_1m, df_1h, retrace_pct=0.33)),
        ("C: MFE-retrace 50%",     lambda s: variant_mfe_retrace(s, df_1m, df_1h, retrace_pct=0.50)),
        ("D: R-cap=2.5 + score",   lambda s: variant_rcap_score(s, df_1m, df_1h, score_long, score_short, R_cap=2.5)),
        ("D: R-cap=3 + score",     lambda s: variant_rcap_score(s, df_1m, df_1h, score_long, score_short, R_cap=3.0)),
        ("D: R-cap=4 + score",     lambda s: variant_rcap_score(s, df_1m, df_1h, score_long, score_short, R_cap=4.0)),
        ("E: BE-ratchet step=1R",  lambda s: variant_be_ratchet(s, df_1m, df_1h, step_R=1.0)),
        ("E: BE-ratchet step=1.5R", lambda s: variant_be_ratchet(s, df_1m, df_1h, step_R=1.5)),
        ("F: Time-decay score",    lambda s: variant_time_decay_score(s, df_1m, df_1h, score_long, score_short)),
    ]

    print()
    print(f"{'Variant':<28} {'n':>4} {'WR%':>5} {'PnL':>9} {'R/tr':>6} {'medR':>6} "
          f"{'maxR':>6} {'top5%':>6} {'top10%':>7} {'avgL':>6}")
    print("-" * 100)
    results = []
    for label, fn in variants:
        trades = evaluate_variant(label, fn, sigs)
        st = distribution_stats(trades)
        if st is None:
            print(f"  {label:<26} : NO DATA")
            continue
        marker = "★" if (st["pnl"] > 200 and st["top5_pct"] < 25 and st["median_R"] > 0) else " "
        print(f"{marker}{label:<27} {st['n']:>4d} {st['wr']:>4.1f}% {st['pnl']:>+8.1f}R "
              f"{st['r_per']:>+5.2f} {st['median_R']:>+5.2f} {st['max_R']:>+5.1f} "
              f"{st['top5_pct']:>5.1f}% {st['top10pct_pct']:>6.1f}% {st['avg_loss']:>+5.2f}")
        results.append((label, st, trades))

    print()
    print("="*100)
    print("ИДЕАЛ: pnl>200 + top5_pct<25 + median>0  (★)")
    print("='" * 50)

    # Rank by combined: maximize PnL × (1 - top5_pct/100) × (1 if median>0 else 0)
    def score_balance(st):
        if st["median_R"] <= 0: return -999
        return st["pnl"] * (1 - st["top5_pct"]/100)
    results.sort(key=lambda x: score_balance(x[1]), reverse=True)
    print("\nTOP-5 по balance-score (PnL × (1 - top5_contrib)):")
    for label, st, _ in results[:5]:
        print(f"  {label:<28}  PnL={st['pnl']:+7.1f}R  top5={st['top5_pct']:5.1f}%  "
              f"med={st['median_R']:+5.2f}  balance={score_balance(st):+7.1f}")


if __name__ == "__main__":
    main()
