"""Strategy 1.1.5: 1d-фрактал → 4h/6h sweep → 4h/6h OB → 1h/2h OB + 15m/20m FVG.

Воронка:
  1. Daily фрактал i±2 на df_1d.
       HH: high(i) > high(i-2), high(i-1), high(i+1), high(i+2)  → SHORT setup.
       LL: low(i)  < low(i-2),  low(i-1),  low(i+1),  low(i+2)   → LONG setup.
     Подтверждается на close i+2 (fractal_open + 3·1d).
  2. На том же ТФ ∈ {4h, 6h} (независимо) — первая failed-sweep свеча.
       HH: high(j) > fractal_high. close(j) ≥ fractal_high → пробой, setup мёртв.
                                    close(j) < fractal_high → failed sweep ✓
       LL: симметрично, close(j) > fractal_low.
     Логика «первой касающейся» совпадает с live fractal.py.
  3. Первый OB того же направления на том же ТФ (4h/6h):
       cur ∈ [sweep_idx, sweep_idx + k_after] — окно «k свечей после снятия»
       плюс особый случай cur=sweep_idx (cur OB сам же снимает фрактал).
  4. В зоне OB-{4h,6h} — первый OB-{1h,2h} того же направления, у которого
     валидная FVG-{15m,20m} внутри его жизни.
     OB-htf и FVG-entry — те же canon-формулы, что в 1.1.1.
     Окно FVG: [ob_htf.prev_time, ob_htf.cur_time + (htf_min - fvg_min)].
     Параллельно ищется 1h И 2h, 15m И 20m — ранний по fvg_entry.c2_time выигрывает.

Если на любом ярусе ничего не нашлось — setup скипается (юзер 2026-05-06).
Entry/SL/TP — НЕ вычисляются (детектор возвращает только зоны).

OB/FVG canon — см. vault/.../универсальные определения OB и FVG.md.
"""
from __future__ import annotations

import pandas as pd

from strategies.strategy_1_1_1 import (
    FVGZone,
    OBZone,
    detect_ob_pair,
    find_first_fvg_in_range,
    zones_overlap,
)


def _is_hh_fractal_1d(df_1d: pd.DataFrame, i: int) -> bool:
    """HH-фрактал i±2: high(i) строго больше высот соседей."""
    if i < 2 or i + 2 >= len(df_1d):
        return False
    hi = float(df_1d.iloc[i]["high"])
    for k in (i - 2, i - 1, i + 1, i + 2):
        if hi <= float(df_1d.iloc[k]["high"]):
            return False
    return True


def _is_ll_fractal_1d(df_1d: pd.DataFrame, i: int) -> bool:
    """LL-фрактал i±2: low(i) строго меньше низов соседей."""
    if i < 2 or i + 2 >= len(df_1d):
        return False
    lo = float(df_1d.iloc[i]["low"])
    for k in (i - 2, i - 1, i + 1, i + 2):
        if lo >= float(df_1d.iloc[k]["low"]):
            return False
    return True


def _find_first_sweep_idx(
    df_htf: pd.DataFrame,
    search_start: pd.Timestamp,
    fractal_price: float,
    fractal_type: str,
) -> int | None:
    """Индекс первой свечи failed-sweep уровня в df_htf начиная с search_start.

    HH: первая свеча с high > fractal_price. Если close ≥ fractal_price → пробой
        (return None). Если close < fractal_price → snipe ✓ (return idx).
    LL: симметрично — close > fractal_price → snipe.

    Возвращает индекс В ИСХОДНОМ df_htf (не в окне).
    """
    if df_htf is None or df_htf.empty:
        return None
    mask = df_htf.index >= search_start
    if not mask.any():
        return None
    start_pos = int(mask.argmax())  # первый True
    n = len(df_htf)
    for j in range(start_pos, n):
        row = df_htf.iloc[j]
        hi = float(row["high"])
        lo = float(row["low"])
        cl = float(row["close"])
        if fractal_type == "HH":
            if hi <= fractal_price:
                continue
            if cl >= fractal_price:
                return None
            return j
        else:  # LL
            if lo >= fractal_price:
                continue
            if cl <= fractal_price:
                return None
            return j
    return None


