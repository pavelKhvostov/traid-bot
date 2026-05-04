"""Strategy 1.2.0: Trend-aligned sweep reversal на BTC.

Гипотеза: высокий WR при weekly-частоте достигается совмещением
4 SMC-фильтров вместе:

  1. Trend gate (EMA-200 на 1d) — отрезает контр-тренд лосы.
  2. Top zone (active OB-1d в направлении тренда) — макро-контекст.
  3. Liquidity sweep на 1h (OB-1h пара пробила min/max последних 24 часов)
     — классический SMC-предиктор разворота.
  4. Entry FVG-15m в OB-1h zone — точка входа с retest'ом.

Управление сделкой:
  - Entry: 80% deep в FVG-15m (shallow = чаще fillится).
  - SL: на свипнутом low/high пары OB-1h + 0.10% буфер (тугой SL).
  - TP: RR=1.0 (низкий ratio = высокий WR).
  - no_entry: TP до entry → отмена (учтено в бэктесте).

Возвращает signal_time = c2_time FVG-15m (момент когда entry-зона сформирована).
"""
from __future__ import annotations

import pandas as pd

from strategies.strategy_1_1_1 import (
    FVGZone,
    OBZone,
    detect_fvg,
    detect_ob_pair,
    zones_overlap,
)

EMA_PERIOD = 200          # EMA-200 на 1d для trend gate
SWEEP_LOOKBACK = 24       # последние 24 1h-свечи для проверки сметы
TOP_OB_LOOKBACK_DAYS = 14 # сколько дней назад ищем активный OB-1d
FVG_15M_WINDOW_HOURS = 4  # окно для поиска FVG-15m после OB-1h close


def compute_ema(series: pd.Series, period: int) -> pd.Series:
    """Pandas EWM с adjust=False — стандартная EMA."""
    return series.ewm(span=period, adjust=False).mean()


def is_sweep_long(df_1h: pd.DataFrame, i: int) -> tuple[bool, float]:
    """Сметнули ли low предыдущих SWEEP_LOOKBACK свечей парой (i-1, i)?

    Возвращает (sweep_ok, swept_low) — swept_low = min(low_c1, low_c2).
    """
    if i < SWEEP_LOOKBACK + 1:
        return False, 0.0
    c1_low = float(df_1h.iloc[i - 1]["low"])
    c2_low = float(df_1h.iloc[i]["low"])
    pair_low = min(c1_low, c2_low)
    prior_low = float(df_1h.iloc[i - SWEEP_LOOKBACK - 1:i - 1]["low"].min())
    return pair_low < prior_low, pair_low


def is_sweep_short(df_1h: pd.DataFrame, i: int) -> tuple[bool, float]:
    if i < SWEEP_LOOKBACK + 1:
        return False, 0.0
    c1_high = float(df_1h.iloc[i - 1]["high"])
    c2_high = float(df_1h.iloc[i]["high"])
    pair_high = max(c1_high, c2_high)
    prior_high = float(df_1h.iloc[i - SWEEP_LOOKBACK - 1:i - 1]["high"].max())
    return pair_high > prior_high, pair_high


def find_active_top_ob(
    df_1d: pd.DataFrame,
    cur_time: pd.Timestamp,
    direction: str,
    ob_1h_b: float,
    ob_1h_t: float,
) -> OBZone | None:
    """Активный OB-1d в направлении тренда, пересекающийся с OB-1h.

    Активный = в range [cur_time - 14d, cur_time], не было закрытия 1d через
    границу OB (LONG: close < bottom; SHORT: close > top).
    """
    cutoff = cur_time - pd.Timedelta(days=TOP_OB_LOOKBACK_DAYS)
    df_window = df_1d[(df_1d.index >= cutoff) & (df_1d.index <= cur_time)]
    if len(df_window) < 2:
        return None
    n = len(df_window)
    for j in range(n - 1, 0, -1):
        ob = detect_ob_pair(df_window, j)
        if ob is None or ob.direction != direction:
            continue
        # Проверка что zone не инвалидирована между cur_time OB и нашим cur_time.
        df_check = df_window[
            (df_window.index > ob.cur_time) & (df_window.index < cur_time)
        ]
        invalidated = False
        for _, row in df_check.iterrows():
            if direction == "LONG" and float(row["close"]) < ob.bottom:
                invalidated = True; break
            if direction == "SHORT" and float(row["close"]) > ob.top:
                invalidated = True; break
        if invalidated:
            continue
        if zones_overlap(ob.bottom, ob.top, ob_1h_b, ob_1h_t):
            return ob
    return None


def find_fvg_15m_in_window(
    df_15m: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    direction: str,
    ob_b: float,
    ob_t: float,
) -> FVGZone | None:
    """Первая FVG-15m нужного направления в окне, пересекающаяся с OB-1h."""
    df_window = df_15m[(df_15m.index >= start) & (df_15m.index <= end)]
    for k in range(2, len(df_window)):
        fvg = detect_fvg(df_window, k)
        if fvg is None or fvg.direction != direction:
            continue
        if not zones_overlap(fvg.bottom, fvg.top, ob_b, ob_t):
            continue
        return fvg
    return None


