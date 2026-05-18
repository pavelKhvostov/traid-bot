"""Strategy 1.1.6: FVG-{1d,12h} + OB-{4h,6h} → FVG-{1h,2h}, entry на htf-FVG.

Параллельная ветка к 1.1.1/1.1.2/1.1.3 с инвертированной структурой каскада:

  1.1.1:  OB-top   → FVG-macro → OB-htf  → FVG-entry (младший ТФ)
  1.1.6:  FVG-top  → OB-macro  → FVG-htf (entry прямо на htf-FVG)

Геометрия:
  TOP    = FVG на 1d/12h, обе ветки параллельно. Wick-инвалидация в окне
           [c2_close, search_start_for_macro_OB].
  MACRO  = первый валидный OB на 4h/6h после top-FVG (earliest-wins),
           zones_overlap с top-FVG (partial), направление совпадает.
  HTF    = первый валидный FVG на 1h/2h (earliest-wins по c2_time),
           zones_overlap с ob_macro AND с fvg_top, без SWEPT-фильтра.

Entry/SL/TP:
  entry  = mid htf-FVG = (htf_fvg.bottom + htf_fvg.top) / 2
  sl     = ob_macro.bottom (LONG) / ob_macro.top (SHORT)
  tp     = entry ± risk × 1.0  (RR=1.0 фиксированный)
  risk   = abs(entry - sl)

Все atomic-хелперы (detect_ob_pair, detect_fvg, zones_overlap, OBZone, FVGZone)
импортируются из 1.1.1 — это canon, при изменении canon обновляются обе.
"""
from __future__ import annotations

import pandas as pd

from strategies.strategy_1_1_1 import (
    FVGZone,
    OBZone,
    detect_fvg,
    detect_ob_pair,
    zones_overlap,
)

# RR фиксированный по спеке 1.1.6. Единственная точка изменения, если позже
# захочется 3-stage optimize с vary RR.
RR = 1.0


def collect_valid_top_fvgs(
    df_top: pd.DataFrame,
    top_tf_hours: int,
) -> list[FVGZone]:
    """Все FVG на top-ТФ (1d или 12h), оба направления.

    Возвращаем как есть — wick-инвалидация проверяется ПОЗЖЕ, в окне
    [c2_close, search_start_for_macro_OB], потому что верхняя граница
    окна определяется только при поиске macro-OB.
    """
    if df_top is None or df_top.empty or len(df_top) < 3:
        return []
    fvgs: list[FVGZone] = []
    for j in range(2, len(df_top)):
        f = detect_fvg(df_top, j)
        if f is not None:
            fvgs.append(f)
    return fvgs


