"""Этап 55: проверка отсутствия 2022 года в 1.1.4 STRICT trades.

Из etap_54 audit: 2022 missing in closed trades. Проверяю:
  1. Есть ли FVG-1d / 12h в 2022?
  2. Есть ли OB-4h / 6h в 2022?
  3. Есть ли overlap'ы вообще в 2022?
  4. Сколько RAW chains до dedup в 2022?
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from collections import defaultdict
import pandas as pd
import numpy as np

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg


def compute_atr(df, period=14):
    high = df["high"]; low = df["low"]; pc = df["close"].shift(1)
    tr = pd.concat([(high-low),(high-pc).abs(),(low-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def collect_obs(df, atr, tf):
    out = []
    for idx in range(2, len(df) - 1):
        ob = detect_ob_pair(df, idx)
        if ob is None: continue
        a = float(atr.iloc[idx])
        if pd.isna(a) or a <= 0: continue
        out.append({"tf": tf, "direction": ob.direction,
                     "bottom": ob.bottom, "top": ob.top,
                     "time": ob.cur_time})
    return out


def collect_fvgs(df, atr, tf):
    out = []
    for idx in range(2, len(df) - 1):
        f = detect_fvg(df, idx)
        if f is None: continue
        a = float(atr.iloc[idx])
        if pd.isna(a) or a <= 0: continue
        out.append({"tf": tf, "direction": f.direction,
                     "bottom": f.bottom, "top": f.top,
                     "time": f.c2_time})
    return out


def main():
    print("[INFO] load")
    df_1d = load_df("BTCUSDT", "1d")
    df_4h = load_df("BTCUSDT", "4h")
    df_1h = load_df("BTCUSDT", "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df("BTCUSDT", "15m")

    cutoff = pd.Timestamp("2020-01-01", tz="UTC")
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_4h = df_4h[df_4h.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_6h = df_6h[df_6h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()

    for tf, df in [("1d", df_1d), ("12h", df_12h), ("6h", df_6h),
                    ("4h", df_4h), ("2h", df_2h), ("1h", df_1h),
                    ("15m", df_15m)]:
        df["atr14"] = compute_atr(df, 14)

    # 1. Yearly breakdown of bars
    print("\n=== Bars per year per TF ===")
    for tf, df in [("1d", df_1d), ("12h", df_12h), ("6h", df_6h),
                    ("4h", df_4h), ("1h", df_1h), ("15m", df_15m)]:
        by_year = df.groupby(df.index.year).size()
        print(f"  {tf:4}: " + ", ".join(f"{y}:{n}" for y, n in by_year.items()))

    # 2. Yearly breakdown of detected zones
    print("\n=== Detected zones per year ===")
    fvgs_1d = collect_fvgs(df_1d, df_1d["atr14"], "1d")
    fvgs_12h = collect_fvgs(df_12h, df_12h["atr14"], "12h")
    obs_4h = collect_obs(df_4h, df_4h["atr14"], "4h")
    obs_6h = collect_obs(df_6h, df_6h["atr14"], "6h")
    obs_1h = collect_obs(df_1h, df_1h["atr14"], "1h")
    obs_2h = collect_obs(df_2h, df_2h["atr14"], "2h")
    fvgs_15m = collect_fvgs(df_15m, df_15m["atr14"], "15m")

    for label, zones in [("FVG-1d", fvgs_1d), ("FVG-12h", fvgs_12h),
                          ("OB-6h", obs_6h), ("OB-4h", obs_4h),
                          ("OB-2h", obs_2h), ("OB-1h", obs_1h),
                          ("FVG-15m", fvgs_15m)]:
        years = pd.Series([z["time"].year for z in zones]).value_counts().sort_index()
        print(f"  {label:8}: " + ", ".join(f"{y}:{n}" for y, n in years.items()))

    # 3. FVG-1d direction split в 2022
    print("\n=== FVG-1d direction в 2022 ===")
    fvg_1d_2022 = [z for z in fvgs_1d if z["time"].year == 2022]
    print(f"  FVG-1d in 2022: {len(fvg_1d_2022)}")
    by_dir = pd.Series([z["direction"] for z in fvg_1d_2022]).value_counts()
    print(f"    by direction: {by_dir.to_dict()}")

    # 4. Раскладка FVG-1d по месяцам 2022
    print("\n=== FVG-1d distribution в 2022 by month ===")
    months = defaultdict(list)
    for z in fvg_1d_2022:
        months[z["time"].month].append(z)
    for m in sorted(months.keys()):
        by_dir = pd.Series([z["direction"] for z in months[m]]).value_counts()
        print(f"    Month {m}: {len(months[m])} FVGs, {by_dir.to_dict()}")

    # 5. Простая проверка - возможен ли первый chain step в 2022?
    print("\n=== Test: первая FVG-1d 2022 + поиск OB-4h в окне 14 дней ===")
    if fvg_1d_2022:
        for fvg in fvg_1d_2022[:5]:
            t = fvg["time"]
            t_end = t + pd.Timedelta(days=14)
            # OB-4h same direction overlap with FVG-1d in window
            candidates = [ob for ob in obs_4h
                           if (ob["time"] >= t + pd.Timedelta(hours=24))
                           and (ob["time"] <= t_end)
                           and (ob["direction"] == fvg["direction"])
                           and not (ob["top"] < fvg["bottom"] or ob["bottom"] > fvg["top"])]
            print(f"  FVG-{fvg['direction']} {t.strftime('%m-%d %H:%M')} "
                  f"[{fvg['bottom']:.0f}, {fvg['top']:.0f}]  "
                  f"-> {len(candidates)} OB-4h candidates")


if __name__ == "__main__":
    main()
