"""Unit-тесты для Strategy 1.1.1 — детектор, dedup, simulate_outcome.

Все тесты на искусственных свечах в фикстурах. Никакого I/O, никакой сети.
Покрытие: happy-path 1d/12h, dedup сценарии (macro, top, разные SL),
20m fill timing, edge case (пустой df_12h).
"""
from __future__ import annotations

import pandas as pd
import pytest

from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals
from backtest_strategy_1_1_1 import dedupe_signals, simulate_outcome


# ---------- helpers ----------

def make_df(candles: list[tuple]) -> pd.DataFrame:
    """[(ts_str, open, high, low, close, volume), ...] -> DataFrame с UTC index."""
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


# ---------- Test 1: happy-path LONG через 1d + 4h + 1h + 15m ----------

def test_happy_path_long_via_1d_4h_1h_15m():
    """Полная воронка LONG: OB-D → FVG-4h → OB-1h → FVG-15m."""
    df_1d = make_df([
        ("2026-01-01", 99, 101, 98, 95, 100),    # prev bearish (close < open)
        ("2026-01-02", 95, 110, 92, 110, 100),   # cur bullish, close(110) > prev.open(99)
    ])
    # OB-D LONG zone = [min(98, 92), 99] = [92, 99]

    df_4h = make_df([
        ("2026-01-01 04:00", 90, 93, 90, 92, 10),    # c0 high=93
        ("2026-01-01 08:00", 92, 94, 91, 93, 10),    # c1
        ("2026-01-01 12:00", 95, 96, 95, 95.5, 10),  # c2 low=95
        ("2026-01-01 16:00", 95, 96, 94, 95, 10),    # filler (для invalidation окна)
        ("2026-01-01 20:00", 95, 96, 94, 95, 10),
    ])
    # FVG-4h: c0.high=93 < c2.low=95 → LONG FVG zone [93, 95], в OB-D [92,99]

    df_1h = make_df([
        ("2026-01-03 00:00", 95, 96, 94, 94, 10),     # prev bearish
        ("2026-01-03 01:00", 94, 95.5, 94, 95.5, 10), # cur bullish, close(95.5) > prev.open(95)
    ])
    # OB-1h LONG zone = [min(94, 94), 95] = [94, 95], overlap c FVG-4h и OB-D

    df_15m = make_df([
        ("2026-01-03 00:30", 94.0, 94.2, 93.8, 94.1, 1),
        ("2026-01-03 00:45", 94.1, 94.4, 94.0, 94.3, 1),
        ("2026-01-03 01:00", 94.6, 94.7, 94.6, 94.7, 1),  # c2 low=94.6
    ])
    # FVG-15m: c0.high=94.2 < c2.low=94.6 → LONG zone [94.2, 94.6]

    sigs = detect_strategy_1_1_1_signals(
        df_1d, empty_df(), df_4h, empty_df(), df_1h, empty_df(),
        df_15m, empty_df(), verbose=False,
    )
    assert len(sigs) == 1
    s = sigs[0]
    assert s["direction"] == "LONG"
    assert s["top_tf"] == "1d"
    assert s["fvg_macro_tf"] == "4h"
    assert s["ob_htf_tf"] == "1h"
    assert s["fvg_tf"] == "15m"
    # SL = ob_d.bottom + depth * OB_SL_DEPTH = 92 + (99-92)*0.15 = 93.05
    assert s["sl"] == pytest.approx(93.05)
    assert s["entry"] == pytest.approx((94.2 + 94.6) / 2)


# ---------- Test 2: happy-path LONG через 12h + 6h + 2h + 20m ----------

