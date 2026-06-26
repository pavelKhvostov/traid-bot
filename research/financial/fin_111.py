"""Financial backtest of Strategy 1.1.1 (SWEPT, canonical) on BTC+ETH+SOL.

Config (canonical, per CLAUDE.md / project_111_approved):
  - SWEPT filter ON (OB-1h/2h pair sweeps min/max of two previous candles)
  - entry_pct = 0.80 (0.80 into the entry-FVG)
  - sl_pct = 0.35 (symmetric between ob_htf edge and FVG entry edge)
  - no_entry = ON (cancel if TP would be hit before entry fill)

This script sweeps RR in {1.0,1.5,2.0,2.2,2.5,3.0,3.5} and computes per-RR
win rate, total_R (= wins*RR - losses), n_closed, plus MONTHLY metrics
(monthly R grouped by calendar month UTC of signal_time).

Reuses the validated sim engine: limit fill waits for price to touch entry
from c2.close + tf_minutes; SL/TP scanned from the FILL bar forward (no
entry-bar lookahead); pnl = +RR if TP first else -1 if SL first; not-filled
and open trades dropped. Signals pooled across the 3 assets and deduped by
(signal_time, direction, round(entry,6)).

Started from research/1_1_1/analyze/analyze_1_1_1_swept_multi_asset.py.
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
from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals

DAYS_BACK = 2400  # full history
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
ENTRY_PCT = 0.80
SL_PCT = 0.35
RR_GRID = [1.0, 1.5, 2.0, 2.2, 2.5, 3.0, 3.5]


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
    """Forward 1m bars start at c2.close + tf_minutes (no entry-bar lookahead)."""
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
    }


def simulate_with_no_entry(s: dict, entry: float, sl: float, tp: float) -> str:
    """Limit-fill: wait for price to touch entry; then SL/TP from FILL bar fwd.

    no_entry: if TP level reached before entry fill -> setup voided.
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


def build_cache_for_symbol(symbol: str) -> list[dict]:
    """Detect SWEPT signals for one symbol; return precomputed sim caches."""
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
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f = df_1d[df_1d.index >= cutoff]
    print(f"  data: 1d={len(df_1d_f)} 4h={len(df_4h)} 1h={len(df_1h)} "
          f"15m={len(df_15m)} 1m={len(df_1m)}")

    raw = detect_strategy_1_1_1_signals(
        df_1d_f, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m, verbose=False,
    )

    # SWEPT filter + dedup the SWEPT path-groups (round entry to 2 for grouping
    # of equivalent paths, as in the validated analyze script).
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
    print(f"  raw paths: {len(raw)}  deduped groups: {len(groups)}  "
          f"SWEPT reps: {len(swept_reps)}  cache: {len(cache)}")
    for c in cache:
        c["symbol"] = symbol
    return cache


def recompute_levels(s: dict, rr: float) -> tuple[float, float, float] | None:
    """Canonical entry/sl/tp recompute.

    entry = 0.80 into entry-FVG (from the market-facing edge).
    sl = 0.35 symmetric between ob_htf edge and FVG entry edge.
    """
    fw = s["fvg_t"] - s["fvg_b"]
    if s["direction"] == "LONG":
        entry = s["fvg_b"] + ENTRY_PCT * fw
        sl = s["obh_b"] + SL_PCT * (s["fvg_b"] - s["obh_b"])
        if sl >= entry:
            return None
        risk = entry - sl
        tp = entry + rr * risk
    else:
        entry = s["fvg_t"] - ENTRY_PCT * fw
        sl = s["obh_t"] - SL_PCT * (s["obh_t"] - s["fvg_t"])
        if sl <= entry:
            return None
        risk = sl - entry
        tp = entry - rr * risk
    return entry, sl, tp


def monthly_stats(month_R: dict[str, float]) -> dict:
    """Given dict month -> sum R, compute monthly metrics."""
    if not month_R:
        return {"monthly_mean_R": 0.0, "pct_pos_months": 0.0,
                "worst_month_R": 0.0, "sharpe_monthly": 0.0}
    vals = np.array(list(month_R.values()), dtype=np.float64)
    mean = float(vals.mean())
    std = float(vals.std(ddof=0))
    pct_pos = float((vals > 0).sum() / len(vals) * 100.0)
    worst = float(vals.min())
    sharpe = float(mean / std) if std > 0 else 0.0
    return {"monthly_mean_R": mean, "pct_pos_months": pct_pos,
            "worst_month_R": worst, "sharpe_monthly": sharpe}