def find_first_macro_ob_for_top_fvg(
    df_macro: pd.DataFrame,
    fvg_top: FVGZone,
    htf_hours: int,
    top_tf_hours: int,
) -> tuple[OBZone, pd.Timestamp] | None:
    """Первый валидный OB-macro после top-FVG с проверкой wick-инвалидации.

    Поиск стартует с момента закрытия c2 свечи top-FVG:
      search_start = fvg_top.c2_time + top_tf_hours

    Earliest-wins: возвращается ПЕРВЫЙ валидный OB-macro. Один macro на одну
    top-FVG — снижает raw count и исключает кейс «разные macro на одной
    структуре» (см. 2026-02-06 в 1.1.1).

    Wick-инвалидация top-FVG проверяется на df_macro в окне
    [search_start, ob_macro.cur_close). Аналогично 1.1.1
    collect_valid_macro_fvgs: invalidation на свечах того же ТФ что и
    candidate — там видно реальное движение цены внутри top-бара. df_top
    1d/12h слишком крупный, между search_start и ob.cur_close может
    оказаться 0 баров — поэтому df_top в этой функции не нужен. Single
    wick в зоне FVG = invalid:
      LONG  top-FVG: low < fvg_top.bottom
      SHORT top-FVG: high > fvg_top.top
    Если на момент кандидата macro_ob top-FVG уже инвалидирована —
    кандидат отбрасывается, поиск останавливается (структура мертва).

    Validity OB-macro:
      - Направление совпадает с top-FVG
      - zones_overlap(ob_macro, fvg_top) — partial overlap (НЕ внутри)
    """
    search_start = fvg_top.c2_time + pd.Timedelta(hours=top_tf_hours)
    df_window = df_macro[df_macro.index >= search_start]
    if len(df_window) < 2:
        return None

    direction = fvg_top.direction
    fvg_top_bottom = fvg_top.bottom
    fvg_top_top = fvg_top.top

    for j in range(1, len(df_window)):
        ob = detect_ob_pair(df_window, j)
        if ob is None or ob.direction != direction:
            continue
        if not zones_overlap(ob.bottom, ob.top, fvg_top_bottom, fvg_top_top):
            continue

        # Проверка wick-инвалидации top-FVG в окне [search_start, ob.cur_close).
        # ob.cur_close = ob.cur_time + htf_hours. Проверяем на df_macro
        # (а не df_top), потому что df_top 1d/12h слишком крупный — между
        # search_start и ob.cur_close может быть 0 баров. df_macro даёт
        # реальное движение цены внутри top-бара. Соответствует подходу
        # 1.1.1 collect_valid_macro_fvgs (invalidation на ТФ candidate'а).
        ob_cur_close = ob.cur_time + pd.Timedelta(hours=htf_hours)
        df_inval = df_macro[
            (df_macro.index >= search_start) & (df_macro.index < ob_cur_close)
        ]
        invalidated = False
        for _, row in df_inval.iterrows():
            if direction == "LONG" and float(row["low"]) < fvg_top_bottom:
                invalidated = True
                break
            if direction == "SHORT" and float(row["high"]) > fvg_top_top:
                invalidated = True
                break
        if invalidated:
            # Top-FVG умерла раньше, чем нашли macro. Других macro
            # для этой top-FVG искать не имеет смысла.
            return None

        return ob, search_start

    return None


def find_first_fvg_htf_in_zone(
    df_htf: pd.DataFrame,
    fvg_top: FVGZone,
    ob_macro: OBZone,
    search_start: pd.Timestamp,
    macro_hours: int,
    htf_label: str,
) -> FVGZone | None:
    """Первый FVG того же направления в зоне overlap top-FVG ∩ ob_macro.

    Окно поиска — после **закрытия cur-свечи macro-OB**, не после её
    open_time. Это критично: htf-реакция должна искаться только когда
    macro-OB уже сформирован как структура. На 14 февраля 2026 был
    конкретный кейс с lookahead'ом, где htf-FVG (1h) формировалась за
    3 часа ДО закрытия 6h-macro-OB.

    Без верхней границы — ищем первый по c2_time валидный FVG.

    Validity:
      - Направление совпадает с top-FVG / ob_macro
      - zones_overlap с ob_macro
      - zones_overlap с fvg_top
    """
    # Поиск стартует с момента ЗАКРЫТИЯ cur ob_macro:
    # cur_time + macro_hours (4 для 4h, 6 для 6h). НЕ + htf_hours —
    # это была грабля идентичная strategy-1-1-1-look-ahead-15min:
    # длительность бара должна выводиться из ТФ candidate-структуры,
    # не из ТФ поиска. Аналог 1.1.1: search_start = ob_top.cur_time
    # + top_tf_hours (длительность top-бара, не htf-бара).
    htf_start = ob_macro.cur_time + pd.Timedelta(hours=macro_hours)
    df_window = df_htf[df_htf.index >= htf_start]
    if len(df_window) < 3:
        return None

    direction = fvg_top.direction
    for k in range(2, len(df_window)):
        f = detect_fvg(df_window, k)
        if f is None or f.direction != direction:
            continue
        if not zones_overlap(f.bottom, f.top, ob_macro.bottom, ob_macro.top):
            continue
        if not zones_overlap(f.bottom, f.top, fvg_top.bottom, fvg_top.top):
            continue
        return f
    return None


