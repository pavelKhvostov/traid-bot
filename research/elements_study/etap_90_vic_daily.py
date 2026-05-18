"""Этап 90: ViC ASVK maxV для D-чарта (TF=D) с auto=true, mlt=100, prem=false.

Pine для D-чарта:
  tfC = 86400s
  rs_raw = 86400/100 = 864s
  rs = max(60, 864) = 864s (non-premium)
  LTF = timeframe.from_seconds(864) = 15m (closest valid, не 14m)

Reference от пользователя:
  2026-05-11 maxV = 81080
  2026-05-12 maxV = 80290
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import pandas as pd

from data_manager import compose_from_base, load_df
from vic_levels import calculate_vic_d


def main():
    df_1m = load_df("BTCUSDT", "1m")
    df_1d = load_df("BTCUSDT", "1d")
    print(f"1m range: {df_1m.index[0]} -> {df_1m.index[-1]}")
    print(f"1d range: {df_1d.index[0]} -> {df_1d.index[-1]}")

    # Reference от user'а
    targets = [
        ("2026-05-11", 81080),
        ("2026-05-12", 80290),
    ]

    print(f"\n{'='*80}")
    print(f"ViC maxV (TF=D, auto=true, mlt=100, non-premium, LTF=15m)")
    print(f"{'='*80}")
    print(f"{'Date':<12} {'maxV (15m)':<12} {'reference':<12} {'diff':<10} {'match':<6}")
    print("-" * 60)

    for date_str, ref in targets:
        day = pd.Timestamp(date_str, tz="UTC")
        # canon calc_vic_d с ltf_minutes=15 (соответствует Pine LTF=15m для D-chart mlt=100)
        maxV = calculate_vic_d(df_1m, day, ltf_minutes=15)
        if maxV is None:
            print(f"{date_str:<12} (no data)")
            continue
        diff = maxV - ref
        match = "OK" if abs(diff) < 50 else ("CLOSE" if abs(diff) < 500 else "FAIL")
        print(f"{date_str:<12} {maxV:>11.2f}  {ref:>11}  {diff:>+9.2f}  {match}")

    # Также сравним с 1m LTF (если бы prem=true и rs=864 → возможно округлилось бы вниз).
    print(f"\n--- Альтернативные LTF (sanity) ---")
    print(f"{'Date':<12} {'maxV-1m':<12} {'maxV-10m':<12} {'maxV-15m':<12} {'maxV-30m':<12}")
    for date_str, ref in targets:
        day = pd.Timestamp(date_str, tz="UTC")
        row = [date_str]
        for ltf in [1, 10, 15, 30]:
            v = calculate_vic_d(df_1m, day, ltf_minutes=ltf)
            row.append(f"{v:>11.2f}" if v else "—".rjust(11))
        print(f"{row[0]:<12} {row[1]} {row[2]} {row[3]} {row[4]}")
        print(f"  (ref = {ref})")


if __name__ == "__main__":
    main()
