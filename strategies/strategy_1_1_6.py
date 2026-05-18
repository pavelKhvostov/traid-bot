"""Strategy 1.1.6: OB-{1d, 12h} + FVG-{4h, 6h} → OB-{1h, 2h} + FVG того же ТФ.

Гибрид:
  - Macro как в 1.1.1: FVG-4h/6h внутри top-OB.
  - Entry как в 1.1.3: FVG того же ТФ что OB-htf (1h или 2h), c0 FVG = OB cur.

Иерархия:
    OB-{1d, 12h}        ← top (4-stage cascade)
    + FVG-{4h, 6h}       ← macro FVG, как в 1.1.1
    → OB-{1h, 2h}        ← htf-OB
    + FVG того же ТФ     ← immediate entry, как в 1.1.3

Entry = mid FVG-htf. SL = OB_SL_DEPTH (15%) inside top-OB (как 1.1.1/1.1.2/1.1.3).
"""
from __future__ import annotations

import pandas as pd

from strategies.strategy_1_1_1 import (
    OB_SL_DEPTH,
    FVGZone,
    OBZone,
    collect_valid_macro_fvgs,
    detect_ob_pair,
    zones_overlap,
)


def find_signal_in_htf_same_tf_with_fvg_macro(
    df_htf: pd.DataFrame,
    ob_d: OBZone,
    fvg_macro: FVGZone,
    search_start: pd.Timestamp,
    htf_label: str,
    fvg_variant: str = "v1",
) -> dict | None:
    """То же что find_signal_in_htf_same_tf из 1.1.3, но macro = FVG, не OB.

    fvg_variant:
      "v1" — FVG на (i, i+1, i+2): c0=OB cur (i)
      "v2" — FVG на (i-1, i, i+1): c0=OB prev (i-1)

    Логика:
      - Итерируем df_htf от search_start.
      - Фрактал ниже fvg_macro.bottom (LONG) / выше top (SHORT) → стоп.
      - На каждой позиции i ищем OB-pair (i-1, i) — direction match, overlap
        с fvg_macro И с top-OB.
      - Проверяем immediate FVG по варианту.
    """
    if fvg_variant not in ("v1", "v2"):
        raise ValueError(f"fvg_variant must be 'v1' or 'v2', got {fvg_variant!r}")
    df_window = df_htf[df_htf.index >= search_start]
    n = len(df_window)
    if n < 3:
        return None

    direction = ob_d.direction
    macro_top = fvg_macro.top
    macro_bottom = fvg_macro.bottom

    highs = df_window["high"].values
    lows = df_window["low"].values

    fractal_confirm_idx: int | None = None

    for i in range(n):
        # 1. Фрактал j=i-2: подтверждается на i.
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
            if direction == "LONG" and is_ll and f_low < macro_bottom:
                fractal_confirm_idx = i
            elif direction == "SHORT" and is_hh and f_high > macro_top:
                fractal_confirm_idx = i

        if fractal_confirm_idx is not None and i > fractal_confirm_idx:
            return None

        # 2. OB-htf на (i-1, i) + overlap с macro и top-OB.
        if i < 1:
            continue
        last_needed = i + 2 if fvg_variant == "v1" else i + 1
        if last_needed >= n:
            continue
        cand = detect_ob_pair(df_window, i)
        if cand is None or cand.direction != direction:
            continue
        if not zones_overlap(cand.bottom, cand.top, macro_bottom, macro_top):
            continue
        if not zones_overlap(cand.bottom, cand.top, ob_d.bottom, ob_d.top):
            continue

        # 3. Immediate FVG того же ТФ что и OB-htf.
        if fvg_variant == "v1":
            c0_idx, c2_idx = i, i + 2
        else:
            c0_idx, c2_idx = i - 1, i + 1
        c0_h = float(highs[c0_idx])
        c0_l = float(lows[c0_idx])
        c2_h = float(highs[c2_idx])
        c2_l = float(lows[c2_idx])

        fvg_entry: FVGZone | None = None
        if direction == "LONG" and c0_h < c2_l:
            fvg_entry = FVGZone(
                direction="LONG", bottom=c0_h, top=c2_l,
                c0_time=df_window.index[c0_idx], c2_time=df_window.index[c2_idx],
            )
        elif direction == "SHORT" and c0_l > c2_h:
            fvg_entry = FVGZone(
                direction="SHORT", bottom=c2_h, top=c0_l,
                c0_time=df_window.index[c0_idx], c2_time=df_window.index[c2_idx],
            )

        if fvg_entry is None:
            continue

        return {
            "ob_htf": cand,
            "htf_label": htf_label,
            "fvg_entry": fvg_entry,
            "fvg_tf": htf_label,
        }

    return None


