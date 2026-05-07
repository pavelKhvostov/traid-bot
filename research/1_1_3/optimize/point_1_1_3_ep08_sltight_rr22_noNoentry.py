"""1.1.3 точка: entry=0.8 в FVG-1h/2h, sl=ob_htf tight edge, RR=2.2, БЕЗ no_entry.

Параметры:
  entry в FVG-htf:
    LONG  : entry = fvg.bottom + 0.8 * (fvg.top - fvg.bottom)
    SHORT : entry = fvg.top    - 0.8 * (fvg.top - fvg.bottom)
  sl (узкий, ближняя к рынку граница ob_htf):
    LONG  : sl = ob_htf.top
    SHORT : sl = ob_htf.bottom
  RR = 2.2
  TP = entry ± 2.2 × risk

БЕЗ no_entry: сделка ждёт активацию entry (low <= entry для LONG) даже если
цена сначала достигла TP. Реалистичная симуляция limit-ордера: вход по entry,
SL/TP first-hit от момента активации.

4 точки: v1/v2 × ALL/SWEPT.
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
EP_PCT = 0.8
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


def precompute(sig, df_1m):
    fvg_b, fvg_t = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    direction = sig["direction"]
    fvg_tf = sig["fvg_tf"]
    tf_minutes = 60 if fvg_tf == "1h" else 120
    forward = df_1m[df_1m.index >= sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)]
    if forward.empty:
        return None
    return {
        "direction": direction,
        "fvg_b": float(fvg_b), "fvg_t": float(fvg_t),
        "obh_b": float(obh_b), "obh_t": float(obh_t),
        "highs": forward["high"].values.astype(np.float64),
        "lows":  forward["low"].values.astype(np.float64),
    }


def simulate_no_noentry(s, entry, sl, tp):
    """Без no_entry: ждём активацию entry, потом SL/TP first-hit."""
    highs, lows = s["highs"], s["lows"]
    n = len(highs)
    if s["direction"] == "LONG":
        entry_idxs = np.where(lows <= entry)[0]
    else:
        entry_idxs = np.where(highs >= entry)[0]
    if not entry_idxs.size:
        return "not_filled"
    entry_idx = int(entry_idxs[0])
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
    wins = losses = nf = opens = skipped = 0
    long_w = long_l = short_w = short_l = 0
    for s in cache:
        fvg_w = s["fvg_t"] - s["fvg_b"]
        if s["direction"] == "LONG":
            entry = s["fvg_b"] + EP_PCT * fvg_w
            sl = s["obh_t"]
            if sl >= entry: skipped += 1; continue
            risk = entry - sl
            tp = entry + RR_TARGET * risk
        else:
            entry = s["fvg_t"] - EP_PCT * fvg_w
            sl = s["obh_b"]
            if sl <= entry: skipped += 1; continue
            risk = sl - entry
            tp = entry - RR_TARGET * risk
        outcome = simulate_no_noentry(s, entry, sl, tp)
        if outcome == "win":
            wins += 1
            if s["direction"] == "LONG": long_w += 1
            else: short_w += 1
        elif outcome == "loss":
            losses += 1
            if s["direction"] == "LONG": long_l += 1
            else: short_l += 1
        elif outcome == "open":
            opens += 1
        else:
            nf += 1
    closed = wins + losses
    pnl_r = wins * RR_TARGET - losses
    long_pnl = long_w * RR_TARGET - long_l
    short_pnl = short_w * RR_TARGET - short_l
    print(f"  [{label}] cache={len(cache)} W={wins} L={losses} sk={skipped} nf={nf} open={opens} closed={closed}")
    if closed:
        print(f"          WR={wins/closed*100:.1f}%  PnL={pnl_r:+.2f}R  R/tr={pnl_r/closed:.3f}")
    if (long_w+long_l):
        print(f"          LONG: {long_w}W/{long_l}L  WR={long_w/(long_w+long_l)*100:.1f}%  PnL={long_pnl:+.1f}R")
    if (short_w+short_l):
        print(f"          SHORT: {short_w}W/{short_l}L  WR={short_w/(short_w+short_l)*100:.1f}%  PnL={short_pnl:+.1f}R")
    print()


def main():
    print(f"[INFO] 1.1.3 point: ep={EP_PCT} (in FVG), sl=ob_htf tight, RR={RR_TARGET}, "
          f"NO no_entry, macro_mode={MACRO_MODE}")
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
            c = precompute(d["sig"], df_1m)
            if c is None: continue
            c["_swept"] = d["swept"]
            cache_all.append(c)
        cache_swept = [c for c in cache_all if c["_swept"]]
        print(f"  raw={len(raw)} ALL={len(cache_all)} SWEPT={len(cache_swept)}")
        run_point(cache_all, f"{variant}/ALL")
        run_point(cache_swept, f"{variant}/SWEPT")


if __name__ == "__main__":
    main()
