"""Разворотная структура дня и недели для модуля аналитики (ОПИСАТЕЛЬНО).

Зачем: дашборд раньше только красил часовые бары по режиму day-type (тренд/боковик),
но не помечал САМУ точку разворота и не классифицировал «разворотный день/неделю».
Этот модуль это делает.

ЧЕСТНАЯ РАМКА (etap_255 + адверсариальная проверка, 3 монеты × 7 лет):
  - Направление ПОСЛЕ разворотной структуры = монетка (dir_ok 42-58%, год-нестаб.).
    Это подтверждённая стена проекта (направление дня = монетка OOS). Поэтому здесь
    НЕТ прогноза направления и НЕТ ставок.
  - «Свип-уровень = магнит» — УБИТ при контроле близости (свип-недели возвращаются к
    уровню НЕ чаще, а чуть реже немечёных на той же дистанции: BTC -10.7пп и т.д.).
  - Поэтому модуль — чистый ОПИСАТЕЛЬ структуры: где развернулось, какой формы день/
    неделя, какой уровень снят. Без directional-claim. Соответствует духу дашборда
    («это состояние дня, а не прогноз будущего»).

Lookahead-чисто: классифицируем только по барам самого периода; «формирующийся»
день/неделя помечается developing=True (берём бары до текущего момента включительно).

API:
  classify_day(g, developing=False) -> dict | None    # g = 1h бары одних UTC-суток
  weekly_structure(df1d) -> dict | None                # дневные бары (вкл. текущий)
  describe_intraday(rec) -> str                        # человеческая строка RU
  describe_weekly(rec) -> str
"""
from __future__ import annotations

import numpy as np
import pandas as pd

IB = 3                 # часов на Initial Balance (1:1 с etap_217)
WICK_REV = 0.50        # доля дневного диапазона: большой встречный фитиль = разворот
TREND_POS = 0.70       # close_pos для трендового дня
WICK_TREND = 0.35      # макс встречный фитиль для трендового дня


def classify_day(g: pd.DataFrame, developing: bool = False) -> dict | None:
    """Классифицировать день g (1h бары одних UTC-суток).

    developing=True — день ещё идёт (берём бары до текущего часа); shape отражает
    формирующуюся структуру (close = последний известный close).
    Возврат dict(shape, side, pivot_hour, pivot_price, ...) или None.
    shape ∈ {rev_up, rev_down, trend_up, trend_down, range}.
    """
    if g is None or len(g) < IB + 2:
        return None
    o = float(g["open"].iloc[0]); c = float(g["close"].iloc[-1])
    H = g["high"].values; Lo = g["low"].values
    hod = float(H.max()); lod = float(Lo.min())
    R = hod - lod
    if R <= 0:
        return None
    hour_hod = int(np.argmax(H)); hour_lod = int(np.argmin(Lo))
    ib_h = float(H[:IB].max()); ib_l = float(Lo[:IB].min())
    ib_mid = (ib_h + ib_l) / 2
    swept_high = hod > ib_h
    swept_low = lod < ib_l
    up_wick = (hod - max(o, c)) / R
    dn_wick = (min(o, c) - lod) / R
    close_pos = (c - lod) / R

    if swept_high and up_wick >= WICK_REV and close_pos <= 0.45 and c < ib_mid:
        shape, side, ph, pp = "rev_down", "short", hour_hod, hod
    elif swept_low and dn_wick >= WICK_REV and close_pos >= 0.55 and c > ib_mid:
        shape, side, ph, pp = "rev_up", "long", hour_lod, lod
    elif close_pos >= TREND_POS and up_wick < WICK_TREND:
        shape, side, ph, pp = "trend_up", "long", hour_lod, lod
    elif close_pos <= (1 - TREND_POS) and dn_wick < WICK_TREND:
        shape, side, ph, pp = "trend_down", "short", hour_hod, hod
    else:
        up = c >= o
        shape, side, ph, pp = "range", "none", (hour_lod if up else hour_hod), (lod if up else hod)

    return dict(shape=shape, side=side, pivot_hour=ph, pivot_price=pp,
                hod=hod, lod=lod, ib_h=ib_h, ib_l=ib_l, close=c, open=o,
                close_pos=close_pos, up_wick=up_wick, dn_wick=dn_wick,
                hour_hod=hour_hod, hour_lod=hour_lod, developing=bool(developing))


