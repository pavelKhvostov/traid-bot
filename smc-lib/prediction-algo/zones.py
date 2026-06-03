"""
Zone snapshot @ cut-off — детекция всех активных зон интереса на момент cut_off_ts.

Phase 1 покрывает три модели mitigation (по одному примеру каждой):
  - OB (wick-fill, 2 свечи)
  - FVG (wick-fill, 3 свечи)
  - Fractal (sweep, точечный уровень)
  - RB (first-touch, 1 свеча)
  - Marubozu (sweep на open level, 1 свеча — dual zone)

Архитектура:
  1. resample 1m → нужные TF
  2. для каждой TF и типа: scan bars → list ZoneEvent
  3. для каждого ZoneEvent: forward-walk до cut-off, применить mitigation → ActiveZone | None
  4. собрать все активные зоны с фичами

Дизайн оптимизирован под понимаемость и тестируемость, не под скорость.
Brute-force брут per cut-off. Optimization (precompute timelines) откладывается на Phase 5.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal

import pandas as pd

# Подключаем smc-lib к sys.path (env SMCLIB_ROOT для portable-режима)
SMC_LIB = Path(os.environ.get("SMCLIB_ROOT", str(Path.home() / "smc-lib")))
sys.path.insert(0, str(SMC_LIB))

from candle import Candle  # noqa: E402
from elements.ob.code import detect_ob  # noqa: E402
from elements.fvg.code import detect_fvg  # noqa: E402
from elements.fractal.code import detect_fractal  # noqa: E402
from elements.rb.code import detect_rb  # noqa: E402
from elements.marubozu.code import detect_marubozu  # noqa: E402
from elements.block_orders.code import detect_block_orders  # noqa: E402
from elements.rdrb.code import detect_rdrb  # noqa: E402
from elements.i_rdrb.code import detect_i_rdrb  # noqa: E402
from elements.i_fvg.code import detect_i_fvg  # noqa: E402
from elements.ob_liq.code import detect_ob_liq  # noqa: E402
from elements.ob_vc.code import detect_ob_vc, HTF_TO_LTF as OB_VC_HTF_TO_LTF  # noqa: E402

from resample import resample_many, tf_to_timedelta  # noqa: E402


ZoneType = Literal[
    "OB", "FVG", "fractal", "marubozu",
    "block_orders", "RDRB", "iRDRB", "iFVG", "ob_liq", "ob_vc",
    # SKIP as prediction target:
    #   ob_sweep_liq_4candles — retrospective event, not forward-looking zone (feature only)
    #   RB — исключён 2026-05-29 решением пользователя (детектор остаётся, но не в ALL_TYPES)
]
ALL_TYPES: tuple[ZoneType, ...] = (
    "OB", "FVG", "fractal", "marubozu",
    "block_orders", "RDRB", "iRDRB", "iFVG", "ob_liq", "ob_vc",
)
PHASE1_TYPES: tuple[ZoneType, ...] = ("OB", "FVG", "fractal", "marubozu")


@dataclass(frozen=True)
class ActiveZone:
    """Активная зона интереса в момент cut-off."""
    tf: str
    type: str
    direction: str          # 'long'/'short' для range zones; 'high'/'low' для fractal; 'top'/'bottom' для RB
    lo: float               # текущая нижняя граница (после wick-fill)
    hi: float               # текущая верхняя граница
    level: float | None     # для fractal или marubozu open-magnet
    born_ts: pd.Timestamp   # время рождения зоны (open_time подтверждающей свечи)
    age_bars: int           # сколько баров TF прошло с born_ts до cut_off
    side: str               # 'above' / 'below' / 'inside' относительно текущей цены
    distance_pct: float     # дистанция до ближайшей границы зоны в % от цены
    mitigation_model: str   # 'wick-fill' | 'first-touch' | 'sweep'
    extras: dict = field(default_factory=dict)


def df_to_candles(df: pd.DataFrame) -> list[Candle]:
    """DataFrame → list[Candle]. open_time = ms since epoch UTC."""
    out: list[Candle] = []
    for ts, row in df.iterrows():
        out.append(Candle(
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            open_time=int(ts.value // 1_000_000),  # ns → ms
        ))
    return out


# ─────────────────────────────────────────────────────────────
# Mitigation models
# ─────────────────────────────────────────────────────────────

def _mit_wick_fill_long(zone_lo: float, zone_hi: float, bar_low: float) -> tuple[float, float] | None:
    """LONG-зона (support снизу). bar wick → сжатие.
    Returns: (new_lo, new_hi) или None если CONSUMED."""
    if bar_low > zone_hi:
        return zone_lo, zone_hi
    if bar_low <= zone_lo:
        return None  # consumed
    return zone_lo, bar_low


def _mit_wick_fill_short(zone_lo: float, zone_hi: float, bar_high: float) -> tuple[float, float] | None:
    """SHORT-зона (resistance сверху). bar wick → сжатие."""
    if bar_high < zone_lo:
        return zone_lo, zone_hi
    if bar_high >= zone_hi:
        return None  # consumed
    return bar_high, zone_hi


def _mit_first_touch(zone_lo: float, zone_hi: float, bar_low: float, bar_high: float) -> bool:
    """True если любое касание wick'ом зоны → consumed."""
    return bar_high >= zone_lo and bar_low <= zone_hi


