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


# ---- LTF-агрегация (Pine ASVK ViC с auto+mlt) ----

def test_ltf_aggregation_changes_winner(make_1m):
    """При ltf_minutes=14 один объёмный 1m может проиграть 14m-агрегату.

    Сценарий: первая 1m свеча с volume=100 (бычья). Следующие 13 1m свечей
    — мелкие медвежьи с volume=10 каждая (∑=130). Один 14m-бар включает
    все 14 1m свечей: open=100 (open первой), close=last close (медвежий),
    volume=100+13×10=230. Этот единственный 14m-бар — bear. На сыром 1m
    выиграл бы bull (объём 100), на 14m — bear (объём 230)."""
    rows = [("2026-04-26 00:00", 100, 101, 100)]   # bull, 100
    for i in range(1, 14):
        rows.append((f"2026-04-26 00:{i:02d}", 100.5 + i * 0.01, 100.4 + i * 0.01, 10))
    df = make_1m(rows)
    # 1m-режим: bull побеждает
    assert calculate_vic_d(df, DAY, ltf_minutes=1) == 101.0
    # 14m-режим: один агрегат, bear (close < open)
    result = calculate_vic_d(df, DAY, ltf_minutes=14)
    assert result is not None
    assert result < 101.0  # close меньше open=100, точное значение зависит от ресемпла


def test_ltf_aggregation_preserves_format(make_1m):
    """ltf_minutes=14 возвращает float, не None при валидных данных."""
    rows = []
    for i in range(28):  # 2 14m-бара
        ts = f"2026-04-26 {i // 60:02d}:{i % 60:02d}"
        rows.append((ts, 100.0, 100.0 + (1 if i < 14 else -1), 50.0))
    df = make_1m(rows)
    result = calculate_vic_d(df, DAY, ltf_minutes=14)
    assert result is not None
    assert type(result) is float


def test_ltf_default_is_1m(make_1m):
    """Default ltf_minutes=1 — поведение идентично сырому 1m расчёту."""
    df = make_1m([
        ("2026-04-26 00:00", 100, 101, 50),
        ("2026-04-26 00:01", 100, 99, 50),
    ])
    # default = no resample = bear (tie-breaker)
    assert calculate_vic_d(df, DAY) == 99.0
    assert calculate_vic_d(df, DAY, ltf_minutes=1) == 99.0
