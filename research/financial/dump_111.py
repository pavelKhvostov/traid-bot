"""Per-trade CSV dump of Strategy 1.1.1 (SWEPT, canonical) at FIXED RR=1.5.

Reuses the validated sim engine + dedup + SWEPT filter from fin_111.py:
  - SWEPT filter ON, entry_pct=0.80, sl_pct=0.35 symmetric, no_entry ON
  - limit-fill waits for price to touch entry from c2.close + tf_minutes
  - SL/TP scanned from the FILL bar forward (no entry-bar lookahead)
  - signals pooled across BTC+ETH+SOL, deduped by (signal_time, direction, round(entry,6))

For each CLOSED trade (win/loss only; not_filled / no_entry / open dropped)
write a row to research/financial/trades_111.csv with EXACTLY columns:
  signal_time, exit_time, sym, direction, gross_R, risk_pct

gross_R = +1.5 if TP hit first else -1.0
risk_pct = abs(entry - sl) / entry * 100  (real per-trade stop distance %)
"""
from __future__ import annotations

import csv
from collections import defaultdict

import numpy as np
import pandas as pd

# Reuse everything from the sibling fin_111.py (same dir).
import sys as _sys
from pathlib import Path as _P
_HERE = _P(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.insert(0, str(_HERE))

from fin_111 import (  # noqa: E402
    SYMBOLS,
    check_swept_for_path,
    recompute_levels,
)
import fin_111 as f111  # noqa: E402

from data_manager import compose_from_base, load_df  # noqa: E402
from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals  # noqa: E402

RR = 1.5
OUT_CSV = _HERE / "trades_111.csv"


def precompute_signal_with_times(sig: dict, df_1m: pd.DataFrame) -> dict | None:
    """Same as fin_111.precompute_signal but also keep the forward bar timestamps.

    Forward 1m bars start at c2.close + tf_minutes (no entry-bar lookahead),
    identical slice to fin_111.precompute_signal so the sim is unchanged.
    """
    fvg_b, fvg_t = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    direction = sig["direction"]
    tf_minutes = 15 if sig["fvg_tf"] == "15m" else 20
    forward = df_1m[df_1m.index >= sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)]
    if forward.empty:
        return None
    return {
        "signal_time": pd.Timestamp(sig["signal_time"]),
        "direction": direction,
        "fvg_b": float(fvg_b), "fvg_t": float(fvg_t),
        "obh_b": float(obh_b), "obh_t": float(obh_t),
        "highs": forward["high"].values.astype(np.float64),
        "lows": forward["low"].values.astype(np.float64),
        "times": forward.index.values,  # datetime64[ns] forward-bar open times
    }


def simulate_with_exit(s: dict, entry: float, sl: float, tp: float):
    """Limit-fill sim identical to fin_111.simulate_with_no_entry, but also
    return the exit bar's absolute index in the forward window.

    Returns (outcome, exit_global_idx) where outcome in
    {no_entry, not_filled, open, win, loss}. exit_global_idx is None unless
    win/loss (index into s['times']/highs/lows of the SL/TP-hit bar).
    """
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
        return "no_entry", None
    if entry_idx >= n:
        return "not_filled", None
    post_l = lows[entry_idx:]; post_h = highs[entry_idx:]
    if s["direction"] == "LONG":
        sl_mask = post_l <= sl; tp_mask = post_h >= tp
    else:
        sl_mask = post_h >= sl; tp_mask = post_l <= tp
    sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
    tp_first = int(np.argmax(tp_mask)) if tp_mask.any() else -1
    if sl_first == -1 and tp_first == -1:
        return "open", None
    if sl_first == -1:
        return "win", entry_idx + tp_first
    if tp_first == -1:
        return "loss", entry_idx + sl_first
    if tp_first < sl_first:
        return "win", entry_idx + tp_first
    return "loss", entry_idx + sl_first


