"""Считает i-RDRB + FVG (FVG в ту же сторону) на BTCUSDT 1h за 6 лет."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.i_rdrb.code import detect_i_rdrb
from elements.fvg.code import detect_fvg

INTERVAL = "1h"
END = datetime(2026, 5, 23, 0, 0, 0, tzinfo=timezone.utc)
START = END - timedelta(days=365 * 6)


def fetch_chunk(start_ms: int, end_ms: int):
    url = (
        f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval={INTERVAL}"
        f"&startTime={start_ms}&endTime={end_ms}&limit=1000"
    )
    return json.loads(subprocess.check_output(["curl", "-s", url], timeout=30))


def fetch_all():
    candles: list[Candle] = []
    cursor = int(START.timestamp() * 1000)
    end_ms = int(END.timestamp() * 1000)
    while cursor < end_ms:
        chunk = fetch_chunk(cursor, end_ms)
        if not chunk:
            break
        for k in chunk:
            candles.append(Candle(
                open=float(k[1]), high=float(k[2]), low=float(k[3]), close=float(k[4]),
                open_time=int(k[0]),
            ))
        cursor = int(chunk[-1][0]) + 60 * 60 * 1000
        if len(chunk) < 1000:
            break
    return candles


print(f"Fetching BTCUSDT {INTERVAL} {START.date()} → {END.date()}...")
candles = fetch_all()
print(f"Fetched {len(candles)} candles\n")

i_rdrb_total = 0
i_rdrb_plus_fvg_same = {"long": 0, "short": 0}
i_rdrb_plus_fvg_any = {"long": 0, "short": 0}
i_rdrb_no_fvg = {"long": 0, "short": 0}
i_rdrb_fvg_opposite = {"long": 0, "short": 0}

for i in range(len(candles) - 4):
    c1, c2, c3, c4, c5 = candles[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None:
        continue
    i_rdrb_total += 1
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None:
        i_rdrb_no_fvg[ir.direction] += 1
        continue
    i_rdrb_plus_fvg_any[ir.direction] += 1
    if fvg.direction == ir.direction:
        i_rdrb_plus_fvg_same[ir.direction] += 1
    else:
        i_rdrb_fvg_opposite[ir.direction] += 1

same_total = i_rdrb_plus_fvg_same["long"] + i_rdrb_plus_fvg_same["short"]
any_total = i_rdrb_plus_fvg_any["long"] + i_rdrb_plus_fvg_any["short"]
no_fvg_total = i_rdrb_no_fvg["long"] + i_rdrb_no_fvg["short"]
opp_total = i_rdrb_fvg_opposite["long"] + i_rdrb_fvg_opposite["short"]

print(f"i-RDRB всего:                            {i_rdrb_total}")
print(f"  с FVG в ту же сторону (same):          {same_total}")
print(f"     LONG:   {i_rdrb_plus_fvg_same['long']}")
print(f"     SHORT:  {i_rdrb_plus_fvg_same['short']}")
print(f"  с FVG в обратную сторону (opposite):   {opp_total}")
print(f"     LONG i-RDRB + SHORT FVG: {i_rdrb_fvg_opposite['long']}")
print(f"     SHORT i-RDRB + LONG FVG: {i_rdrb_fvg_opposite['short']}")
print(f"  без FVG (C3-C4-C5 не FVG):             {no_fvg_total}")
print(f"     LONG:   {i_rdrb_no_fvg['long']}")
print(f"     SHORT:  {i_rdrb_no_fvg['short']}")
print()
print(f"Доля i-RDRB → FVG-same: {same_total / i_rdrb_total * 100:.1f}%")
print(f"Доля i-RDRB → FVG-any:  {any_total / i_rdrb_total * 100:.1f}%")
print(f"Частота i-RDRB+FVG-same: {same_total / (len(candles) / (365 * 24)):.1f}/год")
