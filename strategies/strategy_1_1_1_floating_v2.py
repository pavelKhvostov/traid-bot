"""Strategy 1.1.1 + Floating TP — V2 с заменой L3+L4 на `ob_vc` (9 канонов).

Версия v2 — оригинальный 1.1.1 cascade со стрictой 9-canon заменой
нижнего композита (OB-{1h,2h} + FVG-{15m,20m}) на единый элемент `ob_vc`
по канону Vadim'a (см. vault/sessions/2026-05-29-evening-ob-vc-canon-and-rule-10.md).

Сравнение архитектуры:

  v1 (strategy_1_1_1_floating.py):
    L1 OB-{1d,12h} → L2 FVG-{4h,6h} → L3 OB-{1h,2h} SWEPT → L4 FVG-{15m,20m}

  v2 (ЭТОТ ФАЙЛ):
    L1 OB-{1d,12h} → L2 FVG-{4h,6h} → ob_vc(HTF={1h,2h}, LTF={15m,20m})
                                       ── один композит с 9 каноническими ──
                                       ── условиями вместо SWEPT-фильтра  ──

Ob_vc 9 канонических условий (из session note 2026-05-29):
  1. Сонаправленность: ob.direction == fvg.direction
  2. HTF OB существует на canon-TF
  3. LTF FVG существует на canon-LTF
  4. Spatial overlap с drop/rally area (хотя бы частично)
  5. FVG.zone ⊆ [low_ob_vc, first_Williams_FH/FL.extreme]
  6. OB actionable (caller's responsibility) — пропускается в детекторе
  7. Temporal lower: fvg.c1.open_time ≥ ob.cur.open_time
  8. Temporal upper: fvg.c3.close_time ≤ first_fractal.confirmation_time
  9. FVG не consumed на 1m в окне [fvg.c3.close_time, first_fractal.confirmation_time]

Все остальное (entry/SL/floating TP/per-symbol configs) — идентично v1.
Файл v1 (`strategy_1_1_1_floating.py`) остается без изменений.

Источники канона:
  - vault/sessions/2026-05-29-evening-ob-vc-canon-and-rule-10.md (полная спека)
  - vault/sessions/2026-05-29-night-mh-ml-pipeline-3064-features-pc2-archive.md (доп.)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from strategies.strategy_1_1_1 import (
    OBZone,
    FVGZone,
    collect_valid_macro_fvgs,
    detect_fvg,
    detect_ob_pair,
)

# Переиспользуем индикаторы, score и simulator из v1 — они НЕ зависят от cascade.
from strategies.strategy_1_1_1_floating import (
    FLOATING_TP_CONFIG,
    ENTRY_PCT,
    SL_PCT,
    RR_BASELINE,
    MAX_HOLD_DAYS,
    TradeResult,
    build_score_series,
    simulate_floating,
    aggregate_stats,
)


# ============================================================
# OB_VC — geometric helpers (per Vadim canon)
# ============================================================

def _has_breaker(ob: OBZone, df: pd.DataFrame) -> bool:
    """Breaker block существует ТОЛЬКО при полном пробое prev:
        LONG:  cur.close > prev.high
        SHORT: cur.close < prev.low
    (canon обновлён 2026-05-29 в session note Section VI).
    """
    try:
        prev_idx = df.index.get_loc(ob.prev_time)
        cur_idx = df.index.get_loc(ob.cur_time)
    except (KeyError, TypeError):
        return False
    if prev_idx < 0 or cur_idx >= len(df):
        return False
    prev = df.iloc[prev_idx]; cur = df.iloc[cur_idx]
    if ob.direction == "LONG":
        return float(cur["close"]) > float(prev["high"])
    return float(cur["close"]) < float(prev["low"])


def _drop_or_rally_area(ob: OBZone, df: pd.DataFrame) -> tuple[float, float]:
    """Drop area (LONG) / rally area (SHORT) — узкая часть OB.zone.

    Canon (definition.md OB):
      LONG drop area  = [prev.open, prev.close] reversed = wick от open до low
      SHORT rally area = [prev.close, prev.open] = wick от open до high

    Упрощённо для нашего детектора: возвращаем zone без breaker block:
      LONG:  [ob.bottom, prev.open]   (нижний wick + body anchor low)
      SHORT: [prev.open, ob.top]      (тело прыжка + upper wick)

    Если breaker НЕ существует, drop/rally area = вся ob.zone.
    """
    has_breaker = _has_breaker(ob, df)
    if not has_breaker:
        return (ob.bottom, ob.top)
    # С breaker — drop area = wick часть (без области тела cur)
    try:
        prev = df.loc[ob.prev_time]
    except KeyError:
        return (ob.bottom, ob.top)
    p_open = float(prev["open"])
    if ob.direction == "LONG":
        # Drop area = [ob.bottom, p_open]
        return (ob.bottom, p_open)
    # SHORT rally area
    return (p_open, ob.top)


def _is_williams_fh(df: pd.DataFrame, idx: int, n: int = 2) -> bool:
    """Williams N=2 Fractal High в баре idx: high(idx) > high(idx±k) для k=1..n."""
    if idx < n or idx + n >= len(df):
        return False
    h = float(df.iloc[idx]["high"])
    for k in range(1, n + 1):
        if h <= float(df.iloc[idx - k]["high"]):
            return False
        if h <= float(df.iloc[idx + k]["high"]):
            return False
    return True


def _is_williams_fl(df: pd.DataFrame, idx: int, n: int = 2) -> bool:
    """Williams N=2 Fractal Low в баре idx."""
    if idx < n or idx + n >= len(df):
        return False
    l = float(df.iloc[idx]["low"])
    for k in range(1, n + 1):
        if l >= float(df.iloc[idx - k]["low"]):
            return False
        if l >= float(df.iloc[idx + k]["low"]):
            return False
    return True


def _first_williams_fl_below(
    df_htf: pd.DataFrame, ob: OBZone, n: int = 2,
) -> tuple[int, float, pd.Timestamp] | None:
    """Первый Williams N=2 FL ПОСЛЕ ob.cur_time, low < ob.bottom.

    Используется для LONG ob_vc — выявляет fractal low ниже drop area.
    confirmation_time = время бара (idx + n) — момент когда фрактал confirmed.

    Возвращает (idx, low_value, confirmation_time) или None.
    """
    try:
        cur_idx = df_htf.index.get_loc(ob.cur_time)
    except (KeyError, TypeError):
        return None
    for j in range(cur_idx + n + 1, len(df_htf) - n):
        if not _is_williams_fl(df_htf, j, n):
            continue
        if float(df_htf.iloc[j]["low"]) >= ob.bottom:
            continue
        confirm_idx = j + n
        if confirm_idx >= len(df_htf):
            return None
        return (j, float(df_htf.iloc[j]["low"]), df_htf.index[confirm_idx])
    return None


def _first_williams_fh_above(
    df_htf: pd.DataFrame, ob: OBZone, n: int = 2,
) -> tuple[int, float, pd.Timestamp] | None:
    """Первый Williams N=2 FH ПОСЛЕ ob.cur_time, high > ob.top.
    Для SHORT ob_vc."""
    try:
        cur_idx = df_htf.index.get_loc(ob.cur_time)
    except (KeyError, TypeError):
        return None
    for j in range(cur_idx + n + 1, len(df_htf) - n):
        if not _is_williams_fh(df_htf, j, n):
            continue
        if float(df_htf.iloc[j]["high"]) <= ob.top:
            continue
        confirm_idx = j + n
        if confirm_idx >= len(df_htf):
            return None
        return (j, float(df_htf.iloc[j]["high"]), df_htf.index[confirm_idx])
    return None


def _fvg_consumed_on_1m(
    df_1m: pd.DataFrame,
    fvg: FVGZone,
    fvg_c3_close_time: pd.Timestamp,
    fractal_confirmation_time: pd.Timestamp,
) -> bool:
    """Условие #9: FVG consumed на 1m в окне [c3.close, fh.confirmation].

    LONG FVG consumed если 1m low пробил fvg.bottom в окне.
    SHORT FVG consumed если 1m high пробил fvg.top.
    """
    if df_1m is None:
        return False  # без 1m данных пропускаем условие (как в spec — production canon)
    window = df_1m[(df_1m.index >= fvg_c3_close_time) & (df_1m.index < fractal_confirmation_time)]
    if window.empty:
        return False
    if fvg.direction == "LONG":
        return float(window["low"].min()) < fvg.bottom
    return float(window["high"].max()) > fvg.top


# ============================================================
# OB_VC — главный детектор (9 канонов)
# ============================================================

@dataclass
class OBVC:
    """Композитный элемент ob_vc."""
    direction: str
    ob: OBZone
    fvg: FVGZone
    zone_bottom: float  # = ob.bottom
    zone_top: float     # = ob.top
    htf_label: str      # "1h" или "2h"
    ltf_label: str      # "15m" или "20m"
    fractal_confirmation_time: pd.Timestamp
    fvg_tf_minutes: int


def detect_ob_vc(
    ob: OBZone,
    df_htf: pd.DataFrame,
    df_ltf: pd.DataFrame,
    htf_label: str,
    ltf_label: str,
    fvg_tf_minutes: int,
    df_1m: pd.DataFrame | None = None,
    n_fractal: int = 2,
) -> OBVC | None:
    """Найти первый валидный ob_vc для данной HTF OB, проверив все 9 канонов.

    Args:
      ob: HTF OB (на 1h или 2h)
      df_htf: HTF frame (где живёт ob)
      df_ltf: LTF frame (где ищем FVG)
      htf_label: "1h" | "2h"
      ltf_label: "15m" | "20m"
      fvg_tf_minutes: 15 или 20
      df_1m: 1m frame для условия #9 (если None — условие #9 пропускается)
      n_fractal: Williams N (по канону = 2)
    """
    # === Условие #1: sonap (sonapравленность) — implicit для OB
    # (мы возвращаем только FVG того же direction что и OB ниже)

    # === Условие #2: HTF OB существует — гарантировано caller'ом

    # === Подготовка для #5, #8: first Williams FH/FL за пределами drop/rally area
    if ob.direction == "LONG":
        fractal_result = _first_williams_fl_below(df_htf, ob, n_fractal)
    else:
        fractal_result = _first_williams_fh_above(df_htf, ob, n_fractal)
    if fractal_result is None:
        # Нет фрактала — невозможно проверить #5/#8/#9
        return None
    fractal_idx, fractal_extreme, fractal_confirmation_time = fractal_result

    # === Условие #4: drop/rally area для spatial overlap check
    drop_low, drop_high = _drop_or_rally_area(ob, df_htf)

    # === Поиск FVG на LTF в окне [ob.cur_time, fractal_confirmation_time]
    # Условие #7: fvg.c1.open_time >= ob.cur_time → c0 (= c1 в Vadim canon) тоже после
    # Условие #8: fvg.c3.close_time <= fractal_confirmation_time
    #   fvg.c3 = c2_time + tf_minutes (close of 3rd candle)
    fvg_search_start = ob.cur_time
    fvg_search_end = fractal_confirmation_time

    df_window = df_ltf[(df_ltf.index >= fvg_search_start) & (df_ltf.index <= fvg_search_end)]
    if len(df_window) < 3:
        return None

    for k in range(2, len(df_window)):
        f = detect_fvg(df_window, k)
        if f is None:
            continue
        # === Условие #1 (sonap)
        if f.direction != ob.direction:
            continue
        # c1 = первая свеча FVG (i-2 у нас = c0 == c1 в Vadim canon: первая)
        # c3.close_time = c2_time + tf
        c3_close_time = f.c2_time + pd.Timedelta(minutes=fvg_tf_minutes)

        # === Условие #7: fvg.c1.open_time >= ob.cur_time
        # (у нас c0_time = c1 в Vadim'овской нумерации)
        if f.c0_time < ob.cur_time:
            continue

        # === Условие #8: fvg.c3.close_time <= fractal_confirmation_time
        if c3_close_time > fractal_confirmation_time:
            continue

        # === Условие #4: spatial overlap FVG с drop/rally area (хотя бы частично)
        if not (f.bottom < drop_high and f.top > drop_low):
            continue

        # === Условие #5: FVG ⊆ [low_ob_vc, first_fractal_extreme]
        # LONG: fractal_extreme — это FL.low (нижняя граница диапазона)
        #   FVG.zone должна быть в [ob.bottom, что-то выше] — точнее ⊆ ob.zone от fractal_extreme до ob.top
        #   Vadim canon: "FVG.zone ⊆ [low_ob_vc, first_FH/FL.extreme]"
        #   low_ob_vc = ob.bottom для LONG. first_FL.extreme = ниже ob.bottom → FVG должна быть выше fractal_extreme
        if ob.direction == "LONG":
            if f.bottom < fractal_extreme or f.top > ob.top:
                continue
        else:
            # SHORT: low_ob_vc = ob.top. first_FH.extreme = выше ob.top → FVG должна быть ниже fractal_extreme
            if f.top > fractal_extreme or f.bottom < ob.bottom:
                continue

        # === Условие #9: FVG не consumed на 1m в окне [c3.close, fractal.confirmation]
        if df_1m is not None:
            if _fvg_consumed_on_1m(df_1m, f, c3_close_time, fractal_confirmation_time):
                continue

        # Все 9 канонов пройдены
        return OBVC(
            direction=ob.direction,
            ob=ob,
            fvg=f,
            zone_bottom=ob.bottom,
            zone_top=ob.top,
            htf_label=htf_label,
            ltf_label=ltf_label,
            fractal_confirmation_time=fractal_confirmation_time,
            fvg_tf_minutes=fvg_tf_minutes,
        )
    return None


# ============================================================
# CASCADE — v2: 1.1.1 with ob_vc replacement
# ============================================================

def detect_signals_111_v2(
    df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
    df_1m: pd.DataFrame | None = None,
) -> list[dict]:
    """Strategy 1.1.1 cascade v2 с ob_vc заменой L3+L4.

    Cascade:
      L1: OB-{1d, 12h}                     — top-OB (как в v1)
      L2: FVG-{4h, 6h} macro               — как в v1
      L3+L4: ob_vc(HTF={1h,2h}, LTF={15m,20m})  — единый композит с 9 канонами
             заменяет старые L3 (OB-htf+SWEPT) и L4 (FVG-entry)
    """
    signals: list[dict] = []

    def _scan(df_top, top_tf_hours, top_label):
        if df_top is None or df_top.empty:
            return
        for idx in range(1, len(df_top)):
            ob_top = detect_ob_pair(df_top, idx)
            if ob_top is None:
                continue
            valid_4h = collect_valid_macro_fvgs(df_4h, ob_top, htf_hours=4, top_tf_hours=top_tf_hours)
            valid_6h = collect_valid_macro_fvgs(df_6h, ob_top, htf_hours=6, top_tf_hours=top_tf_hours)
            for fvg_macro, macro_tf in [(f, "4h") for f in valid_4h] + [(f, "6h") for f in valid_6h]:
                search_start = ob_top.cur_time + pd.Timedelta(hours=top_tf_hours)

                # Для ob_vc мы итерируем по HTF={1h, 2h} и LTF={15m, 20m}
                for df_htf, htf_label, htf_hours in [(df_1h, "1h", 1), (df_2h, "2h", 2)]:
                    dfw_htf = df_htf[(df_htf.index >= search_start)]
                    if len(dfw_htf) < 3:
                        continue
                    # Итерируем по всем OB на HTF (внутри L2 macro FVG и L1 top-OB)
                    for i in range(1, len(dfw_htf)):
                        cand_ob = detect_ob_pair(dfw_htf, i)
                        if cand_ob is None or cand_ob.direction != ob_top.direction:
                            continue
                        # OB должен пересекаться с L2 FVG macro и L1 top OB
                        if not (cand_ob.top >= fvg_macro.bottom and cand_ob.bottom <= fvg_macro.top):
                            continue
                        if not (cand_ob.top >= ob_top.bottom and cand_ob.bottom <= ob_top.top):
                            continue

                        # Применяем ob_vc detection с двумя LTF вариантами
                        for df_ltf, ltf_label, tf_min in [(df_15m, "15m", 15), (df_20m, "20m", 20)]:
                            ob_vc = detect_ob_vc(
                                ob=cand_ob,
                                df_htf=dfw_htf,
                                df_ltf=df_ltf,
                                htf_label=htf_label,
                                ltf_label=ltf_label,
                                fvg_tf_minutes=tf_min,
                                df_1m=df_1m,
                                n_fractal=2,
                            )
                            if ob_vc is None:
                                continue

                            signal_time = ob_vc.fvg.c2_time
                            signals.append({
                                "direction": ob_top.direction,
                                "signal_time": signal_time,
                                "top_tf": top_label,
                                "ob_d_cur_time": ob_top.cur_time,
                                "ob_d_zone": (ob_top.bottom, ob_top.top),
                                "fvg_macro_tf": macro_tf,
                                "fvg_macro_zone": (fvg_macro.bottom, fvg_macro.top),
                                # ob_vc parts (replaces ob_htf + fvg_entry from v1)
                                "ob_htf_tf": ob_vc.htf_label,
                                "ob_htf_prev_time": ob_vc.ob.prev_time,
                                "ob_htf_cur_time": ob_vc.ob.cur_time,
                                "ob_htf_zone": (ob_vc.ob.bottom, ob_vc.ob.top),
                                "fvg_tf": ob_vc.ltf_label,
                                "fvg_c2_time": ob_vc.fvg.c2_time,
                                "fvg_zone": (ob_vc.fvg.bottom, ob_vc.fvg.top),
                                # ob_vc-specific meta
                                "ob_vc_fractal_confirmation": ob_vc.fractal_confirmation_time,
                                "version": "v2_ob_vc",
                            })
                            # Один ob_vc на HTF OB достаточно (берём первый валидный LTF)
                            break

    _scan(df_1d, 24, "1d")
    _scan(df_12h, 12, "12h")
    return signals


# ============================================================
# ENTRY / SL builder — те же формулы что в v1
# ============================================================

def build_entry_sl(sig: dict) -> tuple[float, float] | None:
    """Approved live formula (как в v1, использует ob_vc.ob.zone + ob_vc.fvg.zone):
        entry = fvg_bottom + 0.80 × (fvg_top - fvg_bottom)
        sl    = ob_htf_bottom + 0.35 × (fvg_bottom - ob_htf_bottom)
    """
    direction = sig["direction"]
    fb, ft = sig["fvg_zone"]
    obb, obt = sig["ob_htf_zone"]
    fw = ft - fb
    if direction == "LONG":
        entry = fb + ENTRY_PCT * fw
        sl = obb + SL_PCT * (fb - obb)
        if sl >= entry:
            return None
    else:
        entry = ft - ENTRY_PCT * fw
        sl = obt - SL_PCT * (obt - ft)
        if sl <= entry:
            return None
    return float(entry), float(sl)


# ============================================================
# Runner v2 (no SWEPT — заменён 9 канонами ob_vc)
# ============================================================

def run_symbol_backtest_v2(
    symbol: str,
    df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m, df_1m,
) -> list[dict]:
    """End-to-end v2: detect (с ob_vc) → score → simulate floating.

    БЕЗ check_swept — 9 канонов ob_vc уже включают аналог (фрактал-bound + temporal +
    consumption check). Все остальное — идентично v1.
    """
    cfg = FLOATING_TP_CONFIG[symbol]
    signals = detect_signals_111_v2(df_1d, df_12h, df_4h, df_6h, df_1h, df_2h,
                                     df_15m, df_20m, df_1m=df_1m)
    score_long, score_short = build_score_series(df_1h)

    trades = []
    for sig in signals:
        # Используем v1 simulate_floating с теми же per-symbol configs
        result = simulate_floating(
            sig, df_1m, df_1h, score_long, score_short,
            R_cap=cfg["R_cap"],
            threshold=cfg["threshold"],
            confirm=cfg["confirm"],
        )
        if result is None:
            continue
        trades.append({
            **sig,
            "outcome": result.outcome,
            "R": result.R,
            "exit_time": result.exit_time,
            "exit_reason": result.exit_reason,
            "hold_h": result.hold_h,
            "max_R": result.max_R,
        })
    return trades
