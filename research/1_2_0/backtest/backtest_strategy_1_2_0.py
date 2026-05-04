"""Бэктест Strategy 1.2.0 на BTCUSDT (трёхлетнее окно).

Симуляция: limit-вход = 80% deep в FVG-15m. Активация = touch entry на 1m
после close c2 свечи FVG. SL = sweep low/high + 0.10% буфер. TP = RR=1.0.
no_entry = ON (TP до entry → отмена).

Для сравнения: запуск с require_top_ob=True (полный фильтр) и False (без top OB).
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

from data_manager import load_df
from strategies.strategy_1_2_0 import detect_strategy_1_2_0_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
RR_TARGET = 1.0


def precompute(sig: dict, df_1m: pd.DataFrame) -> dict | None:
    forward = df_1m[df_1m.index >= sig["signal_time"] + pd.Timedelta(minutes=15)]
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


def simulate_no_entry(s: dict, rr: float) -> str:
    direction = s["direction"]
    entry = s["entry"]
    sl = s["sl"]
    risk = s["risk"]
    if direction == "LONG":
        tp = entry + rr * risk
    else:
        tp = entry - rr * risk

    highs, lows = s["highs"], s["lows"]
    n = len(highs)
    if direction == "LONG":
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
    if direction == "LONG":
        sl_mask = post_l <= sl; tp_mask = post_h >= tp
    else:
        sl_mask = post_h >= sl; tp_mask = post_l <= tp
    sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
    tp_first = int(np.argmax(tp_mask)) if tp_mask.any() else -1
    if sl_first == -1 and tp_first == -1: return "open"
    if sl_first == -1: return "win"
    if tp_first == -1: return "loss"
    return "win" if tp_first < sl_first else "loss"


def run_variant(name: str, signals: list[dict], df_1m: pd.DataFrame) -> None:
    print()
    print("=" * 90)
    print(f"VARIANT: {name}")
    print("=" * 90)
    print(f"  raw signals: {len(signals)}")

    # dedup по (signal_time, direction, round(entry, 2)) — на случай дублей
    groups = defaultdict(list)
    for s in signals:
        key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
        groups[key].append(s)
    deduped = [g[0] for g in groups.values()]
    print(f"  deduped: {len(deduped)}")

    cache = [c for c in (precompute(s, df_1m) for s in deduped) if c is not None]
    print(f"  cache: {len(cache)}")

    rows = []
    for s in cache:
        outcome = simulate_no_entry(s, RR_TARGET)
        rows.append({
            "signal_time": pd.Timestamp(s["signal_time"]),
            "direction": s["direction"],
            "outcome": outcome,
        })
    df_t = pd.DataFrame(rows)
    df_t["year"] = df_t["signal_time"].dt.year
    df_t["month"] = df_t["signal_time"].dt.to_period("M").astype(str)

    wins = (df_t["outcome"] == "win").sum()
    losses = (df_t["outcome"] == "loss").sum()
    ne = (df_t["outcome"] == "no_entry").sum()
    opens = (df_t["outcome"] == "open").sum()
    nf = (df_t["outcome"] == "not_filled").sum()
    closed = wins + losses
    pnl = wins * RR_TARGET - losses
    print()
    print(f"  total={len(df_t)} no_entry={ne} not_filled={nf} open={opens}")
    print(f"  closed={closed}: W={wins} L={losses}")
    if closed:
        wr = wins / closed * 100
        print(f"  WR={wr:.1f}% PnL={pnl:+.2f}R R/trade={pnl / closed:.3f}")
        weeks = DAYS_BACK / 7
        print(f"  Frequency: {len(df_t) / weeks:.2f} sig/week ({closed / weeks:.2f} closed/week)")

    print()
    print("По годам:")
    yrows = []
    for y, sub in df_t.groupby("year"):
        w = (sub["outcome"] == "win").sum()
        l = (sub["outcome"] == "loss").sum()
        n = (sub["outcome"] == "no_entry").sum()
        c = w + l
        yrows.append({
            "year": int(y), "signals": len(sub), "no_entry": int(n),
            "wins": int(w), "losses": int(l), "closed": int(c),
            "wr": round(w / c * 100, 1) if c else 0,
            "pnl_r": round(w * RR_TARGET - l, 2),
        })
    print(pd.DataFrame(yrows).to_string(index=False))

    print()
    print("По направлению:")
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
        })
    print(pd.DataFrame(drows).to_string(index=False))

    out = Path(f"signals/strategy_1_2_0_{name}.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    df_t.to_csv(out, index=False)
    print(f"\n  saved: {out}")


def main() -> None:
    print(f"[INFO] Strategy 1.2.0 backtest, {SYMBOL}, окно {DAYS_BACK}d, RR={RR_TARGET}, no_entry=on")
    print()

    df_1d = load_df(SYMBOL, "1d")
    df_1h = load_df(SYMBOL, "1h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1h_f = df_1h[df_1h.index >= cutoff]
    df_15m_f = df_15m[df_15m.index >= cutoff]
    print(f"  1d={len(df_1d)} 1h={len(df_1h_f)} 15m={len(df_15m_f)} 1m={len(df_1m)}")

    print()
    print("[INFO] сбор сигналов с require_top_ob=True (полный фильтр)")
    sigs_full = detect_strategy_1_2_0_signals(
        df_1d, df_1h_f, df_15m_f, require_top_ob=True, verbose=True,
    )

    print()
    print("[INFO] сбор сигналов с require_top_ob=False (без top OB-1d)")
    sigs_no_top = detect_strategy_1_2_0_signals(
        df_1d, df_1h_f, df_15m_f, require_top_ob=False, verbose=True,
    )

    if sigs_full:
        run_variant("full", sigs_full, df_1m)
    if sigs_no_top:
        run_variant("no_top_ob", sigs_no_top, df_1m)


if __name__ == "__main__":
    main()
