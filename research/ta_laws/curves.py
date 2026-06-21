"""Детектор КРИВОЛИНЕЙНЫХ паттернов (арки / округления / параболика) для нейро-модуля ТА.

То, что глаз видит как плавную ДУГУ поверх цены (а не прямую трендовую):
  - купол (concave down, a<0)  -> ROUNDING_TOP / арка-над (паттерн с фото юзера: закругление на верху
    + ускоряющийся спуск по дуге);
  - чаша (concave up,  a>0)  -> ROUNDING_BOTTOM / арка-под (cup / округлое дно).

Признак — КРИВИЗНА, не наклон. Меряем фитом параболы close ~ a·t² + b·t + c:
  * r2_quad      — насколько хорошо парабола описывает окно;
  * arc_gain     — насколько парабола ЛУЧШЕ прямой (r2_quad - r2_lin) = «это дуга, не линия»;
  * sagitta_atr  — прогиб дуги от хорды в серединах = |a|·L²/8, в ATR (физическая «изогнутость»).
arm = i1 (правый край окна) — каузально, форма известна только по завершении дуги.

Чистая геометрия. Куда пойдёт / докуда после арки — меряет arc_analysis.py.
Тесты: tests/test_curves.py.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from geometry import compute_atr  # noqa: E402

ARC_MIN_BARS = 15
ARC_MAX_BARS = 90
R2Q_MIN = 0.80          # парабола описывает окно
ARC_GAIN_MIN = 0.04     # парабола заметно лучше прямой
SAGITTA_ATR_MIN = 1.5   # дуга прогибается от хорды >= 1.5 ATR (реально изогнута)
OVERLAP_MAX = 0.5       # дедуп: пересечение окон <= 50%


@dataclass
class Arc:
    kind: str            # ROUNDING_TOP | ROUNDING_BOTTOM
    i0: int
    i1: int
    t0: pd.Timestamp
    t1: pd.Timestamp
    p0: float
    p1: float
    a_norm: float        # кривизна a, нормированная на ATR (a*1bar²/ATR)
    r2_quad: float
    r2_lin: float
    arc_gain: float
    sagitta_atr: float   # прогиб дуги в ATR
    apex_i: int          # бар вершины/дна параболы (в пределах окна)
    apex_price: float
    depth_atr: float     # размах окна в ATR
    conf_i: int          # arm = i1
    coeffs: tuple = field(default=())  # (a,b,c) в координатах x=0..L


def _r2(y, yhat):
    y = np.asarray(y, float)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    if ss_tot <= 0:
        return 0.0
    ss_res = float(((y - yhat) ** 2).sum())
    return 1.0 - ss_res / ss_tot


def fit_quad(x, y):
    a, b, c = np.polyfit(x, y, 2)
    yhat = a * x * x + b * x + c
    return float(a), float(b), float(c), _r2(y, yhat)


def fit_lin(x, y):
    m, q = np.polyfit(x, y, 1)
    return _r2(y, m * x + q)


def detect_arc(df: pd.DataFrame, i0: int, i1: int, atr: np.ndarray) -> Arc | None:
    """Фит параболы к close[i0..i1]. Вернуть Arc если окно реально изогнуто, иначе None."""
    L = i1 - i0
    if L < ARC_MIN_BARS or L > ARC_MAX_BARS or i1 >= len(df):
        return None
    atr_a = atr[i1]
    if not (atr_a > 0):
        return None
    x = np.arange(L + 1, dtype=float)
    y = df["close"].to_numpy()[i0:i1 + 1].astype(float)
    if len(y) != L + 1:
        return None
    a, b, c, r2q = fit_quad(x, y)
    r2l = fit_lin(x, y)
    sagitta = abs(a) * L * L / 8.0          # макс. отклонение параболы от хорды
    sag_atr = sagitta / atr_a
    if r2q < R2Q_MIN or (r2q - r2l) < ARC_GAIN_MIN or sag_atr < SAGITTA_ATR_MIN:
        return None
    kind = "ROUNDING_TOP" if a < 0 else "ROUNDING_BOTTOM"
    xv = -b / (2 * a) if a != 0 else L / 2
    apex_x = int(np.clip(round(xv), 0, L))
    apex_i = i0 + apex_x
    apex_price = float(a * apex_x * apex_x + b * apex_x + c)
    depth_atr = float((y.max() - y.min()) / atr_a)
    return Arc(
        kind=kind, i0=i0, i1=i1, t0=df.index[i0], t1=df.index[i1],
        p0=float(y[0]), p1=float(y[-1]), a_norm=float(a / atr_a),
        r2_quad=float(r2q), r2_lin=float(r2l), arc_gain=float(r2q - r2l),
        sagitta_atr=float(sag_atr), apex_i=apex_i, apex_price=apex_price,
        depth_atr=depth_atr, conf_i=i1, coeffs=(a, b, c))


def _overlap(a: Arc, b: Arc) -> float:
    lo = max(a.i0, b.i0); hi = min(a.i1, b.i1)
    inter = max(0, hi - lo)
    return inter / max(min(a.i1 - a.i0, b.i1 - b.i0), 1)


def find_arcs(df: pd.DataFrame, lengths=(20, 30, 45, 65), atr: np.ndarray | None = None) -> list[Arc]:
    """Скан окнами нескольких длин -> фит параболы -> дедуп по силе (sagitta) и пересечению."""
    if atr is None:
        atr = compute_atr(df)
    n = len(df)
    cand: list[Arc] = []
    for L in lengths:
        step = max(L // 3, 4)
        for i0 in range(0, n - L - 1, step):
            arc = detect_arc(df, i0, i0 + L, atr)
            if arc is not None:
                cand.append(arc)
    cand.sort(key=lambda a: a.sagitta_atr, reverse=True)
    kept: list[Arc] = []
    for a in cand:
        if all(_overlap(a, k) <= OVERLAP_MAX for k in kept):
            kept.append(a)
    kept.sort(key=lambda a: a.i1)
    return kept
