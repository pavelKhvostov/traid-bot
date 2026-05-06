"""Unit-тесты для Strategy 1.1.5 — OB-top + FVG-macro + RDRB4-htf.

Покрытие:
- detect_rdrb4: happy LONG/SHORT, edge cases (нарушение каждого из 5 условий)
- detect_strategy_1_1_5_signals: happy SHORT (полный каскад), lookahead-prevention,
  RR=1 геометрия, no-overlap пропуск.
"""
from __future__ import annotations

import pandas as pd

from strategies.strategy_1_1_5 import (
    RR,
    detect_rdrb4,
    detect_strategy_1_1_5_signals,
)


def make_df(candles: list[tuple]) -> pd.DataFrame:
    idx = pd.DatetimeIndex(
        [pd.Timestamp(c[0], tz="UTC") for c in candles],
        tz="UTC", name="open_time",
    )
    return pd.DataFrame({
        "open":   [c[1] for c in candles],
        "high":   [c[2] for c in candles],
        "low":    [c[3] for c in candles],
        "close":  [c[4] for c in candles],
        "volume": [c[5] for c in candles],
    }, index=idx)


def empty_df() -> pd.DataFrame:
    return pd.DataFrame(
        {"open": [], "high": [], "low": [], "close": [], "volume": []},
        index=pd.DatetimeIndex([], tz="UTC", name="open_time"),
    )


# ============================================================
# detect_rdrb4 — атомарный детектор
# ============================================================

# Каноничный SHORT RDRB-4 (по формулам пользователя):
#   c1.low > c2.low        (c2 уходит ниже c1)
#   c1.low < c2.close      (c2 закрытие выше c1.low)
#   c2.low < c4.high       (c4 хай зашёл в фитиль c2)
#   c3.close < c2.low      (c3 закрытие ниже c2.low — поглощение)
#   c1.low > c4.high       (c4 не пробил c1.low)
# Зона: [c4.high, c1.low]

def test_detect_rdrb4_happy_short():
    # c1: o=110, h=111, l=100, c=109   (нижний фитиль)
    # c2: o=108, h=109, l=95,  c=107   (low ниже c1.low=100, close=107 > c1.low=100)
    # c3: o=107, h=108, l=85,  c=90    (close=90 < c2.low=95)
    # c4: o=91,  h=98,  l=89,  c=93    (high=98: c2.low=95 < 98 < c1.low=100)
    df = make_df([
        ("2026-01-01 00:00:00", 110, 111, 100, 109, 1),
        ("2026-01-01 01:00:00", 108, 109,  95, 107, 1),
        ("2026-01-01 02:00:00", 107, 108,  85,  90, 1),
        ("2026-01-01 03:00:00",  91,  98,  89,  93, 1),
    ])
    z = detect_rdrb4(df, 3)
    assert z is not None
    assert z.direction == "SHORT"
    # bottom = max(c2.low=95, c4_body_high=max(91,93)=93) = 95
    assert z.bottom == 95
    assert z.top == 100  # c1.low
    assert z.c1_high == 111
    assert z.c2_high == 109
    assert z.c4_body_high == 93


def test_detect_rdrb4_happy_long():
    # mirror: c1.high < c2.high, c1.high > c2.close, c2.high > c4.low,
    #         c3.close > c2.high, c1.high < c4.low
    # c1: o=90, h=100, l=89, c=91     (верхний фитиль)
    # c2: o=92, h=105, l=91, c=93     (high=105 > c1.high=100, close=93 < c1.high=100)
    # c3: o=93, h=115, l=92, c=110    (close=110 > c2.high=105)
    # c4: o=109, h=111, l=102, c=107  (low=102: c2.high=105 > 102 > c1.high=100)
    df = make_df([
        ("2026-01-01 00:00:00", 90, 100,  89,  91, 1),
        ("2026-01-01 01:00:00", 92, 105,  91,  93, 1),
        ("2026-01-01 02:00:00", 93, 115,  92, 110, 1),
        ("2026-01-01 03:00:00", 109, 111, 102, 107, 1),
    ])
    z = detect_rdrb4(df, 3)
    assert z is not None
    assert z.direction == "LONG"
    # top = min(c2.high=105, c4_body_low=min(109,107)=107) = 105
    assert z.bottom == 100  # c1.high
    assert z.top == 105
    assert z.c4_body_low == 107


