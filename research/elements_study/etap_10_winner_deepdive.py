"""Этап 10: deep-dive в winner — [OB-1d small] + [FVG-1h] RR=1.0.

Цели:
  1. Per-setup details (entry/SL/TP, outcome, контекст)
  2. Стабильность edge по годам
  3. Что отличает 60% wins от 40% losses (additional filters)
  4. Проверка multi-counting (одна OB-1d могла породить много setups)
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from pathlib import Path
import numpy as np
import pandas as pd

from data_manager import load_df
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
RR = 1.0
SIZE_THRESHOLD_OB = 0.3
HTF_LIFE_DAYS = 30

OUT_DIR = Path("research/elements_study/output")


def compute_atr(df, period=14):
    high = df["high"]; low = df["low"]; pc = df["close"].shift(1)
    tr = pd.concat([(high-low),(high-pc).abs(),(low-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def simulate(direction, entry, sl, tp, df_1m, start_time, timeout_days=14):
    sim = df_1m[df_1m.index >= start_time]
    if sim.empty:
        return ("no_data", 0.0, None, None)
    end_time = start_time + pd.Timedelta(days=timeout_days)
    sim = sim[sim.index <= end_time]
    if sim.empty:
        return ("no_data", 0.0, None, None)
    activation = None
    for ts, row in sim.iterrows():
        h, l = float(row["high"]), float(row["low"])
        if direction == "LONG" and l <= entry:
            activation = ts; break
        if direction == "SHORT" and h >= entry:
            activation = ts; break
    if activation is None:
        return ("not_filled", 0.0, None, None)
    risk = abs(entry - sl)
    if risk <= 0:
        return ("invalid", 0.0, activation, None)
    sim2 = sim[sim.index >= activation]
    for ts, row in sim2.iterrows():
        h, l = float(row["high"]), float(row["low"])
        if direction == "LONG":
            if l <= sl: return ("loss", -1.0, activation, ts)
            if h >= tp:
                return ("win", (tp-entry)/risk, activation, ts)
        else:
            if h >= sl: return ("loss", -1.0, activation, ts)
            if l <= tp:
                return ("win", (entry-tp)/risk, activation, ts)
    return ("open", 0.0, activation, None)


def main():
    print("[INFO] loading")
    df_1d = load_df(SYMBOL, "1d")
    df_1h = load_df(SYMBOL, "1h")
    df_1m = load_df(SYMBOL, "1m")
    start = pd.Timestamp(START_DATE, tz="UTC")
    df_1d = df_1d[df_1d.index >= start].copy()
    df_1h = df_1h[df_1h.index >= start].copy()
    df_1m = df_1m[df_1m.index >= start]

    df_1d["atr14"] = compute_atr(df_1d, 14)
    df_1d["ema200"] = df_1d["close"].ewm(span=200, adjust=False).mean()
    df_1h["atr14"] = compute_atr(df_1h, 14)
    df_1h["ema200"] = df_1h["close"].ewm(span=200, adjust=False).mean()

    # Найти все small OB-1d
    print("[INFO] detecting small OB-1d zones")
    obs = []
    for idx in range(1, len(df_1d) - 1):
        ob = detect_ob_pair(df_1d, idx)
        if ob is None:
            continue
        atr = float(df_1d["atr14"].iloc[idx])
        if pd.isna(atr) or atr <= 0:
            continue
        size_atr = (ob.top - ob.bottom) / atr
        if size_atr >= SIZE_THRESHOLD_OB:
            continue
        em = float(df_1d["ema200"].iloc[idx])
        cur_close = float(df_1d["close"].iloc[idx])
        ob_pos_vs_ema200 = "above" if (not pd.isna(em) and cur_close > em) else "below" if (not pd.isna(em)) else "na"
        obs.append({
            "ob_time": ob.cur_time,
            "ob_direction": ob.direction,
            "ob_bottom": ob.bottom,
            "ob_top": ob.top,
            "ob_size_atr": size_atr,
            "ob_atr": atr,
            "ob_pos_vs_ema200": ob_pos_vs_ema200,
            "ob_dir_vs_ema": "pro" if (
                (ob.direction == "LONG" and ob_pos_vs_ema200 == "above")
                or (ob.direction == "SHORT" and ob_pos_vs_ema200 == "below")
            ) else "counter" if ob_pos_vs_ema200 != "na" else "na",
        })
    print(f"  small OB-1d: {len(obs)}")

    # Для каждой OB найти все FVG-1h в её зоне
    print("[INFO] matching FVG-1h inside OB-1d zones")
    setups = []
    for ob in obs:
        ob_start = ob["ob_time"] + pd.Timedelta(days=1)
        ob_end = ob["ob_time"] + pd.Timedelta(days=HTF_LIFE_DAYS)
        df_1h_win = df_1h[(df_1h.index >= ob_start) & (df_1h.index <= ob_end)]
        if df_1h_win.empty:
            continue
        for j_local in range(2, len(df_1h_win)):
            ts_1h = df_1h_win.index[j_local]
            j = df_1h.index.get_loc(ts_1h)
            f = detect_fvg(df_1h, j)
            if f is None or f.direction != ob["ob_direction"]:
                continue
            # zone overlap
            if f.top < ob["ob_bottom"] or f.bottom > ob["ob_top"]:
                continue
            atr_1h = float(df_1h["atr14"].iloc[j])
            if pd.isna(atr_1h) or atr_1h <= 0:
                continue
            fvg_size_atr = (f.top - f.bottom) / atr_1h
            entry = (f.bottom + f.top) / 2
            if f.direction == "LONG":
                sl = f.bottom - 0.3 * atr_1h
                tp = entry + RR * (entry - sl)
            else:
                sl = f.top + 0.3 * atr_1h
                tp = entry - RR * (sl - entry)
            start_sim = f.c2_time + pd.Timedelta(hours=1)
            outcome, R, act, exit_ts = simulate(f.direction, entry, sl, tp, df_1m, start_sim,
                                                 timeout_days=14)
            # Контекст
            em_1h = float(df_1h["ema200"].iloc[j])
            cur_close_1h = float(df_1h["close"].iloc[j])
            fvg_pos_vs_ema = "above" if cur_close_1h > em_1h else "below"
            fvg_dir_vs_ema = "pro" if (
                (f.direction == "LONG" and fvg_pos_vs_ema == "above")
                or (f.direction == "SHORT" and fvg_pos_vs_ema == "below")
            ) else "counter"
            # Hour of day, day of week
            hour_utc = ts_1h.hour
            weekday = ts_1h.day_name()
            # Distance from OB centre
            ob_mid = (ob["ob_bottom"] + ob["ob_top"]) / 2
            dist_from_ob_mid = abs(entry - ob_mid) / ob["ob_atr"]
            # Bars from OB to FVG
            bars_from_ob = (ts_1h - ob["ob_time"]).total_seconds() / 3600
            setups.append({
                **ob,
                "fvg_time": f.c2_time,
                "fvg_direction": f.direction,
                "fvg_bottom": f.bottom,
                "fvg_top": f.top,
                "fvg_size_atr": fvg_size_atr,
                "fvg_atr": atr_1h,
                "fvg_dir_vs_ema": fvg_dir_vs_ema,
                "hour_utc": hour_utc,
                "weekday": weekday,
                "dist_from_ob_mid_atr": dist_from_ob_mid,
                "bars_from_ob_h": bars_from_ob,
                "entry": entry, "sl": sl, "tp": tp,
                "outcome": outcome, "R": R,
                "activation_time": act, "exit_time": exit_ts,
            })

    df = pd.DataFrame(setups)
    df.to_csv(OUT_DIR / "winner_deepdive.csv", index=False)
    print(f"\n[OK] saved {len(df)} setups")

    closed = df[df["outcome"].isin(["win", "loss"])]
    print(f"\n=== ОБЩАЯ ===")
    print(f"  total={len(df)}, closed={len(closed)}, "
          f"not_filled={(df['outcome']=='not_filled').sum()}, "
          f"open={(df['outcome']=='open').sum()}")
    if len(closed):
        wr = (closed["outcome"] == "win").mean() * 100
        tot = closed["R"].sum()
        rt = closed["R"].mean()
        print(f"  WR={wr:.1f}% TotalR={tot:+.1f} R/tr={rt:+.3f}")

    # === ПО ГОДАМ ===
    print("\n=== ПО ГОДАМ ===")
    closed = closed.copy()
    closed["year"] = pd.to_datetime(closed["fvg_time"]).dt.year
    by_year = closed.groupby("year").agg(
        n=("outcome", "size"),
        wins=("outcome", lambda s: (s=="win").sum()),
        total_R=("R", "sum"),
    )
    by_year["losses"] = by_year["n"] - by_year["wins"]
    by_year["WR%"] = (by_year["wins"] / by_year["n"] * 100).round(1)
    by_year["R/trade"] = (by_year["total_R"] / by_year["n"]).round(3)
    print(by_year.to_string())

    # === ПО НАПРАВЛЕНИЮ ===
    print("\n=== ПО НАПРАВЛЕНИЮ ===")
    by_dir = closed.groupby("ob_direction").agg(
        n=("outcome","size"),
        wins=("outcome", lambda s: (s=="win").sum()),
        total_R=("R","sum"),
    )
    by_dir["losses"] = by_dir["n"] - by_dir["wins"]
    by_dir["WR%"] = (by_dir["wins"] / by_dir["n"] * 100).round(1)
    by_dir["R/trade"] = (by_dir["total_R"] / by_dir["n"]).round(3)
    print(by_dir.to_string())

    # === ПО ema200 для OB ===
    print("\n=== OB direction vs HTF EMA200 ===")
    by_ema = closed.groupby("ob_dir_vs_ema").agg(
        n=("outcome","size"),
        wins=("outcome", lambda s: (s=="win").sum()),
        total_R=("R","sum"),
    )
    by_ema["losses"] = by_ema["n"] - by_ema["wins"]
    by_ema["WR%"] = (by_ema["wins"] / by_ema["n"] * 100).round(1)
    by_ema["R/trade"] = (by_ema["total_R"] / by_ema["n"]).round(3)
    print(by_ema.to_string())

    # === FVG vs ema200 1h ===
    print("\n=== FVG direction vs 1h EMA200 ===")
    by_fvg_ema = closed.groupby("fvg_dir_vs_ema").agg(
        n=("outcome","size"),
        wins=("outcome", lambda s: (s=="win").sum()),
        total_R=("R","sum"),
    )
    by_fvg_ema["losses"] = by_fvg_ema["n"] - by_fvg_ema["wins"]
    by_fvg_ema["WR%"] = (by_fvg_ema["wins"] / by_fvg_ema["n"] * 100).round(1)
    by_fvg_ema["R/trade"] = (by_fvg_ema["total_R"] / by_fvg_ema["n"]).round(3)
    print(by_fvg_ema.to_string())

    # === FVG size buckets ===
    print("\n=== FVG-1h size buckets ===")
    closed["fvg_size_bucket"] = pd.cut(
        closed["fvg_size_atr"],
        bins=[0, 0.3, 0.6, 1.0, 100],
        labels=["small<0.3", "med 0.3-0.6", "0.6-1.0", "large>1.0"],
    )
    by_size = closed.groupby("fvg_size_bucket", observed=True).agg(
        n=("outcome","size"),
        wins=("outcome", lambda s: (s=="win").sum()),
        total_R=("R","sum"),
    )
    by_size["losses"] = by_size["n"] - by_size["wins"]
    by_size["WR%"] = (by_size["wins"] / by_size["n"] * 100).round(1)
    by_size["R/trade"] = (by_size["total_R"] / by_size["n"]).round(3)
    print(by_size.to_string())

    # === Distance from OB mid ===
    print("\n=== distance from OB-mid (in OB ATR units) ===")
    closed["dist_bucket"] = pd.cut(
        closed["dist_from_ob_mid_atr"],
        bins=[-0.001, 0.05, 0.1, 0.2, 100],
        labels=["near_mid<0.05", "0.05-0.10", "0.10-0.20", "far>0.20"],
    )
    by_dist = closed.groupby("dist_bucket", observed=True).agg(
        n=("outcome","size"),
        wins=("outcome", lambda s: (s=="win").sum()),
        total_R=("R","sum"),
    )
    by_dist["losses"] = by_dist["n"] - by_dist["wins"]
    by_dist["WR%"] = (by_dist["wins"] / by_dist["n"] * 100).round(1)
    by_dist["R/trade"] = (by_dist["total_R"] / by_dist["n"]).round(3)
    print(by_dist.to_string())

    # === Bars from OB to FVG (свежесть) ===
    print("\n=== Часы от OB до FVG (свежесть) ===")
    closed["bars_bucket"] = pd.cut(
        closed["bars_from_ob_h"],
        bins=[0, 24, 72, 168, 720],
        labels=["<1d", "1-3d", "3-7d", "7-30d"],
    )
    by_bars = closed.groupby("bars_bucket", observed=True).agg(
        n=("outcome","size"),
        wins=("outcome", lambda s: (s=="win").sum()),
        total_R=("R","sum"),
    )
    by_bars["losses"] = by_bars["n"] - by_bars["wins"]
    by_bars["WR%"] = (by_bars["wins"] / by_bars["n"] * 100).round(1)
    by_bars["R/trade"] = (by_bars["total_R"] / by_bars["n"]).round(3)
    print(by_bars.to_string())

    # === День недели ===
    print("\n=== День недели ===")
    days_order = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
    by_day = closed.groupby("weekday").agg(
        n=("outcome","size"),
        wins=("outcome", lambda s: (s=="win").sum()),
        total_R=("R","sum"),
    ).reindex(days_order).dropna()
    by_day["losses"] = by_day["n"] - by_day["wins"]
    by_day["WR%"] = (by_day["wins"] / by_day["n"] * 100).round(1)
    by_day["R/trade"] = (by_day["total_R"] / by_day["n"]).round(3)
    print(by_day.to_string())

    # === Час UTC ===
    print("\n=== Час UTC (сессия) ===")
    closed["session"] = pd.cut(
        closed["hour_utc"],
        bins=[-0.001, 7, 13, 21, 24],
        labels=["asia 0-7", "europe 7-13", "us 13-21", "late_us 21-24"],
    )
    by_sess = closed.groupby("session", observed=True).agg(
        n=("outcome","size"),
        wins=("outcome", lambda s: (s=="win").sum()),
        total_R=("R","sum"),
    )
    by_sess["losses"] = by_sess["n"] - by_sess["wins"]
    by_sess["WR%"] = (by_sess["wins"] / by_sess["n"] * 100).round(1)
    by_sess["R/trade"] = (by_sess["total_R"] / by_sess["n"]).round(3)
    print(by_sess.to_string())

    # === Multi-counting per OB ===
    print("\n=== Multi-counting: сколько FVG на одной OB ===")
    multi = df.groupby("ob_time").size()
    print(f"  unique OBs that had setups: {len(multi)}")
    print(f"  median setups per OB: {multi.median()}")
    print(f"  max setups per OB: {multi.max()}")
    print(f"  distribution:\n{multi.value_counts().sort_index().head(10).to_string()}")


if __name__ == "__main__":
    main()