def _mit_sweep_high(level: float, bar_high: float) -> bool:
    """FH swept: bar_high > level."""
    return bar_high > level


def _mit_sweep_low(level: float, bar_low: float) -> bool:
    """FL swept: bar_low < level."""
    return bar_low < level


def _mit_sweep_open_marubozu(open_level: float, direction: str, bar_low: float, bar_high: float) -> bool:
    """Marubozu open-level sweep. LONG (bull marubozu, open=low): low ≤ open. SHORT: high ≥ open."""
    if direction == "long":
        return bar_low <= open_level
    if direction == "short":
        return bar_high >= open_level
    return False


# ─────────────────────────────────────────────────────────────
# Per-type scanners — возвращают list of "raw zone events" с born_idx
# ─────────────────────────────────────────────────────────────

def _scan_ob(df: pd.DataFrame) -> list[dict]:
    """Скан OB. Born_idx = индекс cur (вторая свеча).
    Возвращает {direction, lo, hi, born_idx} для каждой найденной зоны."""
    out = []
    for i in range(1, len(df)):
        prev = Candle(df["open"].iloc[i-1], df["high"].iloc[i-1], df["low"].iloc[i-1], df["close"].iloc[i-1])
        cur = Candle(df["open"].iloc[i], df["high"].iloc[i], df["low"].iloc[i], df["close"].iloc[i])
        ob = detect_ob(prev, cur)
        if ob is None:
            continue
        out.append({"type": "OB", "direction": ob.direction, "lo": ob.zone[0], "hi": ob.zone[1], "born_idx": i, "mit": "wick-fill"})
    return out


def _scan_fvg(df: pd.DataFrame) -> list[dict]:
    """Скан FVG. Born_idx = индекс c3 (третья свеча — когда гэп подтверждён)."""
    out = []
    for i in range(2, len(df)):
        c1 = Candle(df["open"].iloc[i-2], df["high"].iloc[i-2], df["low"].iloc[i-2], df["close"].iloc[i-2])
        c2 = Candle(df["open"].iloc[i-1], df["high"].iloc[i-1], df["low"].iloc[i-1], df["close"].iloc[i-1])
        c3 = Candle(df["open"].iloc[i], df["high"].iloc[i], df["low"].iloc[i], df["close"].iloc[i])
        fvg = detect_fvg(c1, c2, c3)
        if fvg is None:
            continue
        out.append({"type": "FVG", "direction": fvg.direction, "lo": fvg.zone[0], "hi": fvg.zone[1], "born_idx": i, "mit": "wick-fill"})
    return out


def _scan_fractal(df: pd.DataFrame, n: int = 2) -> list[dict]:
    """Скан Williams fractal с N=2 (5-bar). Born_idx = индекс center + N (подтверждается после N бар вправо)."""
    out = []
    win = 2 * n + 1
    for i in range(win - 1, len(df)):
        candles = [
            Candle(df["open"].iloc[i-win+1+k], df["high"].iloc[i-win+1+k], df["low"].iloc[i-win+1+k], df["close"].iloc[i-win+1+k])
            for k in range(win)
        ]
        fr = detect_fractal(candles, n=n)
        if fr is None:
            continue
        # center был на индексе (i - n). Зона подтверждается на bar i (после N бар вправо).
        out.append({
            "type": "fractal",
            "direction": fr.direction,         # 'high' or 'low'
            "lo": fr.level, "hi": fr.level,    # точка как degenerate interval
            "level": fr.level,
            "born_idx": i,                     # confirmation bar
            "center_idx": i - n,
            "mit": "sweep",
        })
    return out