def _find_first_ob_after_sweep(
    df_htf: pd.DataFrame,
    sweep_idx: int,
    k_after: int,
    direction: str,
) -> OBZone | None:
    """Первый OB-pair с cur ∈ [sweep_idx, sweep_idx + k_after].

    Включает особый случай cur=sweep_idx (свеча-снятие одновременно cur OB,
    prev = sweep_idx - 1). Дальше — k_after свечей после sweep.
    """
    cur_max = min(sweep_idx + k_after, len(df_htf) - 1)
    for cur_idx in range(sweep_idx, cur_max + 1):
        if cur_idx < 1:
            continue
        ob = detect_ob_pair(df_htf, cur_idx)
        if ob is None or ob.direction != direction:
            continue
        return ob
    return None


def _find_htf_ob_with_entry_fvg(
    df_htf: pd.DataFrame,
    df_15m: pd.DataFrame,
    df_20m: pd.DataFrame,
    zone_bottom: float,
    zone_top: float,
    direction: str,
    search_start: pd.Timestamp,
    htf_minutes: int,
    htf_label: str,
) -> dict | None:
    """Первый OB-htf того же направления в зоне [zone_bottom, zone_top]
    с валидной FVG-entry (15m или 20m, ранний выигрывает).

    Окно FVG: [ob_htf.prev_time, ob_htf.cur_time + (htf_minutes - fvg_minutes)].
    Если у текущего OB-htf FVG нет — продолжаем перебор следующих OB-htf.
    """
    if df_htf is None or df_htf.empty:
        return None
    df_window = df_htf[df_htf.index >= search_start]
    if len(df_window) < 2:
        return None

    for i in range(1, len(df_window)):
        cand = detect_ob_pair(df_window, i)
        if cand is None or cand.direction != direction:
            continue
        if not zones_overlap(cand.bottom, cand.top, zone_bottom, zone_top):
            continue
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


