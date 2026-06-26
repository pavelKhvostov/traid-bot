"""Financial backtest of Strategy 1.1.4 (FVG-top cascade) on BTC+ETH+SOL.

1.1.4 detector: strategies/strategy_1_1_4.detect_strategy_1_1_4_signals
  Top FVG {1d,12h} -> macro FVG {4h,6h} -> htf OB {1h,2h} -> entry FVG {15m,20m}.
  entry = mid of entry-FVG (entry_pct=0.80 baked into detector mid), SL = ob_htf
  far edge (no buffer), risk = |entry-sl| = 1R.

This script (per the task contract):
  - Detects signals per asset, dedups by (signal_time, direction, round(entry,6)).
  - For each RR in the grid, simulates every signal with a LIMIT FILL:
      * fill scan starts at c2.close = signal_time + tf_minutes (15 or 20) -> NO
        entry-bar lookahead;
      * wait until 1m price TOUCHES entry (LONG: low<=entry; SHORT: high>=entry);
      * from the FILL bar forward, scan SL (=1R) vs TP (=RR*risk);
      * pnl per trade = +RR if TP first else -1 if SL first;
      * drop not-filled / still-open trades.
  - Pools the 3 assets, computes per-RR wr / total_R / n_closed and MONTHLY
    metrics (group CLOSED trades by UTC calendar month of signal_time).

Reuses the project's validated vectorized fill+scan pattern
(research/1_1_1/analyze/analyze_1_1_1_swept_monthly.simulate_with_no_entry),
adapted to the simple "wait-for-touch, then SL/TP from fill bar" contract here
(no no_entry cancellation: the task asks only for fill + SL/TP-first).
"""
from __future__ import annotations


# --- repo-root injection ---
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

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_4 import detect_strategy_1_1_4_signals

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
DAYS_BACK = 2400  # full history
RR_GRID = [1.0, 1.5, 2.0, 2.2, 2.5, 3.0, 3.5]


def precompute_signal(sig: dict, df_1m: pd.DataFrame) -> dict | None:
    """Slice 1m highs/lows from c2.close forward (= signal_time + tf_minutes).

    NO entry-bar lookahead: the fill scan begins at the entry-FVG close, which is
    signal_time (open of c2) + tf duration (15m or 20m).
    """
    tf_minutes = 15 if sig["fvg_tf"] == "15m" else 20
    scan_start = sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)
    fw = df_1m[df_1m.index >= scan_start]
    if fw.empty:
        return None
    return {
        "signal_time": pd.Timestamp(sig["signal_time"]),
        "direction": sig["direction"],
        "entry": float(sig["entry"]),
        "sl": float(sig["sl"]),
        "risk": float(sig["risk"]),
        "highs": fw["high"].values.astype(np.float64),
        "lows": fw["low"].values.astype(np.float64),
    }


def simulate(s: dict, rr: float) -> str:
    """Limit fill (wait for touch) then SL/TP-first from the FILL bar forward.

    Returns 'win' (+RR), 'loss' (-1), 'not_filled', or 'open'.
    """
    highs, lows = s["highs"], s["lows"]
    n = len(highs)
    entry = s["entry"]
    sl = s["sl"]
    risk = s["risk"]
    if s["direction"] == "LONG":
        tp = entry + rr * risk
        fill_idxs = np.where(lows <= entry)[0]
    else:
        tp = entry - rr * risk
        fill_idxs = np.where(highs >= entry)[0]
    if fill_idxs.size == 0:
        return "not_filled"
    fi = int(fill_idxs[0])
    # Scan SL/TP from the fill bar forward (inclusive of the fill bar).
    post_h = highs[fi:]
    post_l = lows[fi:]
    if s["direction"] == "LONG":
        sl_mask = post_l <= sl
        tp_mask = post_h >= tp
    else:
        sl_mask = post_h >= sl
        tp_mask = post_l <= tp
    sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
    tp_first = int(np.argmax(tp_mask)) if tp_mask.any() else -1
    if sl_first == -1 and tp_first == -1:
        return "open"
    if sl_first == -1:
        return "win"
    if tp_first == -1:
        return "loss"
    # Tie on the same bar: conservative -> SL first (cannot resolve intrabar order).
    if tp_first < sl_first:
        return "win"
    return "loss"


