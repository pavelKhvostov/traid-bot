"""Общие фикстуры: фабрики синтетических DataFrame-ов свечей."""
from __future__ import annotations

import sys
from pathlib import Path

# Делает модули проекта (vic_levels, strategies/*) импортируемыми из тестов.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import pytest


@pytest.fixture
def make_1m():
    """Фабрика 1m-DataFrame: список (ts_str, open, close, volume) -> DF.

    high и low выводятся из (open, close) — это синтетические свечи для
    проверки логики calculate_vic_d, реальный wick не нужен."""
    def _make(rows):
        idx = pd.DatetimeIndex(
            [pd.Timestamp(r[0], tz="UTC") for r in rows],
            tz="UTC", name="open_time",
        )
        return pd.DataFrame({
            "open":   [r[1] for r in rows],
            "high":   [max(r[1], r[2]) for r in rows],
            "low":    [min(r[1], r[2]) for r in rows],
            "close":  [r[2] for r in rows],
            "volume": [r[3] for r in rows],
        }, index=idx)
    return _make


@pytest.fixture
def make_15m():
    """Фабрика 15m-DataFrame: список (ts_str, open, high, low, close) -> DF."""
    def _make(rows):
        idx = pd.DatetimeIndex(
            [pd.Timestamp(r[0], tz="UTC") for r in rows],
            tz="UTC", name="open_time",
        )
        return pd.DataFrame({
            "open":   [r[1] for r in rows],
            "high":   [r[2] for r in rows],
            "low":    [r[3] for r in rows],
            "close":  [r[4] for r in rows],
            "volume": [100.0] * len(rows),
        }, index=idx)
    return _make


@pytest.fixture
def make_1d():
    """Фабрика 1d-DataFrame с одной строкой D-1.

    `closing` — цена close дневной свечи D-1, по которой определяется
    направление цепочки (close vs maxV)."""
    def _make(closing: float, day_str: str = "2026-04-26"):
        idx = pd.DatetimeIndex(
            [pd.Timestamp(day_str, tz="UTC")], name="open_time"
        )
        return pd.DataFrame({
            "open":   [closing - 1.0],
            "high":   [closing + 1.0],
            "low":    [closing - 2.0],
            "close":  [closing],
            "volume": [1000.0],
        }, index=idx)
    return _make
