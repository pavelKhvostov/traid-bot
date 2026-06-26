"""Тесты стратегии Магнитуда (strategies/magnitude.py): формат сигнала, RR-фильтр, флаг-порог,
edge-кейсы, и СВЕРКА вендоренных фич с research-каноном (reversal_analysis.feats) — ловит дрейф."""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from strategies.magnitude import detect_magnitude_signals, compute_feats, FEATS  # noqa: E402

THR = 0.03
CFG = {
    "THR": THR, "CAP": 120, "flag_pct": 0.70,
    "directions": {
        "long": {"tf": "8h", "rr": [2.5, 4.0], "flag_thr": 0.367, "model": "x"},
        "short": {"tf": "12h", "rr": [1.5, 4.0], "flag_thr": 0.395, "model": "x"},
    },
}


class FakeModel:
    """predict_proba -> фиксированная p (для детерминированной проверки логики отбора)."""
    def __init__(self, p):
        self.p = p

    def predict_proba(self, X):
        return np.array([[1 - self.p, self.p]] * len(X))


def make_df(n=130, seed=0):
    rng = np.random.default_rng(seed)
    c = 100 + np.cumsum(rng.normal(0, 1, n))
    o = c + rng.normal(0, 0.5, n)
    h = np.maximum(o, c) + np.abs(rng.normal(0, 0.5, n))
    lo = np.minimum(o, c) - np.abs(rng.normal(0, 0.5, n))
    v = np.abs(rng.normal(1000, 200, n))
    idx = pd.date_range("2025-01-01", periods=n, freq="8h", tz="UTC")
    return pd.DataFrame({"open": o, "high": h, "low": lo, "close": c, "volume": v}, index=idx)


def set_last(df, close, low, high=None, open_=None):
    df = df.copy()
    i = df.index[-1]
    df.loc[i, "close"] = close; df.loc[i, "low"] = low
    df.loc[i, "high"] = high if high is not None else close + 0.5
    df.loc[i, "open"] = open_ if open_ is not None else close - 0.5
    return df


# --- счастливый путь ---
def test_long_happy_path():
    df = set_last(make_df(), close=100.0, low=99.0)   # risk=0.01 -> RR=3.0 в бакете [2.5,4)
    sigs = detect_magnitude_signals(df, "long", n_recent=1, model=FakeModel(0.9), cfg=CFG)
    assert len(sigs) == 1
    s = sigs[0]
    assert s["direction"] == "LONG" and s["tf"] == "8h"
    assert s["entry"] == 100.0 and s["sl"] == 99.0
    assert abs(s["tp"] - 103.0) < 1e-6           # +3%
    assert abs(s["rr"] - 3.0) < 0.05
    assert "signal_time" in s and "confirm_type" in s and 0 <= s["p"] <= 1


def test_short_happy_path():
    df = set_last(make_df(seed=1), close=100.0, low=99.5, high=101.0)  # risk=(101-100)/100=0.01 -> RR3
    sigs = detect_magnitude_signals(df, "short", n_recent=1, model=FakeModel(0.9), cfg=CFG)
    assert len(sigs) == 1 and sigs[0]["direction"] == "SHORT"
    assert sigs[0]["sl"] == 101.0 and abs(sigs[0]["tp"] - 97.0) < 1e-6


# --- edge cases ---
def test_below_flag_thr_no_signal():
    df = set_last(make_df(), close=100.0, low=99.0)
    sigs = detect_magnitude_signals(df, "long", n_recent=1, model=FakeModel(0.20), cfg=CFG)  # p<0.367
    assert sigs == []


def test_rr_outside_bucket_no_signal():
    # risk=0.003 -> RR=10 (>4, вне бакета) -> нет сигнала даже при высокой p
    df = set_last(make_df(), close=100.0, low=99.7)
    assert detect_magnitude_signals(df, "long", n_recent=1, model=FakeModel(0.95), cfg=CFG) == []
    # risk=0.02 -> RR=1.5 (<2.5, вне long-бакета)
    df2 = set_last(make_df(), close=100.0, low=98.0)
    assert detect_magnitude_signals(df2, "long", n_recent=1, model=FakeModel(0.95), cfg=CFG) == []


def test_short_df_returns_empty():
    assert detect_magnitude_signals(make_df(n=50), "long", model=FakeModel(0.9), cfg=CFG) == []
    assert detect_magnitude_signals(pd.DataFrame(), "long", model=FakeModel(0.9), cfg=CFG) == []


def test_bad_direction_raises():
    with pytest.raises(ValueError):
        detect_magnitude_signals(make_df(), "sideways", model=FakeModel(0.9), cfg=CFG)


# --- сверка фич с research-каноном (дрейф) ---
def test_feats_match_research_canon():
    rp = ROOT / "research" / "reversal_cb"
    if not (rp / "reversal_analysis.py").exists():
        pytest.skip("research canon недоступен")
    sys.path.insert(0, str(rp))
    try:
        from reversal_analysis import feats as canon_feats  # noqa
    except Exception as e:
        pytest.skip(f"не импортируется канон: {e}")
    df = make_df(n=200, seed=42)
    a = compute_feats(df)[FEATS]
    b = canon_feats(df)[FEATS]
    # сравнить там, где оба конечны (последние 100 баров — все окна валидны)
    aa = a.iloc[-100:].values; bb = b.iloc[-100:].values
    mask = np.isfinite(aa) & np.isfinite(bb)
    assert np.allclose(aa[mask], bb[mask], rtol=1e-9, atol=1e-9), "вендоренные фичи разошлись с research-каноном!"