def detect_strategy_1_2_0_signals(
    df_1d: pd.DataFrame,
    df_1h: pd.DataFrame,
    df_15m: pd.DataFrame,
    sl_buffer_pct: float = 0.001,
    entry_pct: float = 0.80,
    require_top_ob: bool = True,
    require_trend: bool = True,
    fvg_window_hours: int = FVG_15M_WINDOW_HOURS,
    verbose: bool = False,
) -> list[dict]:
    """Сканирует все 1h-свечи и собирает сигналы по логике Strategy 1.2.0."""
    if len(df_1d) < EMA_PERIOD + 1:
        return []

    ema = compute_ema(df_1d["close"], EMA_PERIOD)
    df_1d_with_ema = df_1d.assign(ema=ema)

    counters = {
        "candles": 0, "ob_pair": 0,
        "trend_long": 0, "trend_short": 0, "no_trend": 0,
        "sweep_ok": 0, "top_ob_ok": 0, "fvg_15m_ok": 0,
    }

    signals: list[dict] = []
    n = len(df_1h)

    for i in range(SWEEP_LOOKBACK + 2, n):
        counters["candles"] += 1
        cur_time = df_1h.index[i]

        # 1. Trend gate (опционально).
        df_1d_past = df_1d_with_ema[df_1d_with_ema.index < cur_time]
        if df_1d_past.empty:
            continue
        last_1d = df_1d_past.iloc[-1]
        if pd.isna(last_1d["ema"]):
            continue
        close_1d = float(last_1d["close"])
        ema_1d = float(last_1d["ema"])
        if require_trend:
            if close_1d > ema_1d:
                trend_dir = "LONG"
                counters["trend_long"] += 1
            elif close_1d < ema_1d:
                trend_dir = "SHORT"
                counters["trend_short"] += 1
            else:
                counters["no_trend"] += 1
                continue
        else:
            trend_dir = None  # будем брать направление от OB-1h pair

        # 2. OB-1h pair (i-1, i). Если trend gate включён — направление должно совпасть.
        ob_1h = detect_ob_pair(df_1h, i)
        if ob_1h is None:
            continue
        if require_trend and ob_1h.direction != trend_dir:
            continue
        if not require_trend:
            trend_dir = ob_1h.direction
        counters["ob_pair"] += 1

        # 3. Liquidity sweep на 1h.
        if trend_dir == "LONG":
            sweep_ok, swept_extreme = is_sweep_long(df_1h, i)
        else:
            sweep_ok, swept_extreme = is_sweep_short(df_1h, i)
        if not sweep_ok:
            continue
        counters["sweep_ok"] += 1

        # 4. Active OB-1d top zone (опционально).
        top_ob = None
        if require_top_ob:
            top_ob = find_active_top_ob(
                df_1d, cur_time, trend_dir, ob_1h.bottom, ob_1h.top,
            )
            if top_ob is None:
                continue
            counters["top_ob_ok"] += 1

        # 5. FVG-15m в окне после закрытия OB-1h.
        fvg_search_start = ob_1h.cur_time + pd.Timedelta(hours=1)
        fvg_search_end = ob_1h.cur_time + pd.Timedelta(hours=1 + fvg_window_hours)
        fvg_15m = find_fvg_15m_in_window(
            df_15m, fvg_search_start, fvg_search_end,
            trend_dir, ob_1h.bottom, ob_1h.top,
        )
        if fvg_15m is None:
            continue
        counters["fvg_15m_ok"] += 1

        # 6. Entry, SL, TP.
        fw = fvg_15m.top - fvg_15m.bottom
        if trend_dir == "LONG":
            entry = fvg_15m.bottom + entry_pct * fw
            sl = swept_extreme - sl_buffer_pct * entry
        else:
            entry = fvg_15m.top - entry_pct * fw
            sl = swept_extreme + sl_buffer_pct * entry
        risk = abs(entry - sl)
        if risk <= 0:
            continue

        signals.append({
            "direction": trend_dir,
            "signal_time": fvg_15m.c2_time,
            "entry": float(entry),
            "sl": float(sl),
            "risk": float(risk),
            "ob_1h_prev_time": ob_1h.prev_time,
            "ob_1h_cur_time": ob_1h.cur_time,
            "ob_1h_zone": (ob_1h.bottom, ob_1h.top),
            "swept_extreme": float(swept_extreme),
            "fvg_15m_c0_time": fvg_15m.c0_time,
            "fvg_15m_c2_time": fvg_15m.c2_time,
            "fvg_15m_zone": (fvg_15m.bottom, fvg_15m.top),
            "top_ob_time": top_ob.cur_time if top_ob else None,
            "top_ob_zone": (top_ob.bottom, top_ob.top) if top_ob else None,
            "trend_dir": trend_dir,
            "close_1d": close_1d,
            "ema_1d": ema_1d,
        })

    if verbose:
        print(f"[FUNNEL] candles scanned: {counters['candles']}")
        print(f"  trend LONG: {counters['trend_long']}  SHORT: {counters['trend_short']}  none: {counters['no_trend']}")
        print(f"  + OB-1h pair: {counters['ob_pair']}")
        print(f"  + sweep OK: {counters['sweep_ok']}")
        if require_top_ob:
            print(f"  + active top OB-1d: {counters['top_ob_ok']}")
        print(f"  + FVG-15m found: {counters['fvg_15m_ok']}")
        print(f"  signals raw: {len(signals)}")
    return signals