def test_detect_rdrb4_short_fails_c4_breaks_c1_low():
    """c4.high == c1.low → нарушает c1.low > c4.high (строгое неравенство)."""
    df = make_df([
        ("2026-01-01 00:00:00", 110, 111, 100, 109, 1),
        ("2026-01-01 01:00:00", 108, 109,  95, 107, 1),
        ("2026-01-01 02:00:00", 107, 108,  85,  90, 1),
        ("2026-01-01 03:00:00",  91, 100,  89,  93, 1),  # c4.high=100 == c1.low
    ])
    assert detect_rdrb4(df, 3) is None


def test_detect_rdrb4_short_fails_c4_doesnt_enter_c2_wick():
    """c4.high == c2.low → нарушает c2.low < c4.high."""
    df = make_df([
        ("2026-01-01 00:00:00", 110, 111, 100, 109, 1),
        ("2026-01-01 01:00:00", 108, 109,  95, 107, 1),
        ("2026-01-01 02:00:00", 107, 108,  85,  90, 1),
        ("2026-01-01 03:00:00",  91,  95,  89,  93, 1),  # c4.high=95 == c2.low
    ])
    assert detect_rdrb4(df, 3) is None


def test_detect_rdrb4_short_fails_c3_doesnt_close_below_c2_low():
    """c3.close == c2.low → нарушает c3.close < c2.low."""
    df = make_df([
        ("2026-01-01 00:00:00", 110, 111, 100, 109, 1),
        ("2026-01-01 01:00:00", 108, 109,  95, 107, 1),
        ("2026-01-01 02:00:00", 107, 108,  85,  95, 1),  # c3.close=95 == c2.low
        ("2026-01-01 03:00:00",  91,  98,  89,  93, 1),
    ])
    assert detect_rdrb4(df, 3) is None


def test_detect_rdrb4_short_fails_c2_close_below_c1_low():
    """c2.close < c1.low → нарушает c1.low < c2.close (нет ловушки)."""
    df = make_df([
        ("2026-01-01 00:00:00", 110, 111, 100, 109, 1),
        ("2026-01-01 01:00:00", 108, 109,  95,  98, 1),  # c2.close=98 < c1.low=100
        ("2026-01-01 02:00:00", 107, 108,  85,  90, 1),
        ("2026-01-01 03:00:00",  91,  98,  89,  93, 1),
    ])
    assert detect_rdrb4(df, 3) is None


def test_detect_rdrb4_short_fails_c2_low_above_c1_low():
    """c2.low >= c1.low → c2 не выносит ликвидность c1."""
    df = make_df([
        ("2026-01-01 00:00:00", 110, 111, 100, 109, 1),
        ("2026-01-01 01:00:00", 108, 109, 100, 107, 1),  # c2.low=100 == c1.low
        ("2026-01-01 02:00:00", 107, 108,  85,  90, 1),
        ("2026-01-01 03:00:00",  91,  98,  89,  93, 1),
    ])
    assert detect_rdrb4(df, 3) is None


def test_detect_rdrb4_returns_none_on_short_df():
    df = make_df([("2026-01-01 00:00:00", 100, 101, 99, 100, 1)])
    assert detect_rdrb4(df, 0) is None
    assert detect_rdrb4(df, 3) is None


# ============================================================
# detect_strategy_1_1_5_signals — полный каскад
# ============================================================

