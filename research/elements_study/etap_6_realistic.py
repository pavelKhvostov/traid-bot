"""Этап 6: реалистичный backtest 5 одиночных-element setups.

Каждый setup:
  - element detection (RDRB, OB, FVG, Fractal) с фильтрами из observations
  - entry = mid-zone (или level для фрактала)
  - SL = расширенный (за trigger/c0 + N·ATR)
  - TP = entry + 2 × risk (RR = 2)
  - simulation на 1m с момента close zone-cur

Кандидаты:
  1. RDRB-1h all (без фильтра)
  2. RDRB-1d all
  3. FVG-1d small (size < 0.3·ATR)
  4. OB-1d small (size < 0.3·ATR)
  5. Fractal-1d FL pro-trend (LL above EMA200)
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


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]; low = df["low"]; prev_close = df["close"].shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def detect_rdrb(df: pd.DataFrame, idx: int):
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


def simulate(direction, entry, sl, tp, df_1m, start_time, timeout_days=TIMEOUT_DAYS):
    """Limit-fill активация → SL/TP first hit на 1m."""
    sim = df_1m[df_1m.index >= start_time]
    if sim.empty:
        return {"outcome": "no_data", "R": 0.0}
    end_time = start_time + pd.Timedelta(days=timeout_days)
    sim = sim[sim.index <= end_time]
    if sim.empty:
        return {"outcome": "no_data", "R": 0.0}

    # активация
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


# === Кандидаты ===

def candidate_rdrb_basic(df, df_1m, tf_label, sl_buf_atr=0.5):
    """RDRB на любом TF без фильтров."""
    df = df.copy()
    df["atr14"] = compute_atr(df, 14)
    tf_td = pd.Timedelta(df.index[1] - df.index[0])  # tf duration
    setups = []
    for idx in range(2, len(df) - 1):
        z = detect_rdrb(df, idx)
        if z is None:
            continue
        atr = float(df["atr14"].iloc[idx])
        if pd.isna(atr) or atr <= 0:
            continue
        entry = (z["bottom"] + z["top"]) / 2
        if z["direction"] == "LONG":
            sl = z["trigger_low"] - sl_buf_atr * atr
            tp = entry + RR * (entry - sl)
        else:
            sl = z["trigger_high"] + sl_buf_atr * atr
            tp = entry - RR * (sl - entry)
        start = df.index[idx] + tf_td
        out = simulate(z["direction"], entry, sl, tp, df_1m, start)
        setups.append({
            "candidate": f"RDRB-{tf_label}",
            "time": df.index[idx], "direction": z["direction"],
            "entry": entry, "sl": sl, "tp": tp,
            "atr": atr, **out,
        })
    return setups


def candidate_fvg_1d_small(df, df_1m, sl_buf_atr=0.3):
    """FVG-1d small (size < 0.3·ATR). Entry = mid, SL = far border - buffer."""
    df = df.copy()
    df["atr14"] = compute_atr(df, 14)
    tf_td = pd.Timedelta(days=1)
    setups = []
    for idx in range(2, len(df) - 1):
        f = detect_fvg(df, idx)
        if f is None:
            continue
        atr = float(df["atr14"].iloc[idx])
        if pd.isna(atr) or atr <= 0:
            continue
        size_atr = (f.top - f.bottom) / atr
        if size_atr >= 0.3:
            continue
        entry = (f.bottom + f.top) / 2
        if f.direction == "LONG":
            sl = f.bottom - sl_buf_atr * atr
            tp = entry + RR * (entry - sl)
        else:
            sl = f.top + sl_buf_atr * atr
            tp = entry - RR * (sl - entry)
        start = f.c2_time + tf_td
        out = simulate(f.direction, entry, sl, tp, df_1m, start, timeout_days=30)
        setups.append({
            "candidate": "FVG-1d small",
            "time": f.c2_time, "direction": f.direction,
            "entry": entry, "sl": sl, "tp": tp,
            "size_atr": size_atr, **out,
        })
    return setups


def candidate_ob_1d_small(df, df_1m, sl_buf_atr=0.3):
    """OB-1d small (size < 0.3·ATR)."""
    df = df.copy()
    df["atr14"] = compute_atr(df, 14)
    tf_td = pd.Timedelta(days=1)
    setups = []
    for idx in range(1, len(df) - 1):
        ob = detect_ob_pair(df, idx)
        if ob is None:
            continue
        atr = float(df["atr14"].iloc[idx])
        if pd.isna(atr) or atr <= 0:
            continue
        size_atr = (ob.top - ob.bottom) / atr
        if size_atr >= 0.3:
            continue
        entry = (ob.bottom + ob.top) / 2
        if ob.direction == "LONG":
            sl = ob.bottom - sl_buf_atr * atr
            tp = entry + RR * (entry - sl)
        else:
            sl = ob.top + sl_buf_atr * atr
            tp = entry - RR * (sl - entry)
        start = ob.cur_time + tf_td
        out = simulate(ob.direction, entry, sl, tp, df_1m, start, timeout_days=30)
        setups.append({
            "candidate": "OB-1d small",
            "time": ob.cur_time, "direction": ob.direction,
            "entry": entry, "sl": sl, "tp": tp,
            "size_atr": size_atr, **out,
        })
    return setups


def candidate_fractal_1d_pro(df, df_1m, sl_buf_atr=0.3):
    """Fractal-1d FL pro-trend (LL above EMA200) или FH pro-trend (HH below).
    Entry = level, SL = wick low/high - buf·ATR.
    Активация = первое касание после i+2."""
    df = df.copy()
    df["atr14"] = compute_atr(df, 14)
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    tf_td = pd.Timedelta(days=1)
    setups = []
    for i in range(2, len(df) - 2):
        is_ll = is_ll_fractal(df, i)
        is_hh = is_hh_fractal(df, i)
        if not (is_ll or is_hh):
            continue
        if is_ll and is_hh:
            continue
        em = float(df["ema200"].iloc[i])
        cur_close = float(df["close"].iloc[i])
        atr = float(df["atr14"].iloc[i])
        if pd.isna(em) or pd.isna(atr) or atr <= 0:
            continue
        if is_ll:
            level = float(df["low"].iloc[i])
            direction = "LONG"
            # pro-trend: ema200 ниже close (bull regime)
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
        # confirm time = i+2 close
        confirm_time = df.index[i + 2] + tf_td
        out = simulate(direction, entry, sl, tp, df_1m, confirm_time, timeout_days=30)
        setups.append({
            "candidate": "Fractal-1d pro",
            "time": df.index[i], "direction": direction,
            "entry": entry, "sl": sl, "tp": tp,
            "fractal_type": "FL" if is_ll else "FH",
            **out,
        })
    return setups


def main():
    print("[INFO] loading data")
    df_1d = load_df(SYMBOL, "1d")
    df_1h = load_df(SYMBOL, "1h")
    df_1m = load_df(SYMBOL, "1m")
    start = pd.Timestamp(START_DATE, tz="UTC")
    df_1d = df_1d[df_1d.index >= start]
    df_1h = df_1h[df_1h.index >= start]
    df_1m = df_1m[df_1m.index >= start]
    print(f"  1d={len(df_1d)} 1h={len(df_1h)} 1m={len(df_1m)}")

    all_setups = {}
    print("\n[1/5] RDRB-1h basic")
    s1 = candidate_rdrb_basic(df_1h, df_1m, "1h")
    pd.DataFrame(s1).to_csv(OUT_DIR / "real_rdrb_1h.csv", index=False)
    all_setups["RDRB-1h"] = s1

    print("\n[2/5] RDRB-1d basic")
    s2 = candidate_rdrb_basic(df_1d, df_1m, "1d")
    pd.DataFrame(s2).to_csv(OUT_DIR / "real_rdrb_1d.csv", index=False)
    all_setups["RDRB-1d"] = s2

    print("\n[3/5] FVG-1d small")
    s3 = candidate_fvg_1d_small(df_1d, df_1m)
    pd.DataFrame(s3).to_csv(OUT_DIR / "real_fvg_1d_small.csv", index=False)
    all_setups["FVG-1d small"] = s3

    print("\n[4/5] OB-1d small")
    s4 = candidate_ob_1d_small(df_1d, df_1m)
    pd.DataFrame(s4).to_csv(OUT_DIR / "real_ob_1d_small.csv", index=False)
    all_setups["OB-1d small"] = s4

    print("\n[5/5] Fractal-1d pro-trend")
    s5 = candidate_fractal_1d_pro(df_1d, df_1m)
    pd.DataFrame(s5).to_csv(OUT_DIR / "real_fractal_1d_pro.csv", index=False)
    all_setups["Fractal-1d pro"] = s5

    print("\n=== ИТОГОВАЯ СВОДКА (RR=2) ===")
    rows = []
    years = (df_1d.index[-1] - df_1d.index[0]).days / 365
    for name, setups in all_setups.items():
        if not setups:
            continue
        df = pd.DataFrame(setups)
        n = len(df)
        nf = (df["outcome"] == "not_filled").sum()
        op = (df["outcome"] == "open").sum()
        closed = df[df["outcome"].isin(["win", "loss"])]
        nc = len(closed)
        if nc == 0:
            continue
        w = (closed["outcome"] == "win").sum()
        wr = w / nc * 100
        total_R = closed["R"].sum()
        mean_R = closed["R"].mean()
        rows.append({
            "candidate": name,
            "n_total": n,
            "n_per_year": round(n / years, 1),
            "n_per_week": round(n / years / 52, 2),
            "n_closed": nc,
            "n_not_filled": int(nf),
            "n_open": int(op),
            "WR%": round(wr, 1),
            "total_R": round(total_R, 1),
            "R/trade": round(mean_R, 3),
        })
    summary = pd.DataFrame(rows).sort_values("WR%", ascending=False)
    summary.to_csv(OUT_DIR / "real_setups_summary.csv", index=False)
    print(summary.to_string(index=False))

    print("\n=== ПРОВЕРКА КРИТЕРИЕВ (WR>=70%, n/week>=1) ===")
    pass_filter = summary[(summary["WR%"] >= 70) & (summary["n_per_week"] >= 1)]
    if len(pass_filter):
        print("ПРОШЛИ:")
        print(pass_filter.to_string(index=False))
    else:
        print("Никто не прошёл оба критерия одновременно.")


if __name__ == "__main__":
    main()
