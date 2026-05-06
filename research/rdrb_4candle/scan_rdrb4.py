"""4-candle RDRB scanner — finds latest signals on 1h/2h BTC.

Geometry (SHORT, mirror for LONG):
- c1: any candle with a lower wick (c1.body_low > c1.low)
- c2: fully inside lower wick of c1
       c2.high <= c1.body_low  AND  c2.low >= c1.low
- c3: body fully absorbs lower wick of c2
       c3.body_high <= c2.low
- c4: upper wick enters lower wick of c2 (partial overlap)
       c4.high > c2.low  AND  c4.high < c1.body_low
- Zone: [c4.high, c1.low]  (low, high)

Trigger = c4 close. We list raw structures here (no retest/confirmation).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def body_low(o, c):
    return min(o, c)


def body_high(o, c):
    return max(o, c)


def is_short_rdrb4(c1, c2, c3, c4):
    # c1 = i-3, c2 = i-2, c3 = i-1, c4 = i
    if not (c1.low > c2.low):
        return False
    if not (c1.low < c2.close):
        return False
    if not (c2.low < c4.high):
        return False
    if not (c3.close < c2.low):
        return False
    if not (c1.low > c4.high):
        return False
    return True


def is_long_rdrb4(c1, c2, c3, c4):
    # mirror: swap low/high
    if not (c1.high < c2.high):
        return False
    if not (c1.high > c2.close):
        return False
    if not (c2.high > c4.low):
        return False
    if not (c3.close > c2.high):
        return False
    if not (c1.high < c4.low):
        return False
    return True


def scan(df: pd.DataFrame, tf_label: str):
    out = []
    rows = df.reset_index(drop=True)
    for i in range(len(rows) - 3):
        c1, c2, c3, c4 = rows.iloc[i], rows.iloc[i + 1], rows.iloc[i + 2], rows.iloc[i + 3]
        if is_short_rdrb4(c1, c2, c3, c4):
            out.append(
                {
                    "tf": tf_label,
                    "dir": "SHORT",
                    "c1_time": c1.open_time,
                    "c4_time": c4.open_time,
                    "zone_low": float(c4.high),
                    "zone_high": float(c1.low),
                }
            )
        elif is_long_rdrb4(c1, c2, c3, c4):
            out.append(
                {
                    "tf": tf_label,
                    "dir": "LONG",
                    "c1_time": c1.open_time,
                    "c4_time": c4.open_time,
                    "zone_low": float(c1.high),
                    "zone_high": float(c4.low),
                }
            )
    return out


def main():
    results = []
    for tf in ["1h", "2h"]:
        path = ROOT / "data" / f"BTCUSDT_{tf}.csv"
        df = pd.read_csv(path, parse_dates=["open_time"])
        results.extend(scan(df, tf))

    results.sort(key=lambda r: r["c4_time"], reverse=True)

    print(f"\nTotal RDRB-4 found: {len(results)}\n")
    print("Latest 6 (3 per TF):")
    seen = {"1h": 0, "2h": 0}
    for r in results:
        if seen[r["tf"]] >= 3:
            continue
        seen[r["tf"]] += 1
        print(
            f"  {r['tf']:>3}  {r['dir']:<5}  c1={r['c1_time']}  "
            f"c4_close={r['c4_time']}  zone=[{r['zone_low']:.2f}, {r['zone_high']:.2f}]"
        )
        if all(v >= 3 for v in seen.values()):
            break


if __name__ == "__main__":
    main()
