"""Этап 12: [OB-4h small] + [first FVG-1h] для большей частоты.

База: dedup (одна FVG на одну OB-4h)
SL: max(FVG buffer ATR, min_sl_pct % от entry)
RR sweep: 1.0, 1.5, 2.0
min_sl_pct: 0.0, 0.5, 1.0
+/- pro-trend filter

Также сравним 12h как промежуточный вариант.
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
SL_BUF_ATR = 0.3
RR_LIST = [1.0, 1.5, 2.0]
MIN_SL_PCT_LIST = [0.0, 0.5, 1.0]

# OB life — сколько дней зона "активна" для поиска FVG-1h внутри
OB_LIFE_DAYS = {"4h": 5, "12h": 10, "1d": 30}

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


def get_setups(df_htf, df_1h, htf_label, dedup_first=True):
    df_htf = df_htf.copy()
    df_htf["atr14"] = compute_atr(df_htf, 14)
    df_1h_local = df_1h.copy()
    if "atr14" not in df_1h_local.columns:
        df_1h_local["atr14"] = compute_atr(df_1h_local, 14)
    if "ema200" not in df_1h_local.columns:
        df_1h_local["ema200"] = df_1h_local["close"].ewm(span=200, adjust=False).mean()

    obs = []
    for idx in range(1, len(df_htf) - 1):
        ob = detect_ob_pair(df_htf, idx)
        if ob is None:
            continue
        atr = float(df_htf["atr14"].iloc[idx])
        if pd.isna(atr) or atr <= 0:
            continue
        size_atr = (ob.top - ob.bottom) / atr
        if size_atr >= SIZE_THRESHOLD_OB:
            continue
        obs.append({"ob_time": ob.cur_time, "direction": ob.direction,
                     "ob_bottom": ob.bottom, "ob_top": ob.top, "ob_atr": atr})

    life_days = OB_LIFE_DAYS[htf_label]
    htf_td = pd.Timedelta(htf_label)
    setups = []
    for ob in obs:
        ob_start = ob["ob_time"] + htf_td
        ob_end = ob["ob_time"] + pd.Timedelta(days=life_days)
        df_w = df_1h_local[(df_1h_local.index >= ob_start) & (df_1h_local.index <= ob_end)]
        if df_w.empty:
            continue
        for j_local in range(2, len(df_w)):
            ts = df_w.index[j_local]
            j = df_1h_local.index.get_loc(ts)
            f = detect_fvg(df_1h_local, j)
            if f is None or f.direction != ob["direction"]:
                continue
            if f.top < ob["ob_bottom"] or f.bottom > ob["ob_top"]:
                continue
            atr_1h = float(df_1h_local["atr14"].iloc[j])
            if pd.isna(atr_1h) or atr_1h <= 0:
                continue
            entry = (f.bottom + f.top) / 2
            em_1h = float(df_1h_local["ema200"].iloc[j])
            cur_close_1h = float(df_1h_local["close"].iloc[j])
            fvg_pro = ((f.direction == "LONG" and cur_close_1h > em_1h)
                        or (f.direction == "SHORT" and cur_close_1h < em_1h))
            setups.append({
                "ob_time": ob["ob_time"], "direction": f.direction,
                "ob_bottom": ob["ob_bottom"], "ob_top": ob["ob_top"],
                "fvg_time": f.c2_time,
                "fvg_bottom": f.bottom, "fvg_top": f.top,
                "atr_1h": atr_1h, "entry": entry,
                "fvg_pro": fvg_pro,
            })
            if dedup_first:
                break
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
        results.append({**s, "rr": rr, "min_sl_pct": min_sl_pct,
                          "sl": sl, "tp": tp, "risk_pct": risk/entry*100,
                          "outcome": outcome, "R": R})
    return results


def report(rows, label):
    df = pd.DataFrame(rows)
    closed = df[df["outcome"].isin(["win", "loss"])]
    if len(closed) == 0:
        return None
    n = len(df); nc = len(closed)
    w = (closed["outcome"] == "win").sum()
    return {
        "segment": label, "n_total": n, "n_closed": nc,
        "WR%": round(w/nc*100, 1),
        "total_R": round(closed["R"].sum(), 1),
        "R/trade": round(closed["R"].mean(), 3),
        "median_risk_pct": round(closed["risk_pct"].median(), 2),
    }


def main():
    print("[INFO] loading")
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_12h = load_df(SYMBOL, "12h")
    df_1h = load_df(SYMBOL, "1h")
    df_1m = load_df(SYMBOL, "1m")
    start = pd.Timestamp(START_DATE, tz="UTC")
    df_1d = df_1d[df_1d.index >= start]
    df_4h = df_4h[df_4h.index >= start]
    df_12h = df_12h[df_12h.index >= start]
    df_1h = df_1h[df_1h.index >= start].copy()
    df_1h["atr14"] = compute_atr(df_1h, 14)
    df_1h["ema200"] = df_1h["close"].ewm(span=200, adjust=False).mean()
    df_1m = df_1m[df_1m.index >= start]

    years = (df_1d.index[-1] - df_1d.index[0]).days / 365

    all_rows = []
    for htf_label, df_htf in [("4h", df_4h), ("12h", df_12h), ("1d", df_1d)]:
        print(f"\n[{htf_label}] generating setups (dedup first)")
        setups = get_setups(df_htf, df_1h, htf_label, dedup_first=True)
        n_pro = sum(1 for s in setups if s["fvg_pro"])
        print(f"  {len(setups)} setups (pro={n_pro})")

        for rr in RR_LIST:
            for mpct in MIN_SL_PCT_LIST:
                # all
                res = evaluate(setups, df_1m, rr, mpct)
                r = report(res, f"{htf_label} all | RR={rr} | min_sl%={mpct}")
                if r:
                    r["RR"] = rr; r["min_sl%"] = mpct
                    r["htf"] = htf_label; r["filter"] = "all"
                    r["n_per_week"] = round(r["n_total"] / years / 52, 2)
                    all_rows.append(r)
                # pro only
                setups_pro = [s for s in setups if s["fvg_pro"]]
                if setups_pro:
                    res_pro = evaluate(setups_pro, df_1m, rr, mpct)
                    r = report(res_pro, f"{htf_label} pro | RR={rr} | min_sl%={mpct}")
                    if r:
                        r["RR"] = rr; r["min_sl%"] = mpct
                        r["htf"] = htf_label; r["filter"] = "pro"
                        r["n_per_week"] = round(r["n_total"] / years / 52, 2)
                        all_rows.append(r)

    summary = pd.DataFrame(all_rows)
    cols = ["htf", "filter", "RR", "min_sl%", "n_total", "n_per_week",
              "n_closed", "WR%", "total_R", "R/trade", "median_risk_pct"]
    summary = summary[cols]
    summary.to_csv(OUT_DIR / "ob_htf_grid.csv", index=False)

    print("\n=== ВСЯ СВОДКА ===")
    print(summary.to_string(index=False))

    print("\n=== ПРОШЛИ WR>=55, n_per_week>=1 (фьючерс-friendly: min_sl%>=0.5) ===")
    pf = summary[(summary["WR%"] >= 55) & (summary["n_per_week"] >= 1) & (summary["min_sl%"] >= 0.5)]
    print(pf.sort_values("R/trade", ascending=False).to_string(index=False))

    print("\n=== ПРОШЛИ WR>=55, n_per_week>=0.5 (min_sl%>=0.5) ===")
    pf2 = summary[(summary["WR%"] >= 55) & (summary["n_per_week"] >= 0.5) & (summary["min_sl%"] >= 0.5)]
    print(pf2.sort_values("R/trade", ascending=False).to_string(index=False))

    print("\n=== ТОП-15 по R/trade (футурс: min_sl>=0.5) ===")
    futurs = summary[summary["min_sl%"] >= 0.5]
    print(futurs.sort_values("R/trade", ascending=False).head(15).to_string(index=False))


if __name__ == "__main__":
    main()
