"""Unit-тесты для multi_strategy_scanner.

Покрытие:
  - format_signal для всех 6 конфигов × LONG/SHORT (12 кейсов)
  - dedup_key — стабильность ключа
  - check_swept на синтетических OB-htf
  - Конфиг STRATEGIES — 6 стратегий, правильные параметры
"""
from __future__ import annotations

import pandas as pd
import pytest

from multi_strategy_scanner import (
    MAX_SIGNAL_AGE_HOURS,
    NATIVE_TFS,
    STRATEGIES,
    MultiStrategyScanner,
    StrategyConfig,
    check_swept,
    format_signal,
)


# ---------- helpers ----------

def make_df(candles: list[tuple]) -> pd.DataFrame:
    """[(ts_str, open, high, low, close, volume), ...] -> DF UTC index."""
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


# ---------- format_signal: 6 конфигов × LONG/SHORT ----------

def _sig_111(direction="LONG", **kw):
    """Базовый сигнал 1.1.1: macro=FVG, entry=15m/20m FVG."""
    return {
        "symbol": "BTCUSDT",
        "direction": direction,
        "top_tf": kw.get("top_tf", "1d"),
        "fvg_macro_tf": kw.get("fvg_macro_tf", "4h"),
        "ob_htf_tf": kw.get("ob_htf_tf", "1h"),
        "fvg_tf": kw.get("fvg_tf", "15m"),
    }


def _sig_112(direction="LONG", **kw):
    """1.1.2: macro=OB, entry=15m/20m FVG."""
    return {
        "symbol": "BTCUSDT",
        "direction": direction,
        "top_tf": kw.get("top_tf", "1d"),
        "ob_macro_tf": kw.get("ob_macro_tf", "4h"),
        "ob_htf_tf": kw.get("ob_htf_tf", "1h"),
        "fvg_tf": kw.get("fvg_tf", "15m"),
    }


def _sig_113(direction="LONG", **kw):
    """1.1.3: macro=OB, entry=FVG того же ТФ что OB-htf."""
    htf = kw.get("ob_htf_tf", "1h")
    return {
        "symbol": "BTCUSDT",
        "direction": direction,
        "top_tf": kw.get("top_tf", "1d"),
        "ob_macro_tf": kw.get("ob_macro_tf", "4h"),
        "ob_htf_tf": htf,
        "fvg_tf": htf,  # для 1.1.3 fvg_tf == ob_htf_tf
    }


def _sig_114(direction="LONG", **kw):
    """1.1.4: macro=FVG, entry=FVG того же ТФ что OB-htf."""
    htf = kw.get("ob_htf_tf", "1h")
    return {
        "symbol": "BTCUSDT",
        "direction": direction,
        "top_tf": kw.get("top_tf", "1d"),
        "fvg_macro_tf": kw.get("fvg_macro_tf", "4h"),
        "ob_htf_tf": htf,
        "fvg_tf": htf,
    }


def _config_by_name(name: str) -> StrategyConfig:
    for c in STRATEGIES:
        if c.name == name:
            return c
    raise KeyError(name)


def test_format_111_swept_long():
    sig = _sig_111(direction="LONG", top_tf="1d", fvg_macro_tf="4h",
                   ob_htf_tf="1h", fvg_tf="15m")
    text = format_signal(sig, _config_by_name("S111_SWEPT"))
    assert text == (
        "BTC - LONG\n"
        "POI: Daily OB + 4h FVG\n"
        "Volume confirmation: 1h OB + 15m FVG"
    )


def test_format_111_swept_short_12h_top_6h_macro_2h_htf_20m_entry():
    sig = _sig_111(direction="SHORT", top_tf="12h", fvg_macro_tf="6h",
                   ob_htf_tf="2h", fvg_tf="20m")
    text = format_signal(sig, _config_by_name("S111_SWEPT"))
    assert text == (
        "BTC - SHORT\n"
        "POI: 12h OB + 6h FVG\n"
        "Volume confirmation: 2h OB + 20m FVG"
    )


def test_format_112_long():
    sig = _sig_112(direction="LONG", top_tf="1d", ob_macro_tf="4h",
                   ob_htf_tf="1h", fvg_tf="15m")
    text = format_signal(sig, _config_by_name("S112"))
    assert text == (
        "BTC - LONG\n"
        "POI: Daily OB + 4h OB\n"
        "Volume confirmation: 1h OB + 15m FVG"
    )


