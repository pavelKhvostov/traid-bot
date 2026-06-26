"""Per-trade CSV dump of Strategy 1.1.2 (key=112) at FIXED RR=2.2, pooled BTC+ETH+SOL.

Reuses the SAME dedup + no-lookahead limit-fill sim as fin_112.py (imported directly),
but augments precompute to also retain forward timestamps so we can recover exit_time,
and computes per-trade risk_pct = abs(entry - sl) / entry * 100.

Writes research/financial/trades_112.csv with EXACTLY these columns:
  signal_time, exit_time, sym, direction, gross_R, risk_pct

Only CLOSED trades (win/loss). not_filled / open / no_entry are dropped.
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
from strategies.strategy_1_1_2 import detect_strategy_1_1_2_signals

# Reuse the EXACT same constants + canonical config from fin_112.
import fin_112 as base
from fin_112 import (
    DAYS_BACK,
    SYMBOLS,
    ENTRY_PCT,
    SL_PCT,
)

RR = 2.2
OUT_CSV = _Path(__file__).resolve().parent / "trades_112.csv"


def precompute_with_times(sig: dict, df_1m: pd.DataFrame) -> dict | None:
    """Same entry/sl/risk computation as fin_112.precompute, but ALSO keep the forward
    timestamp index (and compute risk_pct) so we can recover exit_time per trade.

    forward starts at signal_time + tf_minutes (= c2.close): no entry-bar lookahead.
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

    risk_pct = abs(entry - sl) / entry * 100.0

    return {
        "signal_time": sig_time,
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "risk": risk,
        "risk_pct": risk_pct,
        "highs": forward["high"].values.astype(np.float64),
        "lows": forward["low"].values.astype(np.float64),
        "times": forward.index,  # 1m timestamps aligned with highs/lows
    }


def simulate_with_exit(s: dict, entry: float, sl: float, tp: float) -> tuple[str, int]:
    """Same no-lookahead engine as fin_112.simulate_with_no_entry, but ALSO return the
    forward-array index of the bar that closed the trade (SL/TP hit). Index is into the
    forward highs/lows/times arrays. Returns (outcome, exit_idx); exit_idx=-1 if unknown.
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
        return "no_entry", -1
    if entry_idx >= n:
        return "not_filled", -1
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
        return "open", -1
    if sl_first == -1:
        return "win", entry_idx + tp_first
    if tp_first == -1:
        return "loss", entry_idx + sl_first
    if tp_first < sl_first:
        return "win", entry_idx + tp_first
    return "loss", entry_idx + sl_first


def build_cache_for_symbol(symbol: str) -> list[dict]:
    """Detect + dedup 1.1.2 signals for one symbol (IDENTICAL to fin_112), then
    precompute WITH timestamps."""
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

    # Dedup by (signal_time, direction, round(entry,6)) -- keep first path. SAME as fin_112.
    groups = defaultdict(list)
    for s in raw:
        key = (pd.Timestamp(s["signal_time"]), s["direction"], round(float(s["entry"]), 6))
        groups[key].append(s)
    deduped = [g[0] for g in groups.values()]

    cache = [c for c in (precompute_with_times(s, df_1m) for s in deduped) if c is not None]
    print(f"  {symbol}: raw={len(raw)} deduped={len(deduped)} cache={len(cache)}")
    return cache


def main() -> None:
    print(f"[INFO] dump_112: per-trade CSV at FIXED RR={RR}")
    print(f"       symbols={SYMBOLS} window={DAYS_BACK}d entry={ENTRY_PCT} sl_pct={SL_PCT}")
    print()

    pooled: list[dict] = []
    for sym in SYMBOLS:
        c = build_cache_for_symbol(sym)
        for x in c:
            x["symbol"] = sym
        pooled.extend(c)
    print(f"\n  POOLED cache (3 assets): {len(pooled)}")

    rows = []
    for s in pooled:
        entry, sl, risk = s["entry"], s["sl"], s["risk"]
        if s["direction"] == "LONG":
            tp = entry + RR * risk
        else:
            tp = entry - RR * risk
        outcome, exit_idx = simulate_with_exit(s, entry, sl, tp)
        if outcome not in ("win", "loss"):
            continue  # drop not_filled / open / no_entry
        gross_R = RR if outcome == "win" else -1.0
        if 0 <= exit_idx < len(s["times"]):
            exit_ts = pd.Timestamp(s["times"][exit_idx]).tz_convert("UTC")
            exit_str = exit_ts.strftime("%Y-%m-%d %H:%M:%S")
        else:
            exit_str = ""
        sig_str = s["signal_time"].tz_convert("UTC").strftime("%Y-%m-%d %H:%M:%S")
        rows.append({
            "signal_time": sig_str,
            "exit_time": exit_str,
            "sym": s["symbol"],
            "direction": s["direction"],
            "gross_R": round(float(gross_R), 6),
            "risk_pct": round(float(s["risk_pct"]), 6),
        })

    cols = ["signal_time", "exit_time", "sym", "direction", "gross_R", "risk_pct"]
    df = pd.DataFrame(rows, columns=cols)
    df.to_csv(OUT_CSV, index=False)
    med = float(df["risk_pct"].median()) if len(df) else float("nan")
    print(f"\n  WROTE {OUT_CSV}")
    print(f"  n_trades={len(df)}  median_risk_pct={med:.6f}")
    print(f"  wins={int((df['gross_R'] > 0).sum())} losses={int((df['gross_R'] < 0).sum())}")
    print("\n[JSON_RESULT]")
    import json
    print(json.dumps({
        "ran_ok": True,
        "csv_path": str(OUT_CSV),
        "n_trades": int(len(df)),
        "opt_rr": RR,
        "median_risk_pct": round(med, 6) if len(df) else None,
        "cols": cols,
    }))


if __name__ == "__main__":
    main()
