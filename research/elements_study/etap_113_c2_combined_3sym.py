"""etap_113: C2 combined trend filters на ETH + SOL (3y).
Подтверждение что EMA OR Hull-6h winner работает не только на BTC."""
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

_E112 = Path(__file__).parent / "etap_112_c2_combined_trend.py"
_spec2 = _ilu.spec_from_file_location("etap112_core", _E112)
_e112 = _ilu.module_from_spec(_spec2); _sys.modules["etap112_core"] = _e112
_spec2.loader.exec_module(_e112)

from data_manager import compose_from_base, load_df

DAYS_BACK = 1095


def run_symbol(symbol):
    print(f"\n{'#'*72}\n# {symbol}\n{'#'*72}")
    df_6h = load_df(symbol, "6h")
    df_2h = load_df(symbol, "2h")
    df_1m = load_df(symbol, "1m")
    if df_6h.empty or df_2h.empty:
        df_1h = load_df(symbol, "1h")
        df_6h = compose_from_base(df_1h, "6h") if df_6h.empty else df_6h
        df_2h = compose_from_base(df_1h, "2h") if df_2h.empty else df_2h

    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = max(today - pd.Timedelta(days=DAYS_BACK), df_1m.index[0])
    df_6h = df_6h[df_6h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]

    df_6h["atr14"] = _e111.compute_atr(df_6h, 14)
    df_2h["atr14"] = _e111.compute_atr(df_2h, 14)
    df_2h["ema200"] = df_2h["close"].ewm(span=200, adjust=False).mean()
    hull_6h_78 = _e111.hull_ma(df_6h["close"], length=78)

    sim = _e111.FastSim(df_1m)
    years = (df_6h.index[-1] - df_6h.index[0]).days / 365
    print(f"  years actual: {years:.2f}")

    obs_6h = _e111.collect_obs(df_6h, df_6h["atr14"], "6h")
    fvgs_2h = _e111.collect_fvgs(df_2h, df_2h["atr14"], "2h")
    print(f"  OB-6h: {len(obs_6h)}, FVG-2h: {len(fvgs_2h)}")

    ema_arr = df_2h["ema200"].to_numpy()
    close_2h = df_2h["close"].to_numpy()
    f_ema = lambda t: _e112.is_pro_ema(t, ema_arr, close_2h)
    f_hull6h = lambda t: _e112.is_pro_hull(t, df_6h, hull_6h_78, 6)
    f_ema_OR_hull6h = lambda t: f_ema(t) or f_hull6h(t)
    f_ema_AND_hull6h = lambda t: f_ema(t) and f_hull6h(t)

    variants = [
        ("NO_FILTER",          lambda t: True),
        ("EMA-200 only (orig)", f_ema),
        ("Hull-6h only",       f_hull6h),
        ("EMA OR Hull-6h",   f_ema_OR_hull6h),
        ("EMA AND Hull-6h",    f_ema_AND_hull6h),
    ]

    print()
    print(f"  {'Variant':<22} {'setups':>6} {'closed':>6} {'WR':>6} {'PnL':>9} {'bad':>5}  by_year")
    print("  " + "-"*100)
    results = []
    for label, fn in variants:
        setups = _e111.build_c2_setups(obs_6h, fvgs_2h, pro_trend_fn=fn)
        df = _e111.evaluate(setups, sim)
        closed = df[df["outcome"].isin(["win", "loss"])]
        nc = len(closed)
        if nc == 0:
            print(f"  {label:<22}: no closed"); continue
        W = (closed["R"] > 0).sum(); L = (closed["R"] < 0).sum()
        wr = W / nc * 100
        pnl = closed["R"].sum()
        yr = closed.groupby("year")["R"].sum()
        bad = (yr < 0).sum()
        yrs_str = "  ".join(f"{int(y)}:{r:+.0f}" for y, r in yr.sort_index().items())
        print(f"  {label:<22} {len(setups):>6d} {nc:>6d} {wr:>5.1f}% {pnl:>+8.1f}R {bad}/{len(yr)}  {yrs_str}")
        results.append({"sym": symbol, "label": label, "n": nc, "wr": wr, "pnl": pnl,
                        "bad": bad, "n_yrs": len(yr)})
    return results


def main():
    print("etap_113: C2 EMA vs Hull-6h trend filter — ETH + SOL 3y")
    btc_baseline = {"BTC": "+33.0R EMA / +41.0R OR  (BTC 3y reference)"}
    print(f"  BTC reference: {btc_baseline['BTC']}")
    print()
    all_results = []
    for sym in ["ETHUSDT", "SOLUSDT"]:
        rs = run_symbol(sym)
        all_results.extend(rs)

    # сводка
    print()
    print("=" * 88)
    print("FINAL — EMA OR Hull-6h vs EMA-200 (baseline)")
    print("=" * 88)
    for sym in ["ETHUSDT", "SOLUSDT"]:
        b = next((r for r in all_results if r["sym"] == sym and r["label"] == "EMA-200 only (orig)"), None)
        w = next((r for r in all_results if r["sym"] == sym and "EMA OR Hull-6h" in r["label"]), None)
        if b is None or w is None: continue
        print(f"\n  {sym}:")
        print(f"    Baseline (EMA only):     n={b['n']:>4d}  WR={b['wr']:5.1f}%  PnL={b['pnl']:+7.1f}R  bad={b['bad']}/{b['n_yrs']}")
        print(f"    Winner (EMA OR Hull-6h): n={w['n']:>4d}  WR={w['wr']:5.1f}%  PnL={w['pnl']:+7.1f}R  bad={w['bad']}/{w['n_yrs']}")
        print(f"    Δ:                       n={w['n']-b['n']:+d}  WR={w['wr']-b['wr']:+.1f}pp  PnL={w['pnl']-b['pnl']:+.1f}R")


if __name__ == "__main__":
    main()
