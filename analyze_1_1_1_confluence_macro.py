"""Confluence-анализ Strategy 1.1.1 BTC vs макро-направление TOTALES и USDT.D.

Обходим ограничение TV (нет глубоких 15m для CRYPTOCAP-тикеров) — используем
daily направление на момент сигнала.

Для каждого BTC-сигнала:
  1. Берём signal_time как момент (= entry FVG c2 close).
  2. Считаем daily-momentum TOTALES и USDT.D на N дней до сигнала:
     dir = sign(close(t) - close(t-N))
  3. BTC LONG sync с TOTALES: TOTALES_dir = +1 (bullish)
  4. BTC LONG sync с USDT.D mirror: USDT_D_dir = -1 (bearish)
  5. Подсчитываем WR/PnL BTC-сигналов в каждой подгруппе.

N = 1, 3, 7 дней — несколько горизонтов.
"""
from __future__ import annotations

import pandas as pd

from backtest_strategy_1_1_1 import simulate_outcome
from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals

DAYS_BACK = 1095
LOOKBACK_DAYS_LIST = [1, 3, 7]


def _empty_ohlc() -> pd.DataFrame:
    df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df.index = pd.DatetimeIndex([], tz="UTC", name="open_time")
    return df


def load_btc_signals_from_csv() -> list[dict]:
    """Загружаем deduped 129 сигналов из готового бэктест-CSV (RR=1.0)."""
    from pathlib import Path
    csv = Path("signals/strategy_1_1_1_3y_RR1.csv")
    df = pd.read_csv(csv)
    # fvg_time в UTC+3 формате 'YYYY-MM-DD HH:MM' — это момент сигнала.
    # Конвертим обратно в UTC: minus 3h.
    out = []
    for _, row in df.iterrows():
        t_utc3 = pd.to_datetime(row["fvg_time"])
        t_utc = (t_utc3 - pd.Timedelta(hours=3)).tz_localize("UTC")
        out.append({
            "signal_time": t_utc,
            "direction": row["direction"],
            "outcome": row["outcome"],
        })
    return out


def daily_momentum_at(df_1d: pd.DataFrame, ts: pd.Timestamp, lookback_days: int) -> int:
    """Возвращает sign(close(ts_day) - close(ts_day - lookback_days)).

    +1 bullish, -1 bearish, 0 если данных не хватает / равно.
    """
    if df_1d.empty:
        return 0
    # День сигнала = floor(ts) до даты
    day = ts.normalize()
    prev_day = day - pd.Timedelta(days=lookback_days)
    # Ближайшая 1d свеча с index <= day
    close_now = df_1d[df_1d.index <= day]
    close_prev = df_1d[df_1d.index <= prev_day]
    if close_now.empty or close_prev.empty:
        return 0
    delta = float(close_now["close"].iloc[-1]) - float(close_prev["close"].iloc[-1])
    if delta > 0:
        return 1
    if delta < 0:
        return -1
    return 0


def stats(rows: list[dict]) -> dict:
    closed = [r for r in rows if r["outcome"] in ("win", "loss")]
    n = len(rows)
    nc = len(closed)
    wins = sum(1 for r in closed if r["outcome"] == "win")
    losses = nc - wins
    wr = wins / nc * 100 if nc else 0.0
    return {
        "total": n, "closed": nc, "wins": wins, "losses": losses,
        "wr_pct": round(wr, 1),
        "pnl_rr1": round(wins - losses, 1),
        "pnl_rr2.2": round(wins * 2.2 - losses, 1),
    }


def main() -> None:
    print(f"[INFO] окно: {DAYS_BACK} дней, lookback days: {LOOKBACK_DAYS_LIST}")
    print()

    print("[INFO] BTC signals from signals/strategy_1_1_1_3y_RR1.csv (deduped)")
    btc = load_btc_signals_from_csv()
    print(f"  total: {len(btc)}")

    df_totales_1d = load_df("TOTALES", "1d")
    df_usdtd_1d = load_df("USDT_D", "1d")
    print(f"  TOTALES 1d range: {df_totales_1d.index[0]} -> {df_totales_1d.index[-1]}")
    print(f"  USDT_D 1d range: {df_usdtd_1d.index[0]} -> {df_usdtd_1d.index[-1]}")
    print()

    print("=" * 90)
    print("Baseline — все BTC сигналы")
    print("=" * 90)
    print(stats(btc))

    for N in LOOKBACK_DAYS_LIST:
        print()
        print("=" * 90)
        print(f"Lookback {N}d — direction = sign(close(t) - close(t-{N}d))")
        print("=" * 90)

        # Маркируем
        for r in btc:
            tot_dir = daily_momentum_at(df_totales_1d, r["signal_time"], N)
            usd_dir = daily_momentum_at(df_usdtd_1d, r["signal_time"], N)
            btc_sign = 1 if r["direction"] == "LONG" else -1
            r["totales_match"] = (tot_dir == btc_sign)
            r["usdtd_mirror_match"] = (usd_dir == -btc_sign)  # mirror

        only_totales = [r for r in btc if r["totales_match"] and not r["usdtd_mirror_match"]]
        only_usdtd = [r for r in btc if r["usdtd_mirror_match"] and not r["totales_match"]]
        triple = [r for r in btc if r["totales_match"] and r["usdtd_mirror_match"]]
        any_sync = [r for r in btc if r["totales_match"] or r["usdtd_mirror_match"]]
        no_sync = [r for r in btc if not r["totales_match"] and not r["usdtd_mirror_match"]]

        rows = [
            ("BTC + TOTALES match (only)",  only_totales),
            ("BTC + USDT.D mirror (only)",  only_usdtd),
            ("Triple confluence",            triple),
            ("Any sync",                     any_sync),
            ("No sync (BTC vs flat/wrong)",  no_sync),
        ]
        for label, group in rows:
            st = stats(group)
            pct_of_total = len(group) / len(btc) * 100 if btc else 0
            print(f"  {label:32}: n={st['total']:3d} ({pct_of_total:4.1f}%)  "
                  f"closed={st['closed']:3d}  WR={st['wr_pct']:5.1f}%  "
                  f"PnL@1={st['pnl_rr1']:+5.1f}R  PnL@2.2={st['pnl_rr2.2']:+5.1f}R")


if __name__ == "__main__":
    main()