def detect_strategy_1_1_6_signals(
    df_1d: pd.DataFrame,
    df_12h: pd.DataFrame,
    df_4h: pd.DataFrame,
    df_6h: pd.DataFrame,
    df_1h: pd.DataFrame,
    df_2h: pd.DataFrame,
    fvg_variant: str = "v1",
    verbose: bool = False,
) -> list[dict]:
    """OB-{1d,12h} + FVG-{4h,6h} → OB-{1h,2h} + immediate FVG того же ТФ.

    Раннее по c2_time выигрывает между 1h и 2h.
    """
    signals: list[dict] = []
    counters = {
        "ob_top_1d": 0, "ob_top_12h": 0,
        "macro_4h": 0, "macro_6h": 0,
        "chosen_htf_1h": 0, "chosen_htf_2h": 0,
    }

    def _scan_top(df_top: pd.DataFrame, top_tf_hours: int, top_label: str) -> None:
        if df_top is None or df_top.empty:
            return
        for idx in range(1, len(df_top)):
            ob_top = detect_ob_pair(df_top, idx)
            if ob_top is None:
                continue
            counters[f"ob_top_{top_label}"] += 1

            cur_day_end = ob_top.cur_time + pd.Timedelta(hours=top_tf_hours)
            valid_4h = collect_valid_macro_fvgs(
                df_4h, ob_top, htf_hours=4, top_tf_hours=top_tf_hours,
            )
            valid_6h = collect_valid_macro_fvgs(
                df_6h, ob_top, htf_hours=6, top_tf_hours=top_tf_hours,
            )
            counters["macro_4h"] += len(valid_4h)
            counters["macro_6h"] += len(valid_6h)

            all_macro = (
                [(f, "4h") for f in valid_4h] + [(f, "6h") for f in valid_6h]
            )

            for fvg_macro, macro_label in all_macro:
                # Окно поиска htf-OB: от c2_close макро-FVG до cur_day_end.
                macro_tf_hours = 4 if macro_label == "4h" else 6
                search_start = fvg_macro.c2_time + pd.Timedelta(hours=macro_tf_hours)
                if search_start >= cur_day_end:
                    continue

                # Ограничим окно по cur_day_end через df slice.
                df_1h_w = df_1h[df_1h.index < cur_day_end]
                df_2h_w = df_2h[df_2h.index < cur_day_end]

                sig_1h = find_signal_in_htf_same_tf_with_fvg_macro(
                    df_1h_w, ob_top, fvg_macro, search_start, "1h", fvg_variant
                )
                sig_2h = find_signal_in_htf_same_tf_with_fvg_macro(
                    df_2h_w, ob_top, fvg_macro, search_start, "2h", fvg_variant
                )

                # Выбираем тот, чей c2_time раньше.
                chosen = None
                if sig_1h and sig_2h:
                    if sig_1h["fvg_entry"].c2_time <= sig_2h["fvg_entry"].c2_time:
                        chosen = sig_1h
                    else:
                        chosen = sig_2h
                else:
                    chosen = sig_1h or sig_2h
                if chosen is None:
                    continue
                counters[f"chosen_htf_{chosen['htf_label']}"] += 1

                # Entry = mid FVG-htf.
                fvg = chosen["fvg_entry"]
                entry = (fvg.bottom + fvg.top) / 2.0

                # SL = 15% inside top-OB.
                if ob_top.direction == "LONG":
                    sl = ob_top.bottom + OB_SL_DEPTH * (ob_top.top - ob_top.bottom)
                else:
                    sl = ob_top.top - OB_SL_DEPTH * (ob_top.top - ob_top.bottom)

                signal_time = fvg.c2_time
                signals.append({
                    "strategy": "1.1.6",
                    "signal_time": signal_time,
                    "direction": ob_top.direction,
                    "top_tf": top_label,
                    "macro_tf": macro_label,
                    "ob_htf_tf": chosen["htf_label"],
                    "fvg_tf": chosen["fvg_tf"],
                    "fvg_zone": (fvg.bottom, fvg.top),
                    "ob_htf_zone": (chosen["ob_htf"].bottom, chosen["ob_htf"].top),
                    "ob_d_zone": (ob_top.bottom, ob_top.top),
                    "macro_fvg_zone": (fvg_macro.bottom, fvg_macro.top),
                    "entry": entry,
                    "sl": sl,
                    "ob_d_cur_time": ob_top.cur_time,
                    "ob_d_prev_time": ob_top.prev_time,
                    "ob_htf_cur_time": chosen["ob_htf"].cur_time,
                    "ob_htf_prev_time": chosen["ob_htf"].prev_time,
                })

    _scan_top(df_1d, 24, "1d")
    _scan_top(df_12h, 12, "12h")

    if verbose:
        print(f"[1.1.6 counters] {counters}")

    return signals
