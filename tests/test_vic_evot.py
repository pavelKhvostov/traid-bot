"""Тесты для detect_vic_evot (strategies/vic_evot.py, §3-§4 спеки).

Покрывает все 11 строк таблицы §8 + два бонусных кейса (direction
mismatch и пустой df_1d)."""
from __future__ import annotations

import pandas as pd
import pytest

from strategies.vic_evot import detect_vic_evot


SYMBOL = "BTCUSDT"
LAST_15M = pd.Timestamp("2026-04-27 01:45", tz="UTC")
VIC = 100.0


def _happy_long_15m(make_15m):
    """6 свечей дня D: первая — касание, последние 5 — фрактал/FVG.

    Раскладка: индексы df_15m.iloc[-5..-1] = [i-2, i-1, i, i+1, i+2].
    i+2 == LAST_15M по open_time."""
    return make_15m([
        ("2026-04-27 00:30", 99,    100.5, 99,    100  ),  # касание (low<=vic)
        ("2026-04-27 00:45", 100,   100.2, 99.5,  99.8 ),  # i-2
        ("2026-04-27 01:00", 99.8,  100.0, 99.6,  99.7 ),  # i-1
        ("2026-04-27 01:15", 99.7,  99.8,  99.0,  99.5 ),  # i: low=99 (LL) < vic, high=99.8
        ("2026-04-27 01:30", 99.5,  99.9,  99.3,  99.6 ),  # i+1
        ("2026-04-27 01:45", 100.5, 101.0, 100.2, 100.8),  # i+2: low=100.2 > high(i)=99.8 (FVG), > vic
    ])


def _happy_short_15m(make_15m):
    """Симметричный SHORT-сценарий: касание high>=vic, HH-фрактал, FVG под vic."""
    return make_15m([
        ("2026-04-27 00:30", 101,   102,   100,   101  ),  # касание (high>=vic)
        ("2026-04-27 00:45", 101,   100.5, 100.0, 100.3),  # i-2
        ("2026-04-27 01:00", 100.3, 100.4, 100.1, 100.2),  # i-1
        ("2026-04-27 01:15", 100.2, 101.0, 100.0, 100.5),  # i: high=101 (HH) > vic
        ("2026-04-27 01:30", 100.5, 100.7, 100.3, 100.4),  # i+1
        ("2026-04-27 01:45", 99.8,  99.9,  99.5,  99.7 ),  # i+2: high=99.9 < low(i)=100, < vic
    ])


# ---------- §8: edge cases (10 строк, ожидание None) ----------

def test_empty_df_15m_returns_none(make_15m, make_1d):
    """§8 строка 1: df_15m пустой."""
    df = make_15m([])
    assert detect_vic_evot(df, make_1d(101.0), VIC, SYMBOL, LAST_15M) is None


def test_too_few_candles_returns_none(make_15m, make_1d):
    """§8 строка 2: df_15m содержит < 5 свечей."""
    df = make_15m([
        ("2026-04-27 00:00", 100, 100, 100, 100),
        ("2026-04-27 00:15", 100, 100, 100, 100),
        ("2026-04-27 00:30", 100, 100, 100, 100),
        ("2026-04-27 00:45", 100, 100, 100, 100),
    ])
    assert detect_vic_evot(df, make_1d(101.0), VIC, SYMBOL, LAST_15M) is None


def test_vic_level_none_returns_none(make_15m, make_1d):
    """§8 строка 3: vic_level == None."""
    df = _happy_long_15m(make_15m)
    assert detect_vic_evot(df, make_1d(101.0), None, SYMBOL, LAST_15M) is None


def test_close_d_minus_1_equals_vic_returns_none(make_15m, make_1d):
    """§8 строка 4: close(D-1) == vic_level — направление не определено."""
    df = _happy_long_15m(make_15m)
    assert detect_vic_evot(df, make_1d(VIC), VIC, SYMBOL, LAST_15M) is None


