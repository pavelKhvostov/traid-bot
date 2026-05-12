"""Перевод Pine-индикатора 'Custom RSI - ASVK' в Python + рисунок на 1h BTC.

Воспроизводит элементы:
  - adjusted_rsi (ema_3) — синяя линия
  - current_value_above / current_value_below — динамические уровни OB/OS
  - upper_band / lower_band — Гауссов канал (NWE)
  - заливки: yellow / red (overbought) и yellow / green (oversold)
  - дивергенции: regular bull, hidden bull, regular bear, hidden bear
  - структурные треугольники: смена EMA50 локальных min/max ema_3

Pine-функции реализованы с нуля (правило проекта: без TA-Lib).
RSI = Wilder's smoothing (alpha=1/period). EMA = pandas ewm(span, adjust=False).
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

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from data_manager import load_df

SYMBOL = "BTCUSDT"
TF = "1h"
PLOT_BARS = 500          # сколько последних баров рисуем
HISTORY_BARS = 1600      # сколько баров грузим (для NWE lookback=499 + запас)

# Pine inputs
RSI_PERIOD = 14
EMA_PERIOD = 5
EMA_PERIOD_2 = 5
EMA_COEF_PERIOD = 5
BARS_TO_LOOK_BACK = 200
NWE_BAR = 499
NWE_BANDWIDTH = 8
NWE_MULTIPLIER = 2
LB_R = 2
LB_L = 3
RANGE_LOWER = 4
RANGE_UPPER = 100
LOCAL_EMA_LEN = 50


# --- Indicator math ---

def rsi_wilder(close: pd.Series, period: int) -> pd.Series:
    """Pine ta.rsi: Wilder's smoothing (alpha=1/period)."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def ema(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(span=period, adjust=False).mean()


def adjusted_rsi(close: pd.Series) -> pd.Series:
    """Pine: ema_3 — финальная синяя линия."""
    rsi = rsi_wilder(close, RSI_PERIOD)
    ema_for_coef = ema(rsi, EMA_COEF_PERIOD)
    coef = pd.Series(np.where(rsi >= 50, 1.2, 0.8), index=rsi.index)
    coefficient = (rsi * coef) / ema_for_coef
    adj = rsi * coefficient
    return ema(adj, EMA_PERIOD)


def dynamic_levels(ema_3: pd.Series, lookback: int = BARS_TO_LOOK_BACK):
    """current_value_above / current_value_below — Pine-логика 1:1.

    Окно: последние `lookback` баров включая текущий.
    """
    n = len(ema_3)
    above = np.full(n, np.nan)
    below = np.full(n, np.nan)
    arr = ema_3.values
    for i in range(lookback - 1, n):
        win = arr[i - lookback + 1: i + 1]
        # above
        mask = win > 50
        z = mask.sum()
        if z > 0:
            x = win[mask].sum()
            y = x / z
            c1 = 100 / y
            c2 = 50 / y
            c3 = c1 - c2
            c4 = (c3 / lookback) * z
            c5 = c4 + c3
            above[i] = c5 * y
        # below
        mask = win < 50
        z = mask.sum()
        if z > 0:
            x = win[mask].sum()
            y = x / z
            c1 = 50 / y
            c2 = 1 / y
            c3 = c1 - c2
            c4 = (c3 / lookback) * z
            c5 = c4 + c3
            below[i] = 100 - (c5 * y)
    return (
        pd.Series(above, index=ema_3.index),
        pd.Series(below, index=ema_3.index),
    )


def nwe_bands(ema_3: pd.Series, bar: int = NWE_BAR,
              bandwidth: float = NWE_BANDWIDTH, multiplier: float = NWE_MULTIPLIER):
    """Гауссов канал (non-repainting): output ± SMA(|ema_3-output|, bar) * mult."""
    weights = np.exp(-(np.arange(bar + 1) ** 2) / (2 * bandwidth ** 2))
    total = weights.sum()
    n = len(ema_3)
    out = np.full(n, np.nan)
    arr = ema_3.values
    for i in range(bar, n):
        # window: ema_3[i], ema_3[i-1], ..., ema_3[i-bar] — соответствует weights[0..bar]
        win = arr[i - bar: i + 1][::-1]
        out[i] = np.dot(win, weights) / total
    out_s = pd.Series(out, index=ema_3.index)
    abs_err = (ema_3 - out_s).abs()
    mae = abs_err.rolling(bar).mean() * multiplier
    return out_s, out_s + mae, out_s - mae


