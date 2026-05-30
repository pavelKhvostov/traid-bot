"""Vadim 12 Confluens ASVK — confluence-score стратегия на базе i-RDRB+FVG
с митигацией зоны.

10 факторов (максимум 16.0 балла):
  Ф1 (1.0): Trendline HMA-78(1h) на close(#5) direction-match
  Ф2 (1.0): OB-pair HTF same direction формирующийся в setup'е
  Ф3 (1.0): Sweep FL/FH на {1h, 2h} свечой #1..#4 direction-aware
  Ф4 (1.5): Sweep FL/FH на HTF {4h, 6h, 12h, 1d, 2d, 3d} direction-aware
  Ф5 (1.0): Свечи #1..#4 перекрывают предсущ. FVG на {15m, 1h, 2h}
  Ф6 (1.5): Свечи #1..#4 перекрывают предсущ. FVG на HTF {4h..3d}
  Ф7 (1.5): Свечи #1..#4 заходят в предсущ. OB HTF same direction
  Ф8 (1.5): Нетронутый ViC.D/2D/3D, первое перекрытие в setup'е
  Ф9 (1.0): Raw RSI(14) на close(#5) <50 LONG / >50 SHORT
  Ф10 (≤5): Дивы на 5 осцилляторах (MACD line, MACD hist, RSI, Stoch%K, OBV)
            с pivot на #1..#5 direction-aware (+1 на каждый осциллятор)
  Ф11 (1.0): rel_vol < 1.5 (тихий объём свечей #2..#4)
             rel_vol = Σvol(#2..#4) / (3 × SMA20(vol_per_1h))

Setup: i-RDRB+FVG (5-свечной element)
Execution: митигация → entry=0.9, SL=0.2, RR=1.4, без таймстопа
Ассеты: BTCUSDT + ETHUSDT + SOLUSDT, 1h, 6 лет.
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from strategies.strategy_rdrb import detect_rdrb
from strategies.strategy_1_1_1 import detect_fvg, detect_ob_pair, zones_overlap
from research.asvk_trend_line.plot_asvk_trend_line import hma
from research.asvk_rsi.plot_asvk_rsi import (
    rsi_wilder, find_divergences, RSI_PERIOD, LB_L, LB_R, RANGE_LOWER, RANGE_UPPER,
)
from vic_levels import calculate_vic_d

ASSETS = [
    ("BTCUSDT", ROOT / "data" / "BTCUSDT_1m_vic_vadim.csv"),
    ("ETHUSDT", ROOT / "data" / "ETHUSDT_1m_vic_vadim.csv"),
]
START = pd.Timestamp("2020-05-15", tz="UTC")
ENTRY_FRAC = 0.9
SL_FRAC = 0.2
RR = 1.4
HMA_LEN = 78
HTF_FOR_OB_SWEEP_FVG = [("4h","4h",4),("6h","6h",6),("12h","12h",12),
                        ("1d","1D",24),("2d","2D",48),("3d","3D",72)]
LTF_FVG = [("15m","15min",0.25),("1h","1h",1),("2h","2h",2)]


def load_1m(path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def resample(df_1m, freq):
    return df_1m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])


def ema(s, n): return s.ewm(span=n, adjust=False).mean()


def macd_components(close):
    macd_line = ema(close, 12) - ema(close, 26)
    signal_line = ema(macd_line, 9)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def stoch_k(high, low, close, period=14):
    hh = high.rolling(period, min_periods=period).max()
    ll = low.rolling(period, min_periods=period).min()
    rng = (hh - ll).replace(0, np.nan)
    return 100 * (close - ll) / rng


def obv(close, volume):
    diff = close.diff().fillna(0)
    sign = np.sign(diff)
    return (sign * volume).cumsum()


def find_fractals(df_tf):
    """5-bar pivot fractals. Returns (fh_levels_arr, fh_ready_ns_arr, fl_levels_arr, fl_ready_ns_arr).
    ready_ns = idx_ns[i+2] + tf_duration_ns."""
    h = df_tf["high"].to_numpy()
    l = df_tf["low"].to_numpy()
    idx_ns = df_tf.index.values.astype("datetime64[ns]").astype(np.int64)
    if len(idx_ns) >= 2:
        tf_ns = int(idx_ns[1] - idx_ns[0])
    else:
        tf_ns = 60 * 60 * 1_000_000_000
    fh_lvl, fh_t, fl_lvl, fl_t = [], [], [], []
    for i in range(2, len(df_tf) - 2):
        if h[i] > h[i-2] and h[i] > h[i-1] and h[i] > h[i+1] and h[i] > h[i+2]:
            fh_lvl.append(float(h[i])); fh_t.append(idx_ns[i+2] + tf_ns)
        if l[i] < l[i-2] and l[i] < l[i-1] and l[i] < l[i+1] and l[i] < l[i+2]:
            fl_lvl.append(float(l[i])); fl_t.append(idx_ns[i+2] + tf_ns)
    return (np.array(fh_lvl, dtype=np.float64), np.array(fh_t, dtype=np.int64),
            np.array(fl_lvl, dtype=np.float64), np.array(fl_t, dtype=np.int64))


def find_fvg_zones(df_tf):
    """LONG FVG: high(c0) < low(c2). SHORT FVG: low(c0) > high(c2).
    Returns list of (dir, bottom, top, ready_ns)."""
    out = []
    h = df_tf["high"].to_numpy(); l = df_tf["low"].to_numpy()
    idx_ns = df_tf.index.values.astype("datetime64[ns]").astype(np.int64)
    if len(idx_ns) >= 2:
        tf_ns = int(idx_ns[1] - idx_ns[0])
    else:
        tf_ns = 60 * 60 * 1_000_000_000
    for k in range(2, len(df_tf)):
        if h[k-2] < l[k]:
            out.append(("LONG", float(h[k-2]), float(l[k]), idx_ns[k] + tf_ns))
        if l[k-2] > h[k]:
            out.append(("SHORT", float(h[k]), float(l[k-2]), idx_ns[k] + tf_ns))
    return out


def find_ob_zones(df_tf):
    """Detects OB pairs (LONG: prev bearish, cur bullish, cur.close > prev.open;
    SHORT: prev bullish, cur bearish, cur.close < prev.open).
    Returns list of (dir, bottom, top, ready_ns)."""
    out = []
    o = df_tf["open"].to_numpy(); h = df_tf["high"].to_numpy()
    l = df_tf["low"].to_numpy(); c = df_tf["close"].to_numpy()
    idx_ns = df_tf.index.values.astype("datetime64[ns]").astype(np.int64)
    if len(idx_ns) >= 2:
        tf_ns = int(idx_ns[1] - idx_ns[0])
    else:
        tf_ns = 60 * 60 * 1_000_000_000
    for k in range(1, len(df_tf)):
        if c[k-1] < o[k-1] and c[k] > o[k] and c[k] > o[k-1]:
            zb = float(min(l[k-1], l[k])); zt = float(o[k-1])
            if zt > zb: out.append(("LONG", zb, zt, idx_ns[k] + tf_ns))
        if c[k-1] > o[k-1] and c[k] < o[k] and c[k] < o[k-1]:
            zb = float(o[k-1]); zt = float(max(h[k-1], h[k]))
            if zt > zb: out.append(("SHORT", zb, zt, idx_ns[k] + tf_ns))
    return out


def has_sweep_one_tf(candle_low, candle_high, candle_close, candle_open_ns,
                     fh_lvl, fh_t, fl_lvl, fl_t, i_dir):
    """LONG sweep: low<FL_lvl AND close>FL_lvl. SHORT: high>FH_lvl AND close<FH_lvl."""
    if i_dir == "LONG":
        if fl_lvl.size == 0: return False
        mask = fl_t <= candle_open_ns
        if not mask.any(): return False
        lvls = fl_lvl[mask]
        return bool(((candle_low < lvls) & (candle_close > lvls)).any())
    else:
        if fh_lvl.size == 0: return False
        mask = fh_t <= candle_open_ns
        if not mask.any(): return False
        lvls = fh_lvl[mask]
        return bool(((candle_high > lvls) & (candle_close < lvls)).any())


def compute_vic_d_levels(df_1m, day_d):
    """Возвращает (vic_d, vic_2d, vic_3d) для дня D — все рассчитаны на 15m LTF
    для окон [D-1, D), [D-2, D), [D-3, D)."""
    vic_d = calculate_vic_d(df_1m, day_d - pd.Timedelta(days=1), ltf_minutes=15)
    # 2D / 3D — вычисляем вручную как maxV на N-дневном окне
    def maxv_window(days_back):
        start = day_d - pd.Timedelta(days=days_back)
        end = day_d
        seg = df_1m[(df_1m.index >= start) & (df_1m.index < end)]
        if seg.empty: return None
        seg_15 = seg.resample("15min", origin="epoch", label="left", closed="left").agg({
            "open":"first","high":"max","low":"min","close":"last","volume":"sum"
        }).dropna(subset=["close"])
        if seg_15.empty: return None
        bull = seg_15[seg_15["close"] > seg_15["open"]]
        bear = seg_15[seg_15["close"] < seg_15["open"]]
        mb = bull["volume"].max() if not bull.empty else 0
        mr = bear["volume"].max() if not bear.empty else 0
        if mb == 0 and mr == 0: return None
        if mb > mr:
            return float(bull.loc[bull["volume"].idxmax(), "close"])
        return float(bear.loc[bear["volume"].idxmax(), "close"])
    return vic_d, maxv_window(2), maxv_window(3)


def scan_asset(asset, path):
    print(f"\n[{asset}] loading 1m...", flush=True)
    df_1m = load_1m(path)
    df_1m = df_1m[df_1m.index >= START]
    df_1h = resample(df_1m, "1h")
    df_2h = resample(df_1m, "2h")
    df_15m = resample(df_1m, "15min")

    htf_dfs = {label: resample(df_1m, freq) for label, freq, _ in HTF_FOR_OB_SWEEP_FVG}

    print(f"[{asset}] computing indicators on 1h...", flush=True)
    closes_1h = df_1h["close"]
    hma_1h = hma(closes_1h, HMA_LEN).to_numpy()
    rsi_1h = rsi_wilder(closes_1h, RSI_PERIOD)
    macd_l, _, macd_h = macd_components(closes_1h)
    stoch_k_1h = stoch_k(df_1h["high"], df_1h["low"], df_1h["close"], 14)
    obv_1h = obv(df_1h["close"], df_1h["volume"])
    vol_1h = df_1h["volume"].to_numpy()
    sma20_vol_1h = pd.Series(vol_1h).rolling(20).mean().to_numpy()

    # Divs для 5 осцилляторов
    print(f"[{asset}] computing divergences...", flush=True)
    osc_divs = {}
    for name, osc in [("MACD_line", macd_l), ("MACD_hist", macd_h),
                       ("RSI", rsi_1h), ("Stoch_K", stoch_k_1h), ("OBV", obv_1h)]:
        bull, h_bull, bear, h_bear = find_divergences(
            osc, df_1h["low"], df_1h["high"],
            lb_l=LB_L, lb_r=LB_R, range_lower=RANGE_LOWER, range_upper=RANGE_UPPER)
        # хранил как (center_idx_current, center_idx_previous)
        osc_divs[name] = {
            "bull": [(d[0], d[1]) for d in bull + h_bull],   # LONG-side (regular + hidden)
            "bear": [(d[0], d[1]) for d in bear + h_bear],   # SHORT-side
        }

    print(f"[{asset}] computing fractals + FVGs + OBs...", flush=True)
    fract_by_tf = {"1h": find_fractals(df_1h), "2h": find_fractals(df_2h)}
    for label, _, _ in HTF_FOR_OB_SWEEP_FVG:
        fract_by_tf[label] = find_fractals(htf_dfs[label])
    fvg_by_tf = {"15m": find_fvg_zones(df_15m), "1h": find_fvg_zones(df_1h),
                  "2h": find_fvg_zones(df_2h)}
    for label, _, _ in HTF_FOR_OB_SWEEP_FVG:
        fvg_by_tf[label] = find_fvg_zones(htf_dfs[label])
    ob_by_tf = {}
    for label, _, _ in HTF_FOR_OB_SWEEP_FVG:
        ob_by_tf[label] = find_ob_zones(htf_dfs[label])

    # Precompute ViC.D/2D/3D — kэшируется по day_d
    days_idx = pd.date_range(start=df_1m.index.min().normalize(),
                              end=df_1m.index.max().normalize(), freq="D")
    print(f"[{asset}] precomputing ViC.D/2D/3D for {len(days_idx)} days...", flush=True)
    vic_cache = {}
    for d in days_idx:
        vic_cache[d] = compute_vic_d_levels(df_1m, d)

    # === Scan setups ===
    print(f"[{asset}] scanning setups...", flush=True)
    n = len(df_1h)
    highs = df_1h["high"].to_numpy(); lows = df_1h["low"].to_numpy()
    closes_arr = df_1h["close"].to_numpy()
    opens_arr = df_1h["open"].to_numpy()
    idx_1h = df_1h.index
    opens_ns = idx_1h.values.astype("datetime64[ns]").astype(np.int64)
    lo1 = df_1m["low"].to_numpy(); hi1 = df_1m["high"].to_numpy()
    idx1 = df_1m.index

    rows = []
    for k in range(2, n - 5):
        rdrb = detect_rdrb(df_1h, k, zone_version="V1")
        if rdrb is None: continue
        c4_close = closes_arr[k + 1]
        if rdrb.direction == "LONG":
            if not (c4_close < rdrb.bottom): continue
            i_dir = "SHORT"
        else:
            if not (c4_close > rdrb.top): continue
            i_dir = "LONG"
        fvg = detect_fvg(df_1h, k + 2)
        if fvg is None or fvg.direction != i_dir: continue
        if i_dir == "LONG":
            zone_b = float(min(lows[k-2], lows[k-1], lows[k], lows[k+1]))
            zone_t = float(lows[k+2])
        else:
            zone_t = float(max(highs[k-2], highs[k-1], highs[k], highs[k+1]))
            zone_b = float(highs[k+2])
        if zone_t <= zone_b: continue
        width = zone_t - zone_b
        if i_dir == "LONG":
            entry = zone_b + ENTRY_FRAC * width; sl = zone_b + SL_FRAC * width
            tp = entry + RR * (entry - sl)
        else:
            entry = zone_t - ENTRY_FRAC * width; sl = zone_t - SL_FRAC * width
            tp = entry - RR * (sl - entry)

        # Свечи setup'а (#1..#5 = k-2..k+2)
        setup_idxs = [k-2, k-1, k, k+1, k+2]
        setup_idxs_14 = setup_idxs[:4]  # #1..#4
        setup_open_ns = opens_ns[setup_idxs]
        setup_lows = lows[setup_idxs]
        setup_highs = highs[setup_idxs]
        setup_closes = closes_arr[setup_idxs]
        setup_open_t = idx_1h[k - 2]
        setup_close_t = idx_1h[k + 2] + pd.Timedelta(minutes=60)

        # === Ф1: Trendline HMA-78 1h ===
        c5_close = closes_arr[k + 2]
        hma_at_5 = hma_1h[k + 2]
        if np.isnan(hma_at_5):
            f1 = False
        elif i_dir == "LONG":
            f1 = hma_at_5 < c5_close
        else:
            f1 = hma_at_5 > c5_close

        # === Ф2: OB HTF same direction формирующийся в setup'е ===
        # cur OB на HTF, чей ready_ns ∈ [open(#4), close(#5)+TF]
        # = OB cur sits within or just after setup
        f2 = False
        f2_check_start = opens_ns[k + 1]  # open(#4)
        for label, freq, tf_h in HTF_FOR_OB_SWEEP_FVG:
            tf_ns = int(tf_h * 3600 * 1e9)
            f2_check_end = opens_ns[k + 2] + 60 * int(1e9) + tf_ns  # close(#5) + TF
            for d, b, t, r_ns in ob_by_tf[label]:
                if d != i_dir: continue
                if f2_check_start <= r_ns <= f2_check_end:
                    f2 = True; break
            if f2: break

        # === Ф3: Sweep FL/FH на {1h, 2h} свечой #1..#4 ===
        f3 = False
        for tf_label in ("1h", "2h"):
            fh_l, fh_t, fl_l, fl_t = fract_by_tf[tf_label]
            for ci in setup_idxs_14:
                if has_sweep_one_tf(setup_lows[setup_idxs.index(ci)],
                                      setup_highs[setup_idxs.index(ci)],
                                      setup_closes[setup_idxs.index(ci)],
                                      opens_ns[ci],
                                      fh_l, fh_t, fl_l, fl_t, i_dir):
                    f3 = True; break
            if f3: break

        # === Ф4: Sweep FL/FH на HTF {4h..3d} ===
        f4 = False
        for label, _, _ in HTF_FOR_OB_SWEEP_FVG:
            fh_l, fh_t, fl_l, fl_t = fract_by_tf[label]
            for ci in setup_idxs_14:
                if has_sweep_one_tf(setup_lows[setup_idxs.index(ci)],
                                      setup_highs[setup_idxs.index(ci)],
                                      setup_closes[setup_idxs.index(ci)],
                                      opens_ns[ci],
                                      fh_l, fh_t, fl_l, fl_t, i_dir):
                    f4 = True; break
            if f4: break

        # === Ф5: Свечи #1..#4 перекрывают предсущ. FVG на LTF {15m,1h,2h} ===
        f5 = False
        for tf_label, _, _ in LTF_FVG:
            for d, b, t, r_ns in fvg_by_tf[tf_label]:
                if r_ns > opens_ns[k - 2]: continue  # ready ≤ open(#1)
                # хотя бы одна свеча #1..#4 перекрывается
                for ci in setup_idxs_14:
                    if zones_overlap(lows[ci], highs[ci], b, t):
                        f5 = True; break
                if f5: break
            if f5: break

        # === Ф6: Свечи #1..#4 перекрывают предсущ. FVG на HTF {4h..3d} ===
        f6 = False
        for label, _, _ in HTF_FOR_OB_SWEEP_FVG:
            for d, b, t, r_ns in fvg_by_tf[label]:
                if r_ns > opens_ns[k - 2]: continue
                for ci in setup_idxs_14:
                    if zones_overlap(lows[ci], highs[ci], b, t):
                        f6 = True; break
                if f6: break
            if f6: break

        # === Ф7: Свечи #1..#4 заходят в предсущ. OB HTF same direction ===
        f7 = False
        for label, _, _ in HTF_FOR_OB_SWEEP_FVG:
            for d, b, t, r_ns in ob_by_tf[label]:
                if d != i_dir: continue
                if r_ns > opens_ns[k - 2]: continue
                for ci in setup_idxs_14:
                    if zones_overlap(lows[ci], highs[ci], b, t):
                        f7 = True; break
                if f7: break
            if f7: break

        # === Ф8: Нетронутый ViC.D/2D/3D, первое перекрытие в setup'е ===
        f8 = False
        day_d = setup_close_t.normalize()
        # Берём ViC уровни для дня D (рассчитаны на D-1, D-2, D-3)
        vic_d, vic_2d, vic_3d = vic_cache.get(day_d, (None, None, None))
        for level in (vic_d, vic_2d, vic_3d):
            if level is None: continue
            # t_formed = close дня формирования = day_d (00:00 UTC дня сетапа)
            t_formed = day_d
            # untouched: в [t_formed, open(#1)] нет 1m с low ≤ level ≤ high
            sp_t = int(idx1.searchsorted(t_formed, side="left"))
            ep_t = int(idx1.searchsorted(setup_open_t, side="left"))
            if ep_t <= sp_t: continue
            seg_lo = lo1[sp_t:ep_t]; seg_hi = hi1[sp_t:ep_t]
            if ((seg_lo <= level) & (seg_hi >= level)).any():
                continue  # был touch до setup
            # Первое перекрытие в setup'е: хотя бы одна свеча #1..#5 имеет low ≤ level ≤ high
            touched_in_setup = False
            for ci in setup_idxs:
                if lows[ci] <= level <= highs[ci]:
                    touched_in_setup = True; break
            if touched_in_setup:
                f8 = True; break

        # === Ф9: Raw RSI(14) на close(#5) <50 LONG / >50 SHORT ===
        rsi_at_5 = rsi_1h.iloc[k + 2]
        if pd.isna(rsi_at_5):
            f9 = False
        elif i_dir == "LONG":
            f9 = rsi_at_5 < 50
        else:
            f9 = rsi_at_5 > 50

        # === Ф10: Дивы на 5 осцилляторах с pivot на #1..#5 ===
        # +1 за каждый осциллятор с хотя бы 1 div нужного направления, чей pivot на #1..#5
        f10_count = 0
        f10_per_osc = {}
        for name, divs in osc_divs.items():
            dir_key = "bull" if i_dir == "LONG" else "bear"
            has_div = False
            for cur_idx, prev_idx in divs[dir_key]:
                if (cur_idx in setup_idxs) or (prev_idx in setup_idxs):
                    has_div = True; break
            f10_per_osc[name] = has_div
            if has_div: f10_count += 1

        # === Ф11: rel_vol < 1.5 (тихий объём свечей #2..#4) ===
        sum_vol_setup = float(vol_1h[k - 1] + vol_1h[k] + vol_1h[k + 1])
        avg_bar_vol = sma20_vol_1h[k] if k < len(sma20_vol_1h) else np.nan
        if np.isnan(avg_bar_vol) or avg_bar_vol <= 0:
            f11 = False; rel_vol = np.nan
        else:
            rel_vol = sum_vol_setup / (3 * avg_bar_vol)
            f11 = bool(rel_vol < 1.5)

        # Confluence score
        score = (1.0 * int(f1) + 1.0 * int(f2) + 1.0 * int(f3) + 1.5 * int(f4)
                 + 1.0 * int(f5) + 1.5 * int(f6) + 1.5 * int(f7) + 1.5 * int(f8)
                 + 1.0 * int(f9) + 1.0 * f10_count + 1.0 * int(f11))

        # === Execution: митигация + entry/SL/TP ===
        signal_time = setup_close_t
        sp = int(idx1.searchsorted(signal_time, side="left"))
        if sp >= len(idx1):
            outcome = "no_data"
        else:
            if i_dir == "LONG":
                mit_hits = np.where(lo1[sp:] <= zone_t)[0]
            else:
                mit_hits = np.where(hi1[sp:] >= zone_b)[0]
            if mit_hits.size == 0:
                outcome = "no_mit"
            else:
                mit_idx = sp + int(mit_hits[0])
                post_lo = lo1[mit_idx:]; post_hi = hi1[mit_idx:]
                m = len(post_lo)
                if i_dir == "LONG":
                    ei = np.where(post_lo <= entry)[0]; ti = np.where(post_hi >= tp)[0]
                else:
                    ei = np.where(post_hi >= entry)[0]; ti = np.where(post_lo <= tp)[0]
                e_idx = int(ei[0]) if ei.size else m + 1
                tp_pre = int(ti[0]) if ti.size else m + 1
                if tp_pre < e_idx: outcome = "no_entry"
                elif e_idx >= m: outcome = "not_filled"
                else:
                    p2l = post_lo[e_idx:]; p2h = post_hi[e_idx:]
                    if i_dir == "LONG":
                        slm = p2l <= sl; tpm = p2h >= tp
                    else:
                        slm = p2h >= sl; tpm = p2l <= tp
                    sf = int(np.argmax(slm)) if slm.any() else -1
                    tf = int(np.argmax(tpm)) if tpm.any() else -1
                    if sf == -1 and tf == -1: outcome = "open"
                    elif sf == -1: outcome = "win"
                    elif tf == -1: outcome = "loss"
                    else: outcome = "win" if tf < sf else "loss"

        rows.append({"asset": asset, "i_time": setup_open_t, "dir": i_dir,
                     "outcome": outcome,
                     "f1": int(f1), "f2": int(f2), "f3": int(f3), "f4": int(f4),
                     "f5": int(f5), "f6": int(f6), "f7": int(f7), "f8": int(f8),
                     "f9": int(f9), "f10_count": f10_count, "f11": int(f11),
                     "rel_vol": rel_vol,
                     "f10_macd_line": int(f10_per_osc.get("MACD_line", False)),
                     "f10_macd_hist": int(f10_per_osc.get("MACD_hist", False)),
                     "f10_rsi": int(f10_per_osc.get("RSI", False)),
                     "f10_stoch": int(f10_per_osc.get("Stoch_K", False)),
                     "f10_obv": int(f10_per_osc.get("OBV", False)),
                     "score": round(score, 2)})
    return pd.DataFrame(rows)


def main():
    parts = []
    for asset, path in ASSETS:
        df = scan_asset(asset, path)
        parts.append(df)
    df_all = pd.concat(parts, ignore_index=True)
    out = ROOT / "signals" / "vadim_confluens_asvk.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df_all.to_csv(out, index=False)
    print(f"\nsaved: {out} ({len(df_all)} rows)")

    closed = df_all[df_all["outcome"].isin(["win", "loss"])]
    w0 = int((closed["outcome"] == "win").sum()); l0 = len(closed) - w0
    base_wr = w0/len(closed)*100 if len(closed) else 0
    print(f"\n=== Baseline (все setup'ы) ===")
    print(f"  n={len(closed)} W={w0} L={l0} WR={base_wr:.2f}% ΣR={w0*RR-l0:+.2f} R/tr={(w0*RR-l0)/len(closed) if len(closed) else 0:+.3f}")

    print(f"\n=== Score distribution ===")
    print(f"  {'score':>5} {'n':>4} {'WR%':>6} {'sumR':>8} {'R/tr':>7} {'dWR':>7}")
    scores_sorted = sorted(closed["score"].unique())
    for s in scores_sorted:
        sub = closed[closed["score"] == s]
        w = int((sub["outcome"] == "win").sum()); l = len(sub) - w
        n = w + l
        wr = w/n*100 if n else 0
        r = w*RR - l
        d = wr - base_wr
        print(f"  {s:>5.2f} {n:>4} {wr:>6.2f} {r:>+8.2f} {r/n if n else 0:>+7.3f} {d:>+7.2f}")

    print(f"\n=== Cumulative score >= X ===")
    print(f"  {'th':>5} {'n':>4} {'WR%':>6} {'sumR':>8} {'R/tr':>7} {'dWR':>7}")
    thresholds = np.arange(0, 16.5, 0.5)
    for th in thresholds:
        sub = closed[closed["score"] >= th]
        w = int((sub["outcome"] == "win").sum()); l = len(sub) - w
        n = w + l
        if n == 0: continue
        wr = w/n*100
        r = w*RR - l
        d = wr - base_wr
        print(f"  {th:>5.1f} {n:>4} {wr:>6.2f} {r:>+8.2f} {r/n:>+7.3f} {d:>+7.2f}")


if __name__ == "__main__":
    main()
