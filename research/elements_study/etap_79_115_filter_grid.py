"""Этап 79: индикаторные фильтры на 1.1.5 B5 single chain strict.

Baseline (из etap_78): WR 45.1%, +114R, n=324, 0 bad/7.

Тестируем те же фильтры что в etap_67 (для 1.1.4):
  - Hull MA (12h L78/L160, 4h L78/L160, 1h L49)
  - Money Hands HA-MF sign (1h, 4h, 12h)
  - ASVK RSI zones (1h, 4h)
  - NY/London sessions
  - Fractal kind (FL/FH)
  - Combos

Каждый фильтр: проверка WR + total + bad-years.
Цель: найти фильтр, повышающий WR до 55+% при сохранении частоты.
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from collections import defaultdict
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
ALLOW_MULTI = 3
PROXIMITY = 1.0
SWEEP_DEPTH = 0.0
N_YEARS = 6.3


def attach_features(setups, hulls, mh_series_by_tf, rsi_zones_by_tf):
    """Mutate setups in-place adding feature columns."""
    for s in setups:
        ts = s["signal_time"]
        d = s["direction"]
        for tf_lbl, ser in hulls.items():
            lbl = _e67.safe_label_at(ser, ts)
            s[f"hull_{tf_lbl}"] = _e67.hull_align(lbl, d)
        for tf, ser in mh_series_by_tf.items():
            # FIX 2026-05-11: side="left"-1 чтобы избежать FORMING bar lookahead
            idx = ser.index.searchsorted(ts, side="left") - 1
            v = ser.iloc[idx] if 0 <= idx < len(ser) else np.nan
            s[f"mh_{tf}"] = _e67.mh_sign_align(v, d)
        for tf, ser in rsi_zones_by_tf.items():
            z = _e67.safe_label_at(ser, ts)
            s[f"rsi_{tf}"] = _e67.rsi_zone_align(z, d)
        h = ts.hour
        s["ny_session"] = "in" if 13 <= h < 21 else "out"
        s["london_session"] = "in" if 7 <= h < 16 else "out"


def eval_filter(setups, rr, df_1m, df_1d, filter_fn=None, only_dom=False):
    rows = []
    for s in setups:
        tup = _e76.build_orders_fractal(s)
        if tup is None: continue
        entry, sl = tup
        if only_dom and not _e66.do_match_aligned(s, entry, df_1d): continue
        if filter_fn is not None and not filter_fn(s): continue
        risk = abs(entry - sl)
        tp = entry + rr * risk if s["direction"] == "LONG" else entry - rr * risk
        outcome, R = _e66.simulate_safe(s, entry, sl, tp, df_1m)
        rows.append({"outcome": outcome, "R": R, "year": s["year"]})
    return pd.DataFrame(rows)


def metrics(df, n_years=N_YEARS):
    if df.empty or "outcome" not in df.columns: return None
    cl = df[df["outcome"].isin(["win", "loss"])]
    if cl.empty: return None
    nc = len(cl); wins = (cl["R"] > 0).sum()
    return {"n": nc, "wr": wins/nc*100, "total": cl["R"].sum(),
             "bad": (cl.groupby("year")["R"].sum() < 0).sum(),
             "n_yrs": len(cl.groupby("year")["R"].sum()),
             "tpy": nc/n_years, "avg_R": cl["R"].sum()/nc}


def main():
    t0 = time.time()
    print("[INFO] load")
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_2h = compose_from_base(df_1h, "2h")
    df_1m = load_df(SYMBOL, "1m")
    df_15m = compose_from_base(df_1m, "15m")

    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_4h = df_4h[df_4h.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]

    for tf, df in [("1d", df_1d), ("12h", df_12h), ("4h", df_4h),
                    ("2h", df_2h), ("1h", df_1h), ("15m", df_15m)]:
        df["atr14"] = _e66.compute_atr(df, 14)

    print("[INFO] compute indicators")
    hulls = {}
    for tf, df, L in [("12h", df_12h, 78), ("12h", df_12h, 160),
                       ("4h", df_4h, 78), ("4h", df_4h, 160),
                       ("1h", df_1h, 49)]:
        h = _e67.hull_ma(df["close"], L)
        hulls[f"{tf}_L{L}"] = _e67.hull_label_series(df["close"], h)

    mh_series = {
        "1h": _e67.money_flow_ha(df_1h),
        "4h": _e67.money_flow_ha(df_4h),
        "12h": _e67.money_flow_ha(df_12h),
    }

    rsi_zones = {}
    for tf, df in [("1h", df_1h), ("4h", df_4h)]:
        e3 = _e67.asvk_adjusted_rsi(df["close"])
        above, below = _e67.asvk_dynamic_levels(e3, lookback=200)
        rsi_zones[tf] = _e67.asvk_zone_label(e3, above, below)

    print("[INFO] detect 1.1.5 B5 strict (single chain)")
    fractals_12h = _e76.collect_fractals_with_sweep(df_12h, df_12h["atr14"], "12h")
    obs_4h = _e66.collect_obs(df_4h, df_4h["atr14"], "4h")
    obs_1h = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
    fvgs_15m = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")

    setups = _e77.detect_strict(fractals_12h, obs_4h, obs_1h, fvgs_15m,
                                  "12h", "4h", "1h", "15m",
                                  allow_multi=ALLOW_MULTI,
                                  proximity_atr=PROXIMITY,
                                  min_sweep_depth_atr=SWEEP_DEPTH)
    print(f"  setups: {len(setups)}")
    attach_features(setups, hulls, mh_series, rsi_zones)

    filters = {
        "baseline (no filter)": None,
        "hull_12h_L78 aligned": lambda s: s["hull_12h_L78"] == "aligned",
        "hull_12h_L160 aligned": lambda s: s["hull_12h_L160"] == "aligned",
        "hull_4h_L78 aligned": lambda s: s["hull_4h_L78"] == "aligned",
        "hull_4h_L160 aligned": lambda s: s["hull_4h_L160"] == "aligned",
        "hull_1h_L49 aligned": lambda s: s["hull_1h_L49"] == "aligned",
        "mh_1h aligned": lambda s: s["mh_1h"] == "aligned",
        "mh_4h aligned": lambda s: s["mh_4h"] == "aligned",
        "mh_12h aligned": lambda s: s["mh_12h"] == "aligned",
        "rsi_1h aligned": lambda s: s["rsi_1h"] == "aligned",
        "rsi_4h aligned": lambda s: s["rsi_4h"] == "aligned",
        "rsi_1h not counter": lambda s: s["rsi_1h"] != "counter",
        "rsi_4h not counter": lambda s: s["rsi_4h"] != "counter",
        "NY session": lambda s: s["ny_session"] == "in",
        "London session": lambda s: s["london_session"] == "in",
        "LONG only (FL)": lambda s: s["direction"] == "LONG",
        "SHORT only (FH)": lambda s: s["direction"] == "SHORT",
        # Combos
        "hull_12h_L78 + mh_12h aligned": lambda s: s["hull_12h_L78"] == "aligned" and s["mh_12h"] == "aligned",
        "hull_4h_L78 + mh_4h aligned": lambda s: s["hull_4h_L78"] == "aligned" and s["mh_4h"] == "aligned",
        "mh_4h + mh_12h aligned": lambda s: s["mh_4h"] == "aligned" and s["mh_12h"] == "aligned",
        "mh_4h aligned + LONG": lambda s: s["mh_4h"] == "aligned" and s["direction"] == "LONG",
        "mh_12h aligned + LONG": lambda s: s["mh_12h"] == "aligned" and s["direction"] == "LONG",
        "hull_12h_L78 aligned + LONG": lambda s: s["hull_12h_L78"] == "aligned" and s["direction"] == "LONG",
        "hull_4h_L160 + mh_12h aligned": lambda s: s["hull_4h_L160"] == "aligned" and s["mh_12h"] == "aligned",
        "mh_1h + mh_4h aligned": lambda s: s["mh_1h"] == "aligned" and s["mh_4h"] == "aligned",
    }

    RR_LIST = [1.8, 2.0, 2.5]

    print(f"\n{'='*98}")
    print(f"FILTER GRID ON 1.1.5 B5 (single chain strict, AM=3, prox=1.0)")
    print(f"{'='*98}")
    print(f"  {'filter':<42} {'RR':<5} {'n':>4} {'tpy':>5} {'WR':>6} {'total':>8} {'avg':>7} {'bad':>5}")

    rows = []
    for fname, ffn in filters.items():
        for rr in RR_LIST:
            df = eval_filter(setups, rr, df_1m, df_1d, ffn, only_dom=False)
            m = metrics(df)
            if not m: continue
            if m["n"] < 20: continue  # too small
            mark = ""
            if m["wr"] > 50 and m["tpy"] >= 20 and m["bad"] <= 1: mark = "*"
            if m["wr"] > 55 and m["tpy"] >= 20 and m["bad"] <= 1: mark = "**"
            print(f"  {fname[:42]:<42} RR={rr:<3} n={m['n']:>3} tpy={m['tpy']:5.1f} "
                  f"WR={m['wr']:5.1f}% total={m['total']:+6.1f}R avg={m['avg_R']:+5.2f}R "
                  f"bad={m['bad']}/{m['n_yrs']} {mark}")
            rows.append({"filter": fname, "rr": rr, **m})

    # Rankings
    print(f"\n\n{'='*98}\nTOP 15 by WR (n>=30, bad<=1):\n{'='*98}")
    by_wr = sorted([r for r in rows if r["n"] >= 30 and r["bad"] <= 1],
                   key=lambda x: x["wr"], reverse=True)[:15]
    for r in by_wr:
        print(f"  {r['filter'][:42]:<42} RR={r['rr']:<3} n={r['n']:>3} tpy={r['tpy']:5.1f} "
              f"WR={r['wr']:5.1f}% total={r['total']:+6.1f}R avg={r['avg_R']:+5.2f}R "
              f"bad={r['bad']}/{r['n_yrs']}")

    print(f"\n--- TOP 15 by avg R/trade (n>=30, bad<=1): ---")
    by_avg = sorted([r for r in rows if r["n"] >= 30 and r["bad"] <= 1],
                    key=lambda x: x["avg_R"], reverse=True)[:15]
    for r in by_avg:
        print(f"  {r['filter'][:42]:<42} RR={r['rr']:<3} n={r['n']:>3} tpy={r['tpy']:5.1f} "
              f"WR={r['wr']:5.1f}% total={r['total']:+6.1f}R avg={r['avg_R']:+5.2f}R "
              f"bad={r['bad']}/{r['n_yrs']}")

    print(f"\n--- TOP 15 by total R (n>=30, bad<=1): ---")
    by_tot = sorted([r for r in rows if r["n"] >= 30 and r["bad"] <= 1],
                    key=lambda x: x["total"], reverse=True)[:15]
    for r in by_tot:
        print(f"  {r['filter'][:42]:<42} RR={r['rr']:<3} n={r['n']:>3} tpy={r['tpy']:5.1f} "
              f"WR={r['wr']:5.1f}% total={r['total']:+6.1f}R avg={r['avg_R']:+5.2f}R "
              f"bad={r['bad']}/{r['n_yrs']}")

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