def test_happy_path_long_via_12h_6h_2h_20m():
    """Полная воронка LONG через альтернативные ТФ: 12h + 6h + 2h + 20m."""
    df_12h = make_df([
        ("2026-01-01 00:00", 99, 101, 98, 95, 100),    # prev bearish
        ("2026-01-01 12:00", 95, 110, 92, 110, 100),   # cur bullish
    ])
    # OB-12h LONG zone = [92, 99], cur_time=2026-01-01 12:00, top_tf_hours=12

    df_6h = make_df([
        ("2026-01-01 00:00", 90, 93, 90, 92, 10),    # c0 high=93
        ("2026-01-01 06:00", 92, 94, 91, 93, 10),    # c1
        ("2026-01-01 12:00", 95, 96, 95, 95.5, 10),  # c2 low=95 (на границе cur_top)
    ])
    # FVG-6h: c0.high=93 < c2.low=95 → LONG zone [93, 95], в OB-12h
    # c2_time=12:00 == ob_top.cur_time → не prev_day, invalidation не проверяем

    df_2h = make_df([
        ("2026-01-02 00:00", 95, 96, 94, 94, 10),     # prev bearish (search_start = cur+12h = 2026-01-02 00:00)
        ("2026-01-02 02:00", 94, 95.5, 94, 95.5, 10), # cur bullish
    ])
    # OB-2h LONG zone = [94, 95]

    # 20m выровнен по эпохе: 00:00, 00:20, 00:40, 01:00, 01:20, ...
    df_20m = make_df([
        ("2026-01-02 00:40", 94.0, 94.2, 93.8, 94.1, 1),
        ("2026-01-02 01:00", 94.1, 94.4, 94.0, 94.3, 1),
        ("2026-01-02 01:20", 94.6, 94.7, 94.6, 94.7, 1),  # c2
    ])
    # FVG-20m: 94.2 < 94.6 → LONG zone [94.2, 94.6]

    sigs = detect_strategy_1_1_1_signals(
        empty_df(), df_12h, empty_df(), df_6h, empty_df(), df_2h,
        empty_df(), df_20m, verbose=False,
    )
    assert len(sigs) == 1
    s = sigs[0]
    assert s["direction"] == "LONG"
    assert s["top_tf"] == "12h"
    assert s["fvg_macro_tf"] == "6h"
    assert s["ob_htf_tf"] == "2h"
    assert s["fvg_tf"] == "20m"


# ---------- Test 3: dedup два разных fvg_macro → 1 строка ----------

def test_dedup_two_macro_fvgs_collapses_to_one_row():
    """Два пути через разные fvg_macro c2_time с одной (entry, sl) → 1 строка."""
    common = {
        "signal_time": pd.Timestamp("2026-01-10 12:00", tz="UTC"),
        "top_tf": "1d",
        "ob_d_time": "2026-01-09 03:00",
        "ob_htf_time": "2026-01-10 14:00",
        "ob_htf_tf": "1h",
        "fvg_time": "2026-01-10 15:00",
        "fvg_tf": "15m",
        "direction": "LONG",
        "entry": 100.0,
        "sl": 95.0,
        "tp": 105.0,
        "risk_pct": 5.0,
        "ob_d_bottom": 95.0, "ob_d_top": 102.0,
        "fvg_macro_top": 99.0, "fvg_macro_bottom": 97.0,
        "intersection_top": 99.0, "intersection_bottom": 97.0,
        "ob_htf_top": 100.5, "ob_htf_bottom": 99.5,
        "fvg_top": 100.5, "fvg_bottom": 99.5,
        "outcome": "win", "activation_time": "2026-01-10 16:00",
        "exit_time": "2026-01-10 18:00", "exit_price": 105.0,
        "hit_type": "tp", "mfe_pct": 5.0, "mae_pct": 0.5,
        "fill_delay_min": 60.0,
    }
    rows = [
        {**common, "fvg_macro_time": "2026-01-09 12:00", "fvg_macro_tf": "4h"},
        {**common, "fvg_macro_time": "2026-01-09 18:00", "fvg_macro_tf": "4h"},
    ]
    out = dedupe_signals(rows)
    assert len(out) == 1
    r = out[0]
    assert r["fvg_macro_count"] == 2
    assert r["fvg_macro_tf"] == "4h"  # оба 4h, sorted-uniq join даёт "4h"
    assert r["fvg_macro_time"] == "2026-01-09 12:00"  # earliest


# ---------- Test 4: dedup два разных top → top_tf="12h,1d" ----------

