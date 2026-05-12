"""Strategy 1.1.7: Fractal-4h sweep + закреп 1h + OB-{1h,2h} + FVG-{15m,20m}.

Каскад (LONG, для SHORT зеркально):

  4h фрактал LL (Bill Williams i±2, валиден после i+2 close)
    └── свеча-снятие 4h (sweep):
          - low < FL.low (вынесла фрактал)
          - close > FL.low (закрылась выше = ловушка)
          - первая такая после i+2
          └── POI = [sweep.low, min(sweep.open, sweep.close)]
                └── В окне [sweep.close, sweep.close + 8h]:
                      1. sweep сам стал фракталом (за 8h нет low < sweep.low)
                      2. 1h закреп: ≥ 1 свеча с close > POI.top (LONG) / close < POI.bottom (SHORT)
                      3. ПОСЛЕ закрепа: OB-1h или OB-2h, zones_overlap с POI
                      4. внутри OB зоны: FVG-15m или 20m после OB.cur_close
                            entry = (fvg.bottom + fvg.top) / 2
                            SL    = OB.bottom (LONG) / OB.top (SHORT)
                            TP    = entry ± risk * RR
                            RR    = 1.0

Lookahead-prevention:
  - FL валиден на (FL.i + 2).close_time
  - sweep search_start = (FL.i + 2).close_time
  - 8h окно = [sweep.close, sweep.close + 8h]
  - "sweep стал фракталом" проверяется на тех же 2 свечах окна (i+1, i+2 относительно sweep)
  - закреп ищется на 1h в окне 8h
  - OB search_start = (confirm_1h_bar).close_time
  - FVG search_start = ob.cur_close

Все 4 (ob_tf, fvg_tf) комбинации earliest-wins по close-time.
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
class Fractal4h:
    direction: str  # "LONG" (LL) / "SHORT" (HH)
    price: float    # FL.low или FH.high
    i: int          # индекс в df_4h
    time: pd.Timestamp


@dataclass
class SweepCandle:
    direction: str
    fractal: Fractal4h
    sweep_time: pd.Timestamp   # open_time
    sweep_close_time: pd.Timestamp
    sweep_open: float
    sweep_high: float
    sweep_low: float
    sweep_close: float
    poi_bottom: float
    poi_top: float


def detect_4h_fractals(df_4h: pd.DataFrame) -> list[Fractal4h]:
    """LL и HH фракталы i±2 (Bill Williams). Strict <,> (как в strategies/fractal.py)."""
    if df_4h is None or len(df_4h) < 5:
        return []
    out: list[Fractal4h] = []
    lows = df_4h["low"].astype(float).values
    highs = df_4h["high"].astype(float).values
    for i in range(2, len(df_4h) - 2):
        lo, hi = lows[i], highs[i]
        is_ll = all(lo < lows[k] for k in (i - 2, i - 1, i + 1, i + 2))
        is_hh = all(hi > highs[k] for k in (i - 2, i - 1, i + 1, i + 2))
        if is_ll:
            out.append(Fractal4h("LONG", float(lo), i, df_4h.index[i]))
        if is_hh:
            out.append(Fractal4h("SHORT", float(hi), i, df_4h.index[i]))
    return out


def find_sweep_candle(
    df_4h: pd.DataFrame, fractal: Fractal4h,
) -> SweepCandle | None:
    """Первая свеча после (fractal.i + 2) удовлетворяющая sweep + закрылась за фракталом.

    LL фрактал → ищем свечу с low < FL AND close > FL.
    HH фрактал → ищем свечу с high > FH AND close < FH.
    """
    n = len(df_4h)
    for j in range(fractal.i + 3, n):
        row = df_4h.iloc[j]
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        if fractal.direction == "LONG":
            if l >= fractal.price:
                continue
            if c <= fractal.price:
                # первая касающаяся закрылась за фракталом — sweep пропущен
                return None
            poi_bottom = l
            poi_top = min(o, c)
        else:
            if h <= fractal.price:
                continue
            if c >= fractal.price:
                return None
            poi_bottom = max(o, c)
            poi_top = h

        sweep_time = df_4h.index[j]
        sweep_close = sweep_time + pd.Timedelta(hours=4)
        return SweepCandle(
            direction=fractal.direction,
            fractal=fractal,
            sweep_time=sweep_time,
            sweep_close_time=sweep_close,
            sweep_open=o, sweep_high=h, sweep_low=l, sweep_close=c,
            poi_bottom=poi_bottom, poi_top=poi_top,
        )
    return None


def sweep_became_fractal(
    df_4h: pd.DataFrame, sweep: SweepCandle,
) -> bool:
    """За 8h после sweep.close (= 2 свечи 4h) sweep не должна быть пробита.

    LONG: ни одна свеча в окне [sweep.close, sweep.close+8h] не имеет low < sweep.low.
    SHORT: ни одна свеча не имеет high > sweep.high.
    """
    end = sweep.sweep_close_time + pd.Timedelta(hours=8)
    window = df_4h[
        (df_4h.index >= sweep.sweep_close_time) & (df_4h.index < end)
    ]
    if window.empty:
        return False
    if sweep.direction == "LONG":
        return bool((window["low"].astype(float) >= sweep.sweep_low).all())
    else:
        return bool((window["high"].astype(float) <= sweep.sweep_high).all())


def find_confirmation_and_invalidation(
    df_1h: pd.DataFrame, sweep: SweepCandle, start: pd.Timestamp,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    """Идём по 1h после start, ищем первое из двух событий:

    LONG:
      - confirmation = первая 1h свеча с close > POI.top
        (цена ушла наверх = подтверждение реверса)
      - invalidation = первая 1h свеча с close < POI.bottom
        (цена пробила POI вниз = реверс провален)

    SHORT — зеркально.

    Возвращает (confirmation_close_time, invalidation_close_time):
      - если первой случилась invalidation, confirmation = None (цепочка мертва)
      - иначе confirmation = время закрытия первой подтверждающей свечи;
        invalidation = first invalidation ПОСЛЕ confirmation (или None)
    """
    window = df_1h[df_1h.index >= start]
    confirmation: pd.Timestamp | None = None
    invalidation: pd.Timestamp | None = None

    for ts, row in window.iterrows():
        c = float(row["close"])
        close_time = ts + pd.Timedelta(hours=1)
        if sweep.direction == "LONG":
            if confirmation is None:
                if c < sweep.poi_bottom:
                    return None, close_time  # инвалидация раньше закрепа
                if c > sweep.poi_top:
                    confirmation = close_time
            else:
                if c < sweep.poi_bottom:
                    invalidation = close_time
                    break
        else:
            if confirmation is None:
                if c > sweep.poi_top:
                    return None, close_time
                if c < sweep.poi_bottom:
                    confirmation = close_time
            else:
                if c > sweep.poi_top:
                    invalidation = close_time
                    break

    return confirmation, invalidation


def find_ob_in_poi_after_confirmation(
    df_ob: pd.DataFrame, sweep: SweepCandle,
    confirmation_close: pd.Timestamp, invalidation_close: pd.Timestamp | None,
) -> OBZone | None:
    """Первый OB того же направления + overlap с POI, в окне (confirmation, invalidation).

    OB ищется ПОСЛЕ закрепа (= возврат цены в POI). Если invalidation
    задана — OB должен образоваться ДО неё.
    """
    window = df_ob[df_ob.index >= confirmation_close]
    if invalidation_close is not None:
        window = window[window.index < invalidation_close]
    for j in range(1, len(window)):
        ob = detect_ob_pair(window, j)
        if ob is None or ob.direction != sweep.direction:
            continue
        if not zones_overlap(ob.bottom, ob.top, sweep.poi_bottom, sweep.poi_top):
            continue
        return ob
    return None


def find_first_fvg_in_ob(
    df_fvg: pd.DataFrame, ob: OBZone, ob_tf_hours: float,
) -> FVGZone | None:
    """Первый FVG после ob.cur_close с overlap с OB зоной, без верхней границы.

    Иерархия first-wins для всей цепочки 1.1.7: один фрактал → первый sweep
    → первый закреп → первый OB → первый FVG. Если FVG не образуется —
    цепочка не реализована, отдельных таймаутов на FVG не накладываем.
    """
    search_start = ob.cur_time + pd.Timedelta(hours=ob_tf_hours)
    window = df_fvg[df_fvg.index >= search_start]
    for k in range(2, len(window)):
        f = detect_fvg(window, k)
        if f is None or f.direction != ob.direction:
            continue
        if not zones_overlap(f.bottom, f.top, ob.bottom, ob.top):
            continue
        return f
    return None


def detect_strategy_1_1_7_signals(
    df_4h: pd.DataFrame,
    df_1h: pd.DataFrame,
    df_2h: pd.DataFrame,
    df_15m: pd.DataFrame,
    df_20m: pd.DataFrame,
    verbose: bool = False,
) -> list[dict]:
    """Сканер 1.1.7 — fractal sweep + 1h anchor + OB-{1h,2h} + FVG-{15m,20m}."""
    signals: list[dict] = []
    counters: dict[str, int] = {
        "fractals_4h": 0, "sweeps": 0, "stayed_fractal": 0,
        "poi_eaten": 0, "confirmed": 0,
        "ob_1h": 0, "ob_2h": 0,
        "chosen_ob_1h": 0, "chosen_ob_2h": 0,
        "chosen_fvg_15m": 0, "chosen_fvg_20m": 0,
    }

    fractals = detect_4h_fractals(df_4h)
    counters["fractals_4h"] = len(fractals)

    for fractal in fractals:
        sweep = find_sweep_candle(df_4h, fractal)
        if sweep is None:
            continue
        counters["sweeps"] += 1

        if not sweep_became_fractal(df_4h, sweep):
            continue
        counters["stayed_fractal"] += 1

        # После 8h окна на 1h ждём:
        #   confirmation (закреп) — LONG: close > POI.top, SHORT: close < POI.bottom
        #   invalidation         — LONG: close < POI.bottom, SHORT: close > POI.top
        # Если первой случилась invalidation — цепочка мертва.
        # После confirmation ждём возврат цены в POI → ищем OB-1h/2h внутри POI,
        # с верхней границей по invalidation (если случится).
        ob_search_start = sweep.sweep_close_time + pd.Timedelta(hours=8)
        confirmation_close, invalidation_close = find_confirmation_and_invalidation(
            df_1h, sweep, ob_search_start,
        )
        if confirmation_close is None:
            counters["poi_eaten"] += 1
            continue
        counters["confirmed"] = counters.get("confirmed", 0) + 1

        ob_1h = find_ob_in_poi_after_confirmation(
            df_1h, sweep, confirmation_close, invalidation_close,
        )
        ob_2h = find_ob_in_poi_after_confirmation(
            df_2h, sweep, confirmation_close, invalidation_close,
        )
        if ob_1h is None and ob_2h is None:
            continue
        if ob_1h is not None:
            counters["ob_1h"] += 1
        if ob_2h is not None:
            counters["ob_2h"] += 1

        # earliest-wins по ob.cur_close.
        if ob_1h is None:
            ob, ob_tf, ob_hours = ob_2h, "2h", 2.0
        elif ob_2h is None:
            ob, ob_tf, ob_hours = ob_1h, "1h", 1.0
        else:
            close_1h = ob_1h.cur_time + pd.Timedelta(hours=1)
            close_2h = ob_2h.cur_time + pd.Timedelta(hours=2)
            if close_1h <= close_2h:
                ob, ob_tf, ob_hours = ob_1h, "1h", 1.0
            else:
                ob, ob_tf, ob_hours = ob_2h, "2h", 2.0
        counters[f"chosen_ob_{ob_tf}"] += 1

        fvg_15 = find_first_fvg_in_ob(df_15m, ob, ob_hours)
        fvg_20 = find_first_fvg_in_ob(df_20m, ob, ob_hours)
        if fvg_15 is None and fvg_20 is None:
            continue
        if fvg_15 is None:
            fvg, fvg_tf, fvg_minutes = fvg_20, "20m", 20
        elif fvg_20 is None:
            fvg, fvg_tf, fvg_minutes = fvg_15, "15m", 15
        else:
            close_15 = fvg_15.c2_time + pd.Timedelta(minutes=15)
            close_20 = fvg_20.c2_time + pd.Timedelta(minutes=20)
            if close_15 <= close_20:
                fvg, fvg_tf, fvg_minutes = fvg_15, "15m", 15
            else:
                fvg, fvg_tf, fvg_minutes = fvg_20, "20m", 20
        counters[f"chosen_fvg_{fvg_tf}"] += 1

        entry = (fvg.bottom + fvg.top) / 2
        if sweep.direction == "LONG":
            sl = ob.bottom
            risk = entry - sl
            tp = entry + risk * RR
        else:
            sl = ob.top
            risk = sl - entry
            tp = entry - risk * RR
        if risk <= 0:
            continue

        signals.append({
            "direction": sweep.direction,
            "signal_time": fvg.c2_time,
            "entry": float(entry),
            "sl": float(sl),
            "tp": float(tp),
            "risk": float(risk),
            "fractal_time": fractal.time,
            "fractal_price": fractal.price,
            "sweep_time": sweep.sweep_time,
            "sweep_close_time": sweep.sweep_close_time,
            "poi_zone": (sweep.poi_bottom, sweep.poi_top),
            "confirmation_close": confirmation_close,
            "invalidation_time": invalidation_close,
            "ob_tf": ob_tf,
            "ob_prev_time": ob.prev_time,
            "ob_cur_time": ob.cur_time,
            "ob_zone": (ob.bottom, ob.top),
            "fvg_tf": fvg_tf,
            "fvg_c0_time": fvg.c0_time,
            "fvg_c2_time": fvg.c2_time,
            "fvg_zone": (fvg.bottom, fvg.top),
        })

    if verbose:
        print(f"[FUNNEL 1.1.7] fractals_4h={counters['fractals_4h']}")
        print(f"  sweeps={counters['sweeps']}  stayed_fractal={counters['stayed_fractal']}")
        print(f"  poi_eaten_before_confirmation={counters['poi_eaten']}  "
              f"confirmed={counters['confirmed']}")
        print(f"  ob_1h={counters['ob_1h']}  ob_2h={counters['ob_2h']}")
        print(f"  chosen ob_1h/2h: {counters['chosen_ob_1h']}/{counters['chosen_ob_2h']}")
        print(f"  chosen fvg 15m/20m: {counters['chosen_fvg_15m']}/{counters['chosen_fvg_20m']}")
        print(f"  signals (raw): {len(signals)}")
    return signals