def test_format_112_short_12h_top_6h_macro_2h_htf_20m_entry():
    sig = _sig_112(direction="SHORT", top_tf="12h", ob_macro_tf="6h",
                   ob_htf_tf="2h", fvg_tf="20m")
    text = format_signal(sig, _config_by_name("S112"))
    assert text == (
        "BTC - SHORT\n"
        "POI: 12h OB + 6h OB\n"
        "Volume confirmation: 2h OB + 20m FVG"
    )


def test_format_113_v1_long():
    """1.1.3: entry-FVG того же ТФ что OB-htf — 1h OB + 1h FVG."""
    sig = _sig_113(direction="LONG", top_tf="1d", ob_macro_tf="4h", ob_htf_tf="1h")
    text = format_signal(sig, _config_by_name("S113_V1"))
    assert text == (
        "BTC - LONG\n"
        "POI: Daily OB + 4h OB\n"
        "Volume confirmation: 1h OB + 1h FVG"
    )


def test_format_113_v1_short_2h_htf():
    sig = _sig_113(direction="SHORT", top_tf="12h", ob_macro_tf="6h", ob_htf_tf="2h")
    text = format_signal(sig, _config_by_name("S113_V1"))
    assert text == (
        "BTC - SHORT\n"
        "POI: 12h OB + 6h OB\n"
        "Volume confirmation: 2h OB + 2h FVG"
    )


def test_format_113_v2_same_format_as_v1():
    """v2 → выглядит точно так же как v1 (без маркировки)."""
    sig = _sig_113(direction="LONG", top_tf="1d", ob_macro_tf="4h", ob_htf_tf="1h")
    text_v1 = format_signal(sig, _config_by_name("S113_V1"))
    text_v2 = format_signal(sig, _config_by_name("S113_V2"))
    assert text_v1 == text_v2


def test_format_114_v1_long():
    """1.1.4: macro=FVG, entry-FVG того же ТФ — 1h OB + 1h FVG."""
    sig = _sig_114(direction="LONG", top_tf="1d", fvg_macro_tf="4h", ob_htf_tf="1h")
    text = format_signal(sig, _config_by_name("S114_V1"))
    assert text == (
        "BTC - LONG\n"
        "POI: Daily OB + 4h FVG\n"
        "Volume confirmation: 1h OB + 1h FVG"
    )


def test_format_114_v1_short_12h_top_6h_macro():
    sig = _sig_114(direction="SHORT", top_tf="12h", fvg_macro_tf="6h", ob_htf_tf="2h")
    text = format_signal(sig, _config_by_name("S114_V1"))
    assert text == (
        "BTC - SHORT\n"
        "POI: 12h OB + 6h FVG\n"
        "Volume confirmation: 2h OB + 2h FVG"
    )


def test_format_114_v2_same_as_v1():
    sig = _sig_114(direction="LONG", top_tf="1d", fvg_macro_tf="4h", ob_htf_tf="1h")
    assert format_signal(sig, _config_by_name("S114_V1")) == format_signal(
        sig, _config_by_name("S114_V2"),
    )


def test_format_111_default_top_when_missing():
    """Если top_tf не задан — fallback на 'Daily' (от 1d default в коде)."""
    sig = {
        "symbol": "BTCUSDT", "direction": "LONG",
        "fvg_macro_tf": "4h", "ob_htf_tf": "1h", "fvg_tf": "15m",
    }
    text = format_signal(sig, _config_by_name("S111_SWEPT"))
    assert "POI: Daily OB + 4h FVG" in text


def test_format_no_circles():
    """Регрессия: убедиться что в формате НЕТ кружков confluence."""
    sig = _sig_111()
    text = format_signal(sig, _config_by_name("S111_SWEPT"))
    assert "🟢" not in text
    assert "🔴" not in text
    assert "⚪" not in text


# ---------- dedup_key ----------

