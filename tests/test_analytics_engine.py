"""Тесты чистых law-функций модуля аналитики (research/analytics_engine.py).

Зона-движок Вадима — интеграционный (smc-lib), здесь юнит-тестим ЗАКОНЫ:
magnet_against (драг зон-магнитов), realistic_tp (цель = ближайший магнит ≤ extent), _trend.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research import analytics_engine as AE  # noqa: E402


def Z(tf="4h", type="OB", side="below", distance_pct=1.0, age_bars=10, level=None, lo=100.0, hi=101.0):
    return SimpleNamespace(tf=tf, type=type, side=side, distance_pct=distance_pct,
                           age_bars=age_bars, level=level, lo=lo, hi=hi)


def test_magnet_against_long_counts_zones_below():
    price = 100.0
    zones = [Z(side="below", distance_pct=1.0, tf="12h", type="OB", lo=98, hi=99)]
    long_drag = AE.magnet_against(zones, price, "LONG")
    short_drag = AE.magnet_against(zones, price, "SHORT")
    assert long_drag > 0           # для LONG магнит снизу = драг против
    assert short_drag == 0         # для SHORT зон сверху нет


def test_magnet_against_more_zones_more_drag():
    price = 100.0
    one = [Z(side="below", distance_pct=1.0)]
    many = [Z(side="below", distance_pct=1.0), Z(side="below", distance_pct=1.5, tf="12h"),
            Z(side="below", distance_pct=2.0, tf="1d")]
    assert AE.magnet_against(many, price, "LONG") > AE.magnet_against(one, price, "LONG")


def test_magnet_higher_tf_stronger():
    price = 100.0
    low = [Z(side="below", distance_pct=1.0, tf="4h")]
    high = [Z(side="below", distance_pct=1.0, tf="1d")]
    assert AE.magnet_against(high, price, "LONG") > AE.magnet_against(low, price, "LONG")


def test_realistic_tp_picks_nearest_zone_in_direction():
    price = 100.0; atr = 1.0
    zones = [Z(side="above", distance_pct=1.0, level=101.0),
             Z(side="above", distance_pct=2.0, level=102.0)]
    tp = AE.realistic_tp(zones, price, "LONG", atr)
    assert abs(tp - 101.0) < 1e-6   # ближайший магнит сверху


def test_realistic_tp_capped_by_extent():
    price = 100.0; atr = 1.0
    far = [Z(side="above", distance_pct=10.0, level=120.0)]   # магнит далеко
    tp = AE.realistic_tp(far, price, "LONG", atr)
    assert tp <= price + AE.MAX_EXT_ATR * atr + 1e-6          # обрезан масштаб-законом


def test_realistic_tp_fallback_no_zone():
    price = 100.0; atr = 2.0
    tp = AE.realistic_tp([], price, "LONG", atr)
    assert abs(tp - (price + AE.SL_ATR * AE.RR * atr)) < 1e-6  # extent-fallback


def test_trend_up_down():
    idx = pd.date_range("2022-01-01", periods=50, freq="1h", tz="UTC")
    up = pd.Series(np.arange(50.0), index=idx)
    dn = pd.Series(np.arange(50.0)[::-1], index=idx)
    ts = idx[-1]
    assert AE._trend(up, ts, pd.Timedelta(hours=10)) == "UP"
    assert AE._trend(dn, ts, pd.Timedelta(hours=10)) == "DOWN"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
