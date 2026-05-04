"""Strategy 1.1.2: OB-{1d, 12h} + OB-{4h, 6h} → OB-{1h, 2h} + FVG-{15m, 20m}.

Аналог 1.1.1, но макро-слой использует OB-4h/6h вместо FVG-4h/6h.
Все остальные правила (LTF + entry FVG, OB_SL_DEPTH=0.15, dedup-логика)
наследуются.

Правила пересечения зон:
  - OB-macro направления = направление top-OB.
  - OB-macro зона лежит внутри top-OB (близкая к рынку граница).
  - prev-day OB-macro считается невалидной, если close на macro-ТФ
    проходит через ближнюю границу (LONG: close < bottom; SHORT: close > top).
  - OB-htf overlaps с OB-macro AND с top-OB.
  - FVG-15m/20m overlaps с OB-htf.

Entry/SL формула 1.1.1:
  entry = mid FVG-entry, SL = OB_SL_DEPTH (15%) inside top-OB.
"""
from __future__ import annotations

import pandas as pd

from strategies.strategy_1_1_1 import (
    OB_SL_DEPTH,
    OBZone,
    detect_ob_pair,
    find_signal_in_htf,
)


def collect_valid_macro_obs(
    df_macro: pd.DataFrame,
    ob_d: OBZone,
    htf_hours: int,
    top_tf_hours: int = 24,
) -> list[OBZone]:
    """Все валидные OB-pair нужного направления внутри top-OB на ТФ htf_hours.

    Аналог collect_valid_macro_fvgs, но детектится OB-pair (не FVG-тройка)
    и инвалидация на close (а не на wick).
    """
    cur_day_end = ob_d.cur_time + pd.Timedelta(hours=top_tf_hours)
    ob_search_start = ob_d.prev_time
    ob_search_end = ob_d.cur_time + pd.Timedelta(hours=top_tf_hours - htf_hours)
    df_window = df_macro[
        (df_macro.index >= ob_search_start) & (df_macro.index <= ob_search_end)
    ]
    if len(df_window) < 2:
        return []

    valid: list[OBZone] = []
    for j in range(1, len(df_window)):
        ob = detect_ob_pair(df_window, j)
        if ob is None or ob.direction != ob_d.direction:
            continue
        if not (ob_d.prev_time <= ob.cur_time < cur_day_end):
            continue
        # Invalidation для prev-day OB-macro (close-based).
        if ob.cur_time < ob_d.cur_time:
            check_start = ob.cur_time + pd.Timedelta(hours=htf_hours)
            df_inval = df_macro[
                (df_macro.index >= check_start) & (df_macro.index < cur_day_end)
            ]
            invalidated = False
            for _, row in df_inval.iterrows():
                if ob_d.direction == "LONG" and float(row["close"]) < ob.bottom:
                    invalidated = True; break
                if ob_d.direction == "SHORT" and float(row["close"]) > ob.top:
                    invalidated = True; break
            if invalidated:
                continue
        # Зона OB-macro попадает в top-OB (близкая к рынку граница).
        if ob_d.direction == "LONG":
            if not (ob_d.bottom <= ob.bottom <= ob_d.top):
                continue
        else:
            if not (ob_d.bottom <= ob.top <= ob_d.top):
                continue
        valid.append(ob)
    return valid


def collect_valid_macro_obs_extended(
    df_macro: pd.DataFrame,
    ob_d: OBZone,
    df_top: pd.DataFrame,
    htf_hours: int,
    top_tf_hours: int = 24,
) -> list[tuple[OBZone, pd.Timestamp]]:
    """Расширенный сбор macro OB. Возвращает (ob_macro, search_start).

    Включает «старые» macro (cur_time < top-OB cur_time, как раньше) И «новые»
    macro, формирующиеся ПОСЛЕ закрытия top-OB cur, пока top-OB не
    инвалидирован (close на 1d/12h не прошёл через дальнюю границу).

    search_start:
      - для старых = top-OB cur close (cur_day_end) — как раньше
      - для новых  = macro cur close — поиск реакции от момента формирования

    Все правила инвалидации новых macro те же, что у старых: close-based на
    macro-ТФ. Zone overlap с top-OB одинаковый (близкая граница внутри).
    """
    cur_day_end = ob_d.cur_time + pd.Timedelta(hours=top_tf_hours)

    # Top-OB invalidation time (close на df_top через дальнюю границу).
    df_top_after = df_top[df_top.index >= cur_day_end]
    top_invalidation: pd.Timestamp | None = None
    for ts, row in df_top_after.iterrows():
        if ob_d.direction == "LONG" and float(row["close"]) < ob_d.bottom:
            top_invalidation = ts + pd.Timedelta(hours=top_tf_hours)
            break
        if ob_d.direction == "SHORT" and float(row["close"]) > ob_d.top:
            top_invalidation = ts + pd.Timedelta(hours=top_tf_hours)
            break
    if top_invalidation is None:
        top_invalidation = df_macro.index[-1] + pd.Timedelta(hours=htf_hours)

    # Окно поиска OB-macro: prev_time top-OB до top_invalidation - htf_hours.
    ob_search_start = ob_d.prev_time
    ob_search_end = top_invalidation - pd.Timedelta(hours=htf_hours)
    df_window = df_macro[
        (df_macro.index >= ob_search_start) & (df_macro.index <= ob_search_end)
    ]
    if len(df_window) < 2:
        return []

    valid: list[tuple[OBZone, pd.Timestamp]] = []
    for j in range(1, len(df_window)):
        ob = detect_ob_pair(df_window, j)
        if ob is None or ob.direction != ob_d.direction:
            continue
        if not (ob_d.prev_time <= ob.cur_time < top_invalidation):
            continue
        macro_close = ob.cur_time + pd.Timedelta(hours=htf_hours)
        if macro_close > top_invalidation:
            continue

        # Старые macro: invalidation между macro close и top close (как раньше).
        if ob.cur_time < ob_d.cur_time:
            df_inval = df_macro[
                (df_macro.index >= macro_close) & (df_macro.index < cur_day_end)
            ]
            invalidated = False
            for _, row in df_inval.iterrows():
                if ob_d.direction == "LONG" and float(row["close"]) < ob.bottom:
                    invalidated = True; break
                if ob_d.direction == "SHORT" and float(row["close"]) > ob.top:
                    invalidated = True; break
            if invalidated:
                continue

        # Zone overlap (близкая к рынку граница macro попадает в top-OB).
        if ob_d.direction == "LONG":
            if not (ob_d.bottom <= ob.bottom <= ob_d.top):
                continue
        else:
            if not (ob_d.bottom <= ob.top <= ob_d.top):
                continue

        # search_start: для старых = top close, для новых = macro close.
        if ob.cur_time < ob_d.cur_time:
            search_start = cur_day_end
        else:
            search_start = macro_close

        valid.append((ob, search_start))
    return valid


