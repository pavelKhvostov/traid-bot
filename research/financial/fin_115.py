"""Financial backtest: Strategy 1.1.5 on BTC+ETH+SOL, RR grid + monthly metrics.

Detector strategies/strategy_1_1_5.py returns ZONES ONLY
  (macro_ob_zone, ob_htf_zone, fvg_entry_zone, signal_time=fvg_entry.c2_time).
Downstream we apply the canonical 1.1.1 convention:
  - entry = 0.80 into fvg_entry_zone
  - sl = 0.35 sym between ob_htf edge and fvg edge
  - TP = RR * risk
Limit-fill: wait until price touches `entry` from c2.close + tf_minutes forward
  (NO entry-bar lookahead). Then SL/TP scanned from the FILL bar forward.
  pnl per trade = +RR if TP first else -1 if SL first. Drop not_filled / open / no_entry.
Dedup by (signal_time, direction, round(entry,6)). Pool the 3 assets.

REUSES the project's validated sim engine (simulate_with_no_entry +
pnl = wins*RR - losses), identical to research/1_1_1/analyze/analyze_1_1_1_swept_monthly.py.
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
from strategies.strategy_1_1_5 import detect_strategy_1_1_5_signals

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
DAYS_BACK = 2400  # full history
ENTRY_PCT = 0.80
SL_PCT = 0.35
RR_GRID = [1.0, 1.5, 2.0, 2.2, 2.5, 3.0, 3.5]
K_AFTER = 3  # canonical 1.1.5 window


def precompute_signal(sig: dict, df_1m: pd.DataFrame) -> dict | None:
    """Build the forward 1m highs/lows window starting at c2.close + tf_minutes.

    fvg_entry.c2_time is the OPEN time of the 3rd FVG candle; that candle closes
    at c2_time + tf_minutes. Forward scan therefore begins at c2_time + tf_minutes
    => no entry-bar lookahead (the signal candle itself is excluded).
    """
    fvg_b, fvg_t = sig["fvg_entry_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    direction = sig["direction"]
    tf_minutes = 15 if sig["fvg_entry_tf"] == "15m" else 20
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
    """Validated engine: limit-fill (wait touch), then SL/TP from fill bar forward.

    Returns one of: win / loss / no_entry / not_filled / open.
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
    if sl_first == -1 and tp_first == -1:
        return "open"
    if sl_first == -1:
        return "win"
    if tp_first == -1:
        return "loss"
    return "win" if tp_first < sl_first else "loss"


def build_cache_for_symbol(symbol: str) -> list[dict]:
    """Detect 1.1.5 signals for one symbol, dedup, precompute forward windows.

    Dedup key = (signal_time, direction, round(entry,6)) where entry is the
    0.80-into-FVG entry price (the trade-level identity).
    """
    df_1d = load_df(symbol, "1d")
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

    raw = detect_strategy_1_1_5_signals(
        df_1d_f, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
        k_after=K_AFTER, verbose=False,
    )

    # Compute entry per signal for dedup, then keep first per dedup key.
    seen = set()
    deduped = []
    for s in raw:
        fvg_b, fvg_t = s["fvg_entry_zone"]
        fw = float(fvg_t) - float(fvg_b)
        if s["direction"] == "LONG":
            entry = float(fvg_b) + ENTRY_PCT * fw
        else:
            entry = float(fvg_t) - ENTRY_PCT * fw
        key = (s["signal_time"], s["direction"], round(entry, 6))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(s)

    cache = []
    for s in deduped:
        c = precompute_signal(s, df_1m)
        if c is not None:
            c["symbol"] = symbol
            cache.append(c)
    print(f"  [{symbol}] raw={len(raw)} deduped={len(deduped)} cache={len(cache)}")
    return cache


def trade_R(s: dict, rr: float) -> tuple[str, float, str] | None:
    """Return (outcome, R, symbol) for a closed trade; None if not closed/invalid."""
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
    outcome = simulate_with_no_entry(s, entry, sl, tp)
    if outcome == "win":
        return ("win", rr, s["symbol"])
    if outcome == "loss":
        return ("loss", -1.0, s["symbol"])
    return None  # no_entry / not_filled / open dropped