def _scan_rb(df: pd.DataFrame) -> list[dict]:
    """Скан RB. Born_idx = индекс самой свечи."""
    out = []
    for i in range(len(df)):
        c = Candle(df["open"].iloc[i], df["high"].iloc[i], df["low"].iloc[i], df["close"].iloc[i])
        rb = detect_rb(c)
        if rb is None:
            continue
        out.append({"type": "RB", "direction": rb.direction, "lo": rb.zone[0], "hi": rb.zone[1], "born_idx": i, "mit": "first-touch"})
    return out


def _scan_marubozu(df: pd.DataFrame) -> list[dict]:
    """Скан Marubozu. Born_idx = индекс свечи. Уровень open (магнит) сохраняем в level."""
    out = []
    for i in range(len(df)):
        c = Candle(df["open"].iloc[i], df["high"].iloc[i], df["low"].iloc[i], df["close"].iloc[i])
        m = detect_marubozu(c)
        if m is None:
            continue
        out.append({
            "type": "marubozu",
            "direction": m.direction,
            "lo": m.zone[0], "hi": m.zone[1],
            "level": m.candle.open,     # open-level = точечный магнит
            "born_idx": i,
            "mit": "sweep-open",         # special: sweep open level не зону
        })
    return out


def _row_to_candle(df: pd.DataFrame, i: int) -> Candle:
    return Candle(
        float(df["open"].iloc[i]), float(df["high"].iloc[i]),
        float(df["low"].iloc[i]), float(df["close"].iloc[i]),
    )


def _scan_block_orders(df: pd.DataFrame, max_window: int = 20) -> list[dict]:
    """Скан block_orders. born_idx = индекс последней counter-свечи (first close-cross).
    Используем форвард окно max_window для каждой начальной точки preceding.
    """
    out = []
    n = len(df)
    for i in range(n - 2):
        end = min(i + max_window, n)
        candles = [_row_to_candle(df, j) for j in range(i, end)]
        bl = detect_block_orders(candles)
        if bl is None:
            continue
        # born_idx = i (preceding) + 1 (initial #1) + n_initial + n_counter - 1 (last counter bar)
        born = i + 1 + bl.n_initial + bl.n_counter - 1
        out.append({"type": "block_orders", "direction": bl.direction, "lo": bl.zone[0], "hi": bl.zone[1], "born_idx": born, "mit": "wick-fill"})
    return out


def _scan_rdrb(df: pd.DataFrame) -> list[dict]:
    """Скан RDRB. POI используется как zone. born_idx = индекс c3."""
    out = []
    for i in range(2, len(df)):
        c1 = _row_to_candle(df, i-2)
        c2 = _row_to_candle(df, i-1)
        c3 = _row_to_candle(df, i)
        r = detect_rdrb(c1, c2, c3)
        if r is None:
            continue
        out.append({"type": "RDRB", "direction": r.direction, "lo": r.poi[0], "hi": r.poi[1], "born_idx": i, "mit": "wick-fill", "variant": r.variant})
    return out


def _scan_i_rdrb(df: pd.DataFrame) -> list[dict]:
    """Скан i-RDRB. POI наследуется от underlying RDRB. born_idx = индекс c4."""
    out = []
    for i in range(3, len(df)):
        c1 = _row_to_candle(df, i-3)
        c2 = _row_to_candle(df, i-2)
        c3 = _row_to_candle(df, i-1)
        c4 = _row_to_candle(df, i)
        ir = detect_i_rdrb(c1, c2, c3, c4)
        if ir is None:
            continue
        # POI наследуется от underlying RDRB
        out.append({"type": "iRDRB", "direction": ir.direction, "lo": ir.rdrb.poi[0], "hi": ir.rdrb.poi[1], "born_idx": i, "mit": "wick-fill"})
    return out


