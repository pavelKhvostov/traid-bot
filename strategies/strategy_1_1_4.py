"""Strategy 1.1.4: FVG-{1d, 12h} + FVG-{4h, 6h} -> OB-{1h, 2h} + FVG-{15m, 20m}.

Аналог 1.1.1, но top-уровень — FVG (1d/12h), а не OB. Остальная воронка
без изменений: macro = FVG-{4h, 6h}, htf = OB-{1h, 2h}, entry = FVG-{15m, 20m}.

Зоны (canon, см. vault/.../универсальные определения OB и FVG.md):
  Top FVG (тройка c0=i-2, c1=i-1, c2=i):
    LONG:  high(c0) < low(c2).   Zone = [high(c0), low(c2)]
    SHORT: low(c0) > high(c2).   Zone = [high(c2), low(c0)]
  OB pair (prev, cur):
    LONG:  prev медвежья, cur.close > prev.open. Zone = [min(prev.low, cur.low), prev.open]
    SHORT: prev бычья,    cur.close < prev.open. Zone = [prev.open, max(prev.high, cur.high)]

Entry = середина выбранной FVG-entry (15m/20m).
SL = ob_htf.bottom (LONG) / ob_htf.top (SHORT) — на дальней границе htf-OB,
без буфера. Отличается от 1.1.1, где SL = OB_SL_DEPTH inside top-OB.

Окна:
  Macro FVG c2 в окне [top_fvg.c0_time, top_fvg.c2_time + top_tf_hours).
  Macro candle открывается до [top_fvg.c2_time + (top_tf_hours - htf_hours)h].
  Если macro c2 < top_fvg.c2_time — wick-invalidation на свечах того же ТФ
  в окне [c2_close, top_fvg.c2_time + top_tf_hours).
  search_start htf-OB = top_fvg.c2_time + top_tf_hours.
"""
from __future__ import annotations

import pandas as pd

from strategies.strategy_1_1_1 import (
    FVGZone,
    detect_fvg,
    find_signal_in_htf,
    zones_overlap,
)


def collect_valid_macro_fvgs_in_top_fvg(
    df_macro: pd.DataFrame,
    top_fvg: FVGZone,
    htf_hours: int,
    top_tf_hours: int = 24,
) -> list[FVGZone]:
    """Все валидные macro-FVG нужного направления внутри top-FVG.

    Аналог `collect_valid_macro_fvgs` из 1.1.1, но top-зона — FVG, а не OB.
    Окно по c2 macro-FVG: [top_fvg.c0_time, top_fvg.c2_time + top_tf_hours).
    Macro candle полностью закрывается до конца окна: c2_open ≤
    top_fvg.c2_time + (top_tf_hours - htf_hours)h.
    Если macro c2 < top_fvg.c2_time → wick-invalidation как в 1.1.1.
    Зона FVG-macro попадает в зону top-FVG (LONG: bottom ∈ top-FVG;
    SHORT: top ∈ top-FVG).
    """
    cur_top_end = top_fvg.c2_time + pd.Timedelta(hours=top_tf_hours)
    fvg_search_start = top_fvg.c0_time
    fvg_search_end = top_fvg.c2_time + pd.Timedelta(hours=top_tf_hours - htf_hours)
    df_window = df_macro[
        (df_macro.index >= fvg_search_start) & (df_macro.index <= fvg_search_end)
    ]
    if len(df_window) < 3:
        return []

    valid: list[FVGZone] = []
    for j in range(2, len(df_window)):
        f = detect_fvg(df_window, j)
        if f is None or f.direction != top_fvg.direction:
            continue
        if not (top_fvg.c0_time <= f.c2_time < cur_top_end):
            continue
        # Invalidation для prev-bar macro FVG (на свечах того же ТФ).
        if f.c2_time < top_fvg.c2_time:
            check_start = f.c2_time + pd.Timedelta(hours=htf_hours)
            df_inval = df_macro[
                (df_macro.index >= check_start) & (df_macro.index < cur_top_end)
            ]
            invalidated = False
            for _, row in df_inval.iterrows():
                if top_fvg.direction == "LONG" and float(row["low"]) < f.bottom:
                    invalidated = True
                    break
                if top_fvg.direction == "SHORT" and float(row["high"]) > f.top:
                    invalidated = True
                    break
            if invalidated:
                continue
        # Зона FVG-macro попадает в top-FVG.
        if top_fvg.direction == "LONG":
            if not (top_fvg.bottom <= f.bottom <= top_fvg.top):
                continue
        else:
            if not (top_fvg.bottom <= f.top <= top_fvg.top):
                continue
        valid.append(f)
    return valid


