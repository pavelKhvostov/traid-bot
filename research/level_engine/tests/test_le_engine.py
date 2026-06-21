"""Тесты движка силы уровней — ядро = ПРИЧИННОСТЬ (нет утечки будущего)."""
import pandas as pd
import numpy as np
import pytest

import le_zones as LZ
import le_interact as LI
import le_belief as LB
import le_engine as LE
from data_manager import load_df


def _mk1h(rows, start="2024-01-02 00:00"):
    idx = pd.date_range(start, periods=len(rows), freq="h", tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)
    df["volume"] = 1.0
    return df


def _atr_const(df, v=1.0):
    di = pd.date_range(df.index[0].normalize() - pd.Timedelta(days=1),
                       df.index[-1].normalize() + pd.Timedelta(days=1), freq="D", tz="UTC")
    return pd.Series(v, index=di)


# ---- interaction classes ----
def test_reject_class():
    df = _mk1h([(105, 105, 104.5, 105), (101.4, 101.6, 101, 101.5),
                (103.5, 104, 103, 103.7), (104, 104.5, 103.5, 104)])
    ev = LI.replay_interactions(100, 102, df.index[0], df, _atr_const(df))
    assert len(ev) == 1 and ev[0].cls == "REJECT" and ev[0].t_resolved >= ev[0].t_touch


def test_break_class():
    df = _mk1h([(105, 105, 104.5, 105), (101.4, 101.6, 101, 101),
                (99.2, 99.4, 98.8, 99), (98, 98.5, 97.5, 98)])
    ev = LI.replay_interactions(100, 102, df.index[0], df, _atr_const(df))
    assert ev[0].cls == "BREAK"


def test_flip_class():
    df = _mk1h([(105, 105, 104.5, 105), (101.4, 101.6, 101, 101), (98.2, 98.4, 97.8, 98),
                (99, 99.5, 98.5, 99), (101, 101.5, 99.4, 99.8), (98, 99, 97, 98)])
    ev = LI.replay_interactions(100, 102, df.index[0], df, _atr_const(df))
    cls = [e.cls for e in ev]
    assert "BREAK" in cls and "FLIP" in cls


# ---- belief monotonicity ----
def _rz(kind, tf, b, t, ft):
    return LZ.RawZone(kind, tf, "LONG", b, t, pd.Timestamp(ft, tz="UTC"), {})


def _inter(cls, m, t):
    tt = pd.Timestamp(t, tz="UTC")
    return LI.Interaction(tt, tt, cls, m, 1.0, {})


def test_belief_freshness_more_touches_not_stronger():
    # LE-STR v2 фикс инверсии: больше касаний -> НЕ сильнее (свежесть декрементирует)
    members = [_rz("OB", "1d", 100, 102, "2024-01-01")]
    T = pd.Timestamp("2024-06-01", tz="UTC")
    few = LB.belief(members, [_inter("REJECT", 2, "2024-05-20")], T)
    many = LB.belief(members, [_inter("REJECT", 2, f"2024-05-2{d}") for d in range(1, 9)], T)
    assert many["touches"] > few["touches"]
    assert LB.strength10(many)[0] <= LB.strength10(few)[0]   # затёртая зона НЕ сильнее свежей
    assert many["fresh_gate"] < few["fresh_gate"]


def test_belief_breaks_weaken():
    members = [_rz("OB", "1d", 100, 102, "2024-01-01")]
    T = pd.Timestamp("2024-06-01", tz="UTC")
    held = LB.belief(members, [_inter("REJECT", 2, "2024-05-25")], T)
    broke = LB.belief(members, [_inter("BREAK", 2, "2024-05-25")], T)
    assert LB.strength10(broke)[0] < LB.strength10(held)[0]


def test_belief_causal_filters_future_interactions():
    members = [_rz("OB", "1d", 100, 102, "2024-01-01")]
    T = pd.Timestamp("2024-03-01", tz="UTC")
    # реакция, разрешённая ПОСЛЕ T, не должна влиять
    fut = LB.belief(members, [_inter("REJECT", 4, "2024-05-01")], T)
    base = LB.belief(members, [], T)
    assert fut["n_used"] == 0 and LB.strength10(fut)[0] == LB.strength10(base)[0]


# ---- THE causal guarantee: future-mutation invariance on real data ----
@pytest.fixture(scope="module")
def btc():
    df = load_df("BTCUSDT", "1h")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df


def test_snapshot_future_mutation_invariance(btc):
    T = pd.Timestamp("2025-06-01 00:00", tz="UTC")
    full = LE.snapshot(btc, T)                       # есть будущие бары > T
    trunc = LE.snapshot(btc[btc.index <= T], T)      # будущего нет
    assert full["n_levels"] == trunc["n_levels"] and full["price"] == trunc["price"]
    fk = [(L["lid"], L["strength"], L["state"], L["rejects"], L["breaks"]) for L in full["levels"]]
    tk = [(L["lid"], L["strength"], L["state"], L["rejects"], L["breaks"]) for L in trunc["levels"]]
    assert fk == tk, "future bars changed the as-of-T snapshot -> LOOKAHEAD LEAK"


def test_zones_no_form_time_after_T(btc):
    T = pd.Timestamp("2024-09-20 00:00", tz="UTC")
    raws = LZ.build_raw_zones(btc, T, window_usd=15000)
    assert raws and all(pd.Timestamp(z.form_time) <= T for z in raws)
