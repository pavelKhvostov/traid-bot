"""Этап 5: 5 связок (А-Д), детектирование и базовая оценка outcome.

Каждая связка использует уже посчитанные базовые элементы (OB, FVG, RDRB,
Fractal). Outcome измеряется через простой mean-reversion-симулятор:
entry = mid-зоны (или специфичный для связки), SL = расширенный, TP = по RR.

Сохраняем CSV setups + сводку.
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

import numpy as np
import pandas as pd

from data_manager import load_df
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
LOOKBACK_BARS_HTF = 100  # сколько баров вперёд проверяем outcome (htf)
SIZE_ATR_THRESHOLD = 0.3  # для small zone

OUT_DIR = Path("research/elements_study/output")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [(high - low),
         (high - prev_close).abs(),
         (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()


def is_hh_fractal(df: pd.DataFrame, i: int) -> bool:
    if i < 2 or i + 2 >= len(df):
        return False
    hi = float(df["high"].iloc[i])
    for k in (i - 2, i - 1, i + 1, i + 2):
        if hi <= float(df["high"].iloc[k]):
            return False
    return True


def is_ll_fractal(df: pd.DataFrame, i: int) -> bool:
    if i < 2 or i + 2 >= len(df):
        return False
    lo = float(df["low"].iloc[i])
    for k in (i - 2, i - 1, i + 1, i + 2):
        if lo >= float(df["low"].iloc[k]):
            return False
    return True


def detect_rdrb(df: pd.DataFrame, idx: int):
    if idx < 2:
        return None
    a = df.iloc[idx - 2]
    m = df.iloc[idx - 1]
    c = df.iloc[idx]
    a_open, a_close, a_high, a_low = float(a["open"]), float(a["close"]), float(a["high"]), float(a["low"])
    m_close = float(m["close"])
    c_open, c_high, c_low, c_close = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
    if m_close > a_high and c_low < a_high and c_close > a_high:
        zb = max(c_low, max(a_open, a_close))
        zt = min(a_high, min(c_open, c_close))
        if zt <= zb:
            return None
        return {"direction": "LONG", "bottom": zb, "top": zt,
                "trigger_idx": idx, "trigger_low": c_low, "trigger_high": c_high}
    if m_close < a_low and c_high > a_low and c_close < a_low:
        zb = max(a_low, max(c_open, c_close))
        zt = min(c_high, min(a_open, a_close))
        if zt <= zb:
            return None
        return {"direction": "SHORT", "bottom": zb, "top": zt,
                "trigger_idx": idx, "trigger_low": c_low, "trigger_high": c_high}
    return None


def zones_overlap(b1, t1, b2, t2):
    return not (t1 < b2 or t2 < b1)


def in_zone(price, bottom, top):
    return bottom <= price <= top


def simulate_simple_outcome(direction: str, entry: float, sl: float, tp: float,
                              df_lower: pd.DataFrame, start_time: pd.Timestamp,
                              timeout_bars: int) -> dict:
    """Простая симуляция outcome.
    Активация: первая свеча после start_time где low<=entry (LONG) / high>=entry.
    После активации: первый из (SL, TP).
    """
    # фильтруем df_lower с start_time
    sim = df_lower[df_lower.index >= start_time]
    if len(sim) == 0:
        return {"outcome": "no_data", "R": 0.0, "activation_time": None,
                "exit_time": None}
    sim = sim.iloc[: timeout_bars * 4]  # запас по барам

    # Активация
    activation_idx = None
    for j, (ts, row) in enumerate(sim.iterrows()):
        h, l = float(row["high"]), float(row["low"])
        if direction == "LONG" and l <= entry:
            activation_idx = j
            break
        if direction == "SHORT" and h >= entry:
            activation_idx = j
            break

    if activation_idx is None:
        return {"outcome": "not_filled", "R": 0.0, "activation_time": None,
                "exit_time": None}

    activation_time = sim.index[activation_idx]
    risk = abs(entry - sl)
    if risk <= 0:
        return {"outcome": "invalid", "R": 0.0, "activation_time": activation_time,
                "exit_time": None}

    # после активации
    sim2 = sim.iloc[activation_idx:]
    for ts, row in sim2.iterrows():
        h, l = float(row["high"]), float(row["low"])
        if direction == "LONG":
            if l <= sl:
                return {"outcome": "loss", "R": -1.0, "activation_time": activation_time,
                        "exit_time": ts}
            if h >= tp:
                rr = (tp - entry) / risk
                return {"outcome": "win", "R": rr, "activation_time": activation_time,
                        "exit_time": ts}
        else:
            if h >= sl:
                return {"outcome": "loss", "R": -1.0, "activation_time": activation_time,
                        "exit_time": ts}
            if l <= tp:
                rr = (entry - tp) / risk
                return {"outcome": "win", "R": rr, "activation_time": activation_time,
                        "exit_time": ts}
    return {"outcome": "open", "R": 0.0, "activation_time": activation_time,
            "exit_time": None}


# =============== СВЯЗКА А ===============

def detect_connection_A(df_1d: pd.DataFrame, df_4h: pd.DataFrame,
                        df_1h: pd.DataFrame, df_1m: pd.DataFrame,
                        rr_target: float = 3.0) -> list[dict]:
    """OB-1d (small) + RDRB-4h в зоне."""
    df_1d = df_1d.copy()
    df_1d["atr14"] = compute_atr(df_1d, 14)
    df_4h = df_4h.copy()
    df_4h["atr14"] = compute_atr(df_4h, 14)

    setups = []
    for idx_1d in range(1, len(df_1d) - 1):
        ob = detect_ob_pair(df_1d, idx_1d)
        if ob is None:
            continue
        atr_1d = df_1d["atr14"].iloc[idx_1d]
        if pd.isna(atr_1d) or atr_1d <= 0:
            continue
        size_atr = (ob.top - ob.bottom) / atr_1d
        if size_atr >= SIZE_ATR_THRESHOLD:
            continue  # пропускаем medium/large OB

        # Окно жизни OB-1d: 30 дней (typical для daily-level)
        ob_end_time = ob.cur_time + pd.Timedelta(days=30)
        scan_start = ob.cur_time + pd.Timedelta(days=1)
        df_4h_win = df_4h[(df_4h.index >= scan_start) & (df_4h.index <= ob_end_time)]
        if df_4h_win.empty:
            continue

        # Ищем первый RDRB-4h в зоне OB того же направления
        for j_local, (ts_4h, _) in enumerate(df_4h_win.iterrows()):
            j = df_4h.index.get_loc(ts_4h)
            r = detect_rdrb(df_4h, j)
            if r is None or r["direction"] != ob.direction:
                continue
            if not zones_overlap(r["bottom"], r["top"], ob.bottom, ob.top):
                continue

            # Setup найден: entry, sl, tp
            entry = (r["bottom"] + r["top"]) / 2
            atr_4h = df_4h["atr14"].iloc[j]
            if r["direction"] == "LONG":
                sl = r["trigger_low"] - 0.5 * atr_4h  # расширенный SL
                tp = entry + (entry - sl) * rr_target
            else:
                sl = r["trigger_high"] + 0.5 * atr_4h
                tp = entry - (sl - entry) * rr_target

            sim_start = ts_4h + pd.Timedelta(hours=4)  # после close trigger 4h
            outcome = simulate_simple_outcome(
                r["direction"], entry, sl, tp, df_1m, sim_start,
                timeout_bars=30 * 24 * 60,  # 30 дней
            )
            setups.append({
                "connection": "A",
                "direction": ob.direction,
                "ob_1d_time": ob.cur_time,
                "ob_1d_zone": (ob.bottom, ob.top),
                "rdrb_4h_time": ts_4h,
                "rdrb_4h_zone": (r["bottom"], r["top"]),
                "entry": entry, "sl": sl, "tp": tp,
                "rr_target": rr_target,
                **outcome,
            })
            break  # только первый RDRB
    return setups


# =============== СВЯЗКА Б ===============

def detect_connection_B(df_1d: pd.DataFrame, df_1h: pd.DataFrame,
                        df_1m: pd.DataFrame, rr_target: float = 3.0) -> list[dict]:
    """FVG-1d (medium) + sweep fractal на 1h."""
    df_1d = df_1d.copy()
    df_1d["atr14"] = compute_atr(df_1d, 14)
    df_1h = df_1h.copy()
    df_1h["atr14"] = compute_atr(df_1h, 14)

    setups = []
    for idx_1d in range(2, len(df_1d) - 1):
        fvg = detect_fvg(df_1d, idx_1d)
        if fvg is None:
            continue
        atr_1d = df_1d["atr14"].iloc[idx_1d]
        if pd.isna(atr_1d) or atr_1d <= 0:
            continue
        size_atr = (fvg.top - fvg.bottom) / atr_1d
        if size_atr < 0.3 or size_atr >= 1.0:
            continue  # только medium

        # Окно жизни FVG-1d: 30 дней
        fvg_end_time = fvg.c2_time + pd.Timedelta(days=30)
        scan_start = fvg.c2_time + pd.Timedelta(days=1)
        df_1h_win = df_1h[(df_1h.index >= scan_start) & (df_1h.index <= fvg_end_time)]
        if df_1h_win.empty:
            continue

        # Ищем первый sweep fractal на 1h в зоне FVG
        # LONG FVG → ищем LL-fractal внутри зоны, sweep вниз, return вверх
        for j_local in range(2, len(df_1h_win) - 2):
            ts_1h = df_1h_win.index[j_local]
            j = df_1h.index.get_loc(ts_1h)
            if fvg.direction == "LONG":
                if not is_ll_fractal(df_1h, j):
                    continue
                level = float(df_1h["low"].iloc[j])
                # Уровень должен быть В зоне FVG
                if not (fvg.bottom <= level <= fvg.top):
                    continue
                # Ищем sweep после i+2 на 1h
                conf_idx = j + 2
                sweep_idx = None
                for k in range(conf_idx + 1, min(conf_idx + 30, len(df_1h))):
                    h_k = float(df_1h["high"].iloc[k])
                    l_k = float(df_1h["low"].iloc[k])
                    c_k = float(df_1h["close"].iloc[k])
                    if l_k <= level:
                        if c_k <= level:
                            # sweep (close под уровнем) — для LONG это плохо, ждём return
                            # Возможно следующая свеча возвращается?
                            if k + 1 < len(df_1h):
                                next_close = float(df_1h["close"].iloc[k + 1])
                                if next_close > level:
                                    sweep_idx = k
                                    break
                            break
                        else:
                            # просто wick — не sweep
                            break
                if sweep_idx is None:
                    continue
                entry = level
                sl = float(df_1h["low"].iloc[sweep_idx]) - 0.3 * df_1h["atr14"].iloc[sweep_idx]
                tp = entry + (entry - sl) * rr_target
                direction = "LONG"
            else:  # SHORT
                if not is_hh_fractal(df_1h, j):
                    continue
                level = float(df_1h["high"].iloc[j])
                if not (fvg.bottom <= level <= fvg.top):
                    continue
                conf_idx = j + 2
                sweep_idx = None
                for k in range(conf_idx + 1, min(conf_idx + 30, len(df_1h))):
                    h_k = float(df_1h["high"].iloc[k])
                    c_k = float(df_1h["close"].iloc[k])
                    if h_k >= level:
                        if c_k >= level:
                            if k + 1 < len(df_1h):
                                next_close = float(df_1h["close"].iloc[k + 1])
                                if next_close < level:
                                    sweep_idx = k
                                    break
                            break
                        else:
                            break
                if sweep_idx is None:
                    continue
                entry = level
                sl = float(df_1h["high"].iloc[sweep_idx]) + 0.3 * df_1h["atr14"].iloc[sweep_idx]
                tp = entry - (sl - entry) * rr_target
                direction = "SHORT"

            sim_start = df_1h.index[sweep_idx + 1] if sweep_idx + 1 < len(df_1h) else df_1h.index[sweep_idx]
            outcome = simulate_simple_outcome(
                direction, entry, sl, tp, df_1m, sim_start,
                timeout_bars=30 * 24 * 60,
            )
            setups.append({
                "connection": "B",
                "direction": direction,
                "fvg_1d_c2_time": fvg.c2_time,
                "fvg_1d_zone": (fvg.bottom, fvg.top),
                "fractal_1h_time": ts_1h,
                "level": level,
                "sweep_1h_time": df_1h.index[sweep_idx],
                "entry": entry, "sl": sl, "tp": tp,
                "rr_target": rr_target,
                **outcome,
            })
            break
    return setups


# =============== СВЯЗКА В: Triple ===============

def detect_connection_V(df_1d: pd.DataFrame, df_4h: pd.DataFrame,
                        df_1h: pd.DataFrame, df_1m: pd.DataFrame,
                        rr_target: float = 3.0) -> list[dict]:
    """OB-1d + FVG-4h в зоне OB + RDRB-1h в зоне FVG."""
    df_1d = df_1d.copy()
    df_1d["atr14"] = compute_atr(df_1d, 14)
    df_4h = df_4h.copy()
    df_4h["atr14"] = compute_atr(df_4h, 14)
    df_1h = df_1h.copy()
    df_1h["atr14"] = compute_atr(df_1h, 14)

    setups = []
    for idx_1d in range(1, len(df_1d) - 1):
        ob = detect_ob_pair(df_1d, idx_1d)
        if ob is None:
            continue
        atr_1d = df_1d["atr14"].iloc[idx_1d]
        if pd.isna(atr_1d) or atr_1d <= 0:
            continue
        if (ob.top - ob.bottom) / atr_1d >= SIZE_ATR_THRESHOLD:
            continue

        ob_end = ob.cur_time + pd.Timedelta(days=30)
        scan_start = ob.cur_time + pd.Timedelta(days=1)

        # Найти первый FVG-4h того же направления в зоне OB
        df_4h_win = df_4h[(df_4h.index >= scan_start) & (df_4h.index <= ob_end)]
        for fj_local in range(2, len(df_4h_win)):
            ts_4h = df_4h_win.index[fj_local]
            j_4h = df_4h.index.get_loc(ts_4h)
            f = detect_fvg(df_4h, j_4h)
            if f is None or f.direction != ob.direction:
                continue
            if not zones_overlap(f.bottom, f.top, ob.bottom, ob.top):
                continue

            # В этой FVG-4h найти RDRB-1h той же направленности
            fvg_end = f.c2_time + pd.Timedelta(days=10)
            scan_start_1h = f.c2_time + pd.Timedelta(hours=4)
            df_1h_win = df_1h[(df_1h.index >= scan_start_1h) & (df_1h.index <= fvg_end)]
            for k_local in range(2, len(df_1h_win)):
                ts_1h = df_1h_win.index[k_local]
                k_1h = df_1h.index.get_loc(ts_1h)
                r = detect_rdrb(df_1h, k_1h)
                if r is None or r["direction"] != ob.direction:
                    continue
                if not zones_overlap(r["bottom"], r["top"], f.bottom, f.top):
                    continue
                if not zones_overlap(r["bottom"], r["top"], ob.bottom, ob.top):
                    continue

                entry = (r["bottom"] + r["top"]) / 2
                atr_1h = df_1h["atr14"].iloc[k_1h]
                if r["direction"] == "LONG":
                    sl = r["trigger_low"] - 0.5 * atr_1h
                    tp = entry + (entry - sl) * rr_target
                else:
                    sl = r["trigger_high"] + 0.5 * atr_1h
                    tp = entry - (sl - entry) * rr_target

                sim_start = ts_1h + pd.Timedelta(hours=1)
                outcome = simulate_simple_outcome(
                    r["direction"], entry, sl, tp, df_1m, sim_start,
                    timeout_bars=15 * 24 * 60,
                )
                setups.append({
                    "connection": "V",
                    "direction": ob.direction,
                    "ob_1d_time": ob.cur_time,
                    "fvg_4h_time": f.c2_time,
                    "rdrb_1h_time": ts_1h,
                    "entry": entry, "sl": sl, "tp": tp,
                    "rr_target": rr_target,
                    **outcome,
                })
                break
            break  # только первый FVG-4h на OB
    return setups


# =============== СВЯЗКА Г: Counter-FVG + Counter-RDRB (reversal) ===============

def detect_connection_G(df_1h: pd.DataFrame, df_1m: pd.DataFrame,
                        rr_target: float = 2.0) -> list[dict]:
    """Counter-trend FVG-1h + Counter-trend RDRB-1h в той же зоне.
    Counter-trend = direction противоположен EMA200 на 1h."""
    df_1h = df_1h.copy()
    df_1h["atr14"] = compute_atr(df_1h, 14)
    df_1h["ema200"] = df_1h["close"].ewm(span=200, adjust=False).mean()

    setups = []
    for idx in range(2, len(df_1h) - 1):
        f = detect_fvg(df_1h, idx)
        if f is None:
            continue
        em = df_1h["ema200"].iloc[idx]
        if pd.isna(em):
            continue
        cur_close = float(df_1h["close"].iloc[idx])
        is_bull_regime = cur_close > em
        # Counter-trend FVG: LONG в bear, SHORT в bull
        if f.direction == "LONG" and is_bull_regime:
            continue
        if f.direction == "SHORT" and not is_bull_regime:
            continue

        # Ищем RDRB того же направления в окне 50 баров после FVG
        scan_end = idx + 50
        for j in range(idx + 1, min(scan_end, len(df_1h))):
            r = detect_rdrb(df_1h, j)
            if r is None or r["direction"] != f.direction:
                continue
            if not zones_overlap(r["bottom"], r["top"], f.bottom, f.top):
                continue

            entry = (r["bottom"] + r["top"]) / 2
            atr = df_1h["atr14"].iloc[j]
            if r["direction"] == "LONG":
                sl = r["trigger_low"] - 0.5 * atr
                tp = entry + (entry - sl) * rr_target
            else:
                sl = r["trigger_high"] + 0.5 * atr
                tp = entry - (sl - entry) * rr_target

            sim_start = df_1h.index[j] + pd.Timedelta(hours=1)
            outcome = simulate_simple_outcome(
                r["direction"], entry, sl, tp, df_1m, sim_start,
                timeout_bars=10 * 24 * 60,
            )
            setups.append({
                "connection": "G",
                "direction": r["direction"],
                "fvg_1h_time": f.c2_time,
                "rdrb_1h_time": df_1h.index[j],
                "entry": entry, "sl": sl, "tp": tp,
                "rr_target": rr_target,
                **outcome,
            })
            break
    return setups


# =============== СВЯЗКА Д: Fractal-sweep + new OB-1h ===============

def detect_connection_D(df_4h: pd.DataFrame, df_1h: pd.DataFrame,
                        df_1m: pd.DataFrame, rr_target: float = 2.0) -> list[dict]:
    """Fractal-4h sweep'нут на 1h → новый OB-1h образуется в зоне sweep."""
    df_1h = df_1h.copy()
    df_1h["atr14"] = compute_atr(df_1h, 14)

    setups = []
    for i_4h in range(2, len(df_4h) - 2):
        is_hh = is_hh_fractal(df_4h, i_4h)
        is_ll = is_ll_fractal(df_4h, i_4h)
        if not (is_hh or is_ll):
            continue
        if is_hh and is_ll:
            continue

        if is_hh:
            level = float(df_4h["high"].iloc[i_4h])
            direction = "SHORT"
        else:
            level = float(df_4h["low"].iloc[i_4h])
            direction = "LONG"

        # confirm time = (i_4h+2 close)
        confirm_time = df_4h.index[i_4h + 2] + pd.Timedelta(hours=4)
        # Ищем sweep на 1h в окне 30 дней
        scan_end = confirm_time + pd.Timedelta(days=30)
        df_1h_win = df_1h[(df_1h.index >= confirm_time) & (df_1h.index <= scan_end)]
        if df_1h_win.empty:
            continue

        # Найти первую 1h-свечу sweep'а
        sweep_1h_idx = None
        for j_local, (ts_1h, row) in enumerate(df_1h_win.iterrows()):
            h, l, c = float(row["high"]), float(row["low"]), float(row["close"])
            if direction == "SHORT":
                if h >= level:
                    if c >= level:
                        # sweep (close выше уровня)
                        sweep_1h_idx = df_1h.index.get_loc(ts_1h)
                        break
                    else:
                        # wick respect — пока не sweep, продолжаем
                        continue
            else:  # LONG
                if l <= level:
                    if c <= level:
                        sweep_1h_idx = df_1h.index.get_loc(ts_1h)
                        break
                    else:
                        continue
        if sweep_1h_idx is None:
            continue

        # На свече sweep_1h_idx или следующей формируется OB того же direction (LONG для FL, SHORT для FH)
        for k in range(sweep_1h_idx, min(sweep_1h_idx + 5, len(df_1h))):
            ob = detect_ob_pair(df_1h, k)
            if ob is None or ob.direction != direction:
                continue
            entry = (ob.bottom + ob.top) / 2
            atr = df_1h["atr14"].iloc[k]
            if direction == "LONG":
                sl = ob.bottom - 0.3 * atr
                tp = entry + (entry - sl) * rr_target
            else:
                sl = ob.top + 0.3 * atr
                tp = entry - (sl - entry) * rr_target

            sim_start = df_1h.index[k] + pd.Timedelta(hours=1)
            outcome = simulate_simple_outcome(
                direction, entry, sl, tp, df_1m, sim_start,
                timeout_bars=10 * 24 * 60,
            )
            setups.append({
                "connection": "D",
                "direction": direction,
                "fractal_4h_time": df_4h.index[i_4h],
                "level": level,
                "sweep_1h_time": df_1h.index[sweep_1h_idx],
                "ob_1h_time": ob.cur_time,
                "entry": entry, "sl": sl, "tp": tp,
                "rr_target": rr_target,
                **outcome,
            })
            break
    return setups


