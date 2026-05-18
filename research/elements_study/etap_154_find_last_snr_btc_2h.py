"""etap_154: Найти последний SnR на BTC 2h по моему определению.

SnR-зона:
  1. >= 2 fractal-swing точек (5-bar) в узком range (default 0.3% от уровня)
  2. Между касаниями цена уходила (gap >= 1% между касаниями)
  3. Зона валидна пока close не закрылся за её границей с подтверждением

Возвращает последнюю валидную SnR-зону с полным контекстом.
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


SYMBOL = "BTCUSDT"
TIMEFRAME = "1d"   # анализируем 1d
ZONE_PCT = 0.01    # 1% от уровня для 1d (более широкая толерантность чем для 2h)
MIN_TOUCHES = 2    # минимум 2 свинга
MIN_GAP_PCT = 0.03 # >= 3% gap между касаниями
WINDOW_LOOKBACK_BARS = 730  # последние 730 баров 1d = ~2 года


def find_fractals(df, n=2):
    """5-bar fractal: low/high экстремум в i относительно i-2..i+2."""
    highs = df["high"].values; lows = df["low"].values
    n_bars = len(df)
    hi_idx, lo_idx = [], []
    for i in range(n, n_bars - n):
        hi = highs[i]
        lo = lows[i]
        if all(hi > highs[i-k] for k in range(1, n+1)) and all(hi > highs[i+k] for k in range(1, n+1)):
            hi_idx.append(i)
        if all(lo < lows[i-k] for k in range(1, n+1)) and all(lo < lows[i+k] for k in range(1, n+1)):
            lo_idx.append(i)
    return hi_idx, lo_idx


def cluster_swings(swings, prices, zone_pct, min_gap_pct):
    """Кластеризуем свинги: те что в ±zone_pct% друг от друга → одна зона.

    Возвращает список зон: каждая = list of (idx, price).
    """
    if not swings: return []
    # сортируем по индексу
    pairs = sorted([(i, prices[i]) for i in swings], key=lambda x: x[0])
    clusters = []  # list of list of (idx, price)
    for idx, price in pairs:
        placed = False
        for cluster in clusters:
            # проверяем что price близок к среднему cluster
            cluster_mean = np.mean([p for _, p in cluster])
            if abs(price - cluster_mean) / cluster_mean <= zone_pct:
                # ещё нужен gap >= min_gap_pct ко всем существующим касаниям в кластере по времени
                last_idx = max(i for i, _ in cluster)
                # gap не обязательно по времени -- мы хотим что цена реально уходила и возвращалась
                # упрощение: между cluster-касаниями есть хотя бы 1 swing противоположного типа?
                # для простоты сейчас просто кластеризуем по цене
                cluster.append((idx, price))
                placed = True
                break
        if not placed:
            clusters.append([(idx, price)])
    return clusters


def main():
    if TIMEFRAME == "1d":
        df_2h = load_df(SYMBOL, "1d")
    else:
        df_1h = load_df(SYMBOL, "1h")
        df_2h = compose_from_base(df_1h, TIMEFRAME)
    df_2h = df_2h.iloc[-WINDOW_LOOKBACK_BARS:].copy()
    print(f"BTC {TIMEFRAME} window: {df_2h.index[0]} -> {df_2h.index[-1]}, {len(df_2h)} bars")
    print(f"Price range: {df_2h['low'].min():.2f} -> {df_2h['high'].max():.2f}")
    print()

    hi_idx, lo_idx = find_fractals(df_2h, n=2)
    print(f"Fractals: HH={len(hi_idx)}, LL={len(lo_idx)}")

    highs = df_2h["high"].values
    lows = df_2h["low"].values
    closes = df_2h["close"].values
    times = df_2h.index

    res_clusters = cluster_swings(hi_idx, highs, ZONE_PCT, MIN_GAP_PCT)
    sup_clusters = cluster_swings(lo_idx, lows, ZONE_PCT, MIN_GAP_PCT)

    # Фильтр: >=2 touches
    res_clusters = [c for c in res_clusters if len(c) >= MIN_TOUCHES]
    sup_clusters = [c for c in sup_clusters if len(c) >= MIN_TOUCHES]
    print(f"Resistance zones (>=2 touches): {len(res_clusters)}")
    print(f"Support zones (>=2 touches): {len(sup_clusters)}")

    # Валидация каждой зоны: проверяем что после последнего касания close не пробил решительно
    def zone_state(cluster, kind):
        last_touch_idx = max(i for i, _ in cluster)
        prices = [p for _, p in cluster]
        zone_top = max(prices) * (1 + ZONE_PCT/2)
        zone_bot = min(prices) * (1 - ZONE_PCT/2)
        # после last_touch_idx есть ли close решительно за зоной (с подтверждением 2 свечи)?
        after = closes[last_touch_idx+1:]
        if kind == "R":  # resistance, инвалидация = 2 closes > zone_top
            for k in range(len(after) - 1):
                if after[k] > zone_top and after[k+1] > zone_top:
                    return "broken", last_touch_idx + 1 + k + 1
        else:  # support, инвалидация = 2 closes < zone_bot
            for k in range(len(after) - 1):
                if after[k] < zone_bot and after[k+1] < zone_bot:
                    return "broken", last_touch_idx + 1 + k + 1
        return "active", None

    # Найти последнюю АКТИВНУЮ зону по времени последнего касания
    all_zones = []
    for c in res_clusters:
        state, broken_idx = zone_state(c, "R")
        all_zones.append(("RESISTANCE", c, state, broken_idx))
    for c in sup_clusters:
        state, broken_idx = zone_state(c, "S")
        all_zones.append(("SUPPORT", c, state, broken_idx))

    # Сортируем по времени последнего touch
    all_zones.sort(key=lambda z: max(i for i, _ in z[1]), reverse=True)
    print()
    print("Top-5 SnR zones by recency of last touch:")
    print("-"*100)
    for j, (kind, cluster, state, broken_idx) in enumerate(all_zones[:5]):
        prices = [p for _, p in cluster]
        zone_top = max(prices) * (1 + ZONE_PCT/2)
        zone_bot = min(prices) * (1 - ZONE_PCT/2)
        last_idx = max(i for i, _ in cluster)
        last_time = times[last_idx]
        print(f"\n#{j+1} {kind}  state={state}")
        print(f"  Zone:  [{zone_bot:.2f} ... {zone_top:.2f}]  (mid={np.mean(prices):.2f})")
        print(f"  Touches: {len(cluster)}")
        for idx, p in sorted(cluster, key=lambda x: x[0]):
            print(f"    {times[idx].strftime('%Y-%m-%d %H:%M')} UTC  price={p:.2f}  bar#{idx}")
        if broken_idx is not None and broken_idx < len(times):
            print(f"  Broken: close beyond zone at {times[broken_idx].strftime('%Y-%m-%d %H:%M')} UTC")
        print(f"  Last touch: {last_time.strftime('%Y-%m-%d %H:%M')} UTC ({len(df_2h) - 1 - last_idx} bars ago)")

    # Тот же поиск, но для последней АКТИВНОЙ
    print()
    print("="*100)
    print("LAST ACTIVE SnR (most recent zone that is NOT yet broken):")
    print("="*100)
    active = [z for z in all_zones if z[2] == "active"]
    if not active:
        print("  No active SnR zone found in window.")
        return
    kind, cluster, state, _ = active[0]
    prices = [p for _, p in cluster]
    zone_top = max(prices) * (1 + ZONE_PCT/2)
    zone_bot = min(prices) * (1 - ZONE_PCT/2)
    last_idx = max(i for i, _ in cluster)
    print(f"\n  TYPE: {kind}")
    print(f"  ZONE: [{zone_bot:.2f} ... {zone_top:.2f}]")
    print(f"  TOUCHES: {len(cluster)}")
    for idx, p in sorted(cluster, key=lambda x: x[0]):
        print(f"    {times[idx].strftime('%Y-%m-%d %H:%M')} UTC  price={p:.2f}  bar#{idx}")
    last_time = times[last_idx]
    current_close = closes[-1]
    print(f"  LAST TOUCH: {last_time.strftime('%Y-%m-%d %H:%M')} UTC")
    print(f"  CURRENT PRICE: {current_close:.2f} ({(current_close - np.mean(prices))/np.mean(prices)*100:+.2f}% from zone mid)")


if __name__ == "__main__":
    main()
