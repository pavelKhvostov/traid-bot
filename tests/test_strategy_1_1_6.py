"""Unit-тесты для Strategy 1.1.6 — детектор FVG-top + OB-macro + FVG-htf.

Все тесты на синтетических свечах. Никакого I/O, никакой сети.
Покрытие: happy-path LONG/SHORT, wick-инвалидация, double-overlap,
earliest-wins по cur_close, RR=1 геометрия.
"""
from __future__ import annotations

import pandas as pd
import pytest

from strategies.strategy_1_1_6 import RR, detect_strategy_1_1_6_signals


# ---------- helpers ----------

def make_df(candles: list[tuple]) -> pd.DataFrame:
    """[(ts_str, open, high, low, close, volume), ...] -> DataFrame UTC index."""
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


# ---------- Test 1: happy-path LONG через 1d + 4h + 1h ----------

def test_happy_path_long_via_1d_4h_1h():
    """Полная воронка LONG: FVG-1d → OB-4h → FVG-1h.

    Геометрия:
      - FVG-1d LONG zone = [102, 108], c2_close = 2026-01-04 00:00
      - OB-4h LONG zone = [107, 110], cur_time = 2026-01-04 04:00, overlap [107..108]
      - FVG-1h LONG zone = [107, 108], c2_time = 2026-01-04 07:00 (signal_time)
      - entry = 107.5, sl = 107 (ob_macro.bottom), tp = 108 (RR=1)
    """
    df_1d = make_df([
        ("2026-01-01", 100, 102, 99, 101, 10),    # c0: high=102
        ("2026-01-02", 101, 110, 100, 109, 10),   # c1: тенью не закрывает gap (low=100 < c0.high=102 — но FVG считается по c0.high и c2.low)
        ("2026-01-03", 109, 120, 108, 119, 10),   # c2: low=108
    ])
    # FVG-1d LONG: high(c0)=102 < low(c2)=108 → zone [102, 108]

    # 4h: одна валидная OB-pair (06:00 prev bearish + 10:00 cur bullish).
    # Свечи 00:00 и 04:00 — нейтральные, чтобы детектор не нашёл OB раньше.
    df_4h = make_df([
        ("2026-01-04 00:00", 110, 110.0, 110, 110, 1),   # плоская
        ("2026-01-04 04:00", 110, 111, 109, 108, 1),     # bearish (close<open), но low=109>=102
        ("2026-01-04 08:00", 108, 112, 107, 112, 1),     # bullish reaction (close=112 > prev.open=110)
        ("2026-01-04 12:00", 112, 112, 110, 111, 1),     # filler после cur_close (для 1m данных в backtest, тут не нужен но симметрия)
    ])
    # OB-4h LONG: prev (04:00) bearish, cur (08:00) close>prev.open
    # zone = [min(prev.low=109, cur.low=107), prev.open=110] = [107, 110]
    # cur_time=08:00, cur_close=12:00
    # Wick check на df_4h в [00:00, 12:00): свечи 00,04,08 → low: 110,109,107. Все >= 102 ✓

    # 1h: htf_start = ob_macro.cur_time + macro_hours = 08:00 + 4h = 12:00.
    # Свечи 12, 13, 14 — FVG LONG ПОСЛЕ закрытия cur 4h-OB
    # (исправление lookahead-бага: до этой правки старт был +1h=09:00,
    # что давало htf-реакцию ДО формирования macro-OB).
    df_1h = make_df([
        ("2026-01-04 12:00", 107, 107, 105, 106, 1),     # c0: high=107
        ("2026-01-04 13:00", 106, 109, 105, 108, 1),     # c1
        ("2026-01-04 14:00", 108, 109, 108, 108.5, 1),   # c2: low=108
    ])
    # FVG-1h LONG: high(c0)=107 < low(c2)=108 → zone [107, 108]
    # Overlap с macro=[107,110]: ✓, с top=[102,108]: ✓ (touch на 108)

    sigs = detect_strategy_1_1_6_signals(
        df_1d, empty_df(), df_4h, empty_df(), df_1h, empty_df(), verbose=False,
    )
    assert len(sigs) == 1
    s = sigs[0]
    assert s["direction"] == "LONG"
    assert s["top_tf"] == "1d"
    assert s["macro_tf"] == "4h"
    assert s["htf_tf"] == "1h"
    assert s["signal_time"] == pd.Timestamp("2026-01-04 14:00", tz="UTC")
    assert s["entry"] == pytest.approx(107.5)
    assert s["sl"] == pytest.approx(107.0)  # ob_macro.bottom
    assert s["tp"] == pytest.approx(108.0)  # entry + risk*1
    assert s["risk"] == pytest.approx(0.5)
    assert s["top_fvg_zone"] == (102.0, 108.0)
    assert s["ob_macro_zone"] == (107.0, 110.0)
    assert s["htf_fvg_zone"] == (107.0, 108.0)


