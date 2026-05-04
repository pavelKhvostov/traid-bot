"""1.1.2 extended (новые macro): финальный конфиг + monthly breakdown.

Конфиг (тот же что у 1.1.2 final monthly):
  - extended_macro_search = True
  - entry_pct = 0.70 (в FVG)
  - sl_pct = 0.35 (между ob_htf edge и fvg edge)
  - RR = 1.8
  - no_entry = ON
  - ALL group (без SWEPT-фильтра)

Параллельно прогоняется baseline (extended=False) для сравнения.
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
from strategies.strategy_1_1_2 import detect_strategy_1_1_2_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
ENTRY_PCT = 0.70
SL_PCT = 0.35
RR_TARGET = 1.8


def precompute(sig, df_1m):
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


def simulate_no_entry(s, entry, sl, tp):
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
    if tp_pre_idx < entry_idx: return "no_entry"
    if entry_idx >= n: return "not_filled"
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


def run_variant(name: str, extended: bool, dfs: dict) -> dict:
    print()
    print("=" * 100)
    print(f"VARIANT: {name}  (extended_macro_search={extended})")
    print("=" * 100)

    raw = detect_strategy_1_1_2_signals(
        dfs["1d_f"], dfs["12h_f"], dfs["4h"], dfs["6h"],
        dfs["1h"], dfs["2h"], dfs["15m"], dfs["20m"],
        extended_macro_search=extended, verbose=False,
    )

    groups = defaultdict(list)
    for s in raw:
        key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
        groups[key].append(s)
    deduped = [g[0] for g in groups.values()]
    cache = [c for c in (precompute(s, dfs["1m"]) for s in deduped) if c is not None]
    print(f"  raw paths: {len(raw)}  deduped: {len(deduped)}  cache: {len(cache)}")

    trades = []
    for s in cache:
        fw = s["fvg_t"] - s["fvg_b"]
        if s["direction"] == "LONG":
            entry = s["fvg_b"] + ENTRY_PCT * fw
            sl = s["obh_b"] + SL_PCT * (s["fvg_b"] - s["obh_b"])
            if sl >= entry: continue
            risk = entry - sl
            tp = entry + RR_TARGET * risk
        else:
            entry = s["fvg_t"] - ENTRY_PCT * fw
            sl = s["obh_t"] - SL_PCT * (s["obh_t"] - s["fvg_t"])
            if sl <= entry: continue
            risk = sl - entry
            tp = entry - RR_TARGET * risk
        outcome = simulate_no_entry(s, entry, sl, tp)
        trades.append({
            "signal_time": pd.Timestamp(s["signal_time"]),
            "direction": s["direction"],
            "outcome": outcome,
        })
    df_t = pd.DataFrame(trades)
    df_t["month"] = df_t["signal_time"].dt.to_period("M").astype(str)
    df_t["year"] = df_t["signal_time"].dt.year

    wins = (df_t["outcome"] == "win").sum()
    losses = (df_t["outcome"] == "loss").sum()
    ne = (df_t["outcome"] == "no_entry").sum()
    closed = wins + losses
    pnl = wins * RR_TARGET - losses
    weeks = DAYS_BACK / 7
    print()
    print(f"  ИТОГО (3y): signals={len(df_t)} no_entry={ne} closed={closed}")
    print(f"  W={wins} L={losses} WR={wins/closed*100:.1f}% PnL={pnl:+.2f}R "
          f"R/trade={pnl/closed:.3f}" if closed else "  no closed trades")
    if closed:
        print(f"  Frequency: {len(df_t)/weeks:.2f} sig/week, {closed/weeks:.2f} closed/week")

    print()
    print("  По годам:")
    yrows = []
    for year, sub in df_t.groupby("year"):
        w = (sub["outcome"] == "win").sum()
        l = (sub["outcome"] == "loss").sum()
        n = (sub["outcome"] == "no_entry").sum()
        c = w + l
        yrows.append({
            "year": int(year), "signals": len(sub), "no_entry": int(n),
            "wins": int(w), "losses": int(l), "closed": int(c),
            "wr": round(w / c * 100, 1) if c else 0,
            "pnl_r": round(w * RR_TARGET - l, 2),
        })
    df_y = pd.DataFrame(yrows)
    print("  " + df_y.to_string(index=False).replace("\n", "\n  "))

    print()
    print("  По направлению:")
    drows = []
    for direction in ["LONG", "SHORT"]:
        sub = df_t[df_t["direction"] == direction]
        w = (sub["outcome"] == "win").sum()
        l = (sub["outcome"] == "loss").sum()
        n = (sub["outcome"] == "no_entry").sum()
        c = w + l
        drows.append({
            "direction": direction, "signals": len(sub), "no_entry": int(n),
            "wins": int(w), "losses": int(l), "closed": int(c),
            "wr": round(w / c * 100, 1) if c else 0,
            "pnl_r": round(w * RR_TARGET - l, 2),
            "r_per_trade": round((w * RR_TARGET - l) / c, 3) if c else 0,
        })
    print("  " + pd.DataFrame(drows).to_string(index=False).replace("\n", "\n  "))

    return {"name": name, "trades": df_t,
            "raw": len(raw), "deduped": len(deduped),
            "wins": int(wins), "losses": int(losses),
            "no_entry": int(ne), "closed": int(closed),
            "wr": round(wins / closed * 100, 1) if closed else 0,
            "pnl_r": round(pnl, 2),
            "r_per_trade": round(pnl / closed, 3) if closed else 0}


def print_monthly(df_t: pd.DataFrame, label: str) -> None:
    print()
    print("=" * 100)
    print(f"Помесячная разбивка: {label}")
    print("=" * 100)
    rows = []
    for month, sub in df_t.groupby("month"):
        w = (sub["outcome"] == "win").sum()
        l = (sub["outcome"] == "loss").sum()
        n = (sub["outcome"] == "no_entry").sum()
        c = w + l
        rows.append({
            "month": month, "signals": len(sub), "no_entry": int(n),
            "wins": int(w), "losses": int(l), "closed": int(c),
            "wr": round(w / c * 100, 1) if c else 0,
            "pnl_r": round(w * RR_TARGET - l, 2),
        })
    df_m = pd.DataFrame(rows).sort_values("month")
    print(df_m.to_string(index=False))


def main():
    print(f"[INFO] 1.1.2 baseline vs extended: entry={ENTRY_PCT}, sl={SL_PCT}, RR={RR_TARGET}")
    df_1d = load_df(SYMBOL, "1d")
    df_12h = load_df(SYMBOL, "12h")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    dfs = {
        "1d_f": df_1d[df_1d.index >= cutoff],
        "12h_f": df_12h[df_12h.index >= cutoff],
        "4h": df_4h, "6h": df_6h, "1h": df_1h, "2h": df_2h,
        "15m": df_15m, "20m": df_20m, "1m": df_1m,
    }

    res_base = run_variant("BASELINE", extended=False, dfs=dfs)
    res_ext = run_variant("EXTENDED", extended=True, dfs=dfs)

    print_monthly(res_ext["trades"], "EXTENDED")

    print()
    print("=" * 100)
    print("СРАВНЕНИЕ (entry=0.70, sl=0.35, RR=1.8):")
    print("=" * 100)
    cmp = pd.DataFrame([
        {k: v for k, v in r.items() if k != "trades"} for r in [res_base, res_ext]
    ])
    print(cmp.to_string(index=False))

    out = Path("signals/analyze_1_1_2_extended_final.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    res_ext["trades"].drop(columns=["year", "month"]).to_csv(out, index=False)
    print(f"\n  saved: {out}")


if __name__ == "__main__":
    main()
