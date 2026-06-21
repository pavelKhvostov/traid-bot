"""Тесты детектора криволинейных паттернов (research/ta_laws/curves.py)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research" / "ta_laws"))
import curves as C  # noqa: E402


def _df(close):
    close = np.asarray(close, float)
    idx = pd.date_range("2022-01-01", periods=len(close), freq="1h", tz="UTC")
    # узкие бары вокруг close, чтобы ATR был мал относительно прогиба дуги
    span = np.full(len(close), 0.5)
    return pd.DataFrame({
        "open": close, "high": close + span, "low": close - span,
        "close": close, "volume": np.ones(len(close)),
    }, index=idx)


def test_dome_detected_as_rounding_top():
    # купол: concave down (a<0), большой прогиб
    L = 40
    x = np.arange(L + 1)
    y = 100 + (-0.08) * (x - L / 2) ** 2 + 0.08 * 4  # вершина в середине
    df = _df(y)
    atr = C.compute_atr(df)
    arc = C.detect_arc(df, 0, L, atr)
    assert arc is not None
    assert arc.kind == "ROUNDING_TOP"
    assert arc.a_norm < 0
    assert arc.sagitta_atr >= C.SAGITTA_ATR_MIN
    assert arc.conf_i == L


def test_bowl_detected_as_rounding_bottom():
    L = 40
    x = np.arange(L + 1)
    y = 100 + (0.08) * (x - L / 2) ** 2  # чаша, concave up
    df = _df(y)
    atr = C.compute_atr(df)
    arc = C.detect_arc(df, 0, L, atr)
    assert arc is not None
    assert arc.kind == "ROUNDING_BOTTOM"
    assert arc.a_norm > 0


def test_straight_line_not_an_arc():
    # прямая: парабола не лучше линии -> arc_gain мал, None
    L = 40
    y = 100 + np.arange(L + 1) * 0.7
    df = _df(y)
    atr = C.compute_atr(df)
    assert C.detect_arc(df, 0, L, atr) is None


def test_flat_not_an_arc():
    L = 40
    y = np.full(L + 1, 100.0) + np.random.default_rng(0).normal(0, 0.05, L + 1)
    df = _df(y)
    atr = C.compute_atr(df)
    assert C.detect_arc(df, 0, L, atr) is None


def test_too_short_window_rejected():
    L = 8  # < ARC_MIN_BARS
    x = np.arange(L + 1)
    y = 100 - 0.5 * (x - L / 2) ** 2
    df = _df(y)
    atr = C.compute_atr(df)
    assert C.detect_arc(df, 0, L, atr) is None


def test_find_arcs_dedup_and_sorted():
    # длинный купол + длинная чаша подряд -> find_arcs находит обе, без дублей-наложений
    L = 50
    x = np.arange(L + 1)
    dome = 100 + (-0.06) * (x - L / 2) ** 2
    bowl = dome[-1] + (0.06) * (x - L / 2) ** 2 - (0.06) * (L / 2) ** 2
    y = np.concatenate([dome, bowl[1:]])
    df = _df(y)
    arcs = C.find_arcs(df, lengths=(30, 50))
    assert len(arcs) >= 1
    # отсортированы по i1
    assert all(arcs[i].i1 <= arcs[i + 1].i1 for i in range(len(arcs) - 1))
    # дедуп: пересечение принятых не больше порога
    for i in range(len(arcs)):
        for j in range(i + 1, len(arcs)):
            assert C._overlap(arcs[i], arcs[j]) <= C.OVERLAP_MAX + 1e-9


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