def detect_strategy_1_1_5_signals(
    df_1d: pd.DataFrame,
    df_4h: pd.DataFrame,
    df_6h: pd.DataFrame,
    df_1h: pd.DataFrame,
    df_2h: pd.DataFrame,
    df_15m: pd.DataFrame,
    df_20m: pd.DataFrame,
    k_after: int = 3,
    verbose: bool = False,
) -> list[dict]:
    """Полная воронка 1.1.5: 1d-фрактал → 4h/6h sweep+OB → 1h/2h OB + 15m/20m FVG.

    Args:
        df_1d/df_4h/df_6h/df_1h/df_2h/df_15m/df_20m: pandas.DataFrame с UTC-индексом
            и колонками open/high/low/close/volume. Пустые DF — допустимы (ветка скипается).
        k_after: окно поиска 4h/6h OB после snipe. cur ∈ [sweep_idx, sweep_idx + k_after].
            По умолчанию 3; в бэктесте перебирается 3 и 4.
        verbose: печать счётчиков воронки.

    Returns:
        Список сигналов (dict). Один фрактал → до 2 сигналов (4h-ветка + 6h-ветка).
        Дедуп — на уровне бэктест-обвязки.
    """
    signals: list[dict] = []
    counters = {
        "fractals_hh": 0, "fractals_ll": 0,
        "swept_4h": 0, "swept_6h": 0,
        "macro_ob_4h": 0, "macro_ob_6h": 0,
        "with_htf_1h": 0, "with_htf_2h": 0,
        "with_fvg_15m": 0, "with_fvg_20m": 0,
    }

    n_1d = len(df_1d)
    for i in range(2, n_1d - 2):
        is_hh = _is_hh_fractal_1d(df_1d, i)
        is_ll = _is_ll_fractal_1d(df_1d, i)
        if not (is_hh or is_ll):
            continue

        if is_hh:
            counters["fractals_hh"] += 1
            fractal_type = "HH"
            direction = "SHORT"
            fractal_price = float(df_1d.iloc[i]["high"])
        else:
            counters["fractals_ll"] += 1
            fractal_type = "LL"
            direction = "LONG"
            fractal_price = float(df_1d.iloc[i]["low"])

        fractal_time = df_1d.index[i]
        confirm_time = df_1d.index[i + 2] + pd.Timedelta(days=1)

        for df_macro, macro_label, macro_hours in (
            (df_4h, "4h", 4), (df_6h, "6h", 6),
        ):
            sweep_idx = _find_first_sweep_idx(
                df_macro, confirm_time, fractal_price, fractal_type,
            )
            if sweep_idx is None:
                continue
            counters[f"swept_{macro_label}"] += 1

            ob_macro = _find_first_ob_after_sweep(
                df_macro, sweep_idx, k_after, direction,
            )
            if ob_macro is None:
                continue
            counters[f"macro_ob_{macro_label}"] += 1

            # Поиск OB-htf+FVG-entry начинается с close cur OB-macro.
            search_start_htf = ob_macro.cur_time + pd.Timedelta(hours=macro_hours)

            sig_1h = _find_htf_ob_with_entry_fvg(
                df_1h, df_15m, df_20m, ob_macro.bottom, ob_macro.top, direction,
                search_start_htf, htf_minutes=60, htf_label="1h",
            )
            sig_2h = _find_htf_ob_with_entry_fvg(
                df_2h, df_15m, df_20m, ob_macro.bottom, ob_macro.top, direction,
                search_start_htf, htf_minutes=120, htf_label="2h",
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

            ob_htf: OBZone = chosen["ob_htf"]
            fvg_entry: FVGZone = chosen["fvg_entry"]
            counters[f"with_htf_{chosen['htf_label']}"] += 1
            counters[f"with_fvg_{chosen['fvg_tf']}"] += 1

            sweep_time = df_macro.index[sweep_idx]
            sweep_row = df_macro.iloc[sweep_idx]
            ob_macro_cur_pos = df_macro.index.get_loc(ob_macro.cur_time)

            signals.append({
                "direction": direction,
                "fractal_type": fractal_type,
                "fractal_time": fractal_time,
                "fractal_price": fractal_price,
                "fractal_confirm_time": confirm_time,
                "sweep_tf": macro_label,
                "sweep_time": sweep_time,
                "sweep_open": float(sweep_row["open"]),
                "sweep_high": float(sweep_row["high"]),
                "sweep_low": float(sweep_row["low"]),
                "sweep_close": float(sweep_row["close"]),
                "macro_ob_tf": macro_label,
                "macro_ob_prev_time": ob_macro.prev_time,
                "macro_ob_cur_time": ob_macro.cur_time,
                "macro_ob_zone": (ob_macro.bottom, ob_macro.top),
                "k_after": k_after,
                "macro_ob_cur_is_sweep": (ob_macro_cur_pos == sweep_idx),
                "ob_htf_tf": chosen["htf_label"],
                "ob_htf_prev_time": ob_htf.prev_time,
                "ob_htf_cur_time": ob_htf.cur_time,
                "ob_htf_zone": (ob_htf.bottom, ob_htf.top),
                "fvg_entry_tf": chosen["fvg_tf"],
                "fvg_entry_c0_time": fvg_entry.c0_time,
                "fvg_entry_c2_time": fvg_entry.c2_time,
                "fvg_entry_zone": (fvg_entry.bottom, fvg_entry.top),
                "signal_time": fvg_entry.c2_time,
            })

    if verbose:
        print(f"[FUNNEL 1.1.5 k_after={k_after}]")
        print(f"  fractals: HH={counters['fractals_hh']} LL={counters['fractals_ll']}")
        print(f"  swept: 4h={counters['swept_4h']} 6h={counters['swept_6h']}")
        print(f"  macro OB: 4h={counters['macro_ob_4h']} 6h={counters['macro_ob_6h']}")
        print(f"  htf chosen: 1h={counters['with_htf_1h']} 2h={counters['with_htf_2h']}")
        print(f"  fvg chosen: 15m={counters['with_fvg_15m']} 20m={counters['with_fvg_20m']}")
        print(f"  signals total: {len(signals)}")
    return signals
