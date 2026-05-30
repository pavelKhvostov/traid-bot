"""Проверка условия для предсказания HH-фрактала на 12h BTC:

  condition (SHORT-разворот): close(i) < high(i-1)

HH-фрактал (canon, строгий >): high(i) > high(j) для j ∈ {i-2, i-1, i+1, i+2}.

Считаем precision = P(HH | cond) и lift над baseline P(HH).

Использует кеш 15m BTC из find_signal_candle.py; 12h composeется с origin=epoch.

Запуск: .venv/bin/python research/vic_vadim/predict_hh_12h.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CACHE_15M = ROOT / "data" / "BTCUSDT_15m_vic_vadim.csv"


def load_15m() -> pd.DataFrame:
    df = pd.read_csv(CACHE_15M, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df


def compose(df_15m: pd.DataFrame, freq: str) -> pd.DataFrame:
    return df_15m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])


def main() -> None:
    df_15m = load_15m()
    df = compose(df_15m, "12h").reset_index(drop=False).rename(columns={"open_time": "ts"})
    n = len(df)
    print(f"12h BTC: {n} баров с {df['ts'].iloc[0]} до {df['ts'].iloc[-1]}")

    # Окно валидных индексов: нужно i±2
    valid = np.arange(2, n - 2)
    high = df["high"].to_numpy()
    close = df["close"].to_numpy()

    low = df["low"].to_numpy()

    # HH-фрактал: high(i) > high(j) для j ∈ {i-2, i-1, i+1, i+2}, строгий >
    hh = (
        (high[valid] > high[valid - 2])
        & (high[valid] > high[valid - 1])
        & (high[valid] > high[valid + 1])
        & (high[valid] > high[valid + 2])
    )
    # LL-фрактал: low(i) < low(j) для j ∈ {i-2, i-1, i+1, i+2}, строгий <
    ll = (
        (low[valid] < low[valid - 2])
        & (low[valid] < low[valid - 1])
        & (low[valid] < low[valid + 1])
        & (low[valid] < low[valid + 2])
    )

    n_total = len(valid)
    n_hh = int(hh.sum())
    n_ll = int(ll.sum())
    print(f"\n=== Базовая статистика фракталов на 12h BTC ===")
    print(f"всего валидных свечей: {n_total}")
    print(f"HH-фракталов: {n_hh}  P(HH) = {n_hh/n_total*100:.2f}%")
    print(f"LL-фракталов: {n_ll}  P(LL) = {n_ll/n_total*100:.2f}%")
    print(f"оба (HH ∩ LL):  {int((hh & ll).sum())}  (= одна и та же свеча HH и LL — обычно 0)")
    print(f"средняя дистанция между HH: {n_total/max(n_hh,1):.1f} свечей ≈ {n_total/max(n_hh,1)*0.5:.1f} дней")
    print(f"средняя дистанция между LL: {n_total/max(n_ll,1):.1f} свечей ≈ {n_total/max(n_ll,1)*0.5:.1f} дней")

    # Условие пользователя: close(i) < high(i-1)
    cond = close[valid] < high[valid - 1]
    n_cond = int(cond.sum())
    n_hh_and_cond = int((hh & cond).sum())

    print("\n=== Условие: close(i) < high(i-1) (тест на предсказание HH) ===")
    baseline = n_hh / n_total
    coverage = n_cond / n_total
    if n_cond > 0:
        precision = n_hh_and_cond / n_cond
        lift = precision / baseline if baseline > 0 else float("nan")
    else:
        precision = float("nan")
        lift = float("nan")
    recall = n_hh_and_cond / n_hh if n_hh > 0 else float("nan")

    print(f"\nвалидных свечей (с i±2): {n_total}")
    print(f"HH-фракталов:            {n_hh}  (P(HH) = {baseline*100:.2f}%, baseline)")
    print(f"свечей с cond:           {n_cond}  (coverage = {coverage*100:.1f}%)")
    print(f"HH ∩ cond:               {n_hh_and_cond}")
    print()
    print(f"precision = P(HH | close(i) < high(i-1)) = {precision*100:.2f}%")
    print(f"lift над baseline                        = ×{lift:.2f}  ({(precision-baseline)*100:+.2f} pp)")
    print(f"recall    = P(cond | HH)                 = {recall*100:.2f}%")

    # Sanity-checks
    print("\n--- sanity ---")
    print(f"  доля красных (close<open):      {(df['close'] < df['open']).mean()*100:.1f}%")
    print(f"  доля close(i)>=high(i-1):       {(1-coverage)*100:.1f}%")
    print(f"  доля HH среди {n_total} баров:  {baseline*100:.2f}%")

    # Последние HH и LL — показать 5 свечей (i-2..i+2)
    hh_idx = valid[hh]
    ll_idx = valid[ll]

    def show_fractal(label: str, center: int) -> None:
        print(f"\n--- последний {label} ---")
        # +3h конверсия для отображения (правило проекта: чат в UTC+3, данные в UTC)
        center_ts = df["ts"].iloc[center] + pd.Timedelta(hours=3)
        print(f"центр: {center_ts.strftime('%Y-%m-%d %H:%M UTC+3')} (12h bar)")
        for k in range(center - 2, center + 3):
            tag = "  ← центр" if k == center else ""
            ts_local = df["ts"].iloc[k] + pd.Timedelta(hours=3)
            o, h, l, c = df["open"].iloc[k], df["high"].iloc[k], df["low"].iloc[k], df["close"].iloc[k]
            print(
                f"  i{k - center:+d}  {ts_local.strftime('%Y-%m-%d %H:%M')}  "
                f"o={o:>9.2f} h={h:>9.2f} l={l:>9.2f} c={c:>9.2f}{tag}",
            )

    if len(hh_idx) > 0:
        show_fractal("HH-фрактал (SHORT-вершина)", int(hh_idx[-1]))
    if len(ll_idx) > 0:
        show_fractal("LL-фрактал (LONG-дно)", int(ll_idx[-1]))


if __name__ == "__main__":
    main()
