"""Для setup'а OB-X + FVG-X (offset +1) на BTC с 2023-01-01:
проверить, формируется ли 5-bar pivot того же ТФ в окне [j+1, j+5]
после FVG.c2 в ожидаемом направлении (LONG→HH, SHORT→LL).
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg

CACHE = ROOT / "data" / "BTCUSDT_1m_vic_vadim.csv"
START = pd.Timestamp("2023-01-01", tz="UTC")
TFS = [("1h", "1h"), ("2h", "2h"), ("90m", "90min")]
WINDOW = 5  # candidate pivot centers в [j+1, j+WINDOW]


def load_1m() -> pd.DataFrame:
    df = pd.read_csv(CACHE, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def resample(df_1m: pd.DataFrame, freq: str) -> pd.DataFrame:
    return df_1m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])


def has_hh_pivot(highs: np.ndarray, lo: int, hi: int) -> bool:
    """5-bar HH pivot с центром p в [lo, hi]. Нужны highs до p+2."""
    n = len(highs)
    for p in range(lo, hi + 1):
        if p - 2 < 0 or p + 2 >= n:
            continue
        h = highs[p]
        if h > highs[p - 2] and h > highs[p - 1] and h > highs[p + 1] and h > highs[p + 2]:
            return True
    return False


def has_ll_pivot(lows: np.ndarray, lo: int, hi: int) -> bool:
    n = len(lows)
    for p in range(lo, hi + 1):
        if p - 2 < 0 or p + 2 >= n:
            continue
        l = lows[p]
        if l < lows[p - 2] and l < lows[p - 1] and l < lows[p + 1] and l < lows[p + 2]:
            return True
    return False


def scan_tf(df_tf: pd.DataFrame, label: str) -> dict:
    n = len(df_tf)
    highs = df_tf["high"].to_numpy()
    lows = df_tf["low"].to_numpy()
    setups = 0
    long_total = 0; long_hit = 0
    short_total = 0; short_hit = 0
    for k in range(1, n - WINDOW - 2):  # запас на pivot confirmation
        ob = detect_ob_pair(df_tf, k)
        if ob is None:
            continue
        j = k + 1
        fvg = detect_fvg(df_tf, j)
        if fvg is None or fvg.direction != ob.direction:
            continue
        setups += 1
        lo, hi = j + 1, j + WINDOW
        if ob.direction == "LONG":
            long_total += 1
            if has_hh_pivot(highs, lo, hi):
                long_hit += 1
        else:
            short_total += 1
            if has_ll_pivot(lows, lo, hi):
                short_hit += 1
    long_p = long_hit / long_total * 100 if long_total else 0
    short_p = short_hit / short_total * 100 if short_total else 0
    total_hit = long_hit + short_hit
    total_p = total_hit / setups * 100 if setups else 0
    return {"tf": label, "setups": setups,
            "long_total": long_total, "long_hit": long_hit, "long_prec": long_p,
            "short_total": short_total, "short_hit": short_hit, "short_prec": short_p,
            "total_hit": total_hit, "total_prec": total_p}


def main():
    print("loading BTC 1m...", flush=True)
    df_1m = load_1m()
    df_1m = df_1m[df_1m.index >= START]
    print(f"  bars: {len(df_1m):,}  {df_1m.index.min()} → {df_1m.index.max()}", flush=True)

    print(f"\n{'TF':>5}  {'setups':>7}  {'LONG':>5} {'→HH':>5} {'%':>6}   {'SHORT':>6} {'→LL':>5} {'%':>6}   {'Σhit':>5} {'Σ%':>6}")
    for label, freq in TFS:
        df_tf = resample(df_1m, freq)
        r = scan_tf(df_tf, label)
        print(f"{r['tf']:>5}  {r['setups']:>7}  "
              f"{r['long_total']:>5} {r['long_hit']:>5} {r['long_prec']:>6.2f}   "
              f"{r['short_total']:>6} {r['short_hit']:>5} {r['short_prec']:>6.2f}   "
              f"{r['total_hit']:>5} {r['total_prec']:>6.2f}")


if __name__ == "__main__":
    main()
