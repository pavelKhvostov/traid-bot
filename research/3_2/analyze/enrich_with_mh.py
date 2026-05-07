"""Обогащение enriched CSV всеми Money Hands метриками.

Берёт strategy_3_2_3y_RR1_with_asvk_part1.csv (уже с ASVK-колонками от первой
партии H8/H10/H11/H16/H17) и добавляет MH-колонки:
  - bw2_at_signal, bw2_sma14_at_signal, bw2_color
  - bw2_at_touch
  - mf_at_signal, mf_at_touch, mf_delta_12 (тренд MF за 12 баров)
  - rsi_mod_at_signal, stc_rsi_mod_at_signal
  - bw2_{bull,h_bull,bear,h_bear}_div_in_window (флаги)
  - max_bw2_*_depth_in_window
  - bw1_bw2_bull_cross_in_window, bw1_bw2_bear_cross_in_window
  - bw2_4h_at_touch  (для MH multi-TF)
  - delta_bw2_12  (для C5 acceleration)
  - nwe_width_at_signal  (для C8 volatility-regime)

Сохраняет: strategy_3_2_3y_RR1_with_asvk_mh.csv
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
_RSI_DIR = _ROOT / "research" / "asvk_rsi"
_MH_DIR = _ROOT / "research" / "money_hands"
for d in (_RSI_DIR, _MH_DIR):
    if str(d) not in _sys.path:
        _sys.path.insert(0, str(d))

from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import load_df
from plot_money_hands import (
    BW2_SMA_LEN, DIV_LB_L, DIV_LB_R, DIV_RANGE_LOWER, DIV_RANGE_UPPER,
    MF_PERIOD, MF_MULT, MF_Y, RSI_STOCH_LEN, SRSI_STOCH_LEN, RSI_SMA,
    WT_N1, WT_N2,
    heikin_ashi, money_flow, sma, stoch,
    wavetrend_blueWaves,
)

INPUT_CSV = Path("signals/strategy_3_2_3y_RR1_with_asvk_part1.csv")
OUT_CSV = Path("signals/strategy_3_2_3y_RR1_with_asvk_mh.csv")
SYMBOL = "BTCUSDT"
DIV_WINDOW_HOURS = 6
CROSS_WINDOW_HOURS = 24
DELTA_LOOKBACK = 12  # для delta_bw2 / delta_MF


def parse_utc3(s):
    if pd.isna(s) or s == "":
        return None
    return pd.Timestamp(s, tz="UTC") - pd.Timedelta(hours=3)


def find_divergences_with_depth_mh(osc, low, high, lb_l, lb_r, range_lower, range_upper):
    """Расширенный find_divergences с депт-метриками для MH."""
    from plot_money_hands import _pivot
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
                    d_osc = cur_osc - last_pl[2]
                    d_price = cur_price - last_pl[3]
                    if d_price != 0:
                        depth = abs(d_osc / d_price * cur_price * 0.01)
                    else:
                        depth = abs(d_osc)
                    if cur_price < last_pl[3] and cur_osc > last_pl[2]:
                        bull.append((i, depth))
                    if cur_price > last_pl[3] and cur_osc < last_pl[2]:
                        h_bull.append((i, depth))
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
                    d_osc = cur_osc - last_ph[2]
                    d_price = cur_price - last_ph[3]
                    if d_price != 0:
                        depth = abs(d_osc / d_price * cur_price * 0.01)
                    else:
                        depth = abs(d_osc)
                    if cur_price > last_ph[3] and cur_osc < last_ph[2]:
                        bear.append((i, depth))
                    if cur_price < last_ph[3] and cur_osc > last_ph[2]:
                        h_bear.append((i, depth))
            last_ph = (i, center, cur_osc, cur_price)
    return bull, h_bull, bear, h_bear


def bw2_color_categorical(bw2_val, sma_val):
    if pd.isna(bw2_val) or pd.isna(sma_val):
        return "na"
    if bw2_val > 0:
        return "green" if bw2_val >= sma_val else "grey_after_green"
    if bw2_val < 0:
        return "red" if bw2_val <= sma_val else "grey_after_red"
    return "na"


def find_bw_crosses(bw1, bw2):
    """Возвращает (bull_cross_times, bear_cross_times) — моменты bw1 пересекает bw2."""
    diff = bw1 - bw2
    bull = (diff > 0) & (diff.shift(1) <= 0)
    bear = (diff < 0) & (diff.shift(1) >= 0)
    bull_t = pd.DatetimeIndex(diff.index[bull.fillna(False)], tz="UTC")
    bear_t = pd.DatetimeIndex(diff.index[bear.fillna(False)], tz="UTC")
    return bull_t, bear_t


def main():
    print(f"[INFO] загрузка {INPUT_CSV}")
    df = pd.read_csv(INPUT_CSV)
    print(f"  rows: {len(df)}")

    print(f"[INFO] загрузка {SYMBOL} 1h, 4h")
    df_1h = load_df(SYMBOL, "1h")
    df_4h = load_df(SYMBOL, "4h")
    print(f"  1h={len(df_1h)} 4h={len(df_4h)}")

    print("[INFO] расчёт MH на 1h")
    hlc3_1h = (df_1h["high"] + df_1h["low"] + df_1h["close"]) / 3
    bw1, bw2, vwap = wavetrend_blueWaves(hlc3_1h, WT_N1, WT_N2)
    bw2_sma14 = sma(bw2, BW2_SMA_LEN)

    ha_o, ha_h, ha_l, ha_c = heikin_ashi(df_1h["open"], df_1h["high"],
                                         df_1h["low"], df_1h["close"])
    mf = money_flow(ha_o, ha_h, ha_l, ha_c)

    rsi_mod = sma(stoch(df_1h["close"], df_1h["high"], df_1h["low"], RSI_STOCH_LEN),
                  RSI_SMA)
    stc_rsi = sma(stoch(df_1h["close"], df_1h["high"], df_1h["low"], SRSI_STOCH_LEN),
                  RSI_SMA)

    bull, h_bull, bear, h_bear = find_divergences_with_depth_mh(
        bw2, df_1h["low"], df_1h["high"],
        DIV_LB_L, DIV_LB_R, DIV_RANGE_LOWER, DIV_RANGE_UPPER,
    )

    def to_records(divs):
        if not divs:
            return pd.DatetimeIndex([], tz="UTC"), np.array([])
        idx = pd.DatetimeIndex([df_1h.index[d[0]] for d in divs], tz="UTC")
        depths = np.array([d[1] for d in divs])
        return idx, depths

    bull_t, bull_d = to_records(bull)
    h_bull_t, h_bull_d = to_records(h_bull)
    bear_t, bear_d = to_records(bear)
    h_bear_t, h_bear_d = to_records(h_bear)
    print(f"  divs MH: bull={len(bull_t)} h_bull={len(h_bull_t)} "
          f"bear={len(bear_t)} h_bear={len(h_bear_t)}")

    bull_cross_t, bear_cross_t = find_bw_crosses(bw1, bw2)
    print(f"  bw1/bw2 crosses: bull={len(bull_cross_t)} bear={len(bear_cross_t)}")

    # MH на 4h тоже (для C5/multi-TF)
    print("[INFO] расчёт MH на 4h")
    hlc3_4h = (df_4h["high"] + df_4h["low"] + df_4h["close"]) / 3
    bw1_4h, bw2_4h, _ = wavetrend_blueWaves(hlc3_4h, WT_N1, WT_N2)
    bw2_sma14_4h = sma(bw2_4h, BW2_SMA_LEN)

    print("[INFO] обогащение")
    new_cols = {}
    fields_init = [
        "bw2_at_signal", "bw2_sma14_at_signal", "bw2_color",
        "bw2_at_touch", "bw2_color_at_touch",
        "mf_at_signal", "mf_at_touch", "mf_delta_12",
        "rsi_mod_at_signal", "stc_rsi_mod_at_signal",
        "bw2_bull_div_in_window", "bw2_h_bull_div_in_window",
        "bw2_bear_div_in_window", "bw2_h_bear_div_in_window",
        "max_bw2_bull_depth_in_window", "max_bw2_h_bull_depth_in_window",
        "max_bw2_bear_depth_in_window", "max_bw2_h_bear_depth_in_window",
        "bw1_bw2_bull_cross_in_window", "bw1_bw2_bear_cross_in_window",
        "bw2_4h_at_signal", "bw2_4h_color_at_signal",
        "delta_bw2_12",
        "nwe_width_at_signal",
    ]
    for f in fields_init:
        new_cols[f] = []

    for _, sig in df.iterrows():
        st = parse_utc3(sig["signal_time"])
        tt = parse_utc3(sig["touch_time"])

        # 1h snapshot at signal_time
        ipos_st = df_1h.index.get_indexer([st], method="ffill")[0]
        ipos_tt = df_1h.index.get_indexer([tt], method="ffill")[0]

        if ipos_st < 0 or ipos_tt < 0:
            for f in fields_init:
                new_cols[f].append(np.nan)
            continue

        bw2_st = float(bw2.iloc[ipos_st])
        bw2_sma_st = float(bw2_sma14.iloc[ipos_st])
        bw2_tt = float(bw2.iloc[ipos_tt])
        bw2_sma_tt = float(bw2_sma14.iloc[ipos_tt])

        new_cols["bw2_at_signal"].append(bw2_st)
        new_cols["bw2_sma14_at_signal"].append(bw2_sma_st)
        new_cols["bw2_color"].append(bw2_color_categorical(bw2_st, bw2_sma_st))
        new_cols["bw2_at_touch"].append(bw2_tt)
        new_cols["bw2_color_at_touch"].append(bw2_color_categorical(bw2_tt, bw2_sma_tt))

        new_cols["mf_at_signal"].append(float(mf.iloc[ipos_st]))
        new_cols["mf_at_touch"].append(float(mf.iloc[ipos_tt]))
        # MF delta — последние 12 баров
        if ipos_st >= DELTA_LOOKBACK:
            mf_now = float(mf.iloc[ipos_st])
            mf_back = float(mf.iloc[ipos_st - DELTA_LOOKBACK])
            new_cols["mf_delta_12"].append(mf_now - mf_back)
        else:
            new_cols["mf_delta_12"].append(np.nan)

        new_cols["rsi_mod_at_signal"].append(float(rsi_mod.iloc[ipos_st]))
        new_cols["stc_rsi_mod_at_signal"].append(float(stc_rsi.iloc[ipos_st]))

        # MH дивергенции в окне [touch-6h, signal]
        div_lo = tt - pd.Timedelta(hours=DIV_WINDOW_HOURS)
        div_hi = st

        def in_win_max(times, depths):
            if len(times) == 0:
                return False, np.nan
            mask = (times >= div_lo) & (times <= div_hi)
            if not mask.any():
                return False, np.nan
            return True, float(depths[mask].max())

        b_in, b_max = in_win_max(bull_t, bull_d)
        hb_in, hb_max = in_win_max(h_bull_t, h_bull_d)
        be_in, be_max = in_win_max(bear_t, bear_d)
        hbe_in, hbe_max = in_win_max(h_bear_t, h_bear_d)
        new_cols["bw2_bull_div_in_window"].append(b_in)
        new_cols["bw2_h_bull_div_in_window"].append(hb_in)
        new_cols["bw2_bear_div_in_window"].append(be_in)
        new_cols["bw2_h_bear_div_in_window"].append(hbe_in)
        new_cols["max_bw2_bull_depth_in_window"].append(b_max)
        new_cols["max_bw2_h_bull_depth_in_window"].append(hb_max)
        new_cols["max_bw2_bear_depth_in_window"].append(be_max)
        new_cols["max_bw2_h_bear_depth_in_window"].append(hbe_max)

        # bw1/bw2 cross в окне [touch-24h, signal]
        cross_lo = tt - pd.Timedelta(hours=CROSS_WINDOW_HOURS)
        cross_hi = st
        new_cols["bw1_bw2_bull_cross_in_window"].append(
            bool(((bull_cross_t >= cross_lo) & (bull_cross_t <= cross_hi)).any())
        )
        new_cols["bw1_bw2_bear_cross_in_window"].append(
            bool(((bear_cross_t >= cross_lo) & (bear_cross_t <= cross_hi)).any())
        )

        # MH на 4h: snapshot at signal
        ipos_st_4h = df_4h.index.get_indexer([st], method="ffill")[0]
        if ipos_st_4h >= 0:
            v = float(bw2_4h.iloc[ipos_st_4h])
            sm = float(bw2_sma14_4h.iloc[ipos_st_4h])
            new_cols["bw2_4h_at_signal"].append(v)
            new_cols["bw2_4h_color_at_signal"].append(bw2_color_categorical(v, sm))
        else:
            new_cols["bw2_4h_at_signal"].append(np.nan)
            new_cols["bw2_4h_color_at_signal"].append("na")

        # delta_bw2 за 12 баров
        if ipos_st >= DELTA_LOOKBACK:
            new_cols["delta_bw2_12"].append(
                bw2_st - float(bw2.iloc[ipos_st - DELTA_LOOKBACK])
            )
        else:
            new_cols["delta_bw2_12"].append(np.nan)

        # NWE-канал ширина (из ASVK)
        nwe_up = sig.get("nwe_upper_at_signal", np.nan)
        nwe_lo_ = sig.get("nwe_lower_at_signal", np.nan)
        if pd.notna(nwe_up) and pd.notna(nwe_lo_):
            new_cols["nwe_width_at_signal"].append(nwe_up - nwe_lo_)
        else:
            new_cols["nwe_width_at_signal"].append(np.nan)

    enriched = pd.concat([df.reset_index(drop=True),
                          pd.DataFrame(new_cols)], axis=1)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_csv(OUT_CSV, index=False)
    print(f"[OK] saved: {OUT_CSV}")
    print(f"  new columns: {len(fields_init)}")


if __name__ == "__main__":
    main()
