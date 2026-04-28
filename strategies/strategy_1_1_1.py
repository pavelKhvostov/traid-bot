"""Strategy 1.1.1: OB-D + FVG-4h → OB-1h/2h + FVG-15m/20m в зоне OB-D ∩ FVG-4h.

Универсальные определения зон (canon, см. vault/.../универсальные определения OB и FVG.md):

OB (пара prev, cur):
  LONG OB:   prev медвежья, cur.close > prev.open. Zone = [min(prev.low, cur.low), prev.open]
  SHORT OB:  prev бычья,    cur.close < prev.open. Zone = [prev.open, max(prev.high, cur.high)]

FVG (3-свечной, c0=i-2, c2=i):
  LONG FVG:  high(c0) < low(c2).   Zone = [high(c0), low(c2)]
  SHORT FVG: low(c0) > high(c2).   Zone = [high(c2), low(c0)]

Логика:
  1. OB-D — сканируем дневные пары (LONG или SHORT).
  2. FVG-4h — того же направления, c2 в prev_day или cur_day OB-D.
     Если c2 в prev_day, дополнительно: цена не закрепилась за FVG-4h
     до конца cur_day (нет 4h close ниже bottom для LONG / выше top для SHORT
     в окне [c2_close, end_of_cur_day]).
     Зона FVG-4h должна попадать в OB-D (bottom для LONG / top для SHORT
     внутри OB-D).
  3. Зона поиска OB-htf (1h и 2h независимо): со СЛЕДУЮЩЕГО UTC-дня после cur OB-D,
     до момента когда:
     - 2 подряд close на htf-таймфрейме ниже bottom(FVG-4h) для LONG / выше top для SHORT
     - стоп срабатывает только ПОСЛЕ первого касания зоны
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


def find_search_end_htf(
    df_htf_window: pd.DataFrame, direction: str, fvg_top: float, fvg_bottom: float,
) -> int:
    """Сколько свечей сканировать в окне поиска OB-htf (1h или 2h).

    Стоп срабатывает ТОЛЬКО после первого касания зоны FVG-4h ценой:
      LONG: первое касание = low <= fvg_top.
        Стоп: 2 подряд close < fvg_bottom (выход вниз).
      SHORT: первое касание = high >= fvg_bottom.
        Стоп: 2 подряд close > fvg_top (выход вверх).
    До первого касания — search продолжается.
    """
    highs = df_htf_window["high"].values
    lows = df_htf_window["low"].values
    closes = df_htf_window["close"].values
    n = len(df_htf_window)
    entered_zone = False
    for i in range(n):
        h = float(highs[i])
        l = float(lows[i])
        c = float(closes[i])

        if not entered_zone:
            if direction == "LONG":
                if l <= fvg_top:
                    entered_zone = True
            else:
                if h >= fvg_bottom:
                    entered_zone = True
            if not entered_zone:
                continue

        if i >= 1:
            cprev = float(closes[i - 1])
            if direction == "LONG":
                if c < fvg_bottom and cprev < fvg_bottom:
                    return i
            else:
                if c > fvg_top and cprev > fvg_top:
                    return i
    return n


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


def find_signal_in_htf(
    df_htf: pd.DataFrame,
    df_15m: pd.DataFrame,
    df_20m: pd.DataFrame,
    ob_d: OBZone,
    fvg_4h: FVGZone,
    search_start: pd.Timestamp,
    htf_minutes: int,
    htf_label: str,
) -> dict | None:
    """Найти первый OB-htf с валидной FVG entry (15m или 20m).

    Возвращает dict с {ob_htf, htf_label, fvg_entry, fvg_tf} или None.
    """
    df_htf_window = df_htf[df_htf.index >= search_start]
    if df_htf_window.empty:
        return None
    end_idx = find_search_end_htf(
        df_htf_window, ob_d.direction, fvg_4h.top, fvg_4h.bottom,
    )
    df_htf_search = df_htf_window.iloc[:end_idx]
    if len(df_htf_search) < 2:
        return None

    for h_idx in range(1, len(df_htf_search)):
        cand = detect_ob_pair(df_htf_search, h_idx)
        if cand is None or cand.direction != ob_d.direction:
            continue
        # OB-htf должна пересекаться с FVG-4h И с OB-D.
        if not zones_overlap(cand.bottom, cand.top, fvg_4h.bottom, fvg_4h.top):
            continue
        if not zones_overlap(cand.bottom, cand.top, ob_d.bottom, ob_d.top):
            continue

        fvg_15m = find_first_fvg_in_range(
            df_15m,
            cand.prev_time,
            cand.cur_time + pd.Timedelta(minutes=htf_minutes - 15),
            ob_d.direction, cand.bottom, cand.top,
        )
        fvg_20m = find_first_fvg_in_range(
            df_20m,
            cand.prev_time,
            cand.cur_time + pd.Timedelta(minutes=htf_minutes - 20),
            ob_d.direction, cand.bottom, cand.top,
        )

        if fvg_15m is None and fvg_20m is None:
            continue

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
    cnt_with_fvg_4h = 0
    cnt_with_intersection = 0
    cnt_chosen_htf_1h = 0
    cnt_chosen_htf_2h = 0
    cnt_chosen_15m = 0
    cnt_chosen_20m = 0

    for d_idx in range(1, len(df_1d)):
        ob_d = detect_ob_pair(df_1d, d_idx)
        if ob_d is None:
            continue
        cnt_ob_d += 1

        # --- FVG-4h поиск (собираем ВСЕ валидные) ---
        # Time range OB-D = [prev_time, cur_time+1d). FVG-4h должна
        # ПОЛНОСТЬЮ закрыться внутри этого окна, т.е. c2.open_time + 4h
        # <= cur_time + 1d → c2.open_time <= cur_time + 20h.
        fvg_search_start = ob_d.prev_time
        fvg_search_end = ob_d.cur_time + pd.Timedelta(hours=20)
        df_4h_window = df_4h[
            (df_4h.index >= fvg_search_start) & (df_4h.index <= fvg_search_end)
        ]
        if len(df_4h_window) < 3:
            continue

        cur_day_end = ob_d.cur_time + pd.Timedelta(days=1)
        valid_fvg_4h_list: list[FVGZone] = []
        for j in range(2, len(df_4h_window)):
            f = detect_fvg(df_4h_window, j)
            if f is None or f.direction != ob_d.direction:
                continue
            # c2 в prev_day или cur_day OB-D (т.е. в [prev_time, cur_time+1d)).
            if not (ob_d.prev_time <= f.c2_time < cur_day_end):
                continue
            # Если c2 в prev_day — FVG не должна быть invalidated до конца cur_day.
            # Перекрытие по wick: low < bottom для LONG / high > top для SHORT
            # на любой 4h-свече в окне [c2_close, cur_day_end).
            if f.c2_time < ob_d.cur_time:
                check_start = f.c2_time + pd.Timedelta(hours=4)
                df_inval = df_4h[
                    (df_4h.index >= check_start) & (df_4h.index < cur_day_end)
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
            # Зона FVG должна попадать в OB-D.
            if ob_d.direction == "LONG":
                if not (ob_d.bottom <= f.bottom <= ob_d.top):
                    continue
            else:
                if not (ob_d.bottom <= f.top <= ob_d.top):
                    continue
            valid_fvg_4h_list.append(f)

        if not valid_fvg_4h_list:
            continue
        cnt_with_fvg_4h += len(valid_fvg_4h_list)
        cnt_with_intersection += len(valid_fvg_4h_list)

        # --- По каждой FVG-4h: параллельно ищем сигнал на 1h и 2h, берём ранний ---
        for fvg_4h in valid_fvg_4h_list:
            zone_bottom = max(ob_d.bottom, fvg_4h.bottom)
            zone_top = min(ob_d.top, fvg_4h.top)

            # Окно поиска OB-htf: со следующего UTC-дня после cur OB-D.
            search_start = (ob_d.cur_time + pd.Timedelta(days=1)).normalize()

            sig_1h = find_signal_in_htf(
                df_1h, df_15m, df_20m, ob_d, fvg_4h,
                search_start, htf_minutes=60, htf_label="1h",
            )
            sig_2h = find_signal_in_htf(
                df_2h, df_15m, df_20m, ob_d, fvg_4h,
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
                "fvg_4h_c0_time": fvg_4h.c0_time,
                "fvg_4h_c2_time": fvg_4h.c2_time,
                "fvg_4h_zone": (fvg_4h.bottom, fvg_4h.top),
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
        print(f"  + FVG-4h: {cnt_with_fvg_4h}")
        print(f"  + intersection non-empty: {cnt_with_intersection}")
        print(f"  signals: {len(signals)}")
        print(f"      chosen htf 1h: {cnt_chosen_htf_1h}")
        print(f"      chosen htf 2h: {cnt_chosen_htf_2h}")
        print(f"      chosen entry 15m: {cnt_chosen_15m}")
        print(f"      chosen entry 20m: {cnt_chosen_20m}")
    return signals
