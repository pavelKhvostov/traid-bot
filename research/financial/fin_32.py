"""Financial backtest for Strategy 3.2 (key=32) on BTC+ETH+SOL, RR-sweep + monthly.

Strategy 3.2: FVG-4h -> first failed-touch (2 свечи rejection) -> FVG-1h в 8h окне.
  Detector: strategies/strategy_3_2.py:detect_strategy_3_2_signals
  Native entry/sl/tp/risk (native RR=1.0). We IGNORE native tp and sweep RR grid
  on top: TP = RR * risk.

Simulation (no entry-bar lookahead, limit-fill = wait for touch):
  - Entry is a LIMIT order: from c2_close+tf_minutes (signal_time + 60m, FVG-1h),
    wait until price (1m) touches `entry`.
        LONG : low  <= entry
        SHORT: high >= entry
  - From the FILL bar FORWARD, scan SL (=1R) vs TP (=RR*risk):
        LONG : SL low<=sl, TP high>=tp
        SHORT: SL high>=sl, TP low<=tp
  - no_entry: if TP would be touched BEFORE entry is filled (price ran away).
  - pnl per closed trade = +RR if TP first else -1 if SL first.
  - drop not_filled / open.

Dedup signals by (signal_time, direction, round(entry,6)) across the pool.
Pool the 3 assets, then per RR: wr, total_R (=wins*RR-losses), n_closed, monthly.

Reuses the project's validated simulate_with_no_entry pattern
(see research/1_1_1/analyze/analyze_1_1_1_swept_monthly.py).
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

from data_manager import load_df
from strategies.strategy_3_2 import detect_strategy_3_2_signals

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
DAYS_BACK = 2400
RR_GRID = [1.0, 1.5, 2.0, 2.2, 2.5, 3.0, 3.5]
TF_MINUTES = 60  # entry FVG is on 1h; signal_time = c2 of FVG-1h


def precompute_signal(sig: dict, df_1m: pd.DataFrame) -> dict | None:
    """Cache forward 1m highs/lows starting at signal_time + tf_minutes.

    Forward starts at c2_close (= signal_time which is c2_open) + tf_minutes,
    i.e. the FIRST bar AFTER the signal candle closes -> no entry-bar lookahead.
    """
    forward_start = sig["signal_time"] + pd.Timedelta(minutes=TF_MINUTES)
    forward = df_1m[df_1m.index >= forward_start]
    if forward.empty:
        return None
    return {
        "signal_time": sig["signal_time"],
        "direction": sig["direction"],
        "entry": float(sig["entry"]),
        "sl": float(sig["sl"]),
        "risk": float(sig["risk"]),
        "highs": forward["high"].values.astype(np.float64),
        "lows": forward["low"].values.astype(np.float64),
    }


def simulate_with_no_entry(s: dict, entry: float, sl: float, tp: float) -> str:
    """Limit-fill then SL/TP scan from fill bar forward. No entry-bar lookahead."""
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
    # price ran to TP before our limit got filled -> we'd never have entered
    if tp_pre_idx < entry_idx:
        return "no_entry"
    if entry_idx >= n:
        return "not_filled"
    post_l = lows[entry_idx:]
    post_h = highs[entry_idx:]
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
    return "win" if tp_first < sl_first else "loss"


def build_cache() -> tuple[list[dict], dict[str, list[dict]]]:
    """Detect signals on all assets, dedup, precompute 1m forward arrays.

    Returns (pooled_cache, per_asset_cache_keys) where pooled_cache items carry
    an 'asset' field; dedup is GLOBAL by (signal_time, direction, round(entry,6)).
    """
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)

    pooled: list[dict] = []
    per_asset_raw: dict[str, int] = {}
    seen: set[tuple] = set()

    for sym in SYMBOLS:
        df_4h = load_df(sym, "4h")
        df_1h = load_df(sym, "1h")
        df_1m = load_df(sym, "1m")
        df_4h = df_4h[df_4h.index >= cutoff]
        df_1h_f = df_1h[df_1h.index >= cutoff]

        raw = detect_strategy_3_2_signals(df_4h, df_1h_f, verbose=False)
        per_asset_raw[sym] = len(raw)

        for sig in raw:
            key = (pd.Timestamp(sig["signal_time"]), sig["direction"],
                   round(float(sig["entry"]), 6))
            if key in seen:
                continue
            seen.add(key)
            if float(sig["risk"]) <= 0:
                continue
            cached = precompute_signal(sig, df_1m)
            if cached is None:
                continue
            cached["asset"] = sym
            pooled.append(cached)

    return pooled, per_asset_raw


def eval_rr(cache: list[dict], rr: float) -> dict:
    """Simulate all cached signals at a given RR; return aggregate + trade list."""
    trades = []
    for s in cache:
        entry = s["entry"]
        sl = s["sl"]
        risk = s["risk"]
        if s["direction"] == "LONG":
            tp = entry + rr * risk
        else:
            tp = entry - rr * risk
        outcome = simulate_with_no_entry(s, entry, sl, tp)
        trades.append({
            "signal_time": pd.Timestamp(s["signal_time"]),
            "direction": s["direction"],
            "asset": s["asset"],
            "outcome": outcome,
        })
    df = pd.DataFrame(trades)
    closed = df[df["outcome"].isin(["win", "loss"])].copy()
    wins = int((closed["outcome"] == "win").sum())
    losses = int((closed["outcome"] == "loss").sum())
    n_closed = wins + losses
    total_R = wins * rr - losses
    wr = (wins / n_closed * 100.0) if n_closed else 0.0

    # per-trade R for monthly aggregation
    closed["R"] = np.where(closed["outcome"] == "win", rr, -1.0)
    closed["month"] = closed["signal_time"].dt.strftime("%Y-%m")

    monthly = closed.groupby("month")["R"].sum().sort_index()
    n_months = len(monthly)
    if n_months:
        monthly_mean_R = float(monthly.mean())
        pct_pos_months = float((monthly > 0).sum() / n_months * 100.0)
        worst_month_R = float(monthly.min())
        std = float(monthly.std(ddof=0))
        sharpe_monthly = float(monthly_mean_R / std) if std > 0 else 0.0
    else:
        monthly_mean_R = 0.0
        pct_pos_months = 0.0
        worst_month_R = 0.0
        sharpe_monthly = 0.0

    return {
        "rr": rr,
        "wr": round(wr, 2),
        "total_R": round(float(total_R), 4),
        "n_closed": n_closed,
        "monthly_mean_R": round(monthly_mean_R, 4),
        "pct_pos_months": round(pct_pos_months, 2),
        "worst_month_R": round(worst_month_R, 4),
        "sharpe_monthly": round(sharpe_monthly, 4),
        "_monthly": monthly,
        "_closed": closed,
    }


def main() -> None:
    print("[INFO] Strategy 3.2 financial backtest — BTC+ETH+SOL pooled")
    print(f"       DAYS_BACK={DAYS_BACK}, RR_GRID={RR_GRID}, TF_MINUTES={TF_MINUTES}")
    cache, per_asset_raw = build_cache()
    print(f"[INFO] raw signals per asset: {per_asset_raw}")
    print(f"[INFO] pooled deduped cache (with 1m forward): {len(cache)}")

    results = [eval_rr(cache, rr) for rr in RR_GRID]

    print()
    print("=" * 100)
    print(f"{'RR':>5} {'WR%':>7} {'totalR':>10} {'closed':>7} "
          f"{'mMeanR':>8} {'pos%':>7} {'worstM':>8} {'sharpe':>8}")
    print("-" * 100)
    for r in results:
        print(f"{r['rr']:>5} {r['wr']:>7} {r['total_R']:>10} {r['n_closed']:>7} "
              f"{r['monthly_mean_R']:>8} {r['pct_pos_months']:>7} "
              f"{r['worst_month_R']:>8} {r['sharpe_monthly']:>8}")

    best_sharpe = max(results, key=lambda r: r["sharpe_monthly"])
    best_total = max(results, key=lambda r: r["total_R"])
    print()
    print(f"[BEST] best_rr_sharpe = {best_sharpe['rr']} "
          f"(sharpe={best_sharpe['sharpe_monthly']})")
    print(f"[BEST] best_rr_totalR = {best_total['rr']} "
          f"(totalR={best_total['total_R']})")

    # monthly_series + per_asset_totalR at best_rr_sharpe
    bs = best_sharpe
    monthly_series = [{"month": m, "R": round(float(v), 4)}
                      for m, v in bs["_monthly"].items()]
    closed_bs = bs["_closed"]
    per_asset = []
    for sym in SYMBOLS:
        sub = closed_bs[closed_bs["asset"] == sym]
        per_asset.append({"asset": sym, "total_R": round(float(sub["R"].sum()), 4)})

    print()
    print("[MONTHLY @ best_rr_sharpe]")
    for ms in monthly_series:
        print(f"  {ms['month']}: {ms['R']}")
    print()
    print("[PER-ASSET totalR @ best_rr_sharpe]")
    for pa in per_asset:
        print(f"  {pa['asset']}: {pa['total_R']}")

    # emit machine-readable footer
    import json
    payload = {
        "n_total_closed": int(sum(r["n_closed"] for r in results)),
        "per_rr": [{k: r[k] for k in (
            "rr", "wr", "total_R", "n_closed", "monthly_mean_R",
            "pct_pos_months", "worst_month_R", "sharpe_monthly")} for r in results],
        "best_rr_sharpe": best_sharpe["rr"],
        "best_rr_totalR": best_total["rr"],
        "monthly_series": monthly_series,
        "per_asset_totalR": per_asset,
    }
    print()
    print("===JSON_START===")
    print(json.dumps(payload))
    print("===JSON_END===")


if __name__ == "__main__":
    main()
