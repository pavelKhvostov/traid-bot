"""VIC BOS backtest (отдельная стратегия, не VIC_EVOT).

Логика:
  1. Закрылся день D-1, считаем maxV(D-1) (как в VIC_EVOT).
  2. Направление по close(D-1) vs maxV: LONG если close>maxV, SHORT если <.
  3. В дне D на 1m находим первое пересечение уровня maxV
     (LONG: low<=maxV; SHORT: high>=maxV).
  4. После cross на 3m ищем break of structure (BOS) в нужную сторону:
       LONG-BOS: первый swing_low (фрактал 2-2) → потом swing_high → 3m close
                 выше swing_high. Это слом шортовой структуры на лонговую.
       SHORT-BOS: первый swing_high → потом swing_low → 3m close ниже
                  swing_low. Слом лонговой на шортовую.
  5. Entry = close BOS-свечи. SL = swing extremity на стороне риска.
     TP = entry ± risk × rr_ratio.

Анти-lookahead: 1m симуляция SL/TP начинается с конца BOS-свечи (= open
следующей 3m). Cross определяется только на 1m свечах внутри дня D.
"""
from __future__ import annotations


# --- repo-root injection (Phase 3 refactor) ---
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    if _ROOT.parent == _ROOT:
        raise RuntimeError("repo root not found")
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
# --- end repo-root injection ---

import time
from pathlib import Path

import numpy as np
import pandas as pd

from config import VIC_LTF_MINUTES
from data_manager import (
    fetch_klines_range,
    load_df,
    save_df,
    tf_to_ms,
    update_df_incrementally,
)
from vic_levels import calculate_vic_d

# ---------------- Параметры ----------------

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
FRACTAL_N = 2     # pivot 2-2 для swing-фрактала на 3m
BOS_TIMEOUT_H = 6  # макс. время от cross до BOS (часы)
RR_RUNS = [
    (1.0, "signals/vic_bos_3y_RR1.csv"),
    (2.2, "signals/vic_bos_3y_RR2.2.csv"),
]


# ---------------- Подготовка данных ----------------

