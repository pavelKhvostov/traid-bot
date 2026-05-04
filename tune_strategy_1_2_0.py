"""Тюнинг детектора Strategy 1.2.0: грид по фильтрам и параметрам.

Сетка:
  - require_trend ∈ {True, False}
  - require_top_ob ∈ {True, False}
  - sl_buffer_pct ∈ {0.001, 0.003, 0.005, 0.01}
  - fvg_window_hours ∈ {4, 8, 12}
  - entry_pct = 0.80 (фиксирован)
  - RR = 1.0 (фиксирован для максимизации WR)
  - no_entry = ON

Выход: таблица по всем комбинациям, отсортированная по PnL и WR.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import load_df
from strategies.strategy_1_2_0 import detect_strategy_1_2_0_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
RR_TARGET = 1.0
ENTRY_PCT = 0.80

GRID = {
    "require_trend": [True, False],
    "require_top_ob": [True, False],
    "sl_buffer_pct": [0.001, 0.003, 0.005, 0.01],
    "fvg_window_hours": [4, 8, 12],
}


def precompute(sig: dict, df_1m: pd.DataFrame) -> dict | None:
    forward = df_1m[df_1m.index >= sig["signal_time"] + pd.Timedelta(minutes=15)]
    if forward.empty:
        return None
    return {
        "direction": sig["direction"],
        "entry": float(sig["entry"]),
        "sl": float(sig["sl"]),
        "risk": float(sig["risk"]),
        "highs": forward["high"].values.astype(np.float64),
        "lows": forward["low"].values.astype(np.float64),
    }


def simulate_no_entry(s: dict, rr: float) -> str:
    direction = s["direction"]
    entry = s["entry"]; sl = s["sl"]; risk = s["risk"]
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


def evaluate(signals: list[dict], df_1m: pd.DataFrame) -> dict:
    groups = defaultdict(list)
    for s in signals:
        key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
        groups[key].append(s)
    deduped = [g[0] for g in groups.values()]
    cache = [c for c in (precompute(s, df_1m) for s in deduped) if c is not None]

    wins = losses = ne = nf = opens = 0
    for s in cache:
        out = simulate_no_entry(s, RR_TARGET)
        if out == "win": wins += 1
        elif out == "loss": losses += 1
        elif out == "no_entry": ne += 1
        elif out == "open": opens += 1
        else: nf += 1
    closed = wins + losses
    weeks = DAYS_BACK / 7
    return {
        "raw": len(signals),
        "deduped": len(deduped),
        "cache": len(cache),
        "no_entry": ne,
        "not_filled": nf,
        "open": opens,
        "wins": wins,
        "losses": losses,
        "closed": closed,
        "wr": round(wins / closed * 100, 1) if closed else 0,
        "pnl_r": round(wins * RR_TARGET - losses, 2),
        "sig_per_week": round(len(deduped) / weeks, 2),
        "closed_per_week": round(closed / weeks, 2),
    }


def main() -> None:
    print(f"[INFO] Strategy 1.2.0 detector tuning, {SYMBOL}, окно {DAYS_BACK}d, RR={RR_TARGET}")
    print()

    df_1d = load_df(SYMBOL, "1d")
    df_1h = load_df(SYMBOL, "1h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1h_f = df_1h[df_1h.index >= cutoff]
    df_15m_f = df_15m[df_15m.index >= cutoff]

    keys = list(GRID.keys())
    combos = list(product(*[GRID[k] for k in keys]))
    print(f"  total combinations: {len(combos)}")
    print()

    rows = []
    for idx, vals in enumerate(combos):
        cfg = dict(zip(keys, vals))
        signals = detect_strategy_1_2_0_signals(
            df_1d, df_1h_f, df_15m_f,
            sl_buffer_pct=cfg["sl_buffer_pct"],
            entry_pct=ENTRY_PCT,
            require_top_ob=cfg["require_top_ob"],
            require_trend=cfg["require_trend"],
            fvg_window_hours=cfg["fvg_window_hours"],
            verbose=False,
        )
        result = evaluate(signals, df_1m)
        row = {**cfg, **result}
        rows.append(row)
        print(f"  [{idx+1}/{len(combos)}] trend={cfg['require_trend']} top={cfg['require_top_ob']} "
              f"sl_buf={cfg['sl_buffer_pct']} fvg_w={cfg['fvg_window_hours']}h "
              f"-> sig={result['deduped']} closed={result['closed']} "
              f"WR={result['wr']}% PnL={result['pnl_r']}R")

    df = pd.DataFrame(rows)
    print()
    print("=" * 110)
    print("Топ-15 по WR (только при closed >= 30 — статистически значимо):")
    print("=" * 110)
    df_sig = df[df["closed"] >= 30].sort_values("wr", ascending=False).head(15)
    cols = ["require_trend", "require_top_ob", "sl_buffer_pct", "fvg_window_hours",
            "deduped", "no_entry", "closed", "wins", "losses", "wr", "pnl_r",
            "sig_per_week", "closed_per_week"]
    print(df_sig[cols].to_string(index=False))

    print()
    print("=" * 110)
    print("Топ-15 по PnL (любое closed):")
    print("=" * 110)
    df_pnl = df.sort_values("pnl_r", ascending=False).head(15)
    print(df_pnl[cols].to_string(index=False))

    print()
    print("=" * 110)
    print("Все варианты с WR >= 60% и closed_per_week >= 0.20 (~раз в 5 нед):")
    print("=" * 110)
    df_target = df[(df["wr"] >= 60) & (df["closed_per_week"] >= 0.20)].sort_values("wr", ascending=False)
    if len(df_target):
        print(df_target[cols].to_string(index=False))
    else:
        print("  (пусто) — ни один конфиг не даёт WR>=60% при closed>=раз в 5 нед")

    print()
    print("=" * 110)
    print("Полный грид (sorted by PnL):")
    print("=" * 110)
    df_full = df.sort_values("pnl_r", ascending=False)
    print(df_full[cols].to_string(index=False))

    out = Path("signals/tune_1_2_0_grid.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    df_full.to_csv(out, index=False)
    print(f"\n  saved: {out}")


if __name__ == "__main__":
    main()