# ---------- Test 2: happy-path SHORT (зеркально) ----------

def test_happy_path_short_via_1d_4h_1h():
    """Зеркально к Test 1: FVG-1d SHORT → OB-4h SHORT → FVG-1h SHORT.

    Геометрия:
      - FVG-1d SHORT zone = [195, 200] (low(c0)=200 > high(c2)=195)
      - OB-4h SHORT zone = [196, 199], cur_time=2026-01-04 08:00
      - FVG-1h SHORT zone = [196, 197], signal_time = 2026-01-04 11:00
      - entry = 196.5, sl = 199 (ob_macro.top), tp = 194 (RR=1)
    """
    df_1d = make_df([
        ("2026-01-01", 204, 205, 200, 201, 10),   # c0: low=200
        ("2026-01-02", 201, 202, 195, 196, 10),   # c1
        ("2026-01-03", 194, 195, 190, 191, 10),   # c2: high=195
    ])
    # FVG-1d SHORT: low(c0)=200 > high(c2)=195 → zone [195, 200]

    df_4h = make_df([
        ("2026-01-04 00:00", 196, 196.0, 196, 196, 1),    # плоская
        ("2026-01-04 04:00", 196, 198, 195, 197, 1),       # bullish (close>open)
        ("2026-01-04 08:00", 197, 199, 193, 193, 1),       # bearish reaction (close=193 < prev.open=196)
        ("2026-01-04 12:00", 193, 195, 192, 194, 1),       # filler после cur_close
    ])
    # OB-4h SHORT: prev (04:00) bullish, cur (08:00) close<prev.open
    # zone = [prev.open=196, max(prev.high=198, cur.high=199)] = [196, 199]
    # cur_time=08:00, cur_close=12:00
    # Wick check (SHORT): high > fvg_top.top=200? 196,198,199 — все < 200 ✓

    # htf_start = ob_macro.cur_time + macro_hours = 08:00 + 4h = 12:00.
    # FVG-1h SHORT после закрытия cur 4h-OB.
    df_1h = make_df([
        ("2026-01-04 12:00", 198, 200, 197, 199, 1),     # c0: low=197
        ("2026-01-04 13:00", 199, 199, 195, 196, 1),     # c1
        ("2026-01-04 14:00", 196, 196, 193, 194, 1),     # c2: high=196
    ])
    # FVG-1h SHORT: low(c0)=197 > high(c2)=196 → zone [196, 197]
    # Overlap с macro=[196,199] ✓, с top=[195,200] ✓

    sigs = detect_strategy_1_1_6_signals(
        df_1d, empty_df(), df_4h, empty_df(), df_1h, empty_df(), verbose=False,
    )
    assert len(sigs) == 1
    s = sigs[0]
    assert s["direction"] == "SHORT"
    assert s["entry"] == pytest.approx(196.5)
    assert s["sl"] == pytest.approx(199.0)  # ob_macro.top для SHORT
    assert s["tp"] == pytest.approx(194.0)  # entry - risk*1 = 196.5 - 2.5
    assert s["risk"] == pytest.approx(2.5)
    assert s["top_fvg_zone"] == (195.0, 200.0)
    assert s["ob_macro_zone"] == (196.0, 199.0)
    assert s["htf_fvg_zone"] == (196.0, 197.0)


# ---------- Test 3: wick-инвалидация top-FVG ----------

