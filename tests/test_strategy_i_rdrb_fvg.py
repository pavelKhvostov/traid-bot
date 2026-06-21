"""Тесты для strategies/strategy_i_rdrb_fvg.detect_i_rdrb_fvg.

Свечи синтетические (ручная сверка с canon i_rdrb_fvg + Combined-D entry/SL).
Happy path LONG + SHORT + 4 edge case + causal-locality.
"""
from __future__ import annotations

import pandas as pd
import pytest

from strategies.strategy_i_rdrb_fvg import detect_i_rdrb_fvg, detect_all_i_rdrb_fvg


def _df(rows: list[dict]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="1h", tz="UTC")
    return pd.DataFrame(rows, index=idx)


# C1=idx0, C2, C3=idx2, C4, C5=idx4. detect_i_rdrb_fvg(df, idx=2).
LONG_ROWS = [
    {"open": 100, "high": 101, "low": 95, "close": 98},   # C1 anchor (bear body)
    {"open": 97, "high": 98, "low": 91, "close": 92},     # C2 displacement down (SHORT RDRB)
    {"open": 93, "high": 99, "low": 92, "close": 96},      # C3 rejection
    {"open": 97, "high": 104, "low": 96, "close": 103},    # C4 bull reversal close>block.top → i-RDRB LONG
    {"open": 105, "high": 108, "low": 103, "close": 107},  # C5 → FVG LONG (C3.high 99 < C5.low 103)
]

SHORT_ROWS = [
    {"open": 100, "high": 105, "low": 99, "close": 102},   # C1 anchor (bull body)
    {"open": 103, "high": 109, "low": 102, "close": 108},  # C2 displacement up (LONG RDRB)
    {"open": 107, "high": 110, "low": 101, "close": 104},  # C3 rejection
    {"open": 103, "high": 104, "low": 96, "close": 97},     # C4 bear reversal close<block.bottom → i-RDRB SHORT
    {"open": 96, "high": 98, "low": 92, "close": 94},       # C5 → FVG SHORT (C3.low 101 > C5.high 98)
]


def test_long_happy_path():
    sig = detect_i_rdrb_fvg(_df(LONG_ROWS), 2)
    assert sig is not None
    assert sig.direction == "LONG"
    assert sig.rdrb_direction == "SHORT"
    assert sig.block == (96.0, 98.0)
    assert sig.pattern_low == 91.0
    assert sig.pattern_high == 108.0
    # Combined-D: entry=block.top, SL=pl+0.1*(block.bottom-pl)
    assert sig.entry == pytest.approx(98.0)
    assert sig.sl == pytest.approx(91.0 + 0.1 * (96.0 - 91.0))  # 91.5
    assert sig.risk == pytest.approx(98.0 - 91.5)               # 6.5
    assert sig.fvg_zone == (99.0, 103.0)


def test_short_happy_path():
    sig = detect_i_rdrb_fvg(_df(SHORT_ROWS), 2)
    assert sig is not None
    assert sig.direction == "SHORT"
    assert sig.rdrb_direction == "LONG"
    assert sig.block == (102.0, 104.0)
    assert sig.pattern_low == 92.0
    assert sig.pattern_high == 110.0
    assert sig.entry == pytest.approx(102.0)
    assert sig.sl == pytest.approx(110.0 - 0.1 * (110.0 - 104.0))  # 109.4
    assert sig.risk == pytest.approx(109.4 - 102.0)               # 7.4
    assert sig.fvg_zone == (98.0, 101.0)


def test_edge_no_rdrb_flat():
    rows = [{"open": 100, "high": 100, "low": 100, "close": 100} for _ in range(5)]
    assert detect_i_rdrb_fvg(_df(rows), 2) is None


def test_edge_c4_no_reversal():
    # RDRB(C1-C3) валиден (SHORT), но C4 НЕ закрывается выше block.top → нет i-RDRB.
    rows = [dict(r) for r in LONG_ROWS]
    rows[3] = {"open": 97, "high": 97.5, "low": 96, "close": 97}  # close 97 < block.top 98
    assert detect_i_rdrb_fvg(_df(rows), 2) is None


def test_edge_no_matching_fvg():
    # i-RDRB LONG валиден, но C5 не образует LONG FVG (C3.high не ниже C5.low).
    rows = [dict(r) for r in LONG_ROWS]
    rows[4] = {"open": 96, "high": 100, "low": 95, "close": 97}  # low 95 < C3.high 99 → нет gap
    assert detect_i_rdrb_fvg(_df(rows), 2) is None


def test_edge_out_of_range():
    df = _df(LONG_ROWS)
    assert detect_i_rdrb_fvg(df, 1) is None          # idx<2
    assert detect_i_rdrb_fvg(df, len(df) - 1) is None  # idx+2 за границей
    assert detect_i_rdrb_fvg(_df(LONG_ROWS[:4]), 2) is None  # слишком короткий df


def test_causal_locality_future_invariant():
    # Добавление произвольных будущих свечей не меняет сигнал на idx=2 (детектор локален C1..C5).
    base = detect_i_rdrb_fvg(_df(LONG_ROWS), 2)
    extended = LONG_ROWS + [
        {"open": 107, "high": 120, "low": 80, "close": 85},
        {"open": 85, "high": 130, "low": 70, "close": 125},
    ]
    ext = detect_i_rdrb_fvg(_df(extended), 2)
    assert ext is not None and base is not None
    assert (ext.direction, ext.entry, ext.sl, ext.fvg_zone) == (
        base.direction, base.entry, base.sl, base.fvg_zone
    )


def test_detect_all_finds_single():
    sigs = detect_all_i_rdrb_fvg(_df(LONG_ROWS))
    assert len(sigs) == 1 and sigs[0].direction == "LONG"
