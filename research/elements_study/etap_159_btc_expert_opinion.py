"""etap_159: Экспертная оценка BTC прямо сейчас.

Multi-TF cascade анализ (по методологии Vadim'a expert_opinion.md):
  W → 3D → 2D → D → 12h → 6h → 4h → 2h → 1h → 15m

На каждом ТФ:
  - Текущая цена vs key levels (SnR + maxV + fractals)
  - Тренд (Hull MA, EMA200)
  - Momentum (RSI, Money Hands)
  - Untouched magnets (FVG, fractals)

Итог: opinion с probability bullish/bearish + key trigger levels.
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists(): _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path: _sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg

SYMBOL = "BTCUSDT"


# ============================================================
# Helpers
# ============================================================

def hull_ma(close: pd.Series, length: int = 78) -> pd.Series:
    half = max(int(length / 2), 1)
    sqrt_len = max(int(round(np.sqrt(length))), 1)
    def _wma(arr, period):
        weights = np.arange(1, period + 1, dtype=float); weights /= weights.sum()
        out = np.full_like(arr, np.nan, dtype=float)
        if len(arr) < period: return out
        valid = np.convolve(arr, weights[::-1], mode="valid")
        out[period - 1:] = valid
        return out
    arr = close.to_numpy(dtype=float)
    raw = 2.0 * _wma(arr, half) - _wma(arr, length)
    hull = _wma(np.where(np.isnan(raw), 0.0, raw), sqrt_len)
    hull[:length + sqrt_len] = np.nan
    return pd.Series(hull, index=close.index)


def find_fractals(df, n=2):
    highs = df["high"].values; lows = df["low"].values
    nb = len(df); hi_idx, lo_idx = [], []
    for i in range(n, nb - n):
        h = highs[i]; l = lows[i]
        if all(h > highs[i-k] for k in range(1, n+1)) and all(h > highs[i+k] for k in range(1, n+1)):
            hi_idx.append(i)
        if all(l < lows[i-k] for k in range(1, n+1)) and all(l < lows[i+k] for k in range(1, n+1)):
            lo_idx.append(i)
    return hi_idx, lo_idx


def cluster_swings(swings_idx, prices, zone_pct, min_touches=2):
    if not swings_idx: return []
    pairs = sorted([(i, prices[i]) for i in swings_idx], key=lambda x: x[0])
    clusters = []
    for idx, price in pairs:
        placed = False
        for cluster in clusters:
            mean = np.mean([p for _, p in cluster])
            if abs(price - mean) / mean <= zone_pct:
                cluster.append((idx, price)); placed = True; break
        if not placed: clusters.append([(idx, price)])
    return [c for c in clusters if len(c) >= min_touches]


def zone_state(cluster, closes_arr, zone_pct, kind):
    prices = [p for _, p in cluster]
    zt = max(prices) * (1 + zone_pct/2); zb = min(prices) * (1 - zone_pct/2)
    last_idx = max(i for i, _ in cluster)
    after = closes_arr[last_idx+1:]
    for k in range(len(after) - 1):
        if kind == "R" and after[k] > zt and after[k+1] > zt: return "broken", zt, zb
        if kind == "S" and after[k] < zb and after[k+1] < zb: return "broken", zt, zb
    return "active", zt, zb


def find_snr_zones(df, zone_pct, min_touches=2, n_fractal=2):
    hi_idx, lo_idx = find_fractals(df, n_fractal)
    res_clusters = cluster_swings(hi_idx, df["high"].values, zone_pct, min_touches)
    sup_clusters = cluster_swings(lo_idx, df["low"].values, zone_pct, min_touches)
    closes = df["close"].values
    res = [(c, *zone_state(c, closes, zone_pct, "R")) for c in res_clusters]
    sup = [(c, *zone_state(c, closes, zone_pct, "S")) for c in sup_clusters]
    return res, sup


def calc_vic_window(df_1m, w_start, w_end, ltf_min):
    mask = (df_1m.index >= w_start) & (df_1m.index < w_end)
    sub = df_1m.loc[mask]
    if sub.empty: return None, None, None
    if ltf_min > 1:
        sub = sub.resample(f"{ltf_min}min", origin="epoch", label="left", closed="left").agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
        }).dropna(subset=["close"])
    bull = sub[sub["close"] > sub["open"]]; bear = sub[sub["close"] < sub["open"]]
    mb = bull["volume"].max() if not bull.empty else 0
    mr = bear["volume"].max() if not bear.empty else 0
    if mb == 0 and mr == 0: return None, None, None
    if mb > mr: idx = bull["volume"].idxmax(); return float(bull.loc[idx, "close"]), "bull", float(mb)
    idx = bear["volume"].idxmax(); return float(bear.loc[idx, "close"]), "bear", float(mr)


def rsi_wilder(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0); loss = (-delta).clip(lower=0)
    avg_g = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_l = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_g / avg_l
    return 100 - (100 / (1 + rs))


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 78)
    print(f"  ЭКСПЕРТНАЯ ОЦЕНКА BTC — multi-TF cascade")
    print("=" * 78)

    # Load all TFs
    df_1d = load_df(SYMBOL, "1d")
    df_1h = load_df(SYMBOL, "1h")
    df_1m = load_df(SYMBOL, "1m")
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_4h = compose_from_base(df_1h, "4h")
    df_2h = compose_from_base(df_1h, "2h")
    # 1w composed
    df_1w = compose_from_base(df_1d, "7d")  # approx weekly

    current_price = float(df_1m["close"].iloc[-1])
    current_time = df_1m.index[-1]
    print(f"\n  Current price: ${current_price:,.2f}  ({current_time.strftime('%Y-%m-%d %H:%M')} UTC)")
    print(f"  1d close last: ${float(df_1d['close'].iloc[-1]):,.2f}  ({df_1d.index[-1].strftime('%Y-%m-%d')})")
    print()

    # ============================================================
    # 1. SnR zones на 1d (последние 2 года) и 12h (последние 6 мес)
    # ============================================================
    print("=" * 78)
    print("  1. KEY SnR ZONES (multi-touch swing clusters)")
    print("=" * 78)

    for tf_name, df_tf, lookback, zone_pct in [("1d", df_1d, 730, 0.012), ("12h", df_12h, 730, 0.008), ("4h", df_4h, 720, 0.005)]:
        df_w = df_tf.iloc[-lookback:].copy()
        res, sup = find_snr_zones(df_w, zone_pct, min_touches=2, n_fractal=2)
        active_res = [(c, zt, zb) for c, state, zt, zb in res if state == "active"]
        active_sup = [(c, zt, zb) for c, state, zt, zb in sup if state == "active"]
        # Sort by recency
        active_res.sort(key=lambda x: max(i for i, _ in x[0]), reverse=True)
        active_sup.sort(key=lambda x: max(i for i, _ in x[0]), reverse=True)
        print(f"\n  --- {tf_name} (window {lookback} bars, zone±{zone_pct*100:.1f}%) ---")
        print(f"  Top-3 ACTIVE RESISTANCE (recent first):")
        for c, zt, zb in active_res[:3]:
            touches = len(c)
            last_t = df_w.index[max(i for i, _ in c)]
            mid = (zt + zb) / 2
            dist_pct = (mid - current_price) / current_price * 100
            print(f"    [${zb:,.0f} ... ${zt:,.0f}]  mid=${mid:,.0f}  {touches} touches  last={last_t.strftime('%Y-%m-%d')}  Δ={dist_pct:+.2f}% from price")
        print(f"  Top-3 ACTIVE SUPPORT (recent first):")
        for c, zt, zb in active_sup[:3]:
            touches = len(c)
            last_t = df_w.index[max(i for i, _ in c)]
            mid = (zt + zb) / 2
            dist_pct = (mid - current_price) / current_price * 100
            print(f"    [${zb:,.0f} ... ${zt:,.0f}]  mid=${mid:,.0f}  {touches} touches  last={last_t.strftime('%Y-%m-%d')}  Δ={dist_pct:+.2f}% from price")

    # ============================================================
    # 2. maxV (последние 10 на 12h, 5 на 1d)
    # ============================================================
    print()
    print("=" * 78)
    print("  2. maxV LEVELS (latest VIC ASVK ВiC)")
    print("=" * 78)

    print(f"\n  --- 1d, последние 5 (LTF=15m) ---")
    last_ts = df_1m.index[-1]
    for tf_h, ltf_m, label, n_last in [(24, 15, "1d", 5), (12, 5, "12h", 8)]:
        step = pd.Timedelta(hours=tf_h)
        last_close = last_ts.floor(f"{tf_h}h")
        if last_close + step > last_ts + pd.Timedelta(minutes=1):
            last_close -= step
        windows = []
        cur = last_close
        for _ in range(n_last):
            windows.append((cur, cur + step)); cur -= step
        windows.reverse()
        print(f"\n  --- {label}, последние {n_last} (LTF={ltf_m}m) ---")
        print(f"  {'Open UTC':<20}  {'type':<5}  {'maxV':>12}  {'Δ% from price':>14}")
        for w_open, w_close in windows:
            mv, kind, vol = calc_vic_window(df_1m, w_open, w_close, ltf_m)
            if mv is None: continue
            d_pct = (mv - current_price) / current_price * 100
            print(f"  {w_open.strftime('%Y-%m-%d %H:%M'):<20}  {kind:<5}  ${mv:>10,.0f}  {d_pct:>+13.2f}%")

    # ============================================================
    # 3. Trend (Hull MA + EMA200) на каждом ТФ
    # ============================================================
    print()
    print("=" * 78)
    print("  3. TREND (Hull MA + EMA-200) per TF")
    print("=" * 78)
    print(f"\n  {'TF':<5}  {'Close':>10}  {'Hull(78)':>10}  {'EMA-200':>10}  {'Hull?':<10}  {'EMA?':<10}  {'RSI(14)':>8}")
    for tf_name, df_tf in [("1w", df_1w), ("1d", df_1d), ("12h", df_12h), ("6h", df_6h), ("4h", df_4h), ("2h", df_2h), ("1h", df_1h)]:
        close = df_tf["close"]
        if len(close) < 200: continue
        hull = hull_ma(close, 78)
        ema = close.ewm(span=200, adjust=False).mean()
        rsi = rsi_wilder(close, 14)
        c_last = float(close.iloc[-1]); h_last = float(hull.iloc[-1]) if not pd.isna(hull.iloc[-1]) else 0
        e_last = float(ema.iloc[-1]); r_last = float(rsi.iloc[-1])
        hull_state = "🟢 ABOVE" if c_last > h_last else "🔴 BELOW"
        ema_state = "🟢 ABOVE" if c_last > e_last else "🔴 BELOW"
        print(f"  {tf_name:<5}  ${c_last:>9,.0f}  ${h_last:>9,.0f}  ${e_last:>9,.0f}  {hull_state:<10}  {ema_state:<10}  {r_last:>7.1f}")

    # ============================================================
    # 4. Recent OB / FVG зоны на 1d, 12h, 4h
    # ============================================================
    print()
    print("=" * 78)
    print("  4. UNTOUCHED MAGNETS (OB/FVG zones near price)")
    print("=" * 78)
    for tf_name, df_tf in [("1d", df_1d), ("12h", df_12h), ("4h", df_4h)]:
        df_lookback = df_tf.iloc[-90:]
        last_close = float(df_lookback["close"].iloc[-1])
        # Find recent OB pairs
        obs = []
        for i in range(1, len(df_lookback)):
            ob = detect_ob_pair(df_lookback, i)
            if ob: obs.append(ob)
        # Filter to active (not touched after creation)
        active_obs = []
        for ob in obs[-30:]:  # последние 30 OB
            cur_idx = df_lookback.index.get_loc(ob.cur_time)
            after = df_lookback.iloc[cur_idx + 1:]
            if after.empty: continue
            if ob.direction == "LONG":
                if (after["low"] <= ob.top).any() and (after["close"] >= ob.bottom).all():
                    pass  # ob touched but not invalidated
                if (after["close"] < ob.bottom).any(): continue  # invalidated
            else:
                if (after["close"] > ob.top).any(): continue
            active_obs.append(ob)
        # FVG aналогично
        fvgs = []
        for k in range(2, len(df_lookback)):
            f = detect_fvg(df_lookback, k)
            if f: fvgs.append(f)
        # filter untouched FVG
        untouched_fvgs = []
        for f in fvgs[-30:]:
            c2_idx = df_lookback.index.get_loc(f.c2_time)
            after = df_lookback.iloc[c2_idx + 1:]
            if after.empty: continue
            if f.direction == "LONG":
                if (after["low"] <= f.bottom).any(): continue
            else:
                if (after["high"] >= f.top).any(): continue
            untouched_fvgs.append(f)

        nearby_obs = sorted(active_obs, key=lambda o: abs((o.top + o.bottom)/2 - last_close))[:3]
        nearby_fvgs = sorted(untouched_fvgs, key=lambda f: abs((f.top + f.bottom)/2 - last_close))[:3]

        print(f"\n  --- {tf_name} (last 90 bars) ---")
        print(f"  Recent active OB nearest to price:")
        for ob in nearby_obs:
            mid = (ob.top + ob.bottom) / 2
            d_pct = (mid - current_price) / current_price * 100
            print(f"    {ob.direction:<5} [${ob.bottom:,.0f} ... ${ob.top:,.0f}]  mid=${mid:,.0f}  Δ={d_pct:+.2f}%  {ob.cur_time.strftime('%Y-%m-%d')}")
        print(f"  Untouched FVG (магниты):")
        for f in nearby_fvgs:
            mid = (f.top + f.bottom) / 2
            d_pct = (mid - current_price) / current_price * 100
            print(f"    {f.direction:<5} [${f.bottom:,.0f} ... ${f.top:,.0f}]  mid=${mid:,.0f}  Δ={d_pct:+.2f}%  {f.c2_time.strftime('%Y-%m-%d')}")


if __name__ == "__main__":
    main()