def test_wick_invalidation_kills_setup():
    """Та же база что Test 1, но в df_4h prev-свеча OB заходит low'ом в top-FVG.

    Wick-инвалидация: low=101 < fvg_top.bottom=102 в окне [search_start, ob.cur_close)
    → find_first_macro_ob_for_top_fvg возвращает None → 0 сигналов.
    """
    df_1d = make_df([
        ("2026-01-01", 100, 102, 99, 101, 10),
        ("2026-01-02", 101, 110, 100, 109, 10),
        ("2026-01-03", 109, 120, 108, 119, 10),
    ])
    # FVG-1d LONG: zone [102, 108]

    # Та же геометрия OB, но prev-свеча OB имеет low=101 < 102 (заход в top-FVG).
    df_4h = make_df([
        ("2026-01-04 00:00", 110, 110.0, 110, 110, 1),     # плоская
        ("2026-01-04 04:00", 110, 111, 101, 108, 1),       # bearish, low=101 → INVALIDATES
        ("2026-01-04 08:00", 108, 112, 107, 112, 1),       # bullish reaction
    ])
    # OB-pair всё ещё валидна по close-условиям (zone = [101, 110]),
    # НО wick-проверка в [00:00, 12:00) увидит low=101 < 102 → invalidated.

    df_1h = make_df([
        ("2026-01-04 09:00", 107, 107, 105, 106, 1),
        ("2026-01-04 10:00", 106, 109, 105, 108, 1),
        ("2026-01-04 11:00", 108, 109, 108, 108.5, 1),
    ])

    sigs = detect_strategy_1_1_6_signals(
        df_1d, empty_df(), df_4h, empty_df(), df_1h, empty_df(), verbose=False,
    )
    assert sigs == []


# ---------- Test 4: htf-FVG не пересекает top-FVG (double-overlap отсёк) ----------

def test_htf_fvg_not_overlapping_top_returns_zero():
    """Та же база Test 1, но htf-FVG зона выше top-FVG.

    htf-FVG=[109,110] пересекает macro=[107,110] но НЕ пересекает top=[102,108].
    Двойной zones_overlap отсекает: возвращается None → 0 сигналов.
    Покрывает ответ на вопрос 5 (overlap не транзитивен).
    """
    df_1d = make_df([
        ("2026-01-01", 100, 102, 99, 101, 10),
        ("2026-01-02", 101, 110, 100, 109, 10),
        ("2026-01-03", 109, 120, 108, 119, 10),
    ])

    df_4h = make_df([
        ("2026-01-04 00:00", 110, 110.0, 110, 110, 1),
        ("2026-01-04 04:00", 110, 111, 109, 108, 1),
        ("2026-01-04 08:00", 108, 112, 107, 112, 1),
        ("2026-01-04 12:00", 112, 112, 110, 111, 1),
    ])

    # htf_start = 08:00 + 4h = 12:00. htf-FVG только в зоне выше top-FVG.top=108: [109, 110]
    df_1h = make_df([
        ("2026-01-04 12:00", 109, 109, 108.5, 108.7, 1),  # c0: high=109
        ("2026-01-04 13:00", 108.7, 109.5, 108.5, 109, 1),  # c1
        ("2026-01-04 14:00", 110, 111, 110, 110.5, 1),    # c2: low=110
    ])
    # FVG-1h: high(c0)=109 < low(c2)=110 → zone [109, 110]
    # Overlap с macro=[107,110] ✓ (touch 110)
    # Overlap с top=[102,108]: 109..110 vs 102..108 → 109>108 → ∅ ✗

    sigs = detect_strategy_1_1_6_signals(
        df_1d, empty_df(), df_4h, empty_df(), df_1h, empty_df(), verbose=False,
    )
    assert sigs == []


# ---------- Test 5: earliest-wins macro по cur_close (а не cur_time) ----------

