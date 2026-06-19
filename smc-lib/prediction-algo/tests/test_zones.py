"""Тесты для prediction-algo/zones.py."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zones import (
    ActiveZone, df_to_candles, zone_snapshot, ALL_TYPES,
    _mit_wick_fill_long, _mit_wick_fill_short, _mit_first_touch,
    _mit_sweep_high, _mit_sweep_low, _mit_sweep_open_marubozu,
    _scan_ob, _scan_fvg, _scan_fractal, _scan_rb, _scan_marubozu,
    _scan_block_orders, _scan_rdrb, _scan_i_rdrb, _scan_i_fvg, _scan_ob_liq,
    _apply_mitigation, _side_and_distance,
)


def _df(bars: list[tuple]) -> pd.DataFrame:
    """Сделать DataFrame из списка (open_time_str, o, h, l, c, [v])."""
    rows = []
    idx = []
    for row in bars:
        ts = pd.Timestamp(row[0], tz="UTC")
        o, h, l, c = row[1], row[2], row[3], row[4]
        v = row[5] if len(row) > 5 else 1.0
        idx.append(ts)
        rows.append({"open": o, "high": h, "low": l, "close": c, "volume": v})
    return pd.DataFrame(rows, index=pd.DatetimeIndex(idx))


# ── Mitigation primitives ────────────────────────────────────

def test_wick_fill_long_no_touch():
    assert _mit_wick_fill_long(100.0, 110.0, 120.0) == (100.0, 110.0)


def test_wick_fill_long_compress():
    assert _mit_wick_fill_long(100.0, 110.0, 105.0) == (100.0, 105.0)


def test_wick_fill_long_consume():
    assert _mit_wick_fill_long(100.0, 110.0, 99.0) is None
    assert _mit_wick_fill_long(100.0, 110.0, 100.0) is None  # boundary touch = consumed


def test_wick_fill_short_no_touch():
    assert _mit_wick_fill_short(100.0, 110.0, 90.0) == (100.0, 110.0)


def test_wick_fill_short_compress():
    assert _mit_wick_fill_short(100.0, 110.0, 105.0) == (105.0, 110.0)


def test_wick_fill_short_consume():
    assert _mit_wick_fill_short(100.0, 110.0, 110.0) is None
    assert _mit_wick_fill_short(100.0, 110.0, 115.0) is None


def test_first_touch_no_touch():
    assert _mit_first_touch(100.0, 110.0, bar_low=90.0, bar_high=99.0) is False


def test_first_touch_yes():
    assert _mit_first_touch(100.0, 110.0, bar_low=95.0, bar_high=105.0) is True
    assert _mit_first_touch(100.0, 110.0, bar_low=110.0, bar_high=120.0) is True  # boundary touch


def test_sweep_high():
    assert _mit_sweep_high(level=100.0, bar_high=100.5) is True
    assert _mit_sweep_high(level=100.0, bar_high=100.0) is False  # strict >
    assert _mit_sweep_high(level=100.0, bar_high=99.0) is False


def test_sweep_low():
    assert _mit_sweep_low(level=100.0, bar_low=99.5) is True
    assert _mit_sweep_low(level=100.0, bar_low=100.0) is False  # strict <


def test_sweep_open_marubozu_long():
    # bull marubozu, open=low=100. Consumed когда low ≤ 100.
    assert _mit_sweep_open_marubozu(100.0, "long", bar_low=100.0, bar_high=110.0) is True
    assert _mit_sweep_open_marubozu(100.0, "long", bar_low=99.0, bar_high=110.0) is True
    assert _mit_sweep_open_marubozu(100.0, "long", bar_low=101.0, bar_high=110.0) is False


# ── Scanners на синтетике ────────────────────────────────────

def test_scan_ob_long():
    # prev bear, cur bull, cur.close > prev.open
    # OB canon zone (2026-06-14): [min(prev.low, cur.low), prev.open] = drop area
    df = _df([
        ("2024-01-01 00:00", 110, 110, 100, 100),  # bear
        ("2024-01-01 01:00", 100, 120, 100, 115),  # bull, close=115 > prev.open=110
    ])
    zs = _scan_ob(df)
    assert len(zs) == 1
    assert zs[0]["direction"] == "long"
    assert zs[0]["lo"] == 100  # min(prev.low, cur.low)
    assert zs[0]["hi"] == 110  # prev.open (canon 2026-06-14: drop area)
    assert zs[0]["born_idx"] == 1


def test_scan_fvg_long():
    # bullish FVG: c1.high < c3.low
    df = _df([
        ("2024-01-01 00:00", 100, 105, 99, 102),
        ("2024-01-01 01:00", 102, 115, 100, 113),  # displacement
        ("2024-01-01 02:00", 113, 120, 110, 118),
    ])
    zs = _scan_fvg(df)
    assert len(zs) == 1
    assert zs[0]["direction"] == "long"
    assert zs[0]["lo"] == 105  # c1.high
    assert zs[0]["hi"] == 110  # c3.low
    assert zs[0]["born_idx"] == 2


def test_scan_fractal_high_5bar():
    # FH в центре окна 5 бар
    df = _df([
        ("2024-01-01 00:00", 100, 105, 95, 100),
        ("2024-01-01 01:00", 100, 108, 95, 100),
        ("2024-01-01 02:00", 100, 115, 95, 100),  # FH center
        ("2024-01-01 03:00", 100, 110, 95, 100),
        ("2024-01-01 04:00", 100, 107, 95, 100),
    ])
    zs = _scan_fractal(df, n=2)
    assert len(zs) == 1
    assert zs[0]["direction"] == "high"
    assert zs[0]["level"] == 115
    assert zs[0]["born_idx"] == 4
    assert zs[0]["center_idx"] == 2


def test_scan_rb_top():
    # TOP RB: огромный верхний фитиль ≥ 2× нижнего и ≥ 3× тела
    df = _df([
        ("2024-01-01 00:00", 100, 130, 99, 101),  # body=1, upper=29, lower=1
    ])
    zs = _scan_rb(df)
    assert len(zs) == 1
    assert zs[0]["direction"] == "top"


def test_scan_marubozu_long():
    df = _df([
        ("2024-01-01 00:00", 100, 110, 100, 110),  # open=low, bull
    ])
    zs = _scan_marubozu(df)
    assert len(zs) == 1
    assert zs[0]["direction"] == "long"
    assert zs[0]["level"] == 100  # open level


# ── apply_mitigation ─────────────────────────────────────────

def test_apply_wick_fill_long_compress_then_consume():
    df = _df([
        ("2024-01-01 00:00", 110, 110, 100, 100),  # bear
        ("2024-01-01 01:00", 100, 120, 100, 115),  # bull → OB(long), zone=(100,115)
        ("2024-01-01 02:00", 115, 117, 108, 112),  # low=108 → compress to (100,108)
        ("2024-01-01 03:00", 112, 115, 105, 110),  # low=105 → compress to (100,105)
    ])
    ev = _scan_ob(df)[0]
    res = _apply_mitigation(ev, df, cut_off_idx=4)
    assert res == {"lo": 100, "hi": 105, "level": None}

    # консумация
    df2 = _df([
        ("2024-01-01 00:00", 110, 110, 100, 100),
        ("2024-01-01 01:00", 100, 120, 100, 115),
        ("2024-01-01 02:00", 115, 117, 95, 100),  # low=95 ≤ zone_lo=100 → consumed
    ])
    ev2 = _scan_ob(df2)[0]
    res2 = _apply_mitigation(ev2, df2, cut_off_idx=3)
    assert res2 is None


def test_apply_first_touch_rb():
    """RB canon 2026-06-15: consume на entry-level 0.5 (mid wick), не на zone boundary."""
    df = _df([
        ("2024-01-01 00:00", 100, 130, 99, 101),  # TOP RB, zone=(101,130), mid=115.5
        # high=120 ≥ 115.5 → consumed
        ("2024-01-01 01:00", 105, 120, 104, 110),
    ])
    ev = _scan_rb(df)[0]
    res = _apply_mitigation(ev, df, cut_off_idx=2)
    assert res is None


def test_apply_first_touch_rb_not_consumed_at_boundary():
    """RB canon 2026-06-15: касание края zone (но не до 0.5) — НЕ consumed."""
    df = _df([
        ("2024-01-01 00:00", 100, 130, 99, 101),  # TOP RB, zone=(101,130), mid=115.5
        # high=105 ≥ zone_lo=101 (touches) но < mid=115.5 → NOT consumed
        ("2024-01-01 01:00", 101, 105, 100, 102),
    ])
    ev = _scan_rb(df)[0]
    res = _apply_mitigation(ev, df, cut_off_idx=2)
    assert res is not None  # zone жива


def test_apply_sweep_fractal_high():
    # FH level 115, в последующем bar high=116 → sweep
    df = _df([
        ("2024-01-01 00:00", 100, 105, 95, 100),
        ("2024-01-01 01:00", 100, 108, 95, 100),
        ("2024-01-01 02:00", 100, 115, 95, 100),  # FH=115
        ("2024-01-01 03:00", 100, 110, 95, 100),
        ("2024-01-01 04:00", 100, 107, 95, 100),  # confirmation
        ("2024-01-01 05:00", 100, 116, 95, 100),  # sweep!
    ])
    ev = _scan_fractal(df, n=2)[0]
    res = _apply_mitigation(ev, df, cut_off_idx=6)
    assert res is None


def test_apply_sweep_open_marubozu():
    # marubozu open=100. После — bar low=99 → sweep open.
    df = _df([
        ("2024-01-01 00:00", 100, 110, 100, 110),  # marubozu long, open level = 100
        ("2024-01-01 01:00", 110, 112, 99, 105),    # low=99 ≤ 100 → swept
    ])
    ev = _scan_marubozu(df)[0]
    res = _apply_mitigation(ev, df, cut_off_idx=2)
    assert res is None


# ── side_and_distance ────────────────────────────────────────

def test_side_above():
    side, d = _side_and_distance(100, 110, price=90)
    assert side == "above"
    assert d == pytest.approx((100 - 90) / 90 * 100)


def test_side_below():
    side, d = _side_and_distance(100, 110, price=120)
    assert side == "below"
    assert d == pytest.approx((120 - 110) / 120 * 100)


def test_side_inside():
    side, d = _side_and_distance(100, 110, price=105)
    assert side == "inside"
    assert d == 0.0


# ── End-to-end snapshot (synthetic 1m → 5m resample) ─────────

def test_zone_snapshot_smoke_synthetic():
    """Сгенерим 1m данные где есть очевидный OB на 5m и проверим что он active в snapshot."""
    rows = []
    # Создаём 5m bar 0: bear 110→100. 1m данные с открытием 110, серия снижения до 100.
    # Каждая 1m имеет линейный downtrend.
    base_ts = pd.Timestamp("2024-01-01 00:00", tz="UTC")
    for i in range(5):
        price_open = 110 - i * 2
        price_close = 110 - (i + 1) * 2
        rows.append((base_ts + pd.Timedelta(minutes=i), price_open, price_open + 0.1, price_close - 0.1, price_close))
    # 5m bar 1: bull 100→115
    for i in range(5):
        price_open = 100 + i * 3
        price_close = 100 + (i + 1) * 3
        rows.append((base_ts + pd.Timedelta(minutes=5 + i), price_open, price_close + 0.1, price_open - 0.1, price_close))
    # потом ещё 5m баров — uptrend (зона не тронута)
    for i in range(20):
        p = 115 + i * 0.5
        rows.append((base_ts + pd.Timedelta(minutes=10 + i), p, p + 0.5, p, p + 0.5))

    df = pd.DataFrame(
        [{"open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": 1.0} for r in rows],
        index=pd.DatetimeIndex([r[0] for r in rows]),
    )

    cut = pd.Timestamp("2024-01-01 00:30", tz="UTC")
    zones = zone_snapshot(df, cut, tfs=("5m",), types=("OB",))

    # ожидаем минимум 1 OB long
    obs = [z for z in zones if z.type == "OB" and z.direction == "long"]
    assert len(obs) >= 1
    z = obs[0]
    # zone should be roughly (98.9, 115) или сжата если был тач — но в нашем uptrend не было сжатия
    assert z.tf == "5m"
    assert z.mitigation_model == "wick-fill"
    assert z.side == "below"  # OB long is BELOW current price (support after uptrend)


# ── Scanners для composite zones ─────────────────────────────

def test_scan_block_orders_long():
    # preceding bull + 2 bear (initial) + 1 bull crossing block_open (counter)
    # block_open = first.open = 110. Counter close > 110 → cross.
    df = _df([
        ("2024-01-01 00:00", 100, 102, 99, 101),  # preceding bull
        ("2024-01-01 01:00", 110, 110, 100, 105),  # initial bear #1, open=110
        ("2024-01-01 02:00", 105, 106, 95, 96),    # initial bear #2
        ("2024-01-01 03:00", 96, 115, 95, 115),    # counter bull, close=115 > 110 → cross
    ])
    zs = _scan_block_orders(df)
    assert len(zs) == 1
    assert zs[0]["direction"] == "long"
    # born_idx = 0 (preceding) + 1 + n_initial(2) + n_counter(1) - 1 = 3
    assert zs[0]["born_idx"] == 3


def test_scan_rdrb_long():
    # bullish RDRB: C2 bull, displacement up, C3 wick overlapping with C1.body_top..C1.high
    # C1: bear 102→98 (body 98..102), high=105 lower wick 95
    # C2: bull 100→115 (close > c1.high=105)
    # C3: open 115, low 103 (wick down), close 116 — wick c3 low..body_bottom overlaps with c1.body_top..c1.high
    # c3.body_bottom > c1.body_top: 115 > 102 ✓
    df = _df([
        ("2024-01-01 00:00", 102, 105, 95, 98),    # c1: bear, body=[98,102], high=105
        ("2024-01-01 01:00", 100, 116, 99, 115),   # c2: bull, close=115 > c1.high=105 ✓
        ("2024-01-01 02:00", 115, 118, 103, 116),  # c3: wick low=103 overlaps with [102, 105]
    ])
    zs = _scan_rdrb(df)
    assert len(zs) == 1
    assert zs[0]["direction"] == "long"
    assert zs[0]["born_idx"] == 2


def test_scan_ob_liq_long():
    # LONG ob_liq: prev bear, cur bull, cur.close > prev.open
    #   + lower_wick(prev) > 3*lower_wick(cur) AND > body(prev)
    # prev: bear open=110, close=105 → body=5, lower_wick = ? body_bottom=105 - low=80 = 25
    #   25 > 3*lower_wick(cur)=? and 25 > 5 ✓
    # cur: bull open=105, close=120, low=105 → lower_wick = 0 → 25 > 0 (need strict >, but 3*0=0) ✓
    df = _df([
        ("2024-01-01 00:00", 110, 112, 80, 105),  # prev bear, big lower wick
        ("2024-01-01 01:00", 105, 120, 105, 120), # cur bull, close=120 > prev.open=110
    ])
    zs = _scan_ob_liq(df)
    assert len(zs) == 1
    assert zs[0]["direction"] == "long"
    assert zs[0]["mit"] == "first-touch"


# ── End-to-end snapshot covering more types ──────────────────

def test_zone_snapshot_returns_multiple_types():
    """Используем синтетику с OB+FVG: ожидаем обе зоны в snapshot."""
    base_ts = pd.Timestamp("2024-01-01 00:00", tz="UTC")
    rows = []
    # 3 свечи, формирующие FVG long: c1, c2 displacement, c3 gap
    # c1: tight (100,99,101,100), c2: bullish jump close=115, c3: open=115 low=110 close=118
    rows.append((base_ts + pd.Timedelta(minutes=0),  100, 102, 99, 100))
    rows.append((base_ts + pd.Timedelta(minutes=1),  100, 116, 100, 115))
    rows.append((base_ts + pd.Timedelta(minutes=2),  115, 120, 110, 118))
    # ещё несколько баров up (зона не тронута)
    for k in range(20):
        p = 118 + k * 0.5
        rows.append((base_ts + pd.Timedelta(minutes=3+k), p, p+0.5, p, p+0.5))
    df = pd.DataFrame(
        [{"open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": 1.0} for r in rows],
        index=pd.DatetimeIndex([r[0] for r in rows]),
    )
    cut = pd.Timestamp("2024-01-01 00:25", tz="UTC")
    zs = zone_snapshot(df, cut, tfs=("1m",), types=("FVG",))
    longs = [z for z in zs if z.type == "FVG" and z.direction == "long"]
    # Должна быть зона из первой формации: lo=102 (c1.high), hi=110 (c3.low)
    target = next((z for z in longs if z.lo == 102 and z.hi == 110), None)
    assert target is not None
    assert target.side == "below"


def test_df_to_candles():
    df = _df([
        ("2024-01-01 00:00", 100, 105, 99, 102),
        ("2024-01-01 01:00", 102, 108, 101, 107),
    ])
    candles = df_to_candles(df)
    assert len(candles) == 2
    assert candles[0].open == 100
    assert candles[0].close == 102
    assert candles[1].high == 108
    # open_time = ms since epoch
    assert candles[0].open_time == int(pd.Timestamp("2024-01-01 00:00", tz="UTC").value // 1_000_000)
