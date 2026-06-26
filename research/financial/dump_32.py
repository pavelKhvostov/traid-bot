"""Per-trade CSV dump for Strategy 3.2 (key=32) at FIXED RR=2.5.

Reuses fin_32.py's detection + dedup + no-lookahead limit-fill simulation,
but additionally records the EXIT timestamp and the per-trade stop distance
(risk_pct = |entry - sl| / entry * 100) so that cost-in-R = fee% / risk_pct.

Pools BTC+ETH+SOL, simulates EVERY signal at RR=2.5, keeps only CLOSED trades
(win/loss; drops not_filled/open/no_entry), and writes
research/financial/trades_32.csv with columns:
    signal_time, exit_time, sym, direction, gross_R, risk_pct

The dedup key and the limit-fill sim are IDENTICAL to fin_32.py — the only
addition is that the forward 1m timestamps are cached alongside highs/lows so
the exit bar's UTC time can be reported.
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

import numpy as np
import pandas as pd

from data_manager import load_df
from strategies.strategy_3_2 import detect_strategy_3_2_signals

# Reuse the EXACT constants from fin_32 so detection/dedup match.
from research.financial.fin_32 import SYMBOLS, DAYS_BACK, TF_MINUTES

FIXED_RR = 2.5
OUT_CSV = _Path(__file__).resolve().parent / "trades_32.csv"


def precompute_signal_with_times(sig: dict, df_1m: pd.DataFrame) -> dict | None:
    """Same forward cache as fin_32.precompute_signal, plus forward timestamps.

    Forward starts at signal_time + TF_MINUTES (first bar AFTER the FVG-1h
    signal candle closes) -> no entry-bar lookahead, identical to fin_32.
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
        "times": forward.index.values,  # datetime64[ns] forward timestamps
    }


def simulate_with_exit(s: dict, entry: float, sl: float, tp: float):
    """Identical limit-fill + SL/TP scan as fin_32.simulate_with_no_entry,
    but also returns the index (into forward arrays) of the EXIT bar.

    Returns (outcome, exit_idx_or_None) where outcome is one of
    win/loss/no_entry/not_filled/open. exit_idx is absolute into highs/lows/times.
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
    # price ran to TP before our limit got filled -> we'd never have entered
    if tp_pre_idx < entry_idx:
        return "no_entry", None
    if entry_idx >= n:
        return "not_filled", None
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
        return "open", None
    if sl_first == -1:
        return "win", entry_idx + tp_first
    if tp_first == -1:
        return "loss", entry_idx + sl_first
    if tp_first < sl_first:
        return "win", entry_idx + tp_first
    return "loss", entry_idx + sl_first


def build_cache_with_times() -> list[dict]:
    """Detect signals on all assets, GLOBAL dedup, precompute 1m forward arrays
    (with timestamps). Dedup key IDENTICAL to fin_32.build_cache.
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
            cached = precompute_signal_with_times(sig, df_1m)
            if cached is None:
                continue
            cached["asset"] = sym
            pooled.append(cached)

    print(f"[INFO] raw signals per asset: {per_asset_raw}")
    return pooled


def main() -> None:
    print(f"[INFO] Strategy 3.2 per-trade dump @ RR={FIXED_RR} — BTC+ETH+SOL pooled")
    print(f"       DAYS_BACK={DAYS_BACK}, TF_MINUTES={TF_MINUTES}")
    cache = build_cache_with_times()
    print(f"[INFO] pooled deduped cache (with 1m forward): {len(cache)}")

    rows = []
    counts = {"win": 0, "loss": 0, "no_entry": 0, "not_filled": 0, "open": 0}
    for s in cache:
        entry = s["entry"]
        sl = s["sl"]
        risk = s["risk"]
        if s["direction"] == "LONG":
            tp = entry + FIXED_RR * risk
        else:
            tp = entry - FIXED_RR * risk
        outcome, exit_idx = simulate_with_exit(s, entry, sl, tp)
        counts[outcome] = counts.get(outcome, 0) + 1
        if outcome not in ("win", "loss"):
            continue
        gross_R = FIXED_RR if outcome == "win" else -1.0
        risk_pct = abs(entry - sl) / entry * 100.0
        if exit_idx is not None and exit_idx < len(s["times"]):
            exit_ts = pd.Timestamp(s["times"][exit_idx])
            exit_str = exit_ts.strftime("%Y-%m-%d %H:%M:%S")
        else:
            exit_str = ""
        sig_ts = pd.Timestamp(s["signal_time"])
        rows.append({
            "signal_time": sig_ts.strftime("%Y-%m-%d %H:%M:%S"),
            "exit_time": exit_str,
            "sym": s["asset"],
            "direction": s["direction"],
            "gross_R": round(float(gross_R), 4),
            "risk_pct": round(float(risk_pct), 6),
        })

    cols = ["signal_time", "exit_time", "sym", "direction", "gross_R", "risk_pct"]
    df = pd.DataFrame(rows, columns=cols)
    df.to_csv(OUT_CSV, index=False)

    print(f"[INFO] outcome counts: {counts}")
    print(f"[INFO] wrote {len(df)} closed trades -> {OUT_CSV}")
    if len(df):
        print(f"[INFO] median risk_pct = {df['risk_pct'].median():.6f}")
        print("[INFO] head:")
        print(df.head(5).to_string(index=False))


if __name__ == "__main__":
    main()
