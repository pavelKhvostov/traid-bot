"""Разбивка по годам для top-конфигов из grid search."""
from __future__ import annotations

import pandas as pd
import numpy as np
from data_manager import load_df

CSV_PATH = "signals/vic_evot_backtest_3y_RR1.csv"
SYMBOL = "BTCUSDT"

# Top-3 + base
CONFIGS = [
    ("e=0.0 sl=0.8", 0.0, 0.8),
    ("e=1.0 sl=0.8", 1.0, 0.8),
    ("e=0.0 sl=1.0", 0.0, 1.0),
    ("e=0.8 sl=1.1 (current)", 0.8, 1.1),
    ("e=0.5 sl=1.0", 0.5, 1.0),
    ("market sl=1.0", "market", 1.0),
]


def main():
    df_csv = pd.read_csv(CSV_PATH)
    df_csv = df_csv[df_csv["outcome"].isin(["win", "loss", "open"])].copy()
    df_csv["signal_time"] = pd.to_datetime(df_csv["signal_time"], utc=True)
    df_csv["fractal_time"] = pd.to_datetime(df_csv["fractal_time"], utc=True)

    df_1m = load_df(SYMBOL, "1m")
    df_15m = load_df(SYMBOL, "15m")

    rows = []
    for _, s in df_csv.iterrows():
        try:
            ip2 = df_15m.loc[s["signal_time"]]
            pos_i_t = s["signal_time"] - pd.Timedelta(minutes=30)
            ic = df_15m.loc[pos_i_t]
            fc = df_15m.loc[s["fractal_time"]]
        except KeyError:
            continue
        if s["direction"] == "LONG":
            rows.append({
                "direction": "LONG",
                "signal_time": s["signal_time"],
                "year": s["signal_time"].year,
                "fvg_low": float(ic["high"]),
                "fvg_high": float(ip2["low"]),
                "close_ip2": float(ip2["close"]),
                "fractal_sl": float(fc["low"]),
            })
        else:
            rows.append({
                "direction": "SHORT",
                "signal_time": s["signal_time"],
                "year": s["signal_time"].year,
                "fvg_low": float(ip2["high"]),
                "fvg_high": float(ic["low"]),
                "close_ip2": float(ip2["close"]),
                "fractal_sl": float(fc["high"]),
            })
    sigs = pd.DataFrame(rows)

    times = df_1m.index.values
    highs = df_1m["high"].values
    lows = df_1m["low"].values

    def simulate_one(direction, signal_time, entry, sl, tp, market_fill=False):
        scan_start = signal_time + pd.Timedelta(minutes=15)
        idx = np.searchsorted(times, np.datetime64(scan_start))
        if idx >= len(times):
            return "not_filled"
        if market_fill:
            act_idx = idx
        else:
            act_idx = None
            for j in range(idx, len(times)):
                h, l = highs[j], lows[j]
                if direction == "LONG":
                    if l <= entry:
                        act_idx = j; break
                else:
                    if h >= entry:
                        act_idx = j; break
            if act_idx is None:
                return "not_filled"
        for j in range(act_idx, len(times)):
            h, l = highs[j], lows[j]
            if direction == "LONG":
                if l <= sl: return "loss"
                if h >= tp: return "win"
            else:
                if h >= sl: return "loss"
                if l <= tp: return "win"
        return "open"

    print(f"{'config':<28} year   n   W   L  WR%  PnL")
    print("-" * 60)
    for label, entry_pct, sl_buffer in CONFIGS:
        per_year = {}
        for _, r in sigs.iterrows():
            if entry_pct == "market":
                entry = r["close_ip2"]
                market_fill = True
            else:
                entry = r["fvg_low"] * (1 - entry_pct) + r["fvg_high"] * entry_pct
                market_fill = False

            if r["direction"] == "LONG":
                raw_risk = entry - r["fractal_sl"]
            else:
                raw_risk = r["fractal_sl"] - entry
            if raw_risk <= 0:
                continue

            sl_dist = raw_risk * sl_buffer
            if r["direction"] == "LONG":
                sl = entry - sl_dist
                tp = entry + sl_dist
            else:
                sl = entry + sl_dist
                tp = entry - sl_dist

            outcome = simulate_one(r["direction"], r["signal_time"], entry, sl, tp, market_fill)
            y = r["year"]
            if y not in per_year:
                per_year[y] = {"n": 0, "w": 0, "l": 0}
            if outcome in ("win", "loss"):
                per_year[y]["n"] += 1
                if outcome == "win":
                    per_year[y]["w"] += 1
                else:
                    per_year[y]["l"] += 1

        for y in sorted(per_year.keys()):
            d = per_year[y]
            n = d["n"]; w = d["w"]; l = d["l"]
            wr = w/n*100 if n else 0
            pnl = w - l
            print(f"{label:<28} {y}  {n:>3} {w:>3} {l:>3} {wr:>5.1f} {pnl:+d}")
        # totals
        total_n = sum(d["n"] for d in per_year.values())
        total_w = sum(d["w"] for d in per_year.values())
        total_l = sum(d["l"] for d in per_year.values())
        total_wr = total_w/total_n*100 if total_n else 0
        print(f"{label:<28} ALL  {total_n:>3} {total_w:>3} {total_l:>3} {total_wr:>5.1f} {total_w-total_l:+d}")
        print()


if __name__ == "__main__":
    main()
