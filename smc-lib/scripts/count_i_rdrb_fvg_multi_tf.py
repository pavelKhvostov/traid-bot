"""Сводка i-RDRB и i-RDRB+FVG на BTCUSDT за 6 лет на разных ТФ."""
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

END = datetime(2026, 5, 23, 0, 0, 0, tzinfo=timezone.utc)
START = END - timedelta(days=365 * 6)

TFS = [("2h", 2), ("4h", 4), ("6h", 6), ("8h", 8), ("12h", 12)]


def fetch_chunk(interval, start_ms, end_ms):
    url = (
        f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval={interval}"
        f"&startTime={start_ms}&endTime={end_ms}&limit=1000"
    )
    return json.loads(subprocess.check_output(["curl", "-s", url], timeout=30))


def fetch_all(interval, tf_hours):
    candles: list[Candle] = []
    cursor = int(START.timestamp() * 1000)
    end_ms = int(END.timestamp() * 1000)
    step_ms = tf_hours * 60 * 60 * 1000
    while cursor < end_ms:
        chunk = fetch_chunk(interval, cursor, end_ms)
        if not chunk:
            break
        for k in chunk:
            candles.append(Candle(
                open=float(k[1]), high=float(k[2]), low=float(k[3]), close=float(k[4]),
                open_time=int(k[0]),
            ))
        cursor = int(chunk[-1][0]) + step_ms
        if len(chunk) < 1000:
            break
    return candles


print(f"{'TF':<5} {'Candles':<8} {'i-RDRB':<8} {'+FVG-same':<11} {'%FVG':<7} {'long':<6} {'short':<6} {'/year':<7}")
print("-" * 70)

for interval, h in TFS:
    candles = fetch_all(interval, h)
    n_irdrb = 0
    n_fvg = {"long": 0, "short": 0}
    for i in range(len(candles) - 4):
        c1, c2, c3, c4, c5 = candles[i:i + 5]
        ir = detect_i_rdrb(c1, c2, c3, c4)
        if ir is None:
            continue
        n_irdrb += 1
        fvg = detect_fvg(c3, c4, c5)
        if fvg is not None and fvg.direction == ir.direction:
            n_fvg[ir.direction] += 1
    fvg_total = n_fvg["long"] + n_fvg["short"]
    pct = fvg_total / n_irdrb * 100 if n_irdrb else 0
    years = len(candles) / (24 / h * 365)
    per_year = fvg_total / years if years else 0
    print(f"{interval:<5} {len(candles):<8} {n_irdrb:<8} {fvg_total:<11} {pct:<6.1f}% {n_fvg['long']:<6} {n_fvg['short']:<6} {per_year:<7.1f}")