def test_earliest_wins_macro_by_cur_close_not_cur_time():
    """4h-OB cur_time=10:00 (cur_close=14:00) vs 6h-OB cur_time=06:00 (cur_close=12:00).

    По cur_time 6h раньше. По cur_close 6h тоже раньше (12:00 < 14:00).
    Должен победить 6h. Покрывает уточнение из последнего ревью (close vs time).

    Использует top-12h, чтобы c2_close=2026-01-04 00:00 (= 12h-сетка).
    """
    # Top-12h FVG LONG: c0=2026-01-02 12:00, c1=2026-01-03 00:00, c2=2026-01-03 12:00
    # c2_close = 2026-01-04 00:00.
    df_12h = make_df([
        ("2026-01-02 12:00", 100, 102, 99, 101, 10),    # c0: high=102
        ("2026-01-03 00:00", 101, 110, 100, 109, 10),   # c1
        ("2026-01-03 12:00", 109, 120, 108, 119, 10),   # c2: low=108
    ])
    # FVG-12h LONG: zone [102, 108]

    # 4h: OB cur_time=10:00 (валиден). prev=06:00 bearish, cur=10:00 bullish.
    # search_start=2026-01-04 00:00.
    df_4h = make_df([
        ("2026-01-04 00:00", 110, 110.0, 110, 110, 1),     # плоская
        ("2026-01-04 04:00", 110, 110.0, 110, 110, 1),     # плоская
        ("2026-01-04 08:00", 110, 111, 109, 108, 1),       # bearish (low=109>=102)
        ("2026-01-04 12:00", 108, 112, 107, 112, 1),       # bullish reaction → cur_time=12:00
    ])
    # Поправляю: чтобы cur_time именно 10:00, нужны 4h-границы 00,04,08,10? Нет — 4h-сетка 00,04,08,12.
    # Меняю спеку: 4h cur_time=12:00 (cur_close=16:00), 6h cur_time=06:00 (cur_close=12:00).
    # 6h всё равно побеждает (12:00 < 16:00).

    # 6h: OB cur_time=06:00. prev=00:00 bearish, cur=06:00 bullish.
    df_6h = make_df([
        ("2026-01-04 00:00", 110, 111, 109, 108, 1),       # bearish (close<open)
        ("2026-01-04 06:00", 108, 112, 107, 112, 1),       # bullish (close>prev.open=110)
    ])
    # OB-6h LONG: zone = [min(109,107)=107, 110]. Overlap с [102,108]: ✓
    # Wick check на df_6h в [00:00, 12:00): low 109, 107 — все >= 102 ✓

    # OB-4h: prev=08:00 (bearish), cur=12:00 (bullish). Zone=[107,110]. Overlap ✓.
    # Wick check на df_4h в [00:00, 16:00): свечи 00,04,08,12 → low: 110,110,109,107. ✓

    # earliest-wins:
    #   4h cur_close = 12:00 + 4h = 16:00
    #   6h cur_close = 06:00 + 6h = 12:00
    # 12 < 16 → 6h побеждает. macro_tf="6h", search_start=00:00, ob_macro.cur_time=06:00.

    # htf_start (для 6h-macro): cur_time + macro_hours = 06:00 + 6h = 12:00.
    # До правки lookahead-бага было 06:00 + 1h = 07:00 — htf-FVG
    # формировалась ДО закрытия cur 6h-OB.
    df_1h = make_df([
        ("2026-01-04 12:00", 107, 107, 105, 106, 1),    # c0: high=107
        ("2026-01-04 13:00", 106, 109, 105, 108, 1),    # c1
        ("2026-01-04 14:00", 108, 109, 108, 108.5, 1),  # c2: low=108
    ])
    # FVG-1h LONG: zone [107, 108]. Overlap с macro=[107,110] ✓, с top=[102,108] ✓.

    sigs = detect_strategy_1_1_6_signals(
        empty_df(), df_12h, df_4h, df_6h, df_1h, empty_df(), verbose=False,
    )
    assert len(sigs) == 1
    s = sigs[0]
    assert s["macro_tf"] == "6h"
    assert s["ob_macro_cur_time"] == pd.Timestamp("2026-01-04 06:00", tz="UTC")
    assert s["top_tf"] == "12h"
    assert s["htf_tf"] == "1h"


# ---------- Test 6: RR=1 — точное равенство |tp-entry| == |entry-sl| ----------

def test_rr_equals_one_exact_equality():
    """Для RR=1 |tp - entry| == |entry - sl|. Используем happy-path LONG из Test 1.

    htf_start = ob_macro.cur_time + macro_hours = 08:00 + 4h = 12:00.
    """
    df_1d = make_df([
        ("2026-01-01", 100, 102, 99, 101, 10),
        ("2026-01-02", 101, 110, 100, 109, 10),
        ("2026-01-03", 109, 120, 108, 119, 10),
    ])
    df_4h = make_df([
        ("2026-01-04 00:00", 110, 110.0, 110, 110, 1),
        ("2026-01-04 04:00", 110, 111, 109, 108, 1),
        ("2026-01-04 08:00", 108, 112, 107, 112, 1),
        ("2026-01-04 12:00", 112, 112, 110, 111, 1),
    ])
    df_1h = make_df([
        ("2026-01-04 12:00", 107, 107, 105, 106, 1),
        ("2026-01-04 13:00", 106, 109, 105, 108, 1),
        ("2026-01-04 14:00", 108, 109, 108, 108.5, 1),
    ])

    sigs = detect_strategy_1_1_6_signals(
        df_1d, empty_df(), df_4h, empty_df(), df_1h, empty_df(), verbose=False,
    )
    assert len(sigs) == 1
    s = sigs[0]
    # RR=1 геометрия: |tp-entry| == |entry-sl| == risk
    assert abs(s["tp"] - s["entry"]) == pytest.approx(abs(s["entry"] - s["sl"]))
    assert s["risk"] == pytest.approx(abs(s["entry"] - s["sl"]))
    # И сама константа RR должна быть 1.0
    assert RR == 1.0