def main():
    print("[INFO] loading data")
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_1m = load_df(SYMBOL, "1m")
    start = pd.Timestamp(START_DATE, tz="UTC")
    df_1d = df_1d[df_1d.index >= start]
    df_4h = df_4h[df_4h.index >= start]
    df_1h = df_1h[df_1h.index >= start]
    df_1m = df_1m[df_1m.index >= start]
    print(f"  1d={len(df_1d)} 4h={len(df_4h)} 1h={len(df_1h)} 1m={len(df_1m)}")

    print("\n[А] OB-1d small + RDRB-4h в зоне")
    a = detect_connection_A(df_1d, df_4h, df_1h, df_1m, rr_target=3.0)
    pd.DataFrame(a).to_csv(OUT_DIR / "connection_A.csv", index=False)
    print(f"  setups: {len(a)}")

    print("\n[Б] FVG-1d medium + sweep fractal-1h в зоне")
    b = detect_connection_B(df_1d, df_1h, df_1m, rr_target=3.0)
    pd.DataFrame(b).to_csv(OUT_DIR / "connection_B.csv", index=False)
    print(f"  setups: {len(b)}")

    print("\n[В] OB-1d + FVG-4h + RDRB-1h triple")
    v = detect_connection_V(df_1d, df_4h, df_1h, df_1m, rr_target=3.0)
    pd.DataFrame(v).to_csv(OUT_DIR / "connection_V.csv", index=False)
    print(f"  setups: {len(v)}")

    print("\n[Г] Counter-FVG + Counter-RDRB на 1h")
    g = detect_connection_G(df_1h, df_1m, rr_target=2.0)
    pd.DataFrame(g).to_csv(OUT_DIR / "connection_G.csv", index=False)
    print(f"  setups: {len(g)}")

    print("\n[Д] Fractal-4h sweep + new OB-1h")
    d = detect_connection_D(df_4h, df_1h, df_1m, rr_target=2.0)
    pd.DataFrame(d).to_csv(OUT_DIR / "connection_D.csv", index=False)
    print(f"  setups: {len(d)}")

    print("\n=== СВОДКА ===")
    summary_rows = []
    for name, setups in [("A", a), ("B", b), ("V", v), ("G", g), ("D", d)]:
        if not setups:
            continue
        df = pd.DataFrame(setups)
        closed = df[df["outcome"].isin(["win", "loss"])]
        n = len(df)
        years = (df_1d.index[-1] - df_1d.index[0]).days / 365
        n_per_year = n / years if years else 0
        if len(closed):
            wr = (closed["outcome"] == "win").mean() * 100
            total_R = closed["R"].sum()
            mean_R = closed["R"].mean()
        else:
            wr = total_R = mean_R = 0
        nf = (df["outcome"] == "not_filled").sum()
        op = (df["outcome"] == "open").sum()
        summary_rows.append({
            "connection": name,
            "n_total": n,
            "n_per_year": round(n_per_year, 1),
            "n_per_2weeks": round(n_per_year / 26, 2),
            "n_closed": len(closed),
            "n_not_filled": int(nf),
            "n_open": int(op),
            "WR%": round(wr, 1),
            "total_R": round(total_R, 1),
            "mean_R": round(mean_R, 3),
            "rr_target": setups[0].get("rr_target"),
        })
    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(OUT_DIR / "connections_summary.csv", index=False)
    print(summary_df.to_string(index=False))


if __name__ == "__main__":
    main()