def load_asset(symbol: str) -> dict:
    df_1d = load_df(symbol, "1d")
    df_12h = load_df(symbol, "12h")
    df_4h = load_df(symbol, "4h")
    df_1h = load_df(symbol, "1h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(symbol, "15m")
    df_1m = load_df(symbol, "1m")
    df_20m = compose_from_base(df_1m, "20m")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f = df_1d[df_1d.index >= cutoff]
    df_12h_f = df_12h[df_12h.index >= cutoff]
    return {
        "df_1d": df_1d_f, "df_12h": df_12h_f, "df_4h": df_4h, "df_6h": df_6h,
        "df_1h": df_1h, "df_2h": df_2h, "df_15m": df_15m, "df_20m": df_20m,
        "df_1m": df_1m,
    }


def collect_trades() -> list[dict]:
    """Detect + dedup signals per asset, precompute 1m slices. Pool the 3 assets."""
    pooled: list[dict] = []
    for symbol in SYMBOLS:
        print(f"[INFO] {symbol}: loading data")
        d = load_asset(symbol)
        print(f"  1d={len(d['df_1d'])} 12h={len(d['df_12h'])} 4h={len(d['df_4h'])} "
              f"6h={len(d['df_6h'])} 1h={len(d['df_1h'])} 2h={len(d['df_2h'])} "
              f"15m={len(d['df_15m'])} 20m={len(d['df_20m'])} 1m={len(d['df_1m'])}")
        raw = detect_strategy_1_1_4_signals(
            d["df_1d"], d["df_12h"], d["df_4h"], d["df_6h"],
            d["df_1h"], d["df_2h"], d["df_15m"], d["df_20m"], verbose=False,
        )
        # Dedup by (signal_time, direction, round(entry, 6)).
        seen: dict[tuple, dict] = {}
        for s in raw:
            key = (pd.Timestamp(s["signal_time"]), s["direction"],
                   round(float(s["entry"]), 6))
            if key not in seen:
                seen[key] = s
        deduped = list(seen.values())
        print(f"  signals raw={len(raw)} deduped={len(deduped)}")
        n_pre = 0
        for s in deduped:
            pc = precompute_signal(s, d["df_1m"])
            if pc is None:
                continue
            pc["asset"] = symbol
            pooled.append(pc)
            n_pre += 1
        print(f"  precomputed (1m slice available)={n_pre}")
    print(f"[INFO] pooled signals across {len(SYMBOLS)} assets = {len(pooled)}")
    return pooled


def monthly_metrics(closed: list[dict], rr: float):
    """closed = list of {month, R}. Returns monthly aggregate metrics + series."""
    by_month: dict[str, float] = defaultdict(float)
    for t in closed:
        by_month[t["month"]] += t["R"]
    months = sorted(by_month)
    vals = np.array([by_month[m] for m in months], dtype=np.float64)
    if vals.size == 0:
        return {
            "monthly_mean_R": 0.0, "pct_pos_months": 0.0,
            "worst_month_R": 0.0, "sharpe_monthly": 0.0,
        }, [], months
    mean = float(vals.mean())
    std = float(vals.std())  # population std
    sharpe = mean / std if std > 0 else 0.0
    pct_pos = float((vals > 0).sum()) / vals.size * 100.0
    worst = float(vals.min())
    series = [{"month": m, "R": round(float(by_month[m]), 4)} for m in months]
    return {
        "monthly_mean_R": round(mean, 4),
        "pct_pos_months": round(pct_pos, 2),
        "worst_month_R": round(worst, 4),
        "sharpe_monthly": round(sharpe, 4),
    }, series, months


def main() -> None:
    print("=" * 70)
    print("Strategy 1.1.4 financial backtest (BTC+ETH+SOL pooled)")
    print(f"RR grid: {RR_GRID}   window: {DAYS_BACK}d")
    print("=" * 70)
    pooled = collect_trades()

    if not pooled:
        print("[WARN] no signals")
        return

    per_rr = []
    # cache outcomes per RR keyed by index for reuse in monthly/per-asset.
    outcomes_by_rr: dict[float, list[dict]] = {}
    for rr in RR_GRID:
        trades = []
        for s in pooled:
            outcome = simulate(s, rr)
            trades.append({
                "asset": s["asset"],
                "signal_time": s["signal_time"],
                "month": s["signal_time"].strftime("%Y-%m"),
                "outcome": outcome,
            })
        outcomes_by_rr[rr] = trades
        wins = sum(1 for t in trades if t["outcome"] == "win")
        losses = sum(1 for t in trades if t["outcome"] == "loss")
        n_closed = wins + losses
        total_R = wins * rr - losses
        wr = (wins / n_closed * 100.0) if n_closed else 0.0
        closed_list = [
            {"month": t["month"], "R": (rr if t["outcome"] == "win" else -1.0)}
            for t in trades if t["outcome"] in ("win", "loss")
        ]
        mm, _series, _months = monthly_metrics(closed_list, rr)
        per_rr.append({
            "rr": rr,
            "wr": round(wr, 2),
            "total_R": round(total_R, 4),
            "n_closed": n_closed,
            "monthly_mean_R": mm["monthly_mean_R"],
            "pct_pos_months": mm["pct_pos_months"],
            "worst_month_R": mm["worst_month_R"],
            "sharpe_monthly": mm["sharpe_monthly"],
        })

    # best RR by sharpe / total_R
    best_rr_sharpe = max(per_rr, key=lambda r: r["sharpe_monthly"])["rr"]
    best_rr_totalR = max(per_rr, key=lambda r: r["total_R"])["rr"]

    # monthly_series + per_asset_totalR at best_rr_sharpe
    bs_trades = outcomes_by_rr[best_rr_sharpe]
    bs_closed = [
        {"month": t["month"], "R": (best_rr_sharpe if t["outcome"] == "win" else -1.0)}
        for t in bs_trades if t["outcome"] in ("win", "loss")
    ]
    _mm, monthly_series, _months = monthly_metrics(bs_closed, best_rr_sharpe)

    per_asset = defaultdict(float)
    for t in bs_trades:
        if t["outcome"] == "win":
            per_asset[t["asset"]] += best_rr_sharpe
        elif t["outcome"] == "loss":
            per_asset[t["asset"]] += -1.0
    per_asset_totalR = [
        {"asset": a, "total_R": round(float(per_asset.get(a, 0.0)), 4)}
        for a in SYMBOLS
    ]

    n_total_closed = sum(1 for t in outcomes_by_rr[RR_GRID[0]]
                         if t["outcome"] in ("win", "loss"))

    # ---- report ----
    print()
    print("=" * 70)
    print("PER-RR RESULTS (pooled BTC+ETH+SOL)")
    print("=" * 70)
    print(f"{'RR':>4} {'WR%':>6} {'totalR':>9} {'nClosed':>8} {'mMeanR':>8} "
          f"{'%pos':>6} {'worstM':>8} {'sharpe':>7}")
    for r in per_rr:
        print(f"{r['rr']:>4} {r['wr']:>6.2f} {r['total_R']:>9.2f} "
              f"{r['n_closed']:>8} {r['monthly_mean_R']:>8.3f} "
              f"{r['pct_pos_months']:>6.1f} {r['worst_month_R']:>8.2f} "
              f"{r['sharpe_monthly']:>7.3f}")
    print()
    print(f"n_total_closed (RR-invariant) = {n_total_closed}")
    print(f"best_rr_sharpe = {best_rr_sharpe}   best_rr_totalR = {best_rr_totalR}")
    print()
    print(f"per_asset_totalR @ RR={best_rr_sharpe}:")
    for pa in per_asset_totalR:
        print(f"  {pa['asset']}: {pa['total_R']:+.2f}R")
    print()
    print(f"monthly_series @ RR={best_rr_sharpe} ({len(monthly_series)} months):")
    for ms in monthly_series:
        print(f"  {ms['month']}: {ms['R']:+.2f}R")

    # Stash structured-ish dump for the harness to parse if needed.
    import json
    result = {
        "strategy": "1.1.4",
        "ran_ok": True,
        "n_total_closed": n_total_closed,
        "per_rr": per_rr,
        "best_rr_sharpe": best_rr_sharpe,
        "best_rr_totalR": best_rr_totalR,
        "monthly_series": monthly_series,
        "per_asset_totalR": per_asset_totalR,
    }
    print()
    print("JSON_RESULT_BEGIN")
    print(json.dumps(result))
    print("JSON_RESULT_END")


if __name__ == "__main__":
    main()
