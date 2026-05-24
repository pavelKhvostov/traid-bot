import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from candle import Candle
from elements.ob_liq.code import detect_ob_liq


def test_long_ob_liq_happy_path():
    """LONG OB: prev bear с длинным нижним фитилём (LL-фрактал), cur bull с close > prev.open."""
    pm2 = Candle(open=110, high=112, low=108, close=109)   # neighbor (low=108 > 80)
    pm1 = Candle(open=109, high=111, low=107, close=108)   # neighbor (low=107 > 80)
    prev = Candle(open=108, high=109, low=80, close=105)   # bear, нижний фитиль = 105-80=25, body=3
    cur = Candle(open=105, high=120, low=104, close=119)   # bull, close 119 > prev.open 108
    # cur lower wick = min(105,119) - 104 = 1, → 25 > 3 (1×3=3) ✓
    cp1 = Candle(open=119, high=125, low=115, close=124)   # neighbor (low=115 > 80)

    r = detect_ob_liq(pm2, pm1, prev, cur, cp1)
    assert r is not None
    assert r.direction == "long"
    assert r.zone == (80, 108)              # [min(prev.low, cur.low), prev.open] = [80, 108]
    assert r.liq_zone == (80, 104)          # [prev.low, cur.low]


def test_short_ob_liq_happy_path():
    """SHORT OB: prev bull с длинным верхним фитилём (HH-фрактал), cur bear close < prev.open."""
    pm2 = Candle(open=90, high=92, low=88, close=91)
    pm1 = Candle(open=91, high=93, low=89, close=92)
    prev = Candle(open=92, high=120, low=91, close=95)     # bull, верхний фитиль = 120-95=25, body=3
    cur = Candle(open=95, high=96, low=80, close=81)       # bear, close 81 < prev.open 92
    # cur upper wick = 96 - max(95,81)=96-95=1, → 25 > 3 ✓
    cp1 = Candle(open=81, high=85, low=75, close=76)

    r = detect_ob_liq(pm2, pm1, prev, cur, cp1)
    assert r is not None
    assert r.direction == "short"
    assert r.zone == (92, 120)              # [prev.open, max(prev.high, cur.high)]
    assert r.liq_zone == (96, 120)          # [cur.high, prev.high]


def test_fails_without_3x_wick_ratio():
    """LONG: фитиль prev меньше чем 3× фитиля cur → None."""
    pm2 = Candle(open=110, high=112, low=108, close=109)
    pm1 = Candle(open=109, high=111, low=107, close=108)
    prev = Candle(open=108, high=109, low=100, close=105)  # фитиль=5
    cur = Candle(open=105, high=120, low=102, close=119)   # фитиль = min(105,119)-102 = 3
    # 5 > 3*3=9? нет → fail
    cp1 = Candle(open=119, high=125, low=115, close=124)

    assert detect_ob_liq(pm2, pm1, prev, cur, cp1) is None


def test_fails_without_fractal_ll():
    """LONG: prev.low не самый низкий среди соседей → None."""
    pm2 = Candle(open=110, high=112, low=75, close=109)    # сосед ниже prev (75 < 80)
    pm1 = Candle(open=109, high=111, low=107, close=108)
    prev = Candle(open=108, high=109, low=80, close=105)
    cur = Candle(open=105, high=120, low=104, close=119)
    cp1 = Candle(open=119, high=125, low=115, close=124)

    assert detect_ob_liq(pm2, pm1, prev, cur, cp1) is None


def test_fails_when_wick_le_body():
    """LONG: фитиль не больше тела → None."""
    pm2 = Candle(open=110, high=112, low=108, close=109)
    pm1 = Candle(open=109, high=111, low=107, close=108)
    prev = Candle(open=108, high=109, low=90, close=92)    # фитиль=2, body=16 → fail
    cur = Candle(open=92, high=120, low=91, close=119)
    cp1 = Candle(open=119, high=125, low=115, close=124)

    assert detect_ob_liq(pm2, pm1, prev, cur, cp1) is None


def test_fails_when_cur_does_not_react():
    """SHORT: cur.close >= prev.open → не SHORT OB."""
    pm2 = Candle(open=90, high=92, low=88, close=91)
    pm1 = Candle(open=91, high=93, low=89, close=92)
    prev = Candle(open=92, high=120, low=91, close=95)     # bull
    cur = Candle(open=95, high=98, low=93, close=93)       # bear но close 93 > prev.open 92 → fail
    cp1 = Candle(open=93, high=95, low=90, close=91)

    assert detect_ob_liq(pm2, pm1, prev, cur, cp1) is None
