"""etap_112: тестируем комбинации EMA-200 и Hull-6h как trend filter для C2.

BTC 3y.

Варианты:
  - EMA-200 only (baseline = etap_43 original)
  - Hull-6h only
  - EMA-200 AND Hull-6h (оба согласны)
  - EMA-200 OR Hull-6h (любой согласен)
  - Hull-2h-200 (Hull на trigger TF, длинный)
  - Hull-2h AND EMA-200
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
import importlib.util as _ilu
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists(): _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path: _sys.path.insert(0, str(_ROOT))

from pathlib import Path
import numpy as np
import pandas as pd

_E111 = Path(__file__).parent / "etap_111_c2_hull_trend.py"
_spec = _ilu.spec_from_file_location("etap111_core", _E111)
_e111 = _ilu.module_from_spec(_spec); _sys.modules["etap111_core"] = _e111
_spec.loader.exec_module(_e111)

from data_manager import compose_from_base, load_df

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"


def is_pro_ema(t, ema_arr, close_arr):
    direction = t["direction"]
    idx = t["idx"]
    em = float(ema_arr[idx]); cl = float(close_arr[idx])
    if pd.isna(em): return False
    return cl > em if direction == "LONG" else cl < em


def is_pro_hull(t, df_anchor, hull_series, anchor_hours):
    """check_time = c2 close (= trigger.time + 2h)."""
    direction = t["direction"]
    c2_close = t["time"] + pd.Timedelta(hours=2)
    idx_pos = df_anchor.index.searchsorted(c2_close, side="right") - 1
    if idx_pos < 2: return False
    if pd.isna(hull_series.iloc[idx_pos - 2]): return False
    close = float(df_anchor["close"].iloc[idx_pos])
    hv = float(hull_series.iloc[idx_pos - 2])
    return close > hv if direction == "LONG" else close < hv


def main():
    print(f"etap_112: C2 combined trend filters — BTC 3y")
    print()

    df_6h = load_df(SYMBOL, "6h")
    df_2h = load_df(SYMBOL, "2h")
    df_1m = load_df(SYMBOL, "1m")
    if df_6h.empty or df_2h.empty:
        df_1h = load_df(SYMBOL, "1h")
        df_6h = compose_from_base(df_1h, "6h") if df_6h.empty else df_6h
        df_2h = compose_from_base(df_1h, "2h") if df_2h.empty else df_2h

    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_6h = df_6h[df_6h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]

    df_6h["atr14"] = _e111.compute_atr(df_6h, 14)
    df_2h["atr14"] = _e111.compute_atr(df_2h, 14)
    df_2h["ema200"] = df_2h["close"].ewm(span=200, adjust=False).mean()

    hull_6h_78 = _e111.hull_ma(df_6h["close"], length=78)
    hull_2h_200 = _e111.hull_ma(df_2h["close"], length=200)

    sim = _e111.FastSim(df_1m)
    years = (df_6h.index[-1] - df_6h.index[0]).days / 365
    print(f"  years actual: {years:.2f}")

    obs_6h = _e111.collect_obs(df_6h, df_6h["atr14"], "6h")
    fvgs_2h = _e111.collect_fvgs(df_2h, df_2h["atr14"], "2h")
    print(f"  OB-6h: {len(obs_6h)}, FVG-2h: {len(fvgs_2h)}")

    ema_arr = df_2h["ema200"].to_numpy()
    close_2h = df_2h["close"].to_numpy()

    # Define filters
    f_ema = lambda t: is_pro_ema(t, ema_arr, close_2h)
    f_hull6h = lambda t: is_pro_hull(t, df_6h, hull_6h_78, 6)
    f_hull2h = lambda t: is_pro_hull(t, df_2h, hull_2h_200, 2)
    f_ema_AND_hull6h = lambda t: f_ema(t) and f_hull6h(t)
    f_ema_OR_hull6h = lambda t: f_ema(t) or f_hull6h(t)
    f_ema_AND_hull2h = lambda t: f_ema(t) and f_hull2h(t)
    f_ema_OR_hull2h = lambda t: f_ema(t) or f_hull2h(t)
    f_hull6h_AND_hull2h = lambda t: f_hull6h(t) and f_hull2h(t)
    f_all3 = lambda t: f_ema(t) and f_hull6h(t) and f_hull2h(t)
    f_any3 = lambda t: f_ema(t) or f_hull6h(t) or f_hull2h(t)

    variants = [
        ("EMA-200 only (original)", f_ema),
        ("Hull-6h only",            f_hull6h),
        ("Hull-2h-200 only",        f_hull2h),
        ("EMA AND Hull-6h",         f_ema_AND_hull6h),
        ("EMA OR Hull-6h",          f_ema_OR_hull6h),
        ("EMA AND Hull-2h",         f_ema_AND_hull2h),
        ("EMA OR Hull-2h",          f_ema_OR_hull2h),
        ("Hull-6h AND Hull-2h",     f_hull6h_AND_hull2h),
        ("ALL 3 (EMA & H6 & H2)",   f_all3),
        ("ANY 3 (EMA | H6 | H2)",   f_any3),
    ]

    print()
    print(f"  {'Variant':<28} {'setups':>6} {'closed':>6} {'WR':>6} {'PnL':>9} {'bad':>5}  by_year")
    print("  " + "-"*100)
    results = []
    for label, fn in variants:
        setups = _e111.build_c2_setups(obs_6h, fvgs_2h, pro_trend_fn=fn)
        df = _e111.evaluate(setups, sim)
        closed = df[df["outcome"].isin(["win", "loss"])]
        nc = len(closed)
        if nc == 0:
            print(f"  {label:<28}: no closed"); continue
        W = (closed["R"] > 0).sum(); L = (closed["R"] < 0).sum()
        wr = W / nc * 100
        pnl = closed["R"].sum()
        yr = closed.groupby("year")["R"].sum()
        bad = (yr < 0).sum()
        yrs_str = "  ".join(f"{int(y)}:{r:+.0f}" for y, r in yr.sort_index().items())
        print(f"  {label:<28} {len(setups):>6d} {nc:>6d} {wr:>5.1f}% {pnl:>+8.1f}R {bad}/{len(yr)}  {yrs_str}")
        results.append((label, len(setups), nc, wr, pnl, bad, len(yr)))

    print()
    # Sort by PnL
    print("RANKED by PnL:")
    results.sort(key=lambda r: r[4], reverse=True)
    for r in results:
        label, ns, nc, wr, pnl, bad, ny = r
        print(f"  {label:<28} closed={nc:>4d}  WR={wr:5.1f}%  PnL={pnl:+7.1f}R  bad={bad}/{ny}")


if __name__ == "__main__":
    main()
