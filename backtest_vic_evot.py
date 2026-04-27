"""Бэктест VIC_EVOT: проход по истории + симуляция SL/TP/EOD на 1m свечах.

Никакого look-ahead: detect_vic_evot получает df_15m обрезанный по
candle.open_time и df_1d обрезанный по D (только закрытые дни)."""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from config import VIC_LTF_MINUTES
from data_manager import (
    fetch_klines_range,
    load_df,
    save_df,
    tf_to_ms,
    update_df_incrementally,
)
from strategies.vic_evot import detect_vic_evot
from vic_levels import calculate_vic_d

# ---------------- Параметры ----------------

DAYS_BACK = 90
SYMBOLS = ["BTCUSDT"]
RR_RATIO = 1.0
CLOSE_EOD = True
OUTPUT_PATH = Path("signals/vic_evot_backtest_RR1.csv")


# ---------------- Подготовка данных ----------------

def ensure_history(symbol: str, tf: str, lookback_days: int) -> None:
    """Гарантировать что в CSV есть свечи за последние lookback_days дней.

    Если данных не хватает (CSV пуст / есть но не покрывает горизонт) —
    фетчит недостающее (backfill, forward fill, или полный fetch)."""
    df = load_df(symbol, tf)
    now_ms = int(time.time() * 1000)
    step = tf_to_ms(tf)
    end_ms = (now_ms // step) * step
    horizon_start_ms = end_ms - lookback_days * 24 * 60 * 60 * 1000

    pieces: list[pd.DataFrame] = []

    if df.empty:
        n_days = lookback_days
        print(f"  [DATA] {symbol} {tf}: full fetch ~{n_days}d")
        full = fetch_klines_range(symbol, tf, horizon_start_ms, end_ms)
        if not full.empty:
            pieces.append(full)
    else:
        first_ms = int(df.index[0].timestamp() * 1000)
        last_ms = int(df.index[-1].timestamp() * 1000)

        if first_ms > horizon_start_ms:
            n_missing = (first_ms - horizon_start_ms) / (24 * 60 * 60 * 1000)
            print(f"  [DATA] {symbol} {tf}: backfill {n_missing:.1f}d")
            back = fetch_klines_range(symbol, tf, horizon_start_ms, first_ms)
            if not back.empty:
                pieces.append(back)

        pieces.append(df)

        if last_ms + step < end_ms:
            n_missing = (end_ms - last_ms) / (24 * 60 * 60 * 1000)
            print(f"  [DATA] {symbol} {tf}: forward {n_missing:.2f}d")
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


# ---------------- Сбор сигналов ----------------

def _utc_today_floor() -> pd.Timestamp:
    today = pd.Timestamp.utcnow().normalize()
    if today.tz is None:
        today = today.tz_localize("UTC")
    return today


def collect_signals(
    symbol: str,
    df_1m: pd.DataFrame,
    df_15m: pd.DataFrame,
    df_1d: pd.DataFrame,
    days_back: int,
):
    """Прогон detect_vic_evot по каждой 15m-свече за окно с no-look-ahead.

    Возвращает list[Signal]."""
    today = _utc_today_floor()
    start_day = today - pd.Timedelta(days=days_back)

    signals = []
    vic_cache: dict[pd.Timestamp, float | None] = {}

    cur_day = start_day
    while cur_day < today:
        D = cur_day
        D_minus_1 = D - pd.Timedelta(days=1)

        if D_minus_1 not in vic_cache:
            vic_cache[D_minus_1] = calculate_vic_d(
                df_1m, D_minus_1, ltf_minutes=VIC_LTF_MINUTES,
            )
        vic_level = vic_cache[D_minus_1]

        if vic_level is None:
            cur_day += pd.Timedelta(days=1)
            continue

        next_day = D + pd.Timedelta(days=1)
        df_15m_day = df_15m[(df_15m.index >= D) & (df_15m.index < next_day)]
        if df_15m_day.empty:
            cur_day += pd.Timedelta(days=1)
            continue

        # df_1d должен содержать ТОЛЬКО закрытые дни < D (no look-ahead).
        df_1d_truncated = df_1d[df_1d.index < D]
        if df_1d_truncated.empty:
            cur_day += pd.Timedelta(days=1)
            continue

        # Все 15m в дне D от i=0. Slice по open_time свечи (включает свечи
        # предыдущего дня для фрактал-контекста при cross-midnight). detect_vic_evot
        # сам разберётся через day_start.
        for i in range(len(df_15m_day)):
            candle_open_time = df_15m_day.index[i]
            df_15m_truncated = df_15m[df_15m.index <= candle_open_time]
            if len(df_15m_truncated) < 5:
                continue

            sig = detect_vic_evot(
                df_15m_truncated, df_1d_truncated, vic_level, symbol, candle_open_time,
            )
            if sig is not None:
                signals.append(sig)
                break  # один сигнал в день D, последующие 15m в этот день не сканируем

        cur_day += pd.Timedelta(days=1)

    return signals


# ---------------- Симуляция исхода ----------------

def simulate_outcome(sig, df_1m: pd.DataFrame, df_15m: pd.DataFrame, rr_ratio: float, close_eod: bool) -> dict:
    """SL/TP/EOD-симуляция через 1m свечи. SL имеет приоритет внутри одной 1m
    свечи (conservative: если low<=SL и high>=TP в одной свече — считаем
    что SL пробило первым)."""
    fractal_time = pd.to_datetime(sig.meta["fractal_time"], utc=True)
    fractal_candle = df_15m.loc[fractal_time]

    entry = float(sig.price)
    entry_time = sig.confirm_time

    if sig.direction == "LONG":
        sl = float(fractal_candle["low"])
        tp = entry + (entry - sl) * rr_ratio
    else:
        sl = float(fractal_candle["high"])
        tp = entry - (sl - entry) * rr_ratio

    entry_day = entry_time.normalize()
    eod_time = entry_day + pd.Timedelta(days=1)

    sim_window = df_1m[(df_1m.index >= entry_time) & (df_1m.index < eod_time)]

    outcome = "open"
    exit_time = None
    exit_price = None
    hit_type = None
    mfe = 0.0
    mae = 0.0

    for ts, candle in sim_window.iterrows():
        high = float(candle["high"])
        low = float(candle["low"])

        if sig.direction == "LONG":
            mfe = max(mfe, high - entry)
            mae = max(mae, entry - low)
            if low <= sl:
                outcome, exit_time, exit_price, hit_type = "loss", ts, sl, "sl"
                break
            if high >= tp:
                outcome, exit_time, exit_price, hit_type = "win", ts, tp, "tp"
                break
        else:
            mfe = max(mfe, entry - low)
            mae = max(mae, high - entry)
            if high >= sl:
                outcome, exit_time, exit_price, hit_type = "loss", ts, sl, "sl"
                break
            if low <= tp:
                outcome, exit_time, exit_price, hit_type = "win", ts, tp, "tp"
                break

    if outcome == "open" and close_eod and not sim_window.empty:
        last_ts = sim_window.index[-1]
        last_close = float(sim_window.iloc[-1]["close"])
        exit_time = last_ts
        exit_price = last_close
        hit_type = "eod"
        if sig.direction == "LONG":
            outcome = "win" if last_close > entry else "loss"
        else:
            outcome = "win" if last_close < entry else "loss"

    return {
        "date": entry_day.strftime("%Y-%m-%d"),
        "symbol": sig.symbol,
        "direction": sig.direction,
        "vic_level": float(sig.level.price),
        "entry_time": entry_time.isoformat(),
        "entry_price": entry,
        "sl": sl,
        "tp": tp,
        "fractal_time": fractal_time.isoformat(),
        "outcome": outcome,
        "exit_time": exit_time.isoformat() if exit_time is not None else "",
        "exit_price": exit_price if exit_price is not None else "",
        "mfe_pct": round((mfe / entry) * 100, 4),
        "mae_pct": round((mae / entry) * 100, 4),
        "hit_type": hit_type or "open",
    }


# ---------------- Сводная статистика ----------------

def print_stats(df: pd.DataFrame, label: str) -> None:
    total = len(df)
    if total == 0:
        print(f"--- {label}: 0 сигналов ---")
        return
    wins = int((df["outcome"] == "win").sum())
    losses = int((df["outcome"] == "loss").sum())
    win_rate = wins / total * 100

    tp_hits = int((df["hit_type"] == "tp").sum())
    sl_hits = int((df["hit_type"] == "sl").sum())
    eod_hits = int((df["hit_type"] == "eod").sum())

    print(f"--- {label} ---")
    print(f"  total={total}  wins={wins}  losses={losses}  win_rate={win_rate:.1f}%")
    print(f"  hits: tp={tp_hits}  sl={sl_hits}  eod={eod_hits}")
    print(
        f"  MFE %: mean={df['mfe_pct'].mean():.3f}  "
        f"median={df['mfe_pct'].median():.3f}  max={df['mfe_pct'].max():.3f}"
    )
    print(
        f"  MAE %: mean={df['mae_pct'].mean():.3f}  "
        f"median={df['mae_pct'].median():.3f}  max={df['mae_pct'].max():.3f}"
    )


# ---------------- Main ----------------

def main():
    print(f"[INFO] окно: {DAYS_BACK} дней, символы: {SYMBOLS}, RR={RR_RATIO}, CLOSE_EOD={CLOSE_EOD}")
    print()

    print("[INFO] подготовка данных")
    for symbol in SYMBOLS:
        print(f"  {symbol}:")
        # 1d уже инкрементирует от HISTORY_START_DATE — миллисекунды
        update_df_incrementally(symbol, "1d")
        # 15m: запас на день D
        ensure_history(symbol, "15m", DAYS_BACK + 1)
        # 1m: запас на maxV(D-1) для самого раннего D
        ensure_history(symbol, "1m", DAYS_BACK + 2)

    print()
    print("[INFO] сбор сигналов")
    all_rows = []
    for symbol in SYMBOLS:
        df_1m = load_df(symbol, "1m")
        df_15m = load_df(symbol, "15m")
        df_1d = load_df(symbol, "1d")
        if df_1m.empty or df_15m.empty or df_1d.empty:
            print(f"  {symbol}: данные пустые, пропускаем")
            continue

        # Диагностика покрытия
        cov_1m = (df_1m.index[-1] - df_1m.index[0]).days
        cov_15m = (df_15m.index[-1] - df_15m.index[0]).days
        print(f"  {symbol}: 1m покрытие {cov_1m}d, 15m {cov_15m}d, 1d рядов {len(df_1d)}")
        if cov_1m < DAYS_BACK:
            print(f"  [WARN] {symbol}: 1m покрытие {cov_1m}d < {DAYS_BACK}d")

        signals = collect_signals(symbol, df_1m, df_15m, df_1d, DAYS_BACK)
        print(f"  {symbol}: найдено {len(signals)} сигналов, симулируем исход")

        for sig in signals:
            row = simulate_outcome(sig, df_1m, df_15m, RR_RATIO, CLOSE_EOD)
            all_rows.append(row)

    if not all_rows:
        print()
        print("[WARN] ни одного сигнала за период")
        return

    df_out = pd.DataFrame(all_rows)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(OUTPUT_PATH, index=False)
    print()
    print(f"[INFO] записано в {OUTPUT_PATH}: {len(all_rows)} строк")

    print()
    print("=" * 60)
    print(f"СВОДКА  RR={RR_RATIO}  CLOSE_EOD={CLOSE_EOD}  окно={DAYS_BACK}d")
    print("=" * 60)
    print_stats(df_out, "Все символы")
    print()
    for symbol in SYMBOLS:
        sub = df_out[df_out["symbol"] == symbol]
        print_stats(sub, symbol)
        print()
    print(f"Сигналов в день (всего): {len(df_out) / DAYS_BACK:.2f}")


if __name__ == "__main__":
    main()