def test_dedup_key_stable_with_tz_naive_input():
    """Ключ одинаковый для tz-naive и tz-aware sigtime."""
    sig_naive = {
        "signal_time": pd.Timestamp("2026-04-15 10:00"),  # без tz
        "direction": "LONG",
        "entry": 65000.0,
    }
    sig_aware = {
        "signal_time": pd.Timestamp("2026-04-15 10:00", tz="UTC"),
        "direction": "LONG",
        "entry": 65000.0,
    }
    config = _config_by_name("S111_SWEPT")
    k1 = MultiStrategyScanner._dedup_key("BTCUSDT", sig_naive, config)
    k2 = MultiStrategyScanner._dedup_key("BTCUSDT", sig_aware, config)
    assert k1 == k2


def test_dedup_key_different_for_different_versions():
    """Один сигнал × разные стратегии = разные ключи."""
    sig = {
        "signal_time": pd.Timestamp("2026-04-15 10:00", tz="UTC"),
        "direction": "LONG",
        "entry": 65000.0,
    }
    k_v1 = MultiStrategyScanner._dedup_key("BTCUSDT", sig, _config_by_name("S113_V1"))
    k_v2 = MultiStrategyScanner._dedup_key("BTCUSDT", sig, _config_by_name("S113_V2"))
    assert k_v1 != k_v2
    assert "S113_V1" in k_v1
    assert "S113_V2" in k_v2


def test_dedup_key_includes_entry():
    """Ключ должен меняться при изменении entry — разные SL = разные трейды."""
    config = _config_by_name("S111_SWEPT")
    sig1 = {"signal_time": pd.Timestamp("2026-04-15 10:00", tz="UTC"),
            "direction": "LONG", "entry": 65000.0}
    sig2 = {"signal_time": pd.Timestamp("2026-04-15 10:00", tz="UTC"),
            "direction": "LONG", "entry": 65500.0}
    k1 = MultiStrategyScanner._dedup_key("BTCUSDT", sig1, config)
    k2 = MultiStrategyScanner._dedup_key("BTCUSDT", sig2, config)
    assert k1 != k2


# ---------- check_swept ----------

def test_swept_long_when_lows_break_below_prev_two():
    """LONG SWEPT: min(c1.low, c2.low) < min(prev1.low, prev2.low)."""
    df_1h = make_df([
        ("2026-04-15 06:00", 100, 102, 98, 101, 1),    # n2 (prev_idx-2): low=98
        ("2026-04-15 07:00", 101, 103, 99, 102, 1),    # n1 (prev_idx-1): low=99
        ("2026-04-15 08:00", 102, 102, 95, 100, 1),    # prev (c1): low=95 — снимает min(98,99)
        ("2026-04-15 09:00", 100, 105, 96, 105, 1),    # cur (c2): low=96
    ])
    df_2h = make_df([])  # не используется
    sig = {
        "ob_htf_tf": "1h",
        "ob_htf_prev_time": pd.Timestamp("2026-04-15 08:00", tz="UTC"),
        "ob_htf_cur_time": pd.Timestamp("2026-04-15 09:00", tz="UTC"),
        "direction": "LONG",
    }
    assert check_swept(sig, df_1h, df_2h) is True


def test_not_swept_long_when_lows_above_prev():
    """LONG NOT-SWEPT: min(c1.low, c2.low) >= min(prev1.low, prev2.low)."""
    df_1h = make_df([
        ("2026-04-15 06:00", 100, 102, 98, 101, 1),    # n2: low=98 (минимум)
        ("2026-04-15 07:00", 101, 103, 99, 102, 1),    # n1
        ("2026-04-15 08:00", 102, 103, 100, 101, 1),   # prev: low=100 (выше)
        ("2026-04-15 09:00", 101, 105, 101, 104, 1),   # cur: low=101
    ])
    df_2h = make_df([])
    sig = {
        "ob_htf_tf": "1h",
        "ob_htf_prev_time": pd.Timestamp("2026-04-15 08:00", tz="UTC"),
        "ob_htf_cur_time": pd.Timestamp("2026-04-15 09:00", tz="UTC"),
        "direction": "LONG",
    }
    assert check_swept(sig, df_1h, df_2h) is False


