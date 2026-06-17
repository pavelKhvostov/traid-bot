"""etap_255 - reversal-structure detector + honest forward-stat study.

Цель (запрос пользователя): усилить модуль аналитики более грамотным ОПРЕДЕЛЕНИЕМ
разворотной точки ДНЯ и НЕДЕЛИ (сейчас модуль лишь красит часовые бары по режиму
day-type, но НЕ помечает саму точку разворота и не классифицирует "разворотный день").

Дисциплина (стены проекта):
  - Направление = монетка OOS (etap_198/211; lookahead bulk_side был пойман).
    Поэтому это НЕ прогноз направления. Это ОПИСАТЕЛЬНОЕ распознавание структуры
    (где случился разворот, какой формы день/неделя) + ЧЕСТНО измеренное последействие
    (continuation / magnitude / fill), по Bulkowski-стилю, с годовой стабильностью и
    базовой ставкой (null). Печатаем только то, что переживает год-проверку.

Детекторы (без lookahead для live: классифицируем ЗАВЕРШЁННЫЙ день/неделю по её
собственным барам, прогноз меряем СТРОГО вперёд):

  ВНУТРИ ДНЯ (1h бары, UTC-сутки), на базе нашего IB-фреймворка (etap_217):
    - rev_down  : день пробил IB вверх (swept_high), но закрылся в нижней части с
                  большим верхним фитилём -> медвежий разворот дня (bull-trap)
    - rev_up    : пробил IB вниз (swept_low), закрылся в верхней части, большой
                  нижний фитиль -> бычий разворот дня
    - trend_up / trend_down : закрытие у экстремума, малый встречный фитиль
    - range     : мелкий ход, закрытие в середине
    Пивот дня = час, на котором поставлен HoD (для rev_down/trend_up) или LoD.

  НЕДЕЛЯ (1d бары, ISO-неделя пн-вс UTC):
    - wk_sweep_high : неделя сняла прошлонедельный максимум (high>PWH), но закрылась
                      НИЖЕ PWH -> медвежий недельный разворот (свип ликвидности)
    - wk_sweep_low  : сняла PWL (low<PWL), закрылась ВЫШЕ PWL -> бычий разворот
    - wk_cont       : закрытие подтвердило пробой (продолжение)

Forward-метрики на каждое событие:
  dir1/2/3   : ушла ли цена в сторону разворота через 1/2/3 периода (close-to-close)
  cont_mfe   : макс. ход в сторону разворота за горизонт (%)
  cont_mae   : макс. ход против (%)
  filled     : вернулась ли цена за снятый уровень (negate: rev_down -> снова выше HoD)

Запуск:
  set PYTHONIOENCODING=utf-8
  venv/Scripts/python.exe research/daily_engine/etap_255_reversal_structure.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
while not (ROOT / "data_manager.py").exists():
    ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))
from data_manager import load_df  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
IB = 3                 # часов на Initial Balance (1:1 с etap_217)
WICK_REV = 0.50        # доля дневного диапазона: большой встречный фитиль = разворот
TREND_POS = 0.70       # close_pos для трендового дня
WICK_TREND = 0.35      # макс встречный фитиль для трендового дня


# ----------------------------------------------------------------------------
# ВНУТРИДНЕВНАЯ форма + пивот
# ----------------------------------------------------------------------------
def classify_day(g: pd.DataFrame) -> dict | None:
    """Классифицировать ЗАВЕРШЁННЫЙ день g (1h бары одних UTC-суток)."""
    if len(g) < IB + 3:
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
        shape, side, pivot_h, pivot_p = "rev_down", "short", hour_hod, hod
    elif swept_low and dn_wick >= WICK_REV and close_pos >= 0.55 and c > ib_mid:
        shape, side, pivot_h, pivot_p = "rev_up", "long", hour_lod, lod
    elif close_pos >= TREND_POS and up_wick < WICK_TREND:
        shape, side, pivot_h, pivot_p = "trend_up", "long", hour_lod, lod
    elif close_pos <= (1 - TREND_POS) and dn_wick < WICK_TREND:
        shape, side, pivot_h, pivot_p = "trend_down", "short", hour_hod, hod
    else:
        shape, side, pivot_h, pivot_p = "range", "none", hour_hod if c >= o else hour_lod, hod if c >= o else lod

    return dict(open=o, close=c, hod=hod, lod=lod, ib_h=ib_h, ib_l=ib_l,
                hour_hod=hour_hod, hour_lod=hour_lod, close_pos=close_pos,
                up_wick=up_wick, dn_wick=dn_wick, shape=shape, side=side,
                pivot_hour=pivot_h, pivot_price=pivot_p,
                ret=c / o - 1, rng_pct=R / o)


def day_table(df1h: pd.DataFrame) -> pd.DataFrame:
    if df1h.index.tz is None:
        df1h = df1h.tz_localize("UTC")
    rows = []
    for day, g in df1h.groupby(df1h.index.normalize()):
        rec = classify_day(g)
        if rec is None:
            continue
        rec["date"] = pd.Timestamp(day)
        rows.append(rec)
    return pd.DataFrame(rows).set_index("date").sort_index()


# ----------------------------------------------------------------------------
# НЕДЕЛЬНАЯ форма + свип
# ----------------------------------------------------------------------------
def week_table(df1d: pd.DataFrame) -> pd.DataFrame:
    """ISO-недели (пн-вс UTC) из дневных баров. Свип прошлонедельных H/L."""
    if df1d.index.tz is None:
        df1d = df1d.tz_localize("UTC")
    wk = df1d.resample("W-MON", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    wk["pwh"] = wk["high"].shift(1)
    wk["pwl"] = wk["low"].shift(1)
    wk["pwc"] = wk["close"].shift(1)
    rows = []
    for t, r in wk.iterrows():
        if not np.isfinite(r["pwh"]):
            continue
        took_high = r["high"] > r["pwh"]
        took_low = r["low"] < r["pwl"]
        if took_high and r["close"] < r["pwh"]:
            shape, side = "wk_sweep_high", "short"
        elif took_low and r["close"] > r["pwl"]:
            shape, side = "wk_sweep_low", "long"
        elif took_high and r["close"] >= r["pwh"]:
            shape, side = "wk_cont_up", "long"
        elif took_low and r["close"] <= r["pwl"]:
            shape, side = "wk_cont_down", "short"
        else:
            shape, side = "wk_inside", "none"
        rows.append(dict(date=t, open=r["open"], high=r["high"], low=r["low"],
                         close=r["close"], pwh=r["pwh"], pwl=r["pwl"],
                         shape=shape, side=side, ret=r["close"] / r["open"] - 1))
    return pd.DataFrame(rows).set_index("date").sort_index()


# ----------------------------------------------------------------------------
# Forward-метрики (строго вперёд)
# ----------------------------------------------------------------------------
def forward_stats(bars: pd.DataFrame, side: str, ref_level: float,
                  horizon: int) -> dict:
    """bars = ПОСЛЕДУЮЩИЕ периоды (после события). side long/short = сторона разворота.
    ref_level = снятый уровень (HoD/LoD/PWH/PWL) для теста 'filled' (negate)."""
    fw = bars.iloc[:horizon]
    if len(fw) == 0:
        return {}
    c0 = None  # close события передаётся через ref не нужен; меряем от open первого fw? нет
    # close-to-close direction: знак суммарного хода за горизонт
    last_c = float(fw["close"].iloc[-1])
    first_o = float(fw["open"].iloc[0])
    mfe = mae = 0.0
    filled = False
    for _, b in fw.iterrows():
        hi, lo = float(b["high"]), float(b["low"])
        if side == "short":
            mfe = max(mfe, (first_o - lo) / first_o)
            mae = max(mae, (hi - first_o) / first_o)
            if hi > ref_level:          # вернулись выше снятого максимума -> negate
                filled = True
        else:
            mfe = max(mfe, (hi - first_o) / first_o)
            mae = max(mae, (first_o - lo) / first_o)
            if lo < ref_level:
                filled = True
    move = (last_c - first_o) / first_o
    went = (move < 0) if side == "short" else (move > 0)
    return dict(dir_ok=bool(went), mfe=mfe, mae=mae, filled=bool(filled),
                move=move)


# ----------------------------------------------------------------------------
# Агрегация + печать
# ----------------------------------------------------------------------------
def summarize(events: pd.DataFrame, fwd: pd.DataFrame, label: str,
              base_dir: float | None = None) -> None:
    """events со столбцом 'shape','side'; fwd с dir_ok/mfe/mae/filled, индекс совпадает."""
    df = events.join(fwd, how="inner")
    df = df[df["side"] != "none"]
    if df.empty:
        print(f"  [{label}] нет событий"); return
    df["year"] = df.index.year
    print(f"\n  --- {label} ---")
    print(f"  {'shape':<14}{'n':>5}{'dir_ok':>8}{'cont(MFE)':>11}{'adv(MAE)':>10}"
          f"{'fill%':>7}{'years +/-':>11}")
    for shape, s in df.groupby("shape"):
        n = len(s)
        dir_ok = s["dir_ok"].mean()
        mfe = s["mfe"].median(); mae = s["mae"].median()
        fill = s["filled"].mean()
        # годовая стабильность направления: доля лет, где dir_ok>50%
        yr = s.groupby("year")["dir_ok"].mean()
        yr = yr[s.groupby("year").size() >= 4]   # только годы с >=4 событий
        years_pos = (yr > 0.5).sum(); years_tot = len(yr)
        print(f"  {shape:<14}{n:>5}{dir_ok:>7.0%}{mfe:>10.1%}{mae:>9.1%}"
              f"{fill:>6.0%}{years_pos:>5}/{years_tot:<5}")
    if base_dir is not None:
        print(f"  база (все периоды) dir_ok в сторону side: ~{base_dir:.0%} "
              f"(сравнивай столбец dir_ok с этим)")


def study_symbol(sym: str) -> None:
    print("=" * 74)
    print(f"  {sym}")
    print("=" * 74)
    df1h = load_df(sym, "1h")
    df1d = load_df(sym, "1d")
    if df1h.empty or df1d.empty:
        print("  нет данных"); return
    print(f"  1h: {df1h.index[0].date()}..{df1h.index[-1].date()} ({len(df1h)})  "
          f"1d: {df1d.index[0].date()}..{df1d.index[-1].date()} ({len(df1d)})")

    # ---- внутридневные события: форвард на ДНЕВНЫХ барах ----
    dt = day_table(df1h)
    if df1d.index.tz is None:
        df1d = df1d.tz_localize("UTC")
    d_idx = df1d.index.normalize()
    rows = {}
    for H in (1, 2, 3):
        recs = {}
        for date, ev in dt.iterrows():
            # последующие дневные бары строго после события
            after = df1d[d_idx > date]
            if len(after) == 0:
                continue
            recs[date] = forward_stats(after, ev["side"], ev["pivot_price"], H)
        rows[H] = pd.DataFrame(recs).T
    # базовая ставка: на сколько вообще день закрывается красным/зелёным (для сравнения)
    for H in (1, 2, 3):
        summarize(dt, rows[H], f"ВНУТРИ ДНЯ -> следующие {H}d (close-to-close)")

    # ---- недельные события: форвард на НЕДЕЛЬНЫХ барах ----
    wt = week_table(df1d)
    wk = df1d.resample("W-MON", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    for H in (1, 2):
        recs = {}
        for date, ev in wt.iterrows():
            after = wk[wk.index > date]
            if len(after) == 0:
                continue
            ref = ev["pwh"] if ev["side"] == "short" else ev["pwl"]
            recs[date] = forward_stats(after, ev["side"], ref, H)
        fwd = pd.DataFrame(recs).T
        summarize(wt, fwd, f"НЕДЕЛЯ -> следующие {H}w")


def main():
    for sym in SYMBOLS:
        study_symbol(sym)
    print("\nЧитать: dir_ok ~50% = монетка (ожидаемо, направление=стена). Смотрим на")
    print("cont(MFE) vs adv(MAE) и fill% — есть ли асимметрия хода/заполнения уровня,")
    print("и years +/- = в скольких годах из всех направление было >50% (год-стабильность).")


if __name__ == "__main__":
    main()
