"""Strategy 1.1.2 + no_entry: TP до entry → отмена сделки.

Симуляция аналогично backtest_strategy_1_1_2, но если TP-цена достигнута
до touch entry — сделка не считается filled.
Прогон на RR=1.0 и RR=2.2 с разбивкой по годам.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_2 import detect_strategy_1_1_2_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
RR_LIST = [1.0, 2.2]


def precompute(sig: dict, df_1m: pd.DataFrame) -> dict | None:
    tf_minutes = 60 if sig["fvg_htf_tf"] == "1h" else 120
    forward = df_1m[df_1m.index >= sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)]
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


def main() -> None:
    print(f"[INFO] Strategy 1.1.2 + no_entry, окно {DAYS_BACK}d, RR={RR_LIST}")
    print()

    df_1d = load_df(SYMBOL, "1d")
    df_12h = load_df(SYMBOL, "12h")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_1m = load_df(SYMBOL, "1m")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f = df_1d[df_1d.index >= cutoff]
    df_12h_f = df_12h[df_12h.index >= cutoff]

    raw = detect_strategy_1_1_2_signals(
        df_1d_f, df_12h_f, df_4h, df_6h, df_1h, df_2h, verbose=False,
    )
    print(f"  raw signals: {len(raw)}")

    # dedup по (signal_time, direction, entry) — берём первый каждой группы
    groups = defaultdict(list)
    for s in raw:
        key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
        groups[key].append(s)
    deduped = [g[0] for g in groups.values()]
    print(f"  deduped: {len(deduped)}")

    cache = [c for c in (precompute(s, df_1m) for s in deduped) if c is not None]
    print(f"  cache: {len(cache)}")

    for rr in RR_LIST:
        print()
        print("=" * 80)
        print(f"RR = {rr}")
        print("=" * 80)
        rows = []
        for s in cache:
            outcome = simulate_no_entry(s, rr)
            rows.append({
                "signal_time": pd.Timestamp(s["signal_time"]),
                "direction": s["direction"],
                "outcome": outcome,
            })
        df_t = pd.DataFrame(rows)
        df_t["year"] = df_t["signal_time"].dt.year

        wins = (df_t["outcome"] == "win").sum()
        losses = (df_t["outcome"] == "loss").sum()
        ne = (df_t["outcome"] == "no_entry").sum()
        opens = (df_t["outcome"] == "open").sum()
        nf = (df_t["outcome"] == "not_filled").sum()
        closed = wins + losses
        pnl = wins * rr - losses
        print(f"  total={len(df_t)} no_entry={ne} not_filled={nf} open={opens}")
        print(f"  closed={closed}: W={wins} L={losses}")
        wr_str = f"{wins / closed * 100:.1f}%" if closed else "-"
        rpt_str = f"{pnl / closed:.3f}" if closed else "-"
        print(f"  WR={wr_str} PnL={pnl:+.2f}R R/trade={rpt_str}")

        print()
        print("По годам:")
        yrows = []
        for y, sub in df_t.groupby("year"):
            w = (sub["outcome"] == "win").sum()
            l = (sub["outcome"] == "loss").sum()
            n = (sub["outcome"] == "no_entry").sum()
            c = w + l
            yrows.append({
                "year": int(y),
                "signals": len(sub),
                "no_entry": int(n),
                "wins": int(w),
                "losses": int(l),
                "closed": int(c),
                "wr": round(w / c * 100, 1) if c else 0,
                "pnl_r": round(w * rr - l, 2),
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
                "direction": direction,
                "signals": len(sub),
                "no_entry": int(n),
                "wins": int(w),
                "losses": int(l),
                "closed": int(c),
                "wr": round(w / c * 100, 1) if c else 0,
                "pnl_r": round(w * rr - l, 2),
            })
        print(pd.DataFrame(drows).to_string(index=False))

        out = Path(f"signals/analyze_1_1_2_no_entry_RR{rr}.csv")
        out.parent.mkdir(parents=True, exist_ok=True)
        df_t.drop(columns=["year"]).to_csv(out, index=False)
        print(f"\n  saved: {out}")


if __name__ == "__main__":
    main()
