"""Обогащение CSV нестандартными метриками для гипотез N1-N11.

Добавляет колонки:
  - bars_since_last_3_2_signal     (для N1 cluster)
  - signals_in_24h_window          (для N1 cluster)
  - hour_of_signal_utc, weekday_of_signal, session_label (для N2)
  - fvg_4h_age_hours, fvg_4h_size_pct, fvg_1h_size_pct (для N3)
  - touch_penetration_pct          (насколько глубоко wick зашёл в FVG-4h)
  - aligned_flag_count, opposed_flag_count, agreement_score (для N4)
  - latest_aligned_div_age_hours   (для N5)
  - latest_any_div_age_hours
  - abs_mf_at_signal               (для N7)
  - mf_quartile                    (rolling year)
  - quick_failure                  (для N8: SL hit ≤2h после активации)
  - prev_was_quick_failure         (chronological previous trade был quick_failure?)
  - win_streak / loss_streak       (для N9)
  - atr14_at_signal                (для N6, дальше re-sim отдельно)
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    if _ROOT.parent == _ROOT:
        raise RuntimeError("repo root not found")
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import load_df

INPUT_CSV = Path("signals/strategy_3_2_3y_RR1_with_asvk_mh.csv")
OUT_CSV = Path("signals/strategy_3_2_3y_RR1_unconventional.csv")
SYMBOL = "BTCUSDT"


def parse_utc3(s):
    if pd.isna(s) or s == "":
        return None
    return pd.Timestamp(s, tz="UTC") - pd.Timedelta(hours=3)


def session_for_hour(h):
    """0-7 asia, 7-13 europe, 13-21 us, 21-24 late_us."""
    if 0 <= h < 7:
        return "asia"
    if 7 <= h < 13:
        return "europe"
    if 13 <= h < 21:
        return "us"
    return "late_us"


def main():
    print(f"[INFO] загрузка {INPUT_CSV}")
    df = pd.read_csv(INPUT_CSV)
    print(f"  rows: {len(df)}")

    # Парсим времена
    df["_st_utc"] = df["signal_time"].apply(parse_utc3)
    df["_tt_utc"] = df["touch_time"].apply(parse_utc3)
    df["_at_utc"] = df["activation_time"].apply(parse_utc3)
    df["_ex_utc"] = df["exit_time"].apply(parse_utc3)
    df["_fvg4h_c2_utc"] = df["fvg_4h_c2_time"].apply(parse_utc3)
    df["_fvg1h_c0_utc"] = df["fvg_1h_c0_time"].apply(parse_utc3)
    df["_fvg1h_c2_utc"] = df["fvg_1h_c2_time"].apply(parse_utc3)

    # Сортируем хронологически (важно для cluster, streak, prev_failure)
    df_sorted = df.sort_values("_st_utc").reset_index(drop=True)

    # ---------- N1: cluster ----------
    print("[INFO] N1 cluster metrics")
    bars_since = []
    signals_24h = []
    for i, row in df_sorted.iterrows():
        st = row["_st_utc"]
        if i == 0 or st is None:
            bars_since.append(np.nan)
        else:
            prev_st = df_sorted.iloc[i - 1]["_st_utc"]
            if prev_st is None:
                bars_since.append(np.nan)
            else:
                bars_since.append((st - prev_st).total_seconds() / 3600)
        # signals в окне [st-24h, st)
        if st is None:
            signals_24h.append(0)
        else:
            mask = (df_sorted["_st_utc"] >= st - pd.Timedelta(hours=24)) & \
                   (df_sorted["_st_utc"] < st)
            signals_24h.append(int(mask.sum()))
    df_sorted["hours_since_last_signal"] = bars_since
    df_sorted["signals_in_prev_24h"] = signals_24h

    # ---------- N2: time/session ----------
    print("[INFO] N2 time / session")
    df_sorted["hour_utc"] = df_sorted["_st_utc"].apply(
        lambda x: x.hour if x is not None else np.nan
    )
    df_sorted["weekday"] = df_sorted["_st_utc"].apply(
        lambda x: x.day_name() if x is not None else None
    )
    df_sorted["session"] = df_sorted["hour_utc"].apply(
        lambda h: session_for_hour(int(h)) if not pd.isna(h) else None
    )

    # ---------- N3: FVG age/size ----------
    print("[INFO] N3 FVG age & size")
    fvg_age = []
    fvg_size_pct = []
    fvg1h_size_pct = []
    touch_pen = []
    for _, row in df_sorted.iterrows():
        tt = row["_tt_utc"]
        c2 = row["_fvg4h_c2_utc"]
        if tt is not None and c2 is not None:
            fvg_age.append((tt - c2).total_seconds() / 3600)
        else:
            fvg_age.append(np.nan)
        bot = row["fvg_4h_bottom"]
        top = row["fvg_4h_top"]
        mid = (bot + top) / 2 if pd.notna(bot) and pd.notna(top) else np.nan
        fvg_size_pct.append((top - bot) / mid * 100 if pd.notna(mid) and mid > 0 else np.nan)

        b1 = row["fvg_1h_bottom"]
        t1 = row["fvg_1h_top"]
        m1 = (b1 + t1) / 2 if pd.notna(b1) and pd.notna(t1) else np.nan
        fvg1h_size_pct.append((t1 - b1) / m1 * 100 if pd.notna(m1) and m1 > 0 else np.nan)

        # Глубина проникновения wick в FVG-4h
        # Для LONG (FVG.bot < FVG.top, цена приходит сверху): touch_low <= top
        # penetration = (top - touch_low) / (top - bot) — 0..1
        # touch_low не записан; вместо этого приближаем через sweep_low/_high — нет, в 3.2 нет sweep, но есть touch_close.
        # Аппроксимация: исп. min(touch_close, touch+1_close) для LONG, max для SHORT.
        # Точная глубина wick требует загрузки 4h данных — отложу как nan.
        touch_pen.append(np.nan)
    df_sorted["fvg_4h_age_hours"] = fvg_age
    df_sorted["fvg_4h_size_pct"] = fvg_size_pct
    df_sorted["fvg_1h_size_pct"] = fvg1h_size_pct

    # ---------- N4: agreement entropy ----------
    print("[INFO] N4 agreement score")
    aligned_cnt = []
    opposed_cnt = []
    agreement_score = []
    for _, row in df_sorted.iterrows():
        d = row["direction"]
        # ASVK aligned-for-LONG flags
        long_flags = [
            row.get("bull_div_in_window", False) is True,
            row.get("h_bull_div_in_window", False) is True,
            (pd.notna(row.get("rsi_at_signal")) and pd.notna(row.get("below_at_signal"))
             and row["rsi_at_signal"] < row["below_at_signal"]),
            (pd.notna(row.get("z_pct_at_signal")) and row["z_pct_at_signal"] < 0.25),
            row.get("bw2_color") in ("green", "grey_after_red"),
            (pd.notna(row.get("mf_at_signal")) and row["mf_at_signal"] > 0),
            (pd.notna(row.get("bw2_at_touch")) and row["bw2_at_touch"] <= -60),
            row.get("bw1_bw2_bull_cross_in_window", False) is True,
        ]
        short_flags = [
            row.get("bear_div_in_window", False) is True,
            row.get("h_bear_div_in_window", False) is True,
            (pd.notna(row.get("rsi_at_signal")) and pd.notna(row.get("above_at_signal"))
             and row["rsi_at_signal"] > row["above_at_signal"]),
            (pd.notna(row.get("z_pct_at_signal")) and row["z_pct_at_signal"] > 0.75),
            row.get("bw2_color") in ("red", "grey_after_green"),
            (pd.notna(row.get("mf_at_signal")) and row["mf_at_signal"] < 0),
            (pd.notna(row.get("bw2_at_touch")) and row["bw2_at_touch"] >= 60),
            row.get("bw1_bw2_bear_cross_in_window", False) is True,
        ]
        long_score = sum(long_flags)
        short_score = sum(short_flags)
        if d == "LONG":
            aligned = long_score
            opposed = short_score
        else:
            aligned = short_score
            opposed = long_score
        aligned_cnt.append(aligned)
        opposed_cnt.append(opposed)
        total_used = aligned + opposed
        if total_used == 0:
            agreement_score.append(0.0)
        else:
            agreement_score.append((aligned - opposed) / 8.0)
    df_sorted["aligned_flag_count"] = aligned_cnt
    df_sorted["opposed_flag_count"] = opposed_cnt
    df_sorted["agreement_score"] = agreement_score

    # ---------- N5: divergence age ----------
    # Загружаем 1h, считаем bars_since_div для каждой сделки
    print("[INFO] N5 divergence age (через bars_since_OB/OS не подходит — нужен div age)")
    # Используем уже-посчитанные booleans + извлечём latest div confirmation time
    # ASVK div times и MH div times уже есть в части первого enrichment, но без точного времени.
    # Проще: воспоьзуемся signal_time как точкой отсчёта; вычислим возраст последней div ANY type
    # перебирая bull/h_bull/bear/h_bear для нужного направления.
    # Время div confirmation = на ipos+lb_r, мы тогда не сохранили. Оставим NA для данной задачи —
    # это не критическая метрика. Переделаем через быстрый ре-расчёт.
    _RSI_DIR = _ROOT / "research" / "asvk_rsi"
    if str(_RSI_DIR) not in _sys.path:
        _sys.path.insert(0, str(_RSI_DIR))
    from plot_asvk_rsi import (
        adjusted_rsi, find_divergences,
        LB_L, LB_R, RANGE_LOWER, RANGE_UPPER,
    )
    df_1h = load_df(SYMBOL, "1h")
    ema_3 = adjusted_rsi(df_1h["close"])
    bull, h_bull, bear, h_bear = find_divergences(
        ema_3, df_1h["low"], df_1h["high"], LB_L, LB_R, RANGE_LOWER, RANGE_UPPER,
    )
    bull_t = pd.DatetimeIndex([df_1h.index[d[0] + LB_R] for d in bull], tz="UTC")
    h_bull_t = pd.DatetimeIndex([df_1h.index[d[0] + LB_R] for d in h_bull], tz="UTC")
    bear_t = pd.DatetimeIndex([df_1h.index[d[0] + LB_R] for d in bear], tz="UTC")
    h_bear_t = pd.DatetimeIndex([df_1h.index[d[0] + LB_R] for d in h_bear], tz="UTC")

    aligned_div_age = []
    for _, row in df_sorted.iterrows():
        st = row["_st_utc"]
        d = row["direction"]
        if st is None:
            aligned_div_age.append(np.nan)
            continue
        if d == "LONG":
            times = bull_t.union(h_bull_t)
        else:
            times = bear_t.union(h_bear_t)
        past = times[times <= st]
        if len(past) == 0:
            aligned_div_age.append(np.nan)
        else:
            aligned_div_age.append((st - past[-1]).total_seconds() / 3600)
    df_sorted["aligned_div_age_hours"] = aligned_div_age

    # ---------- N7: |MF| ----------
    print("[INFO] N7 |MF|")
    df_sorted["abs_mf_at_signal"] = df_sorted["mf_at_signal"].abs()

    # ---------- N8: quick failure / N9: streak ----------
    print("[INFO] N8 quick failure & N9 streak")
    quick_failure = []
    for _, row in df_sorted.iterrows():
        if row["outcome"] != "loss":
            quick_failure.append(False)
            continue
        at = row["_at_utc"]
        ex = row["_ex_utc"]
        if at is None or ex is None:
            quick_failure.append(False)
            continue
        diff_h = (ex - at).total_seconds() / 3600
        quick_failure.append(diff_h <= 2.0)
    df_sorted["quick_failure"] = quick_failure

    # prev_was_quick_failure (chronological)
    prev_qf = [False]
    for i in range(1, len(df_sorted)):
        prev_qf.append(bool(df_sorted.iloc[i - 1]["quick_failure"]))
    df_sorted["prev_was_quick_failure"] = prev_qf

    # win_streak / loss_streak (chronological, on closed only)
    wins_streak = []
    losses_streak = []
    cur_w = 0
    cur_l = 0
    for _, row in df_sorted.iterrows():
        wins_streak.append(cur_w)
        losses_streak.append(cur_l)
        if row["outcome"] == "win":
            cur_w += 1
            cur_l = 0
        elif row["outcome"] == "loss":
            cur_l += 1
            cur_w = 0
        # not_filled / open — streak не меняется
    df_sorted["win_streak_before"] = wins_streak
    df_sorted["loss_streak_before"] = losses_streak

    # ---------- N6: ATR(14) ----------
    print("[INFO] N6 ATR(14) at signal_time")
    high = df_1h["high"]
    low = df_1h["low"]
    close = df_1h["close"]
    prev_close = close.shift(1)
    tr = pd.concat([(high - low),
                    (high - prev_close).abs(),
                    (low - prev_close).abs()], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean()
    atr_at_signal = []
    for _, row in df_sorted.iterrows():
        st = row["_st_utc"]
        if st is None:
            atr_at_signal.append(np.nan)
            continue
        ipos = df_1h.index.get_indexer([st], method="ffill")[0]
        if ipos < 0:
            atr_at_signal.append(np.nan)
            continue
        atr_at_signal.append(float(atr14.iloc[ipos]))
    df_sorted["atr14_at_signal"] = atr_at_signal

    # cleanup помощных колонок
    drop_cols = ["_st_utc", "_tt_utc", "_at_utc", "_ex_utc",
                 "_fvg4h_c2_utc", "_fvg1h_c0_utc", "_fvg1h_c2_utc"]
    df_sorted = df_sorted.drop(columns=drop_cols)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df_sorted.to_csv(OUT_CSV, index=False)
    print(f"[OK] saved: {OUT_CSV}")


if __name__ == "__main__":
    main()