def detect_strategy_1_1_2_signals(
    df_1d: pd.DataFrame,
    df_12h: pd.DataFrame,
    df_4h: pd.DataFrame,
    df_6h: pd.DataFrame,
    df_1h: pd.DataFrame,
    df_2h: pd.DataFrame,
    df_15m: pd.DataFrame,
    df_20m: pd.DataFrame,
    extended_macro_search: bool = False,
    verbose: bool = False,
) -> list[dict]:
    """OB-{1d,12h} + OB-{4h,6h} → OB-{1h,2h} + FVG-{15m,20m}.

    Под каждым top-OB ищутся валидные OB-macro (4h И 6h независимо).
    Под каждой macro-OB — OB-htf (1h И 2h) + entry FVG (15m И 20m).
    Раннее по c2_time выигрывает.

    extended_macro_search: если True — включает macro, формирующиеся ПОСЛЕ
    закрытия cur top-OB (пока top-OB активен). Поиск реакции для них
    стартует от закрытия их cur (а не от закрытия top-OB).
    """
    signals: list[dict] = []
    counters: dict[str, int] = {
        "ob_top_1d": 0, "ob_top_12h": 0,
        "macro_4h": 0, "macro_6h": 0,
        "chosen_htf_1h": 0, "chosen_htf_2h": 0,
        "chosen_15m": 0, "chosen_20m": 0,
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

            cur_day_end = ob_top.cur_time + pd.Timedelta(hours=top_tf_hours)
            if extended_macro_search:
                valid_4h_ext = collect_valid_macro_obs_extended(
                    df_4h, ob_top, df_top, htf_hours=4, top_tf_hours=top_tf_hours,
                )
                valid_6h_ext = collect_valid_macro_obs_extended(
                    df_6h, ob_top, df_top, htf_hours=6, top_tf_hours=top_tf_hours,
                )
            else:
                valid_4h_ext = [
                    (ob, cur_day_end) for ob in collect_valid_macro_obs(
                        df_4h, ob_top, htf_hours=4, top_tf_hours=top_tf_hours,
                    )
                ]
                valid_6h_ext = [
                    (ob, cur_day_end) for ob in collect_valid_macro_obs(
                        df_6h, ob_top, htf_hours=6, top_tf_hours=top_tf_hours,
                    )
                ]
            counters["macro_4h"] += len(valid_4h_ext)
            counters["macro_6h"] += len(valid_6h_ext)

            all_macro = (
                [(ob, ss, "4h") for ob, ss in valid_4h_ext]
                + [(ob, ss, "6h") for ob, ss in valid_6h_ext]
            )
            if not all_macro:
                continue

            for ob_macro, search_start, macro_tf in all_macro:
                zone_bottom = max(ob_top.bottom, ob_macro.bottom)
                zone_top = min(ob_top.top, ob_macro.top)

                # find_signal_in_htf принимает FVGZone, но использует только
                # .bottom/.top — OBZone duck-types корректно.
                sig_1h = find_signal_in_htf(
                    df_1h, df_15m, df_20m, ob_top, ob_macro,
                    search_start, htf_minutes=60, htf_label="1h",
                )
                sig_2h = find_signal_in_htf(
                    df_2h, df_15m, df_20m, ob_top, ob_macro,
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
        print(f"      chosen entry 15m: {counters['chosen_15m']}")
        print(f"      chosen entry 20m: {counters['chosen_20m']}")
    return signals
