"""Тесты для prediction-algo/resample.py."""
from __future__ import annotations

import pandas as pd
import pytest

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resample import resample_one, resample_many, MONDAY_ANCHOR, ALL_TFS


def _make_1m(n_minutes: int, start: str = "2024-01-01 00:00") -> pd.DataFrame:
    """Сгенерировать синтетические 1m bars с предсказуемыми OHLC."""
    idx = pd.date_range(start=start, periods=n_minutes, freq="1min", tz="UTC")
    # open = i, high = i+0.5, low = i-0.5, close = i, volume = 1
    df = pd.DataFrame({
        "open": range(n_minutes),
        "high": [i + 0.5 for i in range(n_minutes)],
        "low": [i - 0.5 for i in range(n_minutes)],
        "close": range(n_minutes),
        "volume": [1.0] * n_minutes,
    }, index=idx)
    return df


def test_resample_1m_is_identity_within_window():
    df = _make_1m(60)
    cut = pd.Timestamp("2024-01-01 01:00", tz="UTC")  # 60 минут закрыто
    out = resample_one(df, "1m", cut)
    assert len(out) == 60
    assert out["open"].iloc[0] == 0
    assert out["close"].iloc[-1] == 59


def test_resample_5m_aggregates_correctly():
    df = _make_1m(15)
    cut = pd.Timestamp("2024-01-01 00:15", tz="UTC")  # 15 минут → 3 пятиминутки
    out = resample_one(df, "5m", cut)
    assert len(out) == 3
    # bar 0: minutes 0..4
    assert out["open"].iloc[0] == 0
    assert out["close"].iloc[0] == 4
    assert out["high"].iloc[0] == 4.5
    assert out["low"].iloc[0] == -0.5
    assert out["volume"].iloc[0] == 5
    # bar 2: minutes 10..14
    assert out["open"].iloc[2] == 10
    assert out["close"].iloc[2] == 14


def test_strict_cutoff_excludes_open_bar():
    # 7 минут данных, cut_off на 7-й минуте → 5m bar (0..4) закрыт, bar (5..9) ещё открыт
    df = _make_1m(7)
    cut = pd.Timestamp("2024-01-01 00:07", tz="UTC")
    out = resample_one(df, "5m", cut)
    assert len(out) == 1, f"only first 5m bar should be closed, got {len(out)} bars"
    assert out["open"].iloc[0] == 0
    assert out["close"].iloc[0] == 4


def test_strict_cutoff_exactly_on_boundary_includes_bar():
    df = _make_1m(5)
    cut = pd.Timestamp("2024-01-01 00:05", tz="UTC")  # ровно на границе 5m
    out = resample_one(df, "5m", cut)
    assert len(out) == 1
    assert out["close"].iloc[0] == 4


def test_weekly_anchor_is_monday():
    # 2024-01-01 = Monday. Weekly bar должен открыться 2024-01-01 00:00 UTC.
    df = _make_1m(7 * 24 * 60, start="2024-01-01 00:00")  # 1 неделя 1m данных
    cut = pd.Timestamp("2024-01-08 00:00", tz="UTC")
    out = resample_one(df, "1w", cut)
    assert len(out) == 1
    assert out.index[0] == pd.Timestamp("2024-01-01 00:00", tz="UTC")
    assert out["open"].iloc[0] == 0
    assert out["close"].iloc[0] == 7 * 24 * 60 - 1


def test_weekly_anchor_with_thursday_start():
    # 2024-01-04 = Thursday (mid-week). Weekly bar должен анкориться на пред. Monday 2024-01-01.
    # Если данные стартуют с Thursday → первый weekly bar = Mon-Sun (но с Thu в качестве open).
    df = _make_1m(8 * 24 * 60, start="2024-01-04 00:00")
    cut = pd.Timestamp("2024-01-12 00:00", tz="UTC")  # Friday next week
    out = resample_one(df, "1w", cut)
    # ожидаем 1 закрытый weekly bar (2024-01-01..2024-01-07), второй (2024-01-08..2024-01-14) ещё открыт
    assert len(out) == 1
    assert out.index[0] == pd.Timestamp("2024-01-01 00:00", tz="UTC")


def test_daily_anchor_at_utc_midnight():
    df = _make_1m(48 * 60, start="2024-01-01 00:00")  # 2 дня
    cut = pd.Timestamp("2024-01-03 00:00", tz="UTC")
    out = resample_one(df, "1d", cut)
    assert len(out) == 2
    assert out.index[0] == pd.Timestamp("2024-01-01 00:00", tz="UTC")
    assert out.index[1] == pd.Timestamp("2024-01-02 00:00", tz="UTC")


def test_12h_anchor_at_00_and_12_utc():
    df = _make_1m(36 * 60, start="2024-01-01 00:00")
    cut = pd.Timestamp("2024-01-02 12:00", tz="UTC")  # 1.5 дня → 3 закрытых 12h bar
    out = resample_one(df, "12h", cut)
    assert len(out) == 3
    assert out.index[0] == pd.Timestamp("2024-01-01 00:00", tz="UTC")
    assert out.index[1] == pd.Timestamp("2024-01-01 12:00", tz="UTC")
    assert out.index[2] == pd.Timestamp("2024-01-02 00:00", tz="UTC")


def test_resample_many_returns_dict():
    df = _make_1m(2 * 60)
    cut = pd.Timestamp("2024-01-01 02:00", tz="UTC")
    out = resample_many(df, ["1m", "5m", "15m", "30m", "1h"], cut)
    assert set(out.keys()) == {"1m", "5m", "15m", "30m", "1h"}
    assert len(out["1m"]) == 120
    assert len(out["5m"]) == 24
    assert len(out["15m"]) == 8
    assert len(out["30m"]) == 4
    assert len(out["1h"]) == 2


def test_cutoff_must_be_tz_aware():
    df = _make_1m(10)
    with pytest.raises(ValueError, match="tz-aware"):
        resample_one(df, "1m", pd.Timestamp("2024-01-01 00:05"))


def test_input_must_be_tz_aware():
    idx = pd.date_range("2024-01-01", periods=10, freq="1min")  # no tz
    df = pd.DataFrame({"open": range(10), "high": range(10), "low": range(10), "close": range(10), "volume": [1.0]*10}, index=idx)
    cut = pd.Timestamp("2024-01-01 00:05", tz="UTC")
    with pytest.raises(ValueError, match="tz-aware"):
        resample_one(df, "1m", cut)


def test_unknown_tf_raises():
    df = _make_1m(10)
    cut = pd.Timestamp("2024-01-01 00:05", tz="UTC")
    with pytest.raises(ValueError, match="Unknown TF"):
        resample_one(df, "7m", cut)


def test_all_canonical_tfs_resolvable():
    df = _make_1m(7 * 24 * 60 * 2)  # 2 недели
    cut = pd.Timestamp("2024-01-15 00:00", tz="UTC")
    out = resample_many(df, ALL_TFS, cut)
    # все TF должны вернуть хотя бы 1 bar
    for tf in ALL_TFS:
        assert len(out[tf]) >= 1, f"{tf} returned empty"