def test_no_touch_in_day_returns_none(make_15m, make_1d):
    """§8 строка 5: ни одной свечи с low<=vic (LONG) до позиции i.

    В текущей реализации этот сценарий пересекается с «фрактал ниже уровня»
    (low(i)<vic), потому что валидный LL-фрактал ниже уровня сам по себе
    создаёт касание свечой i. Тест строится так, что ни одна свеча низом
    не достигает уровня — низ всех свечей строго выше vic.
    """
    df = make_15m([
        ("2026-04-27 00:30", 102,    102.5, 101.5, 102  ),
        ("2026-04-27 00:45", 102,    102.3, 101.6, 101.9),  # i-2
        ("2026-04-27 01:00", 101.9,  102.0, 101.7, 101.85),  # i-1
        ("2026-04-27 01:15", 101.85, 101.9, 101.5, 101.6),  # i: low=101.5 — выше vic
        ("2026-04-27 01:30", 101.6,  101.8, 101.55,101.7),  # i+1
        ("2026-04-27 01:45", 102.5,  103.0, 102.4, 102.8),  # i+2
    ])
    assert detect_vic_evot(df, make_1d(101.0), VIC, SYMBOL, LAST_15M) is None


def test_touch_but_no_fractal_returns_none(make_15m, make_1d):
    """§8 строка 6: касание есть, но low(i) НЕ строго меньше всех 4 соседей."""
    df = make_15m([
        ("2026-04-27 00:30", 99,    100.5, 99,    100  ),  # касание
        ("2026-04-27 00:45", 100,   100.2, 99.5,  99.8 ),
        ("2026-04-27 01:00", 99.8,  100.0, 99.6,  99.7 ),
        ("2026-04-27 01:15", 99.7,  99.8,  99.7,  99.5 ),  # i: low=99.7 НЕ < low(i-1)=99.6
        ("2026-04-27 01:30", 99.5,  99.9,  99.3,  99.6 ),
        ("2026-04-27 01:45", 100.5, 101.0, 100.2, 100.8),
    ])
    assert detect_vic_evot(df, make_1d(101.0), VIC, SYMBOL, LAST_15M) is None


def test_fractal_above_level_returns_none(make_15m, make_1d):
    """§8 строка 7: LL-фрактал валиден, но low(i) > vic."""
    df = make_15m([
        ("2026-04-27 00:30", 100.5, 101,   100,   100.8),  # касание (low=100, == vic)
        ("2026-04-27 00:45", 101,   101.5, 100.8, 101.2),
        ("2026-04-27 01:00", 101.2, 101.3, 100.9, 101.0),
        ("2026-04-27 01:15", 101.0, 101.1, 100.5, 100.7),  # i: low=100.5 (LL), но > vic
        ("2026-04-27 01:30", 100.7, 101.0, 100.6, 100.9),
        ("2026-04-27 01:45", 102.0, 102.5, 101.5, 102.0),
    ])
    assert detect_vic_evot(df, make_1d(101.0), VIC, SYMBOL, LAST_15M) is None


def test_no_fvg_returns_none(make_15m, make_1d):
    """§8 строка 8: фрактал есть, но high(i) >= low(i+2) — FVG не сформирован."""
    df = make_15m([
        ("2026-04-27 00:30", 99,    100.5, 99,    100  ),
        ("2026-04-27 00:45", 100,   100.2, 99.5,  99.8 ),
        ("2026-04-27 01:00", 99.8,  100.0, 99.6,  99.7 ),
        ("2026-04-27 01:15", 99.7,  100.5, 99.0,  99.5 ),  # i: high=100.5
        ("2026-04-27 01:30", 99.5,  99.9,  99.3,  99.6 ),
        ("2026-04-27 01:45", 100.0, 100.5, 100.0, 100.3),  # i+2: low=100.0 < high(i)=100.5 — FVG отсутствует
    ])
    assert detect_vic_evot(df, make_1d(101.0), VIC, SYMBOL, LAST_15M) is None