def weekly_structure(df1d: pd.DataFrame) -> dict | None:
    """Структура ТЕКУЩЕЙ недели (вкл. незакрытую) + снятие прошлонедельных H/L.

    df1d — дневные бары (последний может быть незавершённым днём). Возврат dict с
    pwh/pwl (прошлая неделя), текущими hi/lo/last, флагами took_high/took_low/reclaim
    и shape ∈ {wk_sweep_high, wk_sweep_low, wk_cont_up, wk_cont_down, wk_inside}.
    """
    if df1d is None or len(df1d) < 8:
        return None
    d = df1d.copy()
    if d.index.tz is None:
        d.index = d.index.tz_localize("UTC")
    wk = d.resample("W-MON", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    if len(wk) < 2:
        return None
    cur = wk.iloc[-1]; prev = wk.iloc[-2]
    pwh = float(prev["high"]); pwl = float(prev["low"])
    hi = float(cur["high"]); lo = float(cur["low"]); last = float(cur["close"])
    took_high = hi > pwh
    took_low = lo < pwl
    # развёрнутый ли свип: сняли уровень и вернулись за него
    if took_high and last < pwh:
        shape, side = "wk_sweep_high", "short"
    elif took_low and last > pwl:
        shape, side = "wk_sweep_low", "long"
    elif took_high and last >= pwh:
        shape, side = "wk_cont_up", "long"
    elif took_low and last <= pwl:
        shape, side = "wk_cont_down", "short"
    else:
        shape, side = "wk_inside", "none"
    # позиция в недельном диапазоне
    wr = hi - lo
    pos = (last - lo) / wr if wr > 0 else 0.5
    return dict(shape=shape, side=side, pwh=pwh, pwl=pwl, hi=hi, lo=lo,
                last=last, took_high=took_high, took_low=took_low, pos=pos,
                developing=True)


# ----------------------------------------------------------------------------
# человеческие описания (RU) — ОПИСАТЕЛЬНЫЕ, без прогноза направления
# ----------------------------------------------------------------------------
_DAY_TXT = {
    "rev_up":     "разворот ВВЕРХ (снят утренний минимум, цена выкуплена назад)",
    "rev_down":   "разворот ВНИЗ (снят утренний максимум, цена слита назад)",
    "trend_up":   "трендовый день вверх (закрытие у максимума)",
    "trend_down": "трендовый день вниз (закрытие у минимума)",
    "range":      "боковик (закрытие в середине диапазона)",
}


def _hm(p: float) -> str:
    return f"{p/1000:.1f}k" if p >= 10000 else f"{p:,.0f}"


def describe_intraday(rec: dict | None) -> str:
    """Строка ТОЛЬКО для разворотного дня (rev_up/rev_down) — это и есть новая
    детекция разворота. Трендовый/боковик день уже передаёт режим (заливка баров),
    поэтому для них возвращаем '' (без дублирования)."""
    if not rec or rec["shape"] not in ("rev_up", "rev_down"):
        return ""
    txt = _DAY_TXT[rec["shape"]]
    suffix = " — формируется" if rec.get("developing") else ""
    return (f"🔄 День: {txt} — пивот в {rec['pivot_hour']:02d}:00 UTC "
            f"на {_hm(rec['pivot_price'])}{suffix}")


def describe_weekly(rec: dict | None) -> str:
    """Строка о недельной структуре ТОЛЬКО при реальном событии (свип/пробой PWH-PWL).
    Для 'внутри диапазона' — '' (это уже передаёт строка позиции в неделе)."""
    if not rec or rec["shape"] == "wk_inside":
        return ""
    if rec["shape"] == "wk_sweep_high":
        return (f"📅 Неделя: снят прошлонедельный максимум {_hm(rec['pwh'])} и цена "
                f"вернулась ниже — недельный разворот ВНИЗ (свип ликвидности)")
    if rec["shape"] == "wk_sweep_low":
        return (f"📅 Неделя: снят прошлонедельный минимум {_hm(rec['pwl'])} и цена "
                f"вернулась выше — недельный разворот ВВЕРХ (свип ликвидности)")
    if rec["shape"] == "wk_cont_up":
        return f"📅 Неделя: пробит прошлонедельный максимум {_hm(rec['pwh'])} (продолжение вверх)"
    if rec["shape"] == "wk_cont_down":
        return f"📅 Неделя: пробит прошлонедельный минимум {_hm(rec['pwl'])} (продолжение вниз)"
    return ""
