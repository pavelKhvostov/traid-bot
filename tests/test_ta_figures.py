"""Тесты детекторов фигур (research/ta_laws/figures.py): DT/DB/HS + edge."""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "ta_laws"))
import figures as F  # noqa: E402


def ramp(start, segs):
    out = [float(start)]
    for tgt, nb in segs:
        out.extend(np.linspace(out[-1], tgt, nb + 1)[1:].tolist())
    return out


def make_df(closes, w=None):
    c = np.asarray(closes, float)
    o = np.concatenate([[c[0]], c[:-1]])
    if w is None:
        w = 0.12 * np.mean(np.abs(np.diff(c))) + 1e-9
    hi = np.maximum(o, c) + w
    lo = np.minimum(o, c) - w
    idx = pd.date_range("2024-01-01", periods=len(c), freq="1h", tz="UTC")
    return pd.DataFrame({"open": o, "high": hi, "low": lo, "close": c, "volume": 1.0}, index=idx)


def kinds(figs):
    return {f.kind for f in figs}


def test_double_top():
    df = make_df(ramp(80, [(100, 20), (90, 10), (100, 10), (90, 10)]))
    figs = F.find_figures(df)
    dt = [f for f in figs if f.kind == "DOUBLE_TOP"]
    assert dt, f"ожидался DOUBLE_TOP, нашли {kinds(figs)}"
    f = dt[0]
    assert f.expected_dir == "DOWN"
    assert abs(f.neckline - 90) < 2
    assert f.height > 0


def test_double_bottom():
    df = make_df(ramp(120, [(100, 20), (110, 10), (100, 10), (110, 10)]))
    figs = F.find_figures(df)
    db = [f for f in figs if f.kind == "DOUBLE_BOTTOM"]
    assert db, f"ожидался DOUBLE_BOTTOM, нашли {kinds(figs)}"
    assert db[0].expected_dir == "UP"
    assert abs(db[0].neckline - 110) < 2


def test_head_shoulders():
    df = make_df(ramp(90, [(100, 15), (95, 8), (108, 12), (95, 12), (100, 10), (92, 10)]))
    figs = F.find_figures(df)
    hs = [f for f in figs if f.kind == "HEAD_SHOULDERS"]
    assert hs, f"ожидался HEAD_SHOULDERS, нашли {kinds(figs)}"
    f = hs[0]
    assert f.expected_dir == "DOWN"
    assert abs(f.neckline - 95) < 2.5
    assert f.height > 0


def test_inverse_head_shoulders():
    df = make_df(ramp(110, [(100, 15), (105, 8), (92, 12), (105, 12), (100, 10), (108, 10)]))
    figs = F.find_figures(df)
    ihs = [f for f in figs if f.kind == "INV_HEAD_SHOULDERS"]
    assert ihs, f"ожидался INV_HEAD_SHOULDERS, нашли {kinds(figs)}"
    assert ihs[0].expected_dir == "UP"


def test_edge_flat_none():
    df = make_df([100.0] * 80)
    assert F.find_figures(df) == []


def test_edge_unequal_tops_not_double_top():
    # вершины сильно разные -> НЕ double top
    df = make_df(ramp(80, [(100, 20), (90, 10), (115, 12), (95, 10)]))
    figs = F.find_figures(df)
    assert "DOUBLE_TOP" not in kinds(figs)