def _build_short_cascade():
    """Полный SHORT-каскад: OB-1d → FVG-4h → RDRB4-1h.

    Все зоны overlap, направление SHORT.
    """
    # ===== OB-1d (top): пара (prev=bull, cur=bear closing below prev.open) =====
    # SHORT OB: prev.close > prev.open, cur.close < prev.open
    # zone = [prev.open, max(prev.high, cur.high)]
    df_1d = make_df([
        ("2026-01-01 00:00:00", 100, 110, 95, 108, 1),  # bull (close>open)
        ("2026-01-02 00:00:00", 109, 112, 95, 99,  1),  # bear closing < prev.open=100
        # SHORT OB zone: [100, 112]
    ])
    # search_start for macro-FVG = 2026-01-02 + 24h = 2026-01-03 00:00

    # ===== FVG-4h (macro): SHORT FVG в зоне OB-top =====
    # SHORT FVG: c0.low > c2.high. Зона = [c2.high, c0.low].
    # Должна overlap с [100, 112]. Возьмём [102, 108]: c0.low=108, c2.high=102.
    # Размещаем после search_start.
    df_4h_rows = []
    # filler before search_start:
    t = pd.Timestamp("2026-01-02 00:00:00", tz="UTC")
    while t < pd.Timestamp("2026-01-03 00:00:00", tz="UTC"):
        df_4h_rows.append((t.strftime("%Y-%m-%d %H:%M:%S"), 105, 107, 103, 106, 1))
        t += pd.Timedelta(hours=4)
    # SHORT FVG triple at 03 00:00, 04:00, 08:00
    df_4h_rows.append(("2026-01-03 00:00:00", 107, 109, 108, 108, 1))  # c0: low=108
    df_4h_rows.append(("2026-01-03 04:00:00", 106, 107, 105, 105, 1))  # c1
    df_4h_rows.append(("2026-01-03 08:00:00", 103, 102, 100, 101, 1))  # c2: high=102
    # FVG zone: [102, 108]. fvg.c2_time = 2026-01-03 08:00
    df_4h = make_df(df_4h_rows)

    # search_start for RDRB-1h = 2026-01-03 08:00 + 4h = 2026-01-03 12:00

    # ===== RDRB-4 1h (htf): SHORT в зоне FVG-macro [102, 108] =====
    # Используем шаблон из happy_short, c1.low=104, c4.high=105
    # zone = [105, 104]? Нет: [c4.high, c1.low] = [105, 104] — bottom > top, ошибка.
    # Перестраиваем: c1.low=106, c4.high=103 → zone=[103, 106]. Должно overlap с [102, 108]: да.
    # Пересмотр SHORT условий с c1.low=106:
    #   c1.low(106) > c2.low — c2.low < 106
    #   c1.low(106) < c2.close — c2.close > 106
    #   c2.low < c4.high — c2.low < 103
    #   c3.close < c2.low — c3.close < c2.low
    #   c1.low(106) > c4.high(103) ✓
    # Возьмём c2.low=102, c2.close=107 (нужно o<=107, h>=107, l<=102).
    # c3.close < 102: c3.close=98.
    # c4.high=103, c4.low<103.
    df_1h_rows = []
    t = pd.Timestamp("2026-01-03 00:00:00", tz="UTC")
    while t < pd.Timestamp("2026-01-03 12:00:00", tz="UTC"):
        df_1h_rows.append((t.strftime("%Y-%m-%d %H:%M:%S"), 105, 106, 104, 105, 1))
        t += pd.Timedelta(hours=1)
    # RDRB-4: c1=12:00, c2=13:00, c3=14:00, c4=15:00
    df_1h_rows.append(("2026-01-03 12:00:00", 108, 109, 106, 107, 1))  # c1: low=106
    df_1h_rows.append(("2026-01-03 13:00:00", 107, 108, 102, 107, 1))  # c2: low=102, close=107
    df_1h_rows.append(("2026-01-03 14:00:00", 100, 101,  95,  98, 1))  # c3: close=98 < 102
    df_1h_rows.append(("2026-01-03 15:00:00",  99, 103,  97, 100, 1))  # c4: high=103
    df_1h = make_df(df_1h_rows)

    return df_1d, df_4h, df_1h


def test_strategy_1_1_5_happy_short():
    df_1d, df_4h, df_1h = _build_short_cascade()
    sigs = detect_strategy_1_1_5_signals(
        df_1d=df_1d, df_12h=empty_df(),
        df_4h=df_4h, df_6h=empty_df(),
        df_1h=df_1h, df_2h=empty_df(),
    )
    assert len(sigs) == 1
    s = sigs[0]
    assert s["direction"] == "SHORT"
    assert s["top_tf"] == "1d"
    assert s["macro_tf"] == "4h"
    assert s["htf_tf"] == "1h"
    # Расширенная зона:
    #   c4_body_high = max(c4.open=99, c4.close=100) = 100
    #   bottom = max(c2.low=102, c4_body_high=100) = 102
    #   top    = c1.low = 106
    # Entry SHORT = bottom = 102
    assert s["entry"] == 102
    # SL = max(c1.high=109, c2.high=108) = 109
    assert s["sl"] == 109
    # risk = 109 - 102 = 7, tp = 102 - 7 = 95
    assert s["risk"] == 7
    assert s["tp"] == 95
    assert RR == 1.0


