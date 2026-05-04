"""SWEPT split на baseline 1.1.2 (без оптимизации, default entry=mid FVG, SL=15% inside top-OB).

Аналог analyze_1_1_1_ob_swept.py — разбивает 1.1.2 deduped сетапы на:
  - SWEPT (OB-htf пара min(low_c1,c2) < min(low_c1-1,c1-2) для LONG)
  - NOT-SWEPT (зеркально для SHORT)
И прогоняет через симуляцию RR=1.0 и RR=2.2 с no_entry=on.

Подтверждает гипотезу: NOT-SWEPT убыточен, SWEPT прибылен — как в 1.1.1.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_2 import detect_strategy_1_1_2_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
RR_LIST = [1.0, 2.2]


def check_swept_for_path(sig: dict, df_1h: pd.DataFrame, df_2h: pd.DataFrame) -> bool | None:
    df_top = df_1h if sig["ob_htf_tf"] == "1h" else df_2h
    cur_time = pd.Timestamp(sig["ob_htf_cur_time"])
    prev_time = pd.Timestamp(sig["ob_htf_prev_time"])
    if cur_time.tz is None: cur_time = cur_time.tz_localize("UTC")
    if prev_time.tz is None: prev_time = prev_time.tz_localize("UTC")
    if prev_time not in df_top.index or cur_time not in df_top.index:
        return None
    prev_idx = df_top.index.get_loc(prev_time)
    if prev_idx < 2:
        return None
    cur_idx = df_top.index.get_loc(cur_time)
    c1l = float(df_top.iloc[prev_idx]["low"]); c2l = float(df_top.iloc[cur_idx]["low"])
    c1h = float(df_top.iloc[prev_idx]["high"]); c2h = float(df_top.iloc[cur_idx]["high"])
    n1l = float(df_top.iloc[prev_idx - 1]["low"]); n2l = float(df_top.iloc[prev_idx - 2]["low"])
    n1h = float(df_top.iloc[prev_idx - 1]["high"]); n2h = float(df_top.iloc[prev_idx - 2]["high"])
    if sig["direction"] == "LONG":
        return min(c1l, c2l) < min(n1l, n2l)
    return max(c1h, c2h) > max(n1h, n2h)


def precompute(sig: dict, df_1m: pd.DataFrame) -> dict | None:
    fvg_b, fvg_t = sig["fvg_zone"]
    direction = sig["direction"]
    tf_minutes = 15 if sig["fvg_tf"] == "15m" else 20
    forward = df_1m[df_1m.index >= sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)]
    if forward.empty:
        return None
    return {
        "signal_time": sig["signal_time"],
        "direction": direction,
        "entry": float(sig["entry"]),
        "sl": float(sig["sl"]),
        "risk": float(sig["risk"]),
        "highs": forward["high"].values.astype(np.float64),
        "lows": forward["low"].values.astype(np.float64),
    }


def simulate_no_entry(s: dict, rr: float) -> str:
    direction = s["direction"]
    entry = s["entry"]; sl = s["sl"]; risk = s["risk"]
    if direction == "LONG":
        tp = entry + rr * risk
    else:
        tp = entry - rr * risk
    highs, lows = s["highs"], s["lows"]
    n = len(highs)
    if direction == "LONG":
        entry_idxs = np.where(lows <= entry)[0]
        tp_pre_idxs = np.where(highs >= tp)[0]
    else:
        entry_idxs = np.where(highs >= entry)[0]
        tp_pre_idxs = np.where(lows <= tp)[0]
    entry_idx = int(entry_idxs[0]) if entry_idxs.size else n + 1
    tp_pre_idx = int(tp_pre_idxs[0]) if tp_pre_idxs.size else n + 1
    if tp_pre_idx < entry_idx:
        return "no_entry"
    if entry_idx >= n:
        return "not_filled"
    post_l = lows[entry_idx:]; post_h = highs[entry_idx:]
    if direction == "LONG":
        sl_mask = post_l <= sl; tp_mask = post_h >= tp
    else:
        sl_mask = post_h >= sl; tp_mask = post_l <= tp
    sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
    tp_first = int(np.argmax(tp_mask)) if tp_mask.any() else -1
    if sl_first == -1 and tp_first == -1: return "open"
    if sl_first == -1: return "win"
    if tp_first == -1: return "loss"
    return "win" if tp_first < sl_first else "loss"


def stats(rows: list[dict], rr: float) -> dict:
    cache_outcomes = [r["outcome"] for r in rows]
    wins = sum(1 for o in cache_outcomes if o == "win")
    losses = sum(1 for o in cache_outcomes if o == "loss")
    ne = sum(1 for o in cache_outcomes if o == "no_entry")
    opens = sum(1 for o in cache_outcomes if o == "open")
    closed = wins + losses
    pnl = wins * rr - losses
    return {
        "total": len(rows), "no_entry": ne, "open": opens,
        "wins": wins, "losses": losses, "closed": closed,
        "wr": round(wins / closed * 100, 1) if closed else 0,
        "pnl_r": round(pnl, 2),
        "r_per_trade": round(pnl / closed, 3) if closed else 0,
    }


def main() -> None:
    print(f"[INFO] Strategy 1.1.2: SWEPT split (default entry=mid FVG, SL=15% inside top-OB)")
    print()

    df_1d = load_df(SYMBOL, "1d")
    df_12h = load_df(SYMBOL, "12h")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f = df_1d[df_1d.index >= cutoff]
    df_12h_f = df_12h[df_12h.index >= cutoff]

    raw = detect_strategy_1_1_2_signals(
        df_1d_f, df_12h_f, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m, verbose=False,
    )
    print(f"  raw paths: {len(raw)}")

    groups = defaultdict(list)
    for s in raw:
        key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
        sw = check_swept_for_path(s, df_1h, df_2h)
        if sw is None:
            continue
        groups[key].append({"sig": s, "swept": sw})

    swept_reps = [next(p["sig"] for p in paths if p["swept"])
                  for key, paths in groups.items() if any(p["swept"] for p in paths)]
    not_swept_reps = [paths[0]["sig"]
                      for key, paths in groups.items() if not any(p["swept"] for p in paths)]
    all_reps = [paths[0]["sig"] for key, paths in groups.items()]

    print(f"  deduped groups: {len(groups)}")
    print(f"  SWEPT: {len(swept_reps)}  NOT-SWEPT: {len(not_swept_reps)}  ALL: {len(all_reps)}")

    # Симуляция для каждой группы и каждого RR
    cache_all = [c for c in (precompute(s, df_1m) for s in all_reps) if c is not None]
    cache_swept = [c for c in (precompute(s, df_1m) for s in swept_reps) if c is not None]
    cache_not_swept = [c for c in (precompute(s, df_1m) for s in not_swept_reps) if c is not None]

    for rr in RR_LIST:
        print()
        print("=" * 90)
        print(f"RR = {rr}")
        print("=" * 90)
        for label, cache in [("ALL", cache_all), ("SWEPT", cache_swept), ("NOT-SWEPT", cache_not_swept)]:
            rows = [{"outcome": simulate_no_entry(s, rr)} for s in cache]
            st = stats(rows, rr)
            print(f"  {label:10s} total={st['total']:4d} no_entry={st['no_entry']:4d} "
                  f"closed={st['closed']:3d} W={st['wins']:3d} L={st['losses']:3d} "
                  f"WR={st['wr']:5.1f}% PnL={st['pnl_r']:+7.2f}R R/tr={st['r_per_trade']:+.3f}")

    out = Path("signals/analyze_1_1_2_ob_swept_summary.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        f.write(f"1.1.2 SWEPT split summary\n")
        f.write(f"raw paths={len(raw)} groups={len(groups)}\n")
        f.write(f"SWEPT={len(swept_reps)} NOT-SWEPT={len(not_swept_reps)}\n")
    print(f"\n  saved: {out}")


if __name__ == "__main__":
    main()