# --- Pivots & divergences ---

def _pivot(s: pd.Series, lb_l: int, lb_r: int, kind: str) -> pd.Series:
    """Pine ta.pivothigh/pivotlow.

    Возвращает Series с pivot value на баре `i` если центр (i - lb_r) — строгий
    локальный экстремум в окне [center - lb_l, center + lb_r].
    """
    n = len(s)
    arr = s.values
    out = np.full(n, np.nan)
    for i in range(lb_l + lb_r, n):
        center = i - lb_r
        v = arr[center]
        ok = True
        for k in range(1, lb_l + 1):
            x = arr[center - k]
            if kind == "low" and x <= v:
                ok = False
                break
            if kind == "high" and x >= v:
                ok = False
                break
        if not ok:
            continue
        for k in range(1, lb_r + 1):
            x = arr[center + k]
            if kind == "low" and x <= v:
                ok = False
                break
            if kind == "high" and x >= v:
                ok = False
                break
        if ok:
            out[i] = v
    return pd.Series(out, index=s.index)


def find_divergences(osc: pd.Series, low: pd.Series, high: pd.Series,
                     lb_l: int = LB_L, lb_r: int = LB_R,
                     range_lower: int = RANGE_LOWER, range_upper: int = RANGE_UPPER):
    """Возвращает 4 списка (idx_center, prev_idx_center, osc_val, price_val).

    idx_center = позиция пивота (i - lb_r), удобно для отрисовки.
    """
    pl = _pivot(osc, lb_l, lb_r, "low")
    ph = _pivot(osc, lb_l, lb_r, "high")
    n = len(osc)

    bull, h_bull, bear, h_bear = [], [], [], []

    last_pl = None  # (i, center, osc_v, price_v)
    for i in range(n):
        if not np.isnan(pl.iloc[i]):
            center = i - lb_r
            cur_osc = osc.iloc[center]
            cur_price = low.iloc[center]
            if last_pl is not None:
                bars_since = i - last_pl[0]
                if range_lower <= bars_since <= range_upper:
                    if cur_price < last_pl[3] and cur_osc > last_pl[2]:
                        bull.append((center, last_pl[1], cur_osc, last_pl[2]))
                    if cur_price > last_pl[3] and cur_osc < last_pl[2]:
                        h_bull.append((center, last_pl[1], cur_osc, last_pl[2]))
            last_pl = (i, center, cur_osc, cur_price)

    last_ph = None
    for i in range(n):
        if not np.isnan(ph.iloc[i]):
            center = i - lb_r
            cur_osc = osc.iloc[center]
            cur_price = high.iloc[center]
            if last_ph is not None:
                bars_since = i - last_ph[0]
                if range_lower <= bars_since <= range_upper:
                    if cur_price > last_ph[3] and cur_osc < last_ph[2]:
                        bear.append((center, last_ph[1], cur_osc, last_ph[2]))
                    if cur_price < last_ph[3] and cur_osc > last_ph[2]:
                        h_bear.append((center, last_ph[1], cur_osc, last_ph[2]))
            last_ph = (i, center, cur_osc, cur_price)

    return bull, h_bull, bear, h_bear


# --- Local extrema EMA (структурные треугольники) ---

def local_extrema_ema(ema_3: pd.Series, length: int = LOCAL_EMA_LEN):
    """Pine findLocalExtrema + EMA(50) на минимумах/максимумах."""
    n = len(ema_3)
    arr = ema_3.values
    is_max = np.full(n, np.nan)
    is_min = np.full(n, np.nan)
    # Pine: src[2] strict extremum vs src[3], src[4], src[1], src[0]; isMax/isMin = src[3]
    for i in range(4, n):
        if (arr[i - 2] > arr[i - 3] and arr[i - 2] > arr[i - 4]
                and arr[i - 2] > arr[i - 1] and arr[i - 2] > arr[i]):
            is_max[i] = arr[i - 3]
        if (arr[i - 2] < arr[i - 3] and arr[i - 2] < arr[i - 4]
                and arr[i - 2] < arr[i - 1] and arr[i - 2] < arr[i]):
            is_min[i] = arr[i - 3]

    # Pine: при первом не-na — присваиваем напрямую; дальше — EMA при не-na, иначе сохраняем.
    ema_l = np.full(n, np.nan)
    ema_h = np.full(n, np.nan)
    alpha = 2 / (length + 1)
    cur_l = np.nan
    cur_h = np.nan
    for i in range(n):
        if not np.isnan(is_min[i]):
            cur_l = is_min[i] if np.isnan(cur_l) else cur_l + alpha * (is_min[i] - cur_l)
        ema_l[i] = cur_l
        if not np.isnan(is_max[i]):
            cur_h = is_max[i] if np.isnan(cur_h) else cur_h + alpha * (is_max[i] - cur_h)
        ema_h[i] = cur_h
    return pd.Series(ema_l, index=ema_3.index), pd.Series(ema_h, index=ema_3.index)


