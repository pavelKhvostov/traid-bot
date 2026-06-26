"""Financial backtest of Strategy 1.1.2 (key=112) on BTC+ETH+SOL, RR grid + monthly metrics.

Strategy 1.1.2: OB-{1d,12h} + OB-{4h,6h} -> OB-{1h,2h} + FVG-{15m,20m}.
Config (canonical / validated): ALL (no SWEPT filter), entry_pct=0.70, sl_pct=0.35.

  LONG:  entry = fvg.bottom + 0.70 * (fvg.top - fvg.bottom)
         sl    = ob_htf.bottom + 0.35 * (fvg.bottom - ob_htf.bottom)
         risk  = entry - sl ; tp = entry + RR * risk
  SHORT: entry = fvg.top - 0.70 * (fvg.top - fvg.bottom)
         sl    = ob_htf.top - 0.35 * (ob_htf.top - fvg.top)
         risk  = sl - entry ; tp = entry - RR * risk

Sim (reuses validated simulate_with_no_entry from research/1_1_2 scripts):
  - limit-fill: wait for price to TOUCH entry, starting from c2.close + tf_minutes
    (15m FVG -> +15m, 20m FVG -> +20m). NO entry-bar lookahead.
  - if TP would be reached before entry is filled -> no_entry (discard).
  - from the FILL bar forward, scan SL(=1R) vs TP(=RR*risk); first hit wins.
  - pnl per trade: +RR if TP first, -1 if SL first. open / not_filled / no_entry dropped.

Dedup signals by (signal_time, direction, round(entry,6)). Pool the 3 assets.

For each RR: wr, total_R (=wins*RR - losses), n_closed, plus MONTHLY metrics
(group closed trades by UTC calendar month of signal_time; months with >=1 trade):
  monthly_mean_R, pct_pos_months, worst_month_R, sharpe_monthly (mean/std, 0 if std=0).
best_rr_sharpe = RR max sharpe_monthly ; best_rr_totalR = RR max total_R.
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

import json
from collections import defaultdict

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_2 import detect_strategy_1_1_2_signals

DAYS_BACK = 1095
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
ENTRY_PCT = 0.70
SL_PCT = 0.35
RR_GRID = [1.0, 1.5, 2.0, 2.2, 2.5, 3.0, 3.5]


def precompute(sig: dict, df_1m: pd.DataFrame) -> dict | None:
    """Recompute entry/sl from zones; cache forward 1m highs/lows from c2.close+tf_minutes.

    forward starts at signal_time + tf_minutes -> this is c2.close (the FVG c2 bar has
    already closed). No entry-bar lookahead: fill must be a TOUCH at/after this point.
    """
    fvg_b, fvg_t = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    direction = sig["direction"]
    tf_minutes = 15 if sig["fvg_tf"] == "15m" else 20
    sig_time = pd.Timestamp(sig["signal_time"])
    if sig_time.tz is None:
        sig_time = sig_time.tz_localize("UTC")
    forward = df_1m[df_1m.index >= sig_time + pd.Timedelta(minutes=tf_minutes)]
    if forward.empty:
        return None

    fw = float(fvg_t) - float(fvg_b)
    if direction == "LONG":
        entry = float(fvg_b) + ENTRY_PCT * fw
        sl = float(obh_b) + SL_PCT * (float(fvg_b) - float(obh_b))
        if sl >= entry:
            return None
        risk = entry - sl
    else:
        entry = float(fvg_t) - ENTRY_PCT * fw
        sl = float(obh_t) - SL_PCT * (float(obh_t) - float(fvg_t))
        if sl <= entry:
            return None
        risk = sl - entry
    if risk <= 0:
        return None

    return {
        "signal_time": sig_time,
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "risk": risk,
        "highs": forward["high"].values.astype(np.float64),
        "lows": forward["low"].values.astype(np.float64),
    }


def simulate_with_no_entry(s: dict, entry: float, sl: float, tp: float) -> str:
    """Validated engine: wait for touch (fill), then SL/TP from fill bar forward."""
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
    if sl_first == -1 and tp_first == -1:
        return "open"
    if sl_first == -1:
        return "win"
    if tp_first == -1:
        return "loss"
    return "win" if tp_first < sl_first else "loss"


def build_cache_for_symbol(symbol: str) -> list[dict]:
    """Detect + dedup 1.1.2 signals for one symbol; return precomputed cache."""
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

    raw = detect_strategy_1_1_2_signals(
        df_1d_f, df_12h_f, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m, verbose=False,
    )

    # Dedup by (signal_time, direction, round(entry,6)) -- keep first path.
    groups = defaultdict(list)
    for s in raw:
        key = (pd.Timestamp(s["signal_time"]), s["direction"], round(float(s["entry"]), 6))
        groups[key].append(s)
    deduped = [g[0] for g in groups.values()]

    cache = [c for c in (precompute(s, df_1m) for s in deduped) if c is not None]
    print(f"  {symbol}: raw={len(raw)} deduped={len(deduped)} cache={len(cache)}")
    return cache


def run_rr(cache: list[dict], rr: float) -> list[dict]:
    """Simulate every cached signal at this RR; return list of closed-trade records."""
    closed = []
    for s in cache:
        entry, sl, risk = s["entry"], s["sl"], s["risk"]
        if s["direction"] == "LONG":
            tp = entry + rr * risk
        else:
            tp = entry - rr * risk
        outcome = simulate_with_no_entry(s, entry, sl, tp)
        if outcome == "win":
            closed.append({"signal_time": s["signal_time"], "direction": s["direction"],
                           "symbol": s["symbol"], "R": rr})
        elif outcome == "loss":
            closed.append({"signal_time": s["signal_time"], "direction": s["direction"],
                           "symbol": s["symbol"], "R": -1.0})
        # no_entry / open / not_filled -> dropped
    return closed


def monthly_metrics(closed: list[dict]) -> dict:
    """Group closed trades by UTC calendar month of signal_time; compute month-level stats."""
    if not closed:
        return {"monthly_mean_R": 0.0, "pct_pos_months": 0.0, "worst_month_R": 0.0,
                "sharpe_monthly": 0.0, "monthly_series": []}
    month_R: dict[str, float] = defaultdict(float)
    for t in closed:
        m = pd.Timestamp(t["signal_time"]).tz_convert("UTC").strftime("%Y-%m")
        month_R[m] += t["R"]
    months = sorted(month_R.keys())
    vals = np.array([month_R[m] for m in months], dtype=np.float64)
    mean = float(vals.mean())
    std = float(vals.std())  # population std
    sharpe = mean / std if std > 0 else 0.0
    pct_pos = float((vals > 0).sum() / len(vals) * 100.0)
    worst = float(vals.min())
    series = [{"month": m, "R": round(float(month_R[m]), 4)} for m in months]
    return {"monthly_mean_R": round(mean, 4), "pct_pos_months": round(pct_pos, 2),
            "worst_month_R": round(worst, 4), "sharpe_monthly": round(sharpe, 4),
            "monthly_series": series}


def main() -> None:
    print(f"[INFO] fin_112: Strategy 1.1.2 multi-asset RR grid")
    print(f"       symbols={SYMBOLS} window={DAYS_BACK}d entry={ENTRY_PCT} sl_pct={SL_PCT}")
    print(f"       RR grid={RR_GRID}")
    print()

    # Build pooled cache (tag each cached signal with its symbol).
    pooled_cache: list[dict] = []
    for sym in SYMBOLS:
        c = build_cache_for_symbol(sym)
        for x in c:
            x["symbol"] = sym
        pooled_cache.extend(c)
    print(f"\n  POOLED cache (3 assets): {len(pooled_cache)}")

    per_rr = []
    best_sharpe_val = -1e9
    best_sharpe_rr = None
    best_totalR_val = -1e9
    best_totalR_rr = None
    closed_by_rr: dict[float, list[dict]] = {}

    print()
    print("=" * 100)
    print(f"{'RR':>5} {'n_closed':>9} {'wins':>6} {'losses':>7} {'WR%':>6} "
          f"{'total_R':>9} {'mMeanR':>8} {'%posM':>7} {'worstM':>8} {'sharpe':>7}")
    print("=" * 100)
    for rr in RR_GRID:
        closed = run_rr(pooled_cache, rr)
        closed_by_rr[rr] = closed
        wins = sum(1 for t in closed if t["R"] > 0)
        losses = sum(1 for t in closed if t["R"] < 0)
        n_closed = wins + losses
        total_R = wins * rr - losses
        wr = (wins / n_closed * 100.0) if n_closed else 0.0
        mm = monthly_metrics(closed)
        per_rr.append({
            "rr": rr, "wr": round(wr, 2), "total_R": round(total_R, 4),
            "n_closed": n_closed,
            "monthly_mean_R": mm["monthly_mean_R"], "pct_pos_months": mm["pct_pos_months"],
            "worst_month_R": mm["worst_month_R"], "sharpe_monthly": mm["sharpe_monthly"],
        })
        print(f"{rr:>5.1f} {n_closed:>9} {wins:>6} {losses:>7} {wr:>6.1f} "
              f"{total_R:>9.2f} {mm['monthly_mean_R']:>8.3f} {mm['pct_pos_months']:>7.1f} "
              f"{mm['worst_month_R']:>8.2f} {mm['sharpe_monthly']:>7.3f}")
        if mm["sharpe_monthly"] > best_sharpe_val:
            best_sharpe_val = mm["sharpe_monthly"]; best_sharpe_rr = rr
        if total_R > best_totalR_val:
            best_totalR_val = total_R; best_totalR_rr = rr

    # monthly_series + per_asset_totalR at best_rr_sharpe.
    best_closed = closed_by_rr[best_sharpe_rr]
    mm_best = monthly_metrics(best_closed)
    monthly_series = mm_best["monthly_series"]

    per_asset = defaultdict(float)
    for t in best_closed:
        per_asset[t["symbol"]] += t["R"]
    per_asset_totalR = [{"asset": a, "total_R": round(per_asset.get(a, 0.0), 4)} for a in SYMBOLS]

    total_closed_all = len(closed_by_rr[RR_GRID[0]])  # same dedup set; n_closed varies per RR

    print()
    print("=" * 100)
    print(f"best_rr_sharpe = {best_sharpe_rr} (sharpe={best_sharpe_val:.4f})")
    print(f"best_rr_totalR = {best_totalR_rr} (total_R={best_totalR_val:.2f})")
    print(f"per_asset_totalR @ best_rr_sharpe: {per_asset_totalR}")
    print(f"n closed @ RR={RR_GRID[0]}: {total_closed_all}")
    print("=" * 100)

    result = {
        "strategy": "1.1.2",
        "ran_ok": True,
        "n_total_closed": total_closed_all,
        "per_rr": per_rr,
        "best_rr_sharpe": best_sharpe_rr,
        "best_rr_totalR": best_totalR_rr,
        "monthly_series": monthly_series,
        "per_asset_totalR": per_asset_totalR,
    }
    print("\n[JSON_RESULT]")
    print(json.dumps(result, default=str))


if __name__ == "__main__":
    main()
