"""Этап 39 (1.1.7-edition): Direction-specific composite filter.

Берём direction-aware features из etap_48 + ICT findings из etap_28
+ hull findings из etap_49. Строим best filter per direction, потом
combined filter для production-кандидата.

LONG features (winners):
  - hull_1h_L140 aligned (68.8% / +6R)
  - hull_1h_L160 aligned (68.8% / +6R)
  - mh_4h_color = red (64% / +15R)
  - Thu+Fri+Sat (60% / +12R combo)

SHORT features (winners):
  - hull_12h_L180 aligned (58.8% / +3R)
  - hull_12h_L160 aligned
  - asvk_1h = red (55% / +2R)
  - ema200_4h aligned

Combined criterion to test:
  - Filter A: weekday Thu+Fri+Sat (no London) → keep
  - Filter B: per-direction hull
  - Filter C: ASVK 4h (red excluded, yellow_OS/green preferred)
  - Filter D: mh_4h color (green/grey_from_green excluded)
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

_ELEMENTS = _ROOT / "research" / "elements_study"
if str(_ELEMENTS) not in _sys.path:
    _sys.path.insert(0, str(_ELEMENTS))

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from etap_35_strategy_111_forensic import hull_ma

SYMBOL = "BTCUSDT"
CSV = "research/1_1_7/forensic/output/etap_47_111_7_trades_features.csv"


def main():
    df = pd.read_csv(CSV)
    df["ts"] = pd.to_datetime(df["signal_time"], utc=True)
    base_wr = (df["outcome"] == "win").sum() / len(df) * 100
    base_R = df["R"].sum()
    print(f"[INFO] baseline n={len(df)} WR={base_wr:.1f}% total={base_R:+.1f}R\n")

    # Compute extra hull labels which we'll use as direction-specific filters.
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    h_1h_140 = hull_ma(df_1h["close"], 140)
    h_1h_160 = hull_ma(df_1h["close"], 160)
    h_12h_180 = hull_ma(df_12h["close"], 180)

    def hull_label(close, hull):
        h2 = hull.shift(2)
        return pd.Series(np.where(close > h2, "up", np.where(close < h2, "down", "na")),
                          index=close.index)

    lbl_1h_140 = hull_label(df_1h["close"], h_1h_140)
    lbl_1h_160 = hull_label(df_1h["close"], h_1h_160)
    lbl_12h_180 = hull_label(df_12h["close"], h_12h_180)

    def safe_lookup(labels, ts):
        idx = labels.index.searchsorted(ts, side="right") - 1
        if idx < 1:
            return "na"
        v = labels.iloc[idx - 1]
        return v if pd.notna(v) else "na"

    df["hull_1h_L140"] = df["ts"].apply(lambda t: safe_lookup(lbl_1h_140, t))
    df["hull_1h_L160"] = df["ts"].apply(lambda t: safe_lookup(lbl_1h_160, t))
    df["hull_12h_L180"] = df["ts"].apply(lambda t: safe_lookup(lbl_12h_180, t))

    # Direction-specific filters.
    df["long_hull"] = (df["direction"] == "LONG") & (df["hull_1h_L160"] == "up")
    df["short_hull"] = (df["direction"] == "SHORT") & (df["hull_12h_L180"] == "down")
    df["dir_hull_pass"] = df["long_hull"] | df["short_hull"]

    # Time filter: not_Sunday & not_London.
    df["time_pass"] = (df["weekday"] != "Sunday") & (df["session"] != "London")

    # ASVK 4h exclude red, prefer yellow_OS or green.
    df["asvk_pass"] = ~df["asvk_4h"].isin(["red"])

    # MH 4h color exclude green/grey_from_green (negative for both dirs).
    df["mh_pass"] = ~df["mh_4h_color"].isin(["green", "grey_from_green"])

    # Test individual + combos
    filters = [
        ("dir_hull_pass (1.1.7 direction-specific hull)", df["dir_hull_pass"]),
        ("time_pass (not Sunday, not London)", df["time_pass"]),
        ("asvk_pass (not asvk_4h=red)", df["asvk_pass"]),
        ("mh_pass (not mh_4h green*)", df["mh_pass"]),
        ("time + asvk", df["time_pass"] & df["asvk_pass"]),
        ("time + mh", df["time_pass"] & df["mh_pass"]),
        ("asvk + mh", df["asvk_pass"] & df["mh_pass"]),
        ("time + asvk + mh", df["time_pass"] & df["asvk_pass"] & df["mh_pass"]),
        ("dir_hull + time", df["dir_hull_pass"] & df["time_pass"]),
        ("dir_hull + asvk", df["dir_hull_pass"] & df["asvk_pass"]),
        ("dir_hull + mh", df["dir_hull_pass"] & df["mh_pass"]),
        ("dir_hull + time + asvk", df["dir_hull_pass"] & df["time_pass"] & df["asvk_pass"]),
        ("dir_hull + time + mh", df["dir_hull_pass"] & df["time_pass"] & df["mh_pass"]),
        ("ALL 4 filters", df["dir_hull_pass"] & df["time_pass"] & df["asvk_pass"] & df["mh_pass"]),
        ("time + asvk + mh (no hull)", df["time_pass"] & df["asvk_pass"] & df["mh_pass"]),
    ]

    print(f"{'filter':<55} {'n':<5} {'WR':<7} {'d_pp':<8} {'total':<8} {'avg':<8}")
    for name, mask in filters:
        sub = df[mask]
        n = len(sub)
        if n == 0:
            continue
        wr = (sub["outcome"] == "win").sum() / n * 100
        total = sub["R"].sum()
        d = wr - base_wr
        avg = total / n
        flag = " ***" if d >= 5 else (" !" if d <= -5 else "")
        print(f"{name:<55} {n:<5} {wr:<7.1f} {d:+7.1f} {total:+7.1f} {avg:+7.3f}{flag}")

    # Save filtered CSV для best filter.
    print("\n=== Year-by-year breakdown ===")
    best_filter = (df["dir_hull_pass"] & df["time_pass"]
                   & df["asvk_pass"] & df["mh_pass"])
    best = df[best_filter].copy()
    best["year"] = best["ts"].dt.year
    for y in sorted(best["year"].unique()):
        sub = best[best["year"] == y]
        n = len(sub)
        wr = (sub["outcome"] == "win").sum() / n * 100 if n else 0
        total = sub["R"].sum()
        print(f"  {y}: n={n:<3} WR={wr:5.1f}% total={total:+5.1f}R")
    print(f"\n  TOTAL: n={len(best)} WR={(best['outcome']=='win').sum()/len(best)*100:.1f}% "
          f"total={best['R'].sum():+.1f}R")

    # Per direction within best filter
    for direction in ["LONG", "SHORT"]:
        sub = best[best["direction"] == direction]
        n = len(sub)
        wr = (sub["outcome"] == "win").sum() / n * 100 if n else 0
        total = sub["R"].sum()
        print(f"  {direction}: n={n:<3} WR={wr:5.1f}% total={total:+5.1f}R")


if __name__ == "__main__":
    main()
