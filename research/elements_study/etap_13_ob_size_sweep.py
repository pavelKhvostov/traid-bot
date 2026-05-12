"""Этап 13: проверка size_vs_ATR фильтра OB-4h на реальном backtest.

Та же база ([OB-4h] + [first FVG-1h pro] + min_sl=1% + RR=1.5),
но sweep по разным size фильтрам OB:
  - all (без фильтра)
  - small (<0.3·ATR)
  - medium (0.3-1.0)
  - large (>1.0)

Дополнительно: проверка с pro/all фильтром и RR ∈ {1.0, 1.5, 2.0}.
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
SL_BUF_ATR = 0.3
RR_LIST = [1.0, 1.5, 2.0]
MIN_SL_PCT = 1.0
HTF_LIFE_DAYS = 5
HTF = "4h"

OUT_DIR = Path("research/elements_study/output")


def compute_atr(df, period=14):
    high = df["high"]; low = df["low"]; pc = df["close"].shift(1)
    tr = pd.concat([(high-low),(high-pc).abs(),(low-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def simulate(direction, entry, sl, tp, df_1m, start_time, timeout_days=14):
    sim = df_1m[df_1m.index >= start_time]
    if sim.empty:
        return ("no_data", 0.0)
    end_time = start_time + pd.Timedelta(days=timeout_days)
    sim = sim[sim.index <= end_time]
    if sim.empty:
        return ("no_data", 0.0)
    activation = None
    for ts, row in sim.iterrows():
        h, l = float(row["high"]), float(row["low"])
        if direction == "LONG" and l <= entry:
            activation = ts; break
        if direction == "SHORT" and h >= entry:
            activation = ts; break
    if activation is None:
        return ("not_filled", 0.0)
    risk = abs(entry - sl)
    if risk <= 0:
        return ("invalid", 0.0)
    sim2 = sim[sim.index >= activation]
    for ts, row in sim2.iterrows():
        h, l = float(row["high"]), float(row["low"])
        if direction == "LONG":
            if l <= sl: return ("loss", -1.0)
            if h >= tp: return ("win", (tp-entry)/risk)
        else:
            if h >= sl: return ("loss", -1.0)
            if l <= tp: return ("win", (entry-tp)/risk)
    return ("open", 0.0)


def get_setups(df_4h, df_1h, size_filter_fn=None):
    df_4h = df_4h.copy()
    df_4h["atr14"] = compute_atr(df_4h, 14)

    obs = []
    for idx in range(1, len(df_4h) - 1):
        ob = detect_ob_pair(df_4h, idx)
        if ob is None:
            continue
        atr = float(df_4h["atr14"].iloc[idx])
        if pd.isna(atr) or atr <= 0:
            continue
        size_atr = (ob.top - ob.bottom) / atr
        if size_filter_fn and not size_filter_fn(size_atr):
            continue
        obs.append({"ob_time": ob.cur_time, "direction": ob.direction,
                     "ob_bottom": ob.bottom, "ob_top": ob.top,
                     "ob_atr": atr, "ob_size_atr": size_atr})

    setups = []
    for ob in obs:
        ob_start = ob["ob_time"] + pd.Timedelta(hours=4)
        ob_end = ob["ob_time"] + pd.Timedelta(days=HTF_LIFE_DAYS)
        df_w = df_1h[(df_1h.index >= ob_start) & (df_1h.index <= ob_end)]
        if df_w.empty:
            continue
        for j_local in range(2, len(df_w)):
            ts = df_w.index[j_local]
            j = df_1h.index.get_loc(ts)
            f = detect_fvg(df_1h, j)
            if f is None or f.direction != ob["direction"]:
                continue
            if f.top < ob["ob_bottom"] or f.bottom > ob["ob_top"]:
                continue
            atr_1h = float(df_1h["atr14"].iloc[j])
            if pd.isna(atr_1h) or atr_1h <= 0:
                continue
            entry = (f.bottom + f.top) / 2
            em_1h = float(df_1h["ema200"].iloc[j])
            cur_close_1h = float(df_1h["close"].iloc[j])
            fvg_pro = ((f.direction == "LONG" and cur_close_1h > em_1h)
                        or (f.direction == "SHORT" and cur_close_1h < em_1h))
            setups.append({
                "ob_time": ob["ob_time"], "direction": f.direction,
                "ob_size_atr": ob["ob_size_atr"],
                "fvg_time": f.c2_time,
                "fvg_bottom": f.bottom, "fvg_top": f.top,
                "atr_1h": atr_1h, "entry": entry,
                "fvg_pro": fvg_pro,
            })
            break  # dedup first
    return setups


def evaluate(setups, df_1m, rr, min_sl_pct):
    results = []
    for s in setups:
        direction = s["direction"]
        entry = s["entry"]
        atr = s["atr_1h"]
        if direction == "LONG":
            atr_sl = s["fvg_bottom"] - SL_BUF_ATR * atr
        else:
            atr_sl = s["fvg_top"] + SL_BUF_ATR * atr
        if min_sl_pct > 0:
            min_dist = entry * min_sl_pct / 100
            if direction == "LONG":
                pct_sl = entry - min_dist
                sl = min(atr_sl, pct_sl)
            else:
                pct_sl = entry + min_dist
                sl = max(atr_sl, pct_sl)
        else:
            sl = atr_sl
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        if direction == "LONG":
            tp = entry + rr * risk
        else:
            tp = entry - rr * risk
        start = pd.Timestamp(s["fvg_time"]) + pd.Timedelta(hours=1)
        outcome, R = simulate(direction, entry, sl, tp, df_1m, start, timeout_days=14)
        results.append({**s, "outcome": outcome, "R": R})
    return results


def report(rows, label, years):
    df = pd.DataFrame(rows)
    closed = df[df["outcome"].isin(["win", "loss"])]
    if len(closed) == 0:
        return None
    n = len(df); nc = len(closed)
    w = (closed["outcome"] == "win").sum()
    return {
        "segment": label, "n_total": n, "n_per_week": round(n/years/52, 2),
        "n_closed": nc, "WR%": round(w/nc*100, 1),
        "total_R": round(closed["R"].sum(), 1),
        "R/trade": round(closed["R"].mean(), 3),
    }


def main():
    print("[INFO] loading")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_1m = load_df(SYMBOL, "1m")
    start = pd.Timestamp(START_DATE, tz="UTC")
    df_4h = df_4h[df_4h.index >= start]
    df_1h = df_1h[df_1h.index >= start].copy()
    df_1h["atr14"] = compute_atr(df_1h, 14)
    df_1h["ema200"] = df_1h["close"].ewm(span=200, adjust=False).mean()
    df_1m = df_1m[df_1m.index >= start]
    years = (df_4h.index[-1] - df_4h.index[0]).days / 365

    size_filters = [
        ("ALL (no filter)", None),
        ("small <0.3", lambda s: s < 0.3),
        ("medium 0.3-1.0", lambda s: 0.3 <= s < 1.0),
        ("large >=1.0", lambda s: s >= 1.0),
    ]
    rows = []
    for size_label, size_fn in size_filters:
        setups = get_setups(df_4h, df_1h, size_filter_fn=size_fn)
        n_pro = sum(1 for s in setups if s["fvg_pro"])
        print(f"\n--- size={size_label}: total={len(setups)}, pro={n_pro} ---")
        for rr in RR_LIST:
            # all
            r = report(evaluate(setups, df_1m, rr, MIN_SL_PCT),
                        f"{size_label} | all | RR={rr}", years)
            if r:
                r["size_filter"] = size_label; r["fvg_filter"] = "all"; r["RR"] = rr
                rows.append(r)
            # pro
            setups_pro = [s for s in setups if s["fvg_pro"]]
            if setups_pro:
                r = report(evaluate(setups_pro, df_1m, rr, MIN_SL_PCT),
                            f"{size_label} | pro | RR={rr}", years)
                if r:
                    r["size_filter"] = size_label; r["fvg_filter"] = "pro"; r["RR"] = rr
                    rows.append(r)
    summary = pd.DataFrame(rows)
    cols = ["size_filter", "fvg_filter", "RR", "n_total", "n_per_week",
              "n_closed", "WR%", "total_R", "R/trade"]
    summary = summary[cols]
    summary.to_csv(OUT_DIR / "ob_size_sweep.csv", index=False)
    print("\n=== ВСЯ СВОДКА (min_sl=1%, dedup first) ===")
    print(summary.to_string(index=False))

    print("\n=== ПРОШЛИ WR>=55, n/wk>=0.5 ===")
    pf = summary[(summary["WR%"] >= 55) & (summary["n_per_week"] >= 0.5)]
    print(pf.sort_values("R/trade", ascending=False).to_string(index=False))

    print("\n=== ПРОШЛИ WR>=55, n/wk>=1 ===")
    pf2 = summary[(summary["WR%"] >= 55) & (summary["n_per_week"] >= 1)]
    print(pf2.sort_values("R/trade", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
