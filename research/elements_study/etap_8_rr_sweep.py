"""Этап 8: RR-sweep по 7 экспериментам.

Считаем для RR ∈ {1.0, 1.25, 1.5, 2.0} какой setup даёт WR>=55% и n/week>=1.

Pre-compute: для каждого активированного setup'а — отслеживаем первое hit
SL и timeline. Затем для разных RR вычисляем WR post-hoc.
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
RR_LIST = [1.0, 1.25, 1.5, 2.0]
TIMEOUT_DAYS_LTF = 14
TIMEOUT_DAYS_HTF = 30

OUT_DIR = Path("research/elements_study/output")


def compute_atr(df, period=14):
    high = df["high"]; low = df["low"]; prev_close = df["close"].shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def detect_rdrb(df, idx):
    if idx < 2:
        return None
    a = df.iloc[idx - 2]; m = df.iloc[idx - 1]; c = df.iloc[idx]
    a_open, a_close, a_high, a_low = float(a["open"]), float(a["close"]), float(a["high"]), float(a["low"])
    m_close = float(m["close"])
    c_open, c_high, c_low, c_close = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
    if m_close > a_high and c_low < a_high and c_close > a_high:
        zb = max(c_low, max(a_open, a_close)); zt = min(a_high, min(c_open, c_close))
        if zt <= zb:
            return None
        return {"direction": "LONG", "bottom": zb, "top": zt, "trigger_low": c_low, "trigger_high": c_high}
    if m_close < a_low and c_high > a_low and c_close < a_low:
        zb = max(a_low, max(c_open, c_close)); zt = min(c_high, min(a_open, a_close))
        if zt <= zb:
            return None
        return {"direction": "SHORT", "bottom": zb, "top": zt, "trigger_low": c_low, "trigger_high": c_high}
    return None


def is_hh(df, i):
    if i < 2 or i + 2 >= len(df):
        return False
    hi = float(df["high"].iloc[i])
    return all(hi > float(df["high"].iloc[k]) for k in (i-2, i-1, i+1, i+2))


def is_ll(df, i):
    if i < 2 or i + 2 >= len(df):
        return False
    lo = float(df["low"].iloc[i])
    return all(lo < float(df["low"].iloc[k]) for k in (i-2, i-1, i+1, i+2))


def find_first_touch(df, start_idx, direction, top, bottom, max_bars=100):
    end = min(start_idx + max_bars, len(df) - 1)
    for j in range(start_idx, end + 1):
        row = df.iloc[j]
        h, l, c = float(row["high"]), float(row["low"]), float(row["close"])
        if direction == "LONG":
            if l <= top:
                if c < bottom: return j, "pierce"
                if bottom <= c <= top: return j, "close_inside"
                return j, "wick"
        else:
            if h >= bottom:
                if c > top: return j, "pierce"
                if bottom <= c <= top: return j, "close_inside"
                return j, "wick"
    return None, None


def sim_with_rr_list(direction, entry, sl, df_1m, start_time, rr_list, timeout_days):
    """Возвращает dict{rr: outcome_dict} — для каждого RR независимый результат."""
    sim = df_1m[df_1m.index >= start_time]
    if sim.empty:
        return {rr: {"outcome": "no_data", "R": 0.0} for rr in rr_list}
    end_time = start_time + pd.Timedelta(days=timeout_days)
    sim = sim[sim.index <= end_time]
    if sim.empty:
        return {rr: {"outcome": "no_data", "R": 0.0} for rr in rr_list}
    activation = None
    for ts, row in sim.iterrows():
        h, l = float(row["high"]), float(row["low"])
        if direction == "LONG" and l <= entry:
            activation = ts; break
        if direction == "SHORT" and h >= entry:
            activation = ts; break
    if activation is None:
        return {rr: {"outcome": "not_filled", "R": 0.0} for rr in rr_list}
    risk = abs(entry - sl)
    if risk <= 0:
        return {rr: {"outcome": "invalid", "R": 0.0} for rr in rr_list}
    sim2 = sim[sim.index >= activation]

    # TP-цены для каждого RR
    tps = {}
    for rr in rr_list:
        if direction == "LONG":
            tps[rr] = entry + rr * risk
        else:
            tps[rr] = entry - rr * risk

    # Симулируем: для каждого RR ищем первый из (TP_rr, SL)
    results = {rr: None for rr in rr_list}
    for ts, row in sim2.iterrows():
        h, l = float(row["high"]), float(row["low"])
        if direction == "LONG":
            sl_hit = l <= sl
            for rr in rr_list:
                if results[rr] is not None:
                    continue
                tp_hit = h >= tps[rr]
                if sl_hit and tp_hit:
                    # На одной свече — оба. Считаем worst-case = SL.
                    results[rr] = {"outcome": "loss", "R": -1.0}
                elif sl_hit:
                    results[rr] = {"outcome": "loss", "R": -1.0}
                elif tp_hit:
                    results[rr] = {"outcome": "win", "R": rr}
        else:
            sl_hit = h >= sl
            for rr in rr_list:
                if results[rr] is not None:
                    continue
                tp_hit = l <= tps[rr]
                if sl_hit and tp_hit:
                    results[rr] = {"outcome": "loss", "R": -1.0}
                elif sl_hit:
                    results[rr] = {"outcome": "loss", "R": -1.0}
                elif tp_hit:
                    results[rr] = {"outcome": "win", "R": rr}
        if all(v is not None for v in results.values()):
            break
    for rr in rr_list:
        if results[rr] is None:
            results[rr] = {"outcome": "open", "R": 0.0}
    return results


def gather_setups_zone_wick(df_main, df_1m, name, detect_fn, size_filter=None,
                              require_pro_trend=False, sl_buf_atr=0.3,
                              timeout_days=TIMEOUT_DAYS_HTF):
    df = df_main.copy()
    df["atr14"] = compute_atr(df, 14)
    if require_pro_trend:
        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    tf_td = pd.Timedelta(df.index[1] - df.index[0])
    setups = []
    for idx in range(2, len(df) - 1):
        z = detect_fn(df, idx)
        if z is None:
            continue
        if isinstance(z, dict):
            zb, zt, dirn = z["bottom"], z["top"], z["direction"]
        else:
            zb, zt, dirn = z.bottom, z.top, z.direction
        atr = float(df["atr14"].iloc[idx])
        if pd.isna(atr) or atr <= 0:
            continue
        size_atr = (zt - zb) / atr
        if size_filter and not size_filter(size_atr):
            continue
        if require_pro_trend:
            em = float(df["ema200"].iloc[idx])
            if pd.isna(em):
                continue
            cur_close = float(df["close"].iloc[idx])
            is_bull = cur_close > em
            if dirn == "LONG" and not is_bull:
                continue
            if dirn == "SHORT" and is_bull:
                continue
        touch_idx, touch_kind = find_first_touch(df, idx + 1, dirn, zt, zb)
        if touch_idx is None or touch_kind != "wick":
            continue
        entry = (zb + zt) / 2
        if dirn == "LONG":
            sl = zb - sl_buf_atr * atr
        else:
            sl = zt + sl_buf_atr * atr
        start = df.index[touch_idx] + tf_td
        results_per_rr = sim_with_rr_list(dirn, entry, sl, df_1m, start, RR_LIST, timeout_days)
        record = {"experiment": name, "time": df.index[idx], "direction": dirn,
                   "entry": entry, "sl": sl}
        for rr, r in results_per_rr.items():
            record[f"outcome_rr{rr}"] = r["outcome"]
            record[f"R_rr{rr}"] = r["R"]
        setups.append(record)
    return setups


def gather_setups_rdrb_in_zone(df_1h, df_lt, df_1m, name, detect_zone_fn,
                                 zone_size_filter, sl_buf_atr=0.5):
    df_1h = df_1h.copy()
    df_1h["atr14"] = compute_atr(df_1h, 14)
    df_lt = df_lt.copy()
    df_lt["atr14"] = compute_atr(df_lt, 14)
    zones = []
    for idx in range(2, len(df_lt) - 1):
        z = detect_zone_fn(df_lt, idx)
        if z is None:
            continue
        atr = float(df_lt["atr14"].iloc[idx])
        if pd.isna(atr) or atr <= 0:
            continue
        if isinstance(z, dict):
            zb, zt, dirn = z["bottom"], z["top"], z["direction"]
        else:
            zb, zt, dirn = z.bottom, z.top, z.direction
        size_atr = (zt - zb) / atr
        if zone_size_filter and not zone_size_filter(size_atr):
            continue
        c2_time = (z.cur_time if hasattr(z, "cur_time")
                    else (z.c2_time if hasattr(z, "c2_time") else df_lt.index[idx]))
        zones.append({"direction": dirn, "bottom": zb, "top": zt,
                       "active_from": c2_time,
                       "active_to": c2_time + pd.Timedelta(days=30)})
    setups = []
    for j in range(2, len(df_1h) - 1):
        ts_1h = df_1h.index[j]
        active = [z for z in zones if z["active_from"] < ts_1h <= z["active_to"]]
        if not active:
            continue
        rdrb = detect_rdrb(df_1h, j)
        if rdrb is None:
            continue
        matches = [z for z in active
                    if z["direction"] == rdrb["direction"]
                    and not (rdrb["top"] < z["bottom"] or rdrb["bottom"] > z["top"])]
        if not matches:
            continue
        atr_1h = float(df_1h["atr14"].iloc[j])
        if pd.isna(atr_1h) or atr_1h <= 0:
            continue
        entry = (rdrb["bottom"] + rdrb["top"]) / 2
        if rdrb["direction"] == "LONG":
            sl = rdrb["trigger_low"] - sl_buf_atr * atr_1h
        else:
            sl = rdrb["trigger_high"] + sl_buf_atr * atr_1h
        start = ts_1h + pd.Timedelta(hours=1)
        results = sim_with_rr_list(rdrb["direction"], entry, sl, df_1m, start, RR_LIST, TIMEOUT_DAYS_LTF)
        record = {"experiment": name, "time": ts_1h, "direction": rdrb["direction"],
                   "entry": entry, "sl": sl}
        for rr, r in results.items():
            record[f"outcome_rr{rr}"] = r["outcome"]
            record[f"R_rr{rr}"] = r["R"]
        setups.append(record)
    return setups


def gather_setups_fractal_wick_pro(df, df_1m, sl_buf_atr=0.3):
    df = df.copy()
    df["atr14"] = compute_atr(df, 14)
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    tf_td = pd.Timedelta(days=1)
    setups = []
    for i in range(2, len(df) - 2):
        ll = is_ll(df, i); hh = is_hh(df, i)
        if not (ll or hh) or (ll and hh):
            continue
        atr = float(df["atr14"].iloc[i])
        em = float(df["ema200"].iloc[i])
        if pd.isna(atr) or atr <= 0 or pd.isna(em):
            continue
        cur_close = float(df["close"].iloc[i])
        if ll:
            level = float(df["low"].iloc[i]); direction = "LONG"
            if cur_close <= em:
                continue
            sl = level - sl_buf_atr * atr
        else:
            level = float(df["high"].iloc[i]); direction = "SHORT"
            if cur_close >= em:
                continue
            sl = level + sl_buf_atr * atr
        end_idx = min(i + 100, len(df) - 1)
        touch_idx = None
        for j in range(i + 3, end_idx + 1):
            h = float(df["high"].iloc[j]); l = float(df["low"].iloc[j])
            c = float(df["close"].iloc[j])
            if direction == "LONG":
                if l <= level:
                    if c > level: touch_idx = j; break
                    else: break
            else:
                if h >= level:
                    if c < level: touch_idx = j; break
                    else: break
        if touch_idx is None:
            continue
        start = df.index[touch_idx] + tf_td
        results = sim_with_rr_list(direction, level, sl, df_1m, start, RR_LIST, TIMEOUT_DAYS_HTF)
        record = {"experiment": "Fractal-1d wick+pro", "time": df.index[i],
                   "direction": direction, "entry": level, "sl": sl}
        for rr, r in results.items():
            record[f"outcome_rr{rr}"] = r["outcome"]
            record[f"R_rr{rr}"] = r["R"]
        setups.append(record)
    return setups


def main():
    print("[INFO] loading")
    df_1d = load_df(SYMBOL, "1d")
    df_1h = load_df(SYMBOL, "1h")
    df_1m = load_df(SYMBOL, "1m")
    start = pd.Timestamp(START_DATE, tz="UTC")
    df_1d = df_1d[df_1d.index >= start]
    df_1h = df_1h[df_1h.index >= start]
    df_1m = df_1m[df_1m.index >= start]

    all_records = []

    print("\n[E1] RDRB-1d wick")
    all_records += gather_setups_zone_wick(df_1d, df_1m, "E1: RDRB-1d wick", detect_rdrb)
    print(f"  cumulative records: {len(all_records)}")

    print("\n[E2] OB-1d small wick")
    all_records += gather_setups_zone_wick(df_1d, df_1m, "E2: OB-1d small wick", detect_ob_pair,
                                            size_filter=lambda s: s < 0.3)
    print(f"  cumulative: {len(all_records)}")

    print("\n[E3] FVG-1d small wick")
    all_records += gather_setups_zone_wick(df_1d, df_1m, "E3: FVG-1d small wick", detect_fvg,
                                            size_filter=lambda s: s < 0.3)
    print(f"  cumulative: {len(all_records)}")

    print("\n[E4] RDRB-1h in FVG-1d small")
    all_records += gather_setups_rdrb_in_zone(df_1h, df_1d, df_1m, "E4: RDRB-1h in FVG-1d small",
                                                detect_fvg, lambda s: s < 0.3)
    print(f"  cumulative: {len(all_records)}")

    print("\n[E5] RDRB-1h in OB-1d small")
    all_records += gather_setups_rdrb_in_zone(df_1h, df_1d, df_1m, "E5: RDRB-1h in OB-1d small",
                                                detect_ob_pair, lambda s: s < 0.3)
    print(f"  cumulative: {len(all_records)}")

    print("\n[E6] Fractal-1d wick+pro")
    all_records += gather_setups_fractal_wick_pro(df_1d, df_1m)
    print(f"  cumulative: {len(all_records)}")

    print("\n[E7] RDRB-1d wick+pro")
    all_records += gather_setups_zone_wick(df_1d, df_1m, "E7: RDRB-1d wick+pro",
                                            detect_rdrb, require_pro_trend=True)
    print(f"  total records: {len(all_records)}")

    df_all = pd.DataFrame(all_records)
    df_all.to_csv(OUT_DIR / "rr_sweep_all_records.csv", index=False)

    # Сводка по (experiment, RR)
    print("\n=== СВОДКА (per experiment x RR) ===")
    rows = []
    years = (df_1d.index[-1] - df_1d.index[0]).days / 365
    for exp in df_all["experiment"].unique():
        sub = df_all[df_all["experiment"] == exp]
        n = len(sub)
        for rr in RR_LIST:
            outc = sub[f"outcome_rr{rr}"]
            R = sub[f"R_rr{rr}"]
            closed = sub[outc.isin(["win", "loss"])]
            nc = len(closed)
            if nc == 0:
                continue
            w = (closed[f"outcome_rr{rr}"] == "win").sum()
            wr = w / nc * 100
            total_R = closed[f"R_rr{rr}"].sum()
            mean_R = closed[f"R_rr{rr}"].mean()
            rows.append({
                "experiment": exp, "RR": rr, "n_total": n,
                "n_per_week": round(n / years / 52, 2),
                "n_closed": nc,
                "WR%": round(wr, 1),
                "total_R": round(total_R, 1),
                "R/trade": round(mean_R, 3),
            })
    summary = pd.DataFrame(rows)
    summary.to_csv(OUT_DIR / "rr_sweep_summary.csv", index=False)
    print(summary.to_string(index=False))

    print("\n=== ПРОШЛИ (WR>=55, n/week>=1) ===")
    pf = summary[(summary["WR%"] >= 55) & (summary["n_per_week"] >= 1)]
    if len(pf):
        print(pf.to_string(index=False))
    else:
        print("Никто. Топ-5 по R/trade:")
        print(summary.sort_values("R/trade", ascending=False).head(5).to_string(index=False))


if __name__ == "__main__":
    main()
