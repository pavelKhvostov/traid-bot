"""Этап 11: фьючерсный SL с минимумом 0.5% или 1.0%.

База: [OB-1d small] + [first FVG-1h в зоне OB] (дедуп)
SL: max(zone_buffer_atr, min_sl_pct % от entry) — никогда не уже min_sl_pct
RR: sweep 1.0, 1.5, 2.0
min_sl_pct: 0.5%, 1.0%, ATR-only

Plus фильтры: FVG pro-trend (1h ema200), Wednesday/US-session, freshness.
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
SIZE_THRESHOLD_OB = 0.3
HTF_LIFE_DAYS = 30
RR_LIST = [1.0, 1.5, 2.0]
MIN_SL_PCT_LIST = [0.0, 0.5, 1.0]  # 0.0 = ATR-only (текущий)
SL_BUF_ATR = 0.3

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


def get_setups(df_1d, df_1h, df_1m, dedup_first=True):
    """Detect all [OB-1d small] + [FVG-1h в зоне OB]."""
    df_1d = df_1d.copy()
    df_1d["atr14"] = compute_atr(df_1d, 14)
    df_1h = df_1h.copy()
    df_1h["atr14"] = compute_atr(df_1h, 14)
    df_1h["ema200"] = df_1h["close"].ewm(span=200, adjust=False).mean()

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
        obs.append({"ob_time": ob.cur_time, "direction": ob.direction,
                     "ob_bottom": ob.bottom, "ob_top": ob.top, "ob_atr": atr})

    setups = []
    for ob in obs:
        ob_start = ob["ob_time"] + pd.Timedelta(days=1)
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
                "ob_bottom": ob["ob_bottom"], "ob_top": ob["ob_top"],
                "ob_atr": ob["ob_atr"],
                "fvg_time": f.c2_time,
                "fvg_bottom": f.bottom, "fvg_top": f.top,
                "atr_1h": atr_1h, "entry": entry,
                "fvg_pro": fvg_pro,
                "hour_utc": ts.hour, "weekday": ts.day_name(),
            })
            if dedup_first:
                break  # только первая FVG в этой OB
    return setups


def evaluate(setups, df_1m, rr, min_sl_pct):
    """Симулировать setups с заданным RR и min_sl_pct."""
    results = []
    for s in setups:
        direction = s["direction"]
        entry = s["entry"]
        atr = s["atr_1h"]
        # ATR-based SL
        if direction == "LONG":
            atr_sl = s["fvg_bottom"] - SL_BUF_ATR * atr
        else:
            atr_sl = s["fvg_top"] + SL_BUF_ATR * atr
        # Min SL distance
        if min_sl_pct > 0:
            min_dist = entry * min_sl_pct / 100.0
            if direction == "LONG":
                pct_sl = entry - min_dist
                sl = min(atr_sl, pct_sl)  # дальше от entry = меньшее значение для LONG
            else:
                pct_sl = entry + min_dist
                sl = max(atr_sl, pct_sl)  # дальше от entry = большее значение для SHORT
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
        risk_pct = risk / entry * 100
        results.append({**s, "rr": rr, "min_sl_pct_setting": min_sl_pct,
                          "sl": sl, "tp": tp, "risk_pct": risk_pct,
                          "outcome": outcome, "R": R})
    return results


def report(rows, label):
    df = pd.DataFrame(rows)
    closed = df[df["outcome"].isin(["win", "loss"])]
    if len(closed) == 0:
        return None
    n = len(df); nc = len(closed)
    w = (closed["outcome"] == "win").sum()
    wr = w / nc * 100
    total_R = closed["R"].sum()
    rt = closed["R"].mean()
    return {"segment": label, "n_total": n, "n_closed": nc,
              "WR%": round(wr, 1), "total_R": round(total_R, 1),
              "R/trade": round(rt, 3),
              "median_risk_pct": round(closed["risk_pct"].median(), 2)}


def main():
    print("[INFO] loading + computing setups (dedup=True, first-FVG-per-OB)")
    df_1d = load_df(SYMBOL, "1d")
    df_1h = load_df(SYMBOL, "1h")
    df_1m = load_df(SYMBOL, "1m")
    start = pd.Timestamp(START_DATE, tz="UTC")
    df_1d = df_1d[df_1d.index >= start]
    df_1h = df_1h[df_1h.index >= start]
    df_1m = df_1m[df_1m.index >= start]

    setups = get_setups(df_1d, df_1h, df_1m, dedup_first=True)
    print(f"  unique setups (dedup): {len(setups)}")
    n_pro = sum(1 for s in setups if s["fvg_pro"])
    n_counter = len(setups) - n_pro
    print(f"  pro-trend: {n_pro}, counter-trend: {n_counter}")

    # === GRID: RR x min_sl_pct ===
    print("\n=== GRID: RR x min_sl_pct (на ВСЕХ dedup setups) ===")
    rows = []
    for rr in RR_LIST:
        for min_pct in MIN_SL_PCT_LIST:
            res = evaluate(setups, df_1m, rr, min_pct)
            r = report(res, f"all | RR={rr} | min_sl%={min_pct}")
            if r:
                r["RR"] = rr; r["min_sl%"] = min_pct
                rows.append(r)
    df_grid = pd.DataFrame(rows)
    print(df_grid.to_string(index=False))

    # === Фильтр FVG pro-trend ===
    print("\n=== ТОЛЬКО FVG pro-trend (1h EMA200) ===")
    setups_pro = [s for s in setups if s["fvg_pro"]]
    rows_pro = []
    for rr in RR_LIST:
        for min_pct in MIN_SL_PCT_LIST:
            res = evaluate(setups_pro, df_1m, rr, min_pct)
            r = report(res, f"pro | RR={rr} | min_sl%={min_pct}")
            if r:
                r["RR"] = rr; r["min_sl%"] = min_pct
                rows_pro.append(r)
    df_pro = pd.DataFrame(rows_pro)
    print(df_pro.to_string(index=False))

    # === COMBINE: best of grid ===
    print("\n=== ТОП-10 ВСЕГО (из всех вариантов) ===")
    all_rows = pd.concat([df_grid, df_pro]).reset_index(drop=True)
    all_rows.to_csv(OUT_DIR / "min_sl_grid.csv", index=False)
    top = all_rows.sort_values("R/trade", ascending=False).head(10)
    print(top.to_string(index=False))

    print("\n=== ПРОШЛИ (WR>=55, n_closed>=30) ===")
    pf = all_rows[(all_rows["WR%"] >= 55) & (all_rows["n_closed"] >= 30)]
    print(pf.sort_values("R/trade", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
