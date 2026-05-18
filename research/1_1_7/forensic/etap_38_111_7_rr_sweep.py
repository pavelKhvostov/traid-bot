"""Этап 38 (1.1.7): RR sweep на best filter.

Берём 6.3y baseline, для каждого RR ∈ {1.0, 1.5, 2.0, 2.5, 3.0}
пересимулируем outcome (TP/SL), применяем best filter (time+asvk+mh)
и считаем WR / total / R-per-trade.

Симулятор использует df_1m. Для каждого trade:
  - entry/sl уже зафиксированы в исходном backtest CSV (signal-level)
  - TP = entry + RR × risk (LONG) или entry - RR × risk (SHORT)
  - симуляция: какой раньше hit, TP или SL, после fill?
  - reuse: fill_time из исходного CSV (после fill_time уже сидим в trade)

Это даёт правильное "what-if RR=2.0".
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

_ELEMENTS = _ROOT / "research" / "elements_study"
if str(_ELEMENTS) not in _sys.path:
    _sys.path.insert(0, str(_ELEMENTS))

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from etap_35_strategy_111_forensic import hull_ma

SYMBOL = "BTCUSDT"
BACKTEST_CSV = "signals/backtest_strategy_1_1_7.csv"
FEATURES_CSV = "research/1_1_7/forensic/output/etap_47_111_7_trades_features.csv"
RR_LIST = [1.0, 1.5, 2.0, 2.5, 3.0]


def parse_utc3_to_utc(s):
    if pd.isna(s) or s == "":
        return pd.NaT
    return pd.Timestamp(s, tz="UTC") - pd.Timedelta(hours=3)


def main():
    print("[INFO] загрузка данных")
    df_bt = pd.read_csv(BACKTEST_CSV)
    df_1m = load_df(SYMBOL, "1m")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")

    # Закрытые сетапы — выполняем simulation.
    # Для NO_ENTRY и NOT_FILLED — outcome от RR не зависит (фильтрация на pre-fill).
    df = df_bt.copy()
    print(f"  total: {len(df)}, closed: {(df['outcome'].isin(['WIN','LOSS'])).sum()}")

    # Подготовка времён.
    df["signal_time_utc"] = df["fvg_c2_time"].apply(parse_utc3_to_utc)
    df["fill_time_utc"] = df["fill_time"].apply(
        lambda s: pd.Timestamp(s, tz="UTC") - pd.Timedelta(hours=3)
        if isinstance(s, str) and s else pd.NaT
    )
    df["entry"] = df["entry"].astype(float)
    df["sl"] = df["sl"].astype(float)

    # Compute hull labels для direction filter.
    h_1h_160 = hull_ma(df_1h["close"], 160)
    h_12h_180 = hull_ma(df_12h["close"], 180)

    def hull_label(close, hull):
        h2 = hull.shift(2)
        return pd.Series(
            np.where(close > h2, "up", np.where(close < h2, "down", "na")),
            index=close.index,
        )

    lbl_1h = hull_label(df_1h["close"], h_1h_160)
    lbl_12h = hull_label(df_12h["close"], h_12h_180)

    def safe_lookup(labels, ts):
        if pd.isna(ts):
            return "na"
        idx = labels.index.searchsorted(ts, side="right") - 1
        if idx < 1:
            return "na"
        v = labels.iloc[idx - 1]
        return v if pd.notna(v) else "na"

    df["hull_1h_L160"] = df["signal_time_utc"].apply(lambda t: safe_lookup(lbl_1h, t))
    df["hull_12h_L180"] = df["signal_time_utc"].apply(lambda t: safe_lookup(lbl_12h, t))

    # Load features CSV для time/asvk/mh.
    feat = pd.read_csv(FEATURES_CSV)
    feat["ts"] = pd.to_datetime(feat["signal_time"], utc=True)
    feat = feat[["ts", "asvk_4h", "mh_4h_color", "weekday", "session"]]

    df = df.merge(feat, left_on="signal_time_utc", right_on="ts", how="left")

    # Direction-specific hull + time + asvk + mh.
    df["dir_hull"] = (
        ((df["direction"] == "LONG") & (df["hull_1h_L160"] == "up"))
        | ((df["direction"] == "SHORT") & (df["hull_12h_L180"] == "down"))
    )
    df["time_ok"] = (df["weekday"] != "Sunday") & (df["session"] != "London")
    df["asvk_ok"] = df["asvk_4h"] != "red"
    df["mh_ok"] = ~df["mh_4h_color"].isin(["green", "grey_from_green"])

    # Best filter combos
    df["filter_TAM"] = df["time_ok"] & df["asvk_ok"] & df["mh_ok"]  # time+asvk+mh
    df["filter_DH"] = df["dir_hull"]
    df["filter_TAMH"] = df["filter_TAM"] & df["dir_hull"]  # ALL 4
    df["filter_DH_TIME"] = df["dir_hull"] & df["time_ok"]

    # Fast 1m simulator from etap_35.
    ts_arr = df_1m.index.values
    h_arr = df_1m["high"].to_numpy(dtype=float)
    l_arr = df_1m["low"].to_numpy(dtype=float)

    def simulate_rr(entry, sl, direction, fill_time, rr, timeout_days=14):
        if pd.isna(fill_time):
            return None, 0.0
        risk = abs(entry - sl)
        if risk <= 0:
            return "invalid", 0.0
        if direction == "LONG":
            tp = entry + rr * risk
        else:
            tp = entry - rr * risk
        ft = fill_time.tz_localize(None) if fill_time.tz else fill_time
        end = ft + pd.Timedelta(days=timeout_days)
        i0 = np.searchsorted(ts_arr, np.datetime64(ft))
        i1 = np.searchsorted(ts_arr, np.datetime64(end))
        if i1 <= i0:
            return "no_data", 0.0
        h = h_arr[i0:i1]
        l = l_arr[i0:i1]
        if direction == "LONG":
            sl_hits = l <= sl
            tp_hits = h >= tp
            sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else len(h)
            tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else len(h)
            if sl_idx == len(h) and tp_idx == len(h):
                return "open", 0.0
            if sl_idx <= tp_idx:
                return "loss", -1.0
            return "win", rr
        else:
            sl_hits = h >= sl
            tp_hits = l <= tp
            sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else len(h)
            tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else len(h)
            if sl_idx == len(h) and tp_idx == len(h):
                return "open", 0.0
            if sl_idx <= tp_idx:
                return "loss", -1.0
            return "win", rr

    print(f"\n[INFO] симуляция RR sweep на {len(df)} setups")

    # Только filled trades (есть fill_time).
    filled_mask = df["fill_time_utc"].notna() & df["outcome"].isin(["WIN", "LOSS"])
    filled = df[filled_mask].copy()
    print(f"  filled (will resimulate): {len(filled)}")

    rr_results = {}
    for rr in RR_LIST:
        outcomes = []
        rs = []
        for _, row in filled.iterrows():
            out, r = simulate_rr(row["entry"], row["sl"], row["direction"],
                                  row["fill_time_utc"], rr)
            outcomes.append(out or "no")
            rs.append(r)
        col_o = f"out_RR{rr}"
        col_r = f"R_RR{rr}"
        filled[col_o] = outcomes
        filled[col_r] = rs
        rr_results[rr] = (col_o, col_r)

    # Apply filters and compute summary per RR.
    print(f"\n{'filter':<25} {'RR':<5} {'n':<5} {'WR':<7} {'total':<8} {'R/tr':<8}")
    for filt_name, mask_col in [
        ("baseline", None),
        ("filter_TAM (time+asvk+mh)", "filter_TAM"),
        ("filter_DH (dir_hull)", "filter_DH"),
        ("filter_DH+time", "filter_DH_TIME"),
        ("filter_TAMH (all 4)", "filter_TAMH"),
    ]:
        if mask_col:
            sub = filled[filled[mask_col]]
        else:
            sub = filled
        for rr in RR_LIST:
            col_o, col_r = rr_results[rr]
            outs = sub[col_o]
            rs = sub[col_r]
            closed = sub[outs.isin(["win", "loss"])]
            n = len(closed)
            if n == 0:
                continue
            wr = (closed[col_o] == "win").sum() / n * 100
            # total R including no_entry/open/not_filled as 0
            total = sub[col_r].sum()
            r_tr = total / n
            print(f"{filt_name:<25} {rr:<5} {n:<5} {wr:<7.1f} {total:+7.1f} {r_tr:+7.3f}")

    # Best year-by-year
    print(f"\n=== Year-by-year (filter_TAM × RR=1.5) ===")
    sub = filled[filled["filter_TAM"]].copy()
    sub["year"] = sub["signal_time_utc"].dt.year
    for y in sorted(sub["year"].unique()):
        s = sub[sub["year"] == y]
        col_o, col_r = rr_results[1.5]
        closed = s[s[col_o].isin(["win", "loss"])]
        n = len(closed)
        wr = (closed[col_o] == "win").sum() / n * 100 if n else 0
        total = s[col_r].sum()
        print(f"  {y}: n={n:<3} WR={wr:5.1f}% total={total:+.1f}R")


if __name__ == "__main__":
    main()
