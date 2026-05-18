"""etap_117: широкий grid FVG-D/12h cascades.

Не зацикливаемся на B (12h+4h+1h+15m). Тестируем все ~30 разнообразных цепочек:

L1 ∈ {FVG-1d, FVG-12h, RDRB-1d, RDRB-12h}
L2 ∈ {OB-4h, OB-6h, RDRB-4h, RDRB-6h, FVG-4h, FVG-6h, Fractal-4h, Fractal-6h}
L3 ∈ {OB-1h, OB-2h, RDRB-1h, FVG-1h, FVG-2h}
L4 ∈ {FVG-15m, FVG-20m, FVG-30m, OB-15m}

Каждая комбинация прогоняется raw + с EMA-200(2h) filter.
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

from data_manager import compose_from_base, load_df

_E116 = Path(__file__).parent / "etap_116_fvg_d_strategy_explorer.py"
_spec = _ilu.spec_from_file_location("etap116_core", _E116)
_e116 = _ilu.module_from_spec(_spec); _sys.modules["etap116_core"] = _e116
_spec.loader.exec_module(_e116)

detect_generic_4stage = _e116.detect_generic_4stage
evaluate = _e116.evaluate
stats = _e116.stats
filter_ema_2h = _e116.filter_ema_2h
filter_hull_6h = _e116.filter_hull_6h
collect_rdrb_zones = _e116.collect_rdrb_zones
collect_fractal_zones = _e116.collect_fractal_zones
compute_atr = _e116.compute_atr
hull_ma = _e116.hull_ma
_e66 = _e116._e66
_e66.TF_HOURS["20m"] = 20/60
_e66.LIFE_DAYS["20m"] = 0.5
_e66.TF_HOURS["30m"] = 30/60
_e66.LIFE_DAYS["30m"] = 0.75

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
ALLOW_MULTI = 5


def main():
    print("etap_117: широкий grid FVG-D/12h (BTC 6.3y)")
    print()
    print("[INFO] loading data")
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_1m = load_df(SYMBOL, "1m")
    df_15m = compose_from_base(df_1m, "15m")
    df_20m = compose_from_base(df_1m, "20m")
    df_30m = compose_from_base(df_1m, "30m")

    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_4h = df_4h[df_4h.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_6h = df_6h[df_6h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_20m = df_20m[df_20m.index >= cutoff].copy()
    df_30m = df_30m[df_30m.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]

    for tf, df in [("1d", df_1d), ("12h", df_12h), ("6h", df_6h),
                    ("4h", df_4h), ("2h", df_2h), ("1h", df_1h),
                    ("15m", df_15m), ("20m", df_20m), ("30m", df_30m)]:
        df["atr14"] = compute_atr(df, 14)
    df_2h["ema200"] = df_2h["close"].ewm(span=200, adjust=False).mean()

    print("[INFO] collecting block zones")
    Z = {}  # name -> zones list
    Z["FVG-1d"] = _e66.collect_fvgs(df_1d, df_1d["atr14"], "1d")
    Z["FVG-12h"] = _e66.collect_fvgs(df_12h, df_12h["atr14"], "12h")
    Z["RDRB-1d"] = collect_rdrb_zones(df_1d, df_1d["atr14"], "1d")
    Z["RDRB-12h"] = collect_rdrb_zones(df_12h, df_12h["atr14"], "12h")

    Z["OB-4h"] = _e66.collect_obs(df_4h, df_4h["atr14"], "4h")
    Z["OB-6h"] = _e66.collect_obs(df_6h, df_6h["atr14"], "6h")
    Z["RDRB-4h"] = collect_rdrb_zones(df_4h, df_4h["atr14"], "4h")
    Z["RDRB-6h"] = collect_rdrb_zones(df_6h, df_6h["atr14"], "6h")
    Z["FVG-4h"] = _e66.collect_fvgs(df_4h, df_4h["atr14"], "4h")
    Z["FVG-6h"] = _e66.collect_fvgs(df_6h, df_6h["atr14"], "6h")

    Z["OB-1h"] = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
    Z["OB-2h"] = _e66.collect_obs(df_2h, df_2h["atr14"], "2h")
    Z["RDRB-1h"] = collect_rdrb_zones(df_1h, df_1h["atr14"], "1h")
    Z["FVG-1h"] = _e66.collect_fvgs(df_1h, df_1h["atr14"], "1h")
    Z["FVG-2h"] = _e66.collect_fvgs(df_2h, df_2h["atr14"], "2h")

    Z["FVG-15m"] = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")
    Z["FVG-20m"] = _e66.collect_fvgs(df_20m, df_20m["atr14"], "20m")
    Z["FVG-30m"] = _e66.collect_fvgs(df_30m, df_30m["atr14"], "30m")
    Z["OB-15m"] = _e66.collect_obs(df_15m, df_15m["atr14"], "15m")

    for k, v in Z.items():
        print(f"  {k}: {len(v)}")

    # df_top для каждого L1 (для invalidation check)
    df_top_map = {"FVG-1d": df_1d, "FVG-12h": df_12h,
                  "RDRB-1d": df_1d, "RDRB-12h": df_12h}
    tf_map = {"FVG-1d": "1d", "FVG-12h": "12h", "RDRB-1d": "1d", "RDRB-12h": "12h",
              "OB-4h": "4h", "OB-6h": "6h", "RDRB-4h": "4h", "RDRB-6h": "6h",
              "FVG-4h": "4h", "FVG-6h": "6h",
              "OB-1h": "1h", "OB-2h": "2h", "RDRB-1h": "1h",
              "FVG-1h": "1h", "FVG-2h": "2h",
              "FVG-15m": "15m", "FVG-20m": "20m", "FVG-30m": "30m", "OB-15m": "15m"}

    # === Список цепочек ===
    chains = [
        # Group 1: разные L1 (с лучшим L2/L3/L4)
        ("A: FVG-1d + OB-4h + OB-1h + FVG-15m",     "FVG-1d", "OB-4h", "OB-1h", "FVG-15m"),
        ("B: FVG-12h + OB-4h + OB-1h + FVG-15m",    "FVG-12h", "OB-4h", "OB-1h", "FVG-15m"),
        ("R1: RDRB-1d + OB-4h + OB-1h + FVG-15m",   "RDRB-1d", "OB-4h", "OB-1h", "FVG-15m"),
        ("R2: RDRB-12h + OB-4h + OB-1h + FVG-15m",  "RDRB-12h", "OB-4h", "OB-1h", "FVG-15m"),

        # Group 2: разные L2
        ("B-2a: FVG-12h + OB-6h + OB-1h + FVG-15m", "FVG-12h", "OB-6h", "OB-1h", "FVG-15m"),
        ("B-2b: FVG-12h + RDRB-4h + OB-1h + FVG-15m","FVG-12h", "RDRB-4h", "OB-1h", "FVG-15m"),
        ("B-2c: FVG-12h + RDRB-6h + OB-1h + FVG-15m","FVG-12h", "RDRB-6h", "OB-1h", "FVG-15m"),
        ("B-2d: FVG-12h + FVG-4h + OB-1h + FVG-15m","FVG-12h", "FVG-4h", "OB-1h", "FVG-15m"),
        ("B-2e: FVG-12h + FVG-6h + OB-1h + FVG-15m","FVG-12h", "FVG-6h", "OB-1h", "FVG-15m"),

        # Group 3: разные L3
        ("B-3a: FVG-12h + OB-4h + OB-2h + FVG-15m", "FVG-12h", "OB-4h", "OB-2h", "FVG-15m"),
        ("B-3b: FVG-12h + OB-4h + FVG-1h + FVG-15m","FVG-12h", "OB-4h", "FVG-1h", "FVG-15m"),
        ("B-3c: FVG-12h + OB-4h + FVG-2h + FVG-15m","FVG-12h", "OB-4h", "FVG-2h", "FVG-15m"),

        # Group 4: разные L4
        ("K: FVG-12h + OB-4h + OB-1h + FVG-20m",    "FVG-12h", "OB-4h", "OB-1h", "FVG-20m"),
        ("B-4a: FVG-12h + OB-4h + OB-1h + FVG-30m", "FVG-12h", "OB-4h", "OB-1h", "FVG-30m"),

        # Group 5: FVG-1d full path
        ("F: FVG-1d + OB-6h + OB-2h + FVG-15m",     "FVG-1d", "OB-6h", "OB-2h", "FVG-15m"),
        ("J: FVG-1d + OB-4h + OB-1h + FVG-20m",     "FVG-1d", "OB-4h", "OB-1h", "FVG-20m"),
        ("L: FVG-1d + OB-6h + OB-2h + FVG-20m",     "FVG-1d", "OB-6h", "OB-2h", "FVG-20m"),
        ("F-2a: FVG-1d + FVG-4h + OB-1h + FVG-15m", "FVG-1d", "FVG-4h", "OB-1h", "FVG-15m"),
        ("F-2b: FVG-1d + FVG-6h + OB-2h + FVG-15m", "FVG-1d", "FVG-6h", "OB-2h", "FVG-15m"),
        ("F-2c: FVG-1d + RDRB-4h + OB-1h + FVG-15m","FVG-1d", "RDRB-4h", "OB-1h", "FVG-15m"),
        ("F-2d: FVG-1d + OB-4h + FVG-1h + FVG-15m", "FVG-1d", "OB-4h", "FVG-1h", "FVG-15m"),

        # Group 6: FVG-12h с FVG-2h L3
        ("B-3d: FVG-12h + OB-6h + FVG-2h + FVG-15m","FVG-12h", "OB-6h", "FVG-2h", "FVG-15m"),
        ("B-3e: FVG-12h + OB-6h + OB-2h + FVG-15m", "FVG-12h", "OB-6h", "OB-2h", "FVG-15m"),

        # Group 7: 1h L4
        ("B-4b: FVG-12h + OB-4h + FVG-1h + FVG-20m","FVG-12h", "OB-4h", "FVG-1h", "FVG-20m"),

        # Group 8: 20m everywhere
        ("J-4a: FVG-1d + OB-4h + OB-1h + FVG-30m",  "FVG-1d", "OB-4h", "OB-1h", "FVG-30m"),
        ("L-4a: FVG-1d + OB-6h + OB-2h + FVG-30m",  "FVG-1d", "OB-6h", "OB-2h", "FVG-30m"),

        # Group 9: FVG-1d + OB-4h + OB-2h
        ("E: FVG-1d + OB-4h + OB-2h + FVG-15m",     "FVG-1d", "OB-4h", "OB-2h", "FVG-15m"),
        ("E-4a: FVG-1d + OB-4h + OB-2h + FVG-20m",  "FVG-1d", "OB-4h", "OB-2h", "FVG-20m"),
    ]

    # === Run всех 28 цепочек, no_filter + with EMA-2h filter ===
    print()
    print(f"  {'#':>2} {'Chain':<45} {'mode':<10} {'n':>4} {'WR':>5} {'PnL':>8} {'top5':>5} {'bad':>4}")
    print("  " + "-"*100)
    results = []
    for i, (label, l1_name, l2_name, l3_name, l4_name) in enumerate(chains, 1):
        l1_zones = Z.get(l1_name, [])
        l2_zones = Z.get(l2_name, [])
        l3_zones = Z.get(l3_name, [])
        l4_zones = Z.get(l4_name, [])
        if not l1_zones or not l2_zones or not l3_zones or not l4_zones:
            print(f"  {i:>2} {label:<45} SKIP — missing zones")
            continue
        l1_tf = tf_map[l1_name]
        l2_tf = tf_map[l2_name]
        l3_tf = tf_map[l3_name]
        l4_tf = tf_map[l4_name]
        df_top = df_top_map.get(l1_name, df_12h)
        try:
            setups = detect_generic_4stage(l1_zones, l2_zones, l3_zones, l4_zones,
                                              l1_tf, l2_tf, l3_tf, l4_tf, df_top,
                                              allow_multi=ALLOW_MULTI)
        except Exception as e:
            print(f"  {i:>2} {label:<45} ERROR: {e!r}")
            continue
        # no filter
        df, n = evaluate(setups, df_1m)
        s_raw = stats(df, label)
        # with EMA-2h filter
        df_f, _ = evaluate(setups, df_1m, extra_filter=lambda s: filter_ema_2h(s, df_2h))
        s_ema = stats(df_f, label + " +EMA-2h")

        # raw
        print(f"  {i:>2} {label:<45} {'raw':<10} "
              f"{s_raw['closed']:>4d} {s_raw['wr']:>4.1f}% {s_raw['pnl']:>+7.1f}R "
              f"{s_raw['top5_pct']:>4.1f}% {s_raw['bad']}/{s_raw['n_yrs']}")
        # +EMA
        print(f"  {' ':>2} {' ':<45} {'+EMA-2h':<10} "
              f"{s_ema['closed']:>4d} {s_ema['wr']:>4.1f}% {s_ema['pnl']:>+7.1f}R "
              f"{s_ema['top5_pct']:>4.1f}% {s_ema['bad']}/{s_ema['n_yrs']}")
        results.append({"chain": label, "mode": "raw", **s_raw})
        results.append({"chain": label, "mode": "+EMA", **s_ema})

    # === RANKING ===
    print()
    print("=" * 100)
    print("TOP-15 by PnL (with closed >= 15, top5% < 50%, bad <= 1)")
    print("=" * 100)
    valid = [r for r in results if r["closed"] >= 15 and r["top5_pct"] < 50 and r["bad"] <= 1]
    by_pnl = sorted(valid, key=lambda r: r["pnl"], reverse=True)
    for i, r in enumerate(by_pnl[:15], 1):
        print(f"  #{i:>2}  {r['chain']:<45} {r['mode']:<8} "
              f"n={r['closed']:>3d} WR={r['wr']:>4.1f}% "
              f"PnL={r['pnl']:>+7.1f}R top5={r['top5_pct']:>4.1f}% bad={r['bad']}/{r['n_yrs']}")

    print()
    print("=" * 100)
    print("TOP-10 by WR (with closed >= 20 only)")
    print("=" * 100)
    valid_wr = [r for r in results if r["closed"] >= 20]
    by_wr = sorted(valid_wr, key=lambda r: r["wr"], reverse=True)
    for i, r in enumerate(by_wr[:10], 1):
        print(f"  #{i:>2}  {r['chain']:<45} {r['mode']:<8} "
              f"n={r['closed']:>3d} WR={r['wr']:>4.1f}% "
              f"PnL={r['pnl']:>+7.1f}R bad={r['bad']}/{r['n_yrs']}")


if __name__ == "__main__":
    main()
