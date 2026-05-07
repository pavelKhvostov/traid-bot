"""RR-sweep для Strategy 3.2: пересимуляция outcome для разных RR
на baseline и на ASVK-фильтрованных сегментах.

Использует strategy_3_2_3y_RR1_with_asvk.csv (детектор не запускается).
Активация уже посчитана; пересчитывается только TP по новому RR и
проверяется первое касание SL/TP на 1m.

Сегменты:
  baseline      — все 243 closed
  H1            — aligned divergence в [touch-6h, signal]
  H2_pro        — pro-trend regime (z>130 для LONG, z<70 для SHORT)
  H2_no_short_range — все, кроме SHORT в range-режиме
  H1 AND H2_pro   — пересечение фильтров
  H1 OR H2_no_short_range — объединение
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

from pathlib import Path

import pandas as pd

from data_manager import load_df

ENRICHED_CSV = Path("signals/strategy_3_2_3y_RR1_with_asvk.csv")
RRS = [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]
SYMBOL = "BTCUSDT"


def parse_utc3(s):
    if pd.isna(s) or s == "":
        return None
    return pd.Timestamp(s, tz="UTC") - pd.Timedelta(hours=3)


def resimulate(sig: pd.Series, df_1m: pd.DataFrame, rr: float) -> str:
    """Пересимуляция outcome при новом RR. Возвращает 'win'/'loss'/'open'/'not_filled'."""
    if sig["outcome"] == "not_filled":
        return "not_filled"
    direction = sig["direction"]
    entry = float(sig["entry"])
    sl = float(sig["sl"])
    risk = abs(entry - sl)
    if direction == "LONG":
        tp = entry + risk * rr
    else:
        tp = entry - risk * rr

    activation_time = parse_utc3(sig["activation_time"])
    if activation_time is None:
        return "not_filled"

    sim = df_1m[df_1m.index >= activation_time]
    for ts, c in sim.iterrows():
        h = float(c["high"])
        l = float(c["low"])
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


def stats_for(df: pd.DataFrame, rr: float) -> dict:
    closed = df[df["_outcome_rr"].isin(["win", "loss"])]
    n = len(closed)
    if n == 0:
        return {"n": 0, "wr": 0, "pnl": 0, "rt": 0}
    w = int((closed["_outcome_rr"] == "win").sum())
    l = n - w
    wr = w / n * 100
    pnl = w * rr - l
    return {"n": n, "wr": wr, "pnl": pnl, "rt": pnl / n if n else 0}


def main():
    print(f"[INFO] загрузка enriched CSV: {ENRICHED_CSV}")
    enriched = pd.read_csv(ENRICHED_CSV)
    print(f"  rows: {len(enriched)}")

    print(f"[INFO] загрузка {SYMBOL} 1m")
    df_1m = load_df(SYMBOL, "1m")
    print(f"  bars: {len(df_1m)}")

    # --- Сегменты ---
    long_mask = enriched["direction"] == "LONG"
    short_mask = enriched["direction"] == "SHORT"

    h1_long = (enriched["bull_div_in_window"] == True) | (enriched["h_bull_div_in_window"] == True)
    h1_short = (enriched["bear_div_in_window"] == True) | (enriched["h_bear_div_in_window"] == True)
    h1_aligned = (long_mask & h1_long) | (short_mask & h1_short)

    bull_regime = enriched["z_above_at_signal"] > 130
    bear_regime = enriched["z_above_at_signal"] < 70
    range_regime = ~bull_regime & ~bear_regime

    h2_pro_trend = (bull_regime & long_mask) | (bear_regime & short_mask)
    # «no SHORT in range» — H2 наблюдение: SHORT в range проседает
    h2_no_short_range = ~(range_regime & short_mask)

    segments = [
        ("baseline", pd.Series([True] * len(enriched), index=enriched.index)),
        ("H1 (aligned div)", h1_aligned),
        ("H2_pro_trend", h2_pro_trend),
        ("H2_no_short_range", h2_no_short_range),
        ("H1 AND H2_pro", h1_aligned & h2_pro_trend),
        ("H1 OR H2_pro", h1_aligned | h2_pro_trend),
        ("H1 AND H2_no_short_range", h1_aligned & h2_no_short_range),
    ]

    # --- RR-sweep ---
    results = {}  # results[seg_name][rr] = stats
    for rr in RRS:
        print(f"[INFO] resim RR={rr}")
        enriched["_outcome_rr"] = enriched.apply(
            lambda s: resimulate(s, df_1m, rr), axis=1,
        )
        for seg_name, mask in segments:
            sub = enriched[mask]
            results.setdefault(seg_name, {})[rr] = stats_for(sub, rr)

    # --- Печать таблицы ---
    print()
    print("=" * 110)
    print(f"{'segment':<28s} {'metric':<7s} " + " ".join(f"RR={rr:<5}" for rr in RRS))
    print("=" * 110)
    for seg_name, _ in segments:
        n_static = results[seg_name][RRS[0]]["n"]
        line_n = f"{seg_name:<28s} {'n':<7s} " + " ".join(f"{results[seg_name][rr]['n']:<8d}" for rr in RRS)
        line_wr = f"{'':<28s} {'WR%':<7s} " + " ".join(f"{results[seg_name][rr]['wr']:<8.1f}" for rr in RRS)
        line_pnl = f"{'':<28s} {'PnL_R':<7s} " + " ".join(f"{results[seg_name][rr]['pnl']:<+8.1f}" for rr in RRS)
        line_rt = f"{'':<28s} {'R/tr':<7s} " + " ".join(f"{results[seg_name][rr]['rt']:<+8.3f}" for rr in RRS)
        print(line_n)
        print(line_wr)
        print(line_pnl)
        print(line_rt)
        print("-" * 110)

    # Best per segment by R/trade (с минимальным n=20)
    print()
    print("=" * 78)
    print("BEST RR per segment (по R/trade, мин. n=20)")
    print("=" * 78)
    for seg_name, _ in segments:
        best_rr = None
        best_rt = -999
        for rr in RRS:
            r = results[seg_name][rr]
            if r["n"] < 20:
                continue
            if r["rt"] > best_rt:
                best_rt = r["rt"]
                best_rr = rr
        if best_rr is None:
            print(f"  {seg_name:<28s}  insufficient n")
            continue
        b = results[seg_name][best_rr]
        print(f"  {seg_name:<28s}  RR={best_rr:<4}  n={b['n']:<3d}  "
              f"WR={b['wr']:.1f}%  PnL={b['pnl']:+.1f}R  R/tr={b['rt']:+.3f}")


if __name__ == "__main__":
    main()
