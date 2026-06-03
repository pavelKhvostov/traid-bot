import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from candle import Candle
from patterns.run_3candles_sweep.code import detect_run_3candles_sweep


def test_short_happy_path_btc_8h_2026_05_26():
    """Эталон: BTC 8h SHORT 2026-05-26. wick_ratio=6.34, c2.high > c1.high."""
    c1 = Candle(open=77322, high=77345, low=76476, close=76731)   # bear
    c2 = Candle(open=76731, high=78080, low=76273, close=76518)   # bear, big upper wick
    c3 = Candle(open=76518, high=76710, low=75779, close=76115)   # bear

    r = detect_run_3candles_sweep(c1, c2, c3)
    assert r is not None
    assert r.direction == "short"
    assert r.sweep_zone == (76731, 78080)        # [max(o,c), high] of c2
    assert abs(r.entry - 77135.7) < 0.5           # 76731 + 0.3 * 1349
    assert r.sl == 78080
    assert r.tp == 75779


def test_long_happy_path_mirror():
    """Зеркальный LONG: 3 bull, c2.low < c1.low, c2.lower_wick ≥ 2.5 × body."""
    c1 = Candle(open=100, high=110, low=99, close=108)   # bull
    c2 = Candle(open=108, high=115, low=90, close=112)   # bull, big lower wick (108-90=18, body=4)
    c3 = Candle(open=112, high=125, low=111, close=120)  # bull
    r = detect_run_3candles_sweep(c1, c2, c3)
    assert r is not None
    assert r.direction == "long"
    assert r.sweep_zone == (90, 108)
    assert abs(r.entry - (108 - 0.3 * 18)) < 0.01    # 102.6
    assert r.sl == 90
    assert r.tp == 125


def test_fails_when_not_all_same_direction():
    """Mixed colors → None."""
    c1 = Candle(open=100, high=105, low=95, close=98)   # bear
    c2 = Candle(open=98, high=105, low=90, close=100)   # bull
    c3 = Candle(open=100, high=102, low=95, close=97)   # bear
    assert detect_run_3candles_sweep(c1, c2, c3) is None


def test_fails_without_wick_takes_c1_high_short():
    """SHORT: c2.high не выше c1.high → None."""
    c1 = Candle(open=100, high=110, low=95, close=98)   # bear, high=110
    c2 = Candle(open=98, high=109, low=85, close=95)    # bear, c2.high=109 < c1.high=110
    c3 = Candle(open=95, high=96, low=85, close=90)     # bear
    assert detect_run_3candles_sweep(c1, c2, c3) is None


def test_fails_without_25x_wick_body_ratio_short():
    """SHORT: c2.upper_wick < 2.5 × body → None."""
    c1 = Candle(open=100, high=102, low=95, close=98)
    c2 = Candle(open=98, high=105, low=90, close=92)    # bear, upper_wick=7, body=6, ratio=1.17
    c3 = Candle(open=92, high=93, low=85, close=88)
    assert detect_run_3candles_sweep(c1, c2, c3) is None


def test_fails_when_c2_is_doji():
    """c2 doji (body=0) → None."""
    c1 = Candle(open=100, high=102, low=95, close=98)   # bear
    c2 = Candle(open=98, high=110, low=95, close=98)    # doji
    c3 = Candle(open=98, high=99, low=90, close=92)
    assert detect_run_3candles_sweep(c1, c2, c3) is None


def test_short_entry_sl_tp_geometry():
    """Sanity: entry ниже SL, TP ниже entry; SHORT — RR положительный."""
    c1 = Candle(open=100, high=102, low=95, close=98)
    c2 = Candle(open=98, high=120, low=90, close=92)    # upper_wick=22, body=6, ratio=3.67
    c3 = Candle(open=92, high=93, low=85, close=88)
    r = detect_run_3candles_sweep(c1, c2, c3)
    assert r is not None
    assert r.entry < r.sl, "entry must be below SL for SHORT"
    assert r.tp < r.entry, "TP must be below entry for SHORT"