def test_dedup_two_tops_1d_and_12h_collapses():
    """Один confirm + одна (entry,sl) + два разных top → 1 строка с top_tf='12h,1d'."""
    common = {
        "signal_time": pd.Timestamp("2026-02-16 13:30", tz="UTC"),
        "ob_htf_time": "2026-02-16 16:00",
        "ob_htf_tf": "1h",
        "fvg_macro_time": "2026-02-15 19:00",
        "fvg_macro_tf": "4h",
        "fvg_time": "2026-02-16 16:30",
        "fvg_tf": "15m",
        "direction": "SHORT",
        "entry": 69261.515,
        "sl": 70983.0,
        "tp": 67540.03,
        "risk_pct": 2.5,
        "ob_d_bottom": 68000.0, "ob_d_top": 71000.0,
        "fvg_macro_top": 70000.0, "fvg_macro_bottom": 69000.0,
        "intersection_top": 70000.0, "intersection_bottom": 69000.0,
        "ob_htf_top": 70500.0, "ob_htf_bottom": 69500.0,
        "fvg_top": 69500.0, "fvg_bottom": 69000.0,
        "outcome": "win", "activation_time": "2026-02-16 17:00",
        "exit_time": "2026-02-16 22:00", "exit_price": 67540.03,
        "hit_type": "tp", "mfe_pct": 2.5, "mae_pct": 0.3,
        "fill_delay_min": 30.0,
    }
    rows = [
        {**common, "top_tf": "1d",  "ob_d_time": "2026-02-15 03:00"},
        {**common, "top_tf": "12h", "ob_d_time": "2026-02-15 15:00"},
    ]
    out = dedupe_signals(rows)
    assert len(out) == 1
    r = out[0]
    assert r["top_tf"] == "12h,1d"  # sorted-uniq join
    assert r["top_tf_count"] == 2
    assert r["ob_d_time"] == "2026-02-15 03:00"  # earliest


# ---------- Test 5: dedup разные SL → 2 строки (НЕ схлопываются) ----------

def test_dedup_different_sl_kept_as_separate_rows():
    """Один confirm + один entry + РАЗНЫЕ sl → 2 разные строки.

    Кейс 2026-02-06: разные SL = разный risk = разные трейды.
    См. strategy-1-1-1-разные-sl-на-одном-entry.md.
    """
    common = {
        "signal_time": pd.Timestamp("2026-02-06 00:45", tz="UTC"),
        "top_tf": "1d",
        "fvg_macro_time": "2026-02-05 12:00",
        "fvg_macro_tf": "4h",
        "ob_htf_time": "2026-02-05 23:00",
        "ob_htf_tf": "1h",
        "fvg_time": "2026-02-06 01:00",
        "fvg_tf": "15m",
        "direction": "LONG",
        "entry": 62163.195,
        "tp": 0.0,  # не важно для теста
        "risk_pct": 0.0,
        "fvg_macro_top": 0.0, "fvg_macro_bottom": 0.0,
        "intersection_top": 0.0, "intersection_bottom": 0.0,
        "ob_htf_top": 0.0, "ob_htf_bottom": 0.0,
        "fvg_top": 0.0, "fvg_bottom": 0.0,
        "outcome": "not_filled", "activation_time": "",
        "exit_time": "", "exit_price": "",
        "hit_type": "not_filled", "mfe_pct": 0.0, "mae_pct": 0.0,
        "fill_delay_min": "",
    }
    rows = [
        {**common, "ob_d_time": "2024-10-11 00:00", "sl": 58946.0,
         "ob_d_bottom": 58946.0, "ob_d_top": 60636.01},
        {**common, "ob_d_time": "2024-10-14 00:00", "sl": 62050.0,
         "ob_d_bottom": 62050.0, "ob_d_top": 63206.23},
    ]
    out = dedupe_signals(rows)
    assert len(out) == 2  # разные SL = разные строки
    sls = sorted(r["sl"] for r in out)
    assert sls == [58946.0, 62050.0]


# ---------- Test 6: 20m fill = signal_time + 20min ----------

def test_simulate_outcome_20m_fill_offset_is_20_minutes():
    """Для 20m FVG fill_scan_start = signal_time + 20min (а не 15min)."""
    # Минимальный df_1m: одна свеча через 20 мин с low <= entry → fill срабатывает
    signal_time = pd.Timestamp("2026-01-15 10:20", tz="UTC")
    df_1m = make_df([
        # На +15min: бар, который СТАРЫЙ (некорректный) код увидел бы — НЕ должен попасть в новый scan
        ("2026-01-15 10:35", 100.0, 100.5, 99.5, 100.0, 1),
        # На +20min: первый бар нового scan, fill сработает
        ("2026-01-15 10:40", 100.0, 100.5, 95.0, 100.0, 1),  # low=95 <= entry=100
        # SL/TP-симуляция: следующий бар касается TP
        ("2026-01-15 10:41", 100.0, 110.0, 100.0, 105.0, 1),
    ])
    sig = {
        "signal_time": signal_time,
        "direction": "LONG",
        "entry": 100.0,
        "sl": 90.0,
        "risk": 10.0,
        "fvg_tf": "20m",
        # необходимые поля для base_row:
        "ob_d_cur_time": signal_time, "fvg_macro_c2_time": signal_time,
        "fvg_macro_tf": "4h", "ob_htf_cur_time": signal_time, "ob_htf_tf": "2h",
        "fvg_c2_time": signal_time, "ob_d_zone": (90.0, 105.0),
        "fvg_macro_zone": (95.0, 100.0), "intersection_zone": (95.0, 100.0),
        "ob_htf_zone": (98.0, 102.0), "fvg_zone": (99.0, 101.0),
        "top_tf": "1d",
    }
    row = simulate_outcome(sig, df_1m, 1.0)
    # activation_time должен быть >= signal_time + 20min, т.е. 10:40, не 10:35
    assert row["outcome"] == "win"
    activation_iso = row["activation_time"]  # формат "YYYY-MM-DD HH:MM" UTC+3
    # 10:40 UTC = 13:40 UTC+3
    assert activation_iso == "2026-01-15 13:40"


