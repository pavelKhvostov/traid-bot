"""Grid search оптимальных параметров entry/SL для VIC_EVOT на 3-летнем сэмпле.

RR=1:1 (tp_distance = sl_distance, оба буферятся пропорционально).
Метрика: PnL = wins - losses (каждая сделка +1R или -1R).

Использует уже собранный CSV signals/vic_evot_backtest_3y_RR1.csv для
полного списка сигналов, плюс df_15m / df_1m для пересчёта entry/SL/TP."""
from __future__ import annotations

import pandas as pd
import numpy as np
from data_manager import load_df

CSV_PATH = "signals/vic_evot_backtest_3y_RR1.csv"
SYMBOL = "BTCUSDT"

# Сетка параметров
ENTRY_PCTS = [0.0, 0.2, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, "market"]
SL_BUFFERS = [0.8, 1.0, 1.1, 1.2, 1.3, 1.5, 2.0]


def main():
    print("[INFO] загружаю данные")
    df_csv = pd.read_csv(CSV_PATH)
    df_csv = df_csv[df_csv["outcome"].isin(["win", "loss", "open"])].copy()
    df_csv["signal_time"] = pd.to_datetime(df_csv["signal_time"], utc=True)
    df_csv["fractal_time"] = pd.to_datetime(df_csv["fractal_time"], utc=True)
    print(f"  signals: {len(df_csv)}")

    df_1m = load_df(SYMBOL, "1m")
    df_15m = load_df(SYMBOL, "15m")
    print(f"  1m candles: {len(df_1m)}, 15m: {len(df_15m)}")

    # Pre-extract for speed: high_i, low_ip2, close_ip2, fractal_sl per signal
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
                "fvg_low": float(ic["high"]),     # bottom of FVG
                "fvg_high": float(ip2["low"]),    # top of FVG
                "close_ip2": float(ip2["close"]),
                "fractal_sl": float(fc["low"]),
            })
        else:
            rows.append({
                "direction": "SHORT",
                "signal_time": s["signal_time"],
                "fvg_low": float(ip2["high"]),    # bottom of FVG
                "fvg_high": float(ic["low"]),     # top of FVG
                "close_ip2": float(ip2["close"]),
                "fractal_sl": float(fc["high"]),
            })
    sigs = pd.DataFrame(rows)
    print(f"  усвоено сигналов с метаданными: {len(sigs)}")

    # 1m в numpy для скорости
    times = df_1m.index.values
    highs = df_1m["high"].values
    lows = df_1m["low"].values

    def simulate_one(direction, signal_time, entry, sl, tp, market_fill=False):
        # signal_time = open(i+2). В live сигнал приходит на close(i+2),
        # т.е. через 15 мин. Чтобы избежать lookahead bias, сканируем
        # 1m свечи, начиная с close(i+2) = signal_time + 15min.
        scan_start = signal_time + pd.Timedelta(minutes=15)
        idx = np.searchsorted(times, np.datetime64(scan_start))
        if idx >= len(times):
            return "not_filled"

        if market_fill:
            act_idx = idx
        else:
            # Поиск активации
            act_idx = None
            for j in range(idx, len(times)):
                h, l = highs[j], lows[j]
                if direction == "LONG":
                    if l <= entry:
                        act_idx = j
                        break
                else:
                    if h >= entry:
                        act_idx = j
                        break
            if act_idx is None:
                return "not_filled"

        # Симуляция SL/TP с активации
        for j in range(act_idx, len(times)):
            h, l = highs[j], lows[j]
            if direction == "LONG":
                if l <= sl:
                    return "loss"
                if h >= tp:
                    return "win"
            else:
                if h >= sl:
                    return "loss"
                if l <= tp:
                    return "win"
        return "open"

    results = []
    total_combos = len(ENTRY_PCTS) * len(SL_BUFFERS)
    done = 0
    for entry_pct in ENTRY_PCTS:
        for sl_buffer in SL_BUFFERS:
            wins = losses = nf = openn = 0
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
                    nf += 1
                    continue

                sl_dist = raw_risk * sl_buffer
                if r["direction"] == "LONG":
                    sl = entry - sl_dist
                    tp = entry + sl_dist  # RR=1
                else:
                    sl = entry + sl_dist
                    tp = entry - sl_dist

                outcome = simulate_one(r["direction"], r["signal_time"], entry, sl, tp, market_fill)
                if outcome == "win":
                    wins += 1
                elif outcome == "loss":
                    losses += 1
                elif outcome == "not_filled":
                    nf += 1
                else:
                    openn += 1

            filled = wins + losses
            wr = wins / filled * 100 if filled > 0 else 0.0
            pnl = wins - losses
            results.append({
                "entry_pct": entry_pct,
                "sl_buffer": sl_buffer,
                "filled": filled,
                "not_filled": nf,
                "open": openn,
                "wins": wins,
                "losses": losses,
                "wr_pct": round(wr, 1),
                "pnl_R": pnl,
            })
            done += 1
            print(f"[{done}/{total_combos}] e={entry_pct} sl={sl_buffer}: filled={filled} W={wins} L={losses} nf={nf} WR={wr:.1f}% PnL={pnl:+d}R")

    df_res = pd.DataFrame(results)
    df_res = df_res.sort_values("pnl_R", ascending=False)
    df_res.to_csv("signals/vic_optimize_entry_sl.csv", index=False)
    print()
    print("=== TOP 10 по PnL ===")
    print(df_res.head(10).to_string(index=False))
    print()
    print("=== TOP 10 по WR (filled >= 300) ===")
    print(df_res[df_res["filled"] >= 300].sort_values("wr_pct", ascending=False).head(10).to_string(index=False))


if __name__ == "__main__":
    main()
