"""Smoke-тесты для Strategy 1.1.7 — fractal sweep + 1h anchor + OB + FVG."""
from __future__ import annotations

import pandas as pd

from strategies.strategy_1_1_7 import (
    Fractal4h,
    detect_4h_fractals,
    detect_strategy_1_1_7_signals,
    find_sweep_candle,
    sweep_became_fractal,
)


def make_df(candles: list[tuple]) -> pd.DataFrame:
    idx = pd.DatetimeIndex(
        [pd.Timestamp(c[0], tz="UTC") for c in candles],
        tz="UTC", name="open_time",
    )
    return pd.DataFrame({
        "open":   [c[1] for c in candles],
        "high":   [c[2] for c in candles],
        "low":    [c[3] for c in candles],
        "close":  [c[4] for c in candles],
        "volume": [c[5] for c in candles],
    }, index=idx)


def empty_df() -> pd.DataFrame:
    return pd.DataFrame(
        {"open": [], "high": [], "low": [], "close": [], "volume": []},
        index=pd.DatetimeIndex([], tz="UTC", name="open_time"),
    )


def test_detect_4h_fractal_ll():
    # 5 свечей, средняя (i=2) — LL фрактал.
    df = make_df([
        ("2026-01-01 00:00", 100, 105,  95, 102, 1),
        ("2026-01-01 04:00", 102, 106,  92, 100, 1),
        ("2026-01-01 08:00", 100, 104,  85,  98, 1),  # LL: low=85 < all neighbors
        ("2026-01-01 12:00",  98, 105,  90, 103, 1),
        ("2026-01-01 16:00", 103, 108,  95, 106, 1),
    ])
    fractals = detect_4h_fractals(df)
    assert len(fractals) == 1
    assert fractals[0].direction == "LONG"
    assert fractals[0].price == 85
    assert fractals[0].i == 2


def test_detect_4h_fractal_hh():
    df = make_df([
        ("2026-01-01 00:00", 100, 105,  95, 102, 1),
        ("2026-01-01 04:00", 102, 110,  95, 108, 1),
        ("2026-01-01 08:00", 108, 120,  95, 115, 1),  # HH: high=120 > all
        ("2026-01-01 12:00", 115, 112,  95, 108, 1),
        ("2026-01-01 16:00", 108, 110,  95, 105, 1),
    ])
    fractals = detect_4h_fractals(df)
    assert len(fractals) == 1
    assert fractals[0].direction == "SHORT"
    assert fractals[0].price == 120


def test_find_sweep_candle_long():
    # Фрактал на i=2 (low=85). После фрактала — свеча с low=80, close=88 (sweep).
    df = make_df([
        ("2026-01-01 00:00", 100, 105,  95, 102, 1),
        ("2026-01-01 04:00", 102, 106,  92, 100, 1),
        ("2026-01-01 08:00", 100, 104,  85,  98, 1),  # LL
        ("2026-01-01 12:00",  98, 105,  90, 103, 1),
        ("2026-01-01 16:00", 103, 108,  95, 106, 1),
        ("2026-01-01 20:00", 105, 108,  80,  88, 1),  # sweep: low=80 < 85, close=88 > 85
    ])
    fractal = Fractal4h("LONG", 85.0, 2, df.index[2])
    sweep = find_sweep_candle(df, fractal)
    assert sweep is not None
    assert sweep.sweep_low == 80
    assert sweep.sweep_close == 88
    # POI = [low=80, min(open=105, close=88)=88] = [80, 88]
    assert sweep.poi_bottom == 80
    assert sweep.poi_top == 88


def test_find_sweep_candle_long_no_sweep_if_closed_below():
    # Свеча low=80, close=82 — закрылась за фракталом → sweep пропущен.
    df = make_df([
        ("2026-01-01 00:00", 100, 105,  95, 102, 1),
        ("2026-01-01 04:00", 102, 106,  92, 100, 1),
        ("2026-01-01 08:00", 100, 104,  85,  98, 1),
        ("2026-01-01 12:00",  98, 105,  90, 103, 1),
        ("2026-01-01 16:00", 103, 108,  95, 106, 1),
        ("2026-01-01 20:00", 105, 108,  80,  82, 1),  # close=82 < 85
    ])
    fractal = Fractal4h("LONG", 85.0, 2, df.index[2])
    assert find_sweep_candle(df, fractal) is None


def test_sweep_became_fractal_true():
    # Sweep low=80. За 8h (2 свечи) ни одна low < 80.
    df = make_df([
        ("2026-01-01 20:00", 105, 108,  80,  88, 1),
        ("2026-01-02 00:00",  88,  95,  85,  90, 1),
        ("2026-01-02 04:00",  90, 100,  82,  95, 1),
    ])
    # Создаём sweep вручную:
    from strategies.strategy_1_1_7 import SweepCandle
    sweep = SweepCandle(
        direction="LONG",
        fractal=Fractal4h("LONG", 85.0, 0, df.index[0]),
        sweep_time=df.index[0],
        sweep_close_time=df.index[0] + pd.Timedelta(hours=4),
        sweep_open=105, sweep_high=108, sweep_low=80, sweep_close=88,
        poi_bottom=80, poi_top=88,
    )
    assert sweep_became_fractal(df, sweep) is True


def test_sweep_became_fractal_false_if_low_pierced():
    df = make_df([
        ("2026-01-01 20:00", 105, 108,  80,  88, 1),
        ("2026-01-02 00:00",  88,  95,  75,  90, 1),  # low=75 < 80 → пробил
        ("2026-01-02 04:00",  90, 100,  82,  95, 1),
    ])
    from strategies.strategy_1_1_7 import SweepCandle
    sweep = SweepCandle(
        direction="LONG",
        fractal=Fractal4h("LONG", 85.0, 0, df.index[0]),
        sweep_time=df.index[0],
        sweep_close_time=df.index[0] + pd.Timedelta(hours=4),
        sweep_open=105, sweep_high=108, sweep_low=80, sweep_close=88,
        poi_bottom=80, poi_top=88,
    )
    assert sweep_became_fractal(df, sweep) is False


def test_strategy_1_1_7_empty_inputs_no_crash():
    sigs = detect_strategy_1_1_7_signals(
        df_4h=empty_df(), df_1h=empty_df(), df_2h=empty_df(),
        df_15m=empty_df(), df_20m=empty_df(),
    )
    assert sigs == []
