"""H13 — Trailing exit по противоположной дивергенции после активации.
H14 — Cancellation лимита если ema_3 пробивает противоположный край NWE
       между signal_time и activation_time.

H13 (trailing for LONG): после активации, если на 1h confirms-баре найдена
   bear/h_bear divergence — закрытие по close 1h. SL остаётся.
   (для SHORT — bull/h_bull div).

H14 (cancellation for LONG): между signal_time и activation_time, если
   ema_3 < nwe_lower на 1h close — отмена (not_filled). Для SHORT —
   ema_3 > nwe_upper.

Сравнение с baseline на тех же сделках.
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
    LB_L, LB_R, NWE_BANDWIDTH, NWE_BAR, NWE_MULTIPLIER,
    RANGE_LOWER, RANGE_UPPER,
    adjusted_rsi, find_divergences, nwe_bands,
)

ENRICHED_CSV = Path("signals/strategy_3_2_3y_RR1_with_asvk_part1.csv")
OUT_CSV = Path("signals/strategy_3_2_h13_h14.csv")
SYMBOL = "BTCUSDT"
RR = 1.0
TIMEOUT_DAYS = 14


def parse_utc3(s):
    if pd.isna(s) or s == "":
        return None
    return pd.Timestamp(s, tz="UTC") - pd.Timedelta(hours=3)


def main():
    print(f"[INFO] загрузка enriched CSV: {ENRICHED_CSV}")
    enriched = pd.read_csv(ENRICHED_CSV)
    print(f"  rows: {len(enriched)}")

    print(f"[INFO] загрузка {SYMBOL} 1m, 1h")
    df_1m = load_df(SYMBOL, "1m")
    df_1h = load_df(SYMBOL, "1h")
    print(f"  1m={len(df_1m)} 1h={len(df_1h)}")

    print("[INFO] ASVK на 1h")
    ema_3 = adjusted_rsi(df_1h["close"])
    _, upper, lower = nwe_bands(ema_3, NWE_BAR, NWE_BANDWIDTH, NWE_MULTIPLIER)
    bull, h_bull, bear, h_bear = find_divergences(
        ema_3, df_1h["low"], df_1h["high"],
        LB_L, LB_R, RANGE_LOWER, RANGE_UPPER,
    )
    # confirmation times
    bull_t = pd.DatetimeIndex([df_1h.index[d[0] + LB_R] for d in bull], tz="UTC")
    h_bull_t = pd.DatetimeIndex([df_1h.index[d[0] + LB_R] for d in h_bull], tz="UTC")
    bear_t = pd.DatetimeIndex([df_1h.index[d[0] + LB_R] for d in bear], tz="UTC")
    h_bear_t = pd.DatetimeIndex([df_1h.index[d[0] + LB_R] for d in h_bear], tz="UTC")
    print(f"  divs: bull={len(bull_t)} h_bull={len(h_bull_t)} "
          f"bear={len(bear_t)} h_bear={len(h_bear_t)}")

    print("[INFO] симуляция H13 trailing")
    h13_results = []
    for _, sig in enriched.iterrows():
        if sig["outcome"] == "not_filled":
            h13_results.append({"h13_outcome": "not_filled", "h13_R": 0.0, "h13_exit": "not_filled"})
            continue
        direction = sig["direction"]
        entry = float(sig["entry"])
        sl = float(sig["sl"])
        tp = float(sig["tp"])
        risk = abs(entry - sl)
        activation_time = parse_utc3(sig["activation_time"])
        if activation_time is None:
            h13_results.append({"h13_outcome": "not_filled", "h13_R": 0.0, "h13_exit": "not_filled"})
            continue
        timeout_time = activation_time + pd.Timedelta(days=TIMEOUT_DAYS)
        sim_1m = df_1m[(df_1m.index >= activation_time) & (df_1m.index <= timeout_time)]

        # Сначала классические SL/TP — самый ранний
        sl_time, tp_time = None, None
        for ts, c in sim_1m.iterrows():
            h, l = float(c["high"]), float(c["low"])
            if direction == "LONG":
                if l <= sl and sl_time is None:
                    sl_time = ts
                if h >= tp and tp_time is None:
                    tp_time = ts
            else:
                if h >= sl and sl_time is None:
                    sl_time = ts
                if l <= tp and tp_time is None:
                    tp_time = ts
            if sl_time and tp_time:
                break

        # H13 — противоположная divergence на 1h
        opp_times = bear_t.union(h_bear_t) if direction == "LONG" else bull_t.union(h_bull_t)
        opp_in_window = opp_times[(opp_times >= activation_time) & (opp_times <= timeout_time)]
        opp_div_time = opp_in_window[0] if len(opp_in_window) > 0 else None
        opp_div_close = None
        if opp_div_time is not None and opp_div_time in df_1h.index:
            opp_div_close = float(df_1h.loc[opp_div_time, "close"])

        # Решаем
        candidates = []
        if sl_time is not None:
            candidates.append((sl_time, "sl", sl))
        if tp_time is not None:
            candidates.append((tp_time, "tp", tp))
        if opp_div_time is not None and opp_div_close is not None:
            candidates.append((opp_div_time, "opp_div", opp_div_close))
        if not candidates:
            h13_results.append({"h13_outcome": "timeout", "h13_R": 0.0, "h13_exit": "timeout"})
            continue
        candidates.sort(key=lambda x: x[0])
        first_t, first_type, first_price = candidates[0]
        if direction == "LONG":
            r = (first_price - entry) / risk
        else:
            r = (entry - first_price) / risk
        outcome = "win" if r > 0 else ("loss" if r < 0 else "open")
        h13_results.append({"h13_outcome": outcome, "h13_R": r, "h13_exit": first_type})

    enriched_h13 = pd.concat([enriched.reset_index(drop=True),
                              pd.DataFrame(h13_results)], axis=1)

    print("[INFO] симуляция H14 cancellation")
    h14_results = []
    for _, sig in enriched_h13.iterrows():
        if sig["outcome"] == "not_filled":
            h14_results.append({"h14_outcome": "not_filled", "h14_R": 0.0})
            continue
        signal_time = parse_utc3(sig["signal_time"])
        activation_time = parse_utc3(sig["activation_time"])
        if signal_time is None or activation_time is None:
            h14_results.append({"h14_outcome": "not_filled", "h14_R": 0.0})
            continue
        direction = sig["direction"]
        # сканируем 1h close между signal_time и activation_time
        scan_window = df_1h[(df_1h.index >= signal_time) & (df_1h.index < activation_time)]
        cancelled = False
        for ts in scan_window.index:
            em = float(ema_3.loc[ts])
            up = float(upper.loc[ts]) if not np.isnan(upper.loc[ts]) else None
            lo = float(lower.loc[ts]) if not np.isnan(lower.loc[ts]) else None
            if up is None or lo is None:
                continue
            if direction == "LONG" and em < lo:
                cancelled = True
                break
            if direction == "SHORT" and em > up:
                cancelled = True
                break
        if cancelled:
            h14_results.append({"h14_outcome": "cancelled", "h14_R": 0.0})
        else:
            # без cancellation — берём оригинальный outcome
            if sig["outcome"] == "win":
                h14_results.append({"h14_outcome": "win", "h14_R": RR})
            elif sig["outcome"] == "loss":
                h14_results.append({"h14_outcome": "loss", "h14_R": -1.0})
            else:
                h14_results.append({"h14_outcome": sig["outcome"], "h14_R": 0.0})

    enriched_full = pd.concat([enriched_h13.reset_index(drop=True),
                               pd.DataFrame(h14_results)], axis=1)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    enriched_full.to_csv(OUT_CSV, index=False)
    print(f"[OK] saved: {OUT_CSV}")

    def report_h13(label: str, mask):
        sub = enriched_full[mask]
        n = len(sub)
        if n == 0:
            print(f"  {label:<35s} n=0")
            return
        cl = sub[sub["h13_outcome"].isin(["win", "loss"])]
        if len(cl) == 0:
            print(f"  {label:<35s} n={n}  no closed")
            return
        w = int((cl["h13_outcome"] == "win").sum())
        l = len(cl) - w
        wr = w / len(cl) * 100
        total_r = sub["h13_R"].sum()
        rt = total_r / n
        opp_exits = (sub["h13_exit"] == "opp_div").sum()
        print(f"  {label:<35s}  n={n:<3d} W={w} L={l} (opp_div_exits={opp_exits})  "
              f"WR={wr:5.1f}%  TotalR={total_r:+5.1f}  R/tr={rt:+.3f}")

    def report_h14(label: str, mask):
        sub = enriched_full[mask]
        n = len(sub)
        if n == 0:
            return
        cancelled = (sub["h14_outcome"] == "cancelled").sum()
        cl = sub[sub["h14_outcome"].isin(["win", "loss"])]
        w = int((cl["h14_outcome"] == "win").sum())
        l = len(cl) - w
        wr = w / len(cl) * 100 if len(cl) else 0
        total_r = sub["h14_R"].sum()
        rt = total_r / n if n else 0
        print(f"  {label:<35s}  n={n} W={w} L={l} cancelled={cancelled}  "
              f"WR={wr:5.1f}%  TotalR={total_r:+5.1f}  R/tr={rt:+.3f}")

    long_mask = enriched_full["direction"] == "LONG"
    short_mask = enriched_full["direction"] == "SHORT"
    aligned_long = long_mask & ((enriched_full["bull_div_in_window"] == True)
                                | (enriched_full["h_bull_div_in_window"] == True))
    aligned_short = short_mask & ((enriched_full["bear_div_in_window"] == True)
                                  | (enriched_full["h_bear_div_in_window"] == True))
    h1 = aligned_long | aligned_short

    print()
    print("=" * 110)
    print("H13 — TRAILING ПО ПРОТИВОПОЛОЖНОЙ ДИВЕРГЕНЦИИ")
    print("=" * 110)
    report_h13("ALL", pd.Series(True, index=enriched_full.index))
    report_h13("LONG", long_mask)
    report_h13("SHORT", short_mask)
    report_h13("H1 aligned div", h1)

    print()
    print("=" * 110)
    print("H14 — CANCELLATION лимита (ema_3 пробивает противоположный NWE)")
    print("=" * 110)
    report_h14("ALL", pd.Series(True, index=enriched_full.index))
    report_h14("LONG", long_mask)
    report_h14("SHORT", short_mask)
    report_h14("H1 aligned div", h1)


if __name__ == "__main__":
    main()
