"""Strategy 1.1.3: OB-{1d, 12h} + OB-{4h, 6h} → OB-{1h, 2h} + FVG того же ТФ, immediate.

Аналог 1.1.2, но entry FVG формируется НА ТОМ ЖЕ ТФ что и OB-htf (1h или 2h),
причём первая свеча FVG (c0) = вторая свеча OB-pair (cur).

  i1, i2  — OB pair (prev, cur)
  i2, i3, i4 — FVG triple (c0=i2, c1=i3, c2=i4)
  LONG FVG:  high(i2) < low(i4)   →  zone = [high(i2), low(i4)]
  SHORT FVG: low(i2)  > high(i4)  →  zone = [high(i4), low(i2)]

По построению FVG зона лежит ВЫШЕ OB-htf.top (LONG) или НИЖЕ OB-htf.bottom
(SHORT) — без overlap. Это интенсивный «BOS-like» сетап:
импульс от OB-htf разрывом цены формирует gap (FVG) сразу после.

Entry = mid FVG-htf. SL = OB_SL_DEPTH (15%) inside top-OB (как 1.1.1/1.1.2).
"""
from __future__ import annotations

import pandas as pd

from strategies.strategy_1_1_1 import (
    OB_SL_DEPTH,
    FVGZone,
    OBZone,
    detect_ob_pair,
    zones_overlap,
)
from strategies.strategy_1_1_2 import collect_valid_macro_obs


def collect_valid_macro_obs_untouched(
    df_macro: pd.DataFrame,
    ob_d: OBZone,
    htf_hours: int,
    top_tf_hours: int = 24,
) -> list[OBZone]:
    """Wrapped collect_valid_macro_obs + дополнительный фильтр untouched.

    OB-macro считается валидным только если его зона НЕ затронута (price
    не входил в [bottom, top]) с момента закрытия OB-macro cur и до момента
    закрытия cur OB-1d/12h.

    Untouched-проверка (wick-based, на свечах macro-ТФ):
      LONG  OB: ни одна свеча в окне не имеет low <= ob.top
      SHORT OB: ни одна свеча в окне не имеет high >= ob.bottom

    Окно: [ob_macro.cur_time + htf_hours, cur_day_end), где
    cur_day_end = ob_d.cur_time + top_tf_hours.
    """
    candidates = collect_valid_macro_obs(df_macro, ob_d, htf_hours, top_tf_hours)
    cur_day_end = ob_d.cur_time + pd.Timedelta(hours=top_tf_hours)
    filtered: list[OBZone] = []
    for ob_macro in candidates:
        check_start = ob_macro.cur_time + pd.Timedelta(hours=htf_hours)
        df_check = df_macro[
            (df_macro.index >= check_start) & (df_macro.index < cur_day_end)
        ]
        untouched = True
        for _, row in df_check.iterrows():
            if ob_macro.direction == "LONG":
                if float(row["low"]) <= ob_macro.top:
                    untouched = False; break
            else:
                if float(row["high"]) >= ob_macro.bottom:
                    untouched = False; break
        if untouched:
            filtered.append(ob_macro)
    return filtered


