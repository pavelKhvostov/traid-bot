"""Перевод Pine-индикатора 'Trend Line - ASVK' (Hull MA вариант) в Python +
рисунок на 1h BTC.

Воспроизводит элементы:
  - Hull MA в 3 модах: HMA / EHMA / THMA
  - useHtf — расчёт от старшего ТФ (опционально, по умолчанию off)
  - MHULL = HULL, SHULL = HULL[2] (2-bar shift)
  - Полоса между max(MHULL, SHULL) и min(MHULL, SHULL) — never crosses
  - Цвет: close > SHULL → green, иначе red

Pine-функции реализованы с нуля (правило проекта: без TA-Lib).

Pine-формулы:
  HMA(src, len)  = WMA(2*WMA(src, len/2) - WMA(src, len), round(sqrt(len)))
  EHMA(src, len) = EMA(2*EMA(src, len/2) - EMA(src, len), round(sqrt(len)))
  THMA(src, len) = WMA(WMA(src, len/3)*3 - WMA(src, len/2) - WMA(src, len), len)

Mode("Thma", src, len) = THMA(src, len/2) — отдельный обвёртывающий /2.
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
PLOT_BARS = 500
HISTORY_BARS = 1500

# Pine inputs
MODE = "Hma"           # "Hma" | "Ehma" | "Thma"
LENGTH = 49            # 160-200 для floating S/R, 50-80 для swing entry
LENGTH_MULT = 1.6      # множитель для просмотра HTF straight band
USE_HTF = False        # if True — считать от старшего ТФ
HTF = "4h"             # старший ТФ при USE_HTF
COLOR_CANDLES = False  # окрашивать ли свечи в цвет тренда
SHOW_BAND = True


# --- math primitives ---

def wma(s: pd.Series, period: int) -> pd.Series:
    """Pine ta.wma — линейно-взвешенная средняя.
    weights = 1, 2, ..., period (наибольший вес на текущий бар).
    """
    period = max(int(period), 1)
    weights = np.arange(1, period + 1, dtype=float)
    w_sum = weights.sum()
    return s.rolling(period, min_periods=period).apply(
        lambda x: float(np.dot(x, weights) / w_sum), raw=True,
    )


def ema(s: pd.Series, period: int) -> pd.Series:
    """Pine ta.ema — alpha=2/(period+1), adjust=False."""
    period = max(int(period), 1)
    return s.ewm(span=period, adjust=False).mean()


# --- Hull MA modes ---

def hma(src: pd.Series, length: int) -> pd.Series:
    """Classic Hull MA (Alan Hull):
    HMA = WMA(2*WMA(src, n/2) - WMA(src, n), round(sqrt(n)))
    """
    half = max(int(length / 2), 1)
    sqrt_len = max(int(round(np.sqrt(length))), 1)
    raw = 2.0 * wma(src, half) - wma(src, length)
    return wma(raw, sqrt_len)


def ehma(src: pd.Series, length: int) -> pd.Series:
    """EMA-Hull: те же формулы, но EMA вместо WMA.
    Гладче, отзывчивее на резкие движения, но больше лаг на boring price.
    """
    half = max(int(length / 2), 1)
    sqrt_len = max(int(round(np.sqrt(length))), 1)
    raw = 2.0 * ema(src, half) - ema(src, length)
    return ema(raw, sqrt_len)


def thma(src: pd.Series, length: int) -> pd.Series:
    """Triple-Hull: финальная WMA от комбинации 3 WMA.
    THMA(src, n) = WMA(3*WMA(src, n/3) - WMA(src, n/2) - WMA(src, n), n)
    """
    third = max(int(length / 3), 1)
    half = max(int(length / 2), 1)
    raw = 3.0 * wma(src, third) - wma(src, half) - wma(src, length)
    return wma(raw, length)


def mode(name: str, src: pd.Series, length: int) -> pd.Series:
    """Pine `Mode` switch. Для 'Thma' дополнительно делит длину на 2."""
    if name == "Hma":
        return hma(src, length)
    if name == "Ehma":
        return ehma(src, length)
    if name == "Thma":
        # Pine: result := THMA(_src, _len / 2)
        return thma(src, max(int(length / 2), 1))
    raise ValueError(f"unknown mode: {name}")


# --- HTF resampling helper (если USE_HTF=True) ---

_TF_RESAMPLE = {"15m": "15min", "1h": "1h", "2h": "2h", "4h": "4h",
                 "6h": "6h", "12h": "12h", "1d": "1D"}


def resample_htf(df: pd.DataFrame, src_tf: str, htf: str) -> pd.Series:
    """Берём close с HTF, считаем индикатор на нём и обратно alignим к src_tf.

    Pine `request.security` не repaint'ит в 'on bar close' режиме —
    значение последнего HTF бара появляется когда HTF бар закрывается.
    Для бэктеста надо использовать `.shift(1)` чтобы не зацепить look-ahead.
    """
    rule = _TF_RESAMPLE.get(htf)
    if rule is None:
        raise ValueError(f"unknown htf: {htf}")
    htf_close = df["close"].resample(rule, label="right", closed="right").last()
    htf_close = htf_close.dropna()
    htf_hull = mode(MODE, htf_close, int(LENGTH * LENGTH_MULT))
    # ffill на src_tf timestamps; .shift(1) защищает от look-ahead на live-баре
    aligned = htf_hull.reindex(df.index, method="ffill").shift(1)
    return aligned


# --- main ---

def main():
    print(f"[INFO] загрузка {SYMBOL} {TF}")
    df = load_df(SYMBOL, TF)
    df = df.tail(HISTORY_BARS).copy()
    print(f"  bars: {len(df)} (last {df.index[-1]})")

    eff_len = int(LENGTH * LENGTH_MULT)
    print(f"[INFO] mode={MODE}, length={LENGTH}, mult={LENGTH_MULT}, "
          f"effective_len={eff_len}, useHtf={USE_HTF}")

    if USE_HTF:
        hull = resample_htf(df, TF, HTF)
    else:
        hull = mode(MODE, df["close"], eff_len)

    mhull = hull
    shull = hull.shift(2)

    # Цвет — close vs SHULL (как в Pine)
    is_green = df["close"] > shull
    # Полоса между min/max (Pine упорядочивает чтобы избежать crossing)
    upper = pd.concat([mhull, shull], axis=1).max(axis=1)
    lower = pd.concat([mhull, shull], axis=1).min(axis=1)

    # Подсчёт смен тренда (для статистики)
    trend = is_green.astype(int).diff().fillna(0).abs()
    flips = int(trend.sum())
    bars_green = int(is_green.sum())
    bars_red = int((~is_green).sum() - is_green.isna().sum())
    print(f"  trend flips: {flips}, bars green: {bars_green}, bars red: {bars_red}")

    # Cut for plot
    cut = df.iloc[-PLOT_BARS:]
    idx = cut.index
    mhull_p = mhull.loc[idx]
    shull_p = shull.loc[idx]
    upper_p = upper.loc[idx]
    lower_p = lower.loc[idx]
    is_green_p = is_green.loc[idx]

    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(16, 8))
    fig.patch.set_facecolor("#0e1217")
    ax.set_facecolor("#0e1217")
    ax.grid(True, color="#202632", linewidth=0.5)
    for spine in ax.spines.values():
        spine.set_color("#3a4252")

    # Цена линией
    ax.plot(idx, cut["close"], color="#d6e0f0", linewidth=1.0, label=f"{SYMBOL} close")

    GREEN = "#26a69a"
    RED = "#ef5350"

    # Полоса — отдельно для зелёных и красных сегментов
    if SHOW_BAND:
        ax.fill_between(idx, upper_p, lower_p, where=is_green_p,
                        color=GREEN, alpha=0.30, interpolate=False, linewidth=0,
                        label="band (uptrend)")
        ax.fill_between(idx, upper_p, lower_p, where=~is_green_p,
                        color=RED, alpha=0.30, interpolate=False, linewidth=0,
                        label="band (downtrend)")

    # Сами линии HULL и HULL[2] — в цвет тренда. Plot сегментами для чистого цвета.
    def _segment_plot(idx_, series, mask_green, color_g, color_r, lw, label_g=None):
        # Plot two passes (green where mask, red where not)
        s_g = series.where(mask_green)
        s_r = series.where(~mask_green)
        ax.plot(idx_, s_g, color=color_g, linewidth=lw, label=label_g)
        ax.plot(idx_, s_r, color=color_r, linewidth=lw)

    _segment_plot(idx, mhull_p, is_green_p, GREEN, RED, 1.6, "HULL (current)")
    _segment_plot(idx, shull_p, is_green_p, GREEN, RED, 1.0)

    # Окрашиваем свечи (декоративно)
    if COLOR_CANDLES:
        for ts, row in cut.iterrows():
            c = GREEN if is_green_p.get(ts, False) else RED
            ax.vlines(ts, row["low"], row["high"], color=c, linewidth=0.5, alpha=0.4)

    title = (f"{SYMBOL} {TF} · Trend Line — ASVK "
             f"({MODE}, len={LENGTH}*{LENGTH_MULT}={eff_len}"
             f"{', HTF=' + HTF if USE_HTF else ''})")
    ax.set_title(title, color="#d6e0f0", fontsize=13, pad=10)
    ax.set_ylabel("Price (USDT)", color="#d6e0f0")
    ax.legend(loc="upper left", facecolor="#1a1f29", edgecolor="#3a4252",
              labelcolor="#d6e0f0", fontsize=9)
    ax.tick_params(colors="#d6e0f0")
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=12))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    fig.autofmt_xdate()

    out = _Path(__file__).parent / f"asvk_trend_line_{SYMBOL}_{TF}_{MODE}.png"
    fig.savefig(out, dpi=130, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"[OK] saved: {out}")


if __name__ == "__main__":
    main()
