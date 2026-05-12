"""H9 — Multi-TF ASVK RSI: confluence по 4h-уровню в момент touch_time
помимо 1h-уровня в signal_time.

Считаем ASVK на df_4h, сегментируем сигналы по:
  - rsi_4h_at_touch — ema_3 на 4h в момент touch (округлённо до бара)
  - 4h_in_OS / 4h_in_OB
  - совпадение 1h-сегмента и 4h-сегмента (double-confluence)
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
    BARS_TO_LOOK_BACK,
    NWE_BANDWIDTH, NWE_BAR, NWE_MULTIPLIER,
    adjusted_rsi, dynamic_levels, nwe_bands,
)

ENRICHED_CSV = Path("signals/strategy_3_2_3y_RR1_with_asvk_part1.csv")
OUT_CSV = Path("signals/strategy_3_2_multi_tf_h9.csv")
SYMBOL = "BTCUSDT"
RR = 1.0


def parse_utc3(s):
    if pd.isna(s) or s == "":
        return None
    return pd.Timestamp(s, tz="UTC") - pd.Timedelta(hours=3)


def stats(closed: pd.DataFrame, label: str, total: int):
    n = len(closed)
    if n == 0:
        return f"  {label:<55s}  n=0"
    w = int((closed["outcome"] == "win").sum())
    l = n - w
    wr = w / n * 100
    pnl = w * RR - l
    rt = pnl / n
    share = n / total * 100 if total else 0
    return (f"  {label:<55s}  n={n:<3d} ({share:5.1f}%)  W={w:<3d} L={l:<3d}  "
            f"WR={wr:5.1f}%  PnL={pnl:+5.1f}R  R/tr={rt:+.3f}")


def main():
    print(f"[INFO] загрузка enriched CSV: {ENRICHED_CSV}")
    enriched = pd.read_csv(ENRICHED_CSV)
    print(f"  rows: {len(enriched)}")

    print(f"[INFO] загрузка {SYMBOL} 4h")
    df_4h = load_df(SYMBOL, "4h")
    print(f"  bars: {len(df_4h)}")

    print("[INFO] ASVK RSI на 4h")
    ema_3_4h = adjusted_rsi(df_4h["close"])
    above_4h, below_4h = dynamic_levels(ema_3_4h, BARS_TO_LOOK_BACK)
    _, upper_4h, lower_4h = nwe_bands(ema_3_4h, NWE_BAR, NWE_BANDWIDTH, NWE_MULTIPLIER)

    print("[INFO] обогащение")
    rsi_4h_signal = []
    above_4h_signal = []
    below_4h_signal = []
    nwe_up_4h = []
    nwe_lo_4h = []
    rsi_4h_touch = []

    for _, sig in enriched.iterrows():
        st = parse_utc3(sig["signal_time"])
        tt = parse_utc3(sig["touch_time"])

        # 4h-snapshot at signal_time
        ipos = df_4h.index.get_indexer([st], method="ffill")[0]
        if ipos >= 0:
            rsi_4h_signal.append(float(ema_3_4h.iloc[ipos]))
            above_4h_signal.append(float(above_4h.iloc[ipos]))
            below_4h_signal.append(float(below_4h.iloc[ipos]))
            nwe_up_4h.append(float(upper_4h.iloc[ipos]))
            nwe_lo_4h.append(float(lower_4h.iloc[ipos]))
        else:
            rsi_4h_signal.append(np.nan)
            above_4h_signal.append(np.nan)
            below_4h_signal.append(np.nan)
            nwe_up_4h.append(np.nan)
            nwe_lo_4h.append(np.nan)

        # 4h-rsi at touch_time (тот же 4h бар = touch_time)
        ipos2 = df_4h.index.get_indexer([tt], method="ffill")[0]
        rsi_4h_touch.append(float(ema_3_4h.iloc[ipos2]) if ipos2 >= 0 else np.nan)

    enriched["rsi_4h_at_signal"] = rsi_4h_signal
    enriched["above_4h_at_signal"] = above_4h_signal
    enriched["below_4h_at_signal"] = below_4h_signal
    enriched["nwe_upper_4h_at_signal"] = nwe_up_4h
    enriched["nwe_lower_4h_at_signal"] = nwe_lo_4h
    enriched["rsi_4h_at_touch"] = rsi_4h_touch
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_csv(OUT_CSV, index=False)
    print(f"[OK] saved: {OUT_CSV}")

    closed = enriched[enriched["outcome"].isin(["win", "loss"])].copy()
    total = len(closed)
    long_mask = closed["direction"] == "LONG"
    short_mask = closed["direction"] == "SHORT"

    print()
    print("=" * 110)
    print("H9 — MULTI-TF ASVK RSI на 4h")
    print("=" * 110)
    print(f"baseline: closed={total}  W={int((closed['outcome']=='win').sum())}  "
          f"WR={(closed['outcome']=='win').mean()*100:.1f}%  "
          f"PnL={int((closed['outcome']=='win').sum())*RR - int((closed['outcome']=='loss').sum()):+.1f}R")
    print()

    # 1) 4h ema_3 in OS / OB extremes
    print("--- 4h ema_3 vs current_value 4h (OS/OB на 4h) ---")
    long_in_os_4h = long_mask & (closed["rsi_4h_at_signal"] < closed["below_4h_at_signal"])
    short_in_ob_4h = short_mask & (closed["rsi_4h_at_signal"] > closed["above_4h_at_signal"])
    print(stats(closed[long_in_os_4h], "LONG + rsi_4h<below_4h", total))
    print(stats(closed[short_in_ob_4h], "SHORT + rsi_4h>above_4h", total))
    aligned_4h_extreme = long_in_os_4h | short_in_ob_4h
    print(stats(closed[aligned_4h_extreme], "ALL aligned 4h-extreme", total))
    print(stats(closed[~aligned_4h_extreme], "ALL non-aligned 4h", total))
    print()

    # 2) 4h NWE
    print("--- 4h NWE bands ---")
    long_nwe_4h = long_mask & (closed["rsi_4h_at_signal"] < closed["nwe_lower_4h_at_signal"])
    short_nwe_4h = short_mask & (closed["rsi_4h_at_signal"] > closed["nwe_upper_4h_at_signal"])
    print(stats(closed[long_nwe_4h], "LONG + rsi_4h<NWE_lower_4h", total))
    print(stats(closed[short_nwe_4h], "SHORT + rsi_4h>NWE_upper_4h", total))
    aligned_4h_nwe = long_nwe_4h | short_nwe_4h
    print(stats(closed[aligned_4h_nwe], "ALL aligned 4h-NWE", total))
    print()

    # 3) Double-confluence: 4h + 1h aligned
    print("--- DOUBLE-CONFLUENCE: 4h-extreme + 1h-extreme ---")
    long_in_os_1h = long_mask & (closed["rsi_at_signal"] < closed["below_at_signal"])
    short_in_ob_1h = short_mask & (closed["rsi_at_signal"] > closed["above_at_signal"])
    aligned_1h = long_in_os_1h | short_in_ob_1h
    double_extreme = aligned_4h_extreme & aligned_1h
    print(stats(closed[double_extreme], "DOUBLE EXTREME (4h+1h)", total))
    print(stats(closed[aligned_4h_extreme & ~aligned_1h], "4h-only extreme", total))
    print(stats(closed[~aligned_4h_extreme & aligned_1h], "1h-only extreme", total))
    print()

    # 4) 4h-RSI relative position (above 50, below 50)
    print("--- 4h ema_3 vs 50 ---")
    long_4h_below50 = long_mask & (closed["rsi_4h_at_signal"] < 50)
    short_4h_above50 = short_mask & (closed["rsi_4h_at_signal"] >= 50)
    print(stats(closed[long_4h_below50], "LONG + rsi_4h<50", total))
    print(stats(closed[long_mask & ~long_4h_below50[long_mask].reindex(closed.index, fill_value=False)],
                "LONG + rsi_4h>=50", total))
    print(stats(closed[short_4h_above50], "SHORT + rsi_4h>=50", total))
    aligned_50 = long_4h_below50 | short_4h_above50
    print(stats(closed[aligned_50], "ALL aligned 4h-side-of-50", total))
    print(stats(closed[~aligned_50], "ALL non-aligned 4h-side-of-50", total))
    print()

    # 5) 4h-RSI delta (touch_to_signal)
    print("--- 4h-RSI velocity между touch_time и signal_time ---")
    closed["rsi_4h_velocity"] = closed["rsi_4h_at_signal"] - closed["rsi_4h_at_touch"]
    median_v = closed["rsi_4h_velocity"].median()
    long_4h_up = long_mask & (closed["rsi_4h_velocity"] > median_v)
    short_4h_down = short_mask & (closed["rsi_4h_velocity"] < median_v)
    print(f"  median 4h velocity: {median_v:.3f}")
    print(stats(closed[long_4h_up], "LONG + 4h-vel > median", total))
    print(stats(closed[short_4h_down], "SHORT + 4h-vel < median", total))
    aligned_vel_4h = long_4h_up | short_4h_down
    print(stats(closed[aligned_vel_4h], "ALL aligned 4h-velocity", total))


if __name__ == "__main__":
    main()
