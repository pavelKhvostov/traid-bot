"""Этап 44: понятный CSV всех позиций по стратегии C2.

Экспортируем каждую сделку с человеко-читаемыми колонками:
  - Время обнаружения сетапа, входа, выхода
  - Направление (LONG/SHORT)
  - Цены: entry, SL, TP, фактический exit
  - Размеры зон OB-6h и FVG-2h
  - Risk в %, target в %
  - Результат (win/loss/...) и R-multiple
  - Время удержания
  - Cumulative R (накопительная прибыль для equity curve)
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from pathlib import Path
import time
import numpy as np
import pandas as pd

from data_manager import load_df
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
ANCHOR_TF = "6h"
TRIGGER_TF = "2h"
MIN_SL_PCT = 1.0
SL_BUF_ATR = 0.3
ENTRY_PCT = 0.5
RR = 1.0
LIFE_DAYS = 10
TIMEOUT_DAYS = 3

OUT_DIR = Path("research/elements_study/output")
OUT_CSV_FULL = OUT_DIR / "etap44_c2_positions_full.csv"
OUT_CSV_HUMAN = OUT_DIR / "etap44_c2_positions_human.csv"


def compute_atr(df, period=14):
    high = df["high"]; low = df["low"]; pc = df["close"].shift(1)
    tr = pd.concat([(high-low),(high-pc).abs(),(low-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


class FastSim:
    def __init__(self, df_1m):
        self.ts = df_1m.index.values
        self.high = df_1m["high"].to_numpy(dtype=float)
        self.low = df_1m["low"].to_numpy(dtype=float)

    def simulate(self, direction, entry, sl, tp, start_time, timeout_days):
        end_time = start_time + pd.Timedelta(days=timeout_days)
        i0 = np.searchsorted(self.ts, np.datetime64(
            start_time.tz_localize(None) if start_time.tz else start_time))
        i1 = np.searchsorted(self.ts, np.datetime64(
            end_time.tz_localize(None) if end_time.tz else end_time))
        if i1 <= i0: return ("no_data", 0.0, None, None)
        h = self.high[i0:i1]; l = self.low[i0:i1]
        risk = abs(entry - sl)
        if risk <= 0: return ("invalid", 0.0, None, None)
        if direction == "LONG":
            act_mask = l <= entry
            if not act_mask.any(): return ("not_filled", 0.0, None, None)
            act_idx = int(np.argmax(act_mask))
            fill_ts = pd.Timestamp(self.ts[i0 + act_idx]).tz_localize("UTC")
            h2 = h[act_idx:]; l2 = l[act_idx:]
            sl_hits = l2 <= sl; tp_hits = h2 >= tp
            sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else len(h2)
            tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else len(h2)
            if sl_idx == len(h2) and tp_idx == len(h2):
                return ("open", 0.0, fill_ts, None)
            close_ts = pd.Timestamp(self.ts[i0 + act_idx + min(sl_idx, tp_idx)]).tz_localize("UTC")
            if sl_idx <= tp_idx: return ("loss", -1.0, fill_ts, close_ts)
            return ("win", (tp - entry) / risk, fill_ts, close_ts)
        else:
            act_mask = h >= entry
            if not act_mask.any(): return ("not_filled", 0.0, None, None)
            act_idx = int(np.argmax(act_mask))
            fill_ts = pd.Timestamp(self.ts[i0 + act_idx]).tz_localize("UTC")
            h2 = h[act_idx:]; l2 = l[act_idx:]
            sl_hits = h2 >= sl; tp_hits = l2 <= tp
            sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else len(h2)
            tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else len(h2)
            if sl_idx == len(h2) and tp_idx == len(h2):
                return ("open", 0.0, fill_ts, None)
            close_ts = pd.Timestamp(self.ts[i0 + act_idx + min(sl_idx, tp_idx)]).tz_localize("UTC")
            if sl_idx <= tp_idx: return ("loss", -1.0, fill_ts, close_ts)
            return ("win", (entry - tp) / risk, fill_ts, close_ts)


def collect_obs(df, atr, tf):
    out = []
    for idx in range(2, len(df) - 1):
        ob = detect_ob_pair(df, idx)
        if ob is None: continue
        a = float(atr.iloc[idx])
        if pd.isna(a) or a <= 0: continue
        out.append({"time": ob.cur_time, "direction": ob.direction,
                     "bottom": ob.bottom, "top": ob.top, "atr": a, "tf": tf,
                     "idx": idx, "prev_time": ob.prev_time})
    return out


def collect_fvgs(df, atr, tf):
    out = []
    for idx in range(2, len(df) - 1):
        f = detect_fvg(df, idx)
        if f is None: continue
        a = float(atr.iloc[idx])
        if pd.isna(a) or a <= 0: continue
        out.append({"time": f.c2_time, "direction": f.direction,
                     "bottom": f.bottom, "top": f.top, "atr": a, "tf": tf,
                     "idx": idx, "c0_time": f.c0_time})
    return out


def zones_overlap(b1, t1, b2, t2):
    return not (t1 < b2 or t2 < b1)


def build_c2_setups(obs_6h, fvgs_2h, df_2h):
    a_tf_td = pd.Timedelta(ANCHOR_TF)
    a_life = pd.Timedelta(days=LIFE_DAYS)
    t_sorted = sorted(fvgs_2h, key=lambda x: x["time"])
    t_times = np.array([np.datetime64(t["time"].tz_localize(None) if t["time"].tz else t["time"])
                         for t in t_sorted])
    ema_arr = df_2h["ema200"].to_numpy()
    close_arr = df_2h["close"].to_numpy()
    setups = []
    for a in obs_6h:
        a_start = a["time"] + a_tf_td
        a_end = a["time"] + a_life
        if a_end <= a_start: continue
        i_start = np.searchsorted(t_times, np.datetime64(
            a_start.tz_localize(None) if a_start.tz else a_start), side="right")
        i_end = np.searchsorted(t_times, np.datetime64(
            a_end.tz_localize(None) if a_end.tz else a_end), side="right")
        for ti in range(i_start, i_end):
            t = t_sorted[ti]
            if t["direction"] != a["direction"]: continue
            if not zones_overlap(t["bottom"], t["top"], a["bottom"], a["top"]):
                continue
            em = float(ema_arr[t["idx"]]); cl = float(close_arr[t["idx"]])
            pro = ((t["direction"] == "LONG" and cl > em) or
                   (t["direction"] == "SHORT" and cl < em))
            if not pro: continue
            setups.append({"anchor": a, "trigger": t,
                            "anchor_time": a["time"],
                            "trigger_time": t["time"],
                            "direction": t["direction"],
                            "year": t["time"].year,
                            "ema200": em, "close_at_trigger": cl})
            break
    return setups


def build_c2_orders(s):
    t = s["trigger"]
    direction = t["direction"]
    fb, ft = t["bottom"], t["top"]
    atr = t["atr"]
    if direction == "LONG":
        entry = fb + ENTRY_PCT * (ft - fb)
        atr_sl = fb - SL_BUF_ATR * atr
        min_dist = entry * MIN_SL_PCT / 100
        sl = min(atr_sl, entry - min_dist)
    else:
        entry = ft - ENTRY_PCT * (ft - fb)
        atr_sl = ft + SL_BUF_ATR * atr
        min_dist = entry * MIN_SL_PCT / 100
        sl = max(atr_sl, entry + min_dist)
    risk = abs(entry - sl)
    if risk <= 0: return None
    tp = entry + RR * risk if direction == "LONG" else entry - RR * risk
    return entry, sl, tp


# ---------- Russian outcome labels ----------

OUTCOME_RU = {
    "win":        "ПРИБЫЛЬ (TP)",
    "loss":       "УБЫТОК (SL)",
    "open":       "осталась открытой",
    "not_filled": "не было входа (цена не дошла до entry)",
    "no_data":    "нет данных",
    "invalid":    "некорректный сетап",
}


def main():
    t0 = time.time()
    print("[INFO] загружаем данные")
    df_6h = load_df(SYMBOL, "6h")
    df_2h = load_df(SYMBOL, "2h")
    df_1m = load_df(SYMBOL, "1m")

    df_6h = df_6h[df_6h.index >= pd.Timestamp(START_DATE, tz="UTC")].copy()
    df_2h = df_2h[df_2h.index >= pd.Timestamp(START_DATE, tz="UTC")].copy()
    df_1m = df_1m[df_1m.index >= pd.Timestamp(START_DATE, tz="UTC")]
    df_6h["atr14"] = compute_atr(df_6h, 14)
    df_2h["atr14"] = compute_atr(df_2h, 14)
    df_2h["ema200"] = df_2h["close"].ewm(span=200, adjust=False).mean()

    sim = FastSim(df_1m)
    years = (df_6h.index[-1] - df_6h.index[0]).days / 365
    print(f"  лет: {years:.2f}")

    print("[INFO] собираем зоны")
    obs_6h = collect_obs(df_6h, df_6h["atr14"], "6h")
    fvgs_2h = collect_fvgs(df_2h, df_2h["atr14"], "2h")
    print(f"  OB-6h: {len(obs_6h)}, FVG-2h: {len(fvgs_2h)}")

    print("[INFO] строим C2 setups")
    setups = build_c2_setups(obs_6h, fvgs_2h, df_2h)
    print(f"  всего сетапов: {len(setups)}")

    print("[INFO] симулируем все позиции")
    rows = []
    for s in setups:
        tup = build_c2_orders(s)
        if tup is None:
            continue
        entry, sl, tp = tup
        start_time = s["trigger_time"] + pd.Timedelta(TRIGGER_TF)
        outcome, R, fill_ts, close_ts = sim.simulate(
            s["direction"], entry, sl, tp, start_time, TIMEOUT_DAYS)

        risk = abs(entry - sl)
        risk_pct = risk / entry * 100
        target_pct = RR * risk_pct  # т.к. RR=1.0, target = risk
        if outcome == "win":
            actual_R = R
            actual_pnl_pct = target_pct  # прибыль = +target_pct
            exit_price = tp
        elif outcome == "loss":
            actual_R = -1.0
            actual_pnl_pct = -risk_pct
            exit_price = sl
        else:
            actual_R = 0.0
            actual_pnl_pct = 0.0
            exit_price = None

        hold_h = ((close_ts - start_time).total_seconds() / 3600
                    if close_ts is not None else None)
        time_to_fill_h = ((fill_ts - start_time).total_seconds() / 3600
                           if fill_ts is not None else None)

        ob = s["anchor"]
        fvg = s["trigger"]

        rows.append({
            # Идентификация
            "trade_id": len(rows) + 1,
            "year": s["year"],
            "month": s["trigger_time"].month,
            "direction": s["direction"],
            # Времена
            "anchor_time_utc": s["anchor_time"].strftime("%Y-%m-%d %H:%M"),
            "trigger_time_utc": s["trigger_time"].strftime("%Y-%m-%d %H:%M"),
            "entry_window_start_utc": start_time.strftime("%Y-%m-%d %H:%M"),
            "fill_time_utc": fill_ts.strftime("%Y-%m-%d %H:%M") if fill_ts is not None else "",
            "exit_time_utc": close_ts.strftime("%Y-%m-%d %H:%M") if close_ts is not None else "",
            # Зоны
            "ob_6h_bottom": round(ob["bottom"], 2),
            "ob_6h_top": round(ob["top"], 2),
            "ob_6h_height_pct": round((ob["top"] - ob["bottom"]) / ob["bottom"] * 100, 2),
            "fvg_2h_bottom": round(fvg["bottom"], 2),
            "fvg_2h_top": round(fvg["top"], 2),
            "fvg_2h_height_pct": round((fvg["top"] - fvg["bottom"]) / fvg["bottom"] * 100, 2),
            "atr_2h_at_trigger": round(fvg["atr"], 2),
            "ema200_2h_at_trigger": round(s["ema200"], 2),
            # Ордера
            "entry_price": round(entry, 2),
            "sl_price": round(sl, 2),
            "tp_price": round(tp, 2),
            "risk_pct": round(risk_pct, 3),
            "target_pct": round(target_pct, 3),
            "rr_target": RR,
            # Результат
            "outcome_code": outcome,
            "outcome_ru": OUTCOME_RU.get(outcome, outcome),
            "result_R": round(actual_R, 3),
            "result_pnl_pct": round(actual_pnl_pct, 3),
            "exit_price": round(exit_price, 2) if exit_price is not None else "",
            "time_to_fill_hours": round(time_to_fill_h, 1) if time_to_fill_h is not None else "",
            "hold_hours": round(hold_h, 1) if hold_h is not None else "",
            "hold_days": round(hold_h / 24, 2) if hold_h is not None else "",
        })

    df_full = pd.DataFrame(rows)

    # Cumulative R только для закрытых
    df_full["cumulative_R"] = 0.0
    cum = 0.0
    for i, row in df_full.iterrows():
        if row["outcome_code"] in ("win", "loss"):
            cum += row["result_R"]
        df_full.at[i, "cumulative_R"] = round(cum, 2)

    # Финальная прибыль до этой сделки в %
    df_full["cumulative_pnl_pct"] = 0.0
    cum_p = 0.0
    for i, row in df_full.iterrows():
        if row["outcome_code"] in ("win", "loss"):
            cum_p += row["result_pnl_pct"]
        df_full.at[i, "cumulative_pnl_pct"] = round(cum_p, 2)

    # Сохраняем полный CSV
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df_full.to_csv(OUT_CSV_FULL, index=False, encoding="utf-8-sig")
    print(f"\n[OK] полный CSV: {OUT_CSV_FULL}")
    print(f"     {len(df_full)} позиций, {len(df_full.columns)} колонок")

    # Упрощённая «человеческая» версия для глаз
    cols_human = [
        ("trade_id", "№"),
        ("anchor_time_utc", "Сетап замечен (OB-6h)"),
        ("trigger_time_utc", "Триггер (FVG-2h c2)"),
        ("direction", "Направление"),
        ("entry_price", "Вход"),
        ("sl_price", "Стоп"),
        ("tp_price", "Цель"),
        ("risk_pct", "Риск %"),
        ("outcome_ru", "Результат"),
        ("exit_price", "Выход"),
        ("result_R", "R"),
        ("result_pnl_pct", "Прибыль %"),
        ("hold_hours", "Удержание ч"),
        ("cumulative_R", "Накопит. R"),
    ]
    df_human = df_full[[c for c, _ in cols_human]].copy()
    df_human.columns = [name for _, name in cols_human]
    df_human.to_csv(OUT_CSV_HUMAN, index=False, encoding="utf-8-sig")
    print(f"\n[OK] упрощённая 'человеческая' версия: {OUT_CSV_HUMAN}")
    print(f"     {len(df_human)} позиций, {len(df_human.columns)} колонок")

    # Краткая сводка
    print("\n" + "=" * 70)
    print("СВОДКА")
    print("=" * 70)
    print(f"  Всего позиций:       {len(df_full)}")
    closed = df_full[df_full["outcome_code"].isin(["win", "loss"])]
    print(f"  Закрытых сделок:     {len(closed)}")
    print(f"     прибыльных:       {(closed['outcome_code'] == 'win').sum()}")
    print(f"     убыточных:        {(closed['outcome_code'] == 'loss').sum()}")
    n_no_fill = (df_full["outcome_code"] == "not_filled").sum()
    n_open = (df_full["outcome_code"] == "open").sum()
    n_no_data = (df_full["outcome_code"] == "no_data").sum()
    print(f"     не заполнились:   {n_no_fill}")
    print(f"     остались открыты: {n_open}")
    print(f"     нет данных:       {n_no_data}")
    if len(closed) > 0:
        wr = (closed["outcome_code"] == "win").mean() * 100
        total_R = closed["result_R"].sum()
        print(f"\n  WinRate:            {wr:.1f}%")
        print(f"  Суммарный R:        {total_R:+.1f}")
        print(f"  В % (риск 1%):      {total_R*1:+.0f}% за {years:.2f} лет")
        print(f"  Среднее удержание:  {closed['hold_hours'].astype(float).mean():.1f}ч "
              f"(~{closed['hold_hours'].astype(float).mean()/24:.1f} дней)")

    print("\nКолонки в полном CSV:")
    for col in df_full.columns:
        print(f"  - {col}")

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