def build_cache_for_symbol(symbol: str) -> list[dict]:
    """Detect SWEPT signals for one symbol; precompute sim caches WITH times.

    Mirrors fin_111.build_cache_for_symbol exactly except it uses the
    times-keeping precompute so we can recover exit_time.
    """
    print(f"\n{'=' * 80}\nSYMBOL: {symbol}\n{'=' * 80}")
    df_1d = load_df(symbol, "1d")
    df_4h = load_df(symbol, "4h")
    df_1h = load_df(symbol, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(symbol, "15m")
    df_1m = load_df(symbol, "1m")
    df_20m = compose_from_base(df_1m, "20m")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=f111.DAYS_BACK)
    df_1d_f = df_1d[df_1d.index >= cutoff]
    print(f"  data: 1d={len(df_1d_f)} 4h={len(df_4h)} 1h={len(df_1h)} "
          f"15m={len(df_15m)} 1m={len(df_1m)}")

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
    cache = [c for c in (precompute_signal_with_times(s, df_1m) for s in swept_reps)
             if c is not None]
    print(f"  raw paths: {len(raw)}  deduped groups: {len(groups)}  "
          f"SWEPT reps: {len(swept_reps)}  cache: {len(cache)}")
    for c in cache:
        c["symbol"] = symbol
    return cache


def main() -> dict:
    print(f"[INFO] 1.1.1 SWEPT per-trade dump: entry={f111.ENTRY_PCT} "
          f"sl_pct={f111.SL_PCT} no_entry=on RR={RR}")
    print(f"       symbols={SYMBOLS}, window {f111.DAYS_BACK}d")

    all_cache: list[dict] = []
    for sym in SYMBOLS:
        all_cache.extend(build_cache_for_symbol(sym))
    print(f"\nPooled SWEPT cache across assets: {len(all_cache)}")

    seen = set()
    rows = []
    risk_pcts = []
    wins = losses = 0
    for s in all_cache:
        lv = recompute_levels(s, RR)
        if lv is None:
            continue
        entry, sl, tp = lv
        key = (s["signal_time"], s["direction"], round(entry, 6))
        if key in seen:
            continue
        seen.add(key)
        outcome, exit_idx = simulate_with_exit(s, entry, sl, tp)
        if outcome == "win":
            gross_R = RR; wins += 1
        elif outcome == "loss":
            gross_R = -1.0; losses += 1
        else:
            continue  # drop no_entry / not_filled / open

        risk_pct = abs(entry - sl) / entry * 100.0
        risk_pcts.append(risk_pct)

        st = pd.Timestamp(s["signal_time"])
        if st.tz is not None:
            st = st.tz_convert("UTC")
        signal_time_iso = st.strftime("%Y-%m-%d %H:%M:%S")

        exit_time_iso = ""
        if exit_idx is not None:
            et = pd.Timestamp(s["times"][exit_idx])
            if et.tz is not None:
                et = et.tz_convert("UTC")
            exit_time_iso = et.strftime("%Y-%m-%d %H:%M:%S")

        rows.append({
            "signal_time": signal_time_iso,
            "exit_time": exit_time_iso,
            "sym": s["symbol"],
            "direction": s["direction"],
            "gross_R": gross_R,
            "risk_pct": risk_pct,
        })

    # Sort by signal_time for a stable, readable CSV.
    rows.sort(key=lambda r: (r["signal_time"], r["sym"], r["direction"]))

    cols = ["signal_time", "exit_time", "sym", "direction", "gross_R", "risk_pct"]
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    median_risk = float(np.median(risk_pcts)) if risk_pcts else 0.0
    n_trades = len(rows)
    print("\n" + "=" * 80)
    print(f"wrote {n_trades} closed trades -> {OUT_CSV}")
    print(f"  wins={wins} losses={losses} "
          f"WR={(wins / n_trades * 100.0) if n_trades else 0.0:.1f}%")
    print(f"  median risk_pct = {median_risk:.6f}")
    return {
        "csv_path": str(OUT_CSV),
        "n_trades": n_trades,
        "opt_rr": RR,
        "median_risk_pct": median_risk,
        "cols": cols,
    }


if __name__ == "__main__":
    import json
    res = main()
    print("\n===JSON_RESULT_START===")
    print(json.dumps(res))
    print("===JSON_RESULT_END===")
