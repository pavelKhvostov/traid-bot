"""Strategy 1.1.1: OB-D + FVG-4h/6h → OB-1h/2h + FVG-15m/20m в зоне OB-D ∩ FVG-macro.

Универсальные определения зон (canon, см. vault/.../универсальные определения OB и FVG.md):

OB (пара prev, cur):
  LONG OB:   prev медвежья, cur.close > prev.open. Zone = [min(prev.low, cur.low), prev.open]
  SHORT OB:  prev бычья,    cur.close < prev.open. Zone = [prev.open, max(prev.high, cur.high)]

FVG (3-свечной, c0=i-2, c2=i):
  LONG FVG:  high(c0) < low(c2).   Zone = [high(c0), low(c2)]
  SHORT FVG: low(c0) > high(c2).   Zone = [high(c2), low(c0)]

Логика:
  1. OB-D — сканируем дневные пары (LONG или SHORT).
  2. FVG-macro (4h ИЛИ 6h, независимо) — того же направления, c2 в prev_day или
     cur_day OB-D. Если c2 в prev_day, дополнительно: цена не перекрыла FVG по wick
     (low < bottom для LONG / high > top для SHORT) на свечах того же ТФ
     в окне [c2_close, end_of_cur_day].
     Зона FVG должна попадать в OB-D (bottom для LONG / top для SHORT внутри OB-D).
     Каждая валидная FVG-macro = отдельная ситуация (отдельный поиск OB-htf).
  3. Зона поиска OB-htf (1h и 2h независимо): со СЛЕДУЮЩЕГО UTC-дня после cur OB-D.
     Стоп-правило: при формировании фрактала ниже FVG-macro (LONG) /
     выше FVG-macro (SHORT) — OB-htf с `cur ≤ j+2` (внутри фрактала) ещё валидна;
     OB-htf с `cur > j+2` → FVG невалидна, дальше не ищем.
     Фрактал по Bill Williams: i±2 (low(i) строго ниже low соседей для down /
     high(i) строго выше high соседей для up). j+2 = свеча подтверждения.
  4. OB-htf должен пересекаться с FVG-4h И с OB-D.
  5. Entry FVG ищется параллельно для каждого OB-htf:
     - FVG-15m в окне [prev, cur + (htf_minutes - 15)]
     - FVG-20m в окне [prev, cur + (htf_minutes - 20)]
     Для 1h: 15m end +45, 20m end +40.
     Для 2h: 15m end +105, 20m end +100.
  6. На один (OB-D, FVG-4h) — один сигнал: из всех найденных вариантов
     (1h+15m, 1h+20m, 2h+15m, 2h+20m) берём с самым РАННИМ c2_time entry FVG.
  7. Entry = середина выбранной FVG. SL = низ OB-D (LONG) / верх OB-D (SHORT).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class OBZone:
    direction: str
    bottom: float
    top: float
    prev_time: pd.Timestamp
    cur_time: pd.Timestamp


@dataclass
class FVGZone:
    direction: str
    bottom: float
    top: float
    c0_time: pd.Timestamp
    c2_time: pd.Timestamp


def detect_ob_pair(df: pd.DataFrame, idx: int) -> OBZone | None:
    """Если (df.iloc[idx-1], df.iloc[idx]) — OB пара, вернуть OBZone."""
    if idx < 1 or idx >= len(df):
        return None
    prev = df.iloc[idx - 1]
    cur = df.iloc[idx]
    po, pc = float(prev["open"]), float(prev["close"])
    pl, ph = float(prev["low"]), float(prev["high"])
    cl, ch = float(cur["low"]), float(cur["high"])
    cc = float(cur["close"])

    if pc < po and cc > po:
        return OBZone(
            direction="LONG",
            bottom=min(pl, cl),
            top=po,
            prev_time=df.index[idx - 1],
            cur_time=df.index[idx],
        )
    if pc > po and cc < po:
        return OBZone(
            direction="SHORT",
            bottom=po,
            top=max(ph, ch),
            prev_time=df.index[idx - 1],
            cur_time=df.index[idx],
        )
    return None


def detect_fvg(df: pd.DataFrame, idx: int) -> FVGZone | None:
    """Если (df.iloc[idx-2], _, df.iloc[idx]) — FVG, вернуть FVGZone."""
    if idx < 2 or idx >= len(df):
        return None
    c0 = df.iloc[idx - 2]
    c2 = df.iloc[idx]
    h0 = float(c0["high"])
    l0 = float(c0["low"])
    h2 = float(c2["high"])
    l2 = float(c2["low"])

    if h0 < l2:  # LONG FVG
        return FVGZone(
            direction="LONG", bottom=h0, top=l2,
            c0_time=df.index[idx - 2], c2_time=df.index[idx],
        )
    if l0 > h2:  # SHORT FVG
        return FVGZone(
            direction="SHORT", bottom=h2, top=l0,
            c0_time=df.index[idx - 2], c2_time=df.index[idx],
        )
    return None


def zones_overlap(b1: float, t1: float, b2: float, t2: float) -> bool:
    return not (t1 < b2 or t2 < b1)


def find_first_fvg_in_range(
    df_ltf: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    direction: str,
    ob_bottom: float,
    ob_top: float,
) -> FVGZone | None:
    """Первая FVG нужного направления в окне [start, end], пересекающаяся с OB-htf."""
    df_window = df_ltf[(df_ltf.index >= start) & (df_ltf.index <= end)]
    for k in range(2, len(df_window)):
        ff = detect_fvg(df_window, k)
        if ff is None or ff.direction != direction:
            continue
        if not zones_overlap(ff.bottom, ff.top, ob_bottom, ob_top):
            continue
        return ff
    return None


def collect_valid_macro_fvgs(
    df_macro: pd.DataFrame,
    ob_d: OBZone,
    htf_hours: int,
) -> list[FVGZone]:
    """Все валидные FVG нужного направления для OB-D на таймфрейме htf_hours (4 или 6).

    Правила:
      - c2 в [prev_time, cur_time + 1d) OB-D
      - candle полностью закрывается до конца cur_day → c2_open ≤ cur_time + (24-htf_hours)h
      - если c2 в prev_day: проверка wick-инвалидации на свечах того же ТФ
        в окне [c2_close, cur_day_end)
      - Зона FVG попадает в OB-D
    """
    cur_day_end = ob_d.cur_time + pd.Timedelta(days=1)
    fvg_search_start = ob_d.prev_time
    fvg_search_end = ob_d.cur_time + pd.Timedelta(hours=24 - htf_hours)
    df_window = df_macro[
        (df_macro.index >= fvg_search_start) & (df_macro.index <= fvg_search_end)
    ]
    if len(df_window) < 3:
        return []

    valid: list[FVGZone] = []
    for j in range(2, len(df_window)):
        f = detect_fvg(df_window, j)
        if f is None or f.direction != ob_d.direction:
            continue
        if not (ob_d.prev_time <= f.c2_time < cur_day_end):
            continue
        # Invalidation для prev_day FVG (на свечах того же ТФ).
        if f.c2_time < ob_d.cur_time:
            check_start = f.c2_time + pd.Timedelta(hours=htf_hours)
            df_inval = df_macro[
                (df_macro.index >= check_start) & (df_macro.index < cur_day_end)
            ]
            invalidated = False
            for _, row in df_inval.iterrows():
                if ob_d.direction == "LONG" and float(row["low"]) < f.bottom:
                    invalidated = True
                    break
                if ob_d.direction == "SHORT" and float(row["high"]) > f.top:
                    invalidated = True
                    break
            if invalidated:
                continue
        # Зона FVG попадает в OB-D.
        if ob_d.direction == "LONG":
            if not (ob_d.bottom <= f.bottom <= ob_d.top):
                continue
        else:
            if not (ob_d.bottom <= f.top <= ob_d.top):
                continue
        valid.append(f)
    return valid


def find_signal_in_htf(
    df_htf: pd.DataFrame,
    df_15m: pd.DataFrame,
    df_20m: pd.DataFrame,
    ob_d: OBZone,
    fvg_macro: FVGZone,
    search_start: pd.Timestamp,
    htf_minutes: int,
    htf_label: str,
) -> dict | None:
    """Найти первый OB-htf с валидной FVG entry (15m или 20m).

    fvg_macro = FVG-4h или FVG-6h.
    Стоп: при формировании фрактала ниже FVG-macro (LONG) / выше (SHORT) —
    OB-htf с `cur` в индексе ≤ j+2 (внутри фрактала) ещё валидна;
    дальше FVG считается невалидной, поиск прекращается.
    """
    df_window = df_htf[df_htf.index >= search_start]
    n = len(df_window)
    if n < 2:
        return None

    direction = ob_d.direction
    fvg_top = fvg_macro.top
    fvg_bottom = fvg_macro.bottom

    highs = df_window["high"].values
    lows = df_window["low"].values

    fractal_confirm_idx: int | None = None  # j+2 первого фрактала, инвалидирующего FVG

    for i in range(n):
        # 1. Проверка фрактала на j = i-2 (подтверждается когда есть свечи до i).
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
            if direction == "LONG" and is_ll and f_low < fvg_bottom:
                fractal_confirm_idx = i  # = j+2
            elif direction == "SHORT" and is_hh and f_high > fvg_top:
                fractal_confirm_idx = i

        # 2. Дальше окна {j, j+1, j+2} = i > fractal_confirm_idx → FVG невалидна.
        if fractal_confirm_idx is not None and i > fractal_confirm_idx:
            return None

        # 3. Попытка детектить валидную OB-htf на (i-1, i).
        if i >= 1:
            cand = detect_ob_pair(df_window, i)
            if cand is not None and cand.direction == direction \
               and zones_overlap(cand.bottom, cand.top, fvg_bottom, fvg_top) \
               and zones_overlap(cand.bottom, cand.top, ob_d.bottom, ob_d.top):
                # Поиск entry FVG (15m + 20m, ранний выигрывает).
                fvg_15m = find_first_fvg_in_range(
                    df_15m,
                    cand.prev_time,
                    cand.cur_time + pd.Timedelta(minutes=htf_minutes - 15),
                    direction, cand.bottom, cand.top,
                )
                fvg_20m = find_first_fvg_in_range(
                    df_20m,
                    cand.prev_time,
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


def detect_strategy_1_1_1_signals(
    df_1d: pd.DataFrame,
    df_4h: pd.DataFrame,
    df_6h: pd.DataFrame,
    df_1h: pd.DataFrame,
    df_2h: pd.DataFrame,
    df_15m: pd.DataFrame,
    df_20m: pd.DataFrame,
    verbose: bool = False,
) -> list[dict]:
    """Сканирует все OB-D и собирает сигналы по логике Strategy 1.1.1.

    FVG-4h должен полностью сформироваться в time range OB-D
    (= [prev_time, cur_time+1d)). Entry FVG ищется параллельно на 15m и 20m
    в time range OB-1h; если есть оба — берётся первый по времени.
    OB-1h ищется без time-limit — до stop conditions (full fill / 2 свечи выше).
    """
    signals: list[dict] = []
    # Диагностика воронки
    cnt_ob_d = 0
    cnt_macro_4h = 0
    cnt_macro_6h = 0
    cnt_chosen_htf_1h = 0
    cnt_chosen_htf_2h = 0
    cnt_chosen_15m = 0
    cnt_chosen_20m = 0
    cnt_chosen_macro_4h = 0
    cnt_chosen_macro_6h = 0

    for d_idx in range(1, len(df_1d)):
        ob_d = detect_ob_pair(df_1d, d_idx)
        if ob_d is None:
            continue
        cnt_ob_d += 1

        # --- Сбор валидных FVG-macro: 4h и 6h независимо ---
        valid_4h = collect_valid_macro_fvgs(df_4h, ob_d, htf_hours=4)
        valid_6h = collect_valid_macro_fvgs(df_6h, ob_d, htf_hours=6)
        cnt_macro_4h += len(valid_4h)
        cnt_macro_6h += len(valid_6h)

        all_macro = [(f, "4h") for f in valid_4h] + [(f, "6h") for f in valid_6h]
        if not all_macro:
            continue

        # --- Каждая FVG-macro = отдельная ситуация: поиск 1h/2h × 15m/20m ---
        for fvg_macro, macro_tf in all_macro:
            zone_bottom = max(ob_d.bottom, fvg_macro.bottom)
            zone_top = min(ob_d.top, fvg_macro.top)

            # Окно поиска OB-htf: со следующего UTC-дня после cur OB-D.
            search_start = (ob_d.cur_time + pd.Timedelta(days=1)).normalize()

            sig_1h = find_signal_in_htf(
                df_1h, df_15m, df_20m, ob_d, fvg_macro,
                search_start, htf_minutes=60, htf_label="1h",
            )
            sig_2h = find_signal_in_htf(
                df_2h, df_15m, df_20m, ob_d, fvg_macro,
                search_start, htf_minutes=120, htf_label="2h",
            )

            if sig_1h is None and sig_2h is None:
                continue

            if sig_1h is None:
                chosen = sig_2h
            elif sig_2h is None:
                chosen = sig_1h
            else:
                # Берём с более ранним c2_time entry FVG.
                if sig_1h["fvg_entry"].c2_time <= sig_2h["fvg_entry"].c2_time:
                    chosen = sig_1h
                else:
                    chosen = sig_2h

            ob_htf = chosen["ob_htf"]
            fvg_entry = chosen["fvg_entry"]
            htf_label = chosen["htf_label"]
            fvg_tf = chosen["fvg_tf"]

            if htf_label == "1h":
                cnt_chosen_htf_1h += 1
            else:
                cnt_chosen_htf_2h += 1
            if fvg_tf == "15m":
                cnt_chosen_15m += 1
            else:
                cnt_chosen_20m += 1
            if macro_tf == "4h":
                cnt_chosen_macro_4h += 1
            else:
                cnt_chosen_macro_6h += 1

            entry = (fvg_entry.bottom + fvg_entry.top) / 2
            sl = ob_d.bottom if ob_d.direction == "LONG" else ob_d.top
            risk = abs(entry - sl)
            if risk <= 0:
                continue

            signals.append({
                "direction": ob_d.direction,
                "signal_time": fvg_entry.c2_time,
                "entry": float(entry),
                "sl": float(sl),
                "risk": float(risk),
                "ob_d_prev_time": ob_d.prev_time,
                "ob_d_cur_time": ob_d.cur_time,
                "ob_d_zone": (ob_d.bottom, ob_d.top),
                "fvg_macro_tf": macro_tf,
                "fvg_macro_c0_time": fvg_macro.c0_time,
                "fvg_macro_c2_time": fvg_macro.c2_time,
                "fvg_macro_zone": (fvg_macro.bottom, fvg_macro.top),
                "intersection_zone": (zone_bottom, zone_top),
                "ob_htf_tf": htf_label,
                "ob_htf_prev_time": ob_htf.prev_time,
                "ob_htf_cur_time": ob_htf.cur_time,
                "ob_htf_zone": (ob_htf.bottom, ob_htf.top),
                "fvg_tf": fvg_tf,
                "fvg_c0_time": fvg_entry.c0_time,
                "fvg_c2_time": fvg_entry.c2_time,
                "fvg_zone": (fvg_entry.bottom, fvg_entry.top),
            })

    if verbose:
        print(f"[FUNNEL] OB-D: {cnt_ob_d}")
        print(f"  + valid FVG-4h: {cnt_macro_4h}")
        print(f"  + valid FVG-6h: {cnt_macro_6h}")
        print(f"  signals: {len(signals)}")
        print(f"      chosen macro 4h: {cnt_chosen_macro_4h}")
        print(f"      chosen macro 6h: {cnt_chosen_macro_6h}")
        print(f"      chosen htf 1h: {cnt_chosen_htf_1h}")
        print(f"      chosen htf 2h: {cnt_chosen_htf_2h}")
        print(f"      chosen entry 15m: {cnt_chosen_15m}")
        print(f"      chosen entry 20m: {cnt_chosen_20m}")
    return signals