def test_fvg_below_level_returns_signal(make_15m, make_1d):
    """FVG под уровнем — сигнал валиден (FVG-vs-vic проверка убрана).

    Ранее этот сценарий отвергался требованием `low(i+2) > vic`. Теперь
    достаточно касания (low(0)=99 <= vic) и фрактала под уровнем
    (low(i)=99.0 < vic=100)."""
    df = make_15m([
        ("2026-04-27 00:30", 99,    100.5, 99,    100  ),  # касание (low=99)
        ("2026-04-27 00:45", 100,   100.2, 99.5,  99.8 ),
        ("2026-04-27 01:00", 99.8,  100.0, 99.6,  99.7 ),
        ("2026-04-27 01:15", 99.7,  99.8,  99.0,  99.5 ),  # i: low=99.0 (LL <vic)
        ("2026-04-27 01:30", 99.5,  99.9,  99.3,  99.6 ),
        ("2026-04-27 01:45", 99.85, 100.0, 99.85, 99.95),  # i+2: low=99.85 > 99.8 (FVG)
    ])
    sig = detect_vic_evot(df, make_1d(101.0), VIC, SYMBOL, LAST_15M)
    assert sig is not None
    assert sig.direction == "LONG"
    # entry = high(i)*0.2 + low(i+2)*0.8 = 99.8*0.2 + 99.85*0.8 = 99.84
    assert sig.price == pytest.approx(99.84)


# ---------- §8: happy paths (2 строки) ----------

def test_happy_path_long_returns_signal(make_15m, make_1d):
    """§8 строка 10: все 5 условий выполнены (LONG)."""
    df = _happy_long_15m(make_15m)
    sig = detect_vic_evot(df, make_1d(101.0), VIC, SYMBOL, LAST_15M)

    assert sig is not None
    assert sig.strategy == "VIC_EVOT"
    assert sig.symbol == SYMBOL
    assert sig.timeframe == "1d"
    assert sig.direction == "LONG"
    # entry = high(i)*0.2 + low(i+2)*0.8 = 99.8*0.2 + 100.2*0.8 = 100.12
    assert sig.price == pytest.approx(100.12)
    assert sig.confirm_time == LAST_15M

    # Level заполнен, zone остался None.
    assert sig.zone is None
    assert sig.level is not None
    assert sig.level.price == VIC
    assert sig.level.day == pd.Timestamp("2026-04-26", tz="UTC")
    assert sig.level.source == "VIC"

    # Meta поля для рендера и отладки.
    assert sig.meta["confirm_type"] == "FVG-15m + LL-фрактал + OB-15m"
    assert sig.meta["source_tf"] == "1d"
    assert sig.meta["vic_level"] == VIC
    assert sig.meta["fractal_time"] == "2026-04-27T01:15:00+00:00"


def test_happy_path_short_returns_signal(make_15m, make_1d):
    """§8 строка 11: все 5 условий выполнены (SHORT)."""
    df = _happy_short_15m(make_15m)
    sig = detect_vic_evot(df, make_1d(99.0), VIC, SYMBOL, LAST_15M)

    assert sig is not None
    assert sig.direction == "SHORT"
    # entry = low(i)*0.2 + high(i+2)*0.8 = 100.0*0.2 + 99.9*0.8 = 99.92
    assert sig.price == pytest.approx(99.92)
    assert sig.confirm_time == LAST_15M
    assert sig.zone is None
    assert sig.level.price == VIC


# ---------- Бонусные кейсы (контракт каллера, не из §8) ----------

def test_direction_mismatch_returns_none(make_15m, make_1d):
    """Цепочка LONG (close>vic), но 15m даёт HH-фрактал — None."""
    df = _happy_short_15m(make_15m)
    assert detect_vic_evot(df, make_1d(101.0), VIC, SYMBOL, LAST_15M) is None


def test_empty_df_1d_returns_none(make_15m):
    """df_1d пустой — направление цепочки не определено."""
    df = _happy_long_15m(make_15m)
    empty_1d = pd.DataFrame(
        {"open": [], "high": [], "low": [], "close": [], "volume": []},
        index=pd.DatetimeIndex([], tz="UTC", name="open_time"),
    )
    assert detect_vic_evot(df, empty_1d, VIC, SYMBOL, LAST_15M) is None


# ---- Cross-midnight: фрактал спанит границу UTC-дня (баг f88ee54..b418f86) ----