def ensure_history(symbol: str, tf: str, lookback_days: int) -> None:
    df = load_df(symbol, tf)
    now_ms = int(time.time() * 1000)
    step = tf_to_ms(tf)
    end_ms = (now_ms // step) * step
    horizon_start_ms = end_ms - lookback_days * 24 * 60 * 60 * 1000

    pieces: list[pd.DataFrame] = []
    if df.empty:
        full = fetch_klines_range(symbol, tf, horizon_start_ms, end_ms)
        if not full.empty:
            pieces.append(full)
    else:
        first_ms = int(df.index[0].timestamp() * 1000)
        last_ms = int(df.index[-1].timestamp() * 1000)
        if first_ms > horizon_start_ms:
            back = fetch_klines_range(symbol, tf, horizon_start_ms, first_ms)
            if not back.empty:
                pieces.append(back)
        pieces.append(df)
        if last_ms + step < end_ms:
            forward = fetch_klines_range(symbol, tf, last_ms + step, end_ms)
            if not forward.empty:
                pieces.append(forward)

    if not pieces:
        return
    fresh = pd.concat(pieces).sort_index()
    fresh = fresh[~fresh.index.duplicated(keep="last")]
    last_open_ms = int(fresh.index[-1].timestamp() * 1000)
    if last_open_ms + step > now_ms:
        fresh = fresh.iloc[:-1]
    save_df(fresh, symbol, tf)


def resample_3m(df_1m: pd.DataFrame) -> pd.DataFrame:
    df_3m = df_1m.resample(
        "3min", origin="epoch", label="left", closed="left"
    ).agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna(subset=["close"])
    return df_3m


# ---------------- Структурный анализ ----------------

def is_swing_low(highs: np.ndarray, lows: np.ndarray, idx: int, n: int) -> bool:
    """Фрактал-low: low(idx) < n левых соседей (strict) и <= n правых (с хотя бы
    одним строго меньшим). Это позволяет «плато» считаться фракталом — берём
    первый бар плато."""
    if idx - n < 0 or idx + n >= len(lows):
        return False
    lo = lows[idx]
    has_strict_right = False
    for k in range(1, n + 1):
        if not (lo < lows[idx - k]):
            return False
        if not (lo <= lows[idx + k]):
            return False
        if lo < lows[idx + k]:
            has_strict_right = True
    return has_strict_right


def is_swing_high(highs: np.ndarray, lows: np.ndarray, idx: int, n: int) -> bool:
    """Фрактал-high: high(idx) > n левых соседей (strict) и >= n правых (с хотя бы
    одним строго больше). Первый бар плато считается фракталом."""
    if idx - n < 0 or idx + n >= len(highs):
        return False
    hi = highs[idx]
    has_strict_right = False
    for k in range(1, n + 1):
        if not (hi > highs[idx - k]):
            return False
        if not (hi >= highs[idx + k]):
            return False
        if hi > highs[idx + k]:
            has_strict_right = True
    return has_strict_right


def _add_to_alt(f: dict, alt_list: list) -> None:
    """Добавить фрактал в чередующийся список. Если последний того же типа,
    заменяем на новый (берём самый последний по времени, не более экстремальный)."""
    if not alt_list:
        alt_list.append(f)
        return
    last = alt_list[-1]
    if f["type"] == last["type"]:
        alt_list[-1] = f
    else:
        alt_list.append(f)


def find_bos(
    df_3m: pd.DataFrame,
    direction: str,
    cross_time: pd.Timestamp,
    fractal_n: int = FRACTAL_N,
    timeout_hours: int = BOS_TIMEOUT_H,
) -> dict | None:
    """Поиск BOS по схеме «первый фрактал после cross + предыдущий».

    LONG: ждём первый фрактал после cross_time с time >= 3m-бара содержащего
      cross. Он должен быть FL (sweep-low). Предыдущий фрактал в хронологии
      должен быть FH — это target. Сигнал = 3m close > target.
    SHORT: симметрично — первый фрактал FH (sweep-high), предыдущий FL = target,
      close < target.

    Если типы не совпали (например LONG и предыдущий не FH) — сетап невалидный.
    """
    end_time = cross_time + pd.Timedelta(hours=timeout_hours)
    df_window = df_3m[df_3m.index < end_time]
    if len(df_window) < 2 * fractal_n + 1:
        return None

    highs = df_window["high"].values
    lows = df_window["low"].values
    closes = df_window["close"].values
    times = df_window.index

    # Floor cross_time к 3m boundary — это бар, содержащий cross.
    cross_3m_floor = pd.Timestamp(cross_time).floor("3min")
    cross_idx = int(times.searchsorted(cross_time))

    # Собираем все фракталы хронологически (без дедупа).
    fractals: list[dict] = []
    for k in range(fractal_n, len(df_window) - fractal_n):
        if is_swing_high(highs, lows, k, fractal_n):
            fractals.append({
                "idx": k, "type": "H", "price": float(highs[k]),
                "time": times[k], "confirm_idx": k + fractal_n,
            })
        if is_swing_low(highs, lows, k, fractal_n):
            fractals.append({
                "idx": k, "type": "L", "price": float(lows[k]),
                "time": times[k], "confirm_idx": k + fractal_n,
            })
    fractals.sort(key=lambda f: (f["time"], 0 if f["type"] == "L" else 1))

    # Первый фрактал с time >= cross_3m_floor.
    first_post_idx: int | None = None
    for i, f in enumerate(fractals):
        if f["time"] >= cross_3m_floor:
            first_post_idx = i
            break
    if first_post_idx is None or first_post_idx == 0:
        return None

    f_post = fractals[first_post_idx]
    f_prev = fractals[first_post_idx - 1]

    # Strict проверка типов.
    if direction == "LONG":
        if f_post["type"] != "L" or f_prev["type"] != "H":
            return None
    else:
        if f_post["type"] != "H" or f_prev["type"] != "L":
            return None

    target_price = f_prev["price"]
    target_time = f_prev["time"]

    # Сканируем close после подтверждения f_post (когда мы реально знаем сетап).
    start_j = f_post["confirm_idx"]

    for j in range(start_j, len(df_window)):
        if direction == "LONG":
            if closes[j] > target_price:
                seg_lows = lows[cross_idx : j + 1]
                sl_idx_loc = int(np.argmin(seg_lows))
                sl_idx = cross_idx + sl_idx_loc
                return {
                    "bos_time": times[j],
                    "bos_close": float(closes[j]),
                    "swing_low_price": float(lows[sl_idx]),
                    "swing_high_price": float(target_price),
                    "swing_low_time": times[sl_idx],
                    "swing_high_time": target_time,
                    "f_post_price": float(f_post["price"]),
                    "f_post_time": f_post["time"].isoformat(),
                    "f_prev_price": float(f_prev["price"]),
                    "f_prev_time": f_prev["time"].isoformat(),
                }
        else:
            if closes[j] < target_price:
                seg_highs = highs[cross_idx : j + 1]
                sh_idx_loc = int(np.argmax(seg_highs))
                sh_idx = cross_idx + sh_idx_loc
                return {
                    "bos_time": times[j],
                    "bos_close": float(closes[j]),
                    "swing_low_price": float(target_price),
                    "swing_high_price": float(highs[sh_idx]),
                    "swing_low_time": target_time,
                    "swing_high_time": times[sh_idx],
                    "f_post_price": float(f_post["price"]),
                    "f_post_time": f_post["time"].isoformat(),
                    "f_prev_price": float(f_prev["price"]),
                    "f_prev_time": f_prev["time"].isoformat(),
                }
    return None


# ---------------- Сбор сигналов ----------------

def find_cross_1m(df_1m_day: pd.DataFrame, vic: float, direction: str) -> pd.Timestamp | None:
    if direction == "LONG":
        mask = df_1m_day["low"] <= vic
    else:
        mask = df_1m_day["high"] >= vic
    if not mask.any():
        return None
    return df_1m_day.index[mask.argmax()]


def collect_signals(
    df_1m: pd.DataFrame, df_3m: pd.DataFrame, df_1d: pd.DataFrame, days_back: int,
) -> list[dict]:
    today = pd.Timestamp.utcnow().normalize()
    if today.tz is None:
        today = today.tz_localize("UTC")
    start = today - pd.Timedelta(days=days_back)

    signals = []
    cur = start
    while cur < today:
        D = cur
        Dm1 = D - pd.Timedelta(days=1)
        next_day = D + pd.Timedelta(days=1)

        vic = calculate_vic_d(df_1m, Dm1, ltf_minutes=VIC_LTF_MINUTES)
        if vic is None:
            cur = next_day
            continue

        df_1d_t = df_1d[df_1d.index < D]
        if df_1d_t.empty:
            cur = next_day
            continue
        close_dm1 = float(df_1d_t.iloc[-1]["close"])

        if close_dm1 > vic:
            direction = "LONG"
        elif close_dm1 < vic:
            direction = "SHORT"
        else:
            cur = next_day
            continue

        df_1m_day = df_1m[(df_1m.index >= D) & (df_1m.index < next_day)]
        if df_1m_day.empty:
            cur = next_day
            continue

        cross_time = find_cross_1m(df_1m_day, vic, direction)
        if cross_time is None:
            cur = next_day
            continue

        # find_bos сам берёт нужное окно (фракталы pre-cross + post-cross
        # до cross+timeout) и проверяет BOS только на close после cross.
        bos = find_bos(df_3m, direction, cross_time)
        if bos is None:
            cur = next_day
            continue

        signals.append({
            "date": D.strftime("%Y-%m-%d"),
            "direction": direction,
            "vic_level": vic,
            "close_dm1": close_dm1,
            "cross_time": cross_time,
            **bos,
        })
        cur = next_day
    return signals


# ---------------- Симуляция ----------------

def simulate(sig: dict, df_1m: pd.DataFrame, rr_ratio: float) -> dict:
    direction = sig["direction"]
    bos_time = sig["bos_time"]
    entry = sig["bos_close"]

    # анти-lookahead: с close BOS = open следующей 3m
    sim_start = bos_time + pd.Timedelta(minutes=3)

    if direction == "LONG":
        sl = sig["swing_low_price"]
        risk = entry - sl
    else:
        sl = sig["swing_high_price"]
        risk = sl - entry

    if risk <= 0:
        return {**_base_row(sig), "entry_price": entry, "sl": sl, "tp": None,
                "outcome": "invalid_risk", "exit_time": "", "exit_price": "",
                "hit_type": "invalid_risk", "mfe_pct": 0, "mae_pct": 0}

    if direction == "LONG":
        tp = entry + risk * rr_ratio
    else:
        tp = entry - risk * rr_ratio

    sim = df_1m[df_1m.index >= sim_start]
    outcome = "open"
    exit_time = None
    exit_price = None
    hit_type = None
    mfe = 0.0
    mae = 0.0

    for ts, c in sim.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction == "LONG":
            mfe = max(mfe, h - entry)
            mae = max(mae, entry - l)
            if l <= sl:
                outcome, exit_time, exit_price, hit_type = "loss", ts, sl, "sl"
                break
            if h >= tp:
                outcome, exit_time, exit_price, hit_type = "win", ts, tp, "tp"
                break
        else:
            mfe = max(mfe, entry - l)
            mae = max(mae, h - entry)
            if h >= sl:
                outcome, exit_time, exit_price, hit_type = "loss", ts, sl, "sl"
                break
            if l <= tp:
                outcome, exit_time, exit_price, hit_type = "win", ts, tp, "tp"
                break

    return {
        **_base_row(sig),
        "entry_price": entry,
        "sl": sl,
        "tp": tp,
        "outcome": outcome,
        "exit_time": exit_time.isoformat() if exit_time else "",
        "exit_price": exit_price if exit_price is not None else "",
        "hit_type": hit_type or "open",
        "mfe_pct": round(mfe / entry * 100, 4),
        "mae_pct": round(mae / entry * 100, 4),
    }


def _base_row(sig: dict) -> dict:
    return {
        "date": sig["date"],
        "direction": sig["direction"],
        "vic_level": float(sig["vic_level"]),
        "close_dm1": float(sig["close_dm1"]),
        "cross_time": sig["cross_time"].isoformat(),
        "bos_time": sig["bos_time"].isoformat(),
        "swing_low_price": sig["swing_low_price"],
        "swing_high_price": sig["swing_high_price"],
        "swing_low_time": sig["swing_low_time"].isoformat(),
        "swing_high_time": sig["swing_high_time"].isoformat(),
    }


# ---------------- Main ----------------

def main():
    print(f"[INFO] символ {SYMBOL}, окно {DAYS_BACK}d, FRACTAL_N={FRACTAL_N}, BOS_TIMEOUT={BOS_TIMEOUT_H}h")
    print()
    print("[INFO] подготовка данных")
    update_df_incrementally(SYMBOL, "1d")
    ensure_history(SYMBOL, "1m", DAYS_BACK + 2)

    df_1m = load_df(SYMBOL, "1m")
    df_1d = load_df(SYMBOL, "1d")
    print(f"  1m={len(df_1m)} 1d={len(df_1d)}")

    print("[INFO] resample 1m -> 3m")
    df_3m = resample_3m(df_1m)
    print(f"  3m={len(df_3m)}")

    print("[INFO] сбор BOS-сигналов")
    sigs = collect_signals(df_1m, df_3m, df_1d, DAYS_BACK)
    print(f"  signals: {len(sigs)}")

    for rr_ratio, out_path in RR_RUNS:
        rows = [simulate(s, df_1m, rr_ratio) for s in sigs]
        df = pd.DataFrame(rows)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False)

        closed = df[df["outcome"].isin(["win", "loss"])]
        opens = (df["outcome"] == "open").sum()
        invalid = (df["outcome"] == "invalid_risk").sum()
        W = int((closed["outcome"] == "win").sum())
        L = int((closed["outcome"] == "loss").sum())
        wr = W / (W + L) * 100 if (W + L) else 0
        pnl = W * rr_ratio - L

        print()
        print("=" * 60)
        print(f"RR={rr_ratio}  -> {out_path}")
        print("=" * 60)
        print(f"  total={len(df)} closed={W+L} open={opens} invalid={invalid}")
        print(f"  W={W} L={L} WR={wr:.1f}% PnL={pnl:+.1f}R")

        if not closed.empty:
            closed_y = closed.copy()
            closed_y["year"] = pd.to_datetime(closed_y["date"]).dt.year
            for y in sorted(closed_y["year"].unique()):
                sub = closed_y[closed_y["year"] == y]
                Wy = int((sub["outcome"] == "win").sum())
                Ly = int((sub["outcome"] == "loss").sum())
                wry = Wy / (Wy + Ly) * 100 if (Wy + Ly) else 0
                pnly = Wy * rr_ratio - Ly
                print(f"  {y}: n={Wy+Ly} WR={wry:.1f}% PnL={pnly:+.1f}R")


if __name__ == "__main__":
    main()
