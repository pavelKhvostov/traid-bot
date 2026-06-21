"""Тесты для model.py — Phase 1 lookup модели."""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model import LookupModel, distance_bucket, age_bucket, add_buckets


def test_distance_bucket_boundaries():
    assert distance_bucket(0.0) == "0-0.1"
    assert distance_bucket(0.05) == "0-0.1"
    assert distance_bucket(0.1) == "0.1-0.3"
    assert distance_bucket(0.2) == "0.1-0.3"
    assert distance_bucket(0.3) == "0.3-1"
    assert distance_bucket(0.99) == "0.3-1"
    assert distance_bucket(1.0) == "1-3"
    assert distance_bucket(2.5) == "1-3"
    assert distance_bucket(3.0) == "3-10"
    assert distance_bucket(9.9) == "3-10"
    assert distance_bucket(10.0) == "10+"
    assert distance_bucket(99.0) == "10+"


def test_age_bucket_boundaries():
    assert age_bucket(0) == "0"
    assert age_bucket(1) == "1-5"
    assert age_bucket(5) == "1-5"
    assert age_bucket(6) == "6-19"
    assert age_bucket(19) == "6-19"
    assert age_bucket(20) == "20-99"
    assert age_bucket(99) == "20-99"
    assert age_bucket(100) == "100+"
    assert age_bucket(99999) == "100+"


def test_add_buckets():
    df = pd.DataFrame({
        "distance_pct": [0.05, 1.5, 11.0],
        "age_bars": [0, 5, 200],
    })
    out = add_buckets(df)
    assert list(out["dist_bucket"]) == ["0-0.1", "1-3", "10+"]
    assert list(out["age_bucket"]) == ["0", "1-5", "100+"]


def _train_df():
    """Synthetic training data: 4 buckets с разными hit-rates."""
    rows = []
    # Bucket (1h, OB, below, 0-0.1, 0): 100 zones, 80% hit_D
    for i in range(100):
        rows.append({"tf": "1h", "type": "OB", "side": "below", "distance_pct": 0.05, "age_bars": 0,
                     "hit_12h": i < 60, "hit_D": i < 80})
    # Bucket (1h, OB, below, 3-10, 0): 100 zones, 5% hit_D
    for i in range(100):
        rows.append({"tf": "1h", "type": "OB", "side": "below", "distance_pct": 5.0, "age_bars": 0,
                     "hit_12h": i < 3, "hit_D": i < 5})
    # Bucket (4h, FVG, above, 0-0.1, 0): 100 zones, 50% hit_D
    for i in range(100):
        rows.append({"tf": "4h", "type": "FVG", "side": "above", "distance_pct": 0.05, "age_bars": 0,
                     "hit_12h": i < 30, "hit_D": i < 50})
    return pd.DataFrame(rows)


def test_lookup_full_bucket_hit():
    train = _train_df()
    m = LookupModel.fit(train, min_count=10, alpha=1.0)
    # запрашиваем точно совпадающий bucket
    test = pd.DataFrame([{
        "tf": "1h", "type": "OB", "side": "below", "distance_pct": 0.05, "age_bars": 0,
    }])
    preds = m.predict(test)
    p_d = preds.iloc[0]["P_hit_D"]
    # с alpha=1 и n=100: (80*100 + 0.30*1)/101 ≈ 0.793 (близко к 0.80)
    assert 0.78 < p_d < 0.82
    assert preds.iloc[0]["bucket_used"] == "full"
    assert preds.iloc[0]["n_train"] == 100


def test_lookup_fallback_to_global():
    train = _train_df()
    m = LookupModel.fit(train, min_count=10, alpha=1.0)
    # запрос с tf'ом которого нет в training
    test = pd.DataFrame([{
        "tf": "1w", "type": "fractal", "side": "inside", "distance_pct": 50.0, "age_bars": 200,
    }])
    preds = m.predict(test)
    # должно сфолбэкнуться на global
    assert preds.iloc[0]["bucket_used"] == "global"
    # global hit_D ~= среднее по всем 300 rows = (80+5+50)/300 = 0.45
    assert 0.40 < preds.iloc[0]["P_hit_D"] < 0.50


def test_lookup_intermediate_fallback():
    train = _train_df()
    m = LookupModel.fit(train, min_count=10, alpha=1.0)
    # запрос с известными (tf, type, side, dist_bucket) но новый age — должен фолбэкнуться на no_age
    # Создаём train где есть только age=0, запрашиваем age=200
    test = pd.DataFrame([{
        "tf": "1h", "type": "OB", "side": "below", "distance_pct": 0.05, "age_bars": 200,
    }])
    preds = m.predict(test)
    assert preds.iloc[0]["bucket_used"] in ("no_age", "type_side", "side")  # любой intermediate
    # для этого bucket (tf=1h, type=OB, side=below, dist=0-0.1) — n=100, hit_D ≈ 80%
    assert 0.75 < preds.iloc[0]["P_hit_D"] < 0.85


def test_min_count_threshold():
    train = _train_df()
    m = LookupModel.fit(train, min_count=200, alpha=1.0)  # threshold выше n=100
    test = pd.DataFrame([{
        "tf": "1h", "type": "OB", "side": "below", "distance_pct": 0.05, "age_bars": 0,
    }])
    preds = m.predict(test)
    # full bucket имеет n=100 < min_count=200 → fallback
    assert preds.iloc[0]["bucket_used"] != "full"


def test_predict_preserves_rows():
    train = _train_df()
    m = LookupModel.fit(train, min_count=10, alpha=1.0)
    test = train[["tf", "type", "side", "distance_pct", "age_bars"]].head(5)
    preds = m.predict(test)
    assert len(preds) == 5
    assert set(preds.columns) == {"P_hit_12h", "P_hit_D", "bucket_used", "n_train"}