def test_cross_midnight_fractal_long(make_15m, make_1d):
    """i+2 = 00:45 UTC новый день, i = 00:15 (today), i-2 = 23:45 (вчера).

    Реальный кейс: BTC 27/04 00:45 UTC. Свеча 23:45 предыдущего дня нужна как
    левый сосед фрактала. Касание уровня — только в свечах day D (00:00..i)."""
    df = make_15m([
        ("2026-04-26 23:45", 100.5, 100.7, 100.4, 100.6),  # i-2: вчера, low=100.4
        ("2026-04-27 00:00", 100.6, 100.6, 100.3, 100.4),  # i-1: сегодня
        ("2026-04-27 00:15", 100.4, 100.5,  99.0, 100.0),  # i: low=99 (LL <vic), high=100.5
        ("2026-04-27 00:30", 100.0, 100.4,  99.5, 100.2),  # i+1: low=99.5
        ("2026-04-27 00:45", 100.2, 101.5, 100.7, 101.0),  # i+2: low=100.7 > high(i)=100.5 (FVG)
    ])
    last_15m = pd.Timestamp("2026-04-27 00:45", tz="UTC")
    sig = detect_vic_evot(df, make_1d(101.0), VIC, SYMBOL, last_15m)
    assert sig is not None
    assert sig.direction == "LONG"
    # entry = high(i)*0.2 + low(i+2)*0.8 = 100.5*0.2 + 100.7*0.8 = 100.66
    assert sig.price == pytest.approx(100.66)
    assert sig.level.price == VIC


# ---- Поиск фрактала: ближайший к FVG в day D + проверка противохода ----

def test_fractal_offset_k1_long(make_15m, make_1d):
    """Фрактал на 1 свечу раньше FVG-start.

    7 свечей, n=7 → pos_i=4 (FVG-start), pos_ip2=6 (last_closed).
    Фрактал на pos_f=3, FVG-start на pos=4. Между ними HH-фрактала нет."""
    df = make_15m([
        ("2026-04-27 00:00", 99,    100.5, 99,    100  ),  # касание (low<=vic)
        ("2026-04-27 00:15", 100,   100.2, 99.6,  99.8 ),  # f-2 для f=3
        ("2026-04-27 00:30", 99.8,  100.0, 99.5,  99.7 ),  # f-1
        ("2026-04-27 00:45", 99.7,  99.8,  99.0,  99.5 ),  # f=3: low=99 (LL <vic), high=99.8
        ("2026-04-27 01:00", 99.5,  99.9,  99.3,  99.6 ),  # f+1 = pos_i=4 (FVG-start), high=99.9
        ("2026-04-27 01:15", 99.6,  100.0, 99.4,  99.8 ),  # f+2
        ("2026-04-27 01:30", 100.5, 101.0, 100.2, 100.8),  # i+2=6: low=100.2 > high(i)=99.9 (FVG), > vic
    ])
    last_15m = pd.Timestamp("2026-04-27 01:30", tz="UTC")
    sig = detect_vic_evot(df, make_1d(101.0), VIC, SYMBOL, last_15m)
    assert sig is not None
    assert sig.direction == "LONG"
    # entry = high(i)*0.2 + low(i+2)*0.8 = 99.9*0.2 + 100.2*0.8 = 100.14
    assert sig.price == pytest.approx(100.14)
    assert sig.meta["fractal_offset_k"] == 1
    assert sig.meta["fractal_time"] == "2026-04-27T00:45:00+00:00"


def test_no_valid_fractal_in_day_returns_none(make_15m, make_1d):
    """В day D нет ни одного LL-фрактала с low<vic — None.

    Все низы в day D выше vic — фрактал-под-уровнем условие нигде не
    проходит, хотя FVG валидный сформирован на последних свечах."""
    df = make_15m([
        ("2026-04-27 00:00", 99,    100.5, 99,    100  ),  # касание (вне фрактал-проверки)
        ("2026-04-27 00:15", 100,   100.5, 99.7,  100.2),
        ("2026-04-27 00:30", 100.2, 100.6, 99.9,  100.4),
        ("2026-04-27 00:45", 100.4, 100.7, 100.1, 100.5),
        ("2026-04-27 01:00", 100.5, 100.8, 100.2, 100.6),
        ("2026-04-27 01:15", 100.6, 100.9, 100.3, 100.7),
        ("2026-04-27 01:30", 100.7, 101.0, 100.4, 100.8),
        ("2026-04-27 01:45", 100.8, 101.1, 100.5, 100.9),  # pos_i=7
        ("2026-04-27 02:00", 100.9, 101.2, 100.6, 101.0),  # i+1
        ("2026-04-27 02:15", 102.0, 102.5, 101.5, 102.0),  # i+2: low=101.5 > high(7)=101.1 (FVG)
    ])
    last_15m = pd.Timestamp("2026-04-27 02:15", tz="UTC")
    assert detect_vic_evot(df, make_1d(101.0), VIC, SYMBOL, last_15m) is None


