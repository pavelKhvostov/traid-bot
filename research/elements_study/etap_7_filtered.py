"""Этап 7: Multi-фильтры на лучших single-element setups.

Цель: WR>=55% при RR=2, n>=1/нед.

Эксперименты:
  E1. RDRB-1d + wick-touch first (close первой касающейся свечи СНАРУЖИ зоны)
  E2. OB-1d small + wick-touch first
  E3. FVG-1d small + wick-touch first
  E4. RDRB-1h в зоне FVG-1d small (multi-TF confluence)
  E5. RDRB-1h в зоне OB-1d small
  E6. Fractal-1d FL/FH wick-touch + pro-trend
  E7. RDRB-1d wick-touch + pro-trend
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
RR = 2.0
TIMEOUT_DAYS = 14

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


def is_hh_fractal(df, i):
    if i < 2 or i + 2 >= len(df):
        return False
    hi = float(df["high"].iloc[i])
    return all(hi > float(df["high"].iloc[k]) for k in (i-2, i-1, i+1, i+2))


def is_ll_fractal(df, i):
    if i < 2 or i + 2 >= len(df):
        return False
    lo = float(df["low"].iloc[i])
    return all(lo < float(df["low"].iloc[k]) for k in (i-2, i-1, i+1, i+2))


def find_first_touch(df, start_idx, direction, top, bottom, max_bars=200):
    """Возвращает (touch_idx, touch_kind) или (None, None).
    touch_kind: wick / close_inside / pierce."""
    end = min(start_idx + max_bars, len(df) - 1)
    for j in range(start_idx, end + 1):
        row = df.iloc[j]
        h, l, c = float(row["high"]), float(row["low"]), float(row["close"])
        if direction == "LONG":
            if l <= top:
                if c < bottom:
                    return j, "pierce"
                if bottom <= c <= top:
                    return j, "close_inside"
                return j, "wick"
        else:
            if h >= bottom:
                if c > top:
                    return j, "pierce"
                if bottom <= c <= top:
                    return j, "close_inside"
                return j, "wick"
    return None, None


def simulate(direction, entry, sl, tp, df_1m, start_time, timeout_days=TIMEOUT_DAYS):
    sim = df_1m[df_1m.index >= start_time]
    if sim.empty:
        return {"outcome": "no_data", "R": 0.0}
    end_time = start_time + pd.Timedelta(days=timeout_days)
    sim = sim[sim.index <= end_time]
    if sim.empty:
        return {"outcome": "no_data", "R": 0.0}
    activation = None
    for ts, row in sim.iterrows():
        h, l = float(row["high"]), float(row["low"])
        if direction == "LONG" and l <= entry:
            activation = ts; break
        if direction == "SHORT" and h >= entry:
            activation = ts; break
    if activation is None:
        return {"outcome": "not_filled", "R": 0.0}
    risk = abs(entry - sl)
    if risk <= 0:
        return {"outcome": "invalid", "R": 0.0}
    sim2 = sim[sim.index >= activation]
    for ts, row in sim2.iterrows():
        h, l = float(row["high"]), float(row["low"])
        if direction == "LONG":
            if l <= sl:
                return {"outcome": "loss", "R": -1.0}
            if h >= tp:
                return {"outcome": "win", "R": RR}
        else:
            if h >= sl:
                return {"outcome": "loss", "R": -1.0}
            if l <= tp:
                return {"outcome": "win", "R": RR}
    return {"outcome": "open", "R": 0.0}


# === Эксперименты ===

def exp_zone_wick_touch(df_main, df_1m, name, detect_fn, size_filter=None,
                        require_pro_trend=False, ema200=None, sl_buf_atr=0.3):
    """Generic: zone + wick-touch first, optional size filter & pro-trend."""
    df = df_main.copy()
    df["atr14"] = compute_atr(df, 14)
    if require_pro_trend:
        df["ema200_calc"] = df["close"].ewm(span=200, adjust=False).mean()
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
            em = float(df["ema200_calc"].iloc[idx])
            if pd.isna(em):
                continue
            cur_close = float(df["close"].iloc[idx])
            is_bull_regime = cur_close > em
            if dirn == "LONG" and not is_bull_regime:
                continue
            if dirn == "SHORT" and is_bull_regime:
                continue
        # Wait for first touch
        touch_idx, touch_kind = find_first_touch(df, idx + 1, dirn, zt, zb, max_bars=100)
        if touch_idx is None or touch_kind != "wick":
            continue
        entry = (zb + zt) / 2
        if dirn == "LONG":
            sl = zb - sl_buf_atr * atr
            tp = entry + RR * (entry - sl)
        else:
            sl = zt + sl_buf_atr * atr
            tp = entry - RR * (sl - entry)
        # Активация ТОЛЬКО если цена снова придёт к entry после wick-touch
        # (обычно сразу же — на свече touch_idx или следующей)
        start = df.index[touch_idx] + tf_td
        out = simulate(dirn, entry, sl, tp, df_1m, start,
                        timeout_days=30 if tf_td >= pd.Timedelta(days=1) else 14)
        setups.append({
            "candidate": name, "time": df.index[idx], "direction": dirn,
            "size_atr": size_atr, "touch_kind": touch_kind,
            "entry": entry, "sl": sl, "tp": tp, **out,
        })
    return setups


def exp_fractal_wick_pro(df, df_1m, sl_buf_atr=0.3):
    df = df.copy()
    df["atr14"] = compute_atr(df, 14)
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    tf_td = pd.Timedelta(days=1)
    setups = []
    for i in range(2, len(df) - 2):
        is_ll = is_ll_fractal(df, i)
        is_hh = is_hh_fractal(df, i)
        if not (is_ll or is_hh) or (is_ll and is_hh):
            continue
        atr = float(df["atr14"].iloc[i])
        em = float(df["ema200"].iloc[i])
        if pd.isna(atr) or atr <= 0 or pd.isna(em):
            continue
        cur_close = float(df["close"].iloc[i])
        if is_ll:
            level = float(df["low"].iloc[i])
            direction = "LONG"
            if cur_close <= em:
                continue
            entry = level
            sl = level - sl_buf_atr * atr
            tp = entry + RR * (entry - sl)
        else:
            level = float(df["high"].iloc[i])
            direction = "SHORT"
            if cur_close >= em:
                continue
            entry = level
            sl = level + sl_buf_atr * atr
            tp = entry - RR * (sl - entry)
        # Wait first touch + check wick (close на нашей стороне)
        end_idx = min(i + 100, len(df) - 1)
        touch_idx = None
        for j in range(i + 3, end_idx + 1):
            h = float(df["high"].iloc[j]); l = float(df["low"].iloc[j])
            c = float(df["close"].iloc[j])
            if direction == "LONG":
                if l <= level:
                    if c > level:
                        touch_idx = j; break
                    else:
                        break  # sweep — пропуск
            else:
                if h >= level:
                    if c < level:
                        touch_idx = j; break
                    else:
                        break
        if touch_idx is None:
            continue
        start = df.index[touch_idx] + tf_td
        out = simulate(direction, entry, sl, tp, df_1m, start, timeout_days=30)
        setups.append({
            "candidate": "Fractal-1d wick+pro", "time": df.index[i],
            "direction": direction, "fractal_type": "FL" if is_ll else "FH",
            "entry": entry, "sl": sl, "tp": tp, **out,
        })
    return setups


def exp_rdrb_in_zone(df_1h, df_lt, df_1m, name, detect_fn, size_filter, sl_buf_atr=0.5):
    """RDRB-1h в зоне FVG-1d или OB-1d small."""
    df_1h = df_1h.copy()
    df_1h["atr14"] = compute_atr(df_1h, 14)
    df_lt = df_lt.copy()
    df_lt["atr14"] = compute_atr(df_lt, 14)

    # Найти все active zones на старшем TF
    zones = []
    for idx in range(2, len(df_lt) - 1):
        z = detect_fn(df_lt, idx)
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
        if size_filter and not size_filter(size_atr):
            continue
        c2_time = (z.cur_time if hasattr(z, "cur_time")
                    else (z.c2_time if hasattr(z, "c2_time") else df_lt.index[idx]))
        zones.append({"direction": dirn, "bottom": zb, "top": zt,
                      "active_from": c2_time, "active_to": c2_time + pd.Timedelta(days=30)})

    setups = []
    for j in range(2, len(df_1h) - 1):
        ts_1h = df_1h.index[j]
        # Проверить, в какой зоне сейчас
        active_zones = [z for z in zones
                         if z["active_from"] < ts_1h <= z["active_to"]]
        if not active_zones:
            continue
        rdrb = detect_rdrb(df_1h, j)
        if rdrb is None:
            continue
        # Должен быть в одной из активных зон того же direction
        matching = [z for z in active_zones
                     if z["direction"] == rdrb["direction"]
                     and not (rdrb["top"] < z["bottom"] or rdrb["bottom"] > z["top"])]
        if not matching:
            continue
        atr_1h = float(df_1h["atr14"].iloc[j])
        if pd.isna(atr_1h) or atr_1h <= 0:
            continue
        entry = (rdrb["bottom"] + rdrb["top"]) / 2
        if rdrb["direction"] == "LONG":
            sl = rdrb["trigger_low"] - sl_buf_atr * atr_1h
            tp = entry + RR * (entry - sl)
        else:
            sl = rdrb["trigger_high"] + sl_buf_atr * atr_1h
            tp = entry - RR * (sl - entry)
        start = ts_1h + pd.Timedelta(hours=1)
        out = simulate(rdrb["direction"], entry, sl, tp, df_1m, start, timeout_days=14)
        setups.append({
            "candidate": name, "time": ts_1h, "direction": rdrb["direction"],
            "entry": entry, "sl": sl, "tp": tp, **out,
        })
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

    all_setups = {}

    print("\n[E1] RDRB-1d + wick-touch first")
    s1 = exp_zone_wick_touch(df_1d, df_1m, "RDRB-1d wick", detect_rdrb)
    pd.DataFrame(s1).to_csv(OUT_DIR / "filt_E1.csv", index=False)
    all_setups["E1: RDRB-1d wick"] = s1

    print("\n[E2] OB-1d small + wick-touch first")
    s2 = exp_zone_wick_touch(df_1d, df_1m, "OB-1d small wick", detect_ob_pair,
                              size_filter=lambda s: s < 0.3)
    pd.DataFrame(s2).to_csv(OUT_DIR / "filt_E2.csv", index=False)
    all_setups["E2: OB-1d small wick"] = s2

    print("\n[E3] FVG-1d small + wick-touch first")
    s3 = exp_zone_wick_touch(df_1d, df_1m, "FVG-1d small wick", detect_fvg,
                              size_filter=lambda s: s < 0.3)
    pd.DataFrame(s3).to_csv(OUT_DIR / "filt_E3.csv", index=False)
    all_setups["E3: FVG-1d small wick"] = s3

    print("\n[E4] RDRB-1h в зоне FVG-1d small")
    s4 = exp_rdrb_in_zone(df_1h, df_1d, df_1m, "RDRB-1h in FVG-1d small",
                           detect_fvg, size_filter=lambda s: s < 0.3)
    pd.DataFrame(s4).to_csv(OUT_DIR / "filt_E4.csv", index=False)
    all_setups["E4: RDRB-1h in FVG-1d small"] = s4

    print("\n[E5] RDRB-1h в зоне OB-1d small")
    s5 = exp_rdrb_in_zone(df_1h, df_1d, df_1m, "RDRB-1h in OB-1d small",
                           detect_ob_pair, size_filter=lambda s: s < 0.3)
    pd.DataFrame(s5).to_csv(OUT_DIR / "filt_E5.csv", index=False)
    all_setups["E5: RDRB-1h in OB-1d small"] = s5

    print("\n[E6] Fractal-1d wick + pro-trend")
    s6 = exp_fractal_wick_pro(df_1d, df_1m)
    pd.DataFrame(s6).to_csv(OUT_DIR / "filt_E6.csv", index=False)
    all_setups["E6: Fractal-1d wick+pro"] = s6

    print("\n[E7] RDRB-1d wick + pro-trend (EMA200)")
    s7 = exp_zone_wick_touch(df_1d, df_1m, "RDRB-1d wick+pro",
                              detect_rdrb, require_pro_trend=True)
    pd.DataFrame(s7).to_csv(OUT_DIR / "filt_E7.csv", index=False)
    all_setups["E7: RDRB-1d wick+pro"] = s7

    print("\n=== СВОДКА (RR=2, target WR>=55%, n/week>=1) ===")
    rows = []
    years = (df_1d.index[-1] - df_1d.index[0]).days / 365
    for name, setups in all_setups.items():
        if not setups:
            rows.append({"experiment": name, "n_total": 0})
            continue
        df = pd.DataFrame(setups)
        n = len(df)
        nf = (df["outcome"] == "not_filled").sum()
        op = (df["outcome"] == "open").sum()
        closed = df[df["outcome"].isin(["win", "loss"])]
        nc = len(closed)
        if nc == 0:
            rows.append({"experiment": name, "n_total": n, "n_closed": 0})
            continue
        w = (closed["outcome"] == "win").sum()
        wr = w / nc * 100
        total_R = closed["R"].sum()
        mean_R = closed["R"].mean()
        rows.append({
            "experiment": name, "n_total": n,
            "n_per_year": round(n / years, 1),
            "n_per_week": round(n / years / 52, 2),
            "n_closed": nc,
            "n_not_filled": int(nf),
            "WR%": round(wr, 1),
            "total_R": round(total_R, 1),
            "R/trade": round(mean_R, 3),
        })
    summary = pd.DataFrame(rows).sort_values("WR%", ascending=False, na_position="last")
    summary.to_csv(OUT_DIR / "filt_summary.csv", index=False)
    print(summary.to_string(index=False))

    print("\n=== ПРОШЛИ (WR>=55, n/week>=1) ===")
    pf = summary.dropna(subset=["WR%"])
    pf = pf[(pf["WR%"] >= 55) & (pf["n_per_week"] >= 1)]
    if len(pf):
        print(pf.to_string(index=False))
    else:
        print("Никто. Расширяю окно — WR>=55, n/week>=0.5:")
        pf2 = summary.dropna(subset=["WR%"])
        pf2 = pf2[(pf2["WR%"] >= 55) & (pf2["n_per_week"] >= 0.5)]
        if len(pf2):
            print(pf2.to_string(index=False))
        else:
            print("Тоже никто. Топ-3 по WR:")
            print(summary.dropna(subset=["WR%"]).head(3).to_string(index=False))


if __name__ == "__main__":
    main()