def _scan_i_fvg(df: pd.DataFrame, max_gap: int = 30) -> list[dict]:
    """Скан i-FVG.
    Идея: пробежать по всем FVG-A, и для каждой искать FVG-B opposite direction в окне max_gap.
    Условия проверяет detect_i_fvg (untouched between, B-touches-A, overlap).
    born_idx = индекс B.c3.
    """
    # Сначала найдём ВСЕ FVG в df с их позициями.
    fvgs: list[tuple[int, object]] = []  # (idx_of_c3, FVG)
    for i in range(2, len(df)):
        c1 = _row_to_candle(df, i-2); c2 = _row_to_candle(df, i-1); c3 = _row_to_candle(df, i)
        f = detect_fvg(c1, c2, c3)
        if f is not None:
            fvgs.append((i, f))

    out = []
    # Для каждой пары (A, B): A.c3_idx = ai, B.c3_idx = bi, ai < bi
    for k_a, (ai, a) in enumerate(fvgs):
        for bi, b in fvgs[k_a+1:]:
            if bi - ai > max_gap:
                break  # слишком далеко
            if b.direction == a.direction:
                continue
            # ai = A.c3 index. B.c1 index = bi-2. between = (ai, bi-2) exclusive endpoints inclusive of bars STRICTLY между A.c3 и B.c1.
            between_start = ai + 1
            between_end = bi - 2  # B.c1 находится на bi-2
            if between_start > between_end:
                continue  # B сразу за A — нет между
            between_candles = [_row_to_candle(df, j) for j in range(between_start, between_end + 1)]
            a_c1 = _row_to_candle(df, ai-2); a_c2 = _row_to_candle(df, ai-1); a_c3 = _row_to_candle(df, ai)
            b_c1 = _row_to_candle(df, bi-2); b_c2 = _row_to_candle(df, bi-1); b_c3 = _row_to_candle(df, bi)
            ifvg = detect_i_fvg(a_c1, a_c2, a_c3, between_candles, b_c1, b_c2, b_c3)
            if ifvg is None:
                continue
            out.append({"type": "iFVG", "direction": ifvg.direction, "lo": ifvg.overlap[0], "hi": ifvg.overlap[1], "born_idx": bi, "mit": "wick-fill"})
    return out


def _scan_ob_liq(df: pd.DataFrame) -> list[dict]:
    """Скан ob_liq. born_idx = индекс cur (вторая свеча). Mitigation = first-touch."""
    out = []
    for i in range(1, len(df)):
        prev = _row_to_candle(df, i-1)
        cur = _row_to_candle(df, i)
        ob = detect_ob_liq(prev, cur)
        if ob is None:
            continue
        out.append({"type": "ob_liq", "direction": ob.direction, "lo": ob.zone[0], "hi": ob.zone[1], "born_idx": i, "mit": "first-touch"})
    return out


_SCANNERS = {
    "OB": _scan_ob,
    "FVG": _scan_fvg,
    "fractal": _scan_fractal,
    "RB": _scan_rb,
    "marubozu": _scan_marubozu,
    "block_orders": _scan_block_orders,
    "RDRB": _scan_rdrb,
    "iRDRB": _scan_i_rdrb,
    "iFVG": _scan_i_fvg,
    "ob_liq": _scan_ob_liq,
    # "ob_vc" — cross-TF (HTF OB + LTF FVG + 1m); см. _scan_ob_vc_cross_tf
}


# ─────────────────────────────────────────────────────────────
# Cross-TF scanner для ob_vc (см. ~/smc-lib/elements/ob_vc/definition.md)
# ─────────────────────────────────────────────────────────────