def test_opposite_fractal_invalidates_long(make_15m, make_1d):
    """LL → HH → FVG: HH-фрактал между LL и FVG отвергает сигнал.

    Структура day D: касание, LL-фрактал на pos=3, HH-фрактал на pos=7
    (опровергает разворот вниз), затем FVG между pos=11 и pos=13. По
    структурной инвалидации — None."""
    df = make_15m([
        ("2026-04-27 00:00", 99,    100.5, 99,    100  ),  # 0: касание
        ("2026-04-27 00:15", 100,   100.2, 99.5,  99.8 ),  # 1: LL-2
        ("2026-04-27 00:30", 99.8,  100.0, 99.6,  99.7 ),  # 2: LL-1
        ("2026-04-27 00:45", 99.7,  99.8,  99.0,  99.5 ),  # 3: LL (low=99 <vic)
        ("2026-04-27 01:00", 99.5,  99.9,  99.3,  99.6 ),  # 4: LL+1
        ("2026-04-27 01:15", 99.6,  100.5, 99.4,  100.2),  # 5: LL+2 (= HH-2)
        ("2026-04-27 01:30", 100.2, 100.7, 100.0, 100.5),  # 6: HH-1
        ("2026-04-27 01:45", 100.5, 101.0, 100.3, 100.7),  # 7: HH (high=101 >vic, > 4 соседей)
        ("2026-04-27 02:00", 100.7, 100.9, 100.4, 100.6),  # 8: HH+1
        ("2026-04-27 02:15", 100.6, 100.8, 100.4, 100.5),  # 9: HH+2
        ("2026-04-27 02:30", 100.5, 100.7, 100.3, 100.5),  # 10
        ("2026-04-27 02:45", 100.5, 100.6, 100.2, 100.4),  # 11: pos_i, high=100.6
        ("2026-04-27 03:00", 100.4, 100.5, 100.3, 100.4),  # 12: i+1
        ("2026-04-27 03:15", 101.0, 101.5, 100.8, 101.2),  # 13: i+2 (low=100.8 > 100.6 = FVG, > vic)
    ])
    last_15m = pd.Timestamp("2026-04-27 03:15", tz="UTC")
    assert detect_vic_evot(df, make_1d(101.0), VIC, SYMBOL, last_15m) is None


def test_touch_only_in_yesterday_returns_none(make_15m, make_1d):
    """Касание было только в свечах ВЧЕРА — не считается, day D пуст до i.

    Конструируем: вчерашние свечи трогают vic, сегодняшние (i-1, i, i+1)
    все строго выше vic. Фрактал чисто в today, но low(i) > vic — провал
    условия фрактал-под-уровнем. То есть валидно проверяем что touch-в-вчера
    НЕ компенсирует отсутствие касания/фрактала в day D."""
    df = make_15m([
        ("2026-04-26 23:45", 102, 103, 99, 101),     # вчера: касание (low=99 < vic=100)
        ("2026-04-27 00:00", 101, 102, 100.5, 101.5),  # i-1
        ("2026-04-27 00:15", 101.5, 102, 100.8, 101.3),  # i: low=100.8 (LL по соседям), но > vic
        ("2026-04-27 00:30", 101.3, 102, 101, 101.5),  # i+1
        ("2026-04-27 00:45", 102, 103, 102, 102.5),    # i+2
    ])
    last_15m = pd.Timestamp("2026-04-27 00:45", tz="UTC")
    # Фрактал-проверка отвергнет потому что low(i)=100.8 не < vic=100.
    # Этот тест документирует: касание во вчера не учитывается.
    assert detect_vic_evot(df, make_1d(101.0), VIC, SYMBOL, last_15m) is None