# --- Plot ---

def main():
    print(f"[INFO] загрузка {SYMBOL} {TF}")
    df = load_df(SYMBOL, TF)
    df = df.tail(HISTORY_BARS).copy()
    print(f"  bars loaded: {len(df)} (last {df.index[-1]})")

    print("[INFO] расчёт индикатора")
    ema_3 = adjusted_rsi(df["close"])
    above, below = dynamic_levels(ema_3, BARS_TO_LOOK_BACK)
    nwe_mid, upper, lower = nwe_bands(ema_3, NWE_BAR, NWE_BANDWIDTH, NWE_MULTIPLIER)
    bull, h_bull, bear, h_bear = find_divergences(
        ema_3, df["low"], df["high"], LB_L, LB_R, RANGE_LOWER, RANGE_UPPER,
    )
    ema_l_struct, ema_h_struct = local_extrema_ema(ema_3, LOCAL_EMA_LEN)

    print(f"  divergences: bull={len(bull)} h_bull={len(h_bull)} "
          f"bear={len(bear)} h_bear={len(h_bear)}")

    # Срезаем последние PLOT_BARS для отрисовки
    cut = df.iloc[-PLOT_BARS:]
    idx = cut.index
    ema_3_p = ema_3.loc[idx]
    above_p = above.loc[idx]
    below_p = below.loc[idx]
    upper_p = upper.loc[idx]
    lower_p = lower.loc[idx]
    ema_l_p = ema_l_struct.loc[idx]
    ema_h_p = ema_h_struct.loc[idx]

    # Plot
    plt.style.use("dark_background")
    fig, (ax_p, ax_r) = plt.subplots(
        2, 1, figsize=(16, 10), sharex=True,
        gridspec_kw={"height_ratios": [1.4, 1.6], "hspace": 0.05},
    )
    fig.patch.set_facecolor("#0e1217")
    for ax in (ax_p, ax_r):
        ax.set_facecolor("#0e1217")
        ax.grid(True, color="#202632", linewidth=0.5)
        for spine in ax.spines.values():
            spine.set_color("#3a4252")

    # --- Top: цена + маркеры пивотов ---
    ax_p.plot(idx, cut["close"], color="#d6e0f0", linewidth=1.0, label="BTCUSDT close")
    # маркеры пивотов цены, попавших в окно отрисовки
    plot_start = idx[0]
    cut_pos = {ts: i for i, ts in enumerate(idx)}
    for center, prev_center, _, _ in bull:
        ts = df.index[center]
        if ts in cut_pos:
            ax_p.scatter(ts, df["low"].iloc[center], marker="^",
                         color="#4caf4f", s=40, zorder=5)
    for center, *_ in bear:
        ts = df.index[center]
        if ts in cut_pos:
            ax_p.scatter(ts, df["high"].iloc[center], marker="v",
                         color="#ff5252", s=40, zorder=5)
    ax_p.set_title(f"{SYMBOL} {TF} · ASVK Custom RSI", color="#d6e0f0",
                   fontsize=13, pad=10)
    ax_p.legend(loc="upper left", facecolor="#1a1f29", edgecolor="#3a4252",
                labelcolor="#d6e0f0", fontsize=9)

    # --- Bottom: RSI panel ---
    # Сначала заливки (под линиями)
    yellow = "#ffff00"
    red = "#ff0000"
    green = "#33ff00"

    # OB зона: между upper и above. Yellow — upper>above & ema_3<above. Red — upper>above & ema_3>above.
    cond_yellow_upper = (upper_p > above_p) & (ema_3_p < above_p)
    cond_red_upper = (upper_p > above_p) & (ema_3_p > above_p)
    ax_r.fill_between(idx, upper_p, above_p, where=cond_yellow_upper,
                      color=yellow, alpha=0.20, interpolate=True, linewidth=0)
    ax_r.fill_between(idx, upper_p, above_p, where=cond_red_upper,
                      color=red, alpha=0.30, interpolate=True, linewidth=0)

    # OS зона
    cond_yellow_lower = (lower_p < below_p) & (ema_3_p > below_p)
    cond_green_lower = (lower_p < below_p) & ~(ema_3_p > below_p)
    ax_r.fill_between(idx, lower_p, below_p, where=cond_yellow_lower,
                      color=yellow, alpha=0.20, interpolate=True, linewidth=0)
    ax_r.fill_between(idx, lower_p, below_p, where=cond_green_lower,
                      color=green, alpha=0.20, interpolate=True, linewidth=0)

    # Линии
    purple = "#9c27b0"
    ax_r.plot(idx, upper_p, color=purple, linewidth=1.0, label="NWE Upper")
    ax_r.plot(idx, lower_p, color=purple, linewidth=1.0, label="NWE Lower")
    ax_r.plot(idx, above_p, color="#ff5252", linewidth=1.0, label="Overbought (dyn)")
    ax_r.plot(idx, below_p, color="#4caf4f", linewidth=1.0, label="Oversold (dyn)")
    ax_r.plot(idx, ema_3_p, color="#2769b0", linewidth=1.8, label="Adjusted RSI (ema_3)")
    ax_r.axhline(50, color="#5a6373", linewidth=0.6, linestyle="--")

    # Дивергенции — линии между двумя пивотами + маркеры
    bull_color = "#4caf4f"
    bear_color = "#ff5252"
    h_bull_color = "#4caf4f"
    h_bear_color = "#ff5252"

    def _draw_div(divs, color, label_text, marker_dy, marker_style):
        for center, prev_center, cur_osc, prev_osc in divs:
            ts_cur = df.index[center]
            ts_prev = df.index[prev_center]
            if ts_cur not in cut_pos or ts_prev not in cut_pos:
                continue
            ax_r.plot([ts_prev, ts_cur], [prev_osc, cur_osc],
                      color=color, linewidth=1.4, alpha=0.9)
            ax_r.scatter(ts_cur, cur_osc + marker_dy, marker=marker_style,
                         color=color, s=70, zorder=6)
            ax_r.text(ts_cur, cur_osc + marker_dy * 1.7, label_text,
                      color=color, fontsize=7.5, ha="center", va="center",
                      fontweight="bold")

    _draw_div(bull, bull_color, "Bull", -3.5, "^")
    _draw_div(h_bull, h_bull_color, "H Bull", -5.5, "^")
    _draw_div(bear, bear_color, "Bear", 3.5, "v")
    _draw_div(h_bear, h_bear_color, "H Bear", 5.5, "v")

    # Структурные треугольники: при смене EMA50 локальных min/max
    struct_low_change = (ema_l_p != ema_l_p.shift(1)) & ema_l_p.notna()
    struct_high_change = (ema_h_p != ema_h_p.shift(1)) & ema_h_p.notna()
    if struct_low_change.any():
        ts_l = idx[struct_low_change.values]
        # offset -2 баров, значение = ema_3[2 назад] - 4
        for ts in ts_l:
            i_cut = cut_pos[ts]
            if i_cut < 2:
                continue
            ts_off = idx[i_cut - 2]
            v = ema_3_p.iloc[i_cut - 2] - 4
            ax_r.scatter(ts_off, v, marker="^", color="#4caf4f", s=22, zorder=4)
    if struct_high_change.any():
        ts_h = idx[struct_high_change.values]
        for ts in ts_h:
            i_cut = cut_pos[ts]
            if i_cut < 2:
                continue
            ts_off = idx[i_cut - 2]
            v = ema_3_p.iloc[i_cut - 2] + 4
            ax_r.scatter(ts_off, v, marker="v", color="#ff5252", s=22, zorder=4)

    ax_r.set_ylabel("RSI", color="#d6e0f0")
    ax_r.legend(loc="upper left", facecolor="#1a1f29", edgecolor="#3a4252",
                labelcolor="#d6e0f0", fontsize=8, ncol=3)
    ax_r.tick_params(colors="#d6e0f0")
    ax_p.tick_params(colors="#d6e0f0")
    ax_p.set_ylabel("Price (USDT)", color="#d6e0f0")

    ax_r.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=12))
    ax_r.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    fig.autofmt_xdate()

    out = _Path(__file__).parent / f"asvk_rsi_{SYMBOL}_{TF}.png"
    fig.savefig(out, dpi=130, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"[OK] saved: {out}")


if __name__ == "__main__":
    main()
