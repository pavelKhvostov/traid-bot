"""Тесты геометрии ТА-паттернов (research/ta_laws/geometry.py).

Синтетика: ramp() строит кусочно-линейный close-путь, make_df() -> OHLC.
Покрыто: zigzag-пивоты, импульс, классификатор коррекции (флаг/вымпел), архетип, edge.
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "ta_laws"))
import geometry as G  # noqa: E402


def ramp(start, segs):
    out = [float(start)]
    for tgt, nb in segs:
        out.extend(np.linspace(out[-1], tgt, nb + 1)[1:].tolist())
    return out


def make_df(closes, w=None):
    c = np.asarray(closes, float)
    o = np.concatenate([[c[0]], c[:-1]])
    if w is None:
        w = 0.15 * np.mean(np.abs(np.diff(c))) + 1e-9
    hi = np.maximum(o, c) + w
    lo = np.minimum(o, c) - w
    idx = pd.date_range("2024-01-01", periods=len(c), freq="1h", tz="UTC")
    return pd.DataFrame({"open": o, "high": hi, "low": lo, "close": c, "volume": 1.0}, index=idx)


def _piv(i, p, kind):
    return G.Pivot(i=i, time=pd.Timestamp("2024-01-01", tz="UTC"), price=float(p), kind=kind)


DUMMY_IMP_DOWN = G.Impulse("DOWN", 0, 25, pd.Timestamp("2024-01-01", tz="UTC"),
                           pd.Timestamp("2024-01-02", tz="UTC"), 100.0, 60.0, 25, 40.0, 22.0, 0.95)


def test_zigzag_alternating_pivots():
    df = make_df(ramp(0, [(20, 20), (0, 20), (20, 20)]))
    piv = G.zigzag(df)
    assert len(piv) >= 2
    assert piv[0].kind == "H" and abs(piv[0].price - 20) < 1.5
    assert piv[1].kind == "L" and abs(piv[1].price - 0) < 1.5
    kinds = [p.kind for p in piv]
    assert all(kinds[k] != kinds[k + 1] for k in range(len(kinds) - 1))  # чередуются


def test_find_impulse_down():
    df = make_df(ramp(90, [(100, 15), (60, 25), (65, 4), (61, 4), (66, 4), (62, 4), (67, 4)]))
    atr = G.compute_atr(df)
    imps = G.find_impulses(df, G.zigzag(df), atr)
    downs = [i for i in imps if i.direction == "DOWN"]
    assert downs, "должен найтись DOWN-импульс"
    assert max(i.atr_mag for i in downs) >= 3.5
    assert max(i.efficiency for i in downs) >= G.IMP_MIN_EFF


def test_classify_flag_rising_channel():
    # восходящий параллельный канал после down-импульса -> FLAG (против импульса)
    corr = [_piv(0, 8, "L"), _piv(5, 10, "H"), _piv(10, 10, "L"), _piv(15, 12, "H")]
    c = G.classify_correction(corr, DUMMY_IMP_DOWN, atr_at=1.0)
    assert c is not None
    assert c.kind == "FLAG"
    assert c.against_impulse is True
    assert c.su_norm > 0 and c.sl_norm > 0 and not c.converging


def test_classify_pennant_converging():
    corr = [_piv(0, 12, "H"), _piv(2, 8, "L"), _piv(10, 11, "H"), _piv(12, 9, "L")]
    c = G.classify_correction(corr, DUMMY_IMP_DOWN, atr_at=1.0)
    assert c is not None
    assert c.kind == "PENNANT"
    assert c.converging is True
    assert c.su_norm < 0 < c.sl_norm


def test_find_archetype_impulse_plus_flag():
    df = make_df(ramp(90, [(100, 15), (60, 25), (65, 4), (61, 4), (66, 4), (62, 4), (67, 4)]))
    arts = G.find_archetypes(df)
    downs = [a for a in arts if a.continuation_dir == "DOWN"]
    assert downs, "должен найтись архетип импульс-вниз + коррекция"
    a = downs[0]
    assert a.measured_move_tp < a.breakout_level         # measured move вниз
    assert a.correction.kind in {"FLAG", "CHANNEL", "RISING_WEDGE", "PENNANT", "ASC_TRI"}
    assert a.correction.against_impulse is True


def test_edge_flat_no_patterns():
    df = make_df([100.0] * 60)
    assert G.zigzag(df) == []
    assert G.find_archetypes(df) == []


def test_edge_too_few_corr_pivots():
    corr = [_piv(0, 10, "H"), _piv(5, 8, "L")]  # <2 каждого типа
    assert G.classify_correction(corr, DUMMY_IMP_DOWN, atr_at=1.0) is None
