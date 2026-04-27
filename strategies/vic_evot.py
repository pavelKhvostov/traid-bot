"""VIC_EVOT: подтверждение FVG-15m + LL/HH-фрактал на уровне maxV(D-1)."""
from __future__ import annotations

import pandas as pd

from strategies.base import Level, Signal

# Окно поиска фрактала: фрактал может быть на 0..FRACTAL_WINDOW-1 позиций
# раньше FVG-start (i). k=0 — классический случай (фрактал = i), k=3 —
# фрактал на 3 свечи раньше FVG. Расширение спеки §3 п.2.
FRACTAL_WINDOW = 4


def detect_vic_evot(
    df_15m: pd.DataFrame,
    df_1d: pd.DataFrame,
    vic_level: float | None,
    symbol: str,
    last_closed_15m_open_time: pd.Timestamp,
) -> Signal | None:
    """Возвращает Signal, если все 5 условий §3 спеки выполнены, иначе None.

    Контракт каллера:
      - df_15m: 15m свечи; df_15m.iloc[-1] — свеча с open_time
        last_closed_15m_open_time. Минимум 5 свечей (k=0); для k>0 нужна
        более глубокая история (n ≥ k+5), иначе соответствующее k пропущено.
        Cross-midnight: свечи i-2/i-1 могут быть из ПРЕДЫДУЩЕГО дня.
      - df_1d:  1d свечи; df_1d.iloc[-1] — последняя ЗАКРЫТАЯ дневная (D-1).
      - vic_level: maxV(D-1), уже посчитан через calculate_vic_d.
      - Колонки lowercase (формат data_manager): open/high/low/close/volume.
      - DatetimeIndex (UTC).

    День D для условия 1 (касание в day D) выводится из i+2.normalize().

    FVG-start i фиксирован на n-3 (i+2 = last_closed = n-1). Фрактал f
    ищется в окне {n-3, n-4, n-5, n-6} — берётся первый валидный
    (ближайший к i). k = pos_i - pos_f сохраняется в meta.
    """
    if vic_level is None:
        return None
    if df_15m is None or len(df_15m) < 5:
        return None
    if df_1d is None or df_1d.empty:
        return None

    close_d_minus_1 = float(df_1d.iloc[-1]["close"])
    if close_d_minus_1 > vic_level:
        direction = "LONG"
    elif close_d_minus_1 < vic_level:
        direction = "SHORT"
    else:
        return None

    n = len(df_15m)
    pos_i = n - 3        # FVG-start, фиксировано
    pos_ip2 = n - 1      # last_closed = i+2
    c_i = df_15m.iloc[pos_i]
    c_ip2 = df_15m.iloc[pos_ip2]

    # Условие 3 (FVG между i и i+2). Не зависит от позиции фрактала.
    if direction == "LONG":
        high_i = float(c_i["high"])
        low_ip2 = float(c_ip2["low"])
        if not (high_i < low_ip2 and low_ip2 > vic_level):
            return None
    else:
        low_i = float(c_i["low"])
        high_ip2 = float(c_ip2["high"])
        if not (low_i > high_ip2 and high_ip2 < vic_level):
            return None

    # Условия 1+2 (касание + LL/HH-фрактал) — поиск в окне FRACTAL_WINDOW
    # позиций, начиная с n-3 (классика, k=0) и глубже до n-6 (k=3).
    # Берём первый валидный (ближайший к FVG-start).
    day_start = pd.Timestamp(last_closed_15m_open_time).normalize()
    found_pos_f: int | None = None
    for k in range(FRACTAL_WINDOW):
        pos_f = pos_i - k
        if pos_f - 2 < 0 or pos_f + 2 >= n:
            continue
        c_f = df_15m.iloc[pos_f]
        c_fm2 = df_15m.iloc[pos_f - 2]
        c_fm1 = df_15m.iloc[pos_f - 1]
        c_fp1 = df_15m.iloc[pos_f + 1]
        c_fp2 = df_15m.iloc[pos_f + 2]

        if direction == "LONG":
            low_f = float(c_f["low"])
            if not (low_f < float(c_fm2["low"])
                    and low_f < float(c_fm1["low"])
                    and low_f < float(c_fp1["low"])
                    and low_f < float(c_fp2["low"])):
                continue
            if not (low_f < vic_level):
                continue
            touch_window = df_15m.iloc[: pos_f + 1]
            touch_window = touch_window[touch_window.index >= day_start]
            if touch_window.empty or not bool((touch_window["low"] <= vic_level).any()):
                continue
        else:  # SHORT
            high_f = float(c_f["high"])
            if not (high_f > float(c_fm2["high"])
                    and high_f > float(c_fm1["high"])
                    and high_f > float(c_fp1["high"])
                    and high_f > float(c_fp2["high"])):
                continue
            if not (high_f > vic_level):
                continue
            touch_window = df_15m.iloc[: pos_f + 1]
            touch_window = touch_window[touch_window.index >= day_start]
            if touch_window.empty or not bool((touch_window["high"] >= vic_level).any()):
                continue

        found_pos_f = pos_f
        break

    if found_pos_f is None:
        return None

    # Точка входа = close(i+2) — рынок-вход сразу при закрытии 15m
    # свечи-сигнала, без ожидания возврата к FVG-границе.
    entry_price = float(c_ip2["close"])

    day_d_minus_1 = pd.to_datetime(df_1d.index[-1], utc=True).normalize()
    fractal_time = pd.to_datetime(df_15m.index[found_pos_f], utc=True)

    return Signal(
        strategy="VIC_EVOT",
        symbol=symbol,
        timeframe="1d",
        direction=direction,
        confirm_time=last_closed_15m_open_time,
        price=float(entry_price),
        level=Level(price=float(vic_level), day=day_d_minus_1),
        meta={
            "source_tf": "1d",
            "confirm_type": "FVG-15m + LL-фрактал",
            "fractal_time": fractal_time.isoformat(),
            "vic_level": float(vic_level),
            "fractal_offset_k": pos_i - found_pos_f,
        },
    )
