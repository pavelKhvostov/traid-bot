"""Тесты для labels.py."""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zones import ActiveZone
from labels import label_zone, label_zones, _zone_hit_predicate


def _make_1m_future(prices: list[tuple[int, float, float, float, float]], cut_off_ts: pd.Timestamp) -> pd.DataFrame:
    """prices = list of (minutes_after_cutoff, open, high, low, close)."""
    rows = []
    idx = []
    for m, o, h, l, c in prices:
        idx.append(cut_off_ts + pd.Timedelta(minutes=m))
        rows.append({"open": o, "high": h, "low": l, "close": c, "volume": 1.0})
    return pd.DataFrame(rows, index=pd.DatetimeIndex(idx))


def _zone(type_, direction, lo, hi, level=None, side="below"):
    return ActiveZone(
        tf="1h", type=type_, direction=direction, lo=lo, hi=hi, level=level,
        born_ts=pd.Timestamp("2024-01-01", tz="UTC"), age_bars=0,
        side=side, distance_pct=1.0, mitigation_model="wick-fill",
    )


# ── Hit predicate ────────────────────────────────────────────

def test_predicate_long_zone_hit_from_above():
    z = _zone("OB", "long", lo=100, hi=110)
    p = _zone_hit_predicate(z)
    assert p(115, 109) is True   # low=109 ≤ hi=110 → hit
    assert p(115, 110) is True   # boundary
    assert p(115, 111) is False  # low > hi


def test_predicate_short_zone_hit_from_below():
    z = _zone("OB", "short", lo=100, hi=110)
    p = _zone_hit_predicate(z)
    assert p(99, 90) is False
    assert p(100, 95) is True
    assert p(105, 95) is True


def test_predicate_fractal_high():
    z = _zone("fractal", "high", lo=100, hi=100, level=100)
    p = _zone_hit_predicate(z)
    assert p(100, 99) is False  # strict >
    assert p(100.01, 99) is True


def test_predicate_fractal_low():
    z = _zone("fractal", "low", lo=100, hi=100, level=100)
    p = _zone_hit_predicate(z)
    assert p(101, 100) is False  # strict <
    assert p(101, 99.99) is True


def test_predicate_marubozu_long_open_sweep():
    # marubozu long, open level = 100
    z = _zone("marubozu", "long", lo=100, hi=110, level=100)
    p = _zone_hit_predicate(z)
    assert p(105, 100) is True   # touch ≤
    assert p(105, 99) is True
    assert p(105, 101) is False


def test_predicate_rb_top():
    z = _zone("RB", "top", lo=100, hi=110)  # top RB = short-like (resistance)
    p = _zone_hit_predicate(z)
    assert p(100, 95) is True
    assert p(99, 95) is False


def test_predicate_rb_bottom():
    z = _zone("RB", "bottom", lo=100, hi=110)  # bottom RB = long-like (support)
    p = _zone_hit_predicate(z)
    assert p(105, 110) is True
    assert p(105, 111) is False


# ── Labelling ─────────────────────────────────────────────────

def test_label_zone_hit_within_12h():
    cut = pd.Timestamp("2024-01-01 00:00", tz="UTC")
    z = _zone("OB", "long", lo=100, hi=110)
    df = _make_1m_future([
        (10, 115, 116, 113, 115),  # no hit (low=113 > hi=110)
        (60, 113, 114, 109, 111),  # HIT (low=109 ≤ 110), 60 min after cut
        (120, 111, 113, 108, 109),
    ], cut)
    lbl = label_zone(z, df, cut)
    assert lbl.hit_12h is True
    assert lbl.hit_D is True
    assert lbl.time_to_hit_minutes == 60
    assert lbl.first_hit_horizon == "12h"


def test_label_zone_hit_within_D_only():
    cut = pd.Timestamp("2024-01-01 00:00", tz="UTC")
    z = _zone("OB", "long", lo=100, hi=110)
    df = _make_1m_future([
        (300, 115, 116, 113, 115),  # no hit
        (900, 113, 114, 109, 111),  # HIT (900 min = 15h)
    ], cut)
    lbl = label_zone(z, df, cut)
    assert lbl.hit_12h is False     # > 12h
    assert lbl.hit_D is True         # ≤ 24h
    assert lbl.time_to_hit_minutes == 900
    assert lbl.first_hit_horizon == "D"


def test_label_zone_no_hit():
    cut = pd.Timestamp("2024-01-01 00:00", tz="UTC")
    z = _zone("OB", "long", lo=100, hi=110)
    df = _make_1m_future([
        (60, 120, 125, 115, 122),
        (120, 122, 130, 118, 125),
    ], cut)
    lbl = label_zone(z, df, cut)
    assert lbl.hit_12h is False
    assert lbl.hit_D is False
    assert lbl.time_to_hit_minutes is None
    assert lbl.first_hit_horizon is None


def test_label_zones_first_hit_above_and_below():
    cut = pd.Timestamp("2024-01-01 00:00", tz="UTC")
    # 3 зоны выше (above), 2 ниже (below)
    above1 = _zone("OB", "short", lo=120, hi=130, side="above")
    above2 = _zone("FVG", "short", lo=140, hi=150, side="above")
    below1 = _zone("OB", "long", lo=80, hi=90, side="below")
    below2 = _zone("FVG", "long", lo=60, hi=70, side="below")
    # 1m данные: цена 100, идёт вверх до 125 (hits above1), потом вниз до 85 (hits below1)
    df = _make_1m_future([
        (10, 100, 110, 100, 108),
        (30, 108, 121, 105, 115),  # above1 hit (high=121 ≥ 120)
        (60, 115, 125, 115, 118),
        (120, 118, 119, 85, 87),    # below1 hit (low=85 ≤ 90)
        (200, 87, 88, 80, 82),
    ], cut)
    labels = label_zones([above1, above2, below1, below2], df, cut)
    # above1 — first hit above
    assert labels[0].first_hit_above is True
    assert labels[0].first_hit_below is False
    # above2 — not hit (price max 125 < 140)
    assert labels[1].hit_12h is False
    assert labels[1].first_hit_above is False
    # below1 — first hit below
    assert labels[2].first_hit_below is True
    assert labels[2].first_hit_above is False
    # below2 — not hit (price min 80 not ≤ 70)
    assert labels[3].hit_12h is False


def test_label_zone_inside_immediate_hit():
    """Если zone.side == 'inside', price УЖЕ внутри — первый 1m bar даст hit."""
    cut = pd.Timestamp("2024-01-01 00:00", tz="UTC")
    z = _zone("OB", "long", lo=100, hi=110, side="inside")
    df = _make_1m_future([
        (1, 105, 107, 104, 106),  # внутри зоны → hit (low=104 ≤ hi=110)
    ], cut)
    lbl = label_zone(z, df, cut)
    assert lbl.hit_12h is True
    assert lbl.time_to_hit_minutes == 1


def test_label_empty_future_no_hit():
    cut = pd.Timestamp("2024-01-01 00:00", tz="UTC")
    z = _zone("OB", "long", lo=100, hi=110)
    df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"], index=pd.DatetimeIndex([], tz="UTC"))
    lbl = label_zone(z, df, cut)
    assert lbl.hit_12h is False
    assert lbl.time_to_hit_minutes is None
