"""Per-trade CSV dump for Strategy 1.1.5 at FIXED RR=3.

Reuses fin_115.py's detector + dedup + no-lookahead limit-fill sim. For every
CLOSED trade (win/loss only; drop no_entry/not_filled/open) pooled across
BTC+ETH+SOL, writes research/financial/trades_115.csv with columns:
  signal_time, exit_time, sym, direction, gross_R, risk_pct

gross_R = +3 if TP first else -1.0 (fixed RR=3).
risk_pct = abs(entry - sl) / entry * 100  (real per-trade stop distance %).
exit_time = UTC ISO of the bar where SL/TP was hit (empty if unknown).

The forward window stores 1m timestamps (parallel to highs/lows) so the exact
SL/TP-hit bar's open time can be reported. SAME engine as fin_115 otherwise.
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

import csv

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_5 import detect_strategy_1_1_5_signals

# Reuse constants + dedup logic from fin_115 to stay identical.
import research.financial.fin_115 as fin

SYMBOLS = fin.SYMBOLS
ENTRY_PCT = fin.ENTRY_PCT
SL_PCT = fin.SL_PCT
K_AFTER = fin.K_AFTER
DAYS_BACK = fin.DAYS_BACK
RR = 3.0

OUT_CSV = _Path(__file__).resolve().parent / "trades_115.csv"


def precompute_signal_with_times(sig: dict, df_1m: pd.DataFrame) -> dict | None:
    """Same forward window as fin.precompute_signal, but ALSO keep the 1m
    timestamps (parallel to highs/lows) so we can report exit_time."""
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
        "times": forward.index,  # DatetimeIndex parallel to highs/lows
    }


def simulate_with_exit(s: dict, entry: float, sl: float, tp: float):
    """Validated engine (identical logic to fin.simulate_with_no_entry), but
    also returns the index (into the forward window) of the SL/TP-hit bar.

    Returns (outcome, exit_idx) where outcome in
      win / loss / no_entry / not_filled / open.
    exit_idx is the absolute index into s['highs']/s['times'] for the hit bar,
    or None when not applicable.
    """
    highs, lows, times = s["highs"], s["lows"], s["times"]
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
        return ("no_entry", None)
    if entry_idx >= n:
        return ("not_filled", None)
    post_l = lows[entry_idx:]; post_h = highs[entry_idx:]
    if s["direction"] == "LONG":
        sl_mask = post_l <= sl; tp_mask = post_h >= tp
    else:
        sl_mask = post_h >= sl; tp_mask = post_l <= tp
    sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
    tp_first = int(np.argmax(tp_mask)) if tp_mask.any() else -1
    if sl_first == -1 and tp_first == -1:
        return ("open", None)
    if sl_first == -1:
        return ("win", entry_idx + tp_first)
    if tp_first == -1:
        return ("loss", entry_idx + sl_first)
    if tp_first < sl_first:
        return ("win", entry_idx + tp_first)
    return ("loss", entry_idx + sl_first)


def build_cache_for_symbol(symbol: str) -> list[dict]:
    """Detect + dedup IDENTICAL to fin_115.build_cache_for_symbol, but use the
    time-aware precompute so exit_time is recoverable."""
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

    # Dedup key = (signal_time, direction, round(entry,6)) -- identical to fin_115.
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
        c = precompute_signal_with_times(s, df_1m)
        if c is not None:
            c["symbol"] = symbol
            cache.append(c)
    print(f"  [{symbol}] raw={len(raw)} deduped={len(deduped)} cache={len(cache)}")
    return cache


def _iso(ts) -> str:
    """UTC ISO 'YYYY-MM-DD HH:MM:SS' from a (possibly tz-aware) Timestamp."""
    t = pd.Timestamp(ts)
    if t.tz is not None:
        t = t.tz_convert("UTC")
    return t.strftime("%Y-%m-%d %H:%M:%S")


def trade_row(s: dict):
    """Return a per-trade dict for a CLOSED trade at RR=3, or None if dropped.

    risk_pct = abs(entry - sl) / entry * 100. gross_R = +3 (win) / -1.0 (loss).
    """
    fw = s["fvg_t"] - s["fvg_b"]
    if s["direction"] == "LONG":
        entry = s["fvg_b"] + ENTRY_PCT * fw
        sl = s["obh_b"] + SL_PCT * (s["fvg_b"] - s["obh_b"])
        if sl >= entry:
            return None
        risk = entry - sl
        tp = entry + RR * risk
    else:
        entry = s["fvg_t"] - ENTRY_PCT * fw
        sl = s["obh_t"] - SL_PCT * (s["obh_t"] - s["fvg_t"])
        if sl <= entry:
            return None
        risk = sl - entry
        tp = entry - RR * risk

    outcome, exit_idx = simulate_with_exit(s, entry, sl, tp)
    if outcome not in ("win", "loss"):
        return None  # drop no_entry / not_filled / open

    gross_R = RR if outcome == "win" else -1.0
    risk_pct = abs(entry - sl) / entry * 100.0
    exit_time = ""
    if exit_idx is not None and 0 <= exit_idx < len(s["times"]):
        exit_time = _iso(s["times"][exit_idx])

    return {
        "signal_time": _iso(s["signal_time"]),
        "exit_time": exit_time,
        "sym": s["symbol"],
        "direction": s["direction"],
        "gross_R": gross_R,
        "risk_pct": risk_pct,
    }


COLS = ["signal_time", "exit_time", "sym", "direction", "gross_R", "risk_pct"]


def main() -> None:
    print(f"[INFO] dump_115: per-trade CSV at FIXED RR={RR}")
    print(f"       entry={ENTRY_PCT}, sl={SL_PCT} sym, k_after={K_AFTER}, "
          f"days_back={DAYS_BACK}, symbols={SYMBOLS}")
    print()

    pooled: list[dict] = []
    for sym in SYMBOLS:
        pooled.extend(build_cache_for_symbol(sym))
    print(f"[INFO] pooled cache (3 assets): {len(pooled)}")

    rows = []
    for s in pooled:
        r = trade_row(s)
        if r is not None:
            rows.append(r)

    # Sort by signal_time then sym for a stable, readable CSV.
    rows.sort(key=lambda r: (r["signal_time"], r["sym"]))

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({
                "signal_time": r["signal_time"],
                "exit_time": r["exit_time"],
                "sym": r["sym"],
                "direction": r["direction"],
                "gross_R": f"{r['gross_R']:.4f}",
                "risk_pct": f"{r['risk_pct']:.6f}",
            })

    wins = sum(1 for r in rows if r["gross_R"] > 0)
    losses = len(rows) - wins
    med_risk = float(np.median([r["risk_pct"] for r in rows])) if rows else 0.0
    print(f"[OK] wrote {len(rows)} closed trades -> {OUT_CSV}")
    print(f"     wins={wins} losses={losses} "
          f"WR={(wins/len(rows)*100 if rows else 0):.1f}% median_risk_pct={med_risk:.4f}")


if __name__ == "__main__":
    main()