def test_strategy_1_1_5_lookahead_rdrb_before_fvg_close_rejected():
    """RDRB c1_time раньше чем fvg_macro.c2_time + macro_tf — пропуск."""
    df_1d, df_4h, _df_1h_good = _build_short_cascade()
    # RDRB сдвинут на 8 часов назад: c1=04:00 вместо 12:00.
    # FVG c2_time=2026-01-03 08:00, search_start = 12:00. RDRB до search_start
    # должен быть отброшен.
    df_1h_rows = []
    t = pd.Timestamp("2026-01-03 00:00:00", tz="UTC")
    while t <= pd.Timestamp("2026-01-04 00:00:00", tz="UTC"):
        df_1h_rows.append((t.strftime("%Y-%m-%d %H:%M:%S"), 105, 106, 104, 105, 1))
        t += pd.Timedelta(hours=1)
    # RDRB в early window (04:00 c1) — должен быть отброшен:
    df_1h_rows[4] = ("2026-01-03 04:00:00", 108, 109, 106, 107, 1)
    df_1h_rows[5] = ("2026-01-03 05:00:00", 107, 108, 102, 107, 1)
    df_1h_rows[6] = ("2026-01-03 06:00:00", 100, 101,  95,  98, 1)
    df_1h_rows[7] = ("2026-01-03 07:00:00",  99, 103,  97, 100, 1)
    df_1h_lookahead = make_df(df_1h_rows)

    sigs = detect_strategy_1_1_5_signals(
        df_1d=df_1d, df_12h=empty_df(),
        df_4h=df_4h, df_6h=empty_df(),
        df_1h=df_1h_lookahead, df_2h=empty_df(),
    )
    # RDRB до search_start не должен пройти.
    # Если в df больше нет валидных RDRB после 12:00 — sigs пустой.
    assert len(sigs) == 0


def test_strategy_1_1_5_no_overlap_rdrb_with_fvg_skipped():
    """RDRB зона не overlap с FVG-macro → пропуск."""
    df_1d, df_4h, _ = _build_short_cascade()
    # RDRB далеко выше FVG (zone [103,106] vs RDRB zone выше). FVG zone=[102,108].
    # Сделаем RDRB зону [200, 205] — не overlap.
    df_1h_rows = []
    t = pd.Timestamp("2026-01-03 00:00:00", tz="UTC")
    while t < pd.Timestamp("2026-01-03 12:00:00", tz="UTC"):
        df_1h_rows.append((t.strftime("%Y-%m-%d %H:%M:%S"), 202, 204, 201, 203, 1))
        t += pd.Timedelta(hours=1)
    df_1h_rows.append(("2026-01-03 12:00:00", 208, 209, 206, 207, 1))  # c1: low=206
    df_1h_rows.append(("2026-01-03 13:00:00", 207, 208, 202, 207, 1))
    df_1h_rows.append(("2026-01-03 14:00:00", 200, 201, 195, 198, 1))
    df_1h_rows.append(("2026-01-03 15:00:00", 199, 203, 197, 200, 1))
    df_1h_no_overlap = make_df(df_1h_rows)

    sigs = detect_strategy_1_1_5_signals(
        df_1d=df_1d, df_12h=empty_df(),
        df_4h=df_4h, df_6h=empty_df(),
        df_1h=df_1h_no_overlap, df_2h=empty_df(),
    )
    assert len(sigs) == 0


def test_strategy_1_1_5_empty_inputs_no_crash():
    sigs = detect_strategy_1_1_5_signals(
        df_1d=empty_df(), df_12h=empty_df(),
        df_4h=empty_df(), df_6h=empty_df(),
        df_1h=empty_df(), df_2h=empty_df(),
    )
    assert sigs == []
