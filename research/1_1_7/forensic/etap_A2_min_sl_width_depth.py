"""Этап A2: min_sl_pct sweep + FVG width + OB depth filters.

С лучшей конфигурацией A1 (entry=0.5, sl=asym, RR=2.5, filter_TAM):
1. min_sl_pct: отсекает trades где risk слишком маленький (= узкая зона
   = слишком чувствительна к ATR)
2. FVG width %: small/medium/large
3. OB depth %: small/medium/large
4. POI height % (от sweep size)
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd

from data_manager import load_df

SYMBOL = "BTCUSDT"
BACKTEST_CSV = "signals/backtest_strategy_1_1_7.csv"
FEATURES_CSV = "research/1_1_7/forensic/output/etap_47_111_7_trades_features.csv"


def parse_utc3(s):
    if pd.isna(s) or s == "":
        return pd.NaT
    return pd.Timestamp(s, tz="UTC") - pd.Timedelta(hours=3)


def parse_zone(s):
    a, b = s.split("-")
    return float(a), float(b)


def main():
    df = pd.read_csv(BACKTEST_CSV)
    feat = pd.read_csv(FEATURES_CSV)
    feat["ts"] = pd.to_datetime(feat["signal_time"], utc=True)
    df_1m = load_df(SYMBOL, "1m")

    df["signal_time_utc"] = df["fvg_c2_time"].apply(parse_utc3)
    df = df.merge(feat[["ts", "asvk_4h", "mh_4h_color", "weekday", "session"]],
                   left_on="signal_time_utc", right_on="ts", how="left")
    df["filter_TAM"] = (
        (df["weekday"] != "Sunday")
        & (df["session"] != "London")
        & (df["asvk_4h"] != "red")
        & (~df["mh_4h_color"].isin(["green", "grey_from_green"]))
    )
    df["fvg_b"], df["fvg_t"] = zip(*df["fvg_zone"].apply(parse_zone))
    df["ob_b"], df["ob_t"] = zip(*df["ob_zone"].apply(parse_zone))
    df["poi_b"], df["poi_t"] = zip(*df["poi_zone"].apply(parse_zone))

    df["fvg_w_pct"] = (df["fvg_t"] - df["fvg_b"]) / df["fvg_b"] * 100
    df["ob_depth_pct"] = (df["ob_t"] - df["ob_b"]) / df["ob_b"] * 100
    df["poi_h_pct"] = (df["poi_t"] - df["poi_b"]) / df["poi_b"] * 100

    ts_arr = df_1m.index.values
    h_arr = df_1m["high"].to_numpy(dtype=float)
    l_arr = df_1m["low"].to_numpy(dtype=float)

    def simulate(direction, entry, sl, tp, start_time, timeout_days=14):
        st = start_time.tz_localize(None) if start_time.tz else start_time
        end = st + pd.Timedelta(days=timeout_days)
        i0 = np.searchsorted(ts_arr, np.datetime64(st))
        i1 = np.searchsorted(ts_arr, np.datetime64(end))
        if i1 <= i0:
            return "no_data", 0.0
        h = h_arr[i0:i1]
        l = l_arr[i0:i1]
        risk = abs(entry - sl)
        if risk <= 0:
            return "invalid", 0.0
        if direction == "LONG":
            act_mask = l <= entry
            if not act_mask.any():
                return "not_filled", 0.0
            act = int(np.argmax(act_mask))
            pre_h = h[:act]; pre_l = l[:act]
            if (pre_h >= tp).any() or (pre_l <= sl).any():
                return "no_entry", 0.0
            h2 = h[act:]; l2 = l[act:]
            sl_hits = l2 <= sl; tp_hits = h2 >= tp
            sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else len(h2)
            tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else len(h2)
            if sl_idx == len(h2) and tp_idx == len(h2):
                return "open", 0.0
            if sl_idx <= tp_idx:
                return "loss", -1.0
            return "win", (tp - entry) / risk
        else:
            act_mask = h >= entry
            if not act_mask.any():
                return "not_filled", 0.0
            act = int(np.argmax(act_mask))
            pre_h = h[:act]; pre_l = l[:act]
            if (pre_l <= tp).any() or (pre_h >= sl).any():
                return "no_entry", 0.0
            h2 = h[act:]; l2 = l[act:]
            sl_hits = h2 >= sl; tp_hits = l2 <= tp
            sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else len(h2)
            tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else len(h2)
            if sl_idx == len(h2) and tp_idx == len(h2):
                return "open", 0.0
            if sl_idx <= tp_idx:
                return "loss", -1.0
            return "win", (entry - tp) / risk

    # Setup: entry=0.5 mid FVG, sl=asym, RR=2.5
    rr = 2.5

    def build(row, min_sl_pct=None):
        d = row["direction"]
        fb, ft = row["fvg_b"], row["fvg_t"]
        ob_b, ob_t = row["ob_b"], row["ob_t"]
        if d == "LONG":
            entry = fb + 0.5 * (ft - fb)
            sl = ob_b + 0.35 * (fb - ob_b)
            if sl >= entry:
                return None
            risk_pct = (entry - sl) / entry * 100
            if min_sl_pct is not None and risk_pct < min_sl_pct:
                sl = entry * (1 - min_sl_pct / 100)
            tp = entry + rr * (entry - sl)
        else:
            entry = ft - 0.5 * (ft - fb)
            sl = ob_t - 0.65 * (ob_t - ft)
            if sl <= entry:
                return None
            risk_pct = (sl - entry) / entry * 100
            if min_sl_pct is not None and risk_pct < min_sl_pct:
                sl = entry * (1 + min_sl_pct / 100)
            tp = entry - rr * (sl - entry)
        return entry, sl, tp

    fdf = df[df["filter_TAM"]].copy()

    def run_grid(setups_df, label):
        outcomes, rs = [], []
        for _, row in setups_df.iterrows():
            s = build(row)
            if s is None:
                outcomes.append("invalid")
                rs.append(0.0)
                continue
            entry, sl, tp = s
            out, r = simulate(row["direction"], entry, sl, tp,
                               row["signal_time_utc"])
            outcomes.append(out)
            rs.append(r)
        outcomes = pd.Series(outcomes)
        rs = pd.Series(rs)
        n_cl = outcomes.isin(["win", "loss"]).sum()
        wr = (outcomes == "win").sum() / n_cl * 100 if n_cl else 0
        total = rs.sum()
        r_tr = total / n_cl if n_cl else 0
        print(f"{label:<32} n={len(setups_df):<4} n_cl={n_cl:<4} "
              f"WR={wr:<5.1f}% total={total:+7.1f} R/tr={r_tr:+7.3f}")
        return r_tr, total, n_cl

    # A2: min_sl_pct sweep
    print(f"\n=== A2: min_sl_pct sweep (с базы entry=0.5, sl=asym, RR={rr}) ===")
    run_grid(fdf, "baseline (no min_sl)")
    for ms in [0.5, 1.0, 1.5, 2.0, 3.0]:
        outcomes, rs = [], []
        for _, row in fdf.iterrows():
            s = build(row, min_sl_pct=ms)
            if s is None:
                outcomes.append("invalid")
                rs.append(0.0)
                continue
            entry, sl, tp = s
            out, r = simulate(row["direction"], entry, sl, tp,
                               row["signal_time_utc"])
            outcomes.append(out)
            rs.append(r)
        outcomes = pd.Series(outcomes)
        rs = pd.Series(rs)
        n_cl = outcomes.isin(["win", "loss"]).sum()
        wr = (outcomes == "win").sum() / n_cl * 100 if n_cl else 0
        total = rs.sum()
        r_tr = total / n_cl if n_cl else 0
        print(f"  min_sl_pct={ms:<5} n_cl={n_cl:<4} WR={wr:<5.1f}% "
              f"total={total:+7.1f} R/tr={r_tr:+7.3f}")

    # A3: FVG width buckets
    print(f"\n=== A3: FVG width filter ===")
    bins = [(0, 0.3, "tiny"), (0.3, 0.6, "small"), (0.6, 1.2, "medium"),
            (1.2, 100, "large")]
    for lo, hi, label in bins:
        sub = fdf[(fdf["fvg_w_pct"] >= lo) & (fdf["fvg_w_pct"] < hi)]
        if len(sub) < 10:
            continue
        run_grid(sub, f"fvg_w {label} [{lo}-{hi})")

    # A4: OB depth buckets
    print(f"\n=== A4: OB depth filter ===")
    bins = [(0, 0.5, "small"), (0.5, 1.5, "medium"), (1.5, 3.0, "large"),
            (3.0, 100, "huge")]
    for lo, hi, label in bins:
        sub = fdf[(fdf["ob_depth_pct"] >= lo) & (fdf["ob_depth_pct"] < hi)]
        if len(sub) < 10:
            continue
        run_grid(sub, f"ob_d {label} [{lo}-{hi})")

    # A5: POI height buckets
    print(f"\n=== A5: POI height filter ===")
    bins = [(0, 0.5, "thin"), (0.5, 1.5, "normal"), (1.5, 4.0, "tall"),
            (4.0, 100, "huge")]
    for lo, hi, label in bins:
        sub = fdf[(fdf["poi_h_pct"] >= lo) & (fdf["poi_h_pct"] < hi)]
        if len(sub) < 10:
            continue
        run_grid(sub, f"poi_h {label} [{lo}-{hi})")


if __name__ == "__main__":
    main()