def test_swept_short_mirror():
    """SHORT SWEPT: max(c1.high, c2.high) > max(prev1.high, prev2.high)."""
    df_1h = make_df([
        ("2026-04-15 06:00", 100, 102, 98, 99, 1),     # n2: high=102
        ("2026-04-15 07:00", 99, 103, 98, 102, 1),     # n1: high=103
        ("2026-04-15 08:00", 102, 108, 100, 107, 1),   # prev (c1): high=108 — снимает max(102,103)
        ("2026-04-15 09:00", 107, 105, 95, 96, 1),     # cur (c2): high=105
    ])
    df_2h = make_df([])
    sig = {
        "ob_htf_tf": "1h",
        "ob_htf_prev_time": pd.Timestamp("2026-04-15 08:00", tz="UTC"),
        "ob_htf_cur_time": pd.Timestamp("2026-04-15 09:00", tz="UTC"),
        "direction": "SHORT",
    }
    assert check_swept(sig, df_1h, df_2h) is True


def test_swept_returns_none_when_data_missing():
    """Если prev_time/cur_time не в df — None (граничный случай)."""
    df_1h = make_df([
        ("2026-04-15 06:00", 100, 102, 98, 101, 1),
        ("2026-04-15 07:00", 101, 103, 99, 102, 1),
    ])
    df_2h = make_df([])
    sig = {
        "ob_htf_tf": "1h",
        "ob_htf_prev_time": pd.Timestamp("2026-04-15 08:00", tz="UTC"),  # нет в df
        "ob_htf_cur_time": pd.Timestamp("2026-04-15 09:00", tz="UTC"),
        "direction": "LONG",
    }
    assert check_swept(sig, df_1h, df_2h) is None


# ---------- STRATEGIES конфиг ----------

def test_strategies_count_is_6():
    assert len(STRATEGIES) == 6


def test_strategies_have_unique_names():
    names = [s.name for s in STRATEGIES]
    assert len(names) == len(set(names))
    assert set(names) == {"S111_SWEPT", "S112", "S113_V1", "S113_V2", "S114_V1", "S114_V2"}


def test_only_111_has_swept_filter():
    """Decision 2026-05-06: SWEPT-фильтр только для 1.1.1."""
    swept_names = [s.name for s in STRATEGIES if s.apply_swept]
    assert swept_names == ["S111_SWEPT"]


def test_macro_pattern_correct():
    by_name = {s.name: s for s in STRATEGIES}
    assert by_name["S111_SWEPT"].macro_pattern == "FVG"
    assert by_name["S112"].macro_pattern == "OB"
    assert by_name["S113_V1"].macro_pattern == "OB"
    assert by_name["S113_V2"].macro_pattern == "OB"
    assert by_name["S114_V1"].macro_pattern == "FVG"
    assert by_name["S114_V2"].macro_pattern == "FVG"


def test_htf_tf_minutes_flag():
    """1.1.3 / 1.1.4 — htf_tf_minutes=True (без 15m/20m в детекторе)."""
    by_name = {s.name: s for s in STRATEGIES}
    assert by_name["S111_SWEPT"].htf_tf_minutes is False
    assert by_name["S112"].htf_tf_minutes is False
    assert by_name["S113_V1"].htf_tf_minutes is True
    assert by_name["S113_V2"].htf_tf_minutes is True
    assert by_name["S114_V1"].htf_tf_minutes is True
    assert by_name["S114_V2"].htf_tf_minutes is True


def test_113_kwargs_correct():
    by_name = {s.name: s for s in STRATEGIES}
    assert by_name["S113_V1"].detect_kwargs == {"fvg_variant": "v1", "macro_mode": "untouched"}
    assert by_name["S113_V2"].detect_kwargs == {"fvg_variant": "v2", "macro_mode": "untouched"}


def test_114_kwargs_correct():
    by_name = {s.name: s for s in STRATEGIES}
    assert by_name["S114_V1"].detect_kwargs == {"fvg_variant": "v1"}
    assert by_name["S114_V2"].detect_kwargs == {"fvg_variant": "v2"}


def test_max_signal_age_is_1_hour():
    """Регрессия: уменьшено с 2h до 1h при рефакторе."""
    assert MAX_SIGNAL_AGE_HOURS == 1


def test_native_tfs():
    assert NATIVE_TFS == ["1m", "15m", "1h", "4h", "1d"]
