"""1.1.3 точечный прогон: ep=1.0, sl_pct=0.5, RR=2.2 (классический TP от entry).

Параметры:
  entry = close(c2)
  sl = ob_htf.bottom + 0.5 * (ob_htf.top - ob_htf.bottom)  (LONG)
  sl = ob_htf.top    - 0.5 * (ob_htf.top - ob_htf.bottom)  (SHORT)
  tp = entry + 2.2 * (entry - sl)  (LONG)
  tp = entry - 2.2 * (sl - entry)  (SHORT)
  no_entry: tp до entry -> отмена

4 точки: v1/v2 x ALL/SWEPT.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    if _ROOT.parent == _ROOT:
        raise RuntimeError("repo root not found")
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from collections import defaultdict

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_3 import detect_strategy_1_1_3_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
MACRO_MODE = "extended"
SL_PCT = 0.5
EP = 1.0
RR_TARGET = 2.2


def check_swept(sig, df_1h, df_2h):
    df_top = df_1h if sig["ob_htf_tf"] == "1h" else df_2h
    cur_time = pd.Timestamp(sig["ob_htf_cur_time"])
    prev_time = pd.Timestamp(sig["ob_htf_prev_time"])
    if cur_time.tz is None: cur_time = cur_time.tz_localize("UTC")
    if prev_time.tz is None: prev_time = prev_time.tz_localize("UTC")
    if prev_time not in df_top.index or cur_time not in df_top.index:
        return None
    prev_idx = df_top.index.get_loc(prev_time)
    if prev_idx < 2: return None
    cur_idx = df_top.index.get_loc(cur_time)
    c1l = float(df_top.iloc[prev_idx]["low"]);  c2l = float(df_top.iloc[cur_idx]["low"])
    c1h = float(df_top.iloc[prev_idx]["high"]); c2h = float(df_top.iloc[cur_idx]["high"])
    n1l = float(df_top.iloc[prev_idx - 1]["low"]);  n2l = float(df_top.iloc[prev_idx - 2]["low"])
    n1h = float(df_top.iloc[prev_idx - 1]["high"]); n2h = float(df_top.iloc[prev_idx - 2]["high"])
    if sig["direction"] == "LONG":
        return min(c1l, c2l) < min(n1l, n2l)
    return max(c1h, c2h) > max(n1h, n2h)


def precompute(sig, df_1h, df_2h, df_1m):
    fvg_b, fvg_t = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    direction = sig["direction"]
    fvg_tf = sig["fvg_tf"]
    tf_minutes = 60 if fvg_tf == "1h" else 120
    df_htf_for_close = df_1h if fvg_tf == "1h" else df_2h
    c2_time = pd.Timestamp(sig["fvg_c2_time"])
    if c2_time.tz is None:
        c2_time = c2_time.tz_localize("UTC")
    if c2_time not in df_htf_for_close.index:
        return None
    close_c2 = float(df_htf_for_close.loc[c2_time, "close"])
    forward = df_1m[df_1m.index >= sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)]
    if forward.empty:
        return None
    return {
        "direction": direction,
        "fvg_b": float(fvg_b), "fvg_t": float(fvg_t),
        "obh_b": float(obh_b), "obh_t": float(obh_t),
        "close_c2": close_c2,
        "highs": forward["high"].values.astype(np.float64),
        "lows":  forward["low"].values.astype(np.float64),
    }


def simulate_no_entry(s, entry, sl, tp):
    highs, lows = s["highs"], s["lows"]
    n = len(highs)
    if s["direction"] == "LONG":
        entry_idxs = np.where(lows <= entry)[0]
        tp_pre_idxs = np.where(highs >= tp)[0]
    else:
        entry_idxs = np.where(highs >= entry)[0]
        tp_pre_idxs = np.where(lows <= tp)[0]
    entry_idx = int(entry_idxs[0]) if entry_idxs.size else n + 1
    tp_pre_idx = int(tp_pre_idxs[0]) if tp_pre_idxs.size else n + 1
    if tp_pre_idx < entry_idx: return "no_entry"
    if entry_idx >= n: return "not_filled"
    post_l = lows[entry_idx:]; post_h = highs[entry_idx:]
    if s["direction"] == "LONG":
        sl_mask = post_l <= sl; tp_mask = post_h >= tp
    else:
        sl_mask = post_h >= sl; tp_mask = post_l <= tp
    sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
    tp_first = int(np.argmax(tp_mask)) if tp_mask.any() else -1
    if sl_first == -1 and tp_first == -1: return "open"
    if sl_first == -1: return "win"
    if tp_first == -1: return "loss"
    return "win" if tp_first < sl_first else "loss"


def run_point(cache, label):
    wins = losses = nf = no_entry = opens = skipped = 0
    long_w = long_l = short_w = short_l = 0
    for s in cache:
        ob_h = s["obh_t"] - s["obh_b"]
        if s["direction"] == "LONG":
            entry = s["close_c2"]                       # ep=1.0
            sl = s["obh_b"] + SL_PCT * ob_h
            if sl >= entry: skipped += 1; continue
            risk = entry - sl
            tp = entry + RR_TARGET * risk
        else:
            entry = s["close_c2"]
            sl = s["obh_t"] - SL_PCT * ob_h
            if sl <= entry: skipped += 1; continue
            risk = sl - entry
            tp = entry - RR_TARGET * risk
        outcome = simulate_no_entry(s, entry, sl, tp)
        if outcome == "win":
            wins += 1
            if s["direction"] == "LONG": long_w += 1
            else: short_w += 1
        elif outcome == "loss":
            losses += 1
            if s["direction"] == "LONG": long_l += 1
            else: short_l += 1
        elif outcome == "no_entry":
            no_entry += 1
        elif outcome == "open":
            opens += 1
        else:
            nf += 1
    closed = wins + losses
    pnl_r = wins * RR_TARGET - losses * 1.0
    long_pnl = long_w * RR_TARGET - long_l
    short_pnl = short_w * RR_TARGET - short_l
    print(f"  [{label}] cache={len(cache)} W={wins} L={losses} ne={no_entry} sk={skipped} closed={closed}")
    if closed:
        print(f"          WR={wins/closed*100:.1f}%  PnL={pnl_r:+.2f}R  R/tr={pnl_r/closed:.3f}")
    print(f"          LONG: {long_w}W/{long_l}L  WR={long_w/(long_w+long_l)*100 if (long_w+long_l) else 0:.1f}%  PnL={long_pnl:+.1f}R")
    print(f"          SHORT: {short_w}W/{short_l}L  WR={short_w/(short_w+short_l)*100 if (short_w+short_l) else 0:.1f}%  PnL={short_pnl:+.1f}R")
    print()


def main():
    print(f"[INFO] 1.1.3 point: ep={EP}, sl_pct={SL_PCT}, RR={RR_TARGET}, macro_mode={MACRO_MODE}")
    print()

    df_1d  = load_df(SYMBOL, "1d")
    df_12h = load_df(SYMBOL, "12h")
    df_4h  = load_df(SYMBOL, "4h")
    df_1h  = load_df(SYMBOL, "1h")
    df_6h  = compose_from_base(df_1h, "6h")
    df_2h  = compose_from_base(df_1h, "2h")
    df_1m  = load_df(SYMBOL, "1m")

    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f  = df_1d[df_1d.index >= cutoff]
    df_12h_f = df_12h[df_12h.index >= cutoff]

    for variant in ["v1", "v2"]:
        print(f"[{variant}] detect...")
        raw = detect_strategy_1_1_3_signals(
            df_1d_f, df_12h_f, df_4h, df_6h, df_1h, df_2h,
            fvg_variant=variant, macro_mode=MACRO_MODE, verbose=False,
        )
        groups = defaultdict(list)
        for s in raw:
            key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
            sw = check_swept(s, df_1h, df_2h)
            if sw is None: continue
            groups[key].append({"sig": s, "swept": sw})
        deduped = []
        for k, paths in groups.items():
            rep = paths[0]["sig"]
            any_swept = any(p["swept"] for p in paths)
            deduped.append({"sig": rep, "swept": any_swept})
        cache_all = []
        for d in deduped:
            c = precompute(d["sig"], df_1h, df_2h, df_1m)
            if c is None: continue
            c["_swept"] = d["swept"]
            cache_all.append(c)
        cache_swept = [c for c in cache_all if c["_swept"]]
        print(f"  raw={len(raw)} deduped={len(deduped)} ALL={len(cache_all)} SWEPT={len(cache_swept)}")
        run_point(cache_all, f"{variant}/ALL")
        run_point(cache_swept, f"{variant}/SWEPT")


if __name__ == "__main__":
    main()
