"""i-RDRB + FVG-next: BTC с 2023-01-01, ТФ ∈ {1h, 2h, 90m}.

Setup (5 свечей):
  1-3:  V1 RDRB (тройка anchor=k-2, mid=k-1, trigger=k)
  4:    свеча k+1, чьё close пробивает зону V1 → инверсия (i-RDRB).
        - V1 LONG пробит вниз  → i-RDRB SHORT
        - V1 SHORT пробит вверх → i-RDRB LONG
  5:    свеча k+2 формирует FVG того же направления что i-RDRB
        (тройка c0=k, c1=k+1, c2=k+2).

Метрика: precision pivot 5-bar того же ТФ в окне [j+1, j+5] от FVG.c2
(LONG → HH, SHORT → LL) — как для OB+FVG.
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from strategies.strategy_rdrb import detect_rdrb
from strategies.strategy_1_1_1 import detect_fvg

CACHE = ROOT / "data" / "BTCUSDT_1m_vic_vadim.csv"
START = pd.Timestamp("2023-01-01", tz="UTC")
TFS = [("1h", "1h"), ("2h", "2h"), ("90m", "90min")]
WINDOW = 5


def load_1m() -> pd.DataFrame:
    df = pd.read_csv(CACHE, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def resample(df_1m: pd.DataFrame, freq: str) -> pd.DataFrame:
    return df_1m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])


def has_hh_pivot(highs: np.ndarray, lo: int, hi: int) -> bool:
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


def scan(df_tf: pd.DataFrame, label: str) -> dict:
    n = len(df_tf)
    highs = df_tf["high"].to_numpy()
    lows = df_tf["low"].to_numpy()
    closes = df_tf["close"].to_numpy()

    irdrb_long = irdrb_short = 0  # i-RDRB без FVG-фильтра (для сравнения)
    setups = 0
    long_total = long_hit = 0
    short_total = short_hit = 0

    for k in range(2, n - WINDOW - 4):
        rdrb = detect_rdrb(df_tf, k, zone_version="V1")
        if rdrb is None:
            continue
        # Свеча k+1 — попытка инверсии (close vs зона V1)
        c4_close = closes[k + 1]
        if rdrb.direction == "LONG":
            if not (c4_close < rdrb.bottom):
                continue
            i_dir = "SHORT"
            irdrb_short += 1
        else:  # SHORT
            if not (c4_close > rdrb.top):
                continue
            i_dir = "LONG"
            irdrb_long += 1

        # FVG на свече k+2, направление = i_dir, тройка (k, k+1, k+2)
        fvg = detect_fvg(df_tf, k + 2)
        if fvg is None or fvg.direction != i_dir:
            continue
        setups += 1
        j = k + 2
        lo, hi = j + 1, j + WINDOW
        if i_dir == "LONG":
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
    return {"tf": label, "irdrb_long": irdrb_long, "irdrb_short": irdrb_short,
            "setups": setups,
            "long_total": long_total, "long_hit": long_hit, "long_prec": long_p,
            "short_total": short_total, "short_hit": short_hit, "short_prec": short_p,
            "total_hit": total_hit, "total_prec": total_p}


def main():
    print("loading BTC 1m...", flush=True)
    df_1m = load_1m()
    df_1m = df_1m[df_1m.index >= START]
    print(f"  bars: {len(df_1m):,}  {df_1m.index.min()} → {df_1m.index.max()}", flush=True)

    print(f"\n{'TF':>5}  {'iRDRB_L':>7} {'iRDRB_S':>7}  {'setups':>7}  "
          f"{'LONG':>5} {'→HH':>5} {'%':>6}   {'SHORT':>6} {'→LL':>5} {'%':>6}   "
          f"{'Σhit':>5} {'Σ%':>6}")
    for label, freq in TFS:
        df_tf = resample(df_1m, freq)
        r = scan(df_tf, label)
        print(f"{r['tf']:>5}  {r['irdrb_long']:>7} {r['irdrb_short']:>7}  {r['setups']:>7}  "
              f"{r['long_total']:>5} {r['long_hit']:>5} {r['long_prec']:>6.2f}   "
              f"{r['short_total']:>6} {r['short_hit']:>5} {r['short_prec']:>6.2f}   "
              f"{r['total_hit']:>5} {r['total_prec']:>6.2f}")


if __name__ == "__main__":
    main()
