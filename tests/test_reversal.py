"""Тесты разворотной структуры (reversal.py, etap_255).

Описательный детектор: форма дня (rev_up/rev_down/trend/range) + пивот, и недельный
свип PWH/PWL. Без прогноза направления — проверяем геометрию классификации, пивот и
то, что человеческие строки молчат на не-разворотных случаях.
"""
import numpy as np
import pandas as pd

from reversal import (classify_day, weekly_structure, describe_intraday,
                      describe_weekly)


def make_day(rows, start="2024-03-04 00:00"):
    """rows = список (open, high, low, close) по часам -> 1h DataFrame UTC."""
    idx = pd.date_range(start, periods=len(rows), freq="h", tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)
    df["volume"] = 1.0
    return df


def _flat(n, lvl=100.0):
    """n плоских баров вокруг lvl (для Initial Balance)."""
    return [(lvl, lvl + 1, lvl - 1, lvl) for _ in range(n)]


def test_rev_down():
    # IB ~100 (ib_h=101), затем выброс вверх до 110 и слив в 95 на закрытии
    rows = _flat(3) + [(100, 103, 99, 101)] * 6 + [(101, 110, 100, 100)] + \
           [(100, 100, 95, 95)] * 2
    rec = classify_day(make_day(rows))
    assert rec["shape"] == "rev_down" and rec["side"] == "short"
    assert rec["pivot_price"] == 110            # пивот = HoD
    assert rec["pivot_hour"] == int(np.argmax([r[1] for r in rows]))


def test_rev_up():
    # IB ~100 (ib_l=99), выброс вниз до 90 и выкуп к 105 на закрытии
    rows = _flat(3) + [(100, 101, 97, 99)] * 6 + [(99, 100, 90, 92)] + \
           [(95, 105, 95, 105)] * 2
    rec = classify_day(make_day(rows))
    assert rec["shape"] == "rev_up" and rec["side"] == "long"
    assert rec["pivot_price"] == 90             # пивот = LoD
    assert rec["pivot_hour"] == int(np.argmin([r[2] for r in rows]))


def test_trend_up():
    # монотонный рост, закрытие у максимума, малый верхний фитиль
    rows = _flat(3)
    p = 100.0
    for _ in range(10):
        p += 2
        rows.append((p - 1.5, p + 0.2, p - 1.8, p))
    rec = classify_day(make_day(rows))
    assert rec["shape"] == "trend_up" and rec["side"] == "long"


def test_trend_down():
    rows = _flat(3)
    p = 100.0
    for _ in range(10):
        p -= 2
        rows.append((p + 1.5, p + 1.8, p - 0.2, p))
    rec = classify_day(make_day(rows))
    assert rec["shape"] == "trend_down" and rec["side"] == "short"


def test_range_mid_close():
    # закрытие в середине диапазона, без больших фитилей и без явного тренда
    rows = _flat(3) + [(100, 104, 96, 100), (100, 105, 95, 101),
                       (101, 104, 97, 99), (99, 103, 96, 100),
                       (100, 104, 96, 100)]
    rec = classify_day(make_day(rows))
    assert rec["shape"] == "range" and rec["side"] == "none"


def test_too_few_bars_returns_none():
    assert classify_day(make_day(_flat(3))) is None       # < IB+2
    assert classify_day(None) is None


def test_describe_intraday_silent_on_non_reversal():
    # трендовый/боковик день не дублирует режим -> пустая строка
    trend = classify_day(make_day(_flat(3) + [(100 + i, 101 + i, 99 + i, 100 + i)
                                              for i in range(1, 11)]))
    assert describe_intraday(trend) == ""
    assert describe_intraday(None) == ""


def test_describe_intraday_reversal_has_pivot():
    rows = _flat(3) + [(100, 103, 99, 101)] * 6 + [(101, 110, 100, 100)] + \
           [(100, 100, 95, 95)] * 2
    s = describe_intraday(classify_day(make_day(rows)))
    assert "разворот ВНИЗ" in s and "пивот" in s


# --- недельная структура ---
def make_days(specs):
    """specs = список (date_str, high, low, close); open=предыдущий close (грубо)."""
    idx = pd.to_datetime([d for d, *_ in specs], utc=True)
    rows = [(c, h, l, c) for _, h, l, c in specs]  # open=close для простоты
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)


def _week(monday, hi, lo, last_close, days=7):
    base = pd.Timestamp(monday)
    out = []
    for i in range(days):
        d = (base + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
        if i == 0:
            out.append((d, hi, (hi + lo) / 2, hi))
        elif i == days - 1:
            out.append((d, last_close, lo, last_close))   # low экстремум в конце
        else:
            out.append((d, (hi + lo) / 2, lo, (hi + lo) / 2))
    return out


def test_weekly_sweep_high():
    # прошлая неделя high=120; текущая снимает 125, но закрывается ниже 120 -> sweep_high
    prev = _week("2024-01-01", hi=120, lo=80, last_close=100)
    cur = [("2024-01-08", 122, 100, 110), ("2024-01-09", 125, 105, 118),
           ("2024-01-10", 124, 108, 110)]
    rec = weekly_structure(make_days(prev + cur))
    assert rec["shape"] == "wk_sweep_high" and rec["side"] == "short"
    assert rec["pwh"] == 120
    assert "разворот ВНИЗ" in describe_weekly(rec) and "свип" in describe_weekly(rec)


def test_weekly_inside_is_silent():
    prev = _week("2024-01-01", hi=120, lo=80, last_close=100)
    cur = [("2024-01-08", 115, 90, 110), ("2024-01-09", 118, 95, 112),
           ("2024-01-10", 117, 92, 110)]   # внутри 80..120
    rec = weekly_structure(make_days(prev + cur))
    assert rec["shape"] == "wk_inside"
    assert describe_weekly(rec) == ""       # не дублирует строку позиции


def test_weekly_too_short_none():
    assert weekly_structure(make_days(_week("2024-01-01", 120, 80, 100, days=5))) is None