def _scan_ob_vc_cross_tf(
    resampled: dict[str, pd.DataFrame],
    df_1m: pd.DataFrame,
    n_fractal: int = 2,
) -> dict[str, list[dict]]:
    """Scan ob_vc per канон #1-#9. Возвращает {htf_str: list[event]}.

    Каждый event = один ob_vc на (HTF OB, LTF). Zone = ob.zone (full ZoI per OB canon).
    Born_idx — по HTF (= ob.cur.born_idx). Mitigation = wick-fill (наследует от OB).
    """
    out: dict[str, list[dict]] = {}
    for htf, allowed_ltfs in OB_VC_HTF_TO_LTF.items():
        df_htf = resampled.get(htf)
        if df_htf is None or df_htf.empty:
            continue
        # Подготовить LTF candles + FVGs один раз per LTF
        ltf_all_candles: dict[str, list[Candle]] = {}
        ltf_all_fvgs: dict[str, list] = {}
        for ltf in allowed_ltfs:
            df_ltf = resampled.get(ltf)
            if df_ltf is None or df_ltf.empty:
                continue
            ltf_all_candles[ltf] = df_to_candles(df_ltf)
            fvgs = []
            cs = ltf_all_candles[ltf]
            for i in range(2, len(cs)):
                f = detect_fvg(cs[i - 2], cs[i - 1], cs[i])
                if f is not None:
                    fvgs.append(f)
            ltf_all_fvgs[ltf] = fvgs
        if not ltf_all_candles:
            continue
        htf_events: list[dict] = []
        # Iterate OB pairs in HTF
        for i in range(1, len(df_htf)):
            prev_row = df_htf.iloc[i - 1]
            cur_row = df_htf.iloc[i]
            prev_c = Candle(
                open=float(prev_row["open"]), high=float(prev_row["high"]),
                low=float(prev_row["low"]), close=float(prev_row["close"]),
                open_time=int(df_htf.index[i - 1].value // 1_000_000),
            )
            cur_c = Candle(
                open=float(cur_row["open"]), high=float(cur_row["high"]),
                low=float(cur_row["low"]), close=float(cur_row["close"]),
                open_time=int(df_htf.index[i].value // 1_000_000),
            )
            ob = detect_ob(prev_c, cur_c)
            if ob is None:
                continue
            ob_cur_ms = cur_c.open_time or 0
            # Bars after OB cur (включая cur) per LTF
            ltf_bars_after = {
                ltf: [c for c in ltf_all_candles[ltf] if (c.open_time or 0) >= ob_cur_ms]
                for ltf in ltf_all_candles
            }
            ob_vc = detect_ob_vc(
                ob,
                htf=htf,
                ltf_bars_after_ob=ltf_bars_after,
                ltf_fvgs=ltf_all_fvgs,
                n_fractal=n_fractal,
                df_1m=df_1m,
            )
            if ob_vc is None:
                continue
            htf_events.append({
                "type": "ob_vc",
                "direction": ob_vc.direction,
                "lo": ob.zone[0],
                "hi": ob.zone[1],
                "born_idx": i,
                "mit": "wick-fill",
                "n_fvg_components": len(ob_vc.fvg_components),
            })
        out[htf] = htf_events
    return out


# ─────────────────────────────────────────────────────────────
# Apply mitigation forward → ActiveZone or None
# ─────────────────────────────────────────────────────────────

def _apply_mitigation(zone_event: dict, df: pd.DataFrame, cut_off_idx: int) -> dict | None:
    """Применить per-zone mitigation rule вперёд от born_idx+1 до cut_off_idx-1.
    Returns: dict с обновлёнными {lo, hi, level, ...} или None если consumed.
    """
    mit = zone_event["mit"]
    lo, hi = zone_event["lo"], zone_event["hi"]
    direction = zone_event["direction"]
    level = zone_event.get("level")
    born = zone_event["born_idx"]

    # Bars между born (exclusive) и cut_off_idx (exclusive) — все закрытые после рождения и до cut-off
    if born + 1 >= cut_off_idx:
        # зона только что родилась, никаких миtigation bars
        return {"lo": lo, "hi": hi, "level": level}

    highs = df["high"].iloc[born+1:cut_off_idx].to_numpy()
    lows = df["low"].iloc[born+1:cut_off_idx].to_numpy()

    if mit == "wick-fill":
        for bh, bl in zip(highs, lows):
            if direction == "long":
                r = _mit_wick_fill_long(lo, hi, bl)
            else:
                r = _mit_wick_fill_short(lo, hi, bh)
            if r is None:
                return None
            lo, hi = r
        return {"lo": lo, "hi": hi, "level": level}

    if mit == "first-touch":
        for bh, bl in zip(highs, lows):
            if _mit_first_touch(lo, hi, bl, bh):
                return None
        return {"lo": lo, "hi": hi, "level": level}

    if mit == "sweep":
        # Fractal: direction = 'high'/'low'
        for bh, bl in zip(highs, lows):
            if direction == "high" and _mit_sweep_high(level, bh):
                return None
            if direction == "low" and _mit_sweep_low(level, bl):
                return None
        return {"lo": lo, "hi": hi, "level": level}

    if mit == "sweep-open":
        # Marubozu open level. После sweep'а — consumed (per [[feedback-marubozu-is-imbalance-not-support]]).
        for bh, bl in zip(highs, lows):
            if _mit_sweep_open_marubozu(level, direction, bl, bh):
                return None
        return {"lo": lo, "hi": hi, "level": level}

    raise ValueError(f"Unknown mitigation model: {mit}")


# ─────────────────────────────────────────────────────────────
# Public: zone_snapshot
# ─────────────────────────────────────────────────────────────

def _side_and_distance(lo: float, hi: float, price: float) -> tuple[str, float]:
    if price < lo:
        return "above", (lo - price) / price * 100
    if price > hi:
        return "below", (price - hi) / price * 100
    return "inside", 0.0


def _zones_for_tf(df_tf: pd.DataFrame, tf: str, types: Iterable[str], cut_off_ts: pd.Timestamp, price_now: float) -> list[ActiveZone]:
    """Снять snapshot активных зон для одного TF."""
    if df_tf.empty:
        return []

    # cut_off_idx = первый бар, индекс которого ≥ cut_off_ts. Все bars[< cut_off_idx] полностью закрыты ДО cut_off.
    # df_tf уже отфильтрован resampler'ом до closed bars — все bars действительны.
    cut_off_idx = len(df_tf)
    out: list[ActiveZone] = []

    for ztype in types:
        scanner = _SCANNERS.get(ztype)
        if scanner is None:
            continue
        for ev in scanner(df_tf):
            updated = _apply_mitigation(ev, df_tf, cut_off_idx)
            if updated is None:
                continue
            born_ts = df_tf.index[ev["born_idx"]]
            age_bars = cut_off_idx - ev["born_idx"] - 1
            side, dist_pct = _side_and_distance(updated["lo"], updated["hi"], price_now)
            extras = {}
            if ev["type"] == "fractal":
                extras["center_idx"] = ev["center_idx"]
            out.append(ActiveZone(
                tf=tf,
                type=ev["type"],
                direction=ev["direction"],
                lo=updated["lo"],
                hi=updated["hi"],
                level=updated.get("level"),
                born_ts=born_ts,
                age_bars=age_bars,
                side=side,
                distance_pct=dist_pct,
                mitigation_model=ev["mit"],
                extras=extras,
            ))
    return out


def precompute_zone_events(
    df_1m: pd.DataFrame,
    tfs: Iterable[str] = ("1h", "4h", "12h", "1d"),
    types: Iterable[str] = ALL_TYPES,
    end_ts: pd.Timestamp | None = None,
) -> tuple[dict[tuple[str, str], list[dict]], dict[str, pd.DataFrame]]:
    """
    Сканировать ВСЕ зоны ОДИН раз по полному диапазону данных.
    Возвращает: ((tf, type) → events) и (tf → resampled DataFrame).
    Эти структуры можно использовать с snapshot_from_events для быстрых
    повторяющихся snapshots на разных cut-offs.

    end_ts: ограничение сверху (по умолчанию = последняя 1m + 1 минута).
    """
    if end_ts is None:
        end_ts = df_1m.index[-1] + pd.Timedelta(minutes=1)
    resampled = resample_many(df_1m, tfs, end_ts)

    events_by_tf_type: dict[tuple[str, str], list[dict]] = {}
    for tf, df_tf in resampled.items():
        for ztype in types:
            scanner = _SCANNERS.get(ztype)
            if scanner is None:
                continue
            events = scanner(df_tf)
            # Привязываем born_ts из индекса df_tf
            for ev in events:
                ev["born_ts"] = df_tf.index[ev["born_idx"]]
            events_by_tf_type[(tf, ztype)] = events

    # Cross-TF scanner для ob_vc (если ob_vc в types)
    if "ob_vc" in types:
        # ob_vc требует LTF из таблицы HTF_TO_LTF + 1m для условия #9
        needed_ltfs = {ltf for ltfs in OB_VC_HTF_TO_LTF.values() for ltf in ltfs}
        missing_ltfs = needed_ltfs - set(resampled.keys())
        if missing_ltfs:
            # Дополнительный resample для недостающих LTF (нужны для детекции FVG/фракталов)
            from resample import resample_one
            for ltf in missing_ltfs:
                try:
                    resampled[ltf] = resample_one(df_1m, ltf, end_ts)
                except Exception:
                    continue
        ob_vc_per_htf = _scan_ob_vc_cross_tf(resampled, df_1m)
        for htf, events in ob_vc_per_htf.items():
            df_tf = resampled.get(htf)
            if df_tf is None:
                continue
            for ev in events:
                ev["born_ts"] = df_tf.index[ev["born_idx"]]
            events_by_tf_type[(htf, "ob_vc")] = events
    return events_by_tf_type, resampled


def snapshot_from_events(
    events_by_tf_type: dict[tuple[str, str], list[dict]],
    resampled: dict[str, pd.DataFrame],
    df_1m: pd.DataFrame,
    cut_off_ts: pd.Timestamp,
) -> list[ActiveZone]:
    """
    Снимок зон на cut_off_ts используя precomputed events.

    Для каждого события (зоны):
      - пропускаем если born_ts ≥ cut_off (не родилась к cut_off)
      - иначе применяем mitigation от born+1 до последнего закрытого TF-бара перед cut_off
    """
    df_1m_cut = df_1m.loc[df_1m.index < cut_off_ts]
    if df_1m_cut.empty:
        return []
    price_now = float(df_1m_cut["close"].iloc[-1])

    all_zones: list[ActiveZone] = []
    for (tf, ztype), events in events_by_tf_type.items():
        df_tf = resampled[tf]
        # cut_off_idx = количество TF-bars, у которых close_ts ≤ cut_off_ts
        tf_td = tf_to_timedelta(tf)
        # binary search to find cut_off_idx
        close_ts = df_tf.index + tf_td
        cut_off_idx = int((close_ts <= cut_off_ts).sum())
        if cut_off_idx == 0:
            continue

        for ev in events:
            if ev["born_idx"] >= cut_off_idx:
                continue  # зона ещё не родилась
            updated = _apply_mitigation(ev, df_tf, cut_off_idx)
            if updated is None:
                continue
            born_ts = ev["born_ts"]
            age_bars = cut_off_idx - ev["born_idx"] - 1
            side, dist_pct = _side_and_distance(updated["lo"], updated["hi"], price_now)
            extras = {}
            if ev["type"] == "fractal":
                extras["center_idx"] = ev["center_idx"]
            all_zones.append(ActiveZone(
                tf=tf, type=ev["type"], direction=ev["direction"],
                lo=updated["lo"], hi=updated["hi"], level=updated.get("level"),
                born_ts=born_ts, age_bars=age_bars,
                side=side, distance_pct=dist_pct,
                mitigation_model=ev["mit"],
                extras=extras,
            ))
    all_zones.sort(key=lambda z: z.distance_pct)
    return all_zones


def zone_snapshot(
    df_1m: pd.DataFrame,
    cut_off_ts: pd.Timestamp,
    tfs: Iterable[str] = ("1h", "4h", "12h", "1d"),
    types: Iterable[str] = PHASE1_TYPES,
) -> list[ActiveZone]:
    """
    Снять snapshot всех активных зон во всех TF на момент cut_off_ts.

    df_1m: 1m OHLCV (UTC DatetimeIndex)
    cut_off_ts: момент прогноза (UTC tz-aware)
    tfs: список TF для сканирования
    types: список zone types

    Returns: список ActiveZone, отсортированный по distance_pct (ближайшие первые).
    """
    resampled = resample_many(df_1m, tfs, cut_off_ts)
    # Цена сейчас = close последней закрытой 1m свечи до cut_off
    df_1m_cut = df_1m.loc[df_1m.index < cut_off_ts]
    if df_1m_cut.empty:
        return []
    price_now = float(df_1m_cut["close"].iloc[-1])

    all_zones: list[ActiveZone] = []
    for tf, df_tf in resampled.items():
        all_zones.extend(_zones_for_tf(df_tf, tf, types, cut_off_ts, price_now))

    all_zones.sort(key=lambda z: z.distance_pct)
    return all_zones