def detect_strategy_1_1_4_signals(
    df_1d: pd.DataFrame,
    df_12h: pd.DataFrame,
    df_4h: pd.DataFrame,
    df_6h: pd.DataFrame,
    df_1h: pd.DataFrame,
    df_2h: pd.DataFrame,
    df_15m: pd.DataFrame,
    df_20m: pd.DataFrame,
    verbose: bool = False,
) -> list[dict]:
    """Сканирует FVG-1d И FVG-12h как параллельные top-уровни и собирает сигналы.

    Под каждым top-FVG ищется FVG-macro (4h ИЛИ 6h) → OB-htf (1h ИЛИ 2h)
    → entry FVG (15m ИЛИ 20m). Сигналы из обеих веток объединяются;
    дедуп выполняется на уровне backtest_strategy_1_1_4.dedupe_signals.

    Если df_12h пуст — работаем только через 1d.
    """
    signals: list[dict] = []
    counters: dict[str, int] = {
        "fvg_top_1d": 0, "fvg_top_12h": 0,
        "macro_4h": 0, "macro_6h": 0,
        "chosen_htf_1h": 0, "chosen_htf_2h": 0,
        "chosen_15m": 0, "chosen_20m": 0,
        "chosen_macro_4h": 0, "chosen_macro_6h": 0,
        "chosen_top_1d": 0, "chosen_top_12h": 0,
    }

    def _scan_top(df_top: pd.DataFrame, top_tf_hours: int, top_label: str) -> None:
        if df_top is None or df_top.empty:
            return
        for idx in range(2, len(df_top)):
            top_fvg = detect_fvg(df_top, idx)
            if top_fvg is None:
                continue
            counters[f"fvg_top_{top_label}"] += 1

            valid_4h = collect_valid_macro_fvgs_in_top_fvg(
                df_4h, top_fvg, htf_hours=4, top_tf_hours=top_tf_hours,
            )
            valid_6h = collect_valid_macro_fvgs_in_top_fvg(
                df_6h, top_fvg, htf_hours=6, top_tf_hours=top_tf_hours,
            )
            counters["macro_4h"] += len(valid_4h)
            counters["macro_6h"] += len(valid_6h)

            all_macro = [(f, "4h") for f in valid_4h] + [(f, "6h") for f in valid_6h]
            if not all_macro:
                continue

            for fvg_macro, macro_tf in all_macro:
                zone_bottom = max(top_fvg.bottom, fvg_macro.bottom)
                zone_top = min(top_fvg.top, fvg_macro.top)

                # search_start htf-OB = момент после закрытия cur top-bar
                # (top_fvg.c2_time занимает 1 бар → +top_tf_hours).
                search_start = top_fvg.c2_time + pd.Timedelta(hours=top_tf_hours)

                # find_signal_in_htf принимает ob_d с полями direction/bottom/top —
                # FVGZone подходит (canon-совместимость).
                sig_1h = find_signal_in_htf(
                    df_1h, df_15m, df_20m, top_fvg, fvg_macro,
                    search_start, htf_minutes=60, htf_label="1h",
                )
                sig_2h = find_signal_in_htf(
                    df_2h, df_15m, df_20m, top_fvg, fvg_macro,
                    search_start, htf_minutes=120, htf_label="2h",
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
                counters[f"chosen_{fvg_tf}"] += 1
                counters[f"chosen_macro_{macro_tf}"] += 1
                counters[f"chosen_top_{top_label}"] += 1

                entry = (fvg_entry.bottom + fvg_entry.top) / 2
                # SL на дальней границе htf-OB, без буфера.
                if top_fvg.direction == "LONG":
                    sl = ob_htf.bottom
                else:
                    sl = ob_htf.top
                risk = abs(entry - sl)
                if risk <= 0:
                    continue

                signals.append({
                    "direction": top_fvg.direction,
                    "signal_time": fvg_entry.c2_time,
                    "entry": float(entry),
                    "sl": float(sl),
                    "risk": float(risk),
                    "top_tf": top_label,
                    "top_tf_hours": top_tf_hours,
                    "top_fvg_c0_time": top_fvg.c0_time,
                    "top_fvg_c2_time": top_fvg.c2_time,
                    "top_fvg_zone": (top_fvg.bottom, top_fvg.top),
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
        print(f"[FUNNEL] FVG-top 1d: {counters['fvg_top_1d']}  12h: {counters['fvg_top_12h']}")
        print(f"  + valid FVG-4h: {counters['macro_4h']}")
        print(f"  + valid FVG-6h: {counters['macro_6h']}")
        print(f"  signals (raw, до dedup): {len(signals)}")
        print(f"      chosen top 1d: {counters['chosen_top_1d']}")
        print(f"      chosen top 12h: {counters['chosen_top_12h']}")
        print(f"      chosen macro 4h: {counters['chosen_macro_4h']}")
        print(f"      chosen macro 6h: {counters['chosen_macro_6h']}")
        print(f"      chosen htf 1h: {counters['chosen_htf_1h']}")
        print(f"      chosen htf 2h: {counters['chosen_htf_2h']}")
        print(f"      chosen entry 15m: {counters['chosen_15m']}")
        print(f"      chosen entry 20m: {counters['chosen_20m']}")
    return signals