def main() -> dict:
    print(f"[INFO] 1.1.1 SWEPT financial: entry={ENTRY_PCT} sl_pct={SL_PCT} "
          f"no_entry=on RR_grid={RR_GRID}")
    print(f"       symbols={SYMBOLS}, window {DAYS_BACK}d")

    # Build per-symbol caches once.
    all_cache: list[dict] = []
    for sym in SYMBOLS:
        all_cache.extend(build_cache_for_symbol(sym))

    print(f"\nPooled SWEPT cache across assets: {len(all_cache)}")

    per_rr = []
    best_sharpe = -1e18; best_rr_sharpe = RR_GRID[0]
    best_total = -1e18; best_rr_totalR = RR_GRID[0]
    cache_at_best_sharpe = None

    for rr in RR_GRID:
        # Dedup pooled signals by (signal_time, direction, round(entry,6)).
        seen = set()
        trades = []  # list of (signal_time, symbol, outcome_R or None, month)
        wins = losses = 0
        month_R: dict[str, float] = defaultdict(float)
        asset_R: dict[str, float] = defaultdict(float)
        for s in all_cache:
            lv = recompute_levels(s, rr)
            if lv is None:
                continue
            entry, sl, tp = lv
            key = (s["signal_time"], s["direction"], round(entry, 6))
            if key in seen:
                continue
            seen.add(key)
            outcome = simulate_with_no_entry(s, entry, sl, tp)
            if outcome == "win":
                r = rr; wins += 1
            elif outcome == "loss":
                r = -1.0; losses += 1
            else:
                continue  # drop no_entry / not_filled / open
            month = pd.Timestamp(s["signal_time"]).strftime("%Y-%m")
            month_R[month] += r
            asset_R[s["symbol"]] += r

        n_closed = wins + losses
        total_R = wins * rr - losses
        wr = (wins / n_closed * 100.0) if n_closed else 0.0
        ms = monthly_stats(month_R)
        row = {
            "rr": rr, "wr": round(wr, 2), "total_R": round(total_R, 4),
            "n_closed": n_closed,
            "monthly_mean_R": round(ms["monthly_mean_R"], 4),
            "pct_pos_months": round(ms["pct_pos_months"], 2),
            "worst_month_R": round(ms["worst_month_R"], 4),
            "sharpe_monthly": round(ms["sharpe_monthly"], 4),
        }
        per_rr.append(row)
        print(f"  RR={rr}: closed={n_closed} WR={wr:.1f}% totalR={total_R:+.2f} "
              f"mMeanR={ms['monthly_mean_R']:+.3f} pctPos={ms['pct_pos_months']:.1f}% "
              f"worst={ms['worst_month_R']:+.2f} sharpe={ms['sharpe_monthly']:.3f}")

        if ms["sharpe_monthly"] > best_sharpe:
            best_sharpe = ms["sharpe_monthly"]; best_rr_sharpe = rr
            cache_at_best_sharpe = (dict(month_R), dict(asset_R))
        if total_R > best_total:
            best_total = total_R; best_rr_totalR = rr

    # monthly_series + per_asset at best_rr_sharpe
    month_R_best, asset_R_best = cache_at_best_sharpe
    monthly_series = [{"month": m, "R": round(float(month_R_best[m]), 4)}
                      for m in sorted(month_R_best.keys())]
    per_asset_totalR = [{"asset": a, "total_R": round(float(asset_R_best.get(a, 0.0)), 4)}
                        for a in SYMBOLS]
    n_total_closed = sum(r["n_closed"] for r in per_rr if r["rr"] == best_rr_sharpe)

    print("\n" + "=" * 80)
    print(f"BEST by sharpe: RR={best_rr_sharpe} (sharpe={best_sharpe:.4f})")
    print(f"BEST by totalR: RR={best_rr_totalR} (totalR={best_total:+.2f})")
    print(f"per_asset_totalR @ best_sharpe: {per_asset_totalR}")
    print(f"months @ best_sharpe: {len(monthly_series)}")

    return {
        "per_rr": per_rr,
        "best_rr_sharpe": best_rr_sharpe,
        "best_rr_totalR": best_rr_totalR,
        "monthly_series": monthly_series,
        "per_asset_totalR": per_asset_totalR,
        "n_total_closed": n_total_closed,
    }


if __name__ == "__main__":
    import json
    res = main()
    print("\n===JSON_RESULT_START===")
    print(json.dumps(res))
    print("===JSON_RESULT_END===")
