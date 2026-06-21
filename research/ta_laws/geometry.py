"""Геометрия паттернов ТА — примитивы для нейро-модуля «законов».

Детектит то, что глаз видит на графиках: импульс (флагшток) -> контртрендовая
коррекция (канал / клин / вымпел / треугольник) -> measured-move цель.
Чистая геометрия, без прогноза. Законы формируются ПОЗЖЕ валидатором на размеченных
исходах — здесь только надёжное распознавание форм.

Конвейер:
  1. zigzag(df) -> чередующиеся пивоты H/L (порог по ATR)
  2. find_impulses(pivots) -> сильные однонаправленные ноги (флагштоки)
  3. classify_correction(corr_pivots, impulse_dir) -> тип коррекции + линии + фичи
  4. find_archetypes(df) -> импульс + прикреплённая коррекция + measured-move TP

Все наклоны нормируются на ATR (масштабо-независимо).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# --- пороги (дефолты под формы с пользовательских графиков) ---
ATR_N = 14
ZZ_MULT = 1.8          # порог разворота зигзага в ATR
IMP_MIN_ATR = 3.5      # импульс >= 3.5 ATR по величине
IMP_MAX_BARS = 60      # импульс не длиннее N баров
IMP_MIN_EFF = 0.55     # эффективность ноги: |net| / gross
CORR_MIN_PIVOTS = 4    # >=2 H и >=2 L для двух линий
CORR_MAX_PIVOTS = 10
CORR_MAX_RETR = 1.0    # коррекция глубже 100% импульса = разворот (не флаг)
PARALLEL_TOL = 0.25    # |su-sl|/scale < tol -> параллельные (канал)
FLAT_TOL = 0.12        # |slope|/scale < tol -> «плоская» линия (для ASC/DESC треугольника)
EPS_AGAINST = 0.03     # наклон/ATR > eps -> коррекция имеет ЗНАК против/по импульсу
CONVERGE_RATIO = 0.72  # width_end < width_start*ratio -> сходящиеся


@dataclass
class Pivot:
    i: int                 # бар экстремума
    time: pd.Timestamp
    price: float
    kind: str              # "H" | "L"
    conf_i: int = -1       # бар ПОДТВЕРЖДЕНИЯ пивота (когда разворот превысил порог) — для каузальности


@dataclass
class Impulse:
    direction: str  # "UP" | "DOWN"
    i0: int
    i1: int
    t0: pd.Timestamp
    t1: pd.Timestamp
    p0: float
    p1: float
    bars: int
    magnitude: float       # |p1-p0|
    atr_mag: float         # magnitude / atr
    efficiency: float


@dataclass
class Correction:
    kind: str              # CHANNEL/FLAG/RISING_WEDGE/FALLING_WEDGE/PENNANT/ASC_TRI/DESC_TRI/UNCLEAR
    against_impulse: bool  # наклон коррекции против импульса (флаг-ловушка)
    slope_up: float        # наклон верхней линии (price/bar)
    slope_lo: float
    su_norm: float         # нормированные на ATR
    sl_norm: float
    converging: bool
    depth_pct: float       # глубина коррекции в % от импульса
    bars: int
    pivots: list = field(default_factory=list)
    upper: tuple = None    # (x0,y0,x1,y1) для отрисовки
    lower: tuple = None


@dataclass
class Archetype:
    impulse: Impulse
    correction: Correction
    measured_move_tp: float
    breakout_level: float
    continuation_dir: str  # = impulse.direction


def compute_atr(df: pd.DataFrame, n: int = ATR_N) -> np.ndarray:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean().bfill().to_numpy()


def zigzag(df: pd.DataFrame, atr_mult: float = ZZ_MULT, atr_n: int = ATR_N) -> list[Pivot]:
    """Чередующиеся пивоты H/L. Разворот подтверждается ходом atr_mult*ATR от экстремума."""
    atr = compute_atr(df, atr_n)
    h = df["high"].to_numpy(); l = df["low"].to_numpy(); c = df["close"].to_numpy()
    t = df.index
    n = len(df)
    if n < 3:
        return []
    piv: list[Pivot] = []
    trend = 0
    ext_p = c[0]; ext_i = 0
    for i in range(1, n):
        thr = atr_mult * atr[i]
        if thr <= 0:
            continue
        if trend > 0:
            if h[i] >= ext_p:
                ext_p = h[i]; ext_i = i
            elif l[i] <= ext_p - thr:
                piv.append(Pivot(ext_i, t[ext_i], float(ext_p), "H", conf_i=i))
                trend = -1; ext_p = l[i]; ext_i = i
        elif trend < 0:
            if l[i] <= ext_p:
                ext_p = l[i]; ext_i = i
            elif h[i] >= ext_p + thr:
                piv.append(Pivot(ext_i, t[ext_i], float(ext_p), "L", conf_i=i))
                trend = 1; ext_p = h[i]; ext_i = i
        else:  # trend == 0: ждём первый значимый ход
            if h[i] >= c[0] + thr:
                trend = 1; ext_p = h[i]; ext_i = i
            elif l[i] <= c[0] - thr:
                trend = -1; ext_p = l[i]; ext_i = i
    return piv


def _efficiency(df: pd.DataFrame, i0: int, i1: int) -> float:
    c = df["close"].to_numpy()[i0:i1 + 1]
    if len(c) < 2:
        return 0.0
    net = abs(c[-1] - c[0])
    gross = np.abs(np.diff(c)).sum()
    return float(net / gross) if gross > 0 else 0.0


def find_impulses(df: pd.DataFrame, pivots: list[Pivot], atr: np.ndarray) -> list[Impulse]:
    """Ноги пивот->пивот, проходящие как флагшток (величина+скорость+эффективность)."""
    out = []
    for k in range(len(pivots) - 1):
        a, b = pivots[k], pivots[k + 1]
        bars = b.i - a.i
        if bars <= 0 or bars > IMP_MAX_BARS:
            continue
        mag = abs(b.price - a.price)
        atr_here = atr[b.i] if atr[b.i] > 0 else np.nan
        if not (mag >= IMP_MIN_ATR * atr_here):
            continue
        eff = _efficiency(df, a.i, b.i)
        if eff < IMP_MIN_EFF:
            continue
        out.append(Impulse(
            direction="UP" if b.price > a.price else "DOWN",
            i0=a.i, i1=b.i, t0=a.time, t1=b.time, p0=a.price, p1=b.price,
            bars=bars, magnitude=mag, atr_mag=float(mag / atr_here), efficiency=eff))
    return out


def _fit(xs: list[float], ys: list[float]) -> float:
    """Наклон МНК price/bar. >=2 точки."""
    x = np.asarray(xs, float); y = np.asarray(ys, float)
    if len(x) < 2 or np.ptp(x) == 0:
        return 0.0
    return float(np.polyfit(x, y, 1)[0])


def _line_pts(xs, ys, x0, x1):
    x = np.asarray(xs, float); y = np.asarray(ys, float)
    m, b = np.polyfit(x, y, 1)
    return (x0, m * x0 + b, x1, m * x1 + b)


def classify_correction(corr: list[Pivot], impulse: Impulse, atr_at: float) -> Correction | None:
    """Классифицировать коррекцию по наклонам верхней/нижней линий."""
    highs = [(p.i, p.price) for p in corr if p.kind == "H"]
    lows = [(p.i, p.price) for p in corr if p.kind == "L"]
    if len(highs) < 2 or len(lows) < 2 or atr_at <= 0:
        return None
    su = _fit([x for x, _ in highs], [y for _, y in highs])
    sl = _fit([x for x, _ in lows], [y for _, y in lows])
    su_n, sl_n = su / atr_at, sl / atr_at  # наклон в ATR/бар

    x0 = corr[0].i; x1 = corr[-1].i
    up_pts = _line_pts([x for x, _ in highs], [y for _, y in highs], x0, x1)
    lo_pts = _line_pts([x for x, _ in lows], [y for _, y in lows], x0, x1)
    width_start = up_pts[1] - lo_pts[1]
    width_end = up_pts[3] - lo_pts[3]
    converging = bool(width_end < max(width_start, 1e-9) * CONVERGE_RATIO)

    flat_u = abs(su_n) < FLAT_TOL
    flat_l = abs(sl_n) < FLAT_TOL
    parallel = abs(su_n - sl_n) < PARALLEL_TOL and not converging

    if parallel:
        kind = "CHANNEL"
    elif converging and su_n < 0 and sl_n > 0:
        kind = "PENNANT"          # симм. треугольник
    elif converging and su_n > 0 and sl_n > 0:
        kind = "RISING_WEDGE"
    elif converging and su_n < 0 and sl_n < 0:
        kind = "FALLING_WEDGE"
    elif flat_u and sl_n > 0:
        kind = "ASC_TRI"
    elif flat_l and su_n < 0:
        kind = "DESC_TRI"
    else:
        kind = "CHANNEL" if not converging else "PENNANT"

    # наклон коррекции против импульса? (down-импульс -> восходящая коррекция = ловушка)
    # «против» — про ЗНАК наклона (не крутизну), поэтому малый eps, а не FLAT_TOL.
    corr_mid_slope = (su_n + sl_n) / 2
    against = bool((impulse.direction == "DOWN" and corr_mid_slope > EPS_AGAINST) or
                   (impulse.direction == "UP" and corr_mid_slope < -EPS_AGAINST))
    if kind == "CHANNEL" and against:
        kind = "FLAG"

    depth = abs(max(p.price for p in corr) - min(p.price for p in corr))
    depth_pct = depth / impulse.magnitude * 100 if impulse.magnitude > 0 else 0.0

    return Correction(
        kind=kind, against_impulse=against, slope_up=su, slope_lo=sl,
        su_norm=su_n, sl_norm=sl_n, converging=converging, depth_pct=depth_pct,
        bars=corr[-1].i - corr[0].i, pivots=corr, upper=up_pts, lower=lo_pts)


def find_archetypes(df: pd.DataFrame, atr_mult: float = ZZ_MULT) -> list[Archetype]:
    """Импульс + прикреплённая коррекция + measured-move TP по всему df."""
    atr = compute_atr(df)
    piv = zigzag(df, atr_mult)
    if len(piv) < 5:
        return []
    impulses = find_impulses(df, piv, atr)
    out = []
    for imp in impulses:
        # пивоты после конца импульса
        k_end = next((k for k, p in enumerate(piv) if p.i == imp.i1 and p.price == imp.p1), None)
        if k_end is None:
            continue
        corr = []
        for p in piv[k_end + 1:]:
            # коррекция «жива», пока не уходит за начало импульса (>100% ретрейс = разворот)
            if imp.direction == "DOWN" and p.price > imp.p0:
                break
            if imp.direction == "UP" and p.price < imp.p0:
                break
            corr.append(p)
            if len(corr) >= CORR_MAX_PIVOTS:
                break
        if len(corr) < CORR_MIN_PIVOTS:
            continue
        c = classify_correction(corr, imp, atr[corr[-1].i])
        if c is None:
            continue
        # measured-move: от уровня пробоя проецируем флагшток
        if imp.direction == "DOWN":
            breakout = min(p.price for p in corr)      # низ коррекции
            tp = breakout - imp.magnitude
        else:
            breakout = max(p.price for p in corr)
            tp = breakout + imp.magnitude
        out.append(Archetype(impulse=imp, correction=c, measured_move_tp=tp,
                             breakout_level=breakout, continuation_dir=imp.direction))
    return out
