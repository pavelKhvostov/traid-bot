"""Этап A1: entry_pct × SL formula grid.

Берём 6.3y baseline, для каждой комбинации (entry_pct, sl_variant)
пересчитываем entry/sl/tp и пересимулируем через 1m.

entry_pct: где в FVG ставим entry. 0.3=ближе к c0, 0.5=mid, 0.7=ближе к c2.
  LONG:  entry = fvg.bottom + entry_pct × (fvg.top - fvg.bottom)
  SHORT: entry = fvg.top    - entry_pct × (fvg.top - fvg.bottom)

sl_variant:
  ob_full:  LONG SL = OB.bottom, SHORT SL = OB.top
  ob_inside_15:  SL внутри OB на 15% (как 1.1.1 user)
  ob_inside_50:  SL внутри OB на 50%
  poi_extreme:   LONG SL = POI.bottom (sweep.low),  SHORT SL = sweep.high
  asym:     LONG SL = 0.35 inside, SHORT SL = 0.65 (как 1.1.1 user asym)

Применяем filter_TAM (best из etap_39).
RR: 1.5 и 2.5.
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
    print("[INFO] loading")
    df = pd.read_csv(BACKTEST_CSV)
    feat = pd.read_csv(FEATURES_CSV)
    feat["ts"] = pd.to_datetime(feat["signal_time"], utc=True)
    df_1m = load_df(SYMBOL, "1m")

    df["signal_time_utc"] = df["fvg_c2_time"].apply(parse_utc3)
    df = df.merge(feat[["ts", "asvk_4h", "mh_4h_color", "weekday", "session"]],
                   left_on="signal_time_utc", right_on="ts", how="left")

    # Filter TAM
    df["filter_TAM"] = (
        (df["weekday"] != "Sunday")
        & (df["session"] != "London")
        & (df["asvk_4h"] != "red")
        & (~df["mh_4h_color"].isin(["green", "grey_from_green"]))
    )

    df["fvg_b"], df["fvg_t"] = zip(*df["fvg_zone"].apply(parse_zone))
    df["ob_b"], df["ob_t"] = zip(*df["ob_zone"].apply(parse_zone))
    df["poi_b"], df["poi_t"] = zip(*df["poi_zone"].apply(parse_zone))

    # 1m arrays
    ts_arr = df_1m.index.values
    h_arr = df_1m["high"].to_numpy(dtype=float)
    l_arr = df_1m["low"].to_numpy(dtype=float)

    def simulate(direction, entry, sl, tp, start_time, timeout_days=14):
        # find fill ts.
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
            # check no_entry: did tp or sl hit BEFORE fill?
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
            rr_realized = (tp - entry) / risk
            return "win", rr_realized
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
            rr_realized = (entry - tp) / risk
            return "win", rr_realized

    def compute_setup(row, entry_pct, sl_variant, rr):
        d = row["direction"]
        fb, ft = row["fvg_b"], row["fvg_t"]
        ob_b, ob_t = row["ob_b"], row["ob_t"]
        poi_b, poi_t = row["poi_b"], row["poi_t"]
        if d == "LONG":
            entry = fb + entry_pct * (ft - fb)
            if sl_variant == "ob_full":
                sl = ob_b
            elif sl_variant == "ob_inside_15":
                sl = ob_b + 0.15 * (ob_t - ob_b)
            elif sl_variant == "ob_inside_50":
                sl = ob_b + 0.50 * (ob_t - ob_b)
            elif sl_variant == "poi_extreme":
                sl = poi_b
            elif sl_variant == "asym":
                sl = ob_b + 0.35 * (fb - ob_b)
            else:
                return None
            if sl >= entry:
                return None
            tp = entry + rr * (entry - sl)
        else:
            entry = ft - entry_pct * (ft - fb)
            if sl_variant == "ob_full":
                sl = ob_t
            elif sl_variant == "ob_inside_15":
                sl = ob_t - 0.15 * (ob_t - ob_b)
            elif sl_variant == "ob_inside_50":
                sl = ob_t - 0.50 * (ob_t - ob_b)
            elif sl_variant == "poi_extreme":
                sl = poi_t
            elif sl_variant == "asym":
                sl = ob_t - 0.65 * (ob_t - ft)
            else:
                return None
            if sl <= entry:
                return None
            tp = entry - rr * (sl - entry)
        return entry, sl, tp

    entry_pcts = [0.3, 0.5, 0.7, 0.8]
    sl_variants = ["ob_full", "ob_inside_15", "ob_inside_50", "poi_extreme", "asym"]
    rrs = [1.5, 2.5]

    # Apply filter
    fdf = df[df["filter_TAM"]].copy()
    print(f"[INFO] filtered (filter_TAM): {len(fdf)} setups")

    print(f"\n{'entry':<6} {'sl':<14} {'RR':<5} {'n_cl':<5} {'WR':<7} {'NO_E':<5} {'NOT_F':<6} {'total':<8} {'R/tr':<8}")
    best = None
    for ep in entry_pcts:
        for sv in sl_variants:
            for rr in rrs:
                outcomes = []
                rs = []
                for _, row in fdf.iterrows():
                    setup = compute_setup(row, ep, sv, rr)
                    if setup is None:
                        outcomes.append("invalid")
                        rs.append(0.0)
                        continue
                    entry, sl, tp = setup
                    out, r = simulate(row["direction"], entry, sl, tp,
                                       row["signal_time_utc"])
                    outcomes.append(out)
                    rs.append(r)
                outcomes = pd.Series(outcomes)
                rs = pd.Series(rs)
                closed = outcomes.isin(["win", "loss"])
                n_cl = closed.sum()
                if n_cl == 0:
                    continue
                wr = (outcomes == "win").sum() / n_cl * 100
                no_e = (outcomes == "no_entry").sum()
                not_f = (outcomes == "not_filled").sum()
                total = rs.sum()
                r_tr = total / n_cl
                flag = " ***" if r_tr >= 0.5 else ""
                print(f"{ep:<6} {sv:<14} {rr:<5} {n_cl:<5} {wr:<7.1f} {no_e:<5} {not_f:<6} {total:+7.1f} {r_tr:+7.3f}{flag}")
                if best is None or r_tr > best[6]:
                    best = (ep, sv, rr, n_cl, wr, total, r_tr)

    print(f"\nBest (by R/tr): entry={best[0]}, sl={best[1]}, RR={best[2]} "
          f"→ n={best[3]} WR={best[4]:.1f}% total={best[5]:+.1f}R R/tr={best[6]:+.3f}")


if __name__ == "__main__":
    main()
