import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from candle import Candle
from elements.ob_liq.code import detect_ob_liq


def test_long_ob_liq_happy_path():
    """LONG OB: prev bear с длинным нижним фитилём, cur bull с close > prev.open."""
    prev = Candle(open=108, high=109, low=80, close=105)   # bear, нижний фитиль = 105-80=25, body=3
    cur = Candle(open=105, high=120, low=104, close=119)   # bull, close 119 > prev.open 108
    # cur lower wick = min(105,119) - 104 = 1, → 25 > 3 (1×3=3) ✓

    r = detect_ob_liq(prev, cur)
    assert r is not None
    assert r.direction == "long"
    assert r.zone == (80, 108)              # [min(prev.low, cur.low), prev.open] = [80, 108]
    assert r.liq_zone == (80, 104)          # [prev.low, cur.low]


def test_short_ob_liq_happy_path():
    """SHORT OB: prev bull с длинным верхним фитилём, cur bear close < prev.open."""
    prev = Candle(open=92, high=120, low=91, close=95)     # bull, верхний фитиль = 120-95=25, body=3
    cur = Candle(open=95, high=96, low=80, close=81)       # bear, close 81 < prev.open 92
    # cur upper wick = 96 - max(95,81)=96-95=1, → 25 > 3 ✓

    r = detect_ob_liq(prev, cur)
    assert r is not None
    assert r.direction == "short"
    assert r.zone == (92, 120)              # [prev.open, max(prev.high, cur.high)]
    assert r.liq_zone == (96, 120)          # [cur.high, prev.high]


def test_fails_without_3x_wick_ratio():
    """LONG: фитиль prev меньше чем 3× фитиля cur → None."""
    prev = Candle(open=108, high=109, low=100, close=105)  # фитиль=5
    cur = Candle(open=105, high=120, low=102, close=119)   # фитиль = min(105,119)-102 = 3
    # 5 > 3*3=9? нет → fail
    assert detect_ob_liq(prev, cur) is None


def test_fails_when_wick_le_body():
    """LONG: фитиль не больше тела → None."""
    prev = Candle(open=108, high=109, low=90, close=92)    # фитиль=2, body=16 → fail
    cur = Candle(open=92, high=120, low=91, close=119)
    assert detect_ob_liq(prev, cur) is None


def test_fails_when_cur_does_not_react():
    """SHORT: cur.close >= prev.open → не SHORT OB."""
    prev = Candle(open=92, high=120, low=91, close=95)     # bull
    cur = Candle(open=95, high=98, low=93, close=93)       # bear но close 93 > prev.open 92 → fail
    assert detect_ob_liq(prev, cur) is None


def test_no_williams_neighbors_needed():
    """Подтверждение: ob_liq НЕ требует Williams 5-bar HH/LL после 2026-05-27.
    Раньше тест test_fails_without_fractal_ll fail-ил бы на prev с соседом ниже —
    теперь это не препятствие.
    """
    # Тот же prev/cur что в happy_path — но НЕ важно какие соседи (их вообще не передаём)
    prev = Candle(open=108, high=109, low=80, close=105)
    cur = Candle(open=105, high=120, low=104, close=119)
    assert detect_ob_liq(prev, cur) is not None