def detect_strategy_1_1_6_signals(
    df_1d: pd.DataFrame,
    df_12h: pd.DataFrame,
    df_4h: pd.DataFrame,
    df_6h: pd.DataFrame,
    df_1h: pd.DataFrame,
    df_2h: pd.DataFrame,
    verbose: bool = False,
) -> list[dict]:
    """Сканирует FVG-1d И FVG-12h как параллельные top-уровни.

    Под каждым top-FVG ищется ПЕРВЫЙ macro-OB (4h ИЛИ 6h, earliest-wins).
    Под (top, macro) — первый htf-FVG (1h ИЛИ 2h, earliest-wins по c2_time).

    Возвращает list[dict]; backtest применит дедуп аналогично 1.1.1.
    """
    signals: list[dict] = []
    counters: dict[str, int] = {
        "fvg_top_1d": 0, "fvg_top_12h": 0,
        "macro_ob_4h": 0, "macro_ob_6h": 0,
        "chosen_htf_1h": 0, "chosen_htf_2h": 0,
        "chosen_macro_4h": 0, "chosen_macro_6h": 0,
        "chosen_top_1d": 0, "chosen_top_12h": 0,
    }

    def _scan_top(
        df_top: pd.DataFrame, top_tf_hours: int, top_label: str,
    ) -> None:
        if df_top is None or df_top.empty:
            return
        top_fvgs = collect_valid_top_fvgs(df_top, top_tf_hours)
        counters[f"fvg_top_{top_label}"] += len(top_fvgs)

        for fvg_top in top_fvgs:
            # Earliest-wins на macro: пробуем 4h и 6h, берём с более ранним
            # ob_macro.cur_time. Если оба None — пропускаем.
            macro_4h = find_first_macro_ob_for_top_fvg(
                df_4h, fvg_top, htf_hours=4, top_tf_hours=top_tf_hours,
            )
            macro_6h = find_first_macro_ob_for_top_fvg(
                df_6h, fvg_top, htf_hours=6, top_tf_hours=top_tf_hours,
            )
            if macro_4h is None and macro_6h is None:
                continue

            if macro_4h is not None:
                counters["macro_ob_4h"] += 1
            if macro_6h is not None:
                counters["macro_ob_6h"] += 1

            if macro_4h is None:
                ob_macro, search_start = macro_6h
                macro_tf = "6h"
            elif macro_6h is None:
                ob_macro, search_start = macro_4h
                macro_tf = "4h"
            else:
                # earliest по cur_close (cur_time + htf_hours): кто первым
                # стал известен в реал-тайме. 4h cur закрывается через 4h,
                # 6h — через 6h. При равных cur_time 4h "побеждает" по
                # реальности, не по open_time.
                ob_4h, ss_4h = macro_4h
                ob_6h, ss_6h = macro_6h
                close_4h = ob_4h.cur_time + pd.Timedelta(hours=4)
                close_6h = ob_6h.cur_time + pd.Timedelta(hours=6)
                if close_4h <= close_6h:
                    ob_macro, search_start, macro_tf = ob_4h, ss_4h, "4h"
                else:
                    ob_macro, search_start, macro_tf = ob_6h, ss_6h, "6h"

            # macro_hours для htf-search: 4 если macro=4h, 6 если 6h.
            # Используется в find_first_fvg_htf_in_zone как смещение
            # от ob_macro.cur_time до момента закрытия cur (= legitimate
            # старт поиска htf-FVG, иначе lookahead — см. кейс 14 фев 2026).
            macro_hours = 4 if macro_tf == "4h" else 6

            # Earliest-wins на htf: 1h и 2h независимо.
            htf_1h = find_first_fvg_htf_in_zone(
                df_1h, fvg_top, ob_macro, search_start, macro_hours, htf_label="1h",
            )
            htf_2h = find_first_fvg_htf_in_zone(
                df_2h, fvg_top, ob_macro, search_start, macro_hours, htf_label="2h",
            )
            if htf_1h is None and htf_2h is None:
                continue

            if htf_1h is None:
                fvg_htf, htf_tf = htf_2h, "2h"
            elif htf_2h is None:
                fvg_htf, htf_tf = htf_1h, "1h"
            else:
                # earliest по c2_close: 1h c2 закрывается через 1h, 2h — через 2h.
                # Для 1.1.1-style сравнение по c2_time достаточно (entry-FVG
                # 15m vs 20m — разница 5 мин). У нас разница 1h vs 2h = 100% —
                # учитываем явно.
                close_1h = htf_1h.c2_time + pd.Timedelta(hours=1)
                close_2h = htf_2h.c2_time + pd.Timedelta(hours=2)
                if close_1h <= close_2h:
                    fvg_htf, htf_tf = htf_1h, "1h"
                else:
                    fvg_htf, htf_tf = htf_2h, "2h"

            # Counters.
            counters[f"chosen_htf_{htf_tf}"] += 1
            counters[f"chosen_macro_{macro_tf}"] += 1
            counters[f"chosen_top_{top_label}"] += 1

            # Entry / SL / TP.
            entry = (fvg_htf.bottom + fvg_htf.top) / 2
            if fvg_top.direction == "LONG":
                sl = ob_macro.bottom
                risk = entry - sl
                tp = entry + risk * RR
            else:
                sl = ob_macro.top
                risk = sl - entry
                tp = entry - risk * RR
            if risk <= 0:
                continue

            # Intersection trio (top ∩ macro ∩ htf) — для отчётов/диагностики.
            inter_bottom = max(fvg_top.bottom, ob_macro.bottom, fvg_htf.bottom)
            inter_top = min(fvg_top.top, ob_macro.top, fvg_htf.top)

            signals.append({
                "direction": fvg_top.direction,
                "signal_time": fvg_htf.c2_time,
                "entry": float(entry),
                "sl": float(sl),
                "tp": float(tp),
                "risk": float(risk),

                # Top-уровень.
                "top_tf": top_label,
                "top_tf_hours": top_tf_hours,
                "top_fvg_c0_time": fvg_top.c0_time,
                "top_fvg_c2_time": fvg_top.c2_time,
                "top_fvg_zone": (fvg_top.bottom, fvg_top.top),

                # Macro-уровень.
                "macro_tf": macro_tf,
                "ob_macro_prev_time": ob_macro.prev_time,
                "ob_macro_cur_time": ob_macro.cur_time,
                "ob_macro_zone": (ob_macro.bottom, ob_macro.top),

                # HTF-уровень (= entry).
                "htf_tf": htf_tf,
                "htf_fvg_c0_time": fvg_htf.c0_time,
                "htf_fvg_c2_time": fvg_htf.c2_time,
                "htf_fvg_zone": (fvg_htf.bottom, fvg_htf.top),

                # Trio intersection (top ∩ macro ∩ htf).
                "intersection_zone": (inter_bottom, inter_top),
            })

    _scan_top(df_1d, 24, "1d")
    _scan_top(df_12h, 12, "12h")

    if verbose:
        print(
            f"[FUNNEL] FVG-top 1d: {counters['fvg_top_1d']}  "
            f"12h: {counters['fvg_top_12h']}"
        )
        print(
            f"  + macro-OB 4h: {counters['macro_ob_4h']}  "
            f"6h: {counters['macro_ob_6h']}"
        )
        print(f"  signals (raw, до dedup): {len(signals)}")
        print(f"      chosen top  1d: {counters['chosen_top_1d']}")
        print(f"      chosen top 12h: {counters['chosen_top_12h']}")
        print(f"      chosen macro 4h: {counters['chosen_macro_4h']}")
        print(f"      chosen macro 6h: {counters['chosen_macro_6h']}")
        print(f"      chosen htf  1h: {counters['chosen_htf_1h']}")
        print(f"      chosen htf  2h: {counters['chosen_htf_2h']}")
    return signals
