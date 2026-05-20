"""Strategy RDRB: RDRB-1d/12h → OB-1h/2h + FVG-15m/20m.

Аналог Strategy 1.1.1, но top-уровень вместо «OB-D + FVG-macro» — это RDRB
на 4h или 6h. Логика OB-htf и entry FVG берётся 1-в-1 из 1.1.1.

RDRB определение (3 свечи: anchor=i-2, middle=i-1, trigger=i):

LONG:
  close(i-1) > high(i-2)                      i-1 закрылась выше high якоря (пробой вверх)
  low(i)     < high(i-2)                      i ушла хвостом ПОД high якоря (false retrace)
  close(i)   > max(open(i-2), close(i-2))     i закрылась ВЫШЕ всего тела якоря
  Zone V1 (intersection):
    top    = min(high(i-2), close(i))
    bottom = max(low(i),    close(i-2))
  Zone V2 (+ anchor body ext):
    top    = min(high(i-2), close(i))
    bottom = max(open(i-2), close(i-2))       верх тела якоря

SHORT:
  close(i-1) < low(i-2)
  high(i)    > low(i-2)
  close(i)   < min(open(i-2), close(i-2))     i закрылась НИЖЕ всего тела якоря
  Zone V1 (intersection):
    top    = min(high(i),  close(i-2))
    bottom = max(low(i-2), close(i))
  Zone V2 (+ anchor body ext):
    top    = min(open(i-2), close(i-2))       низ тела якоря
    bottom = max(low(i-2), close(i))

Версии зоны — canon, см. vault/knowledge/smc/что такое rdrb.md.
V1 и V2 зафиксированы как верные (2026-05-19); V3 (MAX) отклонён.

SL = OB_SL_DEPTH (15%) внутрь от ближней к рынку границы RDRB (LONG: bottom вверх,
SHORT: top вниз) — то же правило что в 1.1.1, только зона теперь RDRB.

Entry = mid выбранной FVG-15m/20m. RR=1.0 baseline (есть параллельный RR=2.2).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from strategies.strategy_1_1_1 import (
    FVGZone,
    OB_SL_DEPTH,
    detect_ob_pair,
    find_first_fvg_in_range,
    zones_overlap,
)


@dataclass
class RDRBZone:
    direction: str
    bottom: float
    top: float
    anchor_time: pd.Timestamp   # i-2 open_time
    trigger_time: pd.Timestamp  # i open_time
    tf_hours: int               # 24 или 12 — длина свечи RDRB
    zone_version: str = "V1"    # "V1" intersection | "V2" + anchor body ext


def detect_rdrb(df: pd.DataFrame, idx: int,
                zone_version: str = "V1") -> RDRBZone | None:
    """Если (df.iloc[idx-2], df.iloc[idx-1], df.iloc[idx]) образуют RDRB — вернуть.

    `zone_version` — формула зоны (canon, см. vault/.../что такое rdrb.md):
      "V1" — intersection фитилей anchor+trigger (узкая, точная);
      "V2" — V1 + расширение до тела anchor (баланс).
    Условие формирования паттерна для V1 и V2 идентично — отличается только зона.
    V3 (MAX) отклонён 2026-05-19 — не поддерживается.
    """
    if zone_version not in ("V1", "V2"):
        raise ValueError(
            f"zone_version должен быть 'V1' или 'V2', получено {zone_version!r} "
            f"(V3 отклонён 2026-05-19)"
        )
    if idx < 2 or idx >= len(df):
        return None
    a = df.iloc[idx - 2]
    m = df.iloc[idx - 1]
    c = df.iloc[idx]

    a_high = float(a["high"])
    a_low = float(a["low"])
    a_open = float(a["open"])
    a_close = float(a["close"])
    a_body_top = max(a_open, a_close)     # верх тела якоря
    a_body_bottom = min(a_open, a_close)  # низ тела якоря
    m_close = float(m["close"])
    c_high = float(c["high"])
    c_low = float(c["low"])
    c_close = float(c["close"])

    # LONG
    if (m_close > a_high
            and c_low < a_high
            and c_close > a_body_top):       # close ВЫШЕ всего тела якоря
        top = min(a_high, c_close)
        # V1: низ = пересечение фитилей; V2: низ = верх тела anchor
        bottom = max(c_low, a_close) if zone_version == "V1" else a_body_top
        if top > bottom:
            return RDRBZone(
                direction="LONG", bottom=bottom, top=top,
                anchor_time=df.index[idx - 2],
                trigger_time=df.index[idx],
                tf_hours=0,  # caller проставит
                zone_version=zone_version,
            )

    # SHORT
    if (m_close < a_low
            and c_high > a_low
            and c_close < a_body_bottom):    # close НИЖЕ всего тела якоря
        bottom = max(a_low, c_close)
        # V1: верх = пересечение фитилей; V2: верх = низ тела anchor
        top = min(c_high, a_close) if zone_version == "V1" else a_body_bottom
        if top > bottom:
            return RDRBZone(
                direction="SHORT", bottom=bottom, top=top,
                anchor_time=df.index[idx - 2],
                trigger_time=df.index[idx],
                tf_hours=0,
                zone_version=zone_version,
            )

    return None


def _find_rdrb_invalidation_time(
    df_1h: pd.DataFrame, rdrb: RDRBZone, search_start: pd.Timestamp,
) -> pd.Timestamp | None:
    """Первый момент, когда 1h close закрепилась ЗА зоной RDRB:
      LONG  invalidation: 1h close < rdrb.bottom (зона пробита вниз)
      SHORT invalidation: 1h close > rdrb.top    (зона пробита вверх)
    Возвращает время CLOSE первой такой 1h-свечи (= её open + 1h)
    или None если такая свеча не появилась в окне.
    """
    df_after = df_1h[df_1h.index >= search_start]
    if df_after.empty:
        return None
    closes = df_after["close"].values
    times = df_after.index
    for k in range(len(closes)):
        cl = float(closes[k])
        if rdrb.direction == "LONG" and cl < rdrb.bottom:
            return times[k] + pd.Timedelta(hours=1)
        if rdrb.direction == "SHORT" and cl > rdrb.top:
            return times[k] + pd.Timedelta(hours=1)
    return None


def find_signal_in_htf_for_rdrb(
    df_htf: pd.DataFrame,
    df_15m: pd.DataFrame,
    df_20m: pd.DataFrame,
    df_1h: pd.DataFrame,
    rdrb: RDRBZone,
    search_start: pd.Timestamp,
    htf_minutes: int,
    htf_label: str,
) -> dict | None:
    """Аналог find_signal_in_htf из 1.1.1 для RDRB-стратегии.

    Стопы для зоны:
    1. **1h close beyond zone**: LONG если 1h close < rdrb.bottom,
       SHORT если 1h close > rdrb.top (зона пробита). После этого момента
       OB-htf не считается. Проверяется ВСЕГДА на 1h-таймфрейме (df_1h),
       независимо от того что ищем — OB-1h или OB-2h.
    2. **Fractal на htf** (как в 1.1.1): LL/HH ниже/выше RDRB зоны.
       OB-htf с cur ≤ j+2 ещё валиден.
    """
    df_window = df_htf[df_htf.index >= search_start]
    n = len(df_window)
    if n < 2:
        return None

    direction = rdrb.direction
    rdrb_top = rdrb.top
    rdrb_bottom = rdrb.bottom

    # Pre-compute: время первой 1h-свечи закрытой ЗА зоной (LONG: выше top,
    # SHORT: ниже bottom). После этого момента RDRB невалидна.
    invalidation_time = _find_rdrb_invalidation_time(df_1h, rdrb, search_start)

    highs = df_window["high"].values
    lows = df_window["low"].values

    fractal_confirm_idx: int | None = None

    for i in range(n):
        # 0. RDRB invalidated 1h close'ом — OB-htf должна закрыться до этого.
        cur_time = df_window.index[i]
        cur_close_time = cur_time + pd.Timedelta(minutes=htf_minutes)
        if invalidation_time is not None and cur_close_time > invalidation_time:
            return None

        # 1. Фрактал на j = i-2.
        if i >= 4 and fractal_confirm_idx is None:
            j = i - 2
            f_low = float(lows[j])
            f_high = float(highs[j])
            is_ll = (
                f_low < float(lows[j - 2]) and f_low < float(lows[j - 1])
                and f_low < float(lows[j + 1]) and f_low < float(lows[j + 2])
            )
            is_hh = (
                f_high > float(highs[j - 2]) and f_high > float(highs[j - 1])
                and f_high > float(highs[j + 1]) and f_high > float(highs[j + 2])
            )
            if direction == "LONG" and is_ll and f_low < rdrb_bottom:
                fractal_confirm_idx = i
            elif direction == "SHORT" and is_hh and f_high > rdrb_top:
                fractal_confirm_idx = i

        # 2. После окна {j, j+1, j+2} — RDRB невалидна.
        if fractal_confirm_idx is not None and i > fractal_confirm_idx:
            return None

        # 3. Детект OB-htf на (i-1, i).
        if i >= 1:
            cand = detect_ob_pair(df_window, i)
            if (cand is not None and cand.direction == direction
                    and zones_overlap(cand.bottom, cand.top, rdrb_bottom, rdrb_top)):
                fvg_15m = find_first_fvg_in_range(
                    df_15m, cand.prev_time,
                    cand.cur_time + pd.Timedelta(minutes=htf_minutes - 15),
                    direction, cand.bottom, cand.top,
                )
                fvg_20m = find_first_fvg_in_range(
                    df_20m, cand.prev_time,
                    cand.cur_time + pd.Timedelta(minutes=htf_minutes - 20),
                    direction, cand.bottom, cand.top,
                )
                if fvg_15m is not None or fvg_20m is not None:
                    if fvg_15m is None:
                        fvg_entry, fvg_tf = fvg_20m, "20m"
                    elif fvg_20m is None:
                        fvg_entry, fvg_tf = fvg_15m, "15m"
                    else:
                        if fvg_15m.c2_time <= fvg_20m.c2_time:
                            fvg_entry, fvg_tf = fvg_15m, "15m"
                        else:
                            fvg_entry, fvg_tf = fvg_20m, "20m"
                    return {
                        "ob_htf": cand,
                        "htf_label": htf_label,
                        "fvg_entry": fvg_entry,
                        "fvg_tf": fvg_tf,
                    }

    return None


def detect_strategy_rdrb_signals(
    df_1d: pd.DataFrame,
    df_12h: pd.DataFrame,
    df_1h: pd.DataFrame,
    df_2h: pd.DataFrame,
    df_15m: pd.DataFrame,
    df_20m: pd.DataFrame,
    verbose: bool = False,
    zone_version: str = "V1",
) -> list[dict]:
    """Сканер RDRB на 1d и 12h параллельно. На каждой RDRB → поиск 1h/2h × 15m/20m.

    `zone_version` — версия зоны RDRB ("V1" или "V2", см. detect_rdrb).
    """
    signals: list[dict] = []
    counters = {
        "rdrb_1d": 0, "rdrb_12h": 0,
        "chosen_top_1d": 0, "chosen_top_12h": 0,
        "chosen_htf_1h": 0, "chosen_htf_2h": 0,
        "chosen_15m": 0, "chosen_20m": 0,
    }

    def _scan_rdrb(df_top: pd.DataFrame, top_tf_hours: int, top_label: str) -> None:
        if df_top is None or df_top.empty:
            return
        for idx in range(2, len(df_top)):
            rdrb = detect_rdrb(df_top, idx, zone_version)
            if rdrb is None:
                continue
            rdrb.tf_hours = top_tf_hours
            counters[f"rdrb_{top_label}"] += 1

            # Окно поиска OB-htf — со следующего bar после triggera RDRB.
            search_start = rdrb.trigger_time + pd.Timedelta(hours=top_tf_hours)

            sig_1h = find_signal_in_htf_for_rdrb(
                df_1h, df_15m, df_20m, df_1h, rdrb, search_start, 60, "1h",
            )
            sig_2h = find_signal_in_htf_for_rdrb(
                df_2h, df_15m, df_20m, df_1h, rdrb, search_start, 120, "2h",
            )

            if sig_1h is None and sig_2h is None:
                continue

            if sig_1h is None:
                chosen = sig_2h
            elif sig_2h is None:
                chosen = sig_1h
            else:
                if sig_1h["fvg_entry"].c2_time <= sig_2h["fvg_entry"].c2_time:
                    chosen = sig_1h
                else:
                    chosen = sig_2h

            ob_htf = chosen["ob_htf"]
            fvg_entry = chosen["fvg_entry"]
            htf_label = chosen["htf_label"]
            fvg_tf = chosen["fvg_tf"]

            counters[f"chosen_top_{top_label}"] += 1
            counters[f"chosen_htf_{htf_label}"] += 1
            counters[f"chosen_{fvg_tf}"] += 1

            entry = (fvg_entry.bottom + fvg_entry.top) / 2
            # SL внутри RDRB zone на OB_SL_DEPTH от ближней к рынку границы.
            depth = rdrb.top - rdrb.bottom
            if rdrb.direction == "LONG":
                sl = rdrb.bottom + depth * OB_SL_DEPTH
            else:
                sl = rdrb.top - depth * OB_SL_DEPTH
            risk = abs(entry - sl)
            if risk <= 0:
                continue

            signals.append({
                "direction": rdrb.direction,
                "signal_time": fvg_entry.c2_time,
                "entry": float(entry),
                "sl": float(sl),
                "risk": float(risk),
                "rdrb_tf": top_label,             # "4h" или "6h"
                "rdrb_anchor_time": rdrb.anchor_time,
                "rdrb_trigger_time": rdrb.trigger_time,
                "rdrb_zone": (rdrb.bottom, rdrb.top),
                "rdrb_zone_version": rdrb.zone_version,
                "ob_htf_tf": htf_label,
                "ob_htf_prev_time": ob_htf.prev_time,
                "ob_htf_cur_time": ob_htf.cur_time,
                "ob_htf_zone": (ob_htf.bottom, ob_htf.top),
                "fvg_tf": fvg_tf,
                "fvg_c0_time": fvg_entry.c0_time,
                "fvg_c2_time": fvg_entry.c2_time,
                "fvg_zone": (fvg_entry.bottom, fvg_entry.top),
            })

    _scan_rdrb(df_1d, 24, "1d")
    _scan_rdrb(df_12h, 12, "12h")

    if verbose:
        print(f"[FUNNEL] RDRB 1d: {counters['rdrb_1d']}  12h: {counters['rdrb_12h']}")
        print(f"  signals (raw): {len(signals)}")
        print(f"      chosen rdrb 1d: {counters['chosen_top_1d']}")
        print(f"      chosen rdrb 12h: {counters['chosen_top_12h']}")
        print(f"      chosen htf 1h: {counters['chosen_htf_1h']}")
        print(f"      chosen htf 2h: {counters['chosen_htf_2h']}")
        print(f"      chosen entry 15m: {counters['chosen_15m']}")
        print(f"      chosen entry 20m: {counters['chosen_20m']}")
    return signals
