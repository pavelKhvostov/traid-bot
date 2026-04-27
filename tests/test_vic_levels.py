"""Тесты для calculate_vic_d (vic_levels.py, §2 спеки)."""
from __future__ import annotations

import pandas as pd
import pytest

from vic_levels import calculate_vic_d


DAY = pd.Timestamp("2026-04-26", tz="UTC")


def test_empty_df_returns_none(make_1m):
    df = make_1m([])
    assert calculate_vic_d(df, DAY) is None


def test_only_other_day_candles_returns_none(make_1m):
    """Свечи есть, но НЕ в дне D — mask по диапазону отбрасывает всё."""
    df = make_1m([
        ("2026-04-25 12:00", 100, 101, 50),
        ("2026-04-27 12:00", 100, 102, 60),
    ])
    assert calculate_vic_d(df, DAY) is None


def test_only_doji_returns_none(make_1m):
    """Все свечи с close == open — нет ни bull, ни bear, оба max == 0."""
    df = make_1m([
        ("2026-04-26 00:00", 100, 100, 50),
        ("2026-04-26 00:01", 100, 100, 30),
    ])
    assert calculate_vic_d(df, DAY) is None


def test_bull_only_returns_max_volume_close(make_1m):
    df = make_1m([
        ("2026-04-26 00:00", 100, 101,   10),
        ("2026-04-26 00:01", 100, 102,   50),  # max bull
        ("2026-04-26 00:02", 100, 100.5, 5),
    ])
    assert calculate_vic_d(df, DAY) == 102.0


def test_bear_only_returns_max_volume_close(make_1m):
    df = make_1m([
        ("2026-04-26 00:00", 100, 99,   10),
        ("2026-04-26 00:01", 100, 98,   60),   # max bear
        ("2026-04-26 00:02", 100, 99.5, 5),
    ])
    assert calculate_vic_d(df, DAY) == 98.0


def test_mixed_bull_volume_higher_returns_bull_close(make_1m):
    df = make_1m([
        ("2026-04-26 00:00", 100, 101, 100),  # bull
        ("2026-04-26 00:01", 100, 99,  50),   # bear
    ])
    assert calculate_vic_d(df, DAY) == 101.0


def test_mixed_bear_volume_higher_returns_bear_close(make_1m):
    df = make_1m([
        ("2026-04-26 00:00", 100, 101, 30),
        ("2026-04-26 00:01", 100, 99,  80),  # bear wins
    ])
    assert calculate_vic_d(df, DAY) == 99.0


def test_tie_volumes_picks_bear(make_1m):
    """При max_bull == max_bear выбирается bear (§2: ветка else в `>`)."""
    df = make_1m([
        ("2026-04-26 00:00", 100, 101, 50),
        ("2026-04-26 00:01", 100, 99,  50),
    ])
    assert calculate_vic_d(df, DAY) == 99.0


def test_next_day_candles_excluded_by_mask(make_1m):
    """Свечи из дня D+1 не учитываются — фильтрация по `index < next_day`."""
    df = make_1m([
        ("2026-04-26 23:59", 100, 101, 10),
        ("2026-04-27 00:00", 100, 200, 999),  # уже в дне D+1
    ])
    assert calculate_vic_d(df, DAY) == 101.0


def test_returns_float_not_numpy(make_1m):
    """Контракт §2: возвращаемый тип — Python float (не np.float64)."""
    df = make_1m([("2026-04-26 00:00", 100, 102, 50)])
    result = calculate_vic_d(df, DAY)
    assert type(result) is float
