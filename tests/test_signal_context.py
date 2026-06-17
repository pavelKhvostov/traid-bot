"""Тесты логики авто-контекста сигнала (signal_context).

Покрываем ядро решения — verdict() (ячейка направление × тип дня) и
вспомогательные функции профиля/swing. day_state/build_context требуют
CSV-данные и сети нет — их не тестируем юнитами (визуальная сверка в чате).
"""
import numpy as np
import pandas as pd

from signal_context import verdict, volume_profile, swing_levels, shrunk_rate, signal_grade


# --- signal_grade (etap_249 композитный грейд, год-стабилен 7/7) ---
def test_signal_grade_strong_setup():
    # узкий стоп + Asia + counter-trend (SHORT в растущий) → высокий net, плюсовой класс
    g = signal_grade("SHORT", "TREND_UP", risk_pct=0.30, fvg_tf="15m", hour=3, gauge=0.4)
    assert g["net"] >= 1 and g["label"] == "ВЫСОКОЕ"
    assert "узкий стоп" in g["strong"] and "Asia-сессия" in g["strong"]
    assert g["weak"] == []


def test_signal_grade_weak_setup():
    # широкий стоп + вдогонку + 20m + NY + боковик → глубоко отрицательный
    g = signal_grade("LONG", "ROTATION", risk_pct=0.90, fvg_tf="20m", hour=15, gauge=1.3)
    assert g["net"] <= -2 and g["label"] == "НИЗКОЕ"
    assert "широкий стоп" in g["weak"] and "вход вдогонку (дн. ход выбран)" in g["weak"]


def test_signal_grade_monotone_labels():
    # net растёт → класс не ухудшается
    strong = signal_grade("SHORT", "TREND_UP", 0.30, "15m", 3, 0.4)["net"]
    weak = signal_grade("LONG", "ROTATION", 0.90, "20m", 15, 1.3)["net"]
    assert strong > weak


def test_signal_grade_size_mult_tiered():
    # правило размера (etap_257 TIERED): net>=1 ×1.0, net=0 ×0.75, net=-1 ×0.5
    assert signal_grade("SHORT", "TREND_UP", 0.30, "15m", 3, 0.4)["size_mult"] == 1.0
    # net=0: continuation (нет confluence), средний SL, gauge<1, 15m, час 22 (нет сессии-маркера)
    g0 = signal_grade("LONG", "TREND_UP", 0.45, "15m", 22, 0.4)
    assert g0["net"] == 0 and g0["size_mult"] == 0.75
    # net<=-2 → по умолчанию мягкий режим ×0.25 (GRADE_SKIP_WORST=False)
    weak = signal_grade("LONG", "ROTATION", 0.90, "20m", 15, 1.3)
    assert weak["net"] <= -2 and weak["size_mult"] == 0.25


def test_signal_grade_size_mult_monotone():
    # больше net -> не меньше размер
    nets_mults = [signal_grade("SHORT", "TREND_UP", rp, ft, hr, gz)
                  for rp, ft, hr, gz in [(0.30, "15m", 3, 0.4), (0.50, "15m", 3, 0.4),
                                         (0.90, "20m", 15, 1.3)]]
    mults = [g["size_mult"] for g in nets_mults]
    assert mults == sorted(mults, reverse=True)


# --- shrunk_rate (beta-binomial shrinkage, etap_234) ---
def test_shrunk_rate_empty_returns_prior():
    assert shrunk_rate(0, 0, 0.6) == 0.6


def test_shrunk_rate_large_n_converges_to_empirical():
    # 900/1000 при prior 0.5 -> почти 0.9
    assert abs(shrunk_rate(900, 1000, 0.5) - 0.896) < 0.001


def test_shrunk_rate_small_n_pulled_to_prior():
    # 3/3 = 100% сырой, но с prior 0.5 и alpha=10 стягивается к ~0.62
    v = shrunk_rate(3, 3, 0.5)
    assert 0.55 < v < 0.70


# --- verdict: ключевая находка etap_232 ---
def test_verdict_counter_trend_short_in_uptrend():
    """SHORT в растущий день = сильнейший вход (фейд в сопротивление)."""
    line, size = verdict("SHORT", "TREND_UP")
    assert "CONFLUENCE" in line and "сопротивление" in line
    assert "повышенный" in size


def test_verdict_counter_trend_long_in_downtrend():
    """LONG в падающий день = сильнейший вход (фейд в опору)."""
    line, size = verdict("LONG", "TREND_DOWN")
    assert "CONFLUENCE" in line and "опору" in line
    assert "повышенный" in size


def test_verdict_continuation_is_weak():
    """Вход ПО тренду дня — слабейший случай, минимальный размер."""
    for direction, state in [("LONG", "TREND_UP"), ("SHORT", "TREND_DOWN")]:
        line, size = verdict(direction, state)
        assert "слабейший" in line
        assert "минимальный" in size or "пропуск" in size


def test_verdict_rotation_neutral():
    line, size = verdict("LONG", "ROTATION")
    assert "боковик" in line
    assert size == "размер обычный"


def test_verdict_forming_neutral():
    line, _ = verdict("SHORT", "FORMING")
    assert "формируется" in line


# --- volume_profile edge cases ---
def test_volume_profile_basic():
    # объём сконцентрирован у 100 → POC ~100
    df = pd.DataFrame({
        "high": [101, 100.5, 100.2, 109, 91],
        "low":  [99, 99.5, 99.8, 108, 90],
        "close":[100, 100, 100, 108.5, 90.5],
        "volume":[1000, 1000, 1000, 5, 5],
    })
    poc, vah, val = volume_profile(df, bins=40)
    assert 99 <= poc <= 101
    assert val <= poc <= vah


def test_volume_profile_empty_returns_none():
    assert volume_profile(pd.DataFrame()) is None
    df = pd.DataFrame({"high": [1], "low": [1], "close": [1]})  # нет volume
    assert volume_profile(df) is None


def test_volume_profile_flat_price_returns_none():
    df = pd.DataFrame({"high": [100, 100], "low": [100, 100],
                       "close": [100, 100], "volume": [1, 1]})
    assert volume_profile(df) is None


# --- swing_levels ---
def test_swing_levels_finds_peak_and_trough():
    # пик на idx=2 (110), впадина на idx=4 (90) — оба с n=2 соседями по краям
    highs = [100, 105, 110, 104, 103, 102, 101]
    lows =  [99, 100, 105, 100, 90, 95, 96]
    df = pd.DataFrame({"high": highs, "low": lows,
                       "close": highs, "volume": [1] * 7})
    sh, sl = swing_levels(df, n=2)
    assert 110 in sh
    assert 90 in sl


def test_swing_levels_too_short():
    df = pd.DataFrame({"high": [1, 2], "low": [1, 2],
                       "close": [1, 2], "volume": [1, 1]})
    assert swing_levels(df, n=2) == ([], [])
