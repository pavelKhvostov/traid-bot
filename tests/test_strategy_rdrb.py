"""Unit-тесты для детектора RDRB (strategies/strategy_rdrb.py:detect_rdrb).

Покрытие: happy-path LONG/SHORT для зон V1 и V2, хранение zone_version,
edge cases (нет паттерна, idx вне диапазона, пустой df, невалидная версия).

Все свечи синтетические, никакого I/O. Формулы зон — canon, см.
vault/knowledge/smc/что такое rdrb.md (V1/V2 зафиксированы 2026-05-19,
V3 отклонён).
"""
from __future__ import annotations

import pandas as pd
import pytest

from strategies.strategy_rdrb import detect_rdrb


# ---------- helpers ----------

def make_df(candles: list[tuple]) -> pd.DataFrame:
    """[(ts_str, open, high, low, close, volume), ...] -> DataFrame с UTC index."""
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


# anchor: O=100 H=110 L=95 C=105  → body_top=105, high=110
# mid:    C=115 > anchor.high=110
# trigger:low=108 < 110, close=112 > body_top=105
LONG_CANDLES = [
    ("2026-01-01", 100, 110,  95, 105, 10),  # anchor
    ("2026-01-02", 105, 116, 104, 115, 10),  # mid
    ("2026-01-03", 115, 118, 108, 112, 10),  # trigger
]
# V1 LONG: top=min(110,112)=110  bottom=max(108,105)=108  -> [108, 110]
# V2 LONG: top=110               bottom=body_top=105      -> [105, 110]

# anchor: O=100 H=105 L=90 C=95  → body_bottom=95, low=90
# mid:    C=85 < anchor.low=90
# trigger:high=92 > 90, close=88 < body_bottom=95
SHORT_CANDLES = [
    ("2026-01-01", 100, 105, 90, 95, 10),  # anchor
    ("2026-01-02",  95,  96, 84, 85, 10),  # mid
    ("2026-01-03",  85,  92, 82, 88, 10),  # trigger
]
# V1 SHORT: top=min(92,95)=92  bottom=max(90,88)=90  -> [90, 92]
# V2 SHORT: top=body_bottom=95 bottom=max(90,88)=90  -> [90, 95]


# ---------- happy path: LONG ----------

def test_long_v1_zone():
    """LONG RDRB, зона V1 = пересечение фитилей."""
    z = detect_rdrb(make_df(LONG_CANDLES), 2, "V1")
    assert z is not None
    assert z.direction == "LONG"
    assert z.bottom == pytest.approx(108.0)
    assert z.top == pytest.approx(110.0)
    assert z.zone_version == "V1"


def test_long_v2_zone():
    """LONG RDRB, зона V2 = низ расширен до верха тела anchor."""
    z = detect_rdrb(make_df(LONG_CANDLES), 2, "V2")
    assert z is not None
    assert z.direction == "LONG"
    assert z.bottom == pytest.approx(105.0)   # anchor body_top
    assert z.top == pytest.approx(110.0)
    assert z.zone_version == "V2"


def test_long_default_version_is_v1():
    """Без явного аргумента zone_version детектор возвращает V1."""
    z = detect_rdrb(make_df(LONG_CANDLES), 2)
    assert z is not None
    assert z.zone_version == "V1"
    assert z.bottom == pytest.approx(108.0)


# ---------- happy path: SHORT (противоположное направление) ----------

def test_short_v1_zone():
    """SHORT RDRB, зона V1 = пересечение фитилей."""
    z = detect_rdrb(make_df(SHORT_CANDLES), 2, "V1")
    assert z is not None
    assert z.direction == "SHORT"
    assert z.bottom == pytest.approx(90.0)
    assert z.top == pytest.approx(92.0)
    assert z.zone_version == "V1"


def test_short_v2_zone():
    """SHORT RDRB, зона V2 = верх расширен до низа тела anchor."""
    z = detect_rdrb(make_df(SHORT_CANDLES), 2, "V2")
    assert z is not None
    assert z.direction == "SHORT"
    assert z.bottom == pytest.approx(90.0)
    assert z.top == pytest.approx(95.0)       # anchor body_bottom
    assert z.zone_version == "V2"


# ---------- V1 vs V2: формирование одинаковое, зона разная ----------

def test_v1_v2_same_pattern_different_zone():
    """V1 и V2 ловят ОДИН паттерн, но отдают РАЗНЫЕ зоны."""
    df = make_df(LONG_CANDLES)
    v1 = detect_rdrb(df, 2, "V1")
    v2 = detect_rdrb(df, 2, "V2")
    assert v1 is not None and v2 is not None
    assert v1.direction == v2.direction == "LONG"
    assert v1.anchor_time == v2.anchor_time      # тот же паттерн
    assert v1.trigger_time == v2.trigger_time
    assert (v1.bottom, v1.top) != (v2.bottom, v2.top)  # зоны различаются


# ---------- edge case: нет паттерна ----------

def test_no_pattern_returns_none():
    """Три плоские свечи не образуют RDRB → None для обеих версий."""
    flat = make_df([
        ("2026-01-01", 100, 101, 99, 100, 10),
        ("2026-01-02", 100, 101, 99, 100, 10),
        ("2026-01-03", 100, 101, 99, 100, 10),
    ])
    assert detect_rdrb(flat, 2, "V1") is None
    assert detect_rdrb(flat, 2, "V2") is None


# ---------- edge case: граница диапазона / пустой df ----------

def test_idx_out_of_range_returns_none():
    """idx < 2 или idx >= len(df) → None (нет 3 свечей)."""
    df = make_df(LONG_CANDLES)
    assert detect_rdrb(df, 1) is None    # idx < 2
    assert detect_rdrb(df, 3) is None    # idx >= len
    assert detect_rdrb(empty_df(), 2) is None


# ---------- edge case: невалидная версия зоны ----------

def test_invalid_zone_version_raises():
    """V3 отклонён, любая неизвестная версия → ValueError."""
    df = make_df(LONG_CANDLES)
    with pytest.raises(ValueError):
        detect_rdrb(df, 2, "V3")
    with pytest.raises(ValueError):
        detect_rdrb(df, 2, "v1")   # регистр важен