def find_signal_in_htf_same_tf(
    df_htf: pd.DataFrame,
    ob_d: OBZone,
    ob_macro: OBZone,
    search_start: pd.Timestamp,
    htf_label: str,
    fvg_variant: str = "v1",
) -> dict | None:
    """Найти первый OB-htf с immediate FVG того же ТФ.

    Параметр fvg_variant:
      "v1" — FVG на (i, i+1, i+2): c0=OB cur (i), c2=i+2.
             LONG:  high(i)   < low(i+2);   SHORT: low(i)   > high(i+2)
      "v2" — FVG на (i-1, i, i+1): c0=OB prev (i-1), c2=i+1.
             LONG:  high(i-1) < low(i+1);   SHORT: low(i-1) > high(i+1)

    Логика:
      - Итерируемся по df_htf начиная с search_start.
      - При формировании фрактала ниже OB-macro.bottom (LONG) / выше top
        (SHORT) — поиск прекращается (макро инвалидирована).
      - В каждой позиции i пробуем OB-pair (i-1, i): должна совпасть по
        направлению И пересекаться с OB-macro И с top-OB.
      - Проверяем FVG согласно выбранному варианту.

    fvg_tf = htf_label (1h или 2h).
    """
    if fvg_variant not in ("v1", "v2"):
        raise ValueError(f"fvg_variant must be 'v1' or 'v2', got {fvg_variant!r}")
    df_window = df_htf[df_htf.index >= search_start]
    n = len(df_window)
    if n < 3:
        return None

    direction = ob_d.direction
    macro_top = ob_macro.top
    macro_bottom = ob_macro.bottom

    highs = df_window["high"].values
    lows = df_window["low"].values

    fractal_confirm_idx: int | None = None

    for i in range(n):
        # 1. Фрактал j=i-2: подтверждается когда есть свечи i-1, i (= j+1, j+2).
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
        # v1 нужен i+2, v2 нужен i+1
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

        # 3. Immediate FVG: индексы зависят от варианта.
        if fvg_variant == "v1":
            c0_idx, c2_idx = i, i + 2          # c0 = OB cur
        else:
            c0_idx, c2_idx = i - 1, i + 1      # c0 = OB prev
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


def detect_strategy_1_1_3_signals(
    df_1d: pd.DataFrame,
    df_12h: pd.DataFrame,
    df_4h: pd.DataFrame,
    df_6h: pd.DataFrame,
    df_1h: pd.DataFrame,
    df_2h: pd.DataFrame,
    fvg_variant: str = "v1",
    verbose: bool = False,
) -> list[dict]:
    """OB-{1d,12h} + OB-{4h,6h} → OB-{1h,2h} + immediate FVG того же ТФ.

    Раннее по c2_time выигрывает при выборе между 1h и 2h.
    fvg_variant: "v1" (i,i+1,i+2) или "v2" (i-1,i,i+1) — см. find_signal_in_htf_same_tf.
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

            valid_4h = collect_valid_macro_obs_untouched(
                df_4h, ob_top, htf_hours=4, top_tf_hours=top_tf_hours,
            )
            valid_6h = collect_valid_macro_obs_untouched(
                df_6h, ob_top, htf_hours=6, top_tf_hours=top_tf_hours,
            )
            counters["macro_4h"] += len(valid_4h)
            counters["macro_6h"] += len(valid_6h)

            all_macro = [(ob, "4h") for ob in valid_4h] + [(ob, "6h") for ob in valid_6h]
            if not all_macro:
                continue

            for ob_macro, macro_tf in all_macro:
                zone_bottom = max(ob_top.bottom, ob_macro.bottom)
                zone_top = min(ob_top.top, ob_macro.top)
                search_start = ob_top.cur_time + pd.Timedelta(hours=top_tf_hours)

                sig_1h = find_signal_in_htf_same_tf(
                    df_1h, ob_top, ob_macro, search_start, htf_label="1h",
                    fvg_variant=fvg_variant,
                )
                sig_2h = find_signal_in_htf_same_tf(
                    df_2h, ob_top, ob_macro, search_start, htf_label="2h",
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
                    "ob_macro_tf": macro_tf,
                    "ob_macro_prev_time": ob_macro.prev_time,
                    "ob_macro_cur_time": ob_macro.cur_time,
                    "ob_macro_zone": (ob_macro.bottom, ob_macro.top),
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
        print(f"  + valid OB-4h: {counters['macro_4h']}")
        print(f"  + valid OB-6h: {counters['macro_6h']}")
        print(f"  signals (raw, до dedup): {len(signals)}")
        print(f"      chosen top 1d: {counters['chosen_top_1d']}")
        print(f"      chosen top 12h: {counters['chosen_top_12h']}")
        print(f"      chosen macro 4h: {counters['chosen_macro_4h']}")
        print(f"      chosen macro 6h: {counters['chosen_macro_6h']}")
        print(f"      chosen htf 1h: {counters['chosen_htf_1h']}")
        print(f"      chosen htf 2h: {counters['chosen_htf_2h']}")
    return signals