def main() -> None:
    print(f"[INFO] Strategy 1.1.5 financial backtest, RR grid {RR_GRID}")
    print(f"       entry={ENTRY_PCT}, sl={SL_PCT} sym, k_after={K_AFTER}, "
          f"days_back={DAYS_BACK}, symbols={SYMBOLS}")
    print()

    pooled_cache: list[dict] = []
    for sym in SYMBOLS:
        pooled_cache.extend(build_cache_for_symbol(sym))
    print(f"[INFO] pooled cache (3 assets): {len(pooled_cache)}")
    print()

    per_rr = []
    best_sharpe = -1e9
    best_rr_sharpe = RR_GRID[0]
    best_totalR = -1e9
    best_rr_totalR = RR_GRID[0]
    monthly_at_best_sharpe = []
    per_asset_at_best_sharpe = {}

    # n_total_closed = max number of closed trades across the grid is not meaningful
    # (closed count varies by RR because no_entry depends on tp). Report the count
    # at RR=2.2 (canonical) as a stable reference; also keep per-RR n_closed.
    n_total_closed_ref = 0

    for rr in RR_GRID:
        results = []
        for s in pooled_cache:
            r = trade_R(s, rr)
            if r is not None:
                results.append((s["signal_time"], r[0], r[1], r[2]))
        wins = sum(1 for _, o, _, _ in results if o == "win")
        losses = sum(1 for _, o, _, _ in results if o == "loss")
        n_closed = wins + losses
        total_R = wins * rr - losses
        wr = (wins / n_closed * 100.0) if n_closed else 0.0

        # Monthly grouping (UTC calendar month of signal_time)
        monthly = defaultdict(float)
        for st, _o, rval, _sym in results:
            month = pd.Timestamp(st).tz_convert("UTC").to_period("M").strftime("%Y-%m") \
                if pd.Timestamp(st).tz is not None \
                else pd.Timestamp(st).to_period("M").strftime("%Y-%m")
            monthly[month] += rval
        month_vals = np.array(list(monthly.values()), dtype=np.float64) if monthly else np.array([])
        if month_vals.size:
            monthly_mean_R = float(month_vals.mean())
            pct_pos_months = float((month_vals > 0).sum() / month_vals.size * 100.0)
            worst_month_R = float(month_vals.min())
            std = float(month_vals.std())  # population std
            sharpe_monthly = float(monthly_mean_R / std) if std > 0 else 0.0
        else:
            monthly_mean_R = 0.0
            pct_pos_months = 0.0
            worst_month_R = 0.0
            sharpe_monthly = 0.0

        per_rr.append({
            "rr": rr,
            "wr": round(wr, 2),
            "total_R": round(total_R, 4),
            "n_closed": n_closed,
            "monthly_mean_R": round(monthly_mean_R, 4),
            "pct_pos_months": round(pct_pos_months, 2),
            "worst_month_R": round(worst_month_R, 4),
            "sharpe_monthly": round(sharpe_monthly, 4),
        })

        if rr == 2.2:
            n_total_closed_ref = n_closed

        if sharpe_monthly > best_sharpe:
            best_sharpe = sharpe_monthly
            best_rr_sharpe = rr
            monthly_at_best_sharpe = sorted(
                [{"month": m, "R": round(v, 4)} for m, v in monthly.items()],
                key=lambda x: x["month"],
            )
            pa = defaultdict(float)
            for st, _o, rval, sym in results:
                pa[sym] += rval
            per_asset_at_best_sharpe = dict(pa)

        if total_R > best_totalR:
            best_totalR = total_R
            best_rr_totalR = rr

        print(f"  RR={rr}: closed={n_closed} WR={wr:.1f}% totalR={total_R:.2f} "
              f"mMeanR={monthly_mean_R:.3f} %pos={pct_pos_months:.0f} "
              f"worst={worst_month_R:.2f} sharpe={sharpe_monthly:.3f}")

    print()
    print(f"[BEST] best_rr_sharpe={best_rr_sharpe} (sharpe={best_sharpe:.4f})")
    print(f"[BEST] best_rr_totalR={best_rr_totalR} (totalR={best_totalR:.2f})")
    print(f"[REF]  n_total_closed (at RR=2.2)={n_total_closed_ref}")
    print()
    print("[MONTHLY at best_rr_sharpe]")
    for m in monthly_at_best_sharpe:
        print(f"  {m['month']}: {m['R']:.2f}R")
    print()
    print("[PER-ASSET totalR at best_rr_sharpe]")
    for sym in SYMBOLS:
        print(f"  {sym}: {per_asset_at_best_sharpe.get(sym, 0.0):.2f}R")

    # Emit machine-readable JSON block for the harness to parse if needed.
    out = {
        "best_rr_sharpe": best_rr_sharpe,
        "best_rr_totalR": best_rr_totalR,
        "n_total_closed": n_total_closed_ref,
        "per_rr": per_rr,
        "monthly_series": monthly_at_best_sharpe,
        "per_asset_totalR": [
            {"asset": sym, "total_R": round(per_asset_at_best_sharpe.get(sym, 0.0), 4)}
            for sym in SYMBOLS
        ],
    }
    print()
    print("===JSON_START===")
    print(json.dumps(out))
    print("===JSON_END===")


if __name__ == "__main__":
    main()
