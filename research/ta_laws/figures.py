"""Библиотека классических фигур ТА (из zigzag-пивотов) — для вывода законов.

Реверсивные/уровневые фигуры (в дополнение к импульс-коррекция из geometry.py):
  DOUBLE_TOP/BOTTOM, HEAD_SHOULDERS/INVERSE, TRIPLE_TOP/BOTTOM,
  ASC_TRIANGLE/DESC_TRIANGLE/SYM_TRIANGLE, RECTANGLE(range).
Каждая фигура: kind, expected_dir (учебник), neckline, height, comp_conf_i (каузальный arm).

Чистая геометрия. Куда раскрывается / докуда — меряет figure_analysis.py.
Пивоты строго чередуются H/L (из zigzag) → проверяем kind на завершающем пивоте.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from geometry import Pivot, zigzag, compute_atr, _fit  # noqa: E402

TOL_EQ = 0.7        # «равные» пивоты: |Δ| <= TOL_EQ*ATR
SHOULDER_TOL = 1.0  # плечи H&S чуть свободнее
NECK_TOL = 0.9      # горизонтальность неклайна
WEDGE_MIN_PIV = 4   # треугольники/прямоугольник: >=4 пивота
CONVERGE_RATIO = 0.72
FLAT_TOL = 0.12
PARALLEL_TOL = 0.25


@dataclass
class Figure:
    kind: str
    expected_dir: str          # UP | DOWN (учебная сторона раскрытия)
    neckline: float            # уровень пробоя
    height: float              # высота фигуры (для measured-move)
    comp_i: int                # бар завершающего экстремума
    comp_conf_i: int           # каузальный arm (подтверждение завершающего пивота)
    pivots: list = field(default_factory=list)


def _trend_before(df_close, idx, look=20):
    j = max(idx - look, 0)
    return "UP" if df_close[idx] > df_close[j] else "DOWN"


def find_figures(df: pd.DataFrame, atr_mult: float = 1.8) -> list[Figure]:
    piv = zigzag(df, atr_mult)
    atr = compute_atr(df)
    cl = df["close"].values
    out: list[Figure] = []
    for i in range(len(piv)):
        a = atr[piv[i].i] if atr[piv[i].i] > 0 else np.nan
        if not (a > 0):
            continue
        tol = TOL_EQ * a
        p = piv

        # --- DOUBLE TOP: i=H, i-2=H равны, i-1=L (впадина) ---
        if i >= 2 and p[i].kind == "H":
            h2, h1, lo = p[i].price, p[i - 2].price, p[i - 1].price
            if abs(h2 - h1) <= tol and (h1 + h2) / 2 - lo > 0:
                out.append(Figure("DOUBLE_TOP", "DOWN", lo, (h1 + h2) / 2 - lo,
                                  p[i].i, p[i].conf_i, p[i - 2:i + 1]))
        # --- DOUBLE BOTTOM ---
        if i >= 2 and p[i].kind == "L":
            l2, l1, hi = p[i].price, p[i - 2].price, p[i - 1].price
            if abs(l2 - l1) <= tol and hi - (l1 + l2) / 2 > 0:
                out.append(Figure("DOUBLE_BOTTOM", "UP", hi, hi - (l1 + l2) / 2,
                                  p[i].i, p[i].conf_i, p[i - 2:i + 1]))
        # --- HEAD & SHOULDERS: i=H(RS), i-2=H(head выше), i-4=H(LS); i-1,i-3=L (неклайн) ---
        if i >= 4 and p[i].kind == "H":
            ls, head, rs = p[i - 4].price, p[i - 2].price, p[i].price
            l1, l2 = p[i - 3].price, p[i - 1].price
            if head > ls and head > rs and abs(ls - rs) <= SHOULDER_TOL * a and abs(l1 - l2) <= NECK_TOL * a:
                neck = (l1 + l2) / 2
                out.append(Figure("HEAD_SHOULDERS", "DOWN", neck, head - neck,
                                  p[i].i, p[i].conf_i, p[i - 4:i + 1]))
        # --- INVERSE H&S ---
        if i >= 4 and p[i].kind == "L":
            ls, head, rs = p[i - 4].price, p[i - 2].price, p[i].price
            h1, h2 = p[i - 3].price, p[i - 1].price
            if head < ls and head < rs and abs(ls - rs) <= SHOULDER_TOL * a and abs(h1 - h2) <= NECK_TOL * a:
                neck = (h1 + h2) / 2
                out.append(Figure("INV_HEAD_SHOULDERS", "UP", neck, neck - head,
                                  p[i].i, p[i].conf_i, p[i - 4:i + 1]))
        # --- TRIPLE TOP / BOTTOM ---
        if i >= 4 and p[i].kind == "H":
            tops = [p[i - 4].price, p[i - 2].price, p[i].price]
            if max(tops) - min(tops) <= tol:
                neck = min(p[i - 3].price, p[i - 1].price)
                if sum(tops) / 3 - neck > 0:
                    out.append(Figure("TRIPLE_TOP", "DOWN", neck, sum(tops) / 3 - neck,
                                      p[i].i, p[i].conf_i, p[i - 4:i + 1]))
        if i >= 4 and p[i].kind == "L":
            bots = [p[i - 4].price, p[i - 2].price, p[i].price]
            if max(bots) - min(bots) <= tol:
                neck = max(p[i - 3].price, p[i - 1].price)
                if neck - sum(bots) / 3 > 0:
                    out.append(Figure("TRIPLE_BOTTOM", "UP", neck, neck - sum(bots) / 3,
                                      p[i].i, p[i].conf_i, p[i - 4:i + 1]))
        # --- ТРЕУГОЛЬНИКИ / ПРЯМОУГОЛЬНИК: окно последних 5 пивотов, фит линий ---
        if i >= 4:
            w = p[i - 4:i + 1]
            highs = [(q.i, q.price) for q in w if q.kind == "H"]
            lows = [(q.i, q.price) for q in w if q.kind == "L"]
            if len(highs) >= 2 and len(lows) >= 2:
                su = _fit([x for x, _ in highs], [y for _, y in highs]) / a
                sl = _fit([x for x, _ in lows], [y for _, y in lows]) / a
                x0, x1 = w[0].i, w[-1].i
                hu = np.polyfit([x for x, _ in highs], [y for _, y in highs], 1)
                hl = np.polyfit([x for x, _ in lows], [y for _, y in lows], 1)
                w_start = (hu[0] * x0 + hu[1]) - (hl[0] * x0 + hl[1])
                w_end = (hu[0] * x1 + hu[1]) - (hl[0] * x1 + hl[1])
                converging = w_end < max(w_start, 1e-9) * CONVERGE_RATIO
                flat_u, flat_l = abs(su) < FLAT_TOL, abs(sl) < FLAT_TOL
                parallel = abs(su - sl) < PARALLEL_TOL and not converging
                height = max(w_start, w_end)
                neck_up = hu[0] * x1 + hu[1]; neck_lo = hl[0] * x1 + hl[1]
                kind = expd = None
                if flat_u and sl > FLAT_TOL:
                    kind, expd, neck = "ASC_TRIANGLE", "UP", neck_up
                elif flat_l and su < -FLAT_TOL:
                    kind, expd, neck = "DESC_TRIANGLE", "DOWN", neck_lo
                elif converging and su < 0 < sl:
                    kind, expd = "SYM_TRIANGLE", _trend_before(cl, w[0].i)
                    neck = neck_up if expd == "UP" else neck_lo
                elif parallel and flat_u and flat_l:
                    kind, expd = "RECTANGLE", _trend_before(cl, w[0].i)
                    neck = neck_up if expd == "UP" else neck_lo
                if kind and height > 0:
                    out.append(Figure(kind, expd, float(neck), float(height),
                                      p[i].i, p[i].conf_i, list(w)))
    return out