def test_simulate_outcome_15m_fill_offset_is_15_minutes():
    """Для 15m FVG fill_scan_start = signal_time + 15min (не сломали)."""
    signal_time = pd.Timestamp("2026-01-15 10:00", tz="UTC")
    df_1m = make_df([
        ("2026-01-15 10:14", 100.0, 100.5, 99.5, 100.0, 1),  # ДО +15: пропускается
        ("2026-01-15 10:15", 100.0, 100.5, 95.0, 100.0, 1),  # +15: fill
        ("2026-01-15 10:16", 100.0, 110.0, 100.0, 105.0, 1),  # TP
    ])
    sig = {
        "signal_time": signal_time, "direction": "LONG",
        "entry": 100.0, "sl": 90.0, "risk": 10.0, "fvg_tf": "15m",
        "ob_d_cur_time": signal_time, "fvg_macro_c2_time": signal_time,
        "fvg_macro_tf": "4h", "ob_htf_cur_time": signal_time, "ob_htf_tf": "1h",
        "fvg_c2_time": signal_time, "ob_d_zone": (90.0, 105.0),
        "fvg_macro_zone": (95.0, 100.0), "intersection_zone": (95.0, 100.0),
        "ob_htf_zone": (98.0, 102.0), "fvg_zone": (99.0, 101.0),
        "top_tf": "1d",
    }
    row = simulate_outcome(sig, df_1m, 1.0)
    assert row["outcome"] == "win"
    assert row["activation_time"] == "2026-01-15 13:15"  # 10:15 UTC = 13:15 UTC+3


# ---------- Test 7: edge case — пустой df_12h ----------

def test_detect_with_empty_df_12h_works_via_1d_only():
    """Пустой df_12h не должен ломать стратегию — только 1d-ветка работает."""
    df_1d = make_df([
        ("2026-01-01", 99, 101, 98, 95, 100),
        ("2026-01-02", 95, 110, 92, 110, 100),
    ])
    df_4h = make_df([
        ("2026-01-01 04:00", 90, 93, 90, 92, 10),
        ("2026-01-01 08:00", 92, 94, 91, 93, 10),
        ("2026-01-01 12:00", 95, 96, 95, 95.5, 10),
        ("2026-01-01 16:00", 95, 96, 94, 95, 10),
        ("2026-01-01 20:00", 95, 96, 94, 95, 10),
    ])
    df_1h = make_df([
        ("2026-01-03 00:00", 95, 96, 94, 94, 10),
        ("2026-01-03 01:00", 94, 95.5, 94, 95.5, 10),
    ])
    df_15m = make_df([
        ("2026-01-03 00:30", 94.0, 94.2, 93.8, 94.1, 1),
        ("2026-01-03 00:45", 94.1, 94.4, 94.0, 94.3, 1),
        ("2026-01-03 01:00", 94.6, 94.7, 94.6, 94.7, 1),
    ])

    # df_12h явно пустой → _scan_top("12h") возвращается рано
    sigs = detect_strategy_1_1_1_signals(
        df_1d, empty_df(), df_4h, empty_df(), df_1h, empty_df(),
        df_15m, empty_df(), verbose=False,
    )
    # Должен быть ровно 1 сигнал и только через 1d
    assert len(sigs) == 1
    assert sigs[0]["top_tf"] == "1d"
    assert all(s["top_tf"] != "12h" for s in sigs)
