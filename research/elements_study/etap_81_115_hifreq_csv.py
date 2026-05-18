"""Этап 81: CSV для 1.1.5 hi-freq (B5 strict + hull_1h_L49 aligned), исправленный фикс lookahead.
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import time
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
import importlib.util

_spec76 = importlib.util.spec_from_file_location(
    "etap76_core", str(_Path(__file__).parent / "etap_76_115_fractal_chains_survey.py"))
_e76 = importlib.util.module_from_spec(_spec76); _spec76.loader.exec_module(_e76)
_spec77 = importlib.util.spec_from_file_location(
    "etap77_core", str(_Path(__file__).parent / "etap_77_115_fractal_tightened.py"))
_e77 = importlib.util.module_from_spec(_spec77); _spec77.loader.exec_module(_e77)
_spec67 = importlib.util.spec_from_file_location(
    "etap67_core", str(_Path(__file__).parent / "etap_67_114_filter_grid_BF.py"))
_e67 = importlib.util.module_from_spec(_spec67); _spec67.loader.exec_module(_e67)
_e66 = _e76._e66

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
RR = 2.0
OUTPUT_CSV = _Path("research/elements_study/output/etap81_1_1_5_hifreq_portfolio.csv")


def main():
    t0 = time.time()
    print("[INFO] load")
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_1m = load_df(SYMBOL, "1m")
    df_15m = compose_from_base(df_1m, "15m")

    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_4h = df_4h[df_4h.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]

    for tf, df in [("1d", df_1d), ("12h", df_12h), ("4h", df_4h),
                    ("1h", df_1h), ("15m", df_15m)]:
        df["atr14"] = _e66.compute_atr(df, 14)

    print("[INFO] compute Hull-1h L49")
    hull_1h = _e67.hull_ma(df_1h["close"], 49)
    hull_lbl = _e67.hull_label_series(df_1h["close"], hull_1h)

    fractals_12h = _e76.collect_fractals_with_sweep(df_12h, df_12h["atr14"], "12h")
    obs_4h = _e66.collect_obs(df_4h, df_4h["atr14"], "4h")
    obs_1h = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
    fvgs_15m = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")

    setups = _e77.detect_strict(fractals_12h, obs_4h, obs_1h, fvgs_15m,
                                  "12h", "4h", "1h", "15m",
                                  allow_multi=3, proximity_atr=1.0,
                                  min_sweep_depth_atr=0.0)

    # Apply hull_1h_L49 aligned filter
    filtered = []
    for s in setups:
        lbl = _e67.safe_label_at(hull_lbl, s["signal_time"])
        if _e67.hull_align(lbl, s["direction"]) == "aligned":
            filtered.append(s)
    print(f"  setups before filter: {len(setups)}, after hull_1h aligned: {len(filtered)}")

    rows = []
    for idx, s in enumerate(sorted(filtered, key=lambda x: x["signal_time"])):
        tup = _e76.build_orders_fractal(s)
        if tup is None: continue
        entry, sl = tup
        risk = abs(entry - sl)
        tp = entry + RR * risk if s["direction"] == "LONG" else entry - RR * risk

        # Simulate with times
        start = s["signal_time"]
        end = start + pd.Timedelta(days=7)
        et64 = np.datetime64(start.tz_localize(None) if start.tz else start)
        ee64 = np.datetime64(end.tz_localize(None) if end.tz else end)
        i0 = np.searchsorted(df_1m.index.values, et64)
        i1 = np.searchsorted(df_1m.index.values, ee64)
        outcome = "no_data"; R = 0.0; et = None; xt = None
        if i1 > i0:
            h = df_1m["high"].values[i0:i1].astype(np.float64)
            l = df_1m["low"].values[i0:i1].astype(np.float64)
            times = df_1m.index.values[i0:i1]
            if s["direction"] == "LONG":
                ent_mask = l <= entry; tp_pre_mask = h >= tp
            else:
                ent_mask = h >= entry; tp_pre_mask = l <= tp
            ent_idxs = np.where(ent_mask)[0]
            tp_pre_idxs = np.where(tp_pre_mask)[0]
            ent_idx = int(ent_idxs[0]) if ent_idxs.size else len(h) + 1
            tp_pre = int(tp_pre_idxs[0]) if tp_pre_idxs.size else len(h) + 1
            if tp_pre < ent_idx:
                outcome = "no_entry"
            elif ent_idx >= len(h):
                outcome = "not_filled"
            else:
                et = pd.Timestamp(times[ent_idx])
                post_h = h[ent_idx:]; post_l = l[ent_idx:]; post_t = times[ent_idx:]
                if s["direction"] == "LONG":
                    sl_m = post_l <= sl; tp_m = post_h >= tp
                else:
                    sl_m = post_h >= sl; tp_m = post_l <= tp
                sl_first = int(np.argmax(sl_m)) if sl_m.any() else -1
                tp_first = int(np.argmax(tp_m)) if tp_m.any() else -1
                if sl_first == -1 and tp_first == -1: outcome = "open"
                elif sl_first == -1: outcome = "win"; R = RR; xt = pd.Timestamp(post_t[tp_first])
                elif tp_first == -1: outcome = "loss"; R = -1.0; xt = pd.Timestamp(post_t[sl_first])
                elif tp_first < sl_first: outcome = "win"; R = RR; xt = pd.Timestamp(post_t[tp_first])
                else: outcome = "loss"; R = -1.0; xt = pd.Timestamp(post_t[sl_first])

        rows.append({
            "idx": idx,
            "signal_time": s["signal_time"], "year": s["year"],
            "direction": s["direction"],
            "fractal_kind": s["fractal_kind"],
            "sweep_extreme": round(s["sweep_extreme"], 2),
            "fvg_b": round(s["fvg_b"], 2), "fvg_t": round(s["fvg_t"], 2),
            "obh_b": round(s["obh_b"], 2), "obh_t": round(s["obh_t"], 2),
            "entry": round(entry, 2), "sl": round(sl, 2), "tp": round(tp, 2),
            "risk_abs": round(risk, 2),
            "risk_pct": round(risk/entry*100, 3),
            "outcome": outcome, "R": round(R, 3),
            "entry_time": et, "exit_time": xt,
        })

    df_out = pd.DataFrame(rows)
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"[INFO] CSV saved: {OUTPUT_CSV}")

    # Summary
    print(f"\n{'='*80}\n1.1.5 HI-FREQ FINAL (B5 strict + hull_1h_L49 aligned, RR={RR})")
    print(f"{'='*80}")
    print(f"Total rows: {len(df_out)}")
    for outc, n in df_out["outcome"].value_counts().items():
        print(f"  {outc:<22} {n:>4} ({n/len(df_out)*100:5.1f}%)")

    closed = df_out[df_out["outcome"].isin(["win", "loss"])]
    if len(closed):
        wins = (closed["outcome"] == "win").sum()
        wr = wins/len(closed)*100
        tot = closed["R"].sum()
        avg = closed["R"].mean()
        print(f"\n  closed: {len(closed)}")
        print(f"  WR: {wr:.1f}%")
        print(f"  total R: {tot:+.2f}")
        print(f"  avg R/trade: {avg:+.3f}")

        print(f"\n  Year-by-year:")
        for yr in sorted(closed["year"].unique()):
            yc = closed[closed["year"] == yr]
            yw = (yc["outcome"] == "win").sum()
            print(f"    {yr}: n={len(yc):>3} WR={yw/len(yc)*100:5.1f}% total={yc['R'].sum():+6.1f}R")

        print(f"\n  By direction:")
        for d in ["LONG", "SHORT"]:
            dc = closed[closed["direction"] == d]
            if len(dc):
                dw = (dc["outcome"] == "win").sum()
                print(f"    {d:<6} n={len(dc):>3} WR={dw/len(dc)*100:5.1f}% "
                      f"total={dc['R'].sum():+6.1f}R")

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
