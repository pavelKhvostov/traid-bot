"""Strategy 1.1.4: OB-{1d, 12h} + FVG-{4h, 6h} → OB-{1h, 2h} + immediate FVG того же ТФ.

Аналог 1.1.1, но entry-слой заменён на immediate FVG того же ТФ что и OB-htf
(как в 1.1.3 v1):
  - i-1, i  = OB-htf pair (prev, cur)
  - i, i+1, i+2 = FVG того же ТФ (c0=OB cur, c2=i+2)
  - LONG FVG:  high(i)   < low(i+2);   SHORT: low(i)   > high(i+2)

Macro: FVG-4h/6h (как в 1.1.1, не OB-4h/6h как в 1.1.2/1.1.3).

Entry = mid FVG-htf (1h/2h). SL = OB_SL_DEPTH (15%) inside top-OB (как 1.1.1).
"""
from __future__ import annotations

import pandas as pd

from strategies.strategy_1_1_1 import (
    OB_SL_DEPTH,
    OBZone,
    collect_valid_macro_fvgs,
    detect_ob_pair,
)
from strategies.strategy_1_1_3 import find_signal_in_htf_same_tf


def detect_strategy_1_1_4_signals(
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

    Раннее по c2_time выигрывает при выборе между 1h и 2h.
    """
    signals: list[dict] = []
    counters: dict[str, int] = {
        "ob_top_1d": 0, "ob_top_12h": 0,
        "macro_4h": 0, "macro_6h": 0,
        "chosen_htf_1h": 0, "chosen_htf_2h": 0,
        "chosen_macro_4h": 0, "chosen_macro_6h": 0,
        "chosen_top_1d": 0, "chosen_top_12h": 0,
    }

    def _scan_top(df_top: pd.DataFrame, top_tf_hours: int, top_label: str) -> None:
        if df_top is None or df_top.empty:
            return
        for idx in range(1, len(df_top)):
            ob_top = detect_ob_pair(df_top, idx)
            if ob_top is None:
                continue
            counters[f"ob_top_{top_label}"] += 1

            valid_4h = collect_valid_macro_fvgs(
                df_4h, ob_top, htf_hours=4, top_tf_hours=top_tf_hours,
            )
            valid_6h = collect_valid_macro_fvgs(
                df_6h, ob_top, htf_hours=6, top_tf_hours=top_tf_hours,
            )
            counters["macro_4h"] += len(valid_4h)
            counters["macro_6h"] += len(valid_6h)

            all_macro = [(f, "4h") for f in valid_4h] + [(f, "6h") for f in valid_6h]
            if not all_macro:
                continue

            for fvg_macro, macro_tf in all_macro:
                zone_bottom = max(ob_top.bottom, fvg_macro.bottom)
                zone_top = min(ob_top.top, fvg_macro.top)

                search_start = ob_top.cur_time + pd.Timedelta(hours=top_tf_hours)

                sig_1h = find_signal_in_htf_same_tf(
                    df_1h, ob_top, fvg_macro, search_start, htf_label="1h",
                    fvg_variant=fvg_variant,
                )
                sig_2h = find_signal_in_htf_same_tf(
                    df_2h, ob_top, fvg_macro, search_start, htf_label="2h",
                    fvg_variant=fvg_variant,
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

                counters[f"chosen_htf_{htf_label}"] += 1
                counters[f"chosen_macro_{macro_tf}"] += 1
                counters[f"chosen_top_{top_label}"] += 1

                entry = (fvg_entry.bottom + fvg_entry.top) / 2
                ob_depth = ob_top.top - ob_top.bottom
                if ob_top.direction == "LONG":
                    sl = ob_top.bottom + ob_depth * OB_SL_DEPTH
                else:
                    sl = ob_top.top - ob_depth * OB_SL_DEPTH
                risk = abs(entry - sl)
                if risk <= 0:
                    continue

                signals.append({
                    "direction": ob_top.direction,
                    "signal_time": fvg_entry.c2_time,
                    "entry": float(entry),
                    "sl": float(sl),
                    "risk": float(risk),
                    "top_tf": top_label,
                    "top_tf_hours": top_tf_hours,
                    "ob_d_prev_time": ob_top.prev_time,
                    "ob_d_cur_time": ob_top.cur_time,
                    "ob_d_zone": (ob_top.bottom, ob_top.top),
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

    _scan_top(df_1d, 24, "1d")
    _scan_top(df_12h, 12, "12h")

    if verbose:
        print(f"[FUNNEL] OB-top 1d: {counters['ob_top_1d']}  12h: {counters['ob_top_12h']}")
        print(f"  + valid FVG-4h: {counters['macro_4h']}")
        print(f"  + valid FVG-6h: {counters['macro_6h']}")
        print(f"  signals (raw, до dedup): {len(signals)}")
        print(f"      chosen top 1d: {counters['chosen_top_1d']}")
        print(f"      chosen top 12h: {counters['chosen_top_12h']}")
        print(f"      chosen macro 4h: {counters['chosen_macro_4h']}")
        print(f"      chosen macro 6h: {counters['chosen_macro_6h']}")
        print(f"      chosen htf 1h: {counters['chosen_htf_1h']}")
        print(f"      chosen htf 2h: {counters['chosen_htf_2h']}")
    return signals
