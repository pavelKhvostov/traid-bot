"""Помесячная разбивка финального конфига Strategy 1.1.1 на SWEPT setups.

Финальный конфиг (Stage 1+2+3):
  - SWEPT filter ON
  - entry_pct = 0.80
  - sl_pct = 0.35 (между ob_htf edge и fvg entry edge)
  - RR = 2.2
  - no_entry = ON (отмена если TP до entry)
"""
from __future__ import annotations


# --- repo-root injection (Phase 3 refactor) ---
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    if _ROOT.parent == _ROOT:
        raise RuntimeError("repo root not found")
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
# --- end repo-root injection ---

from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
ENTRY_PCT = 0.80
SL_PCT = 0.35
RR_TARGET = 2.2


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


def precompute_signal(sig: dict, df_1m: pd.DataFrame) -> dict | None:
    fvg_b, fvg_t = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    direction = sig["direction"]
    tf_minutes = 15 if sig["fvg_tf"] == "15m" else 20
    forward = df_1m[df_1m.index >= sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)]
    if forward.empty:
        return None
    return {
        "signal_time": sig["signal_time"],
        "direction": direction,
        "fvg_b": float(fvg_b), "fvg_t": float(fvg_t),
        "obh_b": float(obh_b), "obh_t": float(obh_t),
        "highs": forward["high"].values.astype(np.float64),
        "lows": forward["low"].values.astype(np.float64),
    }


def simulate_with_no_entry(s: dict, entry: float, sl: float, tp: float) -> str:
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
    if tp_pre_idx < entry_idx:
        return "no_entry"
    if entry_idx >= n:
        return "not_filled"
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


def main() -> None:
    print(f"[INFO] Final config monthly breakdown:")
    print(f"       entry_pct={ENTRY_PCT}, sl_pct={SL_PCT}, RR={RR_TARGET}, no_entry=on, SWEPT only")
    print()

    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f = df_1d[df_1d.index >= cutoff]

    raw = detect_strategy_1_1_1_signals(
        df_1d_f, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m, verbose=False,
    )

    groups = defaultdict(list)
    for s in raw:
        key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
        sw = check_swept_for_path(s, df_1h, df_2h)
        if sw is None:
            continue
        groups[key].append({"sig": s, "swept": sw})
    swept_reps = [next(p["sig"] for p in paths if p["swept"])
                  for key, paths in groups.items() if any(p["swept"] for p in paths)]
    cache = [c for c in (precompute_signal(s, df_1m) for s in swept_reps) if c is not None]
    print(f"  SWEPT cache: {len(cache)}")

    trades = []
    for s in cache:
        fw = s["fvg_t"] - s["fvg_b"]
        if s["direction"] == "LONG":
            entry = s["fvg_b"] + ENTRY_PCT * fw
            sl = s["obh_b"] + SL_PCT * (s["fvg_b"] - s["obh_b"])
            if sl >= entry:
                continue
            risk = entry - sl
            tp = entry + RR_TARGET * risk
        else:
            entry = s["fvg_t"] - ENTRY_PCT * fw
            sl = s["obh_t"] - SL_PCT * (s["obh_t"] - s["fvg_t"])
            if sl <= entry:
                continue
            risk = sl - entry
            tp = entry - RR_TARGET * risk
        outcome = simulate_with_no_entry(s, entry, sl, tp)
        trades.append({
            "signal_time": pd.Timestamp(s["signal_time"]),
            "direction": s["direction"],
            "outcome": outcome,
        })

    df_t = pd.DataFrame(trades)
    df_t["month"] = df_t["signal_time"].dt.to_period("M").astype(str)

    print()
    print("=" * 100)
    print("Помесячная разбивка")
    print("=" * 100)

    rows = []
    for month, sub in df_t.groupby("month"):
        wins = (sub["outcome"] == "win").sum()
        losses = (sub["outcome"] == "loss").sum()
        no_entry = (sub["outcome"] == "no_entry").sum()
        opens = (sub["outcome"] == "open").sum()
        nf = (sub["outcome"] == "not_filled").sum()
        closed = wins + losses
        pnl = wins * RR_TARGET - losses
        rows.append({
            "month": month,
            "signals": len(sub),
            "no_entry": int(no_entry),
            "wins": int(wins),
            "losses": int(losses),
            "open": int(opens),
            "nf": int(nf),
            "closed": int(closed),
            "wr": round(wins / closed * 100, 1) if closed else 0,
            "pnl_r": round(pnl, 2),
        })
    df_m = pd.DataFrame(rows).sort_values("month")
    print(df_m.to_string(index=False))

    print()
    print("=" * 100)
    print("Годовая разбивка")
    print("=" * 100)
    df_t["year"] = df_t["signal_time"].dt.year
    yrows = []
    for year, sub in df_t.groupby("year"):
        wins = (sub["outcome"] == "win").sum()
        losses = (sub["outcome"] == "loss").sum()
        no_entry = (sub["outcome"] == "no_entry").sum()
        closed = wins + losses
        pnl = wins * RR_TARGET - losses
        yrows.append({
            "year": int(year),
            "signals": len(sub),
            "no_entry": int(no_entry),
            "wins": int(wins),
            "losses": int(losses),
            "closed": int(closed),
            "wr": round(wins / closed * 100, 1) if closed else 0,
            "pnl_r": round(pnl, 2),
        })
    df_y = pd.DataFrame(yrows)
    print(df_y.to_string(index=False))

    print()
    print("=" * 100)
    print("ИТОГО за 3 года:")
    total_wins = (df_t["outcome"] == "win").sum()
    total_losses = (df_t["outcome"] == "loss").sum()
    total_ne = (df_t["outcome"] == "no_entry").sum()
    total_open = (df_t["outcome"] == "open").sum()
    total_closed = total_wins + total_losses
    total_pnl = total_wins * RR_TARGET - total_losses
    print(f"  signals={len(df_t)} no_entry={total_ne} open={total_open}")
    print(f"  closed={total_closed}: wins={total_wins} losses={total_losses}")
    print(f"  WR={total_wins / total_closed * 100:.1f}% PnL={total_pnl:.2f}R "
          f"R/trade={total_pnl / total_closed:.3f}")

    out = Path("signals/analyze_1_1_1_swept_monthly.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    df_m.to_csv(out, index=False)
    print(f"\nMonthly grid saved: {out}")


if __name__ == "__main__":
    main()
