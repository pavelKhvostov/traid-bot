"""H12 — TP по NWE-каналу: выход когда ema_3 пересекает противоположную
границу Гауссова канала на 1h.

Для LONG: TP = первая 1h-свеча close после активации, где ema_3 > nwe_upper.
Для SHORT: ema_3 < nwe_lower.
SL — оригинальный (low(c0_1h) / high(c0_1h)). Timeout 7 дней.

Result: R = (exit_price - entry) / risk для LONG, симметрично для SHORT.

Сравниваем с baseline RR=1 и RR=1.5/2.0 фикс-TP.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    if _ROOT.parent == _ROOT:
        raise RuntimeError("repo root not found")
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
_RSI_DIR = _ROOT / "research" / "asvk_rsi"
if str(_RSI_DIR) not in _sys.path:
    _sys.path.insert(0, str(_RSI_DIR))

from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import load_df
from plot_asvk_rsi import (
    NWE_BANDWIDTH, NWE_BAR, NWE_MULTIPLIER,
    adjusted_rsi, nwe_bands,
)

ENRICHED_CSV = Path("signals/strategy_3_2_3y_RR1_with_asvk_part1.csv")
OUT_CSV = Path("signals/strategy_3_2_nwe_tp_h12.csv")
SYMBOL = "BTCUSDT"
TIMEOUT_DAYS = 7


def parse_utc3(s):
    if pd.isna(s) or s == "":
        return None
    return pd.Timestamp(s, tz="UTC") - pd.Timedelta(hours=3)


def simulate_nwe_tp(sig: pd.Series, df_1m: pd.DataFrame, df_1h: pd.DataFrame,
                    ema_3: pd.Series, upper: pd.Series, lower: pd.Series):
    """Возвращает (outcome, R, exit_type, exit_time).

    outcome: 'win' (NWE-cross or partial profit), 'loss' (SL), 'timeout', 'not_filled'.
    R = реальный R от entry с учётом exit_price.
    """
    if sig["outcome"] == "not_filled":
        return "not_filled", 0.0, "not_filled", None

    activation_time = parse_utc3(sig["activation_time"])
    if activation_time is None:
        return "not_filled", 0.0, "not_filled", None

    direction = sig["direction"]
    entry = float(sig["entry"])
    sl = float(sig["sl"])
    risk = abs(entry - sl)
    timeout_time = activation_time + pd.Timedelta(days=TIMEOUT_DAYS)

    # Сначала найти SL_hit_time на 1m (если есть)
    sim_1m = df_1m[(df_1m.index >= activation_time) & (df_1m.index <= timeout_time)]
    sl_hit_time = None
    for ts, c in sim_1m.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction == "LONG" and l <= sl:
            sl_hit_time = ts
            break
        if direction == "SHORT" and h >= sl:
            sl_hit_time = ts
            break

    # NWE cross на 1h: первая 1h свеча после activation, где ema_3 пересек границу
    sim_1h = df_1h[(df_1h.index >= activation_time) & (df_1h.index <= timeout_time)]
    nwe_cross_time = None
    nwe_cross_price = None
    for ts in sim_1h.index:
        em = ema_3.loc[ts] if ts in ema_3.index else None
        up = upper.loc[ts] if ts in upper.index else None
        lo = lower.loc[ts] if ts in lower.index else None
        if em is None or up is None or lo is None or np.isnan(em) or np.isnan(up) or np.isnan(lo):
            continue
        if direction == "LONG" and em > up:
            nwe_cross_time = ts
            nwe_cross_price = float(sim_1h.loc[ts, "close"])
            break
        if direction == "SHORT" and em < lo:
            nwe_cross_time = ts
            nwe_cross_price = float(sim_1h.loc[ts, "close"])
            break

    # Решаем exit
    if sl_hit_time is None and nwe_cross_time is None:
        return "timeout", 0.0, "timeout", None
    if nwe_cross_time is None:
        # только SL
        r = (sl - entry) / risk if direction == "LONG" else (entry - sl) / risk
        return "loss", r, "sl", sl_hit_time
    if sl_hit_time is None or nwe_cross_time <= sl_hit_time:
        # NWE cross победил
        r = (nwe_cross_price - entry) / risk if direction == "LONG" else (entry - nwe_cross_price) / risk
        outcome = "win" if r > 0 else ("loss" if r < 0 else "open")
        return outcome, r, "nwe_cross", nwe_cross_time
    # SL hit раньше
    r = (sl - entry) / risk if direction == "LONG" else (entry - sl) / risk
    return "loss", r, "sl", sl_hit_time


def main():
    print(f"[INFO] загрузка enriched CSV: {ENRICHED_CSV}")
    enriched = pd.read_csv(ENRICHED_CSV)
    print(f"  rows: {len(enriched)}")

    print(f"[INFO] загрузка {SYMBOL} 1m, 1h")
    df_1m = load_df(SYMBOL, "1m")
    df_1h = load_df(SYMBOL, "1h")
    print(f"  1m={len(df_1m)} 1h={len(df_1h)}")

    print("[INFO] ASVK на 1h (для NWE)")
    ema_3 = adjusted_rsi(df_1h["close"])
    _, upper, lower = nwe_bands(ema_3, NWE_BAR, NWE_BANDWIDTH, NWE_MULTIPLIER)

    print("[INFO] симуляция NWE-TP")
    results = []
    for _, sig in enriched.iterrows():
        out, r, etype, etime = simulate_nwe_tp(sig, df_1m, df_1h, ema_3, upper, lower)
        results.append({"nwe_outcome": out, "nwe_R": r, "nwe_exit_type": etype})
    res_df = pd.DataFrame(results)
    out_df = pd.concat([enriched.reset_index(drop=True), res_df], axis=1)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(OUT_CSV, index=False)
    print(f"[OK] saved: {OUT_CSV}")

    def report(label: str, mask):
        sub = out_df[mask]
        n = len(sub)
        if n == 0:
            print(f"  {label:<40s}  n=0")
            return
        # NWE TP
        closed_nwe = sub[sub["nwe_outcome"].isin(["win", "loss"])]
        timeouts = (sub["nwe_outcome"] == "timeout").sum()
        total_R = sub["nwe_R"].sum()
        n_win = int((sub["nwe_outcome"] == "win").sum())
        n_loss = int((sub["nwe_outcome"] == "loss").sum())
        wr = n_win / (n_win + n_loss) * 100 if (n_win + n_loss) > 0 else 0
        avg_r_win = sub.loc[sub["nwe_outcome"] == "win", "nwe_R"].mean() if n_win > 0 else 0
        rt = total_R / n if n else 0
        print(f"  {label:<40s}  n={n:<3d} W={n_win} L={n_loss} TO={timeouts}  "
              f"WR={wr:5.1f}%  TotalR={total_R:+5.1f}  avgWin={avg_r_win:+.2f}R  R/tr={rt:+.3f}")

    closed = out_df[out_df["outcome"].isin(["win", "loss"])]
    long_mask = out_df["direction"] == "LONG"
    short_mask = out_df["direction"] == "SHORT"
    aligned_long = long_mask & ((out_df["bull_div_in_window"] == True) | (out_df["h_bull_div_in_window"] == True))
    aligned_short = short_mask & ((out_df["bear_div_in_window"] == True) | (out_df["h_bear_div_in_window"] == True))
    h1 = aligned_long | aligned_short

    print()
    print("=" * 110)
    print("NWE-TP результаты по сегментам")
    print("=" * 110)
    report("ALL signals", pd.Series(True, index=out_df.index))
    report("ALL closed (orig wasn't not_filled)", out_df["outcome"] != "not_filled")
    report("LONG", long_mask)
    report("SHORT", short_mask)
    report("H1: aligned div", h1)
    report("DEEP div (top 50%)",
           h1 & (out_df[["max_bull_depth_in_window", "max_h_bull_depth_in_window",
                         "max_bear_depth_in_window", "max_h_bear_depth_in_window"]].max(axis=1)
                 >= out_df[["max_bull_depth_in_window", "max_h_bull_depth_in_window",
                            "max_bear_depth_in_window", "max_h_bear_depth_in_window"]].max(axis=1).median()))


if __name__ == "__main__":
    main()
