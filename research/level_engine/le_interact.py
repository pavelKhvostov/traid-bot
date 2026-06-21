"""le_interact — реакции цены на уровень: REJECT / BREAK / FLIP (причинно).

Lookahead-register #5/#10: у каждой реакции ДВА времени — t_touch (когда стала видна
свеча-касание) и t_resolved (когда класс+магнитуда полностью известны, <= t_touch+H_react).
Реакция ВХОДИТ в belief(L,T) только при T>=t_resolved. Здесь считаем ПОЛНУЮ историю
реакций уровня (каждая со штампом t_resolved); фильтрацию по T делает belief.

σ = трейлинг ATR_1D as-of дня касания (сдвиг, без подглядывания внутрь дня).
Классы:
  approach сверху (цена пришла ВНИЗ к полосе=поддержка): BREAK=close ниже bottom>=0.25σ;
    REJECT=ушла вверх выше top на follow>=0.5σ.
  approach снизу (resistance): BREAK=close выше top; REJECT=ушла вниз ниже bottom.
  FLIP: после BREAK цена вернулась и оттолкнулась с ДРУГОЙ стороны (полярность сменилась).
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd


@dataclass
class Interaction:
    t_touch: pd.Timestamp
    t_resolved: pd.Timestamp
    cls: str            # REJECT|BREAK|FLIP
    m: float            # [0,4]
    sigma: float
    why: dict = field(default_factory=dict)


def daily_atr(df1h: pd.DataFrame, win: int = 14) -> pd.Series:
    """Трейлинг ATR_1D (true range), сдвинут на 1 день -> as-of предыдущего дня."""
    d = df1h.resample("1D").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    pc = d["close"].shift(1)
    tr = pd.concat([d.high - d.low, (d.high - pc).abs(), (d.low - pc).abs()], axis=1).max(axis=1)
    return (tr.rolling(win).mean()).shift(1)   # as-of: значение на день D исп. бары < D


def _sigma_at(atr_d: pd.Series, t: pd.Timestamp) -> float:
    try:
        v = atr_d.asof(t)
        return float(v) if v and v == v and v > 0 else float("nan")
    except Exception:
        return float("nan")


def replay_interactions(bottom: float, top: float, t_start: pd.Timestamp,
                        df1h: pd.DataFrame, atr_d: pd.Series,
                        H_react: int = 48, cooldown: int = 8,
                        flip_window: int = 72) -> list[Interaction]:
    """Полная причинная история реакций полосы [bottom,top], начиная с t_start."""
    if df1h.index.tz is None:
        df1h = df1h.tz_localize("UTC")
    df = df1h[df1h.index >= t_start]
    n = len(df)
    if n < 3:
        return []
    O = df["open"].values; H = df["high"].values; L = df["low"].values; C = df["close"].values
    idx = df.index
    out: list[Interaction] = []
    i = 1
    while i < n:
        in_band = (L[i] <= top) and (H[i] >= bottom)
        if not in_band:
            i += 1; continue
        prev_c = C[i - 1]
        if prev_c > top:
            side = "above"          # пришли сверху -> поддержка; break вниз, reject вверх
        elif prev_c < bottom:
            side = "below"          # пришли снизу -> сопротивление; break вверх, reject вниз
        else:
            i += 1; continue        # уже внутри полосы (продолжение) — не касание
        sigma = _sigma_at(atr_d, idx[i])
        if not (sigma > 0):
            i += 1; continue
        end = min(i + H_react, n)
        res = None  # (cls, j, m, why)
        run_hi = H[i]; run_lo = L[i]
        for j in range(i, end):
            run_hi = max(run_hi, H[j]); run_lo = min(run_lo, L[j])
            if side == "above":     # поддержка
                if C[j] < bottom - 0.25 * sigma:                       # BREAK вниз
                    close_beyond = (bottom - C[j]) / sigma
                    speed = float(np.clip(2.0 / (j - i + 1), 0, 1.5))
                    res = ("BREAK", j, float(np.clip(close_beyond + speed, 0, 4)),
                           dict(side=side, close_beyond=round(close_beyond, 2), bars=j - i + 1)); break
                if run_hi > top + 0.5 * sigma:                          # REJECT вверх
                    follow = (run_hi - top) / sigma
                    depth = float(np.clip((top - run_lo) / sigma, 0, 1))
                    res = ("REJECT", j, float(np.clip(depth + follow, 0, 4)),
                           dict(side=side, follow_R=round(follow, 2), depth=round(depth, 2))); break
            else:                   # сопротивление
                if C[j] > top + 0.25 * sigma:                          # BREAK вверх
                    close_beyond = (C[j] - top) / sigma
                    speed = float(np.clip(2.0 / (j - i + 1), 0, 1.5))
                    res = ("BREAK", j, float(np.clip(close_beyond + speed, 0, 4)),
                           dict(side=side, close_beyond=round(close_beyond, 2), bars=j - i + 1)); break
                if run_lo < bottom - 0.5 * sigma:                       # REJECT вниз
                    follow = (bottom - run_lo) / sigma
                    depth = float(np.clip((run_hi - bottom) / sigma, 0, 1))
                    res = ("REJECT", j, float(np.clip(depth + follow, 0, 4)),
                           dict(side=side, follow_R=round(follow, 2), depth=round(depth, 2))); break
        if res is None:
            i = end; continue       # не разрешилось в окне — пропускаем
        cls, j, m, why = res
        out.append(Interaction(idx[i], idx[j], cls, m, sigma, why))
        # FLIP: после BREAK ищем возврат+отбой с другой стороны
        if cls == "BREAK":
            fend = min(j + flip_window, n)
            for k in range(j + 1, fend):
                back_in = (L[k] <= top) and (H[k] >= bottom)
                if not back_in:
                    continue
                if side == "above":     # пробили вниз -> теперь сопротивление сверху: отбой вниз
                    if L[k] < bottom - 0.5 * sigma or C[k] < bottom:
                        out.append(Interaction(idx[k], idx[k], "FLIP", float(np.clip(m * 0.7, 0, 4)),
                                               sigma, dict(flip_from=side))); break
                else:
                    if H[k] > top + 0.5 * sigma or C[k] > top:
                        out.append(Interaction(idx[k], idx[k], "FLIP", float(np.clip(m * 0.7, 0, 4)),
                                               sigma, dict(flip_from=side))); break
        i = j + 1 + cooldown        # cooldown, чтобы не считать одну осцилляцию многократно
    return out
