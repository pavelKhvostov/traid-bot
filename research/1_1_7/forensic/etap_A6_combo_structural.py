"""Этап A6: финальная сборка фильтров.

Базис: entry=0.5, sl=asym, RR=2.5.
Filters: TAM + poi_h normal + ob_d medium + дир-hull.

Перебираем комбинации (включить/исключить каждый структурный фильтр).
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

import itertools
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from etap_35_strategy_111_forensic import hull_ma

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
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")

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
    df["ob_d_pct"] = (df["ob_t"] - df["ob_b"]) / df["ob_b"] * 100
    df["poi_h_pct"] = (df["poi_t"] - df["poi_b"]) / df["poi_b"] * 100

    df["filter_poi_normal"] = (df["poi_h_pct"] >= 0.5) & (df["poi_h_pct"] < 1.5)
    df["filter_ob_med"] = (df["ob_d_pct"] >= 0.5) & (df["ob_d_pct"] < 1.5)
    df["filter_fvg_tiny_small"] = df["fvg_w_pct"] < 0.6

    # Direction-specific hull
    h_1h_160 = hull_ma(df_1h["close"], 160)
    h_12h_180 = hull_ma(df_12h["close"], 180)

    def label(close, hull):
        h2 = hull.shift(2)
        return pd.Series(np.where(close > h2, "up",
                          np.where(close < h2, "down", "na")), index=close.index)

    lbl_1h = label(df_1h["close"], h_1h_160)
    lbl_12h = label(df_12h["close"], h_12h_180)

    def safe(labels, ts):
        if pd.isna(ts):
            return "na"
        idx = labels.index.searchsorted(ts, side="right") - 1
        if idx < 1:
            return "na"
        v = labels.iloc[idx - 1]
        return v if pd.notna(v) else "na"

    df["lbl_1h_160"] = df["signal_time_utc"].apply(lambda t: safe(lbl_1h, t))
    df["lbl_12h_180"] = df["signal_time_utc"].apply(lambda t: safe(lbl_12h, t))
    df["filter_dir_hull"] = (
        ((df["direction"] == "LONG") & (df["lbl_1h_160"] == "up"))
        | ((df["direction"] == "SHORT") & (df["lbl_12h_180"] == "down"))
    )

    ts_arr = df_1m.index.values
    h_arr = df_1m["high"].to_numpy(dtype=float)
    l_arr = df_1m["low"].to_numpy(dtype=float)
    rr = 2.5

    def simulate(direction, entry, sl, tp, start_time, timeout_days=14):
        st = start_time.tz_localize(None) if start_time.tz else start_time
        end = st + pd.Timedelta(days=timeout_days)
        i0 = np.searchsorted(ts_arr, np.datetime64(st))
        i1 = np.searchsorted(ts_arr, np.datetime64(end))
        if i1 <= i0:
            return "no_data", 0.0
        h = h_arr[i0:i1]; l = l_arr[i0:i1]
        risk = abs(entry - sl)
        if risk <= 0:
            return "invalid", 0.0
        if direction == "LONG":
            am = l <= entry
            if not am.any():
                return "not_filled", 0.0
            act = int(np.argmax(am))
            if (h[:act] >= tp).any() or (l[:act] <= sl).any():
                return "no_entry", 0.0
            h2 = h[act:]; l2 = l[act:]
            sh = l2 <= sl; th = h2 >= tp
            si = int(np.argmax(sh)) if sh.any() else len(h2)
            ti = int(np.argmax(th)) if th.any() else len(h2)
            if si == len(h2) and ti == len(h2):
                return "open", 0.0
            return ("loss", -1.0) if si <= ti else ("win", (tp - entry)/risk)
        else:
            am = h >= entry
            if not am.any():
                return "not_filled", 0.0
            act = int(np.argmax(am))
            if (l[:act] <= tp).any() or (h[:act] >= sl).any():
                return "no_entry", 0.0
            h2 = h[act:]; l2 = l[act:]
            sh = h2 >= sl; th = l2 <= tp
            si = int(np.argmax(sh)) if sh.any() else len(h2)
            ti = int(np.argmax(th)) if th.any() else len(h2)
            if si == len(h2) and ti == len(h2):
                return "open", 0.0
            return ("loss", -1.0) if si <= ti else ("win", (entry - tp)/risk)

    def build(row):
        d = row["direction"]
        fb, ft = row["fvg_b"], row["fvg_t"]
        ob_b, ob_t = row["ob_b"], row["ob_t"]
        if d == "LONG":
            entry = fb + 0.5 * (ft - fb)
            sl = ob_b + 0.35 * (fb - ob_b)
            if sl >= entry:
                return None
            tp = entry + rr * (entry - sl)
        else:
            entry = ft - 0.5 * (ft - fb)
            sl = ob_t - 0.65 * (ob_t - ft)
            if sl <= entry:
                return None
            tp = entry - rr * (sl - entry)
        return entry, sl, tp

    # Cache outcomes per setup (вычисляем 1 раз для всех)
    print("[INFO] simulating all setups once...")
    outcomes, rs = [], []
    for _, row in df.iterrows():
        s = build(row)
        if s is None:
            outcomes.append("invalid")
            rs.append(0.0)
            continue
        entry, sl, tp = s
        out, r = simulate(row["direction"], entry, sl, tp, row["signal_time_utc"])
        outcomes.append(out)
        rs.append(r)
    df["sim_out"] = outcomes
    df["sim_R"] = rs

    # Combo grid
    filters = {
        "TAM": df["filter_TAM"],
        "poi_normal": df["filter_poi_normal"],
        "ob_med": df["filter_ob_med"],
        "fvg_small": df["filter_fvg_tiny_small"],
        "dir_hull": df["filter_dir_hull"],
    }

    print(f"\n{'combo':<50} {'n':<5} {'n_cl':<5} {'WR':<6} {'total':<8} {'R/tr':<7}")
    for r_size in range(1, len(filters) + 1):
        for combo in itertools.combinations(filters.keys(), r_size):
            mask = pd.Series(True, index=df.index)
            for k in combo:
                mask = mask & filters[k]
            sub = df[mask]
            cl = sub[sub["sim_out"].isin(["win", "loss"])]
            n_cl = len(cl)
            if n_cl < 15:
                continue
            wr = (cl["sim_out"] == "win").sum() / n_cl * 100
            total = sub["sim_R"].sum()
            r_tr = total / n_cl
            name = "+".join(combo)
            flag = " ***" if r_tr >= 1.0 else (" *" if r_tr >= 0.7 else "")
            print(f"{name:<50} {len(sub):<5} {n_cl:<5} {wr:<6.1f} {total:+7.1f} {r_tr:+7.3f}{flag}")

    # Best — year-by-year
    print(f"\n=== Year-by-year for best combos (TAM+poi_normal, TAM+ob_med, all 5) ===")
    for combo in [["TAM", "poi_normal"], ["TAM", "ob_med"],
                  ["TAM", "poi_normal", "ob_med"],
                  ["TAM", "poi_normal", "dir_hull"],
                  ["TAM", "poi_normal", "ob_med", "dir_hull"]]:
        mask = pd.Series(True, index=df.index)
        for k in combo:
            mask = mask & filters[k]
        sub = df[mask].copy()
        sub["year"] = sub["signal_time_utc"].dt.year
        print(f"\n  {'+'.join(combo)}:")
        for y in sorted(sub["year"].dropna().unique()):
            s = sub[sub["year"] == y]
            cl = s[s["sim_out"].isin(["win", "loss"])]
            n_cl = len(cl)
            wr = (cl["sim_out"] == "win").sum() / n_cl * 100 if n_cl else 0
            total = s["sim_R"].sum()
            print(f"    {int(y)}: n={n_cl:<3} WR={wr:5.1f}% total={total:+5.1f}R")


if __name__ == "__main__":
    main()
