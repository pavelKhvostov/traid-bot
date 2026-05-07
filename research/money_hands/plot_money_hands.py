"""Перевод Pine-индикатора 'Money Hands - ASVK' в Python + рисунок на 1h BTC.

Pine использует closed library `raf_mak/libpublic` для функции `blueWaves(src, n1, n2)`.
Без доступа к её коду — допущение: WaveTrend (LazyBear), стандартная реализация,
которой пользуются все клоны Money Cipher B:
  ap   = hlc3
  esa  = EMA(ap, n1)
  d    = EMA(|ap - esa|, n1)
  ci   = (ap - esa) / (0.015 * d)
  wt1  = EMA(ci, n2)
  wt2  = SMA(wt1, 4)
  vwap = wt1 - wt2

bw1 = wt1, bw2 = wt2 (та, на которой дивергенции).

Все остальные элементы переведены 1:1: Heikin Ashi MF, rsiMod (Stoch 40 + SMA 2),
stcRsiMod (Stoch 81 + SMA 2), 4 типа дивергенций (lbL=2, lbR=2, range 5-60),
триггеры ±75, OS/OB ±60.
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
WT_N1 = 9
WT_N2 = 12
WT_SMOOTH_WT2 = 4
BW2_SMA_LEN = 14
TRIGGER_1 = 75
TRIGGER_2 = -75
OB_LEVEL_1 = 60
OS_LEVEL_1 = -60

DIV_LB_R = 2
DIV_LB_L = 2
DIV_RANGE_LOWER = 5
DIV_RANGE_UPPER = 60

MF_PERIOD = 60
MF_MULT = 200
MF_Y = 2.25

RSI_STOCH_LEN = 40
SRSI_STOCH_LEN = 81
RSI_SMA = 2


# --- math ---

def ema(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(span=period, adjust=False).mean()


def sma(s: pd.Series, period: int) -> pd.Series:
    return s.rolling(period, min_periods=period).mean()


def wavetrend_blueWaves(hlc3: pd.Series, n1=WT_N1, n2=WT_N2):
    """Допущение: lib.blueWaves = LazyBear WaveTrend."""
    esa = ema(hlc3, n1)
    d = ema((hlc3 - esa).abs(), n1)
    ci = (hlc3 - esa) / (0.015 * d.replace(0, np.nan))
    wt1 = ema(ci, n2)
    wt2 = sma(wt1, WT_SMOOTH_WT2)
    vwap = wt1 - wt2
    return wt1, wt2, vwap


def heikin_ashi(o, h, l, c):
    """Heikin Ashi с итеративным HA_open."""
    n = len(c)
    ha_close = (o + h + l + c) / 4
    ha_open = np.zeros(n)
    ha_open[0] = (o.iloc[0] + c.iloc[0]) / 2
    ha_close_arr = ha_close.values
    for i in range(1, n):
        ha_open[i] = (ha_open[i - 1] + ha_close_arr[i - 1]) / 2
    ha_open = pd.Series(ha_open, index=c.index)
    ha_high = pd.concat([h, ha_open, ha_close], axis=1).max(axis=1)
    ha_low = pd.concat([l, ha_open, ha_close], axis=1).min(axis=1)
    return ha_open, ha_high, ha_low, ha_close


def money_flow(ha_open, ha_high, ha_low, ha_close,
               period=MF_PERIOD, mult=MF_MULT, y=MF_Y):
    rng = (ha_high - ha_low).replace(0, np.nan)
    raw = ((ha_close - ha_open) / rng) * mult
    return sma(raw, period) - y


def stoch(close, high, low, period):
    """Pine ta.stoch(source, high, low, length) — %K по close vs (highest_high, lowest_low)."""
    hh = high.rolling(period, min_periods=period).max()
    ll = low.rolling(period, min_periods=period).min()
    rng = (hh - ll).replace(0, np.nan)
    return 100 * (close - ll) / rng


# --- pivots & divergences (на bw2) ---

def _pivot(s: pd.Series, lb_l: int, lb_r: int, kind: str) -> pd.Series:
    n = len(s)
    arr = s.values
    out = np.full(n, np.nan)
    for i in range(lb_l + lb_r, n):
        center = i - lb_r
        v = arr[center]
        if np.isnan(v):
            continue
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


def find_divergences(osc, low, high, lb_l, lb_r, range_lower, range_upper):
    pl = _pivot(osc, lb_l, lb_r, "low")
    ph = _pivot(osc, lb_l, lb_r, "high")
    n = len(osc)
    bull, h_bull, bear, h_bear = [], [], [], []

    last_pl = None
    for i in range(n):
        if not np.isnan(pl.iloc[i]):
            center = i - lb_r
            cur_osc = osc.iloc[center]
            cur_price = low.iloc[center]
            if last_pl is not None:
                bs = i - last_pl[0]
                if range_lower <= bs <= range_upper:
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
                bs = i - last_ph[0]
                if range_lower <= bs <= range_upper:
                    if cur_price > last_ph[3] and cur_osc < last_ph[2]:
                        bear.append((center, last_ph[1], cur_osc, last_ph[2]))
                    if cur_price < last_ph[3] and cur_osc > last_ph[2]:
                        h_bear.append((center, last_ph[1], cur_osc, last_ph[2]))
            last_ph = (i, center, cur_osc, cur_price)
    return bull, h_bull, bear, h_bear


# --- plot ---

def main():
    print(f"[INFO] загрузка {SYMBOL} {TF}")
    df = load_df(SYMBOL, TF)
    df = df.tail(HISTORY_BARS).copy()
    print(f"  bars: {len(df)} (last {df.index[-1]})")

    print("[INFO] расчёт компонентов")
    hlc3 = (df["high"] + df["low"] + df["close"]) / 3
    bw1, bw2, vwap = wavetrend_blueWaves(hlc3, WT_N1, WT_N2)
    bw2_sma14 = sma(bw2, BW2_SMA_LEN)

    ha_o, ha_h, ha_l, ha_c = heikin_ashi(df["open"], df["high"], df["low"], df["close"])
    mf = money_flow(ha_o, ha_h, ha_l, ha_c)

    rsi_mod = sma(stoch(df["close"], df["high"], df["low"], RSI_STOCH_LEN), RSI_SMA)
    stc_rsi = sma(stoch(df["close"], df["high"], df["low"], SRSI_STOCH_LEN), RSI_SMA)

    bull, h_bull, bear, h_bear = find_divergences(
        bw2, df["low"], df["high"],
        DIV_LB_L, DIV_LB_R, DIV_RANGE_LOWER, DIV_RANGE_UPPER,
    )
    print(f"  divs: bull={len(bull)} h_bull={len(h_bull)} "
          f"bear={len(bear)} h_bear={len(h_bear)}")

    # Cut for plot
    cut = df.iloc[-PLOT_BARS:]
    idx = cut.index
    bw1_p = bw1.loc[idx]
    bw2_p = bw2.loc[idx]
    vwap_p = vwap.loc[idx]
    bw2_sma14_p = bw2_sma14.loc[idx]
    mf_p = mf.loc[idx]
    rsi_mod_p = rsi_mod.loc[idx]
    stc_rsi_p = stc_rsi.loc[idx]

    plt.style.use("dark_background")
    fig, (ax_p, ax_main, ax_sec) = plt.subplots(
        3, 1, figsize=(16, 11), sharex=True,
        gridspec_kw={"height_ratios": [1.1, 1.7, 1.0], "hspace": 0.05},
    )
    fig.patch.set_facecolor("#0e1217")
    for ax in (ax_p, ax_main, ax_sec):
        ax.set_facecolor("#0e1217")
        ax.grid(True, color="#202632", linewidth=0.5)
        for s in ax.spines.values():
            s.set_color("#3a4252")
        ax.tick_params(colors="#d6e0f0")

    # --- Panel 1: price + pivot markers ---
    ax_p.plot(idx, cut["close"], color="#d6e0f0", linewidth=1.0, label=f"{SYMBOL} close")
    cut_pos = {ts: i for i, ts in enumerate(idx)}
    for center, *_ in bull:
        ts = df.index[center]
        if ts in cut_pos:
            ax_p.scatter(ts, df["low"].iloc[center], marker="^",
                         color="#4caf4f", s=40, zorder=5)
    for center, *_ in bear:
        ts = df.index[center]
        if ts in cut_pos:
            ax_p.scatter(ts, df["high"].iloc[center], marker="v",
                         color="#ff5252", s=40, zorder=5)
    ax_p.set_title(f"{SYMBOL} {TF} · Money Hands — ASVK",
                   color="#d6e0f0", fontsize=13, pad=10)
    ax_p.set_ylabel("Price", color="#d6e0f0")
    ax_p.legend(loc="upper left", facecolor="#1a1f29",
                edgecolor="#3a4252", labelcolor="#d6e0f0", fontsize=9)

    # --- Panel 2: bw2 histogram + sma14 + triggers + divergences ---
    GREEN = "#4caf4f"
    RED = "#ff5252"
    GREY = "#787b86"
    YELLOW = "#ffd54f"

    # bw2 histogram colors
    colors = []
    for v, sm in zip(bw2_p, bw2_sma14_p):
        if pd.isna(v) or pd.isna(sm):
            colors.append(GREY)
        elif v > 0:
            colors.append(GREEN if v >= sm else GREY)
        elif v < 0:
            colors.append(RED if v <= sm else GREY)
        else:
            colors.append(GREY)
    # bar width = 1 hour
    bar_width = pd.Timedelta(hours=1).total_seconds() / 86400 * 0.85
    ax_main.bar(idx, bw2_p, width=bar_width, color=colors, edgecolor="none",
                alpha=0.85, label="bw2")
    ax_main.plot(idx, bw2_sma14_p, color=YELLOW, linewidth=1.5, label="bw2 SMA(14)")

    # Triggers / OB-OS
    ax_main.axhline(TRIGGER_1, color=RED, linewidth=0.8, linestyle="--", alpha=0.7)
    ax_main.axhline(TRIGGER_2, color=GREEN, linewidth=0.8, linestyle="--", alpha=0.7)
    ax_main.axhline(OB_LEVEL_1, color="#ffffff", linewidth=0.6, linestyle=":", alpha=0.4)
    ax_main.axhline(OS_LEVEL_1, color="#ffffff", linewidth=0.6, linestyle=":", alpha=0.4)
    ax_main.axhline(0, color="#5a6373", linewidth=0.6)
    ax_main.text(idx[-1], TRIGGER_1, " 75", color=RED, fontsize=8, va="center")
    ax_main.text(idx[-1], TRIGGER_2, "-75", color=GREEN, fontsize=8, va="center")

    # Divergences — линии между prev и cur пивотами + лейблы
    BULL_C = "#4caf4f"
    BEAR_C = "#ff5252"
    HBULL_C = "#81c784"
    HBEAR_C = "#e57373"

    def draw_div(divs, color, label, dy, marker):
        for center, prev_center, cur_osc, prev_osc in divs:
            ts_cur = df.index[center]
            ts_prev = df.index[prev_center]
            if ts_cur not in cut_pos or ts_prev not in cut_pos:
                continue
            ax_main.plot([ts_prev, ts_cur], [prev_osc, cur_osc],
                         color=color, linewidth=1.4, alpha=0.85)
            ax_main.scatter(ts_cur, cur_osc + dy, marker=marker,
                            color=color, s=55, zorder=6)
            ax_main.text(ts_cur, cur_osc + dy * 1.6, label,
                         color=color, fontsize=7.5, ha="center", va="center",
                         fontweight="bold")

    draw_div(bull, BULL_C, "Bull", -7, "^")
    draw_div(h_bull, HBULL_C, "H Bull", -12, "^")
    draw_div(bear, BEAR_C, "Bear", 7, "v")
    draw_div(h_bear, HBEAR_C, "H Bear", 12, "v")

    ax_main.set_ylabel("bw2 (Blue Wave)", color="#d6e0f0")
    ax_main.legend(loc="upper left", facecolor="#1a1f29",
                   edgecolor="#3a4252", labelcolor="#d6e0f0", fontsize=8, ncol=2)

    # --- Panel 3: aux components — vwap, MF, rsiMod, stcRsiMod ---
    ax_sec.plot(idx, mf_p, color=GREEN, linewidth=1.2, label="Money Flow",
                alpha=0.9)
    ax_sec.fill_between(idx, mf_p, 0, where=mf_p > 0,
                        color=GREEN, alpha=0.15, interpolate=True)
    ax_sec.fill_between(idx, mf_p, 0, where=mf_p < 0,
                        color=RED, alpha=0.15, interpolate=True)
    ax_sec.plot(idx, vwap_p, color=YELLOW, linewidth=0.8, alpha=0.6, label="vwap (wt1-wt2)")
    ax_sec.plot(idx, rsi_mod_p, color="#e52be6", linewidth=1.0, label="rsiMod (Stoch40)", alpha=0.7)
    ax_sec.plot(idx, stc_rsi_p, color="#3ffb03", linewidth=1.0,
                label="stcRsiMod (Stoch81)", alpha=0.7)
    ax_sec.axhline(0, color="#5a6373", linewidth=0.6)
    ax_sec.set_ylabel("aux", color="#d6e0f0")
    ax_sec.legend(loc="upper left", facecolor="#1a1f29",
                  edgecolor="#3a4252", labelcolor="#d6e0f0", fontsize=8, ncol=2)

    ax_sec.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=12))
    ax_sec.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    fig.autofmt_xdate()

    out = _Path(__file__).parent / f"money_hands_{SYMBOL}_{TF}.png"
    fig.savefig(out, dpi=130, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"[OK] saved: {out}")


if __name__ == "__main__":
    main()
