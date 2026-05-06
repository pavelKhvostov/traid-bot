"""Strategy 1.1.5: OB-{1d,12h} + FVG-{4h,6h} → RDRB4-{1h,2h}, entry на касании RDRB зоны.

Каскад:

  1.1.5:  OB-top → FVG-macro → RDRB4-htf (entry на касании top-зоны RDRB)

Геометрия:
  TOP    = OB на 1d/12h, обе ветки параллельно.
  MACRO  = первый валидный FVG на 4h/6h после top-OB (earliest-wins),
           zones_overlap с top-OB, направление совпадает.
  HTF    = первый валидный 4-candle RDRB на 1h/2h (earliest-wins по c4_close),
           зона RDRB zones_overlap с FVG-macro, направление совпадает.

Lookahead-prevention:
  - macro-FVG: search_start = top_ob.cur_time + top_tf_hours
  - htf-RDRB:  search_start (c1_time) = fvg_macro.c2_time + macro_tf_hours

Entry/SL/TP:
  entry  = top of RDRB zone (LONG) / bottom of RDRB zone (SHORT)
           = c4.low (LONG) / c4.high (SHORT)
  sl     = max(c1.high, c2.high) (LONG) / min(c1.low, c2.low) (SHORT)
           — без буфера, по спеке пользователя
  tp     = entry ± risk × RR
  RR     = 1.0 (фикс, как в 1.1.6 baseline)

RDRB-4 геометрия (canon из research/rdrb_4candle/scan_rdrb4.py):
  SHORT: c1.low > c2.low AND c1.low < c2.close AND c2.low < c4.high
         AND c3.close < c2.low AND c1.low > c4.high
  LONG (mirror): high/low swap.
  Zone:
    SHORT: [c4.high, c1.low]   (low, high)
    LONG:  [c1.high, c4.low]
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from strategies.strategy_1_1_1 import (
    FVGZone,
    OBZone,
    detect_fvg,
    detect_ob_pair,
    zones_overlap,
)

RR = 1.0


@dataclass
class RDRB4Zone:
    """4-candle RDRB.

    Расширенная зона = пересечение фитилей c2 и c4 + растяжка до c1-extremum.
      SHORT: zone = [max(c2.low, c4_body_high), c1.low]
        где c4_body_high = max(c4.open, c4.close).
      LONG:  zone = [c1.high, min(c2.high, c4_body_low)]
        где c4_body_low = min(c4.open, c4.close).

    Entry — ближний край зоны (цена приходит к нему первым касанием):
      SHORT: entry = bottom (max(c2.low, c4_body_high))
      LONG:  entry = top    (min(c2.high, c4_body_low))
    """
    direction: str
    bottom: float
    top: float
    c1_time: pd.Timestamp
    c4_time: pd.Timestamp
    c1_high: float
    c1_low: float
    c2_high: float
    c2_low: float
    c4_body_high: float
    c4_body_low: float


def detect_rdrb4(df: pd.DataFrame, idx: int) -> RDRB4Zone | None:
    """4-candle RDRB на (df[idx-3..idx]). idx = c4.

    SHORT: c1.low > c2.low, c1.low < c2.close, c2.low < c4.high,
           c3.close < c2.low, c1.low > c4.high
    LONG:  mirror.
    """
    if idx < 3 or idx >= len(df):
        return None
    c1 = df.iloc[idx - 3]
    c2 = df.iloc[idx - 2]
    c3 = df.iloc[idx - 1]
    c4 = df.iloc[idx]
    c1l, c1h = float(c1["low"]), float(c1["high"])
    c2l, c2h = float(c2["low"]), float(c2["high"])
    c2c = float(c2["close"])
    c3c = float(c3["close"])
    c4o, c4c = float(c4["open"]), float(c4["close"])
    c4l, c4h = float(c4["low"]), float(c4["high"])
    c4_body_high = max(c4o, c4c)
    c4_body_low = min(c4o, c4c)

    # SHORT
    if (c1l > c2l) and (c1l < c2c) and (c2l < c4h) and (c3c < c2l) and (c1l > c4h):
        # Расширенная зона = пересечение нижнего фитиля c2 и верхнего фитиля c4
        # + растяжка верха до c1.low.
        # bottom = max(c2.low, c4_body_high) — нижняя граница пересечения.
        zone_bottom = max(c2l, c4_body_high)
        if zone_bottom >= c1l:
            return None
        return RDRB4Zone(
            direction="SHORT",
            bottom=zone_bottom, top=c1l,
            c1_time=df.index[idx - 3], c4_time=df.index[idx],
            c1_high=c1h, c1_low=c1l, c2_high=c2h, c2_low=c2l,
            c4_body_high=c4_body_high, c4_body_low=c4_body_low,
        )
    # LONG (mirror)
    if (c1h < c2h) and (c1h > c2c) and (c2h > c4l) and (c3c > c2h) and (c1h < c4l):
        # zone = [c1.high, min(c2.high, c4_body_low)]
        zone_top = min(c2h, c4_body_low)
        if zone_top <= c1h:
            return None
        return RDRB4Zone(
            direction="LONG",
            bottom=c1h, top=zone_top,
            c1_time=df.index[idx - 3], c4_time=df.index[idx],
            c1_high=c1h, c1_low=c1l, c2_high=c2h, c2_low=c2l,
            c4_body_high=c4_body_high, c4_body_low=c4_body_low,
        )
    return None


def collect_valid_top_obs(df_top: pd.DataFrame) -> list[OBZone]:
    """Все OB на top-ТФ, оба направления."""
    if df_top is None or df_top.empty or len(df_top) < 2:
        return []
    obs: list[OBZone] = []
    for j in range(1, len(df_top)):
        ob = detect_ob_pair(df_top, j)
        if ob is not None:
            obs.append(ob)
    return obs


def find_first_macro_fvg_for_top_ob(
    df_macro: pd.DataFrame,
    ob_top: OBZone,
    top_tf_hours: int,
) -> FVGZone | None:
    """Первый валидный FVG-macro после закрытия cur top-OB.

    search_start = ob_top.cur_time + top_tf_hours

    Validity:
      - direction == ob_top.direction
      - zones_overlap(fvg_macro, ob_top)
    """
    search_start = ob_top.cur_time + pd.Timedelta(hours=top_tf_hours)
    df_window = df_macro[df_macro.index >= search_start]
    if len(df_window) < 3:
        return None

    for k in range(2, len(df_window)):
        f = detect_fvg(df_window, k)
        if f is None or f.direction != ob_top.direction:
            continue
        if not zones_overlap(f.bottom, f.top, ob_top.bottom, ob_top.top):
            continue
        return f
    return None


def find_first_rdrb4_in_zone(
    df_htf: pd.DataFrame,
    fvg_macro: FVGZone,
    macro_tf_hours: int,
) -> RDRB4Zone | None:
    """Первый RDRB-4 после закрытия c2 FVG-macro, зона overlap с FVG-macro.

    search_start (c1_time) = fvg_macro.c2_time + macro_tf_hours
    (структура RDRB начинается ПОСЛЕ закрытия c2 FVG-macro — анти-lookahead,
     аналог strategy-1-1-6-look-ahead-macro-htf).

    Validity:
      - direction == fvg_macro.direction
      - zones_overlap(rdrb_zone, fvg_macro_zone)
    """
    search_start = fvg_macro.c2_time + pd.Timedelta(hours=macro_tf_hours)
    df_window = df_htf[df_htf.index >= search_start]
    if len(df_window) < 4:
        return None

    direction = fvg_macro.direction
    for k in range(3, len(df_window)):
        r = detect_rdrb4(df_window, k)
        if r is None or r.direction != direction:
            continue
        if not zones_overlap(r.bottom, r.top, fvg_macro.bottom, fvg_macro.top):
            continue
        return r
    return None


def detect_strategy_1_1_5_signals(
    df_1d: pd.DataFrame,
    df_12h: pd.DataFrame,
    df_4h: pd.DataFrame,
    df_6h: pd.DataFrame,
    df_1h: pd.DataFrame,
    df_2h: pd.DataFrame,
    verbose: bool = False,
) -> list[dict]:
    """Сканирует OB-1d И OB-12h как параллельные top.

    Под каждым top-OB ищем первый macro-FVG (4h ИЛИ 6h, earliest-wins по
    c2_close). Под (top, macro) — первый RDRB-4 (1h ИЛИ 2h, earliest по
    c4_close). Все 4 (macro_tf, htf_tf) комбинации валидны.
    """
    signals: list[dict] = []
    counters: dict[str, int] = {
        "ob_top_1d": 0, "ob_top_12h": 0,
        "macro_fvg_4h": 0, "macro_fvg_6h": 0,
        "chosen_top_1d": 0, "chosen_top_12h": 0,
        "chosen_macro_4h": 0, "chosen_macro_6h": 0,
        "chosen_htf_1h": 0, "chosen_htf_2h": 0,
    }

    def _scan_top(df_top: pd.DataFrame, top_tf_hours: int, top_label: str) -> None:
        if df_top is None or df_top.empty:
            return
        top_obs = collect_valid_top_obs(df_top)
        counters[f"ob_top_{top_label}"] += len(top_obs)

        for ob_top in top_obs:
            macro_4h = find_first_macro_fvg_for_top_ob(df_4h, ob_top, top_tf_hours)
            macro_6h = find_first_macro_fvg_for_top_ob(df_6h, ob_top, top_tf_hours)
            if macro_4h is None and macro_6h is None:
                continue
            if macro_4h is not None:
                counters["macro_fvg_4h"] += 1
            if macro_6h is not None:
                counters["macro_fvg_6h"] += 1

            # earliest по c2_close (c2_time + tf_hours).
            if macro_4h is None:
                fvg_macro, macro_tf, macro_hours = macro_6h, "6h", 6
            elif macro_6h is None:
                fvg_macro, macro_tf, macro_hours = macro_4h, "4h", 4
            else:
                close_4h = macro_4h.c2_time + pd.Timedelta(hours=4)
                close_6h = macro_6h.c2_time + pd.Timedelta(hours=6)
                if close_4h <= close_6h:
                    fvg_macro, macro_tf, macro_hours = macro_4h, "4h", 4
                else:
                    fvg_macro, macro_tf, macro_hours = macro_6h, "6h", 6

            # htf RDRB-4: 1h и 2h независимо, earliest по c4_close.
            rdrb_1h = find_first_rdrb4_in_zone(df_1h, fvg_macro, macro_hours)
            rdrb_2h = find_first_rdrb4_in_zone(df_2h, fvg_macro, macro_hours)
            if rdrb_1h is None and rdrb_2h is None:
                continue

            if rdrb_1h is None:
                rdrb, htf_tf, htf_hours = rdrb_2h, "2h", 2
            elif rdrb_2h is None:
                rdrb, htf_tf, htf_hours = rdrb_1h, "1h", 1
            else:
                close_1h = rdrb_1h.c4_time + pd.Timedelta(hours=1)
                close_2h = rdrb_2h.c4_time + pd.Timedelta(hours=2)
                if close_1h <= close_2h:
                    rdrb, htf_tf, htf_hours = rdrb_1h, "1h", 1
                else:
                    rdrb, htf_tf, htf_hours = rdrb_2h, "2h", 2

            counters[f"chosen_top_{top_label}"] += 1
            counters[f"chosen_macro_{macro_tf}"] += 1
            counters[f"chosen_htf_{htf_tf}"] += 1

            # Entry / SL / TP по спеке пользователя.
            if rdrb.direction == "LONG":
                entry = rdrb.top  # = c4.low (верх зоны для LONG)
                sl = max(rdrb.c1_high, rdrb.c2_high)
                risk = sl - entry  # SL выше entry для LONG? Нет — наоборот.
                # Для LONG: вход на верху зоны, SL ВЫШЕ него (max c1.high, c2.high
                # выше всей RDRB-структуры). Это инвертирует логику. Пересмотр:
                # SL для LONG должен быть ПОД зоной, иначе risk отрицательный.
                # Спека пользователя: "SL за max(c1.high, c2.high) для SHORT, для LONG
                # max(c1.high,c2.high)". Перечитываю — он сказал:
                # "стоп лос за мин(с1.hight, c2.hight) для шорта" — это опечатка,
                # SHORT SL за max(c1.high,c2.high), LONG SL за min(c1.low,c2.low).
                # См. разъяснение ниже.
            # Корректная интерпретация (геометрически осмысленная):
            #   SHORT: SL = max(c1.high, c2.high) — выше зоны, выше входа
            #   LONG:  SL = min(c1.low, c2.low)   — ниже зоны, ниже входа
            # Entry — ближний край расширенной зоны (первое касание):
            #   SHORT: entry = bottom = max(c2.low, c4_body_high)  (цена приходит снизу)
            #   LONG:  entry = top    = min(c2.high, c4_body_low)  (цена приходит сверху)
            if rdrb.direction == "LONG":
                entry = rdrb.top
                sl = min(rdrb.c1_low, rdrb.c2_low)
                risk = entry - sl
                tp = entry + risk * RR
            else:
                entry = rdrb.bottom
                sl = max(rdrb.c1_high, rdrb.c2_high)
                risk = sl - entry
                tp = entry - risk * RR

            if risk <= 0:
                continue

            signals.append({
                "direction": rdrb.direction,
                "signal_time": rdrb.c4_time,
                "entry": float(entry),
                "sl": float(sl),
                "tp": float(tp),
                "risk": float(risk),
                "top_tf": top_label, "top_tf_hours": top_tf_hours,
                "ob_top_prev_time": ob_top.prev_time,
                "ob_top_cur_time": ob_top.cur_time,
                "ob_top_zone": (ob_top.bottom, ob_top.top),
                "macro_tf": macro_tf,
                "fvg_macro_c0_time": fvg_macro.c0_time,
                "fvg_macro_c2_time": fvg_macro.c2_time,
                "fvg_macro_zone": (fvg_macro.bottom, fvg_macro.top),
                "htf_tf": htf_tf,
                "rdrb_c1_time": rdrb.c1_time,
                "rdrb_c4_time": rdrb.c4_time,
                "rdrb_zone": (rdrb.bottom, rdrb.top),
            })

    _scan_top(df_1d, 24, "1d")
    _scan_top(df_12h, 12, "12h")

    if verbose:
        print(f"[FUNNEL 1.1.5] OB-top 1d: {counters['ob_top_1d']}  12h: {counters['ob_top_12h']}")
        print(f"  macro-FVG 4h: {counters['macro_fvg_4h']}  6h: {counters['macro_fvg_6h']}")
        print(f"  signals (raw): {len(signals)}")
        print(f"    top  1d/12h: {counters['chosen_top_1d']}/{counters['chosen_top_12h']}")
        print(f"    macro 4h/6h: {counters['chosen_macro_4h']}/{counters['chosen_macro_6h']}")
        print(f"    htf 1h/2h:   {counters['chosen_htf_1h']}/{counters['chosen_htf_2h']}")
    return signals
